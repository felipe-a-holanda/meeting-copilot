"""Tests for Task 2.4 — Wire Segments to Session Storage.

Verifies that:
  1. When a segment arrives and a session is active, save_segment is called.
  2. When no session is active, save_segment is NOT called.
  3. On stop, save_state is called with current summary + action items.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.ws.protocol import ActionItem, TranscriptSegment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_segment(speaker: str = "Me", text: str = "hello") -> TranscriptSegment:
    return TranscriptSegment(
        speaker=speaker,
        text=text,
        timestamp_start=0.0,
        timestamp_end=1.0,
    )


# ---------------------------------------------------------------------------
# _segment_handler — persistence behaviour
# ---------------------------------------------------------------------------


class TestSegmentHandler:
    """Unit tests for the _segment_handler coroutine in main.py."""

    @pytest.mark.asyncio
    async def test_save_segment_called_when_session_active(self):
        """save_segment is called with the active session id and segment."""
        import backend.main as main_module

        segment = _make_segment()
        save_segment_mock = AsyncMock()
        on_new_segment_mock = AsyncMock()

        original_session_id = main_module._active_session_id
        main_module._active_session_id = "sess-test"
        try:
            with (
                patch.object(main_module.context_manager, "on_new_segment", on_new_segment_mock),
                patch.object(main_module.session_store, "save_segment", save_segment_mock),
            ):
                await main_module._segment_handler(segment)
        finally:
            main_module._active_session_id = original_session_id

        on_new_segment_mock.assert_awaited_once_with(segment)
        save_segment_mock.assert_awaited_once_with("sess-test", segment)

    @pytest.mark.asyncio
    async def test_save_segment_not_called_when_no_session(self):
        """save_segment is NOT called when _active_session_id is None."""
        import backend.main as main_module

        segment = _make_segment()
        save_segment_mock = AsyncMock()
        on_new_segment_mock = AsyncMock()

        original_session_id = main_module._active_session_id
        main_module._active_session_id = None
        try:
            with (
                patch.object(main_module.context_manager, "on_new_segment", on_new_segment_mock),
                patch.object(main_module.session_store, "save_segment", save_segment_mock),
            ):
                await main_module._segment_handler(segment)
        finally:
            main_module._active_session_id = original_session_id

        on_new_segment_mock.assert_awaited_once_with(segment)
        save_segment_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_context_manager_always_called(self):
        """context_manager.on_new_segment is called regardless of session state."""
        import backend.main as main_module

        segment = _make_segment(speaker="Them", text="world")
        on_new_segment_mock = AsyncMock()
        save_segment_mock = AsyncMock()

        original_session_id = main_module._active_session_id
        main_module._active_session_id = None
        try:
            with (
                patch.object(main_module.context_manager, "on_new_segment", on_new_segment_mock),
                patch.object(main_module.session_store, "save_segment", save_segment_mock),
            ):
                await main_module._segment_handler(segment)
        finally:
            main_module._active_session_id = original_session_id

        on_new_segment_mock.assert_awaited_once_with(segment)

    @pytest.mark.asyncio
    async def test_correct_segment_forwarded(self):
        """The exact segment object is forwarded to both handlers."""
        import backend.main as main_module

        segment = _make_segment(speaker="Them", text="specific text")
        save_segment_mock = AsyncMock()
        on_new_segment_mock = AsyncMock()

        original_session_id = main_module._active_session_id
        main_module._active_session_id = "sess-abc"
        try:
            with (
                patch.object(main_module.context_manager, "on_new_segment", on_new_segment_mock),
                patch.object(main_module.session_store, "save_segment", save_segment_mock),
            ):
                await main_module._segment_handler(segment)
        finally:
            main_module._active_session_id = original_session_id

        # Both should receive the exact same segment object
        assert on_new_segment_mock.call_args[0][0] is segment
        assert save_segment_mock.call_args[0][1] is segment


# ---------------------------------------------------------------------------
# stop_recording — final state persistence
# ---------------------------------------------------------------------------


class TestStopRecordingPersistsState:
    """Verify that stopping a recording saves summary + action items."""

    @pytest.mark.asyncio
    async def test_save_state_called_on_stop(self):
        """save_state is called with the session id, summary, and action items on stop."""
        from httpx import ASGITransport, AsyncClient
        from backend.audio.recorder import RecordingStats
        from backend.storage.session import SessionData
        from backend.main import app

        import backend.main as main_module

        stats = RecordingStats(
            duration_seconds=10.0,
            chunks_processed=5,
            bytes_read=0,
            is_recording=False,
        )
        session_data = SessionData(
            id="sess-stop",
            title="T",
            created_at=0.0,
            updated_at=0.0,
            summary="",
            action_items=[],
            segments=[],
        )
        recorder_mock = MagicMock()
        recorder_mock.is_recording = True
        recorder_mock.stop = AsyncMock(return_value=stats)

        save_state_mock = AsyncMock()
        load_session_mock = AsyncMock(return_value=session_data)

        # Set context manager state to something non-trivial
        original_summary = main_module.context_manager.state.current_summary
        original_items = main_module.context_manager.state.action_items
        original_session_id = main_module._active_session_id

        main_module.context_manager.state.current_summary = "Meeting summary text"
        main_module.context_manager.state.action_items = [
            ActionItem(id="item-1", description="Follow up", assignee="Alice", source_timestamp=0.0)
        ]
        main_module._active_session_id = "sess-stop"

        try:
            with (
                patch("backend.main.audio_recorder", recorder_mock),
                patch.object(main_module.session_store, "save_state", save_state_mock),
                patch.object(main_module.session_store, "load_session", load_session_mock),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post("/api/recording/stop")
        finally:
            main_module.context_manager.state.current_summary = original_summary
            main_module.context_manager.state.action_items = original_items
            main_module._active_session_id = original_session_id

        assert resp.status_code == 200
        save_state_mock.assert_awaited_once()
        call_args = save_state_mock.call_args
        assert call_args[0][0] == "sess-stop"
        assert call_args[0][1] == "Meeting summary text"
        assert len(call_args[0][2]) == 1
        assert call_args[0][2][0].description == "Follow up"

    @pytest.mark.asyncio
    async def test_save_state_not_called_when_no_session_id(self):
        """save_state is NOT called when there is no active session id (safety check)."""
        from httpx import ASGITransport, AsyncClient
        from backend.audio.recorder import RecordingStats
        from backend.storage.session import SessionData
        from backend.main import app

        import backend.main as main_module

        stats = RecordingStats(
            duration_seconds=5.0,
            chunks_processed=2,
            bytes_read=0,
            is_recording=False,
        )
        recorder_mock = MagicMock()
        recorder_mock.is_recording = True
        recorder_mock.stop = AsyncMock(return_value=stats)

        save_state_mock = AsyncMock()
        load_session_mock = AsyncMock(return_value=None)

        original_session_id = main_module._active_session_id
        main_module._active_session_id = None  # No active session

        try:
            with (
                patch("backend.main.audio_recorder", recorder_mock),
                patch.object(main_module.session_store, "save_state", save_state_mock),
                patch.object(main_module.session_store, "load_session", load_session_mock),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post("/api/recording/stop")
        finally:
            main_module._active_session_id = original_session_id

        assert resp.status_code == 200
        save_state_mock.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_response_includes_segment_count_after_persistence(self):
        """segments_count in the stop response matches the persisted segments."""
        from httpx import ASGITransport, AsyncClient
        from backend.audio.recorder import RecordingStats
        from backend.storage.session import SessionData
        from backend.main import app
        import backend.main as main_module

        seg = _make_segment()
        session_data = SessionData(
            id="sess-stop2",
            title="T",
            created_at=0.0,
            updated_at=0.0,
            summary="",
            action_items=[],
            segments=[seg, seg, seg],
        )
        stats = RecordingStats(
            duration_seconds=3.0, chunks_processed=3, bytes_read=0, is_recording=False
        )
        recorder_mock = MagicMock()
        recorder_mock.is_recording = True
        recorder_mock.stop = AsyncMock(return_value=stats)

        original_session_id = main_module._active_session_id
        main_module._active_session_id = "sess-stop2"

        try:
            with (
                patch("backend.main.audio_recorder", recorder_mock),
                patch.object(main_module.session_store, "save_state", AsyncMock()),
                patch.object(main_module.session_store, "load_session", AsyncMock(return_value=session_data)),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as c:
                    resp = await c.post("/api/recording/stop")
        finally:
            main_module._active_session_id = original_session_id

        assert resp.status_code == 200
        assert resp.json()["segments_count"] == 3
