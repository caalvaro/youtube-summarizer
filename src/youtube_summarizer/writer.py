"""Orchestrates the transcript-to-markdown step.

This module is intentionally provider-agnostic: it builds the prompt,
delegates the LLM call to an :class:`LLMProvider`, and validates the response
against the timestamp-comment contract Phase 2 depends on. Provider-specific
concerns (API keys, SDK clients, retry policy, streaming) all live in
:mod:`youtube_summarizer.providers`.
"""

from __future__ import annotations

import re
import warnings
from collections.abc import Callable

from .providers import LLMProvider, get_provider
from .transcript import Chunk, format_timestamp

SYSTEM_PROMPT = """You are restructuring a YouTube video transcript into a clean, readable, ebook-style markdown document.

You receive the transcript as time-stamped chunks. Produce a single coherent markdown document that:

- Uses an `# H1` for the document title (use the video title provided).
- Organises the content into `## H2` sections with descriptive headings (group multiple chunks per section when topics span them).
- Cleans the prose: fix grammar, remove filler words (uh, um, like, you know), join broken sentences, but preserve the speaker's voice and meaning.
- Groups related ideas into paragraphs.
- Uses **bold** for key terms, definitions, and important concepts the first time they appear.
- Uses bullet lists where the speaker enumerates items.
- Uses `> blockquotes` for memorable verbatim quotes worth preserving.
- Uses fenced code blocks for any code, commands, or technical syntax mentioned.

Critical: emit a hidden HTML comment immediately after each `## H2` heading, recording the timestamp range of the original transcript content covered by that section. Format:

`<!-- timestamp: 12.5-67.8 -->`

(start and end in seconds, decimals OK).\
These comments are used by downstream tooling to align images to sections — they must be present and accurate.

Output only the markdown document. No preamble, no explanation, no closing remarks."""

CONTINUATION_SYSTEM_PROMPT = """You are continuing to restructure a YouTube video transcript into a clean, readable, ebook-style markdown document.

This is a continuation segment — the document title (# H1) was already written by the preceding segment. Do NOT emit an H1 title. Begin directly with ## H2 sections.

You receive transcript chunks for this segment only. Produce ## H2 sections that:

- Organises the content into `## H2` sections with descriptive headings (group multiple chunks per section when topics span them).
- Cleans the prose: fix grammar, remove filler words (uh, um, like, you know), join broken sentences, but preserve the speaker's voice and meaning.
- Groups related ideas into paragraphs.
- Uses **bold** for key terms, definitions, and important concepts the first time they appear.
- Uses bullet lists where the speaker enumerates items.
- Uses `> blockquotes` for memorable verbatim quotes worth preserving.
- Uses fenced code blocks for any code, commands, or technical syntax mentioned.

Critical: emit a hidden HTML comment immediately after each `## H2` heading, recording the timestamp range of the original transcript content covered by that section. Format:

`<!-- timestamp: 12.5-67.8 -->`

(start and end in seconds, decimals OK).
These comments are used by downstream tooling to align images to sections — they must be present and accurate.

Output only the ## H2 sections. No H1, no preamble, no explanation, no closing remarks."""


# Compiled once: H2 detector and the timestamp-comment format declared in SYSTEM_PROMPT.
_H2_RE = re.compile(r"^## ", re.MULTILINE)
_TIMESTAMP_RE = re.compile(r"<!--\s*timestamp:\s*[\d.]+\s*-\s*[\d.]+\s*-->")

# ~150k input tokens leaves headroom under typical 200k context windows for the
# system prompt (~500 tokens) plus the output budget. Conservative on purpose.
_INPUT_TOKEN_WARN_THRESHOLD = 150_000

# Rough char→token ratio for English-ish prose. Underestimating is safer here:
# we'd rather warn slightly early than miss a real overrun.
_CHARS_PER_TOKEN_ESTIMATE = 4

# Target transcript characters per LLM segment. Each segment's chunks are kept
# under this budget so the model has its full output window for that slice alone
# rather than having to condense a 76-minute lecture into 32k tokens.
_SEGMENT_TARGET_CHARS = 12_000


