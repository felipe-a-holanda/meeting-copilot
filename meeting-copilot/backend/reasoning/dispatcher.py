"""LLM Dispatcher — routes reasoning tasks to Ollama (local) or Claude API (remote)."""

import logging

import httpx

from backend.config import Settings
from backend.reasoning.prompts import PROMPT_MAP

logger = logging.getLogger(__name__)

# Tasks that benefit from higher-quality reasoning → prefer API if available
HEAVY_TASKS: set[str] = {"contradictions", "reply", "custom"}


class LLMDispatcher:
    """Routes LLM tasks to Ollama (local) or Claude API (remote fallback)."""

    def __init__(self, settings: Settings) -> None:
        self.ollama_url: str = settings.ollama_url
        self.ollama_model: str = settings.ollama_model
        self.ollama_heavy_model: str = settings.ollama_heavy_model
        self.use_api_fallback: bool = settings.use_api_fallback
        self._anthropic_client = None

        if self.use_api_fallback:
            try:
                import anthropic
                self._anthropic_client = anthropic.AsyncAnthropic(
                    api_key=settings.anthropic_api_key or None,
                )
            except Exception:
                logger.warning("Failed to initialise Anthropic client; API fallback disabled")
                self.use_api_fallback = False

    async def run(self, task_name: str, **kwargs: str) -> str:
        """Run a reasoning task. Routes to best available backend.

        Args:
            task_name: Key in PROMPT_MAP (e.g. "summary", "action_items").
            **kwargs: Variables to format into the prompt template.

        Returns:
            The LLM-generated text response.

        Raises:
            KeyError: If task_name is not in PROMPT_MAP.
            RuntimeError: If all backends fail.
        """
        prompt_template = PROMPT_MAP[task_name]
        prompt = prompt_template.format(**kwargs)

        # Heavy tasks: try API first if enabled, fallback to local
        if task_name in HEAVY_TASKS and self.use_api_fallback:
            try:
                return await self._call_claude(prompt)
            except Exception as exc:
                logger.warning("Claude API call failed for %s: %s — falling back to Ollama", task_name, exc)

        # Default path: Ollama
        try:
            return await self._call_ollama(prompt, heavy=task_name in HEAVY_TASKS)
        except Exception as exc:
            # If Ollama fails and we haven't tried the API yet, try it as last resort
            if self.use_api_fallback and task_name not in HEAVY_TASKS:
                try:
                    return await self._call_claude(prompt)
                except Exception as api_exc:
                    raise RuntimeError(
                        f"All LLM backends failed for task '{task_name}'"
                    ) from api_exc
            raise RuntimeError(
                f"Ollama call failed for task '{task_name}': {exc}"
            ) from exc

    async def _call_ollama(self, prompt: str, *, heavy: bool = False) -> str:
        """Call the Ollama REST API for text generation."""
        model = self.ollama_heavy_model if heavy else self.ollama_model
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 1024},
                },
            )
            response.raise_for_status()
            return response.json()["response"]

    async def _call_claude(self, prompt: str) -> str:
        """Call the Anthropic Claude API."""
        if self._anthropic_client is None:
            raise RuntimeError("Anthropic client not initialised")
        response = await self._anthropic_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text
