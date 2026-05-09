"""Tests for youtube_summarizer.writer."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import anthropic
import pytest

from youtube_summarizer.config import Settings
from youtube_summarizer.transcript import Chunk
from youtube_summarizer.writer import _build_user_message, restructure


# ---------------------------------------------------------------------------
# _build_user_message
# ---------------------------------------------------------------------------

class TestBuildUserMessage:
    def test_contains_title(self, two_chunks: list[Chunk]) -> None:
        msg = _build_user_message("My Great Video", "Channel X", two_chunks)
        assert "My Great Video" in msg

    def test_contains_channel(self, two_chunks: list[Chunk]) -> None:
        msg = _build_user_message("Title", "Channel X", two_chunks)
        assert "Channel X" in msg

    def test_contains_chunk_text(self, two_chunks: list[Chunk]) -> None:
        msg = _build_user_message("Title", "Channel", two_chunks)
        for chunk in two_chunks:
            assert chunk.text in msg

    def test_contains_raw_timestamps(self, two_chunks: list[Chunk]) -> None:
        """Downstream frame-alignment depends on raw float timestamps in the message."""
        msg = _build_user_message("Title", "Channel", two_chunks)
        # first chunk starts at 0.0, ends at 45.0
        assert "0.0" in msg
        assert "45.0" in msg

    def test_empty_channel_omitted(self) -> None:
        chunks = [Chunk(start=0.0, end=10.0, text="Hello")]
        msg = _build_user_message("Title", "", chunks)
        # "Channel:" label should not appear when channel is empty
        assert "Channel:" not in msg

    def test_returns_string(self, two_chunks: list[Chunk]) -> None:
        result = _build_user_message("T", "C", two_chunks)
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# restructure (Anthropic client mocked)
# ---------------------------------------------------------------------------

# A markdown response that satisfies the timestamp-comment contract — used as
# the default mock return so tests not focused on the contract aren't tripped
# by the post-condition validator.
_VALID_MARKDOWN = (
    "# Title\n\n## Section A\n<!-- timestamp: 0.0-45.0 -->\n\nContent here.\n"
)


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Override the lazy-settings singleton with a test-safe value.

    The package now reads configuration via :func:`get_settings`, so tests
    inject a known :class:`Settings` instance instead of patching module-level
    globals. Tests that want to exercise the missing-key branch override this
    locally with their own ``Settings(api_key=None)``.
    """
    monkeypatch.setattr(
        "youtube_summarizer.config._settings",
        Settings(api_key="test-key-not-real", model="claude-test"),
    )


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


