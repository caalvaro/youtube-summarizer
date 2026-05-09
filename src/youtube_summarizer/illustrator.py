"""Markdown parsing and frame-embedding for Phase 2 (key-frame illustration).

Responsible for reading/writing markdown only. All video concerns (download,
ffmpeg, frame extraction) are delegated to :mod:`framer`.

The timestamp-comment contract assumed here is the one Phase 1 guarantees:

    ## Section Heading
    <!-- timestamp: 0.0-487.2 -->
    First paragraph…

:func:`parse_sections` reads that contract; :func:`embed_frames` writes the
``![…](frames/section_NNN.jpg)`` image references into the document.
"""

from __future__ import annotations

import re
import warnings
from dataclasses import dataclass
from pathlib import Path

# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

_H2_RE = re.compile(r"^(## .+)$", re.MULTILINE)
_TIMESTAMP_COMMENT_RE = re.compile(r"^<!--\s*timestamp:\s*([\d:.]+)\s*-\s*([\d:.]+)\s*-->$")
_ALT_STRIP_RE = re.compile(r"[\[\]]")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_timestamp(ts: str) -> float:
    """Convert a timestamp string to seconds.

    Accepts three formats produced by :func:`transcript.format_timestamp`:

    * ``SS.cs``   — plain decimal seconds, e.g. ``59.00`` or ``3.5``
    * ``M:SS.cs`` — minutes and seconds, e.g. ``1:00.29``  -> 60.29 s
    * ``H:MM:SS`` — hours, minutes, seconds, e.g. ``1:06:25`` -> 3985 s

    Args:
        ts: Timestamp string captured from the ``<!-- timestamp: X-Y -->`` comment.

    Returns:
        Equivalent duration in seconds as a :class:`float`.
    """
    parts = ts.split(":")
    if len(parts) == 1:
        return float(parts[0])
    if len(parts) == 2:
        return int(parts[0]) * 60 + float(parts[1])
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])


def _sanitize_alt(text: str) -> str:
    """Strip ``[`` and ``]`` from heading text for use as Markdown image alt-text.

    A literal ``]`` inside ``![alt](url)`` terminates the alt span early and
    produces invalid Markdown. LLM-generated headings may contain arbitrary
    punctuation, so both bracket characters are stripped before embedding.
    """
    return _ALT_STRIP_RE.sub("", text)


# ---------------------------------------------------------------------------
# Public data model
# ---------------------------------------------------------------------------


@dataclass
class Section:
    """A single ``## H2`` section parsed from a Phase 1 summary."""

    index: int
    """0-based position among all H2 headings in the document."""

    heading: str
    """The H2 text without the leading ``## `` prefix."""

    ts_start: float
    """Section start in seconds."""

    ts_end: float
    """Section end in seconds."""

    body_start: int
    """Line index (0-based) of the first body line after the timestamp comment."""


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def parse_sections(markdown: str) -> list[Section]:
    """Extract all ``(heading, timestamp-range)`` pairs from a Phase 1 summary.

    A section is only yielded when it has a valid ``<!-- timestamp: X-Y -->``
    comment on the line immediately after the heading. Headings without the
    comment are warned and skipped.

    Args:
        markdown: Full text of ``summary.md`` produced by Phase 1.

    Returns:
        List of :class:`Section` objects in document order.

    Raises:
        ValueError: If the document contains no H2 headings at all, or if
            every H2 heading lacks a timestamp comment.
    """
    lines = markdown.splitlines()
    sections: list[Section] = []
    index = 0

    i = 0
    while i < len(lines):
        line = lines[i]
        if not line.startswith("## "):
            i += 1
            continue

        heading = line[3:]  # strip "## "
        heading_line = i

        # The timestamp comment must be the very next non-empty line after the heading.
        j = i + 1
        while j < len(lines) and lines[j].strip() == "":
            j += 1

        if j >= len(lines):
            warnings.warn(
                f"H2 heading '{heading}' (line {heading_line + 1}) has no following "
                "timestamp comment — skipping.",
                stacklevel=2,
            )
            index += 1
            i += 1
            continue

        match = _TIMESTAMP_COMMENT_RE.match(lines[j].strip())
        if match is None:
            warnings.warn(
                f"H2 heading '{heading}' (line {heading_line + 1}) is not followed by a "
                f"'<!-- timestamp: X-Y -->' comment (got: {lines[j]!r}) — skipping.",
                stacklevel=2,
            )
            index += 1
            i += 1
            continue

        try:
            ts_start = _parse_timestamp(match.group(1))
            ts_end = _parse_timestamp(match.group(2))
        except ValueError:
            warnings.warn(
                f"H2 heading '{heading}' (line {heading_line + 1}) has a malformed "
                f"timestamp value in comment (got: {lines[j]!r}) — skipping.",
                stacklevel=2,
            )
            index += 1
            i = j + 1
            continue

        if ts_end <= ts_start:
            warnings.warn(
                f"H2 heading '{heading}' (line {heading_line + 1}) has an inverted "
                f"timestamp range ({ts_start}-{ts_end}) — skipping.",
                stacklevel=2,
            )
            index += 1
            i = j + 1
            continue

        body_start = j + 1  # first line after the comment

        sections.append(
            Section(
                index=index,
                heading=heading,
                ts_start=ts_start,
                ts_end=ts_end,
                body_start=body_start,
            )
        )
        index += 1
        i = j + 1

    if index == 0:
        raise ValueError(
            "No '## H2' headings found in the markdown. Is this a valid Phase 1 summary.md?"
        )

    if not sections:
        raise ValueError(
            f"Found {index} H2 heading(s) but none had a valid "
            "'<!-- timestamp: X-Y -->' comment. Re-run Phase 1 to regenerate summary.md."
        )

    return sections


