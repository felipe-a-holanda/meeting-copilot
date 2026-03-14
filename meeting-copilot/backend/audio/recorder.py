"""AudioRecorder: captures mic + system audio via PulseAudio/ffmpeg and feeds the pipeline."""
from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


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


class AudioRecorder:
    """Captures mic + system audio via PulseAudio/ffmpeg and feeds the pipeline."""

    def __init__(self, pipeline=None, config=None):
        self._pipeline = pipeline
        self._config = config
        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._is_recording: bool = False

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

    @property
    def is_recording(self) -> bool:
        return self._is_recording
