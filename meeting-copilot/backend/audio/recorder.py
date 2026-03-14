"""AudioRecorder: captures mic + system audio via PulseAudio/ffmpeg and feeds the pipeline."""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

CHUNK_SIZE = 4096
DEFAULT_MIC_VOLUME = 2.0


@dataclass
class AudioDevice:
    """A PulseAudio source or sink."""

    name: str
    description: str


@dataclass
class DeviceDefaults:
    """Default PulseAudio source, sink, and derived monitor source."""

    source: str = ""
    sink: str = ""
    monitor: str = ""


@dataclass
class DeviceList:
    """Result of device discovery."""

    sources: list[AudioDevice] = field(default_factory=list)
    sinks: list[AudioDevice] = field(default_factory=list)
    defaults: DeviceDefaults = field(default_factory=DeviceDefaults)


@dataclass
class DependencyStatus:
    """Result of dependency check."""

    pactl_available: bool = False
    ffmpeg_available: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def all_available(self) -> bool:
        return self.pactl_available and self.ffmpeg_available


@dataclass
class RecordingStats:
    """Stats collected during / after a recording session."""

    duration_seconds: float = 0.0
    chunks_processed: int = 0
    bytes_read: int = 0
    is_recording: bool = False
    file_path: str | None = None   # meeting directory when saving, else None
    audio_files: list[str] = field(default_factory=list)  # WAV file paths


