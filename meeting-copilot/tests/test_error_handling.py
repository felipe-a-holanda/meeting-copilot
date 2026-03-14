"""Tests for error handling and resilience."""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.reasoning.context_manager import ContextManager
from backend.ws.protocol import TranscriptSegment


def make_segment(text: str = "Hello", speaker: str = "Alice") -> TranscriptSegment:
    return TranscriptSegment(
        speaker=speaker,
        text=text,
        timestamp_start=0.0,
        timestamp_end=1.0,
    )


def make_context_manager(worker_side_effect=None):
    """Create a ContextManager with a mocked dispatcher that raises on run()."""
    dispatcher = MagicMock()
    broadcast = AsyncMock()
    cm = ContextManager(
        dispatcher=dispatcher,
        broadcast_fn=broadcast,
        summary_every_n=2,
        action_scan_every_n=2,
        contradiction_check_seconds=9999,
    )
    return cm, broadcast


class TestContextManagerResilience:
    @pytest.mark.asyncio
    async def test_summary_failure_does_not_raise(self):
        cm, broadcast = make_context_manager()
        cm._summary_worker = MagicMock()
        cm._summary_worker.execute = AsyncMock(side_effect=RuntimeError("Ollama down"))

        # Add enough segments to trigger summary
        for i in range(3):
            seg = make_segment(text=f"seg {i}")
            cm.state.add_segment(seg)

        # _run_summary should catch the exception internally
        await cm._run_summary()
        # broadcast was not called with a summary update
        for call in broadcast.call_args_list:
            assert call[0][0].get("type") != "summary_update"

    @pytest.mark.asyncio
    async def test_action_items_failure_does_not_raise(self):
        cm, broadcast = make_context_manager()
        cm._action_item_worker = MagicMock()
        cm._action_item_worker.execute = AsyncMock(side_effect=RuntimeError("Ollama timeout"))

        await cm._run_action_items()
        # Should not raise, state unchanged
        assert cm.state.action_items == []

    @pytest.mark.asyncio
    async def test_contradictions_failure_does_not_raise(self):
        cm, broadcast = make_context_manager()
        cm._contradiction_worker = MagicMock()
        cm._contradiction_worker.execute = AsyncMock(side_effect=RuntimeError("Connection refused"))

        await cm._run_contradictions()
        # Should not raise

    @pytest.mark.asyncio
    async def test_handle_custom_prompt_failure_broadcasts_error(self):
        cm, broadcast = make_context_manager()
        cm._custom_prompt_worker = MagicMock()
        cm._custom_prompt_worker.execute = AsyncMock(side_effect=RuntimeError("LLM unavailable"))

        await cm.handle_custom_prompt("Summarize the key points")

        # Should broadcast an error message
        calls = [c[0][0] for c in broadcast.call_args_list]
        error_calls = [c for c in calls if c.get("type") == "error"]
        assert len(error_calls) == 1
        assert "custom_prompt" in error_calls[0].get("context", "")

    @pytest.mark.asyncio
    async def test_handle_reply_request_failure_broadcasts_error(self):
        cm, broadcast = make_context_manager()
        cm._reply_worker = MagicMock()
        cm._reply_worker.execute = AsyncMock(side_effect=RuntimeError("API rate limit"))

        await cm.handle_reply_request("What should I say?")

        calls = [c[0][0] for c in broadcast.call_args_list]
        error_calls = [c for c in calls if c.get("type") == "error"]
        assert len(error_calls) == 1
        assert "reply_suggestion" in error_calls[0].get("context", "")


class TestDispatcherRateLimitRetry:
    @pytest.mark.asyncio
    async def test_claude_retries_on_rate_limit_then_succeeds(self):
        from backend.config import Settings
        from backend.reasoning.dispatcher import LLMDispatcher

        settings = Settings(use_api_fallback=True, anthropic_api_key="test-key")
        dispatcher = LLMDispatcher.__new__(LLMDispatcher)
        dispatcher.ollama_url = "http://localhost:11434"
        dispatcher.ollama_model = "llama3"
        dispatcher.ollama_heavy_model = "llama3"
        dispatcher.use_api_fallback = True

        # Rate limit error with status_code 429
        rate_limit_exc = Exception("Rate limit exceeded")
        rate_limit_exc.status_code = 429

        call_count = 0

        async def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise rate_limit_exc
            result = MagicMock()
            result.content = [MagicMock(text="retry success")]
            return result

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = mock_create
        dispatcher._anthropic_client = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await dispatcher._call_claude("test prompt")

        assert result == "retry success"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_claude_raises_after_max_retries(self):
        from backend.reasoning.dispatcher import LLMDispatcher

        dispatcher = LLMDispatcher.__new__(LLMDispatcher)
        dispatcher.use_api_fallback = True

        rate_limit_exc = Exception("429 rate limit")
        rate_limit_exc.status_code = 429

        async def always_rate_limit(**kwargs):
            raise rate_limit_exc

        mock_client = MagicMock()
        mock_client.messages = MagicMock()
        mock_client.messages.create = always_rate_limit
        dispatcher._anthropic_client = mock_client

        with patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(Exception):
                await dispatcher._call_claude("test prompt")
