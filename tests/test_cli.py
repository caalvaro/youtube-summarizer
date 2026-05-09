"""CLI smoke tests using Typer's :class:`CliRunner`."""

from __future__ import annotations

import pytest
import yt_dlp.utils
from typer.testing import CliRunner

from youtube_summarizer.cli import app
from youtube_summarizer.config import Settings
from youtube_summarizer.downloader import CaptionsUnavailable

runner = CliRunner()


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default to a present API key for CLI tests; tests that want the
    missing-key branch override locally."""
    monkeypatch.setattr(
        "youtube_summarizer.config._settings",
        Settings(api_key="test-key", model="claude-test"),
    )


# ---------------------------------------------------------------------------
# --help: trivially exits 0
# ---------------------------------------------------------------------------

class TestHelp:
    def test_help_exits_zero(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        # Typer renders our app help text; just check our own description shows up.
        assert "youtube" in result.stdout.lower()


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------

class TestErrorExits:
    def test_missing_api_key_exits_two(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Exit code 2 (config error) when ANTHROPIC_API_KEY is unset."""
        monkeypatch.setattr(
            "youtube_summarizer.config._settings",
            Settings(api_key=None, model="claude-test"),
        )
        result = runner.invoke(app, ["https://www.youtube.com/watch?v=fake"])
        assert result.exit_code == 2
        assert "ANTHROPIC_API_KEY" in result.stdout

    def test_captions_unavailable_exits_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Caption-fetch failure should produce a clean exit-1, not a traceback."""
        def fake_fetch(*_args: object, **_kwargs: object) -> None:
            raise CaptionsUnavailable("no captions for this URL")

        monkeypatch.setattr("youtube_summarizer.cli.downloader.fetch", fake_fetch)
        result = runner.invoke(app, ["https://www.youtube.com/watch?v=fake"])
        assert result.exit_code == 1
        assert "no captions for this URL" in result.stdout

    def test_yt_dlp_download_error_exits_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """yt-dlp's typed errors should be caught and translated to exit-1.

        Regression: previously only ``CaptionsUnavailable`` was wrapped; a
        ``DownloadError`` (network blip, video removed, age-gated) printed a
        full traceback at the user.
        """
        def fake_fetch(*_args: object, **_kwargs: object) -> None:
            raise yt_dlp.utils.DownloadError("network unreachable")

        monkeypatch.setattr("youtube_summarizer.cli.downloader.fetch", fake_fetch)
        result = runner.invoke(app, ["https://www.youtube.com/watch?v=fake"])
        assert result.exit_code == 1
        assert "Failed to fetch video" in result.stdout
