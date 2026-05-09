"""Google Gemini implementation of :class:`LLMProvider`.

Uses the unified ``google-genai`` SDK (the successor to
``google-generativeai``). The free tier on Google AI Studio is sufficient for
moderate personal use of this CLI, which is what motivated adding this
provider in the first place.
"""

from __future__ import annotations

import os

from google import genai
from google.genai import errors as genai_errors
from google.genai import types as genai_types

from .base import retry_call

_DEFAULT_MODEL = "gemini-3-flash-preview"
_MAX_OUTPUT_TOKENS = 32000

# Gemini's rate-limit response is a 429 ClientError. ServerError covers 5xx.
# 429 is *not* a generic ClientError-bad-input — it's worth retrying with
# backoff, identical to how every mature API client handles it.
_HTTP_TOO_MANY_REQUESTS = 429


class GeminiProvider:
    """Sends prompts to Google's Gemini API via the ``google-genai`` SDK.

    Resolves the API key from ``GOOGLE_API_KEY`` (Google's own convention) or
    ``GEMINI_API_KEY`` (matches the naming users may already have set). The
    SDK client is constructed eagerly so a missing key fails at construction.
    """

    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        resolved_key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not resolved_key:
            raise RuntimeError(
                "GOOGLE_API_KEY environment variable is not set. "
                "Add it to your environment or .env file before using the Gemini "
                "provider. Get a free key at https://aistudio.google.com/apikey."
            )
        self.api_key: str = resolved_key
        self.model: str = model or _DEFAULT_MODEL
        self._client = genai.Client(api_key=self.api_key)

    def generate(self, *, system: str, user: str) -> str:
        return retry_call(
            lambda: self._call(system=system, user=user),
            is_retriable=self._is_retriable,
        )

    # -- internals --

    def _call(self, *, system: str, user: str) -> str:
        response = self._client.models.generate_content(
            model=self.model,
            contents=[user],
            config=genai_types.GenerateContentConfig(
                system_instruction=system,
                max_output_tokens=_MAX_OUTPUT_TOKENS,
            ),
        )
        # `.text` is a convenience accessor that joins every text part of the
        # response. It can be `None` if the model produced only non-text parts
        # (tool calls, safety blocks, etc.) — coerce to empty string so the
        # downstream contract validator gets a deterministic input.
        return response.text or ""

    @staticmethod
    def _is_retriable(exc: BaseException) -> bool:
        """5xx responses and *per-minute* 429 rate-limits are retried; daily
        quota exhaustion and other 4xx errors (auth, bad request, content
        policy) are surfaced immediately.

        There are two meaningfully different kinds of 429 from the Gemini API:
        - Per-minute rate limit: retrying with backoff after a short wait works.
        - Per-day (or per-project-day) quota exhaustion: retrying today never
          helps — the quota resets at midnight.  The daily violation IDs contain
          "PerDay" in their ``quotaId`` field; we detect that substring in the
          stringified exception and bail out fast instead of burning retry
          budget uselessly.
        """
        if isinstance(exc, genai_errors.ServerError):
            return True
        if isinstance(exc, genai_errors.ClientError):
            if getattr(exc, "code", None) != _HTTP_TOO_MANY_REQUESTS:
                return False
            # Daily quota exhaustion is not retriable today.
            if "PerDay" in str(exc):
                return False
            return True
        return False