def embed_frames(markdown: str, frame_map: dict[int, Path]) -> str:
    """Inject ``![heading](frames/section_NNN.jpg)`` after each timestamp comment.

    The image line is inserted between the ``<!-- timestamp -->`` comment and
    the first line of the section body. Sections whose index is not in
    ``frame_map`` are left unchanged (graceful degradation). Sections that
    already have an image reference on the line immediately after their
    timestamp comment are left unchanged to prevent double-injection.

    Args:
        markdown: Full markdown text (typically the contents of ``summary.md``).
        frame_map: Maps section index -> absolute path to the extracted JPEG.
            Paths are converted to relative references (``frames/section_NNN.jpg``)
            so the output document is portable.

    Returns:
        The modified markdown string, ready to write to ``summary_illustrated.md``.

    Raises:
        ValueError: Propagated from :func:`parse_sections` if the markdown has no
            H2 headings, or if every H2 heading lacks a valid timestamp comment.
            This indicates a partially-written or pre-Phase-1 file -- callers should
            surface the message to the user rather than letting it propagate silently.
    """
    if not frame_map:
        return markdown

    lines = markdown.splitlines(keepends=True)
    # Work bottom-up so line-index insertions don't shift earlier positions.
    sections = parse_sections(markdown)

    # Build a lookup: line_index_of_timestamp_comment -> section
    comment_line_to_section: dict[int, Section] = {}
    for section in sections:
        if section.index not in frame_map:
            continue
        # Locate the timestamp comment line for this section.
        # It's the line just before body_start (skipping any blank lines
        # the parser stepped over).
        comment_line = section.body_start - 1
        comment_line_to_section[comment_line] = section

    if not comment_line_to_section:
        return markdown

    output_lines: list[str] = []
    i = 0
    while i < len(lines):
        output_lines.append(lines[i])
        # Check whether this line is a timestamp comment we need to follow with an image.
        line_index = i
        if line_index in comment_line_to_section:
            section = comment_line_to_section[line_index]
            frame_path = frame_map[section.index]
            # Use a consistent relative path regardless of where frame_path is absolute.
            relative = f"frames/{frame_path.name}"
            alt = _sanitize_alt(section.heading)
            image_line = f"![{alt}]({relative})\n"

            # Guard: don't double-inject if the next non-empty line is already an image.
            next_j = i + 1
            while next_j < len(lines) and lines[next_j].strip() == "":
                next_j += 1
            already_has_image = next_j < len(lines) and lines[next_j].strip().startswith(
                f"![{alt}]"
            )

            if not already_has_image:
                output_lines.append(image_line)
        i += 1

    return "".join(output_lines)
