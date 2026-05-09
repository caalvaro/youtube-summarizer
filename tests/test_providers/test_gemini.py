"""Tests for the Google Gemini provider."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors as genai_errors

from youtube_summarizer.providers.gemini import GeminiProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_response(text: str | None) -> MagicMock:
    """Build a minimal mock of a google-genai generate_content response."""
    resp = MagicMock()
    resp.text = text
    return resp


def _make_client_error(code: int) -> genai_errors.ClientError:
    """Construct a real ClientError with a chosen status code without
    poking the SDK's internal ``response`` validation."""
    err = genai_errors.ClientError.__new__(genai_errors.ClientError)
    Exception.__init__(err, f"http {code}")
    err.code = code  # type: ignore[attr-defined]
    return err


def _make_server_error() -> genai_errors.ServerError:
    err = genai_errors.ServerError.__new__(genai_errors.ServerError)
    Exception.__init__(err, "5xx")
    err.code = 503  # type: ignore[attr-defined]
    return err


# ---------------------------------------------------------------------------
# API-key resolution
# ---------------------------------------------------------------------------


class TestApiKeyResolution:
    def test_reads_from_google_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_API_KEY", "from-google-env")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with patch("youtube_summarizer.providers.gemini.genai.Client"):
            p = GeminiProvider()
        assert p.api_key == "from-google-env"

    def test_falls_back_to_gemini_api_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "from-gemini-env")
        with patch("youtube_summarizer.providers.gemini.genai.Client"):
            p = GeminiProvider()
        assert p.api_key == "from-gemini-env"

    def test_google_api_key_takes_precedence(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_API_KEY", "google-wins")
        monkeypatch.setenv("GEMINI_API_KEY", "gemini-loses")
        with patch("youtube_summarizer.providers.gemini.genai.Client"):
            p = GeminiProvider()
        assert p.api_key == "google-wins"

    def test_explicit_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_API_KEY", "from-env")
        with patch("youtube_summarizer.providers.gemini.genai.Client"):
            p = GeminiProvider(api_key="explicit")
        assert p.api_key == "explicit"

    def test_raises_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
            GeminiProvider()

    def test_passes_api_key_to_sdk_client(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_API_KEY", "k")
        with patch("youtube_summarizer.providers.gemini.genai.Client") as mock_client:
            GeminiProvider()
        mock_client.assert_called_once_with(api_key="k")


# ---------------------------------------------------------------------------
# Model resolution
# ---------------------------------------------------------------------------


class TestModel:
    def test_default_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_API_KEY", "k")
        with patch("youtube_summarizer.providers.gemini.genai.Client"):
            p = GeminiProvider()
        assert p.model.startswith("gemini-")

    def test_explicit_model(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GOOGLE_API_KEY", "k")
        with patch("youtube_summarizer.providers.gemini.genai.Client"):
            p = GeminiProvider(model="gemini-test-model")
        assert p.model == "gemini-test-model"


# ---------------------------------------------------------------------------
# generate — SDK call shape
# ---------------------------------------------------------------------------


@pytest.fixture()
def _set_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")


class TestGenerateCallShape:
    def test_passes_system_and_user(self, _set_key: None) -> None:
        captured: dict[str, object] = {}

        def capture(**kwargs: object) -> MagicMock:
            captured.update(kwargs)
            return _make_mock_response("output")

        with patch("youtube_summarizer.providers.gemini.genai.Client") as mock_client:
            mock_client.return_value.models.generate_content.side_effect = capture
            GeminiProvider().generate(system="my-system", user="my-user")

        assert captured["contents"] == ["my-user"]
        # `system_instruction` is on the config object (a GenerateContentConfig).
        assert captured["config"].system_instruction == "my-system"

    def test_returns_text(self, _set_key: None) -> None:
        with patch("youtube_summarizer.providers.gemini.genai.Client") as mock_client:
            mock_client.return_value.models.generate_content.return_value = _make_mock_response(
                "the answer"
            )
            result = GeminiProvider().generate(system="s", user="u")
        assert result == "the answer"

    def test_handles_none_text_response(self, _set_key: None) -> None:
        """If the model returns no text parts (e.g. only safety block), `.text`
        is None — the provider must coerce to an empty string so the writer's
        contract validator gets a deterministic input."""
        with patch("youtube_summarizer.providers.gemini.genai.Client") as mock_client:
            mock_client.return_value.models.generate_content.return_value = _make_mock_response(
                None
            )
            result = GeminiProvider().generate(system="s", user="u")
        assert result == ""


# ---------------------------------------------------------------------------
# Retry policy
# ---------------------------------------------------------------------------


class TestRetry:
    def test_retries_on_server_error_and_succeeds(
        self,
        _set_key: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        attempts = {"n": 0}

        def side_effect(**_: object) -> MagicMock:
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise _make_server_error()
            return _make_mock_response("ok")

        monkeypatch.setattr("youtube_summarizer.providers.base.time.sleep", lambda _s: None)
        with patch("youtube_summarizer.providers.gemini.genai.Client") as mock_client:
            mock_client.return_value.models.generate_content.side_effect = side_effect
            result = GeminiProvider().generate(system="s", user="u")

        assert attempts["n"] == 2
        assert result == "ok"

    def test_retries_on_429_rate_limit(
        self,
        _set_key: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        attempts = {"n": 0}

        def side_effect(**_: object) -> MagicMock:
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise _make_client_error(429)
            return _make_mock_response("ok")

        monkeypatch.setattr("youtube_summarizer.providers.base.time.sleep", lambda _s: None)
        with patch("youtube_summarizer.providers.gemini.genai.Client") as mock_client:
            mock_client.return_value.models.generate_content.side_effect = side_effect
            result = GeminiProvider().generate(system="s", user="u")

        assert attempts["n"] == 2
        assert result == "ok"

    def test_does_not_retry_400_bad_request(
        self,
        _set_key: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """4xx errors other than 429 won't improve on retry — surface immediately."""
        attempts = {"n": 0}

        def side_effect(**_: object) -> MagicMock:
            attempts["n"] += 1
            raise _make_client_error(400)

        monkeypatch.setattr("youtube_summarizer.providers.base.time.sleep", lambda _s: None)
        with patch("youtube_summarizer.providers.gemini.genai.Client") as mock_client:
            mock_client.return_value.models.generate_content.side_effect = side_effect
            with pytest.raises(genai_errors.ClientError):
                GeminiProvider().generate(system="s", user="u")

        assert attempts["n"] == 1

    def test_gives_up_after_max_retries(
        self,
        _set_key: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        attempts = {"n": 0}

        def side_effect(**_: object) -> MagicMock:
            attempts["n"] += 1
            raise _make_server_error()

        monkeypatch.setattr("youtube_summarizer.providers.base.time.sleep", lambda _s: None)
        with patch("youtube_summarizer.providers.gemini.genai.Client") as mock_client:
            mock_client.return_value.models.generate_content.side_effect = side_effect
            with pytest.raises(genai_errors.ServerError):
                GeminiProvider().generate(system="s", user="u")

        assert attempts["n"] == 3
