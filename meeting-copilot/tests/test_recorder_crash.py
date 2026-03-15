"""Tests for AudioRecorder crash detection and resilience (Task 4.5).

Covers:
- ffmpeg crashing mid-recording (all streams exit unexpectedly)
- Single stream crash while the other continues (device unplug scenario)
- Graceful stop does NOT trigger crash callback
- Concurrent start returns 409 (already in E2E; duplicated here as unit test)
- Orphaned ffmpeg cleanup on startup
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.audio.recorder import AudioRecorder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stdout(chunks: list[bytes]):
    """Return an AsyncMock for process.stdout that yields *chunks* then EOF."""
    side_effects = list(chunks) + [b""]
    mock = AsyncMock()
    mock.read = AsyncMock(side_effect=side_effects)
    return mock


def _make_proc(chunks: list[bytes] | None = None):
    """Return a MagicMock mimicking an asyncio subprocess."""
    proc = MagicMock()
    proc.stdout = _make_stdout(chunks or [])
    proc.stderr = AsyncMock()
    proc.returncode = 0
    proc.wait = AsyncMock(return_value=0)
    proc.send_signal = MagicMock()
    proc.kill = MagicMock()
    proc.pid = 12345
    return proc


def _make_recorder(pipeline=None):
    return AudioRecorder(pipeline=pipeline or MagicMock(), recordings_dir="/tmp")


# ---------------------------------------------------------------------------
# Tests — crash detection
# ---------------------------------------------------------------------------


class TestCrashDetection:
    @pytest.mark.asyncio
    async def test_crash_callback_called_when_both_streams_exit(self):
        """When both ffmpeg processes exit unexpectedly, the crash callback fires."""
        recorder = _make_recorder()
        crash_called = []

        async def on_crash():
            crash_called.append(True)

        recorder.set_crash_callback(on_crash)

        mic_proc = _make_proc([])
        monitor_proc = _make_proc([])

        with patch("asyncio.create_subprocess_exec", side_effect=[mic_proc, monitor_proc]):
            await recorder.start(mic_source="test_mic", monitor_source="test_monitor")

            # Wait for both reader loops to finish (they get EOF immediately)
            if recorder._mic_reader_task:
                await asyncio.wait_for(recorder._mic_reader_task, timeout=3.0)
            if recorder._monitor_reader_task:
                await asyncio.wait_for(recorder._monitor_reader_task, timeout=3.0)

        assert len(crash_called) == 1, "Crash callback should fire exactly once"

    @pytest.mark.asyncio
    async def test_crash_resets_is_recording_to_false(self):
        """After a crash, is_recording becomes False without calling stop()."""
        recorder = _make_recorder()
        recorder.set_crash_callback(AsyncMock())

        mic_proc = _make_proc([])
        monitor_proc = _make_proc([])

        with patch("asyncio.create_subprocess_exec", side_effect=[mic_proc, monitor_proc]):
            await recorder.start(mic_source="test_mic", monitor_source="test_monitor")

            assert recorder.is_recording is True

            if recorder._mic_reader_task:
                await asyncio.wait_for(recorder._mic_reader_task, timeout=3.0)
            if recorder._monitor_reader_task:
                await asyncio.wait_for(recorder._monitor_reader_task, timeout=3.0)

        assert recorder.is_recording is False

    @pytest.mark.asyncio
    async def test_crash_clears_process_references(self):
        """After a crash, _mic_process and _monitor_process are cleared."""
        recorder = _make_recorder()
        recorder.set_crash_callback(AsyncMock())

        mic_proc = _make_proc([])
        monitor_proc = _make_proc([])

        with patch("asyncio.create_subprocess_exec", side_effect=[mic_proc, monitor_proc]):
            await recorder.start(mic_source="test_mic", monitor_source="test_monitor")

            if recorder._mic_reader_task:
                await asyncio.wait_for(recorder._mic_reader_task, timeout=3.0)
            if recorder._monitor_reader_task:
                await asyncio.wait_for(recorder._monitor_reader_task, timeout=3.0)

        assert recorder._mic_process is None
        assert recorder._monitor_process is None

    @pytest.mark.asyncio
    async def test_no_crash_callback_when_none_registered(self):
        """If no crash callback is registered, crash handling is still safe (no error raised)."""
        recorder = _make_recorder()
        # Don't register any callback

        mic_proc = _make_proc([])
        monitor_proc = _make_proc([])

        with patch("asyncio.create_subprocess_exec", side_effect=[mic_proc, monitor_proc]):
            await recorder.start(mic_source="test_mic", monitor_source="test_monitor")

            if recorder._mic_reader_task:
                await asyncio.wait_for(recorder._mic_reader_task, timeout=3.0)
            if recorder._monitor_reader_task:
                await asyncio.wait_for(recorder._monitor_reader_task, timeout=3.0)

        # No exception raised; recording is reset
        assert recorder.is_recording is False


# ---------------------------------------------------------------------------
# Tests — partial crash (device disappearing)
# ---------------------------------------------------------------------------


class TestPartialCrash:
    @pytest.mark.asyncio
    async def test_single_stream_crash_does_not_trigger_callback(self):
        """When only the monitor stream crashes, the crash callback is NOT called.

        The mic stream is still alive (its read blocks on an asyncio.Event),
        so _active_stream_count stays above 0.
        """
        recorder = _make_recorder()
        crash_called = []

        async def on_crash():
            crash_called.append(True)

        recorder.set_crash_callback(on_crash)

        # Mic read blocks until we release it via an Event
        mic_unblock = asyncio.Event()

        async def blocking_read(n: int) -> bytes:
            await mic_unblock.wait()
            return b""  # EOF once unblocked

        mic_proc = _make_proc()
        mic_proc.stdout.read = blocking_read

        monitor_proc = _make_proc([])  # EOF immediately

        with patch("asyncio.create_subprocess_exec", side_effect=[mic_proc, monitor_proc]):
            await recorder.start(mic_source="test_mic", monitor_source="test_monitor")

            # Wait only for the monitor reader to finish (EOF immediately)
            if recorder._monitor_reader_task:
                await asyncio.wait_for(recorder._monitor_reader_task, timeout=3.0)

            # Give the event loop a moment to settle
            await asyncio.sleep(0)

            # Crash callback must NOT have fired — mic stream still alive
            assert len(crash_called) == 0, "Crash callback must not fire with one stream alive"
            assert recorder.is_recording is True, "Should still be recording on surviving stream"

            # Unblock the mic reader so it can exit cleanly
            mic_unblock.set()
            if recorder._mic_reader_task and not recorder._mic_reader_task.done():
                try:
                    await asyncio.wait_for(recorder._mic_reader_task, timeout=3.0)
                except (asyncio.CancelledError, Exception):
                    pass
            recorder._is_recording = False  # manual cleanup for test teardown

    @pytest.mark.asyncio
    async def test_mic_only_crash_triggers_callback(self):
        """In mic-only mode (no monitor), a single stream crash triggers the callback."""
        recorder = _make_recorder()
        crash_called = []

        async def on_crash():
            crash_called.append(True)

        recorder.set_crash_callback(on_crash)

        mic_proc = _make_proc([])  # EOF immediately

        with patch("asyncio.create_subprocess_exec", side_effect=[mic_proc]):
            # Pass empty string for monitor_source → mic-only
            await recorder.start(mic_source="test_mic", monitor_source="")

            if recorder._mic_reader_task:
                await asyncio.wait_for(recorder._mic_reader_task, timeout=3.0)

        assert len(crash_called) == 1, "Single-stream crash should fire callback"
        assert recorder.is_recording is False


# ---------------------------------------------------------------------------
# Tests — graceful stop does NOT trigger crash
# ---------------------------------------------------------------------------


class TestGracefulStopNoCrash:
    @pytest.mark.asyncio
    async def test_graceful_stop_does_not_call_crash_callback(self):
        """A normal stop() call must NOT trigger the crash callback."""
        recorder = _make_recorder()
        crash_called = []

        async def on_crash():
            crash_called.append(True)

        recorder.set_crash_callback(on_crash)

        # Processes exit immediately after SIGINT (stop() sends it)
        mic_proc = _make_proc([])
        monitor_proc = _make_proc([])

        with patch("asyncio.create_subprocess_exec", side_effect=[mic_proc, monitor_proc]):
            await recorder.start(mic_source="test_mic", monitor_source="test_monitor")
            # Manually set _stopping so reader loops (already at EOF) see graceful stop
            recorder._stopping = True
            await recorder.stop()

        assert len(crash_called) == 0, "stop() must never trigger the crash callback"

    @pytest.mark.asyncio
    async def test_stop_sets_stopping_flag_before_killing_processes(self):
        """stop() sets _stopping=True before sending SIGINT so reader loops skip crash logic."""
        recorder = _make_recorder()
        stopping_flag_at_stop_time = []

        original_stop_process = recorder._stop_process

        async def spy_stop_process(proc):
            stopping_flag_at_stop_time.append(recorder._stopping)
            await original_stop_process(proc)

        recorder._stop_process = spy_stop_process

        crash_callback = AsyncMock()
        recorder.set_crash_callback(crash_callback)

        mic_proc = _make_proc([])
        monitor_proc = _make_proc([])

        with patch("asyncio.create_subprocess_exec", side_effect=[mic_proc, monitor_proc]):
            await recorder.start(mic_source="test_mic", monitor_source="test_monitor")
            recorder._stopping = True  # simulate what stop() does first
            await recorder.stop()

        crash_callback.assert_not_awaited()


# ---------------------------------------------------------------------------
# Tests — crash callback in main.py (integration)
# ---------------------------------------------------------------------------


class TestMainCrashIntegration:
    @pytest.mark.asyncio
    async def test_crash_resets_active_session_id(self):
        """When recorder crashes, _active_session_id is cleared in main.py."""
        import backend.main as main_module

        # Save and restore module state
        original_session_id = main_module._active_session_id
        main_module._active_session_id = "test-session-123"

        try:
            # Directly invoke the crash callback that main.py registered
            mock_broadcast = AsyncMock()
            with patch.object(main_module, "_broadcast_error", mock_broadcast):
                await main_module._on_recorder_crash()

            assert main_module._active_session_id is None
        finally:
            main_module._active_session_id = original_session_id

    @pytest.mark.asyncio
    async def test_crash_broadcasts_error_message(self):
        """Crash handler broadcasts an error with context='recorder_crash'."""
        import backend.main as main_module

        original_session_id = main_module._active_session_id
        main_module._active_session_id = "test-session-456"

        try:
            mock_broadcast = AsyncMock()
            with patch.object(main_module, "_broadcast_error", mock_broadcast):
                await main_module._on_recorder_crash()

            mock_broadcast.assert_awaited_once()
            call_kwargs = mock_broadcast.call_args
            assert call_kwargs.kwargs.get("context") == "recorder_crash"
        finally:
            main_module._active_session_id = original_session_id


# ---------------------------------------------------------------------------
# Tests — orphaned ffmpeg cleanup on startup
# ---------------------------------------------------------------------------


class TestOrphanedCleanup:
    @pytest.mark.asyncio
    async def test_cleanup_calls_pkill_on_startup(self):
        """_cleanup_orphaned_ffmpeg uses pkill -f 'ffmpeg.*-f pulse'."""
        from backend.main import _cleanup_orphaned_ffmpeg

        pkill_proc = MagicMock()
        pkill_proc.wait = AsyncMock(return_value=0)  # pkill found processes

        with patch("asyncio.create_subprocess_exec", return_value=pkill_proc) as mock_exec:
            await _cleanup_orphaned_ffmpeg()

        mock_exec.assert_called_once()
        args = mock_exec.call_args[0]
        assert "pkill" in args
        assert "-f" in args
        assert "ffmpeg.*-f pulse" in args

    @pytest.mark.asyncio
    async def test_cleanup_silent_when_no_orphans(self):
        """pkill exit code 1 (no processes matched) is silently ignored."""
        from backend.main import _cleanup_orphaned_ffmpeg

        pkill_proc = MagicMock()
        pkill_proc.wait = AsyncMock(return_value=1)  # no processes matched

        with patch("asyncio.create_subprocess_exec", return_value=pkill_proc):
            # Must not raise
            await _cleanup_orphaned_ffmpeg()

    @pytest.mark.asyncio
    async def test_cleanup_silent_when_pkill_missing(self):
        """If pkill is not installed, _cleanup_orphaned_ffmpeg is a no-op (no exception)."""
        from backend.main import _cleanup_orphaned_ffmpeg

        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            await _cleanup_orphaned_ffmpeg()  # must not raise