def restructure(
    title: str,
    channel: str,
    chunks: list[Chunk],
    *,
    provider: LLMProvider | None = None,
    segment_chars: int = _SEGMENT_TARGET_CHARS,
    on_segment: Callable[[int, int, str, list[Chunk]], None] | None = None,
) -> str:
    """Send the transcript to an LLM and return structured ebook-style markdown.

    For short videos (total transcript chars ≤ ``segment_chars``) the original
    single-call path is used. For longer videos the call is delegated to
    :func:`restructure_segmented`, which issues one LLM call per ~12k-char
    slice and appends the results.

    Args:
        title: Video title — becomes the H1.
        channel: Channel name — included in the prompt context.
        chunks: Time-stamped transcript chunks from :mod:`transcript`.
        provider: Optional explicit provider. Defaults to the one configured
            by :func:`youtube_summarizer.providers.get_provider`.
        segment_chars: Character budget per segment. Also used as the
            threshold above which segmentation activates.
        on_segment: Optional callback invoked after each segment completes,
            with signature ``(index, total, text, segment_chunks)``. Used by
            :mod:`cli` for incremental file writing and progress display.

    Returns:
        The full markdown document (all segments joined).

    Raises:
        ValueError: the LLM produced ``## H2`` headings but no
            ``<!-- timestamp: ... -->`` comments (single-call path only).
        RuntimeError: the provider is not configured (e.g. missing API key).
    """
    resolved = provider if provider is not None else get_provider()
    total_chars = sum(len(c.text) for c in chunks)
    if total_chars <= segment_chars:
        return _restructure_single(title, channel, chunks, provider=resolved, on_segment=on_segment)
    return restructure_segmented(
        title,
        channel,
        chunks,
        provider=resolved,
        segment_chars=segment_chars,
        on_segment=on_segment,
    )


def restructure_segmented(
    title: str,
    channel: str,
    chunks: list[Chunk],
    *,
    provider: LLMProvider | None = None,
    segment_chars: int = _SEGMENT_TARGET_CHARS,
    on_segment: Callable[[int, int, str, list[Chunk]], None] | None = None,
) -> str:
    """Split chunks into segments and call the LLM once per segment.

    Each segment receives a tailored prompt: segment 0 produces the full
    document (H1 + H2 sections); segments 1..K produce only H2 sections so
    the title is not duplicated. Results are joined and returned as a single
    markdown string.

    Timestamp-contract violations within a segment are downgraded to warnings
    so that a single non-compliant segment does not abort the entire run.
    Empty segment outputs are warned and skipped in the final join.

    Args:
        title: Video title.
        channel: Channel name.
        chunks: All transcript chunks for the video.
        provider: Optional explicit provider; resolved from environment if omitted.
        segment_chars: Target transcript characters per segment.
        on_segment: Callback ``(index, total, text, segment_chunks)`` invoked
            after each segment's LLM call succeeds.

    Returns:
        Combined markdown from all segments.
    """
    resolved = provider if provider is not None else get_provider()
    segments = _segment_chunks(chunks, segment_chars)
    if not segments:
        return ""

    total = len(segments)
    parts: list[str] = []

    for index, seg in enumerate(segments):
        system = SYSTEM_PROMPT if index == 0 else CONTINUATION_SYSTEM_PROMPT
        user_message = _build_segment_user_message(title, channel, seg, index, total)
        raw = resolved.generate(system=system, user=user_message)
        text = raw.strip()

        if not text:
            warnings.warn(
                f"Segment {index + 1}/{total} produced empty output — skipping.",
                stacklevel=2,
            )
        else:
            # Timestamp contract: raise on the single-call path, warn here so
            # one bad segment does not abort an otherwise successful long run.
            try:
                _validate_timestamp_contract(text)
            except ValueError as exc:
                warnings.warn(str(exc), stacklevel=2)

        parts.append(text)

        if on_segment is not None:
            on_segment(index, total, text, seg)

    return "\n\n".join(p for p in parts if p)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _restructure_single(
    title: str,
    channel: str,
    chunks: list[Chunk],
    *,
    provider: LLMProvider,
    on_segment: Callable[[int, int, str, list[Chunk]], None] | None = None,
) -> str:
    """Original single-call path for short videos."""
    user_message = _build_user_message(title, channel, chunks)
    _warn_if_oversized(user_message)
    raw = provider.generate(system=SYSTEM_PROMPT, user=user_message)
    markdown = raw.strip()
    _validate_timestamp_contract(markdown)
    if on_segment is not None:
        on_segment(0, 1, markdown, chunks)
    return markdown


