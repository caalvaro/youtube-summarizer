"""CLI smoke tests using Typer's :class:`CliRunner`."""

from __future__ import annotations

import pytest
import yt_dlp.utils
from typer.testing import CliRunner

from youtube_summarizer.cli import app
from youtube_summarizer.downloader import CaptionsUnavailableError

runner = CliRunner()


# ---------------------------------------------------------------------------
# A FakeProvider used to short-circuit get_provider() without env-var setup.
# ---------------------------------------------------------------------------


class _FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, *, model: str | None = None) -> None:
        # The factory always passes `model=...`; accept it for shape compatibility.
        self.model = model or "fake-model"

    def generate(self, *, system: str, user: str) -> str:
        return "# Title\n"  # no H2 → contract vacuously satisfied


@pytest.fixture(autouse=True)
def _stub_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Swap in a fake provider class for every CLI test by default.

    Tests that want to exercise the missing-key / unknown-provider paths
    override the ``--provider`` flag locally, which routes back through the
    real registry."""
    from youtube_summarizer import providers as providers_module

    monkeypatch.setitem(
        providers_module._PROVIDERS, "fake", lambda model: _FakeProvider(model=model)
    )
    # Make 'fake' the default provider for the duration of the test.
    monkeypatch.setenv("YT_SUMMARIZER_PROVIDER", "fake")
    monkeypatch.setattr("youtube_summarizer.config._settings", None)


# ---------------------------------------------------------------------------
# --help: trivially exits 0
# ---------------------------------------------------------------------------


class TestHelp:
    def test_help_exits_zero(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "youtube" in result.stdout.lower()

    def test_help_lists_provider_flag(self) -> None:
        result = runner.invoke(app, ["run", "--help"])
        assert "--provider" in result.stdout
        assert "--model" in result.stdout


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestErrorExits:
    def test_unknown_provider_exits_two(self, monkeypatch: pytest.MonkeyPatch) -> None:
        result = runner.invoke(
            app,
            ["run", "https://www.youtube.com/watch?v=fake", "--provider", "totally-bogus"],
        )
        assert result.exit_code == 2
        assert "Unknown provider" in result.stdout

    def test_missing_api_key_exits_two(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When the user picks a real provider but hasn't configured its key."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        result = runner.invoke(
            app,
            ["run", "https://www.youtube.com/watch?v=fake", "--provider", "claude"],
        )
        assert result.exit_code == 2
        assert "ANTHROPIC_API_KEY" in result.stdout

    def test_captions_unavailable_exits_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_fetch(*_args: object, **_kwargs: object) -> None:
            raise CaptionsUnavailableError("no captions for this URL")

        monkeypatch.setattr("youtube_summarizer.cli.downloader.fetch", fake_fetch)
        result = runner.invoke(app, ["run", "https://www.youtube.com/watch?v=fake"])
        assert result.exit_code == 1
        assert "no captions for this URL" in result.stdout

    def test_yt_dlp_download_error_exits_one(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def fake_fetch(*_args: object, **_kwargs: object) -> None:
            raise yt_dlp.utils.DownloadError("network unreachable")

        monkeypatch.setattr("youtube_summarizer.cli.downloader.fetch", fake_fetch)
        result = runner.invoke(app, ["run", "https://www.youtube.com/watch?v=fake"])
        assert result.exit_code == 1
        assert "Failed to fetch video" in result.stdout
