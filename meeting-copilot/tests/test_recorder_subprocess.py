"""Tests for AudioRecorder ffmpeg subprocess management (Tasks 1.2 / 1B.2)."""
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
    proc.stdout.read = AsyncMock(return_value=b"")  # EOF immediately — prevents reader loop hang
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
# _build_stream_cmd
# ---------------------------------------------------------------------------


class TestBuildStreamCmd:
    def test_single_input(self):
        cmd = AudioRecorder._build_stream_cmd("my_source")
        assert cmd[0] == "ffmpeg"
        assert cmd.count("-i") == 1
        idx = cmd.index("-i")
        assert cmd[idx + 1] == "my_source"
        assert "-filter_complex" not in cmd
        assert "s16le" in cmd
        assert "pipe:1" in cmd

    def test_sample_rate_and_channels(self):
        cmd = AudioRecorder._build_stream_cmd("my_source")
        assert cmd[cmd.index("-ar") + 1] == "16000"
        assert cmd[cmd.index("-ac") + 1] == "1"

    def test_pulse_input_format(self):
        cmd = AudioRecorder._build_stream_cmd("my_source")
        assert "-f" in cmd
        f_idx = cmd.index("-f")
        assert cmd[f_idx + 1] == "pulse"

    def test_with_file_path_has_two_outputs(self):
        cmd = AudioRecorder._build_stream_cmd("my_source", file_path="/tmp/out.wav")
        assert "pipe:1" in cmd
        assert "/tmp/out.wav" in cmd
        assert "pcm_s16le" in cmd
        assert cmd.count("-map") == 2

    def test_with_file_path_pipe_comes_first(self):
        cmd = AudioRecorder._build_stream_cmd("my_source", file_path="/tmp/out.wav")
        pipe_idx = cmd.index("pipe:1")
        file_idx = cmd.index("/tmp/out.wav")
        assert pipe_idx < file_idx

    def test_without_file_path_no_pcm_codec(self):
        cmd = AudioRecorder._build_stream_cmd("my_source")
        assert "pcm_s16le" not in cmd
        assert "-map" not in cmd


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------


