"""Tests for dual-stream speaker-label behaviour (Task 1B.2)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, call

import pytest

from backend.audio.recorder import AudioRecorder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stdout_mock(chunks: list[bytes]):
    side_effects = list(chunks) + [b""]
    mock = AsyncMock()
    mock.read = AsyncMock(side_effect=side_effects)
    return mock


def _make_process_mock(stdout_chunks: list[bytes] | None = None):
    proc = MagicMock()
    proc.stdout = _make_stdout_mock(stdout_chunks or [])
    proc.stderr = AsyncMock()
    proc.returncode = 0
    proc.wait = AsyncMock(return_value=0)
    proc.send_signal = MagicMock()
    proc.kill = MagicMock()
    return proc


def _make_pipeline_mock():
    pipeline = MagicMock()
    pipeline.process_audio_chunk = AsyncMock()
    pipeline.reset = AsyncMock()
    return pipeline


# ---------------------------------------------------------------------------
# Two separate ffmpeg processes
# ---------------------------------------------------------------------------


class TestTwoProcessesStarted:
    @pytest.mark.asyncio
    async def test_dual_stream_creates_two_processes(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ) as mock_exec:
            await recorder.start(mic_source="mic_src", monitor_source="mon_src")

        assert mock_exec.call_count == 2

    @pytest.mark.asyncio
    async def test_mic_process_uses_mic_source(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ) as mock_exec:
            await recorder.start(mic_source="mic_src", monitor_source="mon_src")

        mic_cmd = mock_exec.call_args_list[0][0]
        assert "mic_src" in mic_cmd

    @pytest.mark.asyncio
    async def test_monitor_process_uses_monitor_source(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ) as mock_exec:
            await recorder.start(mic_source="mic_src", monitor_source="mon_src")

        mon_cmd = mock_exec.call_args_list[1][0]
        assert "mon_src" in mon_cmd

    @pytest.mark.asyncio
    async def test_mic_only_creates_one_process(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", return_value=mic_mock
        ) as mock_exec:
            await recorder.start(mic_source="mic_src", monitor_source="")

        assert mock_exec.call_count == 1
        assert recorder._monitor_process is None


# ---------------------------------------------------------------------------
# Speaker labels
# ---------------------------------------------------------------------------


class TestSpeakerLabels:
    @pytest.mark.asyncio
    async def test_mic_chunks_tagged_me(self):
        mic_chunk = b"\x01" * 256
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)
        mic_mock = _make_process_mock([mic_chunk])
        monitor_mock = _make_process_mock([])

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon")
            if recorder._mic_reader_task:
                await asyncio.wait_for(recorder._mic_reader_task, timeout=2.0)

        pipeline.process_audio_chunk.assert_any_call(mic_chunk, speaker_label="Me")

    @pytest.mark.asyncio
    async def test_monitor_chunks_tagged_them(self):
        mon_chunk = b"\x02" * 256
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)
        mic_mock = _make_process_mock([])
        monitor_mock = _make_process_mock([mon_chunk])

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon")
            if recorder._monitor_reader_task:
                await asyncio.wait_for(recorder._monitor_reader_task, timeout=2.0)

        pipeline.process_audio_chunk.assert_any_call(mon_chunk, speaker_label="Them")

    @pytest.mark.asyncio
    async def test_mic_only_chunks_tagged_me(self):
        """In mic-only mode, all chunks get speaker_label='Me'."""
        chunk = b"\x03" * 256
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)
        mic_mock = _make_process_mock([chunk])

        with patch("asyncio.create_subprocess_exec", return_value=mic_mock):
            await recorder.start(mic_source="mic", monitor_source="")
            if recorder._mic_reader_task:
                await asyncio.wait_for(recorder._mic_reader_task, timeout=2.0)

        pipeline.process_audio_chunk.assert_any_call(chunk, speaker_label="Me")
        # Confirm "Them" was never used
        for c in pipeline.process_audio_chunk.call_args_list:
            assert c.kwargs.get("speaker_label") != "Them"

    @pytest.mark.asyncio
    async def test_mic_chunks_never_tagged_them(self):
        mic_chunk = b"\x04" * 256
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)
        mic_mock = _make_process_mock([mic_chunk])
        monitor_mock = _make_process_mock([])

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon")
            if recorder._mic_reader_task:
                await asyncio.wait_for(recorder._mic_reader_task, timeout=2.0)

        for c in pipeline.process_audio_chunk.call_args_list:
            if c.args and c.args[0] == mic_chunk:
                assert c.kwargs.get("speaker_label") == "Me"

    @pytest.mark.asyncio
    async def test_monitor_chunks_never_tagged_me(self):
        mon_chunk = b"\x05" * 256
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)
        mic_mock = _make_process_mock([])
        monitor_mock = _make_process_mock([mon_chunk])

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon")
            if recorder._monitor_reader_task:
                await asyncio.wait_for(recorder._monitor_reader_task, timeout=2.0)

        for c in pipeline.process_audio_chunk.call_args_list:
            if c.args and c.args[0] == mon_chunk:
                assert c.kwargs.get("speaker_label") == "Them"


# ---------------------------------------------------------------------------
# stop() shuts down both processes
# ---------------------------------------------------------------------------


class TestStopBothProcesses:
    @pytest.mark.asyncio
    async def test_stop_shuts_down_both_processes(self):
        import signal as _signal
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon")

        await recorder.stop()

        mic_mock.send_signal.assert_called_once_with(_signal.SIGINT)
        monitor_mock.send_signal.assert_called_once_with(_signal.SIGINT)

    @pytest.mark.asyncio
    async def test_stop_clears_both_process_references(self):
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

    @pytest.mark.asyncio
    async def test_stop_clears_both_reader_task_references(self):
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()
        monitor_mock = _make_process_mock()

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon")

        await recorder.stop()

        assert recorder._mic_reader_task is None
        assert recorder._monitor_reader_task is None

    @pytest.mark.asyncio
    async def test_stop_mic_only_only_shuts_down_mic(self):
        import signal as _signal
        recorder = AudioRecorder()
        mic_mock = _make_process_mock()

        with patch("asyncio.create_subprocess_exec", return_value=mic_mock):
            await recorder.start(mic_source="mic", monitor_source="")

        await recorder.stop()

        mic_mock.send_signal.assert_called_once_with(_signal.SIGINT)
        # No monitor process was ever created
        assert recorder._monitor_process is None

    @pytest.mark.asyncio
    async def test_stop_not_recording_raises(self):
        recorder = AudioRecorder()
        with pytest.raises(RuntimeError, match="Not currently recording"):
            await recorder.stop()
