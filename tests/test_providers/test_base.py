"""Tests for the shared retry helper and Protocol shape."""

from __future__ import annotations

import pytest

from youtube_summarizer.providers.base import LLMProvider, retry_call

# ---------------------------------------------------------------------------
# retry_call
# ---------------------------------------------------------------------------


class TestRetryCall:
    def test_returns_value_on_first_success(self) -> None:
        result = retry_call(lambda: 42, is_retriable=lambda _e: True)
        assert result == 42

    def test_does_not_sleep_on_success(self) -> None:
        sleeps: list[float] = []
        retry_call(lambda: 42, is_retriable=lambda _e: True, sleep=sleeps.append)
        assert sleeps == []

    def test_retries_on_retriable_then_succeeds(self) -> None:
        attempts = {"n": 0}

        def call() -> str:
            attempts["n"] += 1
            if attempts["n"] < 2:
                raise ConnectionError("transient")
            return "ok"

        sleeps: list[float] = []
        result = retry_call(
            call,
            is_retriable=lambda e: isinstance(e, ConnectionError),
            sleep=sleeps.append,
        )
        assert result == "ok"
        assert attempts["n"] == 2
        # Backoff before the (now-successful) retry: base_delay * 2**0 = 1.0.
        assert sleeps == [1.0]

    def test_gives_up_after_max_attempts(self) -> None:
        attempts = {"n": 0}

        def call() -> str:
            attempts["n"] += 1
            raise ConnectionError("forever")

        with pytest.raises(ConnectionError):
            retry_call(
                call,
                is_retriable=lambda _e: True,
                sleep=lambda _s: None,
            )
        assert attempts["n"] == 3  # default `retries=3`

    def test_does_not_retry_non_retriable(self) -> None:
        attempts = {"n": 0}

        def call() -> str:
            attempts["n"] += 1
            raise ValueError("permanent")

        with pytest.raises(ValueError):
            retry_call(
                call,
                is_retriable=lambda e: isinstance(e, ConnectionError),
                sleep=lambda _s: None,
            )
        assert attempts["n"] == 1

    def test_exponential_backoff_schedule(self) -> None:
        sleeps: list[float] = []

        def call() -> str:
            raise ConnectionError("transient")

        with pytest.raises(ConnectionError):
            retry_call(
                call,
                is_retriable=lambda _e: True,
                base_delay=2.0,
                sleep=sleeps.append,
            )
        # 3 attempts → 2 sleeps (no sleep after the final failed attempt).
        # Schedule: 2.0 * 2**0, 2.0 * 2**1.
        assert sleeps == [2.0, 4.0]


# ---------------------------------------------------------------------------
# LLMProvider Protocol
# ---------------------------------------------------------------------------


class TestProtocolShape:
    def test_duck_typed_class_satisfies_protocol(self) -> None:
        class _Fake:
            name = "fake"
            model = "fake-model"

            def generate(self, *, system: str, user: str) -> str:
                return f"{system}/{user}"

        # `runtime_checkable` makes this work without explicit inheritance.
        assert isinstance(_Fake(), LLMProvider)

    def test_class_missing_generate_does_not_satisfy(self) -> None:
        class _Incomplete:
            name = "x"
            model = "y"

        assert not isinstance(_Incomplete(), LLMProvider)
