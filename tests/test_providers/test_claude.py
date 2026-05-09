"""Tests for the Anthropic Claude provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import anthropic
import pytest

from youtube_summarizer.providers.claude import ClaudeProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_stream(text: str) -> MagicMock:
    """Build a minimal mock of the anthropic streaming context manager."""
    text_block = MagicMock()
    text_block.type = "text"
    text_block.text = text

    final_message = MagicMock()
    final_message.content = [text_block]

    stream = MagicMock()
    stream.__enter__ = MagicMock(return_value=stream)
    stream.__exit__ = MagicMock(return_value=False)
    stream.get_final_message.return_value = final_message
    return stream


# ---------------------------------------------------------------------------
# API-key resolution
# ---------------------------------------------------------------------------


class TestApiKeyResolution:
    def test_reads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
        with patch("youtube_summarizer.providers.claude.anthropic.Anthropic"):
            p = ClaudeProvider()
        assert p.api_key == "from-env"

    def test_explicit_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
        with patch("youtube_summarizer.providers.claude.anthropic.Anthropic"):
            p = ClaudeProvider(api_key="explicit")
        assert p.api_key == "explicit"

    @pytest.mark.parametrize("missing", [pytest.param(None, id="unset"), ""])
    def test_raises_when_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        missing: str | None,
    ) -> None:
        if missing is None:
            monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        else:
            monkeypatch.setenv("ANTHROPIC_API_KEY", missing)
        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            ClaudeProvider()

    def test_passes_api_key_to_sdk_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Regression: previously the SDK was instantiated without `api_key=`,
        relying on env-read at call time which could diverge from the import-
        time guard."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        with patch("youtube_summarizer.providers.claude.anthropic.Anthropic") as mock_client:
            ClaudeProvider()
        mock_client.assert_called_once_with(api_key="k")


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------


class TestModel:
    def test_default_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        with patch("youtube_summarizer.providers.claude.anthropic.Anthropic"):
            p = ClaudeProvider()
        assert p.model.startswith("claude-")

    def test_explicit_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
        with patch("youtube_summarizer.providers.claude.anthropic.Anthropic"):
            p = ClaudeProvider(model="claude-3-5-sonnet-test")
        assert p.model == "claude-3-5-sonnet-test"


# ---------------------------------------------------------------------------
# generate — SDK call shape
# ---------------------------------------------------------------------------


@pytest.fixture()
def _set_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")


class TestGenerateCallShape:
    def test_uses_streaming_api(self, _set_key: None) -> None:
        """Provider must use messages.stream, not messages.create."""
        with patch("youtube_summarizer.providers.claude.anthropic.Anthropic") as mock_client:
            mock_client.return_value.messages.stream.return_value = _make_mock_stream("result")
            ClaudeProvider().generate(system="sys", user="usr")

        mock_client.return_value.messages.stream.assert_called_once()
        mock_client.return_value.messages.create.assert_not_called()

    def test_passes_system_and_user(self, _set_key: None) -> None:
        captured: dict[str, object] = {}

        def capture(**kwargs: object) -> MagicMock:
            captured.update(kwargs)
            return _make_mock_stream("ok")

        with patch("youtube_summarizer.providers.claude.anthropic.Anthropic") as mock_client:
            mock_client.return_value.messages.stream.side_effect = capture
            ClaudeProvider().generate(system="my-system", user="my-user")

        assert captured["system"][0]["text"] == "my-system"  # type: ignore[index]
        assert captured["messages"][0]["content"] == "my-user"  # type: ignore[index]

    def test_joins_multiple_text_blocks(self, _set_key: None) -> None:
        block1 = MagicMock(type="text")
        block1.text = "Part one"
        block2 = MagicMock(type="text")
        block2.text = "Part two"
        message = MagicMock()
        message.content = [block1, block2]
        stream = MagicMock()
        stream.__enter__ = MagicMock(return_value=stream)
        stream.__exit__ = MagicMock(return_value=False)
        stream.get_final_message.return_value = message

        with patch("youtube_summarizer.providers.claude.anthropic.Anthropic") as mock_client:
            mock_client.return_value.messages.stream.return_value = stream
            result = ClaudeProvider().generate(system="s", user="u")

        assert "Part one" in result
        assert "Part two" in result

    def test_ignores_non_text_blocks(self, _set_key: None) -> None:
        text_block = MagicMock(type="text")
        text_block.text = "the answer"
        tool_block = MagicMock(type="tool_use")
        message = MagicMock()
        message.content = [tool_block, text_block]
        stream = MagicMock()
        stream.__enter__ = MagicMock(return_value=stream)
        stream.__exit__ = MagicMock(return_value=False)
        stream.get_final_message.return_value = message

        with patch("youtube_summarizer.providers.claude.anthropic.Anthropic") as mock_client:
            mock_client.return_value.messages.stream.return_value = stream
            result = ClaudeProvider().generate(system="s", user="u")

        assert result == "the answer"


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------


class TestRetry:
    def test_retries_on_connection_error_and_succeeds(
        self,
        _set_key: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        success = _make_mock_stream("ok")
        attempts = {"n": 0}
        connection_error = anthropic.APIConnectionError(request=MagicMock())

        def stream_side_effect(**_: object) -> MagicMock:
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise connection_error
            return success

        monkeypatch.setattr("youtube_summarizer.providers.base.time.sleep", lambda _s: None)
        with patch("youtube_summarizer.providers.claude.anthropic.Anthropic") as mock_client:
            mock_client.return_value.messages.stream.side_effect = stream_side_effect
            result = ClaudeProvider().generate(system="s", user="u")

        assert attempts["n"] == 2
        assert result == "ok"

    def test_gives_up_after_max_retries(
        self,
        _set_key: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        attempts = {"n": 0}
        connection_error = anthropic.APIConnectionError(request=MagicMock())

        def always_fail(**_: object) -> MagicMock:
            attempts["n"] += 1
            raise connection_error

        monkeypatch.setattr("youtube_summarizer.providers.base.time.sleep", lambda _s: None)
        with patch("youtube_summarizer.providers.claude.anthropic.Anthropic") as mock_client:
            mock_client.return_value.messages.stream.side_effect = always_fail
            with pytest.raises(anthropic.APIConnectionError):
                ClaudeProvider().generate(system="s", user="u")

        assert attempts["n"] == 3

    def test_does_not_retry_value_error(
        self,
        _set_key: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        attempts = {"n": 0}

        def always_value_error(**_: object) -> MagicMock:
            attempts["n"] += 1
            raise ValueError("not a retriable anthropic error")

        monkeypatch.setattr("youtube_summarizer.providers.base.time.sleep", lambda _s: None)
        with patch("youtube_summarizer.providers.claude.anthropic.Anthropic") as mock_client:
            mock_client.return_value.messages.stream.side_effect = always_value_error
            with pytest.raises(ValueError):
                ClaudeProvider().generate(system="s", user="u")

        assert attempts["n"] == 1
