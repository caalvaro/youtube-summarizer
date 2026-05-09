"""Tests for youtube_summarizer.writer.

The writer is now a pure orchestrator — provider-agnostic — so these tests
inject a :class:`FakeProvider` instead of mocking SDK internals. Provider-
specific tests (SDK call shape, retry policy, API-key resolution) live under
``tests/test_providers/``.
"""

from __future__ import annotations

import re
import warnings

import pytest

from youtube_summarizer.transcript import Chunk
from youtube_summarizer.writer import (
    CONTINUATION_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    _build_user_message,
    _segment_chunks,
    restructure,
    restructure_segmented,
)

# ---------------------------------------------------------------------------
# FakeProvider — satisfies the LLMProvider Protocol structurally
# ---------------------------------------------------------------------------


class FakeProvider:
    """In-memory provider for tests.

    Records every (system, user) call and returns a pre-set response. Replaces
    the previous pattern of mocking ``anthropic.Anthropic`` deep inside the
    streaming context manager — much cleaner now that the writer talks to
    providers through the Protocol.
    """

    name = "fake"
    model = "fake-model"

    def __init__(self, response: str = "# Title\n") -> None:
        self.response = response
        self.calls: list[dict[str, str]] = []

    def generate(self, *, system: str, user: str) -> str:
        self.calls.append({"system": system, "user": user})
        return self.response


# A markdown response that satisfies the timestamp-comment contract — used as
# the default fake response so tests not focused on the contract aren't
# tripped by the post-condition validator.
_VALID_MARKDOWN = "# Title\n\n## Section A\n<!-- timestamp: 0.0-45.0 -->\n\nContent here.\n"


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
# restructure — orchestration only (provider mocked)
# ---------------------------------------------------------------------------


