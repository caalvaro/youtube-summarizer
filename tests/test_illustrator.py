"""Unit tests for :mod:`youtube_summarizer.illustrator`."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from youtube_summarizer.illustrator import embed_frames, parse_sections

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_VALID_MD = """\
# My Video Title

## Introduction
<!-- timestamp: 0.0-120.5 -->
This is the intro text.

## Deep Dive
<!-- timestamp: 120.5-480.0 -->
Here we go deep.

## Conclusion
<!-- timestamp: 480.0-600.0 -->
That's a wrap.
"""

_ONE_SECTION_MD = """\
# Title

## Only Section
<!-- timestamp: 10.0-90.0 -->
Body text here.
"""

_NO_H2_MD = "# Just a title\n\nSome prose.\n"

_H2_WITHOUT_COMMENT_MD = """\
# Title

## Section Without Timestamp
Some body text.

## Section With Timestamp
<!-- timestamp: 50.0-100.0 -->
Body.
"""

_MALFORMED_TIMESTAMP_MD = """\
# Title

## Bad Comment
<!-- timestamp: not-a-number -->
Body.
"""

_BLANK_LINES_BETWEEN_MD = """\
# Title

## Section

<!-- timestamp: 0.0-60.0 -->
Body text.
"""


# ---------------------------------------------------------------------------
# parse_sections — happy path
# ---------------------------------------------------------------------------


class TestParseSectionsValid:
    def test_returns_correct_count(self) -> None:
        sections = parse_sections(_VALID_MD)
        assert len(sections) == 3

    def test_indices_are_zero_based_sequential(self) -> None:
        sections = parse_sections(_VALID_MD)
        assert [s.index for s in sections] == [0, 1, 2]

    def test_headings_stripped_of_prefix(self) -> None:
        sections = parse_sections(_VALID_MD)
        assert sections[0].heading == "Introduction"
        assert sections[1].heading == "Deep Dive"
        assert sections[2].heading == "Conclusion"

    def test_timestamps_parsed_correctly(self) -> None:
        sections = parse_sections(_VALID_MD)
        assert sections[0].ts_start == pytest.approx(0.0)
        assert sections[0].ts_end == pytest.approx(120.5)
        assert sections[1].ts_start == pytest.approx(120.5)
        assert sections[1].ts_end == pytest.approx(480.0)
        assert sections[2].ts_start == pytest.approx(480.0)
        assert sections[2].ts_end == pytest.approx(600.0)

    def test_body_start_points_past_comment(self) -> None:
        sections = parse_sections(_VALID_MD)
        lines = _VALID_MD.splitlines()
        # body_start line should not be the comment line itself
        for s in sections:
            assert not lines[s.body_start - 1].startswith("## ")

    def test_single_section(self) -> None:
        sections = parse_sections(_ONE_SECTION_MD)
        assert len(sections) == 1
        assert sections[0].heading == "Only Section"
        assert sections[0].ts_start == pytest.approx(10.0)
        assert sections[0].ts_end == pytest.approx(90.0)

    def test_blank_lines_between_heading_and_comment(self) -> None:
        """Parser should skip blank lines between the heading and the comment."""
        sections = parse_sections(_BLANK_LINES_BETWEEN_MD)
        assert len(sections) == 1
        assert sections[0].ts_start == pytest.approx(0.0)
        assert sections[0].ts_end == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# parse_sections — error paths
# ---------------------------------------------------------------------------


class TestParseSectionsErrors:
    def test_raises_when_no_h2_headings(self) -> None:
        with pytest.raises(ValueError, match="No '## H2' headings"):
            parse_sections(_NO_H2_MD)

    def test_raises_when_all_headings_lack_comments(self) -> None:
        with pytest.raises(ValueError, match="none had a valid"):
            parse_sections("# Title\n\n## Section\nNo comment here.\n")

    def test_malformed_timestamp_warns_and_skips(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            with pytest.raises(ValueError):
                # Only one heading; it has a malformed comment → zero valid sections
                parse_sections(_MALFORMED_TIMESTAMP_MD)
        assert any("timestamp" in str(warning.message).lower() for warning in w)

    def test_heading_without_comment_is_warned_and_skipped(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            sections = parse_sections(_H2_WITHOUT_COMMENT_MD)
        # Only the section WITH a comment should come through
        assert len(sections) == 1
        assert sections[0].heading == "Section With Timestamp"
        # A warning should have been raised for the skipped heading
        assert any("Section Without Timestamp" in str(warning.message) for warning in w)

    def test_partial_comments_increments_index_correctly(self) -> None:
        """Sections skipped due to missing comments must not shift the index of
        subsequent valid sections."""
        md = "# T\n\n## First\nNo comment.\n\n## Second\n<!-- timestamp: 10.0-20.0 -->\nBody.\n"
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            sections = parse_sections(md)

        assert len(sections) == 1
        # index=0 was consumed by the skipped first heading; this one is index=1
        assert sections[0].index == 1


# ---------------------------------------------------------------------------
# embed_frames — happy path
# ---------------------------------------------------------------------------


class TestEmbedFrames:
    def _make_frame_map(self, *pairs: tuple[int, str]) -> dict[int, Path]:
        return {idx: Path(f"/abs/frames/{name}") for idx, name in pairs}

    def test_image_inserted_after_timestamp_comment(self) -> None:
        frame_map = self._make_frame_map((0, "section_001.jpg"))
        result = embed_frames(_VALID_MD, frame_map)
        assert "![Introduction](frames/section_001.jpg)" in result

    def test_image_not_inserted_for_missing_section(self) -> None:
        # Only embed for section 0; section 1 and 2 should be untouched
        frame_map = self._make_frame_map((0, "section_001.jpg"))
        result = embed_frames(_VALID_MD, frame_map)
        assert "section_002.jpg" not in result
        assert "section_003.jpg" not in result

    def test_all_sections_embedded(self) -> None:
        frame_map = self._make_frame_map(
            (0, "section_001.jpg"),
            (1, "section_002.jpg"),
            (2, "section_003.jpg"),
        )
        result = embed_frames(_VALID_MD, frame_map)
        assert "![Introduction](frames/section_001.jpg)" in result
        assert "![Deep Dive](frames/section_002.jpg)" in result
        assert "![Conclusion](frames/section_003.jpg)" in result

    def test_image_appears_after_comment_not_before(self) -> None:
        frame_map = self._make_frame_map((0, "section_001.jpg"))
        result = embed_frames(_VALID_MD, frame_map)
        lines = result.splitlines()
        comment_idx = next(i for i, ln in enumerate(lines) if "timestamp: 0.0" in ln)
        image_idx = next(i for i, ln in enumerate(lines) if "section_001.jpg" in ln)
        assert image_idx > comment_idx

    def test_image_uses_relative_path(self) -> None:
        frame_map = {0: Path("/absolute/deep/nested/path/section_001.jpg")}
        result = embed_frames(_VALID_MD, frame_map)
        # Must use just the filename under frames/
        assert "frames/section_001.jpg" in result
        assert "/absolute/" not in result

    def test_empty_frame_map_returns_unchanged_markdown(self) -> None:
        result = embed_frames(_VALID_MD, {})
        assert result == _VALID_MD

    def test_no_double_injection_on_rerun(self) -> None:
        """Running embed_frames twice must not add a second image line."""
        frame_map = self._make_frame_map((0, "section_001.jpg"))
        once = embed_frames(_VALID_MD, frame_map)
        twice = embed_frames(once, frame_map)
        assert twice.count("section_001.jpg") == 1

    def test_original_markdown_text_preserved(self) -> None:
        frame_map = self._make_frame_map((0, "section_001.jpg"))
        result = embed_frames(_VALID_MD, frame_map)
        assert "This is the intro text." in result
        assert "Here we go deep." in result
        assert "That's a wrap." in result

    def test_heading_text_used_in_alt_attribute(self) -> None:
        frame_map = self._make_frame_map((1, "section_002.jpg"))
        result = embed_frames(_VALID_MD, frame_map)
        assert "![Deep Dive](frames/section_002.jpg)" in result

    def test_single_section_embed(self) -> None:
        frame_map = {0: Path("/frames/section_001.jpg")}
        result = embed_frames(_ONE_SECTION_MD, frame_map)
        assert "![Only Section](frames/section_001.jpg)" in result


# ---------------------------------------------------------------------------
# parse_sections — inverted / zero-duration timestamp guard (S1)
# ---------------------------------------------------------------------------

_INVERTED_RANGE_MD = """\
# Title

