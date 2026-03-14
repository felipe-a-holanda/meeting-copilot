"""Tests for AudioRecorder reader loop and pipeline integration (Task 1.3)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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


# ---------------------------------------------------------------------------
# _reader_loop tests
# ---------------------------------------------------------------------------


class TestReaderLoop:
    @pytest.mark.asyncio
    async def test_forwards_chunks_to_pipeline(self):
        chunk1 = b"\x00\x01" * 512  # 1024 bytes
        chunk2 = b"\x02\x03" * 512
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)
        proc_mock = _make_process_mock([chunk1, chunk2])

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="mon")
            # Wait for reader loop to drain (it should finish quickly — EOF comes after 2 chunks)
            if recorder._reader_task:
                await asyncio.wait_for(recorder._reader_task, timeout=2.0)

        assert pipeline.process_audio_chunk.call_count == 2
        pipeline.process_audio_chunk.assert_any_call(chunk1)
        pipeline.process_audio_chunk.assert_any_call(chunk2)

    @pytest.mark.asyncio
    async def test_updates_stats_counters(self):
        chunk = b"\xAB\xCD" * (CHUNK_SIZE // 2)
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)
        proc_mock = _make_process_mock([chunk, chunk, chunk])

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="mon")
            if recorder._reader_task:
                await asyncio.wait_for(recorder._reader_task, timeout=2.0)

        assert recorder._chunks_processed == 3
        assert recorder._bytes_read == 3 * len(chunk)

    @pytest.mark.asyncio
    async def test_eof_stops_reader_loop(self):
        """When ffmpeg closes stdout, reader loop exits without error."""
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)
        proc_mock = _make_process_mock([])  # immediate EOF

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="mon")
            task = recorder._reader_task
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
            await recorder.start(mic_source="mic", monitor_source="mon")
            if recorder._reader_task:
                await asyncio.wait_for(recorder._reader_task, timeout=2.0)

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
            await recorder.start(mic_source="mic", monitor_source="mon")
            if recorder._reader_task:
                await asyncio.wait_for(recorder._reader_task, timeout=2.0)

        # Both chunks were attempted
        assert pipeline.process_audio_chunk.call_count == 2
        assert recorder._chunks_processed == 2


# ---------------------------------------------------------------------------
# stop() — reader task handling
# ---------------------------------------------------------------------------


class TestStopReaderTask:
    @pytest.mark.asyncio
    async def test_stop_calls_pipeline_reset(self):
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)
        proc_mock = _make_process_mock([])

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="mon")

        await recorder.stop()

        pipeline.reset.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_cancels_reader_task_if_still_running(self):
        """If reader loop hasn't finished, stop() should cancel it."""
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)

        # Simulate a reader that blocks indefinitely
        async def blocking_read(*_):
            await asyncio.sleep(100)
            return b""

        proc_mock = _make_process_mock([])
        proc_mock.stdout.read = blocking_read

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="mon")

        task = recorder._reader_task
        assert task is not None
        assert not task.done()

        await recorder.stop()

        assert task.cancelled() or task.done()
        assert recorder._reader_task is None

    @pytest.mark.asyncio
    async def test_stop_no_pipeline_reset_skipped(self):
        """When no pipeline is set, stop() should not raise."""
        recorder = AudioRecorder(pipeline=None)
        proc_mock = _make_process_mock([])

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="mon")

        # Should not raise
        stats = await recorder.stop()
        assert stats.is_recording is False

    @pytest.mark.asyncio
    async def test_stop_reader_task_set_to_none(self):
        pipeline = _make_pipeline_mock()
        recorder = AudioRecorder(pipeline=pipeline)
        proc_mock = _make_process_mock([])

        with patch("asyncio.create_subprocess_exec", return_value=proc_mock):
            await recorder.start(mic_source="mic", monitor_source="mon")

        await recorder.stop()

        assert recorder._reader_task is None
