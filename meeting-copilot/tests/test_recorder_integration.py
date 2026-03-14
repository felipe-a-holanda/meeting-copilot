"""Tests for AudioRecorder reader loop and pipeline integration (Tasks 1.3 / 1B.2)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from backend.audio.recorder import AudioRecorder, CHUNK_SIZE


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stdout_mock(chunks: list[bytes]):
    """Return a mock stdout that yields the given chunks then EOF (b'')."""
    side_effects = list(chunks) + [b""]
    mock = AsyncMock()
    mock.read = AsyncMock(side_effect=side_effects)
    return mock


def _make_process_mock(stdout_chunks: list[bytes] | None = None):
    """Return a mock asyncio.subprocess.Process."""
    proc = MagicMock()
    proc.stdout = _make_stdout_mock(stdout_chunks or [])
    proc.stderr = AsyncMock()
    proc.returncode = 0
    proc.wait = AsyncMock(return_value=0)
    proc.send_signal = MagicMock()
    proc.kill = MagicMock()
    return proc


def _make_pipeline_mock():
    """Return a mock AudioPipeline."""
    pipeline = MagicMock()
    pipeline.process_audio_chunk = AsyncMock()
    pipeline.reset = AsyncMock()
    return pipeline


def _make_eof_process_mock():
    """Process mock that returns EOF immediately (no chunks)."""
    return _make_process_mock([])


# ---------------------------------------------------------------------------
# _reader_loop tests (mic-only for isolation)
# ---------------------------------------------------------------------------


class TestReaderLoop:
    @pytest.mark.asyncio
    async def test_forwards_chunks_to_pipeline_with_speaker_label(self):
        chunk1 = b"\x00\x01" * 512  # 1024 bytes
        chunk2 = b"\x02\x03" * 512
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)
        proc_mock = _make_process_mock([chunk1, chunk2])

        # mic-only so a single process is started
        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="")
            if recorder._mic_reader_task:
                await asyncio.wait_for(recorder._mic_reader_task, timeout=2.0)

        assert pipeline.process_audio_chunk.call_count == 2
        pipeline.process_audio_chunk.assert_any_call(chunk1, speaker_label="Me")
        pipeline.process_audio_chunk.assert_any_call(chunk2, speaker_label="Me")

    @pytest.mark.asyncio
    async def test_updates_stats_counters(self):
        chunk = b"\xAB\xCD" * (CHUNK_SIZE // 2)
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)
        proc_mock = _make_process_mock([chunk, chunk, chunk])

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="")
            if recorder._mic_reader_task:
                await asyncio.wait_for(recorder._mic_reader_task, timeout=2.0)

        assert recorder._chunks_processed == 3
        assert recorder._bytes_read == 3 * len(chunk)

    @pytest.mark.asyncio
    async def test_eof_stops_reader_loop(self):
        """When ffmpeg closes stdout, reader loop exits without error."""
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)
        proc_mock = _make_process_mock([])  # immediate EOF

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="")
            task = recorder._mic_reader_task
            assert task is not None
            await asyncio.wait_for(task, timeout=2.0)

        assert not task.cancelled()
        assert task.exception() is None  # no error

    @pytest.mark.asyncio
    async def test_no_pipeline_does_not_crash(self):
        """When pipeline is None, chunks are consumed but not forwarded."""
        recorder = AudioRecorder(pipeline=None)
        chunk = b"\x00" * 512
        proc_mock = _make_process_mock([chunk])

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="")
            if recorder._mic_reader_task:
                await asyncio.wait_for(recorder._mic_reader_task, timeout=2.0)

        assert recorder._chunks_processed == 1

    @pytest.mark.asyncio
    async def test_pipeline_error_does_not_stop_reader(self):
        """A pipeline exception on one chunk should not stop the reader loop."""
        pipeline = _make_pipeline_mock()
        pipeline.process_audio_chunk = AsyncMock(
            side_effect=[RuntimeError("boom"), None]
        )
        chunk = b"\x00" * 256
        recorder = AudioRecorder(pipeline=pipeline)
        proc_mock = _make_process_mock([chunk, chunk])

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="")
            if recorder._mic_reader_task:
                await asyncio.wait_for(recorder._mic_reader_task, timeout=2.0)

        # Both chunks were attempted
        assert pipeline.process_audio_chunk.call_count == 2
        assert recorder._chunks_processed == 2


# ---------------------------------------------------------------------------
# Dual-stream reader loop tests
# ---------------------------------------------------------------------------


class TestDualStreamReaderLoop:
    @pytest.mark.asyncio
    async def test_mic_chunks_get_me_label(self):
        chunk = b"\x01\x02" * 256
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)
        mic_mock = _make_process_mock([chunk])
        monitor_mock = _make_process_mock([])

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon")
            if recorder._mic_reader_task:
                await asyncio.wait_for(recorder._mic_reader_task, timeout=2.0)

        pipeline.process_audio_chunk.assert_any_call(chunk, speaker_label="Me")

    @pytest.mark.asyncio
    async def test_monitor_chunks_get_them_label(self):
        chunk = b"\x03\x04" * 256
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)
        mic_mock = _make_process_mock([])
        monitor_mock = _make_process_mock([chunk])

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon")
            if recorder._monitor_reader_task:
                await asyncio.wait_for(recorder._monitor_reader_task, timeout=2.0)

        pipeline.process_audio_chunk.assert_any_call(chunk, speaker_label="Them")

    @pytest.mark.asyncio
    async def test_both_streams_contribute_to_stats(self):
        chunk = b"\x00" * 512
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)
        mic_mock = _make_process_mock([chunk, chunk])    # 2 chunks
        monitor_mock = _make_process_mock([chunk])       # 1 chunk

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon")
            tasks = [t for t in (recorder._mic_reader_task, recorder._monitor_reader_task) if t]
            await asyncio.gather(*[asyncio.wait_for(t, timeout=2.0) for t in tasks])

        assert recorder._chunks_processed == 3
        assert recorder._bytes_read == 3 * len(chunk)


# ---------------------------------------------------------------------------
# stop() — reader task handling
# ---------------------------------------------------------------------------


class TestStopReaderTask:
    @pytest.mark.asyncio
    async def test_stop_calls_pipeline_reset(self):
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)
        mic_mock = _make_process_mock([])
        monitor_mock = _make_process_mock([])

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon")

        await recorder.stop()

        pipeline.reset.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_cancels_mic_reader_task_if_still_running(self):
        """If mic reader loop hasn't finished, stop() should cancel it."""
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)

        async def blocking_read(*_):
            await asyncio.sleep(100)
            return b""

        proc_mock = _make_process_mock([])
        proc_mock.stdout.read = blocking_read

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="")

        task = recorder._mic_reader_task
        assert task is not None
        assert not task.done()

        await recorder.stop()

        assert task.cancelled() or task.done()
        assert recorder._mic_reader_task is None

    @pytest.mark.asyncio
    async def test_stop_cancels_monitor_reader_task_if_still_running(self):
        """If monitor reader loop hasn't finished, stop() should cancel it."""
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)

        async def blocking_read(*_):
            await asyncio.sleep(100)
            return b""

        mic_mock = _make_process_mock([])
        monitor_mock = _make_process_mock([])
        monitor_mock.stdout.read = blocking_read

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon")

        mon_task = recorder._monitor_reader_task
        assert mon_task is not None
        assert not mon_task.done()

        await recorder.stop()

        assert mon_task.cancelled() or mon_task.done()
        assert recorder._monitor_reader_task is None

    @pytest.mark.asyncio
    async def test_stop_no_pipeline_reset_skipped(self):
        """When no pipeline is set, stop() should not raise."""
        recorder = AudioRecorder(pipeline=None)
        proc_mock = _make_process_mock([])

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="")

        # Should not raise
        stats = await recorder.stop()
        assert stats.is_recording is False

    @pytest.mark.asyncio
    async def test_stop_reader_tasks_set_to_none(self):
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)
        mic_mock = _make_process_mock([])
        monitor_mock = _make_process_mock([])

        with patch(
            "asyncio.create_subprocess_exec", side_effect=[mic_mock, monitor_mock]
        ):
            await recorder.start(mic_source="mic", monitor_source="mon")

        await recorder.stop()

        assert recorder._mic_reader_task is None
        assert recorder._monitor_reader_task is None