## Inverted Section
<!-- timestamp: 120.0-60.0 -->
Body.

## Valid Section
<!-- timestamp: 200.0-300.0 -->
Body.
"""

_EQUAL_TIMESTAMPS_MD = """\
# Title

## Zero-Duration Section
<!-- timestamp: 60.0-60.0 -->
Body.

## Valid Section
<!-- timestamp: 200.0-300.0 -->
Body.
"""


class TestParseSectionsInvertedRange:
    def test_warns_and_skips_inverted_range(self) -> None:
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            sections = parse_sections(_INVERTED_RANGE_MD)

        assert len(sections) == 1
        assert sections[0].heading == "Valid Section"
        assert any("inverted" in str(warning.message).lower() for warning in w)

    def test_warns_and_skips_equal_timestamps(self) -> None:
        """ts_end == ts_start is a zero-duration section and should also be skipped."""
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            sections = parse_sections(_EQUAL_TIMESTAMPS_MD)

        assert len(sections) == 1
        assert sections[0].heading == "Valid Section"
        assert any("inverted" in str(warning.message).lower() for warning in w)

    def test_inverted_range_increments_index_for_subsequent_sections(self) -> None:
        """A skipped inverted section must still consume an index slot so
        subsequent valid sections have stable indices."""
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            sections = parse_sections(_INVERTED_RANGE_MD)

        # index=0 was consumed by the inverted section; Valid Section is index=1
        assert sections[0].index == 1

    def test_all_inverted_raises_value_error(self) -> None:
        md = "# Title\n\n## Section\n<!-- timestamp: 100.0-50.0 -->\nBody.\n"
        with warnings.catch_warnings(record=True):
            warnings.simplefilter("always")
            with pytest.raises(ValueError, match="none had a valid"):
                parse_sections(md)


# ---------------------------------------------------------------------------
# embed_frames — _sanitize_alt bracket-stripping (S4)
# ---------------------------------------------------------------------------


class TestEmbedFramesSanitizeAlt:
    """Verify that bracket characters in LLM-generated headings are stripped
    from alt text so the produced Markdown image syntax is always valid."""

    def test_close_bracket_stripped_from_alt(self) -> None:
        md = "# Title\n\n## Intro] Extra\n<!-- timestamp: 0.0-60.0 -->\nBody.\n"
        result = embed_frames(md, {0: Path("/frames/section_001.jpg")})
        assert "![Intro Extra](frames/section_001.jpg)" in result

    def test_open_bracket_stripped_from_alt(self) -> None:
        md = "# Title\n\n## [Intro\n<!-- timestamp: 0.0-60.0 -->\nBody.\n"
        result = embed_frames(md, {0: Path("/frames/section_001.jpg")})
        assert "![Intro](frames/section_001.jpg)" in result

    def test_both_brackets_stripped_from_alt(self) -> None:
        md = "# Title\n\n## [Key Concepts]\n<!-- timestamp: 0.0-60.0 -->\nBody.\n"
        result = embed_frames(md, {0: Path("/frames/section_001.jpg")})
        assert "![Key Concepts](frames/section_001.jpg)" in result

    def test_double_injection_guard_works_with_sanitized_heading(self) -> None:
        """Re-running embed_frames on already-illustrated markdown must not
        add a second image line even when the heading contains brackets."""
        md = "# Title\n\n## [Key Concepts]\n<!-- timestamp: 0.0-60.0 -->\nBody.\n"
        frame_map = {0: Path("/frames/section_001.jpg")}
        once = embed_frames(md, frame_map)
        twice = embed_frames(once, frame_map)
        assert twice.count("section_001.jpg") == 1

    def test_heading_without_brackets_unchanged(self) -> None:
        """Sanitization must not corrupt normal headings."""
        result = embed_frames(_VALID_MD, {0: Path("/frames/section_001.jpg")})
        assert "![Introduction](frames/section_001.jpg)" in result


# ---------------------------------------------------------------------------
# _parse_timestamp — unit tests (S5)
# ---------------------------------------------------------------------------


from youtube_summarizer.illustrator import _parse_timestamp  # noqa: E402


class TestParseTimestamp:
    """Unit tests for the private _parse_timestamp() helper."""

    def test_plain_decimal_integer(self) -> None:
        assert _parse_timestamp("0") == pytest.approx(0.0)

    def test_plain_decimal_float(self) -> None:
        assert _parse_timestamp("59.00") == pytest.approx(59.0)

    def test_plain_decimal_fractional(self) -> None:
        assert _parse_timestamp("3.5") == pytest.approx(3.5)

    def test_mm_ss_exact(self) -> None:
        """1:00 → 60 s."""
        assert _parse_timestamp("1:00") == pytest.approx(60.0)

    def test_mm_ss_with_centiseconds(self) -> None:
        """1:00.29 → 60.29 s (the M:SS.cs format from format_timestamp)."""
        assert _parse_timestamp("1:00.29") == pytest.approx(60.29)

    def test_mm_ss_multi_digit_minutes(self) -> None:
        """10:30.5 → 630.5 s."""
        assert _parse_timestamp("10:30.5") == pytest.approx(630.5)

    def test_h_mm_ss_exact(self) -> None:
        """1:06:25 → 3985 s."""
        assert _parse_timestamp("1:06:25") == pytest.approx(3985.0)

    def test_h_mm_ss_zero_hours(self) -> None:
        """0:01:30 → 90 s."""
        assert _parse_timestamp("0:01:30") == pytest.approx(90.0)

    def test_h_mm_ss_large(self) -> None:
        """2:00:00 → 7200 s."""
        assert _parse_timestamp("2:00:00") == pytest.approx(7200.0)


# ---------------------------------------------------------------------------
# parse_sections — mixed timestamp formats (S5 integration)
# ---------------------------------------------------------------------------

_MIXED_FORMAT_MD = """\
# Video Title

