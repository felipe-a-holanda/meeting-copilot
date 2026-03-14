"""Tests for ContextManager and MeetingState."""

import asyncio
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from backend.ws.protocol import TranscriptSegment, ActionItem
from backend.reasoning.context_manager import MeetingState, ContextManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_segment(
    text: str = "Hello",
    speaker: str = "Speaker_A",
    start: float = 0.0,
    end: float = 1.0,
) -> TranscriptSegment:
    return TranscriptSegment(
        speaker=speaker,
        text=text,
        timestamp_start=start,
        timestamp_end=end,
    )


# ---------------------------------------------------------------------------
# MeetingState unit tests
# ---------------------------------------------------------------------------


class TestMeetingState:
    def test_initial_state(self):
        state = MeetingState(session_id="s1", start_time=0.0)
        assert state.segments == []
        assert state.speakers == set()
        assert state.current_summary == ""
        assert state.action_items == []
        assert state.segments_since_last_summary == 0
        assert state.segments_since_last_action_scan == 0

    def test_add_segment_accumulates(self):
        state = MeetingState(session_id="s1", start_time=0.0)
        seg = make_segment(text="Test", speaker="Alice")
        state.add_segment(seg)

        assert len(state.segments) == 1
        assert "Alice" in state.speakers
        assert state.segments_since_last_summary == 1
        assert state.segments_since_last_action_scan == 1

    def test_add_multiple_segments(self):
        state = MeetingState(session_id="s1", start_time=0.0)
        for i in range(5):
            state.add_segment(make_segment(text=f"Word {i}", speaker="Alice"))
        assert len(state.segments) == 5
        assert state.segments_since_last_summary == 5

    def test_add_segments_multiple_speakers(self):
        state = MeetingState(session_id="s1", start_time=0.0)
        state.add_segment(make_segment(speaker="Alice"))
        state.add_segment(make_segment(speaker="Bob"))
        assert state.speakers == {"Alice", "Bob"}

    def test_recent_window_maxlen(self):
        state = MeetingState(session_id="s1", start_time=0.0)
        state.recent_window = deque(maxlen=3)
        for i in range(5):
            state.add_segment(make_segment(text=f"seg{i}"))
        assert len(state.recent_window) == 3
        texts = [s.text for s in state.recent_window]
        assert texts == ["seg2", "seg3", "seg4"]

    def test_get_transcript_text_all(self):
        state = MeetingState(session_id="s1", start_time=0.0)
        state.add_segment(make_segment(text="Hello", speaker="Alice", start=0.0, end=1.0))
        state.add_segment(make_segment(text="World", speaker="Bob", start=1.0, end=2.0))
        text = state.get_transcript_text()
        assert "Alice" in text
        assert "Bob" in text
        assert "Hello" in text
        assert "World" in text

    def test_get_transcript_text_last_n(self):
        state = MeetingState(session_id="s1", start_time=0.0)
        for i in range(10):
            state.add_segment(make_segment(text=f"seg{i}", speaker="Alice", start=float(i), end=float(i + 1)))
        text = state.get_transcript_text(last_n=3)
        assert "seg9" in text
        assert "seg8" in text
        assert "seg7" in text
        assert "seg0" not in text

    def test_get_full_context_no_summary(self):
        state = MeetingState(session_id="s1", start_time=0.0)
        state.add_segment(make_segment(text="Hello"))
        ctx = state.get_full_context()
        assert "Recent Transcript" in ctx
        assert "Summary" not in ctx

    def test_get_full_context_with_summary(self):
        state = MeetingState(session_id="s1", start_time=0.0)
        state.current_summary = "Meeting is about project X"
        state.add_segment(make_segment(text="Hello"))
        ctx = state.get_full_context()
        assert "Summary So Far" in ctx
        assert "Meeting is about project X" in ctx

    def test_get_full_context_with_action_items(self):
        state = MeetingState(session_id="s1", start_time=0.0)
        state.action_items = [
            ActionItem(
                id="1",
                description="Fix the bug",
                assignee="Alice",
                source_timestamp=5.0,
            )
        ]
        state.add_segment(make_segment(text="OK"))
        ctx = state.get_full_context()
        assert "Action Items" in ctx
        assert "Fix the bug" in ctx
        assert "Alice" in ctx