class AudioRecorder:
    """Captures mic + system audio via PulseAudio/ffmpeg and feeds the pipeline.

    Two separate ffmpeg processes are used — one for the mic source (speaker_label="Me")
    and one for the system monitor source (speaker_label="Them").  This gives deterministic
    speaker attribution at zero ML cost, replacing pyannote diarization.
    """

    def __init__(self, pipeline=None, config=None, recordings_dir: str = "./recordings"):
        self._pipeline = pipeline
        self._config = config
        self._recordings_dir = recordings_dir
        # Separate processes and reader tasks for each audio stream
        self._mic_process: asyncio.subprocess.Process | None = None
        self._monitor_process: asyncio.subprocess.Process | None = None
        self._mic_reader_task: asyncio.Task | None = None
        self._monitor_reader_task: asyncio.Task | None = None
        self._is_recording: bool = False
        self._start_time: float | None = None
        self._chunks_processed: int = 0
        self._bytes_read: int = 0
        self._mic_source: str = ""
        self._monitor_source: str = ""
        self._meeting_dir: str | None = None
        self._timestamp: str = ""
        self._audio_files: list[str] = []
        self._title: str = ""

    @staticmethod
    async def check_dependencies() -> DependencyStatus:
        """Verify that pactl and ffmpeg are available on PATH."""
        status = DependencyStatus()

        status.pactl_available = shutil.which("pactl") is not None
        status.ffmpeg_available = shutil.which("ffmpeg") is not None

        if not status.pactl_available:
            status.errors.append(
                "pactl not found. Install pulseaudio-utils: "
                "sudo apt install pulseaudio-utils"
            )
        if not status.ffmpeg_available:
            status.errors.append(
                "ffmpeg not found. Install ffmpeg: "
                "sudo apt install ffmpeg"
            )

        return status

    @staticmethod
    def _parse_device_list(output: str) -> list[AudioDevice]:
        """Parse `pactl list sources/sinks short` output into AudioDevice list.

        Each line has tab-separated fields:
            index  name  driver  sample_spec  state
        """
        devices: list[AudioDevice] = []
        for line in output.strip().splitlines():
            if not line.strip():
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                name = parts[1].strip()
                # Use the name as description too; full descriptions
                # would need `pactl list sources` (verbose), but short
                # format is faster and more reliable.
                devices.append(AudioDevice(name=name, description=name))
        return devices

    @staticmethod
    async def _run_pactl(*args: str) -> str:
        """Run a pactl command and return stdout, or raise RuntimeError."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "pactl",
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
        except FileNotFoundError:
            raise RuntimeError("pactl is not installed or not on PATH")

        if proc.returncode != 0:
            err = stderr.decode().strip() if stderr else "unknown error"
            raise RuntimeError(f"pactl {' '.join(args)} failed: {err}")

        return stdout.decode()

    async def list_devices(self) -> DeviceList:
        """Query pactl for available sources and sinks, plus defaults."""
        sources_output = await self._run_pactl("list", "sources", "short")
        sinks_output = await self._run_pactl("list", "sinks", "short")

        sources = self._parse_device_list(sources_output)
        sinks = self._parse_device_list(sinks_output)
        defaults = await self.get_defaults()

        return DeviceList(sources=sources, sinks=sinks, defaults=defaults)

    async def get_defaults(self) -> DeviceDefaults:
        """Get default source, sink, and derived monitor source name."""
        defaults = DeviceDefaults()

        try:
            source_output = await self._run_pactl("get-default-source")
            defaults.source = source_output.strip()
        except RuntimeError as exc:
            logger.warning("Could not get default source: %s", exc)

        try:
            sink_output = await self._run_pactl("get-default-sink")
            defaults.sink = sink_output.strip()
        except RuntimeError as exc:
            logger.warning("Could not get default sink: %s", exc)

        # Derive monitor source from default sink
        if defaults.sink:
            defaults.monitor = f"{defaults.sink}.monitor"

        return defaults

    # ------------------------------------------------------------------
    # ffmpeg command builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_stream_cmd(
        source: str,
        file_path: str | None = None,
    ) -> list[str]:
        """Return the ffmpeg argument list for a single PulseAudio source stream.

        Outputs raw 16-kHz mono s16le PCM to pipe:1.  When *file_path* is provided,
        the command also writes a PCM WAV file as a second output.
        """
        if file_path:
            return [
                "ffmpeg",
                "-f", "pulse", "-i", source,
                "-map", "0:a", "-ar", "16000", "-ac", "1", "-f", "s16le", "pipe:1",
                "-map", "0:a", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", file_path,
            ]
        return [
            "ffmpeg",
            "-f", "pulse", "-i", source,
            "-ar", "16000",
            "-ac", "1",
            "-f", "s16le",
            "pipe:1",
        ]

    @staticmethod
    def _make_recording_path(recordings_dir: str, timestamp: str) -> tuple[Path, str, str]:
        """Create the dated meeting directory; return (meeting_dir, mic_filename, monitor_filename)."""
        date_str = timestamp[:8]  # YYYYMMDD
        meeting_dir = Path(recordings_dir) / date_str / f"meeting_{timestamp}"
        meeting_dir.mkdir(parents=True, exist_ok=True)
        mic_filename = f"meeting_{timestamp}_mic.wav"
        monitor_filename = f"meeting_{timestamp}_monitor.wav"
        return meeting_dir, mic_filename, monitor_filename

    @staticmethod
    def _write_metadata(
        meeting_dir: Path,
        title: str,
        timestamp: str,
        audio_files: list[str],
    ) -> None:
        """Write a JSON metadata sidecar file."""
        metadata_file = meeting_dir / f"meeting_{timestamp}_metadata.json"
        date_str = timestamp[:8]
        metadata = {
            "title": title,
            "timestamp": timestamp,
            "date": date_str,
            "audio_files": audio_files,
            "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "local_recording",
        }
        metadata_file.write_text(json.dumps(metadata, indent=2))

    # ------------------------------------------------------------------
    # Recording lifecycle
    # ------------------------------------------------------------------

    async def start(
        self,
        mic_source: str | None = None,
        monitor_source: str | None = None,
        mic_volume: float = DEFAULT_MIC_VOLUME,  # kept for API compatibility; not used in stream cmd
        save_to_file: bool = False,
        title: str = "",
    ) -> None:
        """Launch separate ffmpeg processes for mic and monitor streams.

        *mic_source* and *monitor_source* default to ``None`` which means
        auto-detect via :meth:`get_defaults`.  Pass an explicit empty string
        ``""`` for *monitor_source* to force mic-only mode.  When the
        auto-detected monitor is empty the recorder also falls back to
        mic-only mode.

        When *save_to_file* is ``True``, each ffmpeg process writes a separate
        WAV file under ``recordings_dir/<YYYYMMDD>/meeting_<timestamp>/`` in
        addition to streaming PCM to the pipeline.  A JSON metadata sidecar
        is written when recording stops.
        """
        if self._is_recording:
            raise RuntimeError("Recording is already in progress")

        # Auto-detect only for params that were not explicitly provided
        if mic_source is None or monitor_source is None:
            defaults = await self.get_defaults()
            if mic_source is None:
                mic_source = defaults.source
            if monitor_source is None:
                monitor_source = defaults.monitor

        if not mic_source:
            raise RuntimeError("No microphone source available")

        # Prepare optional WAV file paths
        mic_file_path: str | None = None
        monitor_file_path: str | None = None
        meeting_dir_path: str | None = None
        recording_timestamp: str = ""

        if save_to_file:
            recording_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            meeting_dir, mic_filename, monitor_filename = self._make_recording_path(
                self._recordings_dir, recording_timestamp
            )
            mic_file_path = str(meeting_dir / mic_filename)
            monitor_file_path = str(meeting_dir / monitor_filename) if monitor_source else None
            meeting_dir_path = str(meeting_dir)
            logger.info("WAV output: mic=%s monitor=%s", mic_file_path, monitor_file_path)

        # Launch mic process (speaker_label="Me")
        mic_cmd = self._build_stream_cmd(mic_source, mic_file_path)
        logger.info("Starting mic ffmpeg: source=%s", mic_source)
        self._mic_process = await asyncio.create_subprocess_exec(
            *mic_cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Launch monitor process (speaker_label="Them") if available
        if monitor_source:
            monitor_cmd = self._build_stream_cmd(monitor_source, monitor_file_path)
            logger.info("Starting monitor ffmpeg: source=%s", monitor_source)
            self._monitor_process = await asyncio.create_subprocess_exec(
                *monitor_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

        self._mic_source = mic_source
        self._monitor_source = monitor_source
        self._is_recording = True
        self._start_time = time.monotonic()
        self._chunks_processed = 0
        self._bytes_read = 0
        self._meeting_dir = meeting_dir_path
        self._timestamp = recording_timestamp
        self._audio_files = [p for p in [mic_file_path, monitor_file_path] if p is not None]
        self._title = title

        self._mic_reader_task = asyncio.create_task(
            self._reader_loop(self._mic_process, "Me")
        )
        if self._monitor_process is not None:
            self._monitor_reader_task = asyncio.create_task(
                self._reader_loop(self._monitor_process, "Them")
            )

    async def stop(self) -> RecordingStats:
        """Stop both ffmpeg processes and return recording stats.

        Sends SIGINT first for graceful shutdown, then SIGKILL after 5 s per process.
        """
        if not self._is_recording:
            raise RuntimeError("Not currently recording")

        # Graceful shutdown for each process
        if self._mic_process is not None:
            await self._stop_process(self._mic_process)
        if self._monitor_process is not None:
            await self._stop_process(self._monitor_process)

        # Cancel reader tasks after ffmpeg has exited
        for task in (self._mic_reader_task, self._monitor_reader_task):
            if task is not None and not task.done():
                task.cancel()
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=1.0)
                except (asyncio.CancelledError, asyncio.TimeoutError):
                    pass

        self._mic_reader_task = None
        self._monitor_reader_task = None

        # Flush any buffered audio in the pipeline
        if self._pipeline is not None:
            try:
                await self._pipeline.reset()
            except Exception as exc:
                logger.error("Pipeline reset error: %s", exc)

        duration = (
            time.monotonic() - self._start_time
            if self._start_time is not None
            else 0.0
        )

        # Write metadata sidecar if we were saving to file
        if self._meeting_dir and self._audio_files:
            try:
                meeting_dir = Path(self._meeting_dir)
                self._write_metadata(
                    meeting_dir,
                    self._title,
                    self._timestamp,
                    [Path(f).name for f in self._audio_files],
                )
                logger.info("Metadata written for %s", self._meeting_dir)
            except Exception as exc:
                logger.error("Failed to write recording metadata: %s", exc)

        stats = RecordingStats(
            duration_seconds=duration,
            chunks_processed=self._chunks_processed,
            bytes_read=self._bytes_read,
            is_recording=False,
            file_path=self._meeting_dir,
            audio_files=list(self._audio_files),
        )

        self._is_recording = False
        self._mic_process = None
        self._monitor_process = None
        self._start_time = None
        self._meeting_dir = None
        self._timestamp = ""
        self._audio_files = []
        self._title = ""

        logger.info(
            "Recording stopped — duration=%.1f s chunks=%d bytes=%d",
            duration,
            stats.chunks_processed,
            stats.bytes_read,
        )
        return stats

    async def _stop_process(self, proc: asyncio.subprocess.Process) -> None:
        """Send SIGINT to *proc*, wait up to 5 s, then SIGKILL if needed."""
        try:
            proc.send_signal(signal.SIGINT)
        except ProcessLookupError:
            pass  # Already exited

        try:
            await asyncio.wait_for(proc.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("ffmpeg did not exit within 5 s — sending SIGKILL")
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()

    # ------------------------------------------------------------------
    # Reader loop
    # ------------------------------------------------------------------

    async def _reader_loop(
        self, process: asyncio.subprocess.Process, speaker_label: str
    ) -> None:
        """Read PCM chunks from ffmpeg stdout and forward them to the pipeline."""
        assert process.stdout is not None

        try:
            while True:
                chunk = await process.stdout.read(CHUNK_SIZE)
                if not chunk:
                    logger.info("Reader loop (%s): EOF from ffmpeg stdout", speaker_label)
                    break
                self._chunks_processed += 1
                self._bytes_read += len(chunk)
                if self._pipeline is not None:
                    try:
                        await self._pipeline.process_audio_chunk(chunk, speaker_label=speaker_label)
                    except Exception as exc:
                        logger.error(
                            "Pipeline error processing chunk (%s): %s", speaker_label, exc
                        )
        except asyncio.CancelledError:
            logger.debug("Reader loop (%s) cancelled", speaker_label)
            raise
        except Exception as exc:
            logger.error("Reader loop (%s) unexpected error: %s", speaker_label, exc)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_recording(self) -> bool:
        return self._is_recording

    @property
    def recording_stats(self) -> RecordingStats:
        """Current stats snapshot (safe to call while recording)."""
        duration = (
            time.monotonic() - self._start_time
            if self._start_time is not None
            else 0.0
        )
        return RecordingStats(
            duration_seconds=duration,
            chunks_processed=self._chunks_processed,
            bytes_read=self._bytes_read,
            is_recording=self._is_recording,
            file_path=self._meeting_dir,
            audio_files=list(self._audio_files),
        )