def _segment_chunks(chunks: list[Chunk], target_chars: int) -> list[list[Chunk]]:
    """Group chunks into segments without splitting a chunk across boundaries.

    Accumulates chunks until adding the next chunk would exceed ``target_chars``,
    then starts a new segment. A chunk that is itself larger than ``target_chars``
    is never split — it becomes its own single-chunk segment.

    Args:
        chunks: Source chunks (typically 90-second windows from :func:`to_chunks`).
        target_chars: Soft upper bound on total ``.text`` chars per segment.

    Returns:
        A list of segments, each a non-empty list of :class:`Chunk` objects.
    """
    if not chunks:
        return []

    segments: list[list[Chunk]] = []
    current: list[Chunk] = []
    current_chars = 0

    for chunk in chunks:
        chunk_chars = len(chunk.text)
        # Close the current segment when the budget would be exceeded, but only
        # if it already contains at least one chunk (never leave current empty).
        if current and current_chars + chunk_chars > target_chars:
            segments.append(current)
            current = []
            current_chars = 0
        current.append(chunk)
        current_chars += chunk_chars

    if current:
        segments.append(current)

    return segments


def _validate_timestamp_contract(markdown: str) -> None:
    """Verify the LLM produced the timestamp comments downstream tooling depends on.

    Each ``## H2`` heading must be followed by an ``<!-- timestamp: start-end -->``
    comment (see :data:`SYSTEM_PROMPT`). When the model omits them entirely
    despite emitting headings, raise — partial output is still surfaced via a
    warning so the caller can decide whether to re-run.
    """
    h2_count = len(_H2_RE.findall(markdown))
    ts_count = len(_TIMESTAMP_RE.findall(markdown))
    if h2_count > 0 and ts_count == 0:
        raise ValueError(
            "LLM output violates timestamp contract: "
            f"found {h2_count} '## ' headings but no '<!-- timestamp: ... -->' "
            "comments. Phase 2 frame alignment requires these markers."
        )
    if h2_count > ts_count:
        warnings.warn(
            f"Timestamp contract is partial: {h2_count} headings vs {ts_count} "
            "timestamp comments. Phase 2 alignment may be incomplete.",
            stacklevel=2,
        )


def _warn_if_oversized(user_message: str) -> None:
    """Warn when the prompt likely exceeds the model's input-context budget."""
    estimated_tokens = (len(user_message) + len(SYSTEM_PROMPT)) // _CHARS_PER_TOKEN_ESTIMATE
    if estimated_tokens > _INPUT_TOKEN_WARN_THRESHOLD:
        warnings.warn(
            f"Input is large (~{estimated_tokens} tokens estimated). Long videos "
            "may exceed the model's context window — consider chunking the run.",
            stacklevel=2,
        )


def _build_user_message(title: str, channel: str, chunks: list[Chunk]) -> str:
    lines: list[str] = [f"Video title: {title}"]
    if channel:
        lines.append(f"Channel: {channel}")
    lines.extend(["", "Transcript chunks (timestamps in seconds):", ""])
    for chunk in chunks:
        ts = (
            f"[{format_timestamp(chunk.start)} - {format_timestamp(chunk.end)}] "
            f"(raw: {chunk.start:.1f}-{chunk.end:.1f})"
        )
        lines.append(ts)
        lines.append(chunk.text)
        lines.append("")
    lines.append(
        "Produce the structured markdown document now, \
        following all the rules in the system prompt."
    )
    return "\n".join(lines)


def _build_segment_user_message(
    title: str,
    channel: str,
    chunks: list[Chunk],
    segment_index: int,
    total_segments: int,
) -> str:
    """Build the user message for a single segment in a multi-segment run.

    Segment 0 instructs the model to produce the full document (H1 + H2 sections).
    Segments 1..K instruct it to produce only H2 sections (no duplicate H1).
    """
    start_ts = format_timestamp(chunks[0].start)
    end_ts = format_timestamp(chunks[-1].end)

    lines: list[str] = [f"Video title: {title}"]
    if channel:
        lines.append(f"Channel: {channel}")
    lines.append(f"Segment: {segment_index + 1} of {total_segments}  |  Time: {start_ts}-{end_ts}")
    lines.extend(["", "Transcript chunks (timestamps in seconds):", ""])
    for chunk in chunks:
        ts = (
            f"[{format_timestamp(chunk.start)} - {format_timestamp(chunk.end)}] "
            f"(raw: {chunk.start:.1f}-{chunk.end:.1f})"
        )
        lines.append(ts)
        lines.append(chunk.text)
        lines.append("")

    if segment_index == 0:
        lines.append(
            "Produce the structured markdown document starting with the # H1 title, "
            "then ## H2 sections for this segment only. "
            "Follow all the rules in the system prompt."
        )
    else:
        lines.append(
            "Produce ## H2 sections only for this segment. No H1, no preamble. "
            "Follow all the rules in the system prompt."
        )

    return "\n".join(lines)
