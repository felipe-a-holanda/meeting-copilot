"""Tests for WebSocket protocol message models."""
import json
import pytest
from backend.ws.protocol import (
    TranscriptSegment,
    SummaryUpdate,
    ActionItem,
    ActionItemsUpdate,
    ContradictionAlert,
    ReplySuggestion,
    CustomPromptResult,
    RequestReplySuggestion,
    CustomPromptRequest,
)


class TestTranscriptSegment:
    def test_defaults(self):
        seg = TranscriptSegment(
            speaker="Speaker 1",
            text="Hello world",
            timestamp_start=0.0,
            timestamp_end=1.5,
        )
        assert seg.type == "transcript_segment"
        assert seg.language == "pt"
        assert seg.is_partial is False

    def test_serialization(self):
        seg = TranscriptSegment(
            speaker="Speaker 1",
            text="Olá",
            timestamp_start=0.0,
            timestamp_end=1.0,
        )
        data = seg.model_dump()
        assert data["type"] == "transcript_segment"
        assert data["speaker"] == "Speaker 1"
        assert data["text"] == "Olá"

    def test_json_round_trip(self):
        seg = TranscriptSegment(
            speaker="Speaker 2",
            text="Test",
            timestamp_start=5.0,
            timestamp_end=6.0,
            is_partial=True,
        )
        raw = json.dumps(seg.model_dump())
        loaded = TranscriptSegment.model_validate_json(raw)
        assert loaded.speaker == seg.speaker
        assert loaded.is_partial is True

    def test_invalid_missing_required(self):
        with pytest.raises(Exception):
            TranscriptSegment(text="No speaker or timestamps")


class TestSummaryUpdate:
    def test_serialization(self):
        su = SummaryUpdate(summary="Meeting about budget.", covered_until=120.0)
        data = su.model_dump()
        assert data["type"] == "summary_update"
        assert data["summary"] == "Meeting about budget."
        assert data["covered_until"] == 120.0

    def test_json_round_trip(self):
        su = SummaryUpdate(summary="Summary text", covered_until=60.5)
        raw = json.dumps(su.model_dump())
        loaded = SummaryUpdate.model_validate_json(raw)
        assert loaded.covered_until == 60.5


class TestActionItem:
    def test_defaults(self):
        item = ActionItem(id="1", description="Send report", source_timestamp=30.0)
        assert item.assignee is None
        assert item.status == "new"

    def test_with_assignee(self):
        item = ActionItem(
            id="2",
            description="Review PR",
            assignee="Speaker 1",
            source_timestamp=45.0,
            status="updated",
        )
        assert item.assignee == "Speaker 1"
        assert item.status == "updated"

    def test_invalid_status(self):
        with pytest.raises(Exception):
            ActionItem(id="3", description="Bad", source_timestamp=0.0, status="invalid")


class TestActionItemsUpdate:
    def test_empty_items(self):
        update = ActionItemsUpdate(items=[])
        data = update.model_dump()
        assert data["type"] == "action_items_update"
        assert data["items"] == []

    def test_with_items(self):
        items = [
            ActionItem(id="1", description="Task A", source_timestamp=10.0),
            ActionItem(id="2", description="Task B", assignee="Speaker 2", source_timestamp=20.0),
        ]
        update = ActionItemsUpdate(items=items)
        data = update.model_dump()
        assert len(data["items"]) == 2
        assert data["items"][0]["description"] == "Task A"

    def test_json_round_trip(self):
        items = [ActionItem(id="x", description="Do thing", source_timestamp=5.0)]
        update = ActionItemsUpdate(items=items)
        raw = json.dumps(update.model_dump())
        loaded = ActionItemsUpdate.model_validate_json(raw)
        assert loaded.items[0].id == "x"


class TestContradictionAlert:
    def test_serialization(self):
        alert = ContradictionAlert(
            description="Contradicts earlier statement",
            statement_a="Budget is 100k",
            statement_a_timestamp=10.0,
            statement_b="Budget is 50k",
            statement_b_timestamp=300.0,
            severity="high",
        )
        data = alert.model_dump()
        assert data["type"] == "contradiction_alert"
        assert data["severity"] == "high"

    def test_invalid_severity(self):
        with pytest.raises(Exception):
            ContradictionAlert(
                description="x",
                statement_a="a",
                statement_a_timestamp=0.0,
                statement_b="b",
                statement_b_timestamp=1.0,
                severity="critical",
            )

    def test_json_round_trip(self):
        alert = ContradictionAlert(
            description="Desc",
            statement_a="A",
            statement_a_timestamp=1.0,
            statement_b="B",
            statement_b_timestamp=2.0,
            severity="low",
        )
        raw = json.dumps(alert.model_dump())
        loaded = ContradictionAlert.model_validate_json(raw)
        assert loaded.severity == "low"


class TestReplySuggestion:
    def test_serialization(self):
        rs = ReplySuggestion(
            suggestions=["Option 1", "Option 2"],
            context="User asked for help",
            triggered_by="manual",
        )
        data = rs.model_dump()
        assert data["type"] == "reply_suggestion"
        assert len(data["suggestions"]) == 2

    def test_invalid_triggered_by(self):
        with pytest.raises(Exception):
            ReplySuggestion(
                suggestions=[],
                context="ctx",
                triggered_by="unknown",
            )

    def test_json_round_trip(self):
        rs = ReplySuggestion(
            suggestions=["Say this"],
            context="ctx",
            triggered_by="auto",
        )
        raw = json.dumps(rs.model_dump())
        loaded = ReplySuggestion.model_validate_json(raw)
        assert loaded.triggered_by == "auto"


class TestCustomPromptResult:
    def test_serialization(self):
        cpr = CustomPromptResult(
            prompt="What were the decisions?",
            result="Decision 1: ...",
            timestamp=500.0,
        )
        data = cpr.model_dump()
        assert data["type"] == "custom_prompt_result"
        assert data["prompt"] == "What were the decisions?"

    def test_json_round_trip(self):
        cpr = CustomPromptResult(prompt="Q", result="A", timestamp=1.0)
        raw = json.dumps(cpr.model_dump())
        loaded = CustomPromptResult.model_validate_json(raw)
        assert loaded.result == "A"


class TestRequestReplySuggestion:
    def test_defaults(self):
        req = RequestReplySuggestion()
        assert req.type == "request_reply"
        assert req.context_hint is None

    def test_with_hint(self):
        req = RequestReplySuggestion(context_hint="Focus on budget")
        data = req.model_dump()
        assert data["context_hint"] == "Focus on budget"

    def test_json_round_trip(self):
        req = RequestReplySuggestion(context_hint="hint")
        raw = json.dumps(req.model_dump())
        loaded = RequestReplySuggestion.model_validate_json(raw)
        assert loaded.context_hint == "hint"


class TestCustomPromptRequest:
    def test_serialization(self):
        req = CustomPromptRequest(prompt="Summarize decisions")
        data = req.model_dump()
        assert data["type"] == "custom_prompt"
        assert data["prompt"] == "Summarize decisions"

    def test_json_round_trip(self):
        req = CustomPromptRequest(prompt="My prompt")
        raw = json.dumps(req.model_dump())
        loaded = CustomPromptRequest.model_validate_json(raw)
        assert loaded.prompt == "My prompt"