class TestRestructure:
    def test_returns_string(self, two_chunks: list[Chunk]) -> None:
        fake = FakeProvider(response=_VALID_MARKDOWN)
        result = restructure("My Video", "Channel", two_chunks, provider=fake)
        assert isinstance(result, str)

    def test_strips_leading_trailing_whitespace(self, two_chunks: list[Chunk]) -> None:
        fake = FakeProvider(response=f"  \n{_VALID_MARKDOWN}  \n")
        result = restructure("My Video", "Channel", two_chunks, provider=fake)
        assert result == result.strip()

    def test_passes_title_in_user_message(self, two_chunks: list[Chunk]) -> None:
        """The user message handed to the provider must contain the video title."""
        fake = FakeProvider(response=_VALID_MARKDOWN)
        restructure("Unique Title XYZ", "Channel", two_chunks, provider=fake)
        assert any("Unique Title XYZ" in call["user"] for call in fake.calls)

    def test_passes_system_prompt_to_provider(self, two_chunks: list[Chunk]) -> None:
        """The system prompt sent to the provider must declare the timestamp contract."""
        fake = FakeProvider(response=_VALID_MARKDOWN)
        restructure("T", "C", two_chunks, provider=fake)
        assert "<!-- timestamp:" in fake.calls[0]["system"]

    def test_empty_chunks_still_calls_provider(self) -> None:
        fake = FakeProvider(response="# Output\n")  # no H2 → contract OK
        result = restructure("Title", "Channel", [], provider=fake)
        assert isinstance(result, str)
        assert len(fake.calls) == 1

    def test_explicit_provider_used_over_factory_default(
        self,
        two_chunks: list[Chunk],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Injecting an explicit provider must short-circuit the factory.

        Regression guard against accidentally calling get_provider() even when
        the caller supplied one — that would defeat dependency injection and
        force every test to also configure env vars.
        """
        called = {"factory": False}

        def boom(*_a: object, **_kw: object) -> None:
            called["factory"] = True
            raise AssertionError("factory should not have been called")

        monkeypatch.setattr("youtube_summarizer.writer.get_provider", boom)

        fake = FakeProvider(response=_VALID_MARKDOWN)
        restructure("T", "C", two_chunks, provider=fake)
        assert not called["factory"]


# ---------------------------------------------------------------------------
# Timestamp-comment contract (Phase 2 alignment depends on this)
# ---------------------------------------------------------------------------


class TestTimestampContract:
    def test_raises_when_h2_present_but_no_timestamps(self, two_chunks: list[Chunk]) -> None:
        """LLM output with `## ` headings but zero timestamp comments must raise."""
        bad = "# Title\n\n## Section A\n\nContent.\n\n## Section B\n\nMore.\n"
        fake = FakeProvider(response=bad)
        with pytest.raises(ValueError, match="timestamp contract"):
            restructure("Title", "Channel", two_chunks, provider=fake)

    def test_passes_when_all_timestamps_present(self, two_chunks: list[Chunk]) -> None:
        good = (
            "# Title\n\n"
            "## Section A\n<!-- timestamp: 0.0-45.0 -->\n\nFirst.\n\n"
            "## Section B\n<!-- timestamp: 45.0-90.0 -->\n\nSecond.\n"
        )
        fake = FakeProvider(response=good)
        result = restructure("Title", "Channel", two_chunks, provider=fake)
        assert "## Section A" in result
        assert "## Section B" in result

    def test_warns_on_partial_timestamp_coverage(self, two_chunks: list[Chunk]) -> None:
        partial = (
            "# Title\n\n"
            "## Section A\n<!-- timestamp: 0.0-45.0 -->\n\nFirst.\n\n"
            "## Section B\n\nSecond — no timestamp.\n"
        )
        fake = FakeProvider(response=partial)
        with pytest.warns(UserWarning, match="Timestamp contract is partial"):
            restructure("Title", "Channel", two_chunks, provider=fake)

    def test_no_h2_headings_skips_validation(self, two_chunks: list[Chunk]) -> None:
        """Output with only an H1 (degenerate) should not require timestamps."""
        fake = FakeProvider(response="# Title\n\nFlat content.\n")
        result = restructure("Title", "Channel", two_chunks, provider=fake)
        assert result == "# Title\n\nFlat content."


# ---------------------------------------------------------------------------
# _segment_chunks
# ---------------------------------------------------------------------------


def _chunks_of(n: int, chars_each: int, start_offset: float = 0.0) -> list[Chunk]:
    """Return n Chunk objects, each with `chars_each` characters of text."""
    return [
        Chunk(
            start=start_offset + i * 90.0,
            end=start_offset + (i + 1) * 90.0,
            text="x" * chars_each,
        )
        for i in range(n)
    ]


class TestSegmentChunks:
    def test_empty_input_returns_empty(self) -> None:
        assert _segment_chunks([], 12_000) == []

    def test_single_chunk_under_target_stays_alone(self) -> None:
        chunks = [Chunk(start=0.0, end=90.0, text="hello")]
        assert _segment_chunks(chunks, 12_000) == [chunks]

    def test_single_chunk_over_target_is_not_split(self) -> None:
        """A chunk larger than the target is never split — it becomes its own segment."""
        chunks = [Chunk(start=0.0, end=90.0, text="x" * 20_000)]
        result = _segment_chunks(chunks, 12_000)
        assert len(result) == 1
        assert result[0] == chunks

    def test_two_chunks_that_fit_stay_together(self) -> None:
        chunks = _chunks_of(2, chars_each=5_000)
        # 5k + 5k = 10k ≤ 12k → single segment
        result = _segment_chunks(chunks, 12_000)
        assert len(result) == 1
        assert result[0] == chunks

    def test_two_chunks_that_overflow_split_into_two(self) -> None:
        chunks = _chunks_of(2, chars_each=7_000)
        # 7k + 7k = 14k > 12k → each chunk in its own segment
        result = _segment_chunks(chunks, 12_000)
        assert len(result) == 2
        assert result[0] == [chunks[0]]
        assert result[1] == [chunks[1]]

    def test_groups_multiple_small_chunks_per_segment(self) -> None:
        # 4 chunks x 3k = 12k total; target = 10k
        # chunks[0+1+2] = 9k < 10k; adding chunk[3] → 12k > 10k → split at 3+1
        chunks = _chunks_of(4, chars_each=3_000)
        result = _segment_chunks(chunks, 10_000)
        assert len(result) == 2
        assert len(result[0]) == 3
        assert len(result[1]) == 1

    def test_no_empty_segments_produced(self) -> None:
        chunks = _chunks_of(10, chars_each=1_500)
        for target in (3_000, 5_000, 12_000, 1):
            result = _segment_chunks(chunks, target)
            assert all(len(s) >= 1 for s in result), f"Empty segment produced with target={target}"

    def test_all_chunks_appear_exactly_once(self) -> None:
        chunks = _chunks_of(7, chars_each=2_000)
        result = _segment_chunks(chunks, 5_000)
        flattened = [c for seg in result for c in seg]
        assert flattened == chunks

    def test_boundary_at_exact_target_does_not_overflow(self) -> None:
        """Accumulated chars == target is NOT > target — next chunk stays in same segment."""
        chunks = [
            Chunk(start=0.0, end=90.0, text="a" * 6_000),  # 6k
            Chunk(start=90.0, end=180.0, text="b" * 6_000),  # 6k — total 12k == target
            Chunk(start=180.0, end=270.0, text="c" * 1_000),  # would push to 13k > target
        ]
        result = _segment_chunks(chunks, 12_000)
        # chunks[0]+[1] = 12k, not > 12k → they stay together
        # chunks[2] would push to 13k > 12k → new segment
        assert len(result) == 2
        assert result[0] == [chunks[0], chunks[1]]
        assert result[1] == [chunks[2]]

    def test_target_of_one_forces_one_chunk_per_segment(self) -> None:
        chunks = _chunks_of(3, chars_each=1)
        result = _segment_chunks(chunks, 1)
        # Each chunk is 1 char; adding another (1+1=2) > 1 → new segment each time
        assert len(result) == 3
        for i, seg in enumerate(result):
            assert seg == [chunks[i]]


# ---------------------------------------------------------------------------
# restructure_segmented
# ---------------------------------------------------------------------------


class _FirstContinuationProvider:
    """Returns a proper H1+H2 doc on the first call, only H2 sections on subsequent ones."""

    name = "fake"
    model = "fake-model"

    def __init__(self) -> None:
        self.call_count = 0

    def generate(self, *, system: str, user: str) -> str:
        self.call_count += 1
        if self.call_count == 1:
            return "# My Video\n\n## Opening\n<!-- timestamp: 0.0-90.0 -->\nFirst content."
        return f"## Section {self.call_count}\n<!-- timestamp: 90.0-180.0 -->\nMore content."


class TestRestructureSegmented:
    def test_first_segment_uses_system_prompt_rest_use_continuation(self) -> None:
        """Segment 0 must use SYSTEM_PROMPT; segments 1..K must use CONTINUATION_SYSTEM_PROMPT."""
        chunks = _chunks_of(6, chars_each=5_000)  # 30k > 12k → ≥ 2 segments
        provider = FakeProvider(response="## S\n<!-- timestamp: 0.0-90.0 -->\nContent.")

        restructure_segmented(title="T", channel="C", chunks=chunks, provider=provider)

        assert len(provider.calls) >= 2
        assert provider.calls[0]["system"] == SYSTEM_PROMPT
        for call in provider.calls[1:]:
            assert call["system"] == CONTINUATION_SYSTEM_PROMPT

    def test_h1_appears_exactly_once_in_combined_output(self) -> None:
        chunks = _chunks_of(6, chars_each=5_000)
        provider = _FirstContinuationProvider()

        result = restructure_segmented(
            title="My Video", channel="Channel", chunks=chunks, provider=provider
        )

        h1_matches = re.findall(r"^# ", result, re.MULTILINE)
        assert len(h1_matches) == 1, f"Expected exactly 1 H1, got {len(h1_matches)}"

    def test_on_segment_called_for_every_segment_with_correct_indices(self) -> None:
        chunks = _chunks_of(6, chars_each=5_000)
        provider = FakeProvider(response="## S\n<!-- timestamp: 0.0-90.0 -->\nContent.")

        received: list[tuple[int, int]] = []

        def on_seg(index: int, total: int, text: str, seg: list[Chunk]) -> None:
            received.append((index, total))

        restructure_segmented(
            title="T", channel="C", chunks=chunks, provider=provider, on_segment=on_seg
        )

        expected_total = len(provider.calls)
        assert len(received) == expected_total
        for i, (idx, total) in enumerate(received):
            assert idx == i
            assert total == expected_total

    def test_segment_user_message_contains_segment_header(self) -> None:
        chunks = _chunks_of(6, chars_each=5_000)
        provider = FakeProvider(response="## S\n<!-- timestamp: 0.0-90.0 -->\nContent.")

        restructure_segmented(title="T", channel="C", chunks=chunks, provider=provider)

        for i, call in enumerate(provider.calls):
            assert f"Segment: {i + 1} of" in call["user"]

    def test_first_segment_user_message_instructs_h1(self) -> None:
        chunks = _chunks_of(6, chars_each=5_000)
        provider = FakeProvider(response="## S\n<!-- timestamp: 0.0-90.0 -->\nContent.")

        restructure_segmented(title="T", channel="C", chunks=chunks, provider=provider)

        first_user = provider.calls[0]["user"]
        assert "# H1" in first_user or "H1 title" in first_user

    def test_continuation_segment_user_message_forbids_h1(self) -> None:
        chunks = _chunks_of(6, chars_each=5_000)
        provider = FakeProvider(response="## S\n<!-- timestamp: 0.0-90.0 -->\nContent.")

        restructure_segmented(title="T", channel="C", chunks=chunks, provider=provider)

        for call in provider.calls[1:]:
            user = call["user"]
            assert "No H1" in user or "no preamble" in user

    def test_empty_chunks_returns_empty_string_with_no_calls(self) -> None:
        provider = FakeProvider(response="## S\n<!-- timestamp: 0.0-90.0 -->\nContent.")
        result = restructure_segmented(title="T", channel="C", chunks=[], provider=provider)
        assert result == ""
        assert provider.calls == []

    def test_short_video_produces_single_llm_call(self) -> None:
        chunks = _chunks_of(2, chars_each=3_000)  # 6k < 12k → 1 segment
        provider = FakeProvider(response="## S\n<!-- timestamp: 0.0-90.0 -->\nContent.")

        restructure_segmented(
            title="T", channel="C", chunks=chunks, provider=provider, segment_chars=12_000
        )

        assert len(provider.calls) == 1

    def test_timestamp_contract_violation_warns_not_raises(self) -> None:
        """A missing-timestamp segment must warn, not abort the whole run."""
        chunks = _chunks_of(6, chars_each=5_000)
        # H2 present but NO timestamp comment → contract violation
        provider = FakeProvider(response="## Section\nContent.")

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = restructure_segmented(title="T", channel="C", chunks=chunks, provider=provider)

        assert any("timestamp contract" in str(w.message).lower() for w in caught)
        assert "Section" in result  # run completed, content is present

    def test_empty_segment_output_warns_and_is_excluded_from_join(self) -> None:
        call_count = 0

        class PartialProvider:
            name = "fake"
            model = "fake-model"

            def generate(self, *, system: str, user: str) -> str:
                nonlocal call_count
                call_count += 1
                if call_count == 2:
                    return ""  # simulate empty second segment
                return "## S\n<!-- timestamp: 0.0-90.0 -->\nContent."

        chunks = _chunks_of(9, chars_each=5_000)  # forces ≥ 3 segments

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = restructure_segmented(
                title="T", channel="C", chunks=chunks, provider=PartialProvider()
            )

        assert any("empty output" in str(w.message).lower() for w in caught)
        # Empty segment must not introduce a blank double-block gap
        assert "\n\n\n\n" not in result

    def test_parts_joined_with_double_newline(self) -> None:
        call_num = 0

        class CountingProvider:
            name = "fake"
            model = "fake-model"

            def generate(self, *, system: str, user: str) -> str:
                nonlocal call_num
                call_num += 1
                return f"## Sec{call_num}\n<!-- timestamp: 0.0-90.0 -->\nContent {call_num}."

        chunks = _chunks_of(6, chars_each=5_000)
        result = restructure_segmented(
            title="T", channel="C", chunks=chunks, provider=CountingProvider()
        )

        assert "\n\n" in result
        assert "## Sec1" in result
        assert "## Sec2" in result
