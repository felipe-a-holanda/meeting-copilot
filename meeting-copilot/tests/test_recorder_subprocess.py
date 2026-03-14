"""Tests for AudioRecorder ffmpeg subprocess management (Task 1.2)."""
from __future__ import annotations

import asyncio
import signal
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from backend.audio.recorder import (
    AudioRecorder,
    DeviceDefaults,
    RecordingStats,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_process_mock(returncode: int = 0):
    """Return a mock that looks like asyncio.subprocess.Process."""
    proc = MagicMock()
    proc.stdout = AsyncMock()
    proc.stderr = AsyncMock()
    proc.returncode = returncode
    proc.wait = AsyncMock(return_value=returncode)
    proc.send_signal = MagicMock()
    proc.kill = MagicMock()
    return proc


DEFAULT_DEFAULTS = DeviceDefaults(
    source="alsa_input.pci.analog-stereo",
    sink="alsa_output.pci.analog-stereo",
    monitor="alsa_output.pci.analog-stereo.monitor",
)

NO_MONITOR_DEFAULTS = DeviceDefaults(
    source="alsa_input.pci.analog-stereo",
    sink="",
    monitor="",
)


# ---------------------------------------------------------------------------
# _build_ffmpeg_cmd
# ---------------------------------------------------------------------------


class TestBuildFfmpegCmd:
    def test_dual_source_command(self):
        cmd = AudioRecorder._build_ffmpeg_cmd(
            mic_source="mic_src",
            monitor_source="monitor_src",
            mic_volume=2.0,
        )
        assert cmd[0] == "ffmpeg"
        # Both inputs present
        assert cmd.count("-i") == 2
        idx = cmd.index("-i")
        assert cmd[idx + 1] == "mic_src"
        assert cmd[cmd.index("-i", idx + 1) + 1] == "monitor_src"
        # filter_complex present
        assert "-filter_complex" in cmd
        fc_idx = cmd.index("-filter_complex")
        assert "volume=2.0" in cmd[fc_idx + 1]
        assert "amix" in cmd[fc_idx + 1]
        # Output format
        assert "-f" in cmd
        assert "s16le" in cmd
        assert "pipe:1" in cmd

    def test_custom_mic_volume(self):
        cmd = AudioRecorder._build_ffmpeg_cmd("mic", "mon", mic_volume=3.5)
        fc_idx = cmd.index("-filter_complex")
        assert "volume=3.5" in cmd[fc_idx + 1]

    def test_sample_rate_and_channels(self):
        cmd = AudioRecorder._build_ffmpeg_cmd("mic", "mon", mic_volume=1.0)
        assert "-ar" in cmd
        assert cmd[cmd.index("-ar") + 1] == "16000"
        assert "-ac" in cmd
        assert cmd[cmd.index("-ac") + 1] == "1"


class TestBuildFfmpegCmdMicOnly:
    def test_single_input(self):
        cmd = AudioRecorder._build_ffmpeg_cmd_mic_only("my_mic")
        assert cmd[0] == "ffmpeg"
        assert cmd.count("-i") == 1
        idx = cmd.index("-i")
        assert cmd[idx + 1] == "my_mic"
        assert "-filter_complex" not in cmd
        assert "s16le" in cmd
        assert "pipe:1" in cmd

    def test_sample_rate_and_channels(self):
        cmd = AudioRecorder._build_ffmpeg_cmd_mic_only("my_mic")
        assert cmd[cmd.index("-ar") + 1] == "16000"
        assert cmd[cmd.index("-ac") + 1] == "1"


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------


class TestStart:
    @pytest.mark.asyncio
    async def test_start_with_explicit_sources(self):
        recorder = AudioRecorder()
        proc_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", return_value=proc_mock
        ) as mock_exec:
            await recorder.start(
                mic_source="mic_src",
                monitor_source="mon_src",
                mic_volume=2.0,
            )

        assert recorder.is_recording is True
        cmd = mock_exec.call_args[0]
        assert "ffmpeg" in cmd
        assert "mic_src" in cmd
        assert "mon_src" in cmd

    @pytest.mark.asyncio
    async def test_start_auto_detects_sources(self):
        recorder = AudioRecorder()
        proc_mock = _make_process_mock()

        with patch.object(
            AudioRecorder, "get_defaults", return_value=DEFAULT_DEFAULTS
        ):
            with patch(
                "asyncio.create_subprocess_exec", return_value=proc_mock
            ) as mock_exec:
                await recorder.start()

        assert recorder.is_recording is True
        cmd = mock_exec.call_args[0]
        assert DEFAULT_DEFAULTS.source in cmd
        assert DEFAULT_DEFAULTS.monitor in cmd

    @pytest.mark.asyncio
    async def test_start_falls_back_to_mic_only_when_no_monitor(self):
        recorder = AudioRecorder()
        proc_mock = _make_process_mock()

        with patch.object(
            AudioRecorder, "get_defaults", return_value=NO_MONITOR_DEFAULTS
        ):
            with patch(
                "asyncio.create_subprocess_exec", return_value=proc_mock
            ) as mock_exec:
                await recorder.start()

        cmd = mock_exec.call_args[0]
        # mic-only: no filter_complex
        assert "-filter_complex" not in cmd
        assert cmd.count("-i") == 1

    @pytest.mark.asyncio
    async def test_start_explicit_no_monitor_fallback(self):
        """Passing monitor_source='' explicitly should also use mic-only."""
        recorder = AudioRecorder()
        proc_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", return_value=proc_mock
        ) as mock_exec:
            await recorder.start(mic_source="my_mic", monitor_source="")

        cmd = mock_exec.call_args[0]
        assert cmd.count("-i") == 1
        assert "-filter_complex" not in cmd

    @pytest.mark.asyncio
    async def test_start_raises_if_already_recording(self):
        recorder = AudioRecorder()
        proc_mock = _make_process_mock()

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="mon")

        with pytest.raises(RuntimeError, match="already in progress"):
            await recorder.start(mic_source="mic", monitor_source="mon")

    @pytest.mark.asyncio
    async def test_start_raises_when_no_mic_source(self):
        recorder = AudioRecorder()
        empty_defaults = DeviceDefaults(source="", sink="", monitor="")

        with patch.object(
            AudioRecorder, "get_defaults", return_value=empty_defaults
        ):
            with pytest.raises(RuntimeError, match="No microphone"):
                await recorder.start()

    @pytest.mark.asyncio
    async def test_start_stores_process_reference(self):
        recorder = AudioRecorder()
        proc_mock = _make_process_mock()

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="mon")

        assert recorder._process is proc_mock


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_sends_sigint(self):
        recorder = AudioRecorder()
        proc_mock = _make_process_mock()

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="mon")

        stats = await recorder.stop()

        proc_mock.send_signal.assert_called_once_with(signal.SIGINT)
        assert recorder.is_recording is False
        assert isinstance(stats, RecordingStats)
        assert stats.is_recording is False

    @pytest.mark.asyncio
    async def test_stop_returns_stats(self):
        recorder = AudioRecorder()
        proc_mock = _make_process_mock()

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="mon")

        stats = await recorder.stop()

        assert stats.duration_seconds >= 0.0
        assert stats.chunks_processed == 0

    @pytest.mark.asyncio
    async def test_stop_raises_when_not_recording(self):
        recorder = AudioRecorder()
        with pytest.raises(RuntimeError, match="Not currently recording"):
            await recorder.stop()

    @pytest.mark.asyncio
    async def test_stop_sigkill_on_timeout(self):
        recorder = AudioRecorder()
        proc_mock = _make_process_mock()
        # wait() always succeeds — the timeout comes from wait_for patch
        proc_mock.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="mon")

        call_count = 0

        async def fake_wait_for(coro, timeout):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                coro.close()
                raise asyncio.TimeoutError()
            return await coro

        with patch("asyncio.wait_for", side_effect=fake_wait_for):
            stats = await recorder.stop()

        proc_mock.kill.assert_called_once()
        assert stats.is_recording is False

    @pytest.mark.asyncio
    async def test_stop_handles_process_already_exited(self):
        recorder = AudioRecorder()
        proc_mock = _make_process_mock()
        proc_mock.send_signal.side_effect = ProcessLookupError()

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="mon")

        # Should not raise
        stats = await recorder.stop()
        assert stats.is_recording is False

    @pytest.mark.asyncio
    async def test_stop_clears_process_reference(self):
        recorder = AudioRecorder()
        proc_mock = _make_process_mock()

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="mon")

        await recorder.stop()
        assert recorder._process is None


# ---------------------------------------------------------------------------
# recording_stats property
# ---------------------------------------------------------------------------


class TestRecordingStats:
    @pytest.mark.asyncio
    async def test_stats_idle(self):
        recorder = AudioRecorder()
        stats = recorder.recording_stats
        assert stats.is_recording is False
        assert stats.duration_seconds == 0.0
        assert stats.chunks_processed == 0

    @pytest.mark.asyncio
    async def test_stats_while_recording(self):
        recorder = AudioRecorder()
        proc_mock = _make_process_mock()

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="mon")

        stats = recorder.recording_stats
        assert stats.is_recording is True
        assert stats.duration_seconds >= 0.0

    @pytest.mark.asyncio
    async def test_stats_after_stop(self):
        recorder = AudioRecorder()
        proc_mock = _make_process_mock()

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="mon")

        await recorder.stop()
        stats = recorder.recording_stats
        assert stats.is_recording is False
