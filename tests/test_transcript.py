"""Tests for youtube_summarizer.transcript."""

from __future__ import annotations

from pathlib import Path

import pytest

from youtube_summarizer.transcript import (
    Caption,
    Chunk,
    format_timestamp,
    parse_vtt,
    to_chunks,
)

# ---------------------------------------------------------------------------
# format_timestamp
# ---------------------------------------------------------------------------


class TestFormatTimestamp:
    def test_seconds_only(self) -> None:
        assert format_timestamp(45.0) == "00:45"

    def test_minutes_and_seconds(self) -> None:
        assert format_timestamp(125.0) == "02:05"

    def test_hours(self) -> None:
        assert format_timestamp(3661.0) == "1:01:01"

    def test_zero(self) -> None:
        assert format_timestamp(0.0) == "00:00"

    def test_truncates_fractional_seconds(self) -> None:
        # format_timestamp truncates to whole seconds
        assert format_timestamp(61.9) == "01:01"


# ---------------------------------------------------------------------------
# parse_vtt
# ---------------------------------------------------------------------------


class TestParseVtt:
    def test_parses_three_clean_cues(self, simple_vtt_file: Path) -> None:
        captions = parse_vtt(simple_vtt_file)
        assert len(captions) == 3

    def test_first_cue_timestamps(self, simple_vtt_file: Path) -> None:
        captions = parse_vtt(simple_vtt_file)
        assert captions[0].start == pytest.approx(0.0)
        assert captions[0].end == pytest.approx(2.5)

    def test_first_cue_text(self, simple_vtt_file: Path) -> None:
        captions = parse_vtt(simple_vtt_file)
        assert captions[0].text == "Hello, welcome to this video."

    def test_rolling_duplicates_removed(self, rolling_vtt_file: Path) -> None:
        """Auto-caption rolling cues should be collapsed to unique sentences."""
        captions = parse_vtt(rolling_vtt_file)
        texts = [c.text for c in captions]
        # No cue should be a prefix of the next one
        for i in range(len(texts) - 1):
            assert not texts[i + 1].startswith(
                texts[i]
            ), f"Cue {i} is a prefix of cue {i + 1}: {texts[i]!r}"

    def test_empty_vtt_returns_empty_list(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.vtt"
        p.write_text("WEBVTT\n\n", encoding="utf-8")
        assert parse_vtt(p) == []

    def test_inline_timing_tags_stripped(self, tmp_path: Path) -> None:
        """Karaoke <c> tags and timestamp tags must be removed from text."""
        vtt = (
            "WEBVTT\n\n"
            "00:00:01.000 --> 00:00:03.000\n"
            "<00:00:01.500><c>word</c> <00:00:02.000><c>by</c> <00:00:02.500><c>word</c>\n\n"
        )
        p = tmp_path / "tagged.vtt"
        p.write_text(vtt, encoding="utf-8")
        captions = parse_vtt(p)
        assert len(captions) == 1
        assert "<" not in captions[0].text
        assert ">" not in captions[0].text

    def test_returns_caption_dataclasses(self, simple_vtt_file: Path) -> None:
        captions = parse_vtt(simple_vtt_file)
        for cap in captions:
            assert isinstance(cap, Caption)

    def test_rolling_dedup_handles_recase_and_repunctuation(self, tmp_path: Path) -> None:
        """Rolling cues that re-emit the same words with case or whitespace
        differences must still be deduped.

        Regression: a strict ``startswith`` check left these surviving duplicates,
        which the writer then forwarded to Claude and bloated the prompt. The
        normalised prefix check (lower-case + collapsed whitespace) drops them.
        """
        vtt = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:02.000\n"
            "hello world\n\n"
            "00:00:01.500 --> 00:00:04.000\n"
            "HELLO  WORLD this is\n\n"  # re-cased + extra space
            "00:00:03.500 --> 00:00:06.000\n"
            "hello world this is a test\n\n"
        )
        p = tmp_path / "rolling_recased.vtt"
        p.write_text(vtt, encoding="utf-8")
        captions = parse_vtt(p)
        # Only the final, longest cue should survive.
        assert len(captions) == 1
        assert "test" in captions[0].text


# ---------------------------------------------------------------------------
# to_chunks
# ---------------------------------------------------------------------------


class TestToChunks:
    def test_empty_input_returns_empty(self) -> None:
        assert to_chunks([]) == []

    def test_single_caption_becomes_one_chunk(self, three_captions: list[Caption]) -> None:
        single = [three_captions[0]]
        chunks = to_chunks(single)
        assert len(chunks) == 1
        assert chunks[0].text == three_captions[0].text

    def test_short_captions_merge_into_one_chunk(self, three_captions: list[Caption]) -> None:
        # 10 seconds total, target is 90 — all in one chunk
        chunks = to_chunks(three_captions, target_seconds=90.0)
        assert len(chunks) == 1

    def test_chunk_text_joins_captions(self, three_captions: list[Caption]) -> None:
        chunks = to_chunks(three_captions, target_seconds=90.0)
        combined = " ".join(c.text for c in three_captions)
        assert chunks[0].text == combined

    def test_splits_into_multiple_chunks(self) -> None:
        captions = [
            Caption(start=float(i * 10), end=float(i * 10 + 9), text=f"Cue {i}") for i in range(20)
        ]
        # 200 seconds total, target 90 → expect 3 chunks
        chunks = to_chunks(captions, target_seconds=90.0)
        assert len(chunks) >= 2

    def test_chunk_timestamps_are_contiguous(self) -> None:
        captions = [
            Caption(start=float(i * 10), end=float(i * 10 + 9), text=f"Cue {i}") for i in range(20)
        ]
        chunks = to_chunks(captions, target_seconds=90.0)
        for chunk in chunks:
            assert chunk.start < chunk.end

    def test_returns_chunk_dataclasses(self, three_captions: list[Caption]) -> None:
        chunks = to_chunks(three_captions)
        for chunk in chunks:
            assert isinstance(chunk, Chunk)
