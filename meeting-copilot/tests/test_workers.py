"""Tests for reasoning workers — mock dispatcher, verify prompt formatting and response parsing."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.reasoning.workers.base import BaseWorker
from backend.reasoning.workers.summary import SummaryWorker
from backend.reasoning.workers.action_items import ActionItemWorker
from backend.reasoning.workers.contradictions import ContradictionWorker
from backend.ws.protocol import ActionItem, ContradictionAlert


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_dispatcher(return_value: str = "mock response") -> MagicMock:
    """Create a mock dispatcher with an async run method."""
    dispatcher = MagicMock()
    dispatcher.run = AsyncMock(return_value=return_value)
    return dispatcher


def _make_action_item(**overrides) -> ActionItem:
    defaults = {
        "id": "abc123",
        "description": "Do something",
        "assignee": "Alice",
        "source_timestamp": 100.0,
        "status": "new",
    }
    defaults.update(overrides)
    return ActionItem(**defaults)


# ===========================================================================
# BaseWorker
# ===========================================================================

class TestBaseWorker:
    def test_cannot_instantiate_directly(self):
        """BaseWorker is abstract and cannot be instantiated."""
        with pytest.raises(TypeError):
            BaseWorker(MagicMock())

    def test_subclass_must_implement_execute(self):
        """A subclass that doesn't implement execute raises TypeError."""
        class IncompleteWorker(BaseWorker):
            pass

        with pytest.raises(TypeError):
            IncompleteWorker(MagicMock())

    def test_subclass_with_execute_works(self):
        """A subclass implementing execute can be instantiated."""
        class GoodWorker(BaseWorker):
            async def execute(self, **kwargs):
                return "ok"

        worker = GoodWorker(MagicMock())
        assert worker.dispatcher is not None


# ===========================================================================
# SummaryWorker
# ===========================================================================

class TestSummaryWorker:
    @pytest.mark.asyncio
    async def test_calls_dispatcher_with_correct_task(self):
        """SummaryWorker calls dispatcher.run('summary', ...)."""
        dispatcher = _mock_dispatcher("Updated summary text")
        worker = SummaryWorker(dispatcher)

        result = await worker.execute(
            current_summary="Previous summary",
            new_segments="[Speaker A @ 10s]: Hello\n[Speaker B @ 15s]: Hi there",
        )

        dispatcher.run.assert_called_once_with(
            "summary",
            current_summary="Previous summary",
            new_segments="[Speaker A @ 10s]: Hello\n[Speaker B @ 15s]: Hi there",
        )
        assert result == "Updated summary text"

    @pytest.mark.asyncio
    async def test_strips_whitespace_from_result(self):
        """SummaryWorker strips leading/trailing whitespace."""
        dispatcher = _mock_dispatcher("  Summary with spaces  \n")
        worker = SummaryWorker(dispatcher)

        result = await worker.execute(
            current_summary="old",
            new_segments="[Speaker @ 0s]: text",
        )
        assert result == "Summary with spaces"

    @pytest.mark.asyncio
    async def test_empty_segments_returns_current_summary(self):
        """When no new segments, returns existing summary without calling dispatcher."""
        dispatcher = _mock_dispatcher()
        worker = SummaryWorker(dispatcher)

        result = await worker.execute(
            current_summary="Existing summary",
            new_segments="   ",
        )

        dispatcher.run.assert_not_called()
        assert result == "Existing summary"

    @pytest.mark.asyncio
    async def test_first_summary_sends_placeholder(self):
        """On first run (empty summary), sends a placeholder to the LLM."""
        dispatcher = _mock_dispatcher("First summary")
        worker = SummaryWorker(dispatcher)

        await worker.execute(current_summary="", new_segments="[A @ 0s]: Hello")

        call_kwargs = dispatcher.run.call_args[1]
        assert "No summary yet" in call_kwargs["current_summary"]


# ===========================================================================
# ActionItemWorker
# ===========================================================================