## Early Section
<!-- timestamp: 59.00-1:00.29 -->
Intro body.

## Later Section
<!-- timestamp: 1:06:25-1:07:55 -->
Deep body.
"""


class TestParseSectionsMixedFormats:
    def test_mm_ss_cs_parsed(self) -> None:
        """'1:00.29' must be interpreted as 60.29 s, not skipped."""
        sections = parse_sections(_MIXED_FORMAT_MD)
        assert len(sections) == 2

    def test_h_mm_ss_parsed(self) -> None:
        """'1:06:25' must be interpreted as 3985 s, not skipped."""
        sections = parse_sections(_MIXED_FORMAT_MD)
        assert sections[1].ts_start == pytest.approx(3985.0)
        assert sections[1].ts_end == pytest.approx(4075.0)  # 1:07:55

    def test_decimal_and_time_mixed(self) -> None:
        """A section with start=decimal and end=MM:SS.cs must parse both halves."""
        sections = parse_sections(_MIXED_FORMAT_MD)
        assert sections[0].ts_start == pytest.approx(59.0)
        assert sections[0].ts_end == pytest.approx(60.29)

    def test_no_warnings_for_valid_time_formats(self) -> None:
        """Time-format timestamps are valid — no warnings should be raised."""
        import warnings as _warnings

        with _warnings.catch_warnings(record=True) as w:
            _warnings.simplefilter("always")
            parse_sections(_MIXED_FORMAT_MD)
        assert len(w) == 0