class TestStart:
    @pytest.mark.asyncio
    async def test_start_dual_stream_launches_two_processes(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ) as mock_exec:
            await recorder.start(mic_source="mic_src", monitor_source="mon_src")

        assert mock_exec.call_count == 2
        assert recorder.is_recording is True

    @pytest.mark.asyncio
    async def test_start_dual_stream_mic_gets_mic_source(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ) as mock_exec:
            await recorder.start(mic_source="mic_src", monitor_source="mon_src")

        first_call_cmd = mock_exec.call_args_list[0][0]
        assert "mic_src" in first_call_cmd
        assert "mon_src" not in first_call_cmd

    @pytest.mark.asyncio
    async def test_start_dual_stream_monitor_gets_monitor_source(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ) as mock_exec:
            await recorder.start(mic_source="mic_src", monitor_source="mon_src")

        second_call_cmd = mock_exec.call_args_list[1][0]
        assert "mon_src" in second_call_cmd
        assert "mic_src" not in second_call_cmd

    @pytest.mark.asyncio
    async def test_start_stores_process_references(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic_src", monitor_source="mon_src")

        assert recorder._mic_process is mic_mock
        assert recorder._monitor_process is monitor_mock

    @pytest.mark.asyncio
    async def test_start_auto_detects_sources(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()

        with patch.object(AudioRecorder, "get_defaults", return_value=DEFAULT_DEFAULTS):
            with patch(
                "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
            ) as mock_exec:
                await recorder.start()

        assert recorder.is_recording is True
        first_cmd = mock_exec.call_args_list[0][0]
        second_cmd = mock_exec.call_args_list[1][0]
        assert DEFAULT_DEFAULTS.source in first_cmd
        assert DEFAULT_DEFAULTS.monitor in second_cmd

    @pytest.mark.asyncio
    async def test_start_falls_back_to_mic_only_when_no_monitor(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()

        with patch.object(AudioRecorder, "get_defaults", return_value=NO_MONITOR_DEFAULTS):
            with patch(
                "asyncio.create_subprocess_exec", return_value=mic_mock
            ) as mock_exec:
                await recorder.start()

        assert mock_exec.call_count == 1
        assert recorder._monitor_process is None
        assert recorder._monitor_reader_task is None

    @pytest.mark.asyncio
    async def test_start_explicit_no_monitor_fallback(self):
        """Passing monitor_source='' explicitly should also use mic-only."""
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", return_value=mic_mock
        ) as mock_exec:
            await recorder.start(mic_source="my_mic", monitor_source="")

        assert mock_exec.call_count == 1
        assert recorder._monitor_process is None

    @pytest.mark.asyncio
    async def test_start_raises_if_already_recording(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon")

        with pytest.raises(RuntimeError, match="already in progress"):
            await recorder.start(mic_source="mic", monitor_source="mon")

    @pytest.mark.asyncio
    async def test_start_raises_when_no_mic_source(self):
        recorder = AudioRecorder()
        empty_defaults = DeviceDefaults(source="", sink="", monitor="")

        with patch.object(AudioRecorder, "get_defaults", return_value=empty_defaults):
            with pytest.raises(RuntimeError, match="No microphone"):
                await recorder.start()

    @pytest.mark.asyncio
    async def test_start_no_filter_complex_for_either_stream(self):
        """Both mic and monitor commands must NOT use amix — simple single-input commands."""
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ) as mock_exec:
            await recorder.start(mic_source="mic_src", monitor_source="mon_src")

        for call_args in mock_exec.call_args_list:
            cmd = call_args[0]
            assert "-filter_complex" not in cmd
            assert cmd.count("-i") == 1


# ---------------------------------------------------------------------------
# stop()
# ---------------------------------------------------------------------------


class TestStop:
    @pytest.mark.asyncio
    async def test_stop_sends_sigint_to_both_processes(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon")

        stats = await recorder.stop()

        mic_mock.send_signal.assert_called_once_with(signal.SIGINT)
        monitor_mock.send_signal.assert_called_once_with(signal.SIGINT)
        assert recorder.is_recording is False
        assert isinstance(stats, RecordingStats)
        assert stats.is_recording is False

    @pytest.mark.asyncio
    async def test_stop_mic_only_sends_sigint_to_one_process(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()

        with patch("asyncio.create_subprocess_exec", return_value=mic_mock):
            await recorder.start(mic_source="mic", monitor_source="")

        stats = await recorder.stop()

        mic_mock.send_signal.assert_called_once_with(signal.SIGINT)
        assert stats.is_recording is False

    @pytest.mark.asyncio
    async def test_stop_returns_stats(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
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
    async def test_stop_sigkill_on_timeout_mic_only(self):
        """Verify SIGKILL fallback on a single mic-only process."""
        recorder = AudioRecorder()
        proc_mock = _make_process_mock()
        proc_mock.wait = AsyncMock(return_value=0)

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="")

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
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()
        mic_mock.send_signal.side_effect = ProcessLookupError()
        monitor_mock.send_signal.side_effect = ProcessLookupError()

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon")

        # Should not raise
        stats = await recorder.stop()
        assert stats.is_recording is False

    @pytest.mark.asyncio
    async def test_stop_clears_process_references(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon")

        await recorder.stop()
        assert recorder._mic_process is None
        assert recorder._monitor_process is None


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
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon")

        stats = recorder.recording_stats
        assert stats.is_recording is True
        assert stats.duration_seconds >= 0.0

    @pytest.mark.asyncio
    async def test_stats_after_stop(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon")

        await recorder.stop()
        stats = recorder.recording_stats
        assert stats.is_recording is False
