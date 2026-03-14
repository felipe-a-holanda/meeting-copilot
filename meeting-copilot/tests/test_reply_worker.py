"""Tests for ReplyWorker."""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.reasoning.workers.reply import ReplyWorker
from backend.ws.protocol import ReplySuggestion


@pytest.fixture
def mock_dispatcher():
    d = MagicMock()
    d.run = AsyncMock()
    return d


@pytest.fixture
def worker(mock_dispatcher):
    return ReplyWorker(mock_dispatcher)


@pytest.mark.asyncio
async def test_worker_calls_dispatcher_with_reply_task(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = json.dumps({
        "suggestions": ["Let's move forward."],
        "context": "Responding to timeline question",
    })
    await worker.execute(full_context="Meeting transcript here", context_hint="About the timeline")
    mock_dispatcher.run.assert_called_once_with(
        "reply",
        full_context="Meeting transcript here",
        context_hint="About the timeline",
    )


@pytest.mark.asyncio
async def test_worker_returns_reply_suggestion_model(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = json.dumps({
        "suggestions": ["Option A", "Option B", "Option C"],
        "context": "General response",
    })
    result = await worker.execute(full_context="context", context_hint="hint")
    assert isinstance(result, ReplySuggestion)
    assert result.type == "reply_suggestion"
    assert result.triggered_by == "manual"


@pytest.mark.asyncio
async def test_worker_parses_suggestions_list(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = json.dumps({
        "suggestions": ["First suggestion", "Second suggestion", "Third suggestion"],
        "context": "Context note",
    })
    result = await worker.execute(full_context="ctx", context_hint="")
    assert result.suggestions == ["First suggestion", "Second suggestion", "Third suggestion"]
    assert result.context == "Context note"


@pytest.mark.asyncio
async def test_worker_filters_empty_suggestions(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = json.dumps({
        "suggestions": ["Valid", "", "  ", "Also valid"],
        "context": "",
    })
    result = await worker.execute(full_context="ctx", context_hint="")
    assert result.suggestions == ["Valid", "Also valid"]


@pytest.mark.asyncio
async def test_worker_handles_invalid_json(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = "This is not JSON but a plain text reply"
    result = await worker.execute(full_context="ctx", context_hint="some hint")
    assert isinstance(result, ReplySuggestion)
    assert result.suggestions == ["This is not JSON but a plain text reply"]


@pytest.mark.asyncio
async def test_worker_handles_markdown_fenced_json(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = (
        '```json\n'
        '{"suggestions": ["Fenced suggestion"], "context": "Parsed from fence"}\n'
        '```'
    )
    result = await worker.execute(full_context="ctx", context_hint="")
    assert result.suggestions == ["Fenced suggestion"]
    assert result.context == "Parsed from fence"


@pytest.mark.asyncio
async def test_worker_uses_placeholder_when_no_context(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = json.dumps({"suggestions": [], "context": ""})
    await worker.execute(full_context="", context_hint="hint")
    mock_dispatcher.run.assert_called_once_with(
        "reply",
        full_context="(No meeting context yet.)",
        context_hint="hint",
    )


@pytest.mark.asyncio
async def test_worker_uses_default_context_hint_when_missing(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = json.dumps({"suggestions": [], "context": ""})
    await worker.execute(full_context="some context")
    _, kwargs = mock_dispatcher.run.call_args
    assert kwargs["context_hint"] == "No specific context provided."


@pytest.mark.asyncio
async def test_worker_handles_non_list_suggestions(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = json.dumps({
        "suggestions": "not a list",
        "context": "oops",
    })
    result = await worker.execute(full_context="ctx", context_hint="")
    assert result.suggestions == []


@pytest.mark.asyncio
async def test_worker_filters_non_string_suggestions(worker, mock_dispatcher):
    mock_dispatcher.run.return_value = json.dumps({
        "suggestions": ["Valid string", 42, None, "Another valid"],
        "context": "",
    })
    result = await worker.execute(full_context="ctx", context_hint="")
    assert result.suggestions == ["Valid string", "Another valid"]
