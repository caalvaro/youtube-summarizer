from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Caption:
    start: float  # seconds from video start
    end: float
    text: str


@dataclass
class Chunk:
    start: float
    end: float
    text: str


_TS_RE = re.compile(r"(\d+):(\d+):(\d+)[.,](\d+)\s*-->\s*(\d+):(\d+):(\d+)[.,](\d+)")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _normalize_for_dedup(text: str) -> str:
    """Lower-case + collapse whitespace, used by the rolling-dedup prefix check.

    Auto-captions occasionally re-punctuate or re-case the same words across
    rolling cues, which defeats a strict ``startswith`` check. Normalising
    before comparison restores the intended dedup behaviour.
    """
    return _WS_RE.sub(" ", text).strip().lower()


def parse_vtt(path: Path) -> list[Caption]:
    """Parse a YouTube VTT file, handling the rolling/karaoke format auto-captions use.

    Auto-captions repeat each line with the next one (each cue contains the previous
    cue's words plus new ones). We strip inline timing tags and skip cues whose text
    is a prefix of the next cue's text.
    """
    raw = path.read_text(encoding="utf-8")
    blocks = re.split(r"\r?\n\r?\n+", raw.strip())

    cues: list[Caption] = []
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if not lines:
            continue
        ts_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if ts_idx is None:
            continue
        m = _TS_RE.search(lines[ts_idx])
        if not m:
            continue
        h1, m1, s1, ms1, h2, m2, s2, ms2 = (int(x) for x in m.groups())
        start = h1 * 3600 + m1 * 60 + s1 + ms1 / 1000
        end = h2 * 3600 + m2 * 60 + s2 + ms2 / 1000

        text_raw = " ".join(lines[ts_idx + 1 :])
        text = _TAG_RE.sub("", text_raw)
        text = _WS_RE.sub(" ", text).strip()
        if not text:
            continue
        cues.append(Caption(start=start, end=end, text=text))

    # Drop rolling duplicates: keep cue N only if its normalised text is not a
    # prefix of cue N+1's normalised text. Normalising defeats minor punctuation
    # / case differences across rolling re-emits.
    cleaned: list[Caption] = []
    for i, cue in enumerate(cues):
        if i + 1 < len(cues):
            cur_norm = _normalize_for_dedup(cue.text)
            next_norm = _normalize_for_dedup(cues[i + 1].text)
            if next_norm.startswith(cur_norm):
                continue
        cleaned.append(cue)

    # Final pass: drop exact duplicates of the immediately-previous text.
    deduped: list[Caption] = []
    for cue in cleaned:
        if deduped and cue.text == deduped[-1].text:
            deduped[-1] = Caption(start=deduped[-1].start, end=cue.end, text=cue.text)
            continue
        deduped.append(cue)

    return deduped


def to_chunks(captions: list[Caption], target_seconds: float = 90.0) -> list[Chunk]:
    """Group captions into roughly target_seconds-sized chunks.

    A chunk closes when its accumulated duration crosses target_seconds. The chunk
    boundary is the end of the last caption that fit, so timestamps stay accurate.
    """
    if not captions:
        return []

    chunks: list[Chunk] = []
    buf: list[Caption] = []
    chunk_start = captions[0].start

    for cue in captions:
        if buf and (cue.end - chunk_start) > target_seconds:
            chunks.append(
                Chunk(
                    start=chunk_start,
                    end=buf[-1].end,
                    text=" ".join(c.text for c in buf),
                )
            )
            buf = []
            chunk_start = cue.start
        buf.append(cue)

    if buf:
        chunks.append(
            Chunk(
                start=chunk_start,
                end=buf[-1].end,
                text=" ".join(c.text for c in buf),
            )
        )

    return chunks


def format_timestamp(seconds: float) -> str:
    """Format a seconds value as H:MM:SS or MM:SS."""
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"