class TestActionItemWorker:
    @pytest.mark.asyncio
    async def test_calls_dispatcher_with_correct_task(self):
        """ActionItemWorker calls dispatcher.run('action_items', ...)."""
        dispatcher = _mock_dispatcher('{"new_items": [], "updated_items": []}')
        worker = ActionItemWorker(dispatcher)

        await worker.execute(
            full_context="context",
            recent_transcript="transcript",
            existing_items=[],
        )

        dispatcher.run.assert_called_once()
        assert dispatcher.run.call_args[0][0] == "action_items"

    @pytest.mark.asyncio
    async def test_parses_new_items(self):
        """New action items from LLM response are parsed into ActionItem objects."""
        response = json.dumps({
            "new_items": [
                {"description": "Schedule follow-up", "assignee": "Bob", "type": "action"},
                {"description": "Review budget", "assignee": "TBD", "type": "action"},
            ],
            "updated_items": [],
        })
        dispatcher = _mock_dispatcher(response)
        worker = ActionItemWorker(dispatcher)

        result = await worker.execute(
            full_context="ctx",
            recent_transcript="transcript",
            existing_items=[],
        )

        assert len(result) == 2
        assert result[0].description == "Schedule follow-up"
        assert result[0].assignee == "Bob"
        assert result[0].status == "new"
        assert result[1].description == "Review budget"

    @pytest.mark.asyncio
    async def test_updates_existing_items(self):
        """Existing items can be updated (e.g. marked completed)."""
        existing = _make_action_item(id="item1", description="Do X", status="new")
        response = json.dumps({
            "new_items": [],
            "updated_items": [{"id": "item1", "status": "completed", "note": "Done"}],
        })
        dispatcher = _mock_dispatcher(response)
        worker = ActionItemWorker(dispatcher)

        result = await worker.execute(
            full_context="ctx",
            recent_transcript="transcript",
            existing_items=[existing],
        )

        assert len(result) == 1
        assert result[0].id == "item1"
        assert result[0].status == "completed"

    @pytest.mark.asyncio
    async def test_merges_new_and_existing(self):
        """New items are added alongside existing items."""
        existing = _make_action_item(id="old1", description="Existing task")
        response = json.dumps({
            "new_items": [{"description": "New task", "assignee": "Carol"}],
            "updated_items": [],
        })
        dispatcher = _mock_dispatcher(response)
        worker = ActionItemWorker(dispatcher)

        result = await worker.execute(
            full_context="ctx",
            recent_transcript="transcript",
            existing_items=[existing],
        )

        assert len(result) == 2
        descriptions = {item.description for item in result}
        assert "Existing task" in descriptions
        assert "New task" in descriptions

    @pytest.mark.asyncio
    async def test_handles_invalid_json(self):
        """Invalid JSON response returns existing items unchanged."""
        existing = _make_action_item()
        dispatcher = _mock_dispatcher("This is not JSON at all")
        worker = ActionItemWorker(dispatcher)

        result = await worker.execute(
            full_context="ctx",
            recent_transcript="transcript",
            existing_items=[existing],
        )

        assert len(result) == 1
        assert result[0].id == existing.id

    @pytest.mark.asyncio
    async def test_handles_markdown_code_fences(self):
        """JSON wrapped in markdown code fences is handled correctly."""
        inner = json.dumps({
            "new_items": [{"description": "Fenced item", "assignee": "Dan"}],
            "updated_items": [],
        })
        response = f"```json\n{inner}\n```"
        dispatcher = _mock_dispatcher(response)
        worker = ActionItemWorker(dispatcher)

        result = await worker.execute(
            full_context="ctx",
            recent_transcript="transcript",
            existing_items=[],
        )

        assert len(result) == 1
        assert result[0].description == "Fenced item"

    @pytest.mark.asyncio
    async def test_skips_malformed_new_items(self):
        """Items without a description field are skipped."""
        response = json.dumps({
            "new_items": [
                {"assignee": "No description field"},
                {"description": "Valid item", "assignee": "Eve"},
            ],
            "updated_items": [],
        })
        dispatcher = _mock_dispatcher(response)
        worker = ActionItemWorker(dispatcher)

        result = await worker.execute(
            full_context="ctx",
            recent_transcript="transcript",
            existing_items=[],
        )

        assert len(result) == 1
        assert result[0].description == "Valid item"

    @pytest.mark.asyncio
    async def test_ignores_invalid_status_updates(self):
        """Updates with invalid status values are ignored."""
        existing = _make_action_item(id="item1", status="new")
        response = json.dumps({
            "new_items": [],
            "updated_items": [{"id": "item1", "status": "invalid_status"}],
        })
        dispatcher = _mock_dispatcher(response)
        worker = ActionItemWorker(dispatcher)

        result = await worker.execute(
            full_context="ctx",
            recent_transcript="transcript",
            existing_items=[existing],
        )

        assert result[0].status == "new"  # unchanged

    @pytest.mark.asyncio
    async def test_serializes_existing_items_as_json(self):
        """Existing items are serialized as JSON for the LLM prompt."""
        existing = _make_action_item(id="x1", description="Task X")
        dispatcher = _mock_dispatcher('{"new_items": [], "updated_items": []}')
        worker = ActionItemWorker(dispatcher)

        await worker.execute(
            full_context="ctx",
            recent_transcript="transcript",
            existing_items=[existing],
        )

        call_kwargs = dispatcher.run.call_args[1]
        # The existing_items kwarg should be valid JSON
        parsed = json.loads(call_kwargs["existing_items"])
        assert len(parsed) == 1
        assert parsed[0]["id"] == "x1"


# ===========================================================================
# ContradictionWorker
# ===========================================================================

