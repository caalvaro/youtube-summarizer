from __future__ import annotations

import re
import time
import warnings
from typing import Any

import anthropic

from .config import get_settings
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

(start and end in seconds, decimals OK). These comments are used by downstream tooling to align images to sections — they must be present and accurate.

Output only the markdown document. No preamble, no explanation, no closing remarks."""


# Compiled once: H2 detector and the timestamp-comment format declared in SYSTEM_PROMPT.
_H2_RE = re.compile(r"^## ", re.MULTILINE)
_TIMESTAMP_RE = re.compile(
    r"<!--\s*timestamp:\s*[\d.]+\s*-\s*[\d.]+\s*-->"
)

# ~150k input tokens leaves headroom under Claude's 200k context window for the
# system prompt (~500 tokens) plus the 32k output budget. Conservative on purpose.
_INPUT_TOKEN_WARN_THRESHOLD = 150_000

# Rough char→token ratio for English-ish prose. Underestimating is safer here:
# we'd rather warn slightly early than miss a real overrun.
_CHARS_PER_TOKEN_ESTIMATE = 4

# Retry policy for the Anthropic streaming call. Three attempts with 1s, 2s
# backoff covers the common transient failure modes (rate-limit jitter,
# 5xx blips, brief connection drops) without making the user wait long when
# the issue is permanent (auth, bad request, etc., which are not retried).
_MAX_RETRIES = 3
_RETRY_BASE_DELAY_SECONDS = 1.0


def restructure(
    title: str,
    channel: str,
    chunks: list[Chunk],
) -> str:
    """Send chunks to Claude and return the structured markdown."""
    settings = get_settings()
    if not settings.api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set. "
            "Add it to your environment or .env file before running youtube-summarizer."
        )

    user_message = _build_user_message(title, channel, chunks)
    _warn_if_oversized(user_message)

    client = anthropic.Anthropic(api_key=settings.api_key)
    message = _call_with_retry(
        client,
        model=settings.model,
        max_tokens=32000,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[{"role": "user", "content": user_message}],
    )

    parts = [block.text for block in message.content if block.type == "text"]
    markdown = "\n".join(parts).strip()
    _validate_timestamp_contract(markdown)
    return markdown


def _call_with_retry(
    client: anthropic.Anthropic,
    *,
    retries: int = _MAX_RETRIES,
    base_delay: float = _RETRY_BASE_DELAY_SECONDS,
    **kwargs: Any,
) -> Any:
    """Stream a Claude completion with exponential backoff on transient errors.

    Mirrors the retry behaviour of mature SDKs (httpx transports, openai-python):
    rate-limit, timeout, network, and 5xx errors are retried; auth and bad-request
    errors are not (they will not improve on retry).
    """
    retriable: tuple[type[Exception], ...] = (
        anthropic.APIConnectionError,
        anthropic.APITimeoutError,
        anthropic.RateLimitError,
        anthropic.InternalServerError,
    )
    for attempt in range(retries):
        try:
            with client.messages.stream(**kwargs) as stream:
                return stream.get_final_message()
        except retriable:
            if attempt == retries - 1:
                raise
            time.sleep(base_delay * (2**attempt))
    # Defensive: the loop either returns or re-raises.
    raise RuntimeError("unreachable: retry loop exhausted without return")


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
    """Warn when the prompt likely exceeds Claude's input-context budget."""
    estimated_tokens = (
        len(user_message) + len(SYSTEM_PROMPT)
    ) // _CHARS_PER_TOKEN_ESTIMATE
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
        "Produce the structured markdown document now, following all the rules in the system prompt."
    )
    return "\n".join(lines)
