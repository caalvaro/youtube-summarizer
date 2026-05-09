from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = PROJECT_ROOT / "output"


@dataclass(frozen=True)
class Settings:
    """Lazily-resolved runtime configuration.

    Reads environment variables on construction (not on import). Capturing env
    at import time is a classic footgun: ``.env`` reloads, runtime env mutation,
    and tests that mutate env after the package has been imported all silently
    diverge from what the rest of the code sees.

    The provider's API key (``ANTHROPIC_API_KEY``, ``GOOGLE_API_KEY``, etc.)
    is *not* a Settings field: each provider class is responsible for resolving
    its own key from the environment, which keeps provider-specific naming
    conventions out of the shared configuration object.

    Tests can override the singleton via::

        monkeypatch.setattr(
            "youtube_summarizer.config._settings",
            Settings(provider="claude", model="claude-test"),
        )
    """

    provider: str = field(default_factory=lambda: os.getenv("YT_SUMMARIZER_PROVIDER", "claude"))
    """Which LLM provider to use. One of ``"claude"`` or ``"gemini"``."""

    # Treat empty-string env vars as unset so providers fall back to their
    # built-in default rather than passing ``""`` to the SDK.
    model: str | None = field(default_factory=lambda: os.getenv("YT_SUMMARIZER_MODEL") or None)
    """Optional model override. ``None`` means "use the provider's default"."""


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton, building it on first call."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
