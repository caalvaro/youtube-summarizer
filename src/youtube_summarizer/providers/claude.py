"""Anthropic Claude implementation of :class:`LLMProvider`.

Uses the streaming Messages API (lower memory footprint for long generations)
with prompt caching on the system prompt — the cache won't help much for
single-shot CLI runs but pays off in any future batch / interactive workflow.
"""

from __future__ import annotations

import os

import anthropic

from .base import retry_call

_DEFAULT_MODEL = "claude-opus-4-7"
_MAX_OUTPUT_TOKENS = 32000


class ClaudeProvider:
    """Sends prompts to Anthropic's Messages API via the streaming endpoint.

    Reads ``ANTHROPIC_API_KEY`` from the environment unless ``api_key`` is
    passed explicitly. Constructs the SDK client eagerly so a missing key
    fails at provider construction (clear error site) rather than deep inside
    the first :meth:`generate` call.
    """

    name = "claude"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        resolved_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not resolved_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY environment variable is not set. "
                "Add it to your environment or .env file before using the Claude provider."
            )
        self.api_key: str = resolved_key
        self.model: str = model or _DEFAULT_MODEL
        self._client = anthropic.Anthropic(api_key=self.api_key)

    def generate(self, *, system: str, user: str) -> str:
        return retry_call(
            lambda: self._call(system=system, user=user),
            is_retriable=self._is_retriable,
        )

    # -- internals --

    def _call(self, *, system: str, user: str) -> str:
        with self._client.messages.stream(
            model=self.model,
            max_tokens=_MAX_OUTPUT_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{"role": "user", "content": user}],
        ) as stream:
            message = stream.get_final_message()
        parts = [block.text for block in message.content if block.type == "text"]
        return "\n".join(parts)

    @staticmethod
    def _is_retriable(exc: BaseException) -> bool:
        """Retry transient failures only. Auth and bad-request errors won't
        improve on retry, so they're allowed to surface immediately."""
        return isinstance(
            exc,
            anthropic.APIConnectionError
            | anthropic.APITimeoutError
            | anthropic.RateLimitError
            | anthropic.InternalServerError,
        )
