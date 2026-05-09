"""Tests for the provider factory (`get_provider`)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from youtube_summarizer.config import Settings
from youtube_summarizer.providers import (
    ClaudeProvider,
    GeminiProvider,
    get_provider,
)


class TestGetProvider:
    def test_routes_to_claude(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        with patch("youtube_summarizer.providers.claude.anthropic.Anthropic"):
            p = get_provider(Settings(provider="claude", model=None))
        assert isinstance(p, ClaudeProvider)

    def test_routes_to_gemini(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_API_KEY", "k")
        with patch("youtube_summarizer.providers.gemini.genai.Client"):
            p = get_provider(Settings(provider="gemini", model=None))
        assert isinstance(p, GeminiProvider)

    def test_passes_model_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        with patch("youtube_summarizer.providers.claude.anthropic.Anthropic"):
            p = get_provider(Settings(provider="claude", model="custom-model"))
        assert p.model == "custom-model"

    def test_falls_back_to_provider_default_model_when_settings_model_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        with patch("youtube_summarizer.providers.claude.anthropic.Anthropic"):
            p = get_provider(Settings(provider="claude", model=None))
        assert p.model.startswith("claude-")

    def test_unknown_provider_raises_value_error(self) -> None:
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider(Settings(provider="not-a-real-provider", model=None))

    def test_uses_global_settings_when_none_passed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        monkeypatch.setattr(
            "youtube_summarizer.config._settings",
            Settings(provider="claude", model="claude-via-global"),
        )
        with patch("youtube_summarizer.providers.claude.anthropic.Anthropic"):
            p = get_provider()
        assert p.model == "claude-via-global"

    def test_propagates_missing_api_key_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            get_provider(Settings(provider="claude", model=None))
