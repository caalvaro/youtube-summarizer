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
    at import time is a classic footgun: `.env` reloads, runtime env mutation,
    and tests that mutate env after the package has been imported all silently
    diverge from what the rest of the code sees.

    Tests can override the singleton via::

        monkeypatch.setattr(
            "youtube_summarizer.config._settings",
            Settings(api_key="test-key", model="claude-test"),
        )
    """

    # Default model. Opus 4.7 has high-resolution vision (useful for phase 2 frame
    # selection) and strong long-context handling. Override with YT_SUMMARIZER_MODEL
    # if you want to trade quality for cost (e.g. claude-sonnet-4-6).
    api_key: str | None = field(
        default_factory=lambda: os.getenv("ANTHROPIC_API_KEY")
    )
    model: str = field(
        default_factory=lambda: os.getenv("YT_SUMMARIZER_MODEL", "claude-opus-4-7")
    )


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return the process-wide :class:`Settings` singleton, building it on first call."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
