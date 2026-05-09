"""LLM provider abstraction.

The orchestrator (:mod:`youtube_summarizer.writer`) talks to LLMs only through
the :class:`LLMProvider` Protocol defined here. Concrete implementations
(:class:`ClaudeProvider`, :class:`GeminiProvider`) live in sibling modules and
are wired up by :func:`get_provider`.

Adding a new provider:

1. Create ``providers/<name>.py`` with a class that satisfies
   :class:`LLMProvider` (i.e. exposes ``name``, ``model``, and ``generate``).
2. Register it in :data:`_PROVIDERS` below.
3. Add tests under ``tests/test_providers/test_<name>.py``.

No edits to :mod:`writer` or :mod:`cli` are required — that's the point of
the Protocol indirection.
"""

from __future__ import annotations

from collections.abc import Callable

from ..config import Settings, get_settings
from .base import LLMProvider, retry_call
from .claude import ClaudeProvider
from .gemini import GeminiProvider

__all__ = [
    "ClaudeProvider",
    "GeminiProvider",
    "LLMProvider",
    "get_provider",
    "retry_call",
]

# Each factory accepts an optional model override and returns a provider instance.
_PROVIDERS: dict[str, Callable[[str | None], LLMProvider]] = {
    "claude": lambda model: ClaudeProvider(model=model),
    "gemini": lambda model: GeminiProvider(model=model),
}


def get_provider(settings: Settings | None = None) -> LLMProvider:
    """Construct the LLM provider configured by ``settings`` (or the global default).

    Args:
        settings: Optional explicit settings. Defaults to :func:`get_settings`,
            which reads ``YT_SUMMARIZER_PROVIDER`` and ``YT_SUMMARIZER_MODEL``
            from the environment.

    Returns:
        A provider instance ready for :meth:`generate` calls.

    Raises:
        ValueError: ``settings.provider`` is not a known provider name.
        RuntimeError: the chosen provider's API key is not configured.
    """
    settings = settings or get_settings()
    factory = _PROVIDERS.get(settings.provider)
    if factory is None:
        known = ", ".join(sorted(_PROVIDERS))
        raise ValueError(
            f"Unknown provider {settings.provider!r}. "
            f"Set YT_SUMMARIZER_PROVIDER to one of: {known}."
        )
    return factory(settings.model)
