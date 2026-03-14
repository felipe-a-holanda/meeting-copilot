"""Tests for AudioRecorder device discovery (Task 1.1)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

from backend.audio.recorder import AudioRecorder, DeviceDefaults, DeviceList


# --- Fixtures ---

PACTL_SOURCES_SHORT = (
    "0\talsa_input.pci-0000_00_1f.3.analog-stereo\tmodule-alsa-card.c\ts16le 2ch 44100Hz\tIDLE\n"
    "1\talsa_output.pci-0000_00_1f.3.analog-stereo.monitor\tmodule-alsa-card.c\ts16le 2ch 44100Hz\tSUSPENDED\n"
)

PACTL_SINKS_SHORT = (
    "0\talsa_output.pci-0000_00_1f.3.analog-stereo\tmodule-alsa-card.c\ts16le 2ch 44100Hz\tSUSPENDED\n"
)


def _make_process_mock(stdout: str = "", stderr: str = "", returncode: int = 0):
    """Create a mock asyncio subprocess."""
    proc = AsyncMock()
    proc.communicate.return_value = (stdout.encode(), stderr.encode())
    proc.returncode = returncode
    return proc


# --- check_dependencies ---


class TestCheckDependencies:
    @pytest.mark.asyncio
    async def test_all_available(self):
        with patch("backend.audio.recorder.shutil.which", return_value="/usr/bin/tool"):
            status = await AudioRecorder.check_dependencies()
        assert status.pactl_available is True
        assert status.ffmpeg_available is True
        assert status.all_available is True
        assert status.errors == []

    @pytest.mark.asyncio
    async def test_pactl_missing(self):
        def fake_which(name):
            return None if name == "pactl" else "/usr/bin/ffmpeg"

        with patch("backend.audio.recorder.shutil.which", side_effect=fake_which):
            status = await AudioRecorder.check_dependencies()
        assert status.pactl_available is False
        assert status.ffmpeg_available is True
        assert status.all_available is False
        assert len(status.errors) == 1
        assert "pactl" in status.errors[0]

    @pytest.mark.asyncio
    async def test_ffmpeg_missing(self):
        def fake_which(name):
            return "/usr/bin/pactl" if name == "pactl" else None

        with patch("backend.audio.recorder.shutil.which", side_effect=fake_which):
            status = await AudioRecorder.check_dependencies()
        assert status.pactl_available is True
        assert status.ffmpeg_available is False
        assert status.all_available is False
        assert len(status.errors) == 1
        assert "ffmpeg" in status.errors[0]

    @pytest.mark.asyncio
    async def test_both_missing(self):
        with patch("backend.audio.recorder.shutil.which", return_value=None):
            status = await AudioRecorder.check_dependencies()
        assert status.all_available is False
        assert len(status.errors) == 2


# --- _parse_device_list ---


class TestParseDeviceList:
    def test_parse_sources(self):
        devices = AudioRecorder._parse_device_list(PACTL_SOURCES_SHORT)
        assert len(devices) == 2
        assert devices[0].name == "alsa_input.pci-0000_00_1f.3.analog-stereo"
        assert devices[1].name == "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor"

    def test_parse_sinks(self):
        devices = AudioRecorder._parse_device_list(PACTL_SINKS_SHORT)
        assert len(devices) == 1
        assert devices[0].name == "alsa_output.pci-0000_00_1f.3.analog-stereo"

    def test_empty_output(self):
        devices = AudioRecorder._parse_device_list("")
        assert devices == []

    def test_whitespace_only(self):
        devices = AudioRecorder._parse_device_list("  \n  \n")
        assert devices == []


# --- list_devices ---


class TestListDevices:
    @pytest.mark.asyncio
    async def test_list_devices(self):
        recorder = AudioRecorder()

        async def fake_run_pactl(*args):
            cmd = " ".join(args)
            if "sources" in cmd:
                return PACTL_SOURCES_SHORT
            elif "sinks" in cmd:
                return PACTL_SINKS_SHORT
            elif "get-default-source" in cmd:
                return "alsa_input.pci-0000_00_1f.3.analog-stereo\n"
            elif "get-default-sink" in cmd:
                return "alsa_output.pci-0000_00_1f.3.analog-stereo\n"
            return ""

        with patch.object(AudioRecorder, "_run_pactl", side_effect=fake_run_pactl):
            result = await recorder.list_devices()

        assert len(result.sources) == 2
        assert len(result.sinks) == 1
        assert result.defaults.source == "alsa_input.pci-0000_00_1f.3.analog-stereo"
        assert result.defaults.sink == "alsa_output.pci-0000_00_1f.3.analog-stereo"
        assert result.defaults.monitor == "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor"

    @pytest.mark.asyncio
    async def test_list_devices_empty(self):
        recorder = AudioRecorder()

        async def fake_run_pactl(*args):
            cmd = " ".join(args)
            if "sources" in cmd or "sinks" in cmd:
                return ""
            elif "get-default-source" in cmd:
                return "\n"
            elif "get-default-sink" in cmd:
                return "\n"
            return ""

        with patch.object(AudioRecorder, "_run_pactl", side_effect=fake_run_pactl):
            result = await recorder.list_devices()

        assert result.sources == []
        assert result.sinks == []

    @pytest.mark.asyncio
    async def test_pactl_not_installed(self):
        recorder = AudioRecorder()

        with patch.object(
            AudioRecorder,
            "_run_pactl",
            side_effect=RuntimeError("pactl is not installed or not on PATH"),
        ):
            with pytest.raises(RuntimeError, match="pactl"):
                await recorder.list_devices()


# --- get_defaults ---


class TestGetDefaults:
    @pytest.mark.asyncio
    async def test_get_defaults(self):
        recorder = AudioRecorder()

        async def fake_run_pactl(*args):
            if "get-default-source" in args:
                return "alsa_input.pci-0000_00_1f.3.analog-stereo\n"
            elif "get-default-sink" in args:
                return "alsa_output.pci-0000_00_1f.3.analog-stereo\n"
            return ""

        with patch.object(AudioRecorder, "_run_pactl", side_effect=fake_run_pactl):
            defaults = await recorder.get_defaults()

        assert defaults.source == "alsa_input.pci-0000_00_1f.3.analog-stereo"
        assert defaults.sink == "alsa_output.pci-0000_00_1f.3.analog-stereo"
        assert defaults.monitor == "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor"

    @pytest.mark.asyncio
    async def test_no_monitor_when_no_sink(self):
        recorder = AudioRecorder()

        async def fake_run_pactl(*args):
            if "get-default-source" in args:
                return "some-source\n"
            elif "get-default-sink" in args:
                raise RuntimeError("no sink configured")
            return ""

        with patch.object(AudioRecorder, "_run_pactl", side_effect=fake_run_pactl):
            defaults = await recorder.get_defaults()

        assert defaults.source == "some-source"
        assert defaults.sink == ""
        assert defaults.monitor == ""

    @pytest.mark.asyncio
    async def test_both_defaults_fail(self):
        recorder = AudioRecorder()

        with patch.object(
            AudioRecorder,
            "_run_pactl",
            side_effect=RuntimeError("pactl failed"),
        ):
            defaults = await recorder.get_defaults()

        assert defaults.source == ""
        assert defaults.sink == ""
        assert defaults.monitor == ""


# --- _run_pactl ---


class TestRunPactl:
    @pytest.mark.asyncio
    async def test_success(self):
        proc_mock = _make_process_mock(stdout="output\n")
        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            result = await AudioRecorder._run_pactl("list", "sources", "short")
        assert result == "output\n"

    @pytest.mark.asyncio
    async def test_nonzero_exit(self):
        proc_mock = _make_process_mock(stderr="connection refused", returncode=1)
        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            with pytest.raises(RuntimeError, match="failed"):
                await AudioRecorder._run_pactl("list", "sources", "short")

    @pytest.mark.asyncio
    async def test_not_installed(self):
        with patch(
            "asyncio.create_subprocess_exec",
            side_effect=FileNotFoundError("No such file"),
        ):
            with pytest.raises(RuntimeError, match="not installed"):
                await AudioRecorder._run_pactl("list", "sources", "short")
