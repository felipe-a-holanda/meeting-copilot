"""Tests for ContradictionWorker and contradiction trigger in ContextManager."""

import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.reasoning.workers.contradictions import ContradictionWorker
from backend.reasoning.context_manager import ContextManager
from backend.ws.protocol import ContradictionAlert, TranscriptSegment


# === ContradictionWorker Tests ===


@pytest.fixture
def mock_dispatcher():
    d = MagicMock()
    d.run = AsyncMock()
    return d


@pytest.fixture
def worker(mock_dispatcher):
    return ContradictionWorker(mock_dispatcher)


@pytest.mark.asyncio
async def test_worker_returns_empty_on_no_transcript(worker):
    result = await worker.execute(current_summary="some summary", recent_transcript="")
    assert result == []


@pytest.mark.asyncio
async def test_worker_returns_empty_on_whitespace_transcript(worker):
    result = await worker.execute(current_summary="some summary", recent_transcript="   \n  ")
    assert result == []


@pytest.mark.asyncio
async def test_worker_calls_dispatcher_with_correct_task(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = '{"contradictions": []}'
    await worker.execute(
        current_summary="Meeting about X",
        recent_transcript="[Speaker A @ 10s]: Let's do Y",
    )
    mock_dispatcher.run.assert_called_once_with(
        "contradictions",
        current_summary="Meeting about X",
        recent_transcript="[Speaker A @ 10s]: Let's do Y",
    )


@pytest.mark.asyncio
async def test_worker_parses_no_contradictions(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = '{"contradictions": []}'
    result = await worker.execute(
        current_summary="summary",
        recent_transcript="transcript",
    )
    assert result == []


@pytest.mark.asyncio
async def test_worker_parses_single_contradiction(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = json.dumps({
        "contradictions": [
            {
                "description": "Speaker changed stance on deadline",
                "statement_a": "We need it by Friday",
                "statement_b": "Monday is fine",
                "severity": "medium",
            }
        ]
    })
    result = await worker.execute(
        current_summary="summary",
        recent_transcript="transcript",
    )
    assert len(result) == 1
    assert isinstance(result[0], ContradictionAlert)
    assert result[0].description == "Speaker changed stance on deadline"
    assert result[0].statement_a == "We need it by Friday"
    assert result[0].statement_b == "Monday is fine"
    assert result[0].severity == "medium"
    assert result[0].type == "contradiction_alert"


@pytest.mark.asyncio
async def test_worker_parses_multiple_contradictions(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = json.dumps({
        "contradictions": [
            {
                "description": "Contradiction 1",
                "statement_a": "A1",
                "statement_b": "B1",
                "severity": "low",
            },
            {
                "description": "Contradiction 2",
                "statement_a": "A2",
                "statement_b": "B2",
                "severity": "high",
            },
        ]
    })
    result = await worker.execute(
        current_summary="summary",
        recent_transcript="transcript",
    )
    assert len(result) == 2
    assert result[0].severity == "low"
    assert result[1].severity == "high"


@pytest.mark.asyncio
async def test_worker_handles_invalid_json(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = "This is not valid JSON at all"
    result = await worker.execute(
        current_summary="summary",
        recent_transcript="transcript",
    )
    assert result == []


@pytest.mark.asyncio
async def test_worker_handles_markdown_fenced_json(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = '```json\n{"contradictions": [{"description": "X", "statement_a": "A", "statement_b": "B", "severity": "low"}]}\n```'
    result = await worker.execute(
        current_summary="summary",
        recent_transcript="transcript",
    )
    assert len(result) == 1
    assert result[0].description == "X"


@pytest.mark.asyncio
async def test_worker_skips_malformed_entries(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = json.dumps({
        "contradictions": [
            {"severity": "low"},  # missing description
            "not a dict",
            {"description": "Valid one", "severity": "high"},
        ]
    })
    result = await worker.execute(
        current_summary="summary",
        recent_transcript="transcript",
    )
    assert len(result) == 1
    assert result[0].description == "Valid one"


@pytest.mark.asyncio
async def test_worker_defaults_invalid_severity_to_low(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = json.dumps({
        "contradictions": [
            {
                "description": "Test",
                "statement_a": "A",
                "statement_b": "B",
                "severity": "extreme",
            }
        ]
    })
    result = await worker.execute(
        current_summary="summary",
        recent_transcript="transcript",
    )
    assert len(result) == 1
    assert result[0].severity == "low"


@pytest.mark.asyncio
async def test_worker_uses_placeholder_summary_when_empty(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = '{"contradictions": []}'
    await worker.execute(
        current_summary="",
        recent_transcript="some transcript",
    )
    mock_dispatcher.run.assert_called_once_with(
        "contradictions",
        current_summary="(No summary yet.)",
        recent_transcript="some transcript",
    )


# === ContextManager Contradiction Trigger Tests ===


def _make_segment(i: int) -> TranscriptSegment:
    return TranscriptSegment(
        speaker=f"Speaker {i % 2}",
        text=f"Segment {i}",
        timestamp_start=float(i * 10),
        timestamp_end=float(i * 10 + 9),
    )


@pytest.mark.asyncio
async def test_contradiction_trigger_fires_after_time_threshold():
    """Contradiction check should fire when enough time has passed."""
    mock_dispatcher = MagicMock()
    mock_dispatcher.run = AsyncMock(return_value='{"contradictions": []}')
    broadcast = AsyncMock()

    cm = ContextManager(
        dispatcher=mock_dispatcher,
        broadcast_fn=broadcast,
        summary_every_n=100,  # high threshold to avoid summary triggers
        action_scan_every_n=100,  # high threshold to avoid action triggers
        contradiction_check_seconds=0,  # fire immediately
    )

    # Adding a segment should trigger contradiction check since threshold is 0
    await cm.on_new_segment(_make_segment(0))

    # Let fire-and-forget tasks complete
    await asyncio.sleep(0.05)

    # Dispatcher should have been called for contradictions
    contradiction_calls = [
        c for c in mock_dispatcher.run.call_args_list
        if c[0][0] == "contradictions"
    ]
    assert len(contradiction_calls) == 1


@pytest.mark.asyncio
async def test_contradiction_trigger_does_not_fire_before_threshold():
    """Contradiction check should NOT fire when not enough time has passed."""
    mock_dispatcher = MagicMock()
    mock_dispatcher.run = AsyncMock(return_value='{"contradictions": []}')
    broadcast = AsyncMock()

    cm = ContextManager(
        dispatcher=mock_dispatcher,
        broadcast_fn=broadcast,
        summary_every_n=100,
        action_scan_every_n=100,
        contradiction_check_seconds=9999,  # very high threshold
    )

    await cm.on_new_segment(_make_segment(0))
    await asyncio.sleep(0.05)

    # No contradiction calls should have been made
    contradiction_calls = [
        c for c in mock_dispatcher.run.call_args_list
        if c[0][0] == "contradictions"
    ]
    assert len(contradiction_calls) == 0


@pytest.mark.asyncio
async def test_contradiction_alerts_are_broadcast():
    """Contradiction alerts should be broadcast to clients."""
    alert_json = json.dumps({
        "contradictions": [
            {
                "description": "Budget conflict",
                "statement_a": "Budget is 100k",
                "statement_b": "Budget is 50k",
                "severity": "high",
            }
        ]
    })
    mock_dispatcher = MagicMock()
    mock_dispatcher.run = AsyncMock(return_value=alert_json)
    broadcast = AsyncMock()

    cm = ContextManager(
        dispatcher=mock_dispatcher,
        broadcast_fn=broadcast,
        summary_every_n=100,
        action_scan_every_n=100,
        contradiction_check_seconds=0,
    )

    await cm.on_new_segment(_make_segment(0))
    await asyncio.sleep(0.05)

    # Find broadcast calls with contradiction_alert type
    contradiction_broadcasts = [
        c for c in broadcast.call_args_list
        if isinstance(c[0][0], dict) and c[0][0].get("type") == "contradiction_alert"
    ]
    assert len(contradiction_broadcasts) == 1
    payload = contradiction_broadcasts[0][0][0]
    assert payload["description"] == "Budget conflict"
    assert payload["severity"] == "high"
