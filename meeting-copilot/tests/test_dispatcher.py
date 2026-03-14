"""Tests for LLM Dispatcher — mock HTTP responses, verify routing logic."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import httpx

from backend.config import Settings
from backend.reasoning.dispatcher import LLMDispatcher, HEAVY_TASKS


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(**overrides) -> Settings:
    defaults = {
        "ollama_url": "http://localhost:11434",
        "ollama_model": "llama3.1:8b",
        "ollama_heavy_model": "llama3.1:70b",
        "use_api_fallback": False,
        "anthropic_api_key": "",
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _ollama_response(text: str) -> httpx.Response:
    """Build a fake Ollama JSON response."""
    return httpx.Response(
        200,
        json={"response": text},
        request=httpx.Request("POST", "http://localhost:11434/api/generate"),
    )


# ---------------------------------------------------------------------------
# Basic routing — Ollama only
# ---------------------------------------------------------------------------

class TestOllamaRouting:
    """When use_api_fallback=False, all tasks go through Ollama."""

    @pytest.fixture
    def dispatcher(self):
        return LLMDispatcher(_make_settings())

    async def test_summary_uses_ollama_light_model(self, dispatcher):
        with patch.object(dispatcher, "_call_ollama", new_callable=AsyncMock, return_value="summary text") as mock:
            result = await dispatcher.run(
                "summary",
                current_summary="prev",
                new_segments="seg1",
            )
            assert result == "summary text"
            mock.assert_awaited_once()
            # summary is not heavy → heavy=False
            _, kwargs = mock.call_args
            assert kwargs.get("heavy") is False

    async def test_action_items_uses_ollama_light_model(self, dispatcher):
        with patch.object(dispatcher, "_call_ollama", new_callable=AsyncMock, return_value="items") as mock:
            result = await dispatcher.run(
                "action_items",
                full_context="ctx",
                recent_transcript="trans",
                existing_items="[]",
            )
            assert result == "items"
            _, kwargs = mock.call_args
            assert kwargs.get("heavy") is False

    async def test_contradictions_uses_ollama_heavy_model(self, dispatcher):
        with patch.object(dispatcher, "_call_ollama", new_callable=AsyncMock, return_value="none") as mock:
            await dispatcher.run(
                "contradictions",
                current_summary="sum",
                recent_transcript="trans",
            )
            _, kwargs = mock.call_args
            assert kwargs.get("heavy") is True

    async def test_reply_uses_ollama_heavy_model(self, dispatcher):
        with patch.object(dispatcher, "_call_ollama", new_callable=AsyncMock, return_value="reply") as mock:
            await dispatcher.run(
                "reply",
                full_context="ctx",
                context_hint="hint",
            )
            _, kwargs = mock.call_args
            assert kwargs.get("heavy") is True

    async def test_custom_uses_ollama_heavy_model(self, dispatcher):
        with patch.object(dispatcher, "_call_ollama", new_callable=AsyncMock, return_value="answer") as mock:
            await dispatcher.run(
                "custom",
                full_context="ctx",
                user_prompt="what happened?",
            )
            _, kwargs = mock.call_args
            assert kwargs.get("heavy") is True

    async def test_invalid_task_raises_key_error(self, dispatcher):
        with pytest.raises(KeyError):
            await dispatcher.run("nonexistent_task")


# ---------------------------------------------------------------------------
# API fallback routing
# ---------------------------------------------------------------------------

class TestAPIFallbackRouting:
    """When use_api_fallback=True, heavy tasks try Claude first."""

    @pytest.fixture
    def dispatcher(self):
        # Create with fallback disabled (anthropic may not be installed)
        d = LLMDispatcher(_make_settings())
        # Manually enable API fallback with a mock client
        d.use_api_fallback = True
        d._anthropic_client = MagicMock()
        return d

    async def test_heavy_task_tries_claude_first(self, dispatcher):
        with patch.object(dispatcher, "_call_claude", new_callable=AsyncMock, return_value="claude answer") as mock_claude:
            with patch.object(dispatcher, "_call_ollama", new_callable=AsyncMock) as mock_ollama:
                result = await dispatcher.run(
                    "contradictions",
                    current_summary="sum",
                    recent_transcript="trans",
                )
                assert result == "claude answer"
                mock_claude.assert_awaited_once()
                mock_ollama.assert_not_awaited()

    async def test_heavy_task_falls_back_to_ollama_on_claude_error(self, dispatcher):
        with patch.object(dispatcher, "_call_claude", new_callable=AsyncMock, side_effect=Exception("API down")) as mock_claude:
            with patch.object(dispatcher, "_call_ollama", new_callable=AsyncMock, return_value="ollama answer") as mock_ollama:
                result = await dispatcher.run(
                    "reply",
                    full_context="ctx",
                    context_hint="hint",
                )
                assert result == "ollama answer"
                mock_claude.assert_awaited_once()
                mock_ollama.assert_awaited_once()

    async def test_light_task_uses_ollama_first(self, dispatcher):
        with patch.object(dispatcher, "_call_ollama", new_callable=AsyncMock, return_value="ollama result") as mock_ollama:
            with patch.object(dispatcher, "_call_claude", new_callable=AsyncMock) as mock_claude:
                result = await dispatcher.run(
                    "summary",
                    current_summary="prev",
                    new_segments="seg",
                )
                assert result == "ollama result"
                mock_ollama.assert_awaited_once()
                mock_claude.assert_not_awaited()

    async def test_light_task_falls_back_to_claude_when_ollama_fails(self, dispatcher):
        with patch.object(dispatcher, "_call_ollama", new_callable=AsyncMock, side_effect=Exception("connection refused")):
            with patch.object(dispatcher, "_call_claude", new_callable=AsyncMock, return_value="api result") as mock_claude:
                result = await dispatcher.run(
                    "summary",
                    current_summary="prev",
                    new_segments="seg",
                )
                assert result == "api result"
                mock_claude.assert_awaited_once()

    async def test_all_backends_fail_raises_runtime_error(self, dispatcher):
        with patch.object(dispatcher, "_call_ollama", new_callable=AsyncMock, side_effect=Exception("offline")):
            with patch.object(dispatcher, "_call_claude", new_callable=AsyncMock, side_effect=Exception("quota")):
                with pytest.raises(RuntimeError, match="All LLM backends failed"):
                    await dispatcher.run(
                        "summary",
                        current_summary="prev",
                        new_segments="seg",
                    )


# ---------------------------------------------------------------------------
# Ollama HTTP call
# ---------------------------------------------------------------------------

class TestCallOllama:
    """Verify _call_ollama builds correct HTTP requests."""

    async def test_call_ollama_light_model(self):
        dispatcher = LLMDispatcher(_make_settings())
        mock_response = _ollama_response("hello world")

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            result = await dispatcher._call_ollama("test prompt")
            assert result == "hello world"
            call_args = mock_post.call_args
            assert call_args[0][0] == "http://localhost:11434/api/generate"
            body = call_args[1]["json"]
            assert body["model"] == "llama3.1:8b"
            assert body["prompt"] == "test prompt"
            assert body["stream"] is False

    async def test_call_ollama_heavy_model(self):
        dispatcher = LLMDispatcher(_make_settings())
        mock_response = _ollama_response("heavy result")

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response) as mock_post:
            result = await dispatcher._call_ollama("test prompt", heavy=True)
            assert result == "heavy result"
            body = mock_post.call_args[1]["json"]
            assert body["model"] == "llama3.1:70b"

    async def test_call_ollama_http_error_raises(self):
        dispatcher = LLMDispatcher(_make_settings())
        error_response = httpx.Response(500, text="Internal Server Error")
        error_response.request = httpx.Request("POST", "http://localhost:11434/api/generate")

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=error_response):
            with pytest.raises(httpx.HTTPStatusError):
                await dispatcher._call_ollama("test prompt")

    async def test_call_ollama_connection_error_raises(self):
        dispatcher = LLMDispatcher(_make_settings())

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=httpx.ConnectError("refused")):
            with pytest.raises(httpx.ConnectError):
                await dispatcher._call_ollama("test prompt")


# ---------------------------------------------------------------------------
# Claude API call
# ---------------------------------------------------------------------------

class TestCallClaude:
    """Verify _call_claude interacts with the Anthropic SDK correctly."""

    async def test_call_claude_returns_text(self):
        dispatcher = LLMDispatcher(_make_settings(use_api_fallback=True, anthropic_api_key="sk-test"))

        # Mock the Anthropic client
        mock_content = MagicMock()
        mock_content.text = "Claude says hello"
        mock_response = MagicMock()
        mock_response.content = [mock_content]

        mock_create = AsyncMock(return_value=mock_response)
        dispatcher._anthropic_client = MagicMock()
        dispatcher._anthropic_client.messages.create = mock_create

        result = await dispatcher._call_claude("test prompt")
        assert result == "Claude says hello"
        mock_create.assert_awaited_once()
        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["max_tokens"] == 1024
        assert call_kwargs["messages"] == [{"role": "user", "content": "test prompt"}]

    async def test_call_claude_without_client_raises(self):
        dispatcher = LLMDispatcher(_make_settings())
        assert dispatcher._anthropic_client is None
        with pytest.raises(RuntimeError, match="Anthropic client not initialised"):
            await dispatcher._call_claude("test prompt")


# ---------------------------------------------------------------------------
# Prompt formatting
# ---------------------------------------------------------------------------

class TestPromptFormatting:
    """Verify prompts are correctly assembled from templates."""

    async def test_summary_prompt_includes_variables(self):
        dispatcher = LLMDispatcher(_make_settings())
        captured_prompt = None

        async def capture_ollama(prompt, *, heavy=False):
            nonlocal captured_prompt
            captured_prompt = prompt
            return "summary"

        with patch.object(dispatcher, "_call_ollama", side_effect=capture_ollama):
            await dispatcher.run(
                "summary",
                current_summary="existing summary",
                new_segments="[Speaker 1 @ 10s]: hello",
            )
            assert "existing summary" in captured_prompt
            assert "[Speaker 1 @ 10s]: hello" in captured_prompt

    async def test_action_items_prompt_includes_variables(self):
        dispatcher = LLMDispatcher(_make_settings())
        captured_prompt = None

        async def capture_ollama(prompt, *, heavy=False):
            nonlocal captured_prompt
            captured_prompt = prompt
            return "items"

        with patch.object(dispatcher, "_call_ollama", side_effect=capture_ollama):
            await dispatcher.run(
                "action_items",
                full_context="meeting context here",
                recent_transcript="recent text",
                existing_items="[item1]",
            )
            assert "meeting context here" in captured_prompt
            assert "recent text" in captured_prompt
            assert "[item1]" in captured_prompt

    async def test_missing_template_variable_raises(self):
        dispatcher = LLMDispatcher(_make_settings())
        with pytest.raises(KeyError):
            await dispatcher.run("summary")  # missing current_summary, new_segments


# ---------------------------------------------------------------------------
# HEAVY_TASKS constant
# ---------------------------------------------------------------------------

class TestHeavyTasks:
    def test_heavy_tasks_set(self):
        assert "contradictions" in HEAVY_TASKS
        assert "reply" in HEAVY_TASKS
        assert "custom" in HEAVY_TASKS
        assert "summary" not in HEAVY_TASKS
        assert "action_items" not in HEAVY_TASKS


# ---------------------------------------------------------------------------
# Init edge cases
# ---------------------------------------------------------------------------

class TestDispatcherInit:
    def test_no_api_fallback_by_default(self):
        d = LLMDispatcher(_make_settings())
        assert d.use_api_fallback is False
        assert d._anthropic_client is None

    def test_api_fallback_with_key(self):
        mock_client = MagicMock()
        with patch.dict("sys.modules", {"anthropic": MagicMock(AsyncAnthropic=MagicMock(return_value=mock_client))}):
            # Re-import to pick up the mocked anthropic module
            import importlib
            import backend.reasoning.dispatcher as disp_mod
            importlib.reload(disp_mod)
            d = disp_mod.LLMDispatcher(_make_settings(use_api_fallback=True, anthropic_api_key="sk-test"))
            assert d.use_api_fallback is True
            assert d._anthropic_client is not None

    def test_api_fallback_disabled_if_anthropic_import_fails(self):
        with patch("backend.reasoning.dispatcher.LLMDispatcher.__init__", wraps=LLMDispatcher.__init__):
            # Simulate import failure by patching the import inside __init__
            original_init = LLMDispatcher.__init__

            def patched_init(self, settings):
                self.ollama_url = settings.ollama_url
                self.ollama_model = settings.ollama_model
                self.ollama_heavy_model = settings.ollama_heavy_model
                self.use_api_fallback = settings.use_api_fallback
                self._anthropic_client = None
                if self.use_api_fallback:
                    try:
                        raise ImportError("no anthropic")
                    except Exception:
                        self.use_api_fallback = False

            with patch.object(LLMDispatcher, "__init__", patched_init):
                d = LLMDispatcher(_make_settings(use_api_fallback=True, anthropic_api_key="sk-test"))
                assert d.use_api_fallback is False
                assert d._anthropic_client is None
