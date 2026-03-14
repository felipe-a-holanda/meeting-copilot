"""AudioRecorder: captures mic + system audio via PulseAudio/ffmpeg and feeds the pipeline."""
from __future__ import annotations

import asyncio
import logging
import shutil
import signal
import time
from dataclasses import dataclass, field

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


class AudioRecorder:
    """Captures mic + system audio via PulseAudio/ffmpeg and feeds the pipeline."""

    def __init__(self, pipeline=None, config=None):
        self._pipeline = pipeline
        self._config = config
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._is_recording: bool = False
        self._start_time: float | None = None
        self._chunks_processed: int = 0
        self._bytes_read: int = 0
        self._mic_source: str = ""
        self._monitor_source: str = ""

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
    # ffmpeg command builders
    # ------------------------------------------------------------------

    @staticmethod
    def _build_ffmpeg_cmd(
        mic_source: str,
        monitor_source: str,
        mic_volume: float,
    ) -> list[str]:
        """Return the ffmpeg argument list for dual (mic + monitor) capture."""
        filter_complex = (
            f"[0:a]volume={mic_volume}[mic];"
            "[1:a][mic]amix=inputs=2:duration=longest:normalize=0"
        )
        return [
            "ffmpeg",
            "-f", "pulse", "-i", mic_source,
            "-f", "pulse", "-i", monitor_source,
            "-filter_complex", filter_complex,
            "-ar", "16000",
            "-ac", "1",
            "-f", "s16le",
            "pipe:1",
        ]

    @staticmethod
    def _build_ffmpeg_cmd_mic_only(mic_source: str) -> list[str]:
        """Return the ffmpeg argument list for mic-only capture."""
        return [
            "ffmpeg",
            "-f", "pulse", "-i", mic_source,
            "-ar", "16000",
            "-ac", "1",
            "-f", "s16le",
            "pipe:1",
        ]

    # ------------------------------------------------------------------
    # Recording lifecycle
    # ------------------------------------------------------------------

    async def start(
        self,
        mic_source: str | None = None,
        monitor_source: str | None = None,
        mic_volume: float = DEFAULT_MIC_VOLUME,
    ) -> None:
        """Launch ffmpeg and begin recording.

        *mic_source* and *monitor_source* default to ``None`` which means
        auto-detect via :meth:`get_defaults`.  Pass an explicit empty string
        ``""`` for *monitor_source* to force mic-only mode.  When the
        auto-detected monitor is empty the recorder also falls back to
        mic-only mode.
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

        if monitor_source:
            cmd = self._build_ffmpeg_cmd(mic_source, monitor_source, mic_volume)
            logger.info(
                "Starting ffmpeg with mic=%s monitor=%s volume=%.1f",
                mic_source,
                monitor_source,
                mic_volume,
            )
        else:
            cmd = self._build_ffmpeg_cmd_mic_only(mic_source)
            logger.info(
                "Starting ffmpeg mic-only (no monitor source) mic=%s", mic_source
            )

        self._process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        self._mic_source = mic_source
        self._monitor_source = monitor_source
        self._is_recording = True
        self._start_time = time.monotonic()
        self._chunks_processed = 0
        self._bytes_read = 0

        # Reader loop is wired up in Task 1.3; placeholder stored here
        self._reader_task = None

    async def stop(self) -> RecordingStats:
        """Stop the ffmpeg process and return recording stats.

        Sends SIGINT first for graceful shutdown, then SIGKILL after 5 s.
        """
        if not self._is_recording or self._process is None:
            raise RuntimeError("Not currently recording")

        # Cancel reader task (Task 1.3 concern, but handle if present)
        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._reader_task), timeout=1.0
                )
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            self._reader_task = None

        # Graceful shutdown
        try:
            self._process.send_signal(signal.SIGINT)
        except ProcessLookupError:
            pass  # Already exited

        try:
            await asyncio.wait_for(self._process.wait(), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("ffmpeg did not exit within 5 s — sending SIGKILL")
            try:
                self._process.kill()
            except ProcessLookupError:
                pass
            await self._process.wait()

        duration = (
            time.monotonic() - self._start_time
            if self._start_time is not None
            else 0.0
        )

        stats = RecordingStats(
            duration_seconds=duration,
            chunks_processed=self._chunks_processed,
            bytes_read=self._bytes_read,
            is_recording=False,
        )

        self._is_recording = False
        self._process = None
        self._start_time = None

        logger.info(
            "Recording stopped — duration=%.1f s chunks=%d bytes=%d",
            duration,
            stats.chunks_processed,
            stats.bytes_read,
        )
        return stats

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
        )