class TestRestructure:
    def test_returns_string(self, two_chunks: list[Chunk]) -> None:
        mock_stream = _make_mock_stream(_VALID_MARKDOWN)

        with patch("youtube_summarizer.writer.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.stream.return_value = mock_stream
            result = restructure("My Video", "Channel", two_chunks)

        assert isinstance(result, str)

    def test_strips_leading_trailing_whitespace(
        self, two_chunks: list[Chunk]
    ) -> None:
        mock_stream = _make_mock_stream(f"  \n{_VALID_MARKDOWN}  \n")

        with patch("youtube_summarizer.writer.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.stream.return_value = mock_stream
            result = restructure("My Video", "Channel", two_chunks)

        assert result == result.strip()

    def test_passes_title_in_user_message(self, two_chunks: list[Chunk]) -> None:
        """The user message sent to the API must contain the video title."""
        mock_stream = _make_mock_stream(_VALID_MARKDOWN)
        captured_messages: list[dict] = []

        def capture_stream(**kwargs: object) -> MagicMock:
            captured_messages.extend(kwargs.get("messages", []))  # type: ignore[arg-type]
            return mock_stream

        with patch("youtube_summarizer.writer.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.stream.side_effect = capture_stream
            restructure("Unique Title XYZ", "Channel", two_chunks)

        assert any(
            "Unique Title XYZ" in str(m.get("content", ""))
            for m in captured_messages
        )

    def test_passes_api_key_to_client(self, two_chunks: list[Chunk]) -> None:
        """The Anthropic client must be constructed with the resolved api_key.

        Regression: previously we relied on the SDK reading ``ANTHROPIC_API_KEY``
        from env at call time, but the guard read it at import time — letting
        the two diverge silently when env mutated between import and call.
        """
        mock_stream = _make_mock_stream(_VALID_MARKDOWN)

        with patch("youtube_summarizer.writer.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.stream.return_value = mock_stream
            restructure("Title", "Channel", two_chunks)

        MockClient.assert_called_once_with(api_key="test-key-not-real")

    def test_uses_streaming_api(self, two_chunks: list[Chunk]) -> None:
        """Restructure must use client.messages.stream, not client.messages.create."""
        mock_stream = _make_mock_stream(_VALID_MARKDOWN)

        with patch("youtube_summarizer.writer.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.stream.return_value = mock_stream
            restructure("Title", "Channel", two_chunks)

        MockClient.return_value.messages.stream.assert_called_once()
        MockClient.return_value.messages.create.assert_not_called()

    def test_empty_chunks_still_calls_api(self) -> None:
        # No H2 headings expected → contract is vacuously satisfied.
        mock_stream = _make_mock_stream("# Output\n")

        with patch("youtube_summarizer.writer.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.stream.return_value = mock_stream
            result = restructure("Title", "Channel", [])

        assert isinstance(result, str)

    @pytest.mark.parametrize("missing_value", [None, ""])
    def test_raises_when_api_key_missing(
        self,
        two_chunks: list[Chunk],
        monkeypatch: pytest.MonkeyPatch,
        missing_value: str | None,
    ) -> None:
        """Regression: the guard must fire when ANTHROPIC_API_KEY is unset or empty.

        The previous implementation tested ``if not anthropic:``, which checks the
        truthiness of the imported module object — always True — so the guard
        never fired and users hit a less obvious error inside the SDK instead.
        """
        monkeypatch.setattr(
            "youtube_summarizer.config._settings",
            Settings(api_key=missing_value, model="claude-test"),
        )

        with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
            restructure("Title", "Channel", two_chunks)


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestRestructureEdgeCases:
    def test_multiple_text_blocks_joined(self, two_chunks: list[Chunk]) -> None:
        """If the API returns multiple text content blocks they must be joined."""
        block1 = MagicMock()
        block1.type = "text"
        block1.text = "# Part one\n\n## Section\n<!-- timestamp: 0.0-1.0 -->"

        block2 = MagicMock()
        block2.type = "text"
        block2.text = "\n\nMore content"

        final_message = MagicMock()
        final_message.content = [block1, block2]

        stream = MagicMock()
        stream.__enter__ = MagicMock(return_value=stream)
        stream.__exit__ = MagicMock(return_value=False)
        stream.get_final_message.return_value = final_message

        with patch("youtube_summarizer.writer.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.stream.return_value = stream
            result = restructure("Title", "Channel", two_chunks)

        assert "Part one" in result
        assert "More content" in result

    def test_non_text_blocks_ignored(self, two_chunks: list[Chunk]) -> None:
        """Tool-use or image blocks in the response must be silently ignored."""
        text_block = MagicMock()
        text_block.type = "text"
        text_block.text = "# Valid markdown"  # no H2, contract vacuously OK

        tool_block = MagicMock()
        tool_block.type = "tool_use"

        final_message = MagicMock()
        final_message.content = [tool_block, text_block]

        stream = MagicMock()
        stream.__enter__ = MagicMock(return_value=stream)
        stream.__exit__ = MagicMock(return_value=False)
        stream.get_final_message.return_value = final_message

        with patch("youtube_summarizer.writer.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.stream.return_value = stream
            result = restructure("Title", "Channel", two_chunks)

        assert result == "# Valid markdown"


# ---------------------------------------------------------------------------
# Timestamp-comment contract (Phase 2 alignment depends on this)
# ---------------------------------------------------------------------------

class TestTimestampContract:
    def test_raises_when_h2_present_but_no_timestamps(
        self, two_chunks: list[Chunk]
    ) -> None:
        """LLM output with `## ` headings but zero timestamp comments must raise."""
        bad = "# Title\n\n## Section A\n\nContent.\n\n## Section B\n\nMore.\n"
        mock_stream = _make_mock_stream(bad)

        with patch("youtube_summarizer.writer.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.stream.return_value = mock_stream
            with pytest.raises(ValueError, match="timestamp contract"):
                restructure("Title", "Channel", two_chunks)

    def test_passes_when_all_timestamps_present(
        self, two_chunks: list[Chunk]
    ) -> None:
        good = (
            "# Title\n\n"
            "## Section A\n<!-- timestamp: 0.0-45.0 -->\n\nFirst.\n\n"
            "## Section B\n<!-- timestamp: 45.0-90.0 -->\n\nSecond.\n"
        )
        mock_stream = _make_mock_stream(good)

        with patch("youtube_summarizer.writer.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.stream.return_value = mock_stream
            result = restructure("Title", "Channel", two_chunks)

        assert "## Section A" in result
        assert "## Section B" in result

    def test_warns_on_partial_timestamp_coverage(
        self, two_chunks: list[Chunk]
    ) -> None:
        partial = (
            "# Title\n\n"
            "## Section A\n<!-- timestamp: 0.0-45.0 -->\n\nFirst.\n\n"
            "## Section B\n\nSecond — no timestamp.\n"
        )
        mock_stream = _make_mock_stream(partial)

        with patch("youtube_summarizer.writer.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.stream.return_value = mock_stream
            with pytest.warns(UserWarning, match="Timestamp contract is partial"):
                restructure("Title", "Channel", two_chunks)

    def test_no_h2_headings_skips_validation(
        self, two_chunks: list[Chunk]
    ) -> None:
        """Output with only an H1 (degenerate) should not require timestamps."""
        mock_stream = _make_mock_stream("# Title\n\nFlat content.\n")

        with patch("youtube_summarizer.writer.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.stream.return_value = mock_stream
            result = restructure("Title", "Channel", two_chunks)

        assert result == "# Title\n\nFlat content."


# ---------------------------------------------------------------------------
# Retry / backoff
# ---------------------------------------------------------------------------

class TestRetry:
    def test_retries_on_connection_error_and_succeeds(
        self,
        two_chunks: list[Chunk],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A transient APIConnectionError on the first call must be retried."""
        success = _make_mock_stream(_VALID_MARKDOWN)

        attempts = {"count": 0}
        connection_error = anthropic.APIConnectionError(request=MagicMock())

        def stream_side_effect(**_: object) -> MagicMock:
            attempts["count"] += 1
            if attempts["count"] < 2:
                raise connection_error
            return success

        # Don't actually sleep during tests.
        monkeypatch.setattr("youtube_summarizer.writer.time.sleep", lambda _s: None)

        with patch("youtube_summarizer.writer.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.stream.side_effect = stream_side_effect
            result = restructure("Title", "Channel", two_chunks)

        assert attempts["count"] == 2
        assert isinstance(result, str)

    def test_gives_up_after_max_retries(
        self,
        two_chunks: list[Chunk],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If every attempt raises, the last exception must propagate."""
        connection_error = anthropic.APIConnectionError(request=MagicMock())

        attempts = {"count": 0}

        def always_fail(**_: object) -> MagicMock:
            attempts["count"] += 1
            raise connection_error

        monkeypatch.setattr("youtube_summarizer.writer.time.sleep", lambda _s: None)

        with patch("youtube_summarizer.writer.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.stream.side_effect = always_fail
            with pytest.raises(anthropic.APIConnectionError):
                restructure("Title", "Channel", two_chunks)

        assert attempts["count"] == 3  # _MAX_RETRIES

    def test_does_not_retry_on_non_retriable_error(
        self,
        two_chunks: list[Chunk],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Auth and bad-request errors should NOT be retried (they won't improve)."""
        attempts = {"count": 0}

        def always_value_error(**_: object) -> MagicMock:
            attempts["count"] += 1
            raise ValueError("not a retriable anthropic error")

        monkeypatch.setattr("youtube_summarizer.writer.time.sleep", lambda _s: None)

        with patch("youtube_summarizer.writer.anthropic.Anthropic") as MockClient:
            MockClient.return_value.messages.stream.side_effect = always_value_error
            with pytest.raises(ValueError):
                restructure("Title", "Channel", two_chunks)

        assert attempts["count"] == 1