class TestContradictionWorker:
    @pytest.mark.asyncio
    async def test_calls_dispatcher_with_correct_task(self):
        """ContradictionWorker calls dispatcher.run('contradictions', ...)."""
        response = json.dumps({"contradictions": []})
        dispatcher = _mock_dispatcher(response)
        worker = ContradictionWorker(dispatcher)

        await worker.execute(
            current_summary="Summary so far",
            recent_transcript="[Speaker A @ 10s]: Hello",
        )

        dispatcher.run.assert_called_once()
        assert dispatcher.run.call_args[0][0] == "contradictions"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_transcript(self):
        """Empty transcript returns empty list without calling dispatcher."""
        dispatcher = _mock_dispatcher('{"contradictions": []}')
        worker = ContradictionWorker(dispatcher)

        result = await worker.execute(
            current_summary="Summary",
            recent_transcript="   ",
        )

        dispatcher.run.assert_not_called()
        assert result == []

    @pytest.mark.asyncio
    async def test_parses_contradictions(self):
        """Contradictions from LLM response are parsed into ContradictionAlert objects."""
        response = json.dumps({
            "contradictions": [
                {
                    "description": "Speaker changed position on deadline",
                    "statement_a": "We'll ship by Friday",
                    "statement_b": "I said we need two more weeks",
                    "severity": "high",
                },
            ]
        })
        dispatcher = _mock_dispatcher(response)
        worker = ContradictionWorker(dispatcher)

        result = await worker.execute(
            current_summary="Summary",
            recent_transcript="[Speaker A @ 10s]: text",
        )

        assert len(result) == 1
        alert = result[0]
        assert isinstance(alert, ContradictionAlert)
        assert alert.description == "Speaker changed position on deadline"
        assert alert.statement_a == "We'll ship by Friday"
        assert alert.statement_b == "I said we need two more weeks"
        assert alert.severity == "high"
        assert alert.type == "contradiction_alert"

    @pytest.mark.asyncio
    async def test_returns_empty_list_when_no_contradictions(self):
        """Empty contradictions list from LLM returns empty list."""
        dispatcher = _mock_dispatcher('{"contradictions": []}')
        worker = ContradictionWorker(dispatcher)

        result = await worker.execute(
            current_summary="Summary",
            recent_transcript="[A @ 5s]: All good",
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_invalid_json(self):
        """Invalid JSON response returns empty list."""
        dispatcher = _mock_dispatcher("Not JSON at all")
        worker = ContradictionWorker(dispatcher)

        result = await worker.execute(
            current_summary="Summary",
            recent_transcript="[A @ 5s]: text",
        )

        assert result == []

    @pytest.mark.asyncio
    async def test_handles_markdown_code_fences(self):
        """JSON wrapped in markdown code fences is parsed correctly."""
        inner = json.dumps({
            "contradictions": [
                {
                    "description": "Budget contradiction",
                    "statement_a": "Budget is 100k",
                    "statement_b": "Budget is 50k",
                    "severity": "medium",
                }
            ]
        })
        response = f"```json\n{inner}\n```"
        dispatcher = _mock_dispatcher(response)
        worker = ContradictionWorker(dispatcher)

        result = await worker.execute(
            current_summary="Summary",
            recent_transcript="[A @ 5s]: text",
        )

        assert len(result) == 1
        assert result[0].severity == "medium"

    @pytest.mark.asyncio
    async def test_defaults_unknown_severity_to_low(self):
        """Unknown severity values default to 'low'."""
        response = json.dumps({
            "contradictions": [
                {
                    "description": "Some contradiction",
                    "statement_a": "Statement A",
                    "statement_b": "Statement B",
                    "severity": "unknown_value",
                }
            ]
        })
        dispatcher = _mock_dispatcher(response)
        worker = ContradictionWorker(dispatcher)

        result = await worker.execute(
            current_summary="Summary",
            recent_transcript="[A @ 5s]: text",
        )

        assert len(result) == 1
        assert result[0].severity == "low"

    @pytest.mark.asyncio
    async def test_skips_malformed_contradictions(self):
        """Items missing required 'description' field are skipped."""
        response = json.dumps({
            "contradictions": [
                {"statement_a": "No description field", "severity": "low"},
                {
                    "description": "Valid contradiction",
                    "statement_a": "A",
                    "statement_b": "B",
                    "severity": "high",
                },
            ]
        })
        dispatcher = _mock_dispatcher(response)
        worker = ContradictionWorker(dispatcher)

        result = await worker.execute(
            current_summary="Summary",
            recent_transcript="[A @ 5s]: text",
        )

        assert len(result) == 1
        assert result[0].description == "Valid contradiction"

    @pytest.mark.asyncio
    async def test_uses_placeholder_when_summary_empty(self):
        """When summary is empty, sends placeholder to dispatcher."""
        dispatcher = _mock_dispatcher('{"contradictions": []}')
        worker = ContradictionWorker(dispatcher)

        await worker.execute(
            current_summary="",
            recent_transcript="[A @ 5s]: text",
        )

        call_kwargs = dispatcher.run.call_args[1]
        assert "No summary yet" in call_kwargs["current_summary"]