# ---------------------------------------------------------------------------
# ContextManager tests
# ---------------------------------------------------------------------------


class TestContextManagerTriggers:
    def _make_manager(
        self,
        summary_every_n: int = 5,
        action_scan_every_n: int = 3,
        broadcast_calls: list | None = None,
        dispatcher_return: str = "LLM result",
    ) -> tuple["ContextManager", AsyncMock]:
        broadcast_fn = AsyncMock()
        dispatcher = AsyncMock()
        dispatcher.run = AsyncMock(return_value=dispatcher_return)
        cm = ContextManager(
            dispatcher=dispatcher,
            broadcast_fn=broadcast_fn,
            summary_every_n=summary_every_n,
            action_scan_every_n=action_scan_every_n,
            session_id="test-session",
        )
        return cm, broadcast_fn

    @pytest.mark.asyncio
    async def test_segment_is_broadcast(self):
        cm, broadcast_fn = self._make_manager()
        seg = make_segment(text="Hello")
        await cm.on_new_segment(seg)
        broadcast_fn.assert_called_once()
        call_args = broadcast_fn.call_args[0][0]
        assert call_args["text"] == "Hello"

    @pytest.mark.asyncio
    async def test_summary_trigger_fires_at_threshold(self):
        cm, broadcast_fn = self._make_manager(summary_every_n=3)
        for i in range(3):
            await cm.on_new_segment(make_segment(text=f"s{i}", start=float(i), end=float(i + 1)))
        # Allow tasks to run
        await asyncio.sleep(0)
        # Counter resets
        assert cm.state.segments_since_last_summary == 0

    @pytest.mark.asyncio
    async def test_summary_trigger_does_not_fire_before_threshold(self):
        cm, broadcast_fn = self._make_manager(summary_every_n=5)
        for i in range(4):
            await cm.on_new_segment(make_segment(text=f"s{i}", start=float(i), end=float(i + 1)))
        await asyncio.sleep(0)
        # Counter not reset yet
        assert cm.state.segments_since_last_summary == 4

    @pytest.mark.asyncio
    async def test_action_scan_trigger_fires_at_threshold(self):
        cm, broadcast_fn = self._make_manager(action_scan_every_n=3)
        for i in range(3):
            await cm.on_new_segment(make_segment(text=f"s{i}", start=float(i), end=float(i + 1)))
        await asyncio.sleep(0)
        assert cm.state.segments_since_last_action_scan == 0

    @pytest.mark.asyncio
    async def test_action_scan_does_not_fire_before_threshold(self):
        cm, broadcast_fn = self._make_manager(action_scan_every_n=5)
        for i in range(4):
            await cm.on_new_segment(make_segment(text=f"s{i}", start=float(i), end=float(i + 1)))
        await asyncio.sleep(0)
        assert cm.state.segments_since_last_action_scan == 4

    @pytest.mark.asyncio
    async def test_summary_calls_dispatcher(self):
        cm, broadcast_fn = self._make_manager(summary_every_n=2)
        for i in range(2):
            await cm.on_new_segment(make_segment(text=f"s{i}", start=float(i), end=float(i + 1)))
        await asyncio.sleep(0)
        cm.dispatcher.run.assert_called_with(
            "summary",
            current_summary="",
            new_segments=cm.state.get_transcript_text(last_n=2),
        )

    @pytest.mark.asyncio
    async def test_summary_broadcasts_summary_update(self):
        cm, broadcast_fn = self._make_manager(summary_every_n=2)
        cm.dispatcher.run = AsyncMock(return_value="Summarized text")
        for i in range(2):
            await cm.on_new_segment(make_segment(text=f"s{i}", start=float(i), end=float(i + 1)))
        # Let the background task run
        await asyncio.sleep(0.01)
        # First call is the segment broadcast, second should be summary
        calls = broadcast_fn.call_args_list
        types = [c[0][0].get("type") for c in calls]
        assert "summary_update" in types

    @pytest.mark.asyncio
    async def test_action_scan_broadcasts_action_items_update(self):
        cm, broadcast_fn = self._make_manager(action_scan_every_n=2)
        cm.dispatcher.run = AsyncMock(return_value="[]")
        for i in range(2):
            await cm.on_new_segment(make_segment(text=f"s{i}", start=float(i), end=float(i + 1)))
        await asyncio.sleep(0.01)
        calls = broadcast_fn.call_args_list
        types = [c[0][0].get("type") for c in calls]
        assert "action_items_update" in types

    @pytest.mark.asyncio
    async def test_handle_custom_prompt(self):
        cm, broadcast_fn = self._make_manager()
        cm.dispatcher.run = AsyncMock(return_value="Custom LLM answer")
        cm.state.add_segment(make_segment(text="Segment", start=0.0, end=1.0))

        await cm.handle_custom_prompt("What was decided?")

        cm.dispatcher.run.assert_called_with(
            "custom",
            full_context=cm.state.get_full_context(),
            user_prompt="What was decided?",
        )
        broadcast_fn.assert_called_once()
        result = broadcast_fn.call_args[0][0]
        assert result["type"] == "custom_prompt_result"
        assert result["prompt"] == "What was decided?"
        assert result["result"] == "Custom LLM answer"

    @pytest.mark.asyncio
    async def test_handle_custom_prompt_no_segments(self):
        cm, broadcast_fn = self._make_manager()
        cm.dispatcher.run = AsyncMock(return_value="Answer")
        await cm.handle_custom_prompt("What happened?")
        result = broadcast_fn.call_args[0][0]
        assert result["timestamp"] == 0.0

    @pytest.mark.asyncio
    async def test_handle_reply_request(self):
        cm, broadcast_fn = self._make_manager()
        cm.dispatcher.run = AsyncMock(return_value={"suggestions": ["OK", "Sure"]})
        cm.state.add_segment(make_segment(text="Let's talk"))

        await cm.handle_reply_request("more context here")

        cm.dispatcher.run.assert_called_with(
            "reply",
            full_context=cm.state.get_full_context(),
            context_hint="more context here",
        )
        broadcast_fn.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_reply_request_no_hint(self):
        cm, broadcast_fn = self._make_manager()
        cm.dispatcher.run = AsyncMock(return_value={"suggestions": []})
        await cm.handle_reply_request()
        cm.dispatcher.run.assert_called_with(
            "reply",
            full_context=cm.state.get_full_context(),
            context_hint="No specific context provided.",
        )

    @pytest.mark.asyncio
    async def test_multiple_trigger_cycles(self):
        """Trigger fires twice after 2*threshold segments."""
        cm, broadcast_fn = self._make_manager(summary_every_n=3, action_scan_every_n=3)
        for i in range(6):
            await cm.on_new_segment(make_segment(text=f"s{i}", start=float(i), end=float(i + 1)))
        await asyncio.sleep(0.01)
        # dispatcher.run should have been called for both summary and action_items x2
        assert cm.dispatcher.run.call_count >= 4

    def test_custom_thresholds_stored(self):
        cm, _ = self._make_manager(summary_every_n=7, action_scan_every_n=2)
        assert cm.SUMMARY_EVERY_N_SEGMENTS == 7
        assert cm.ACTION_SCAN_EVERY_N_SEGMENTS == 2

    def test_default_thresholds(self):
        broadcast_fn = AsyncMock()
        dispatcher = AsyncMock()
        cm = ContextManager(dispatcher=dispatcher, broadcast_fn=broadcast_fn)
        assert cm.SUMMARY_EVERY_N_SEGMENTS == 10
        assert cm.ACTION_SCAN_EVERY_N_SEGMENTS == 5
        assert cm.CONTRADICTION_CHECK_SECONDS == 120
