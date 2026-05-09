from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yt_dlp


class CaptionsUnavailable(Exception):
    """Raised when neither manual nor auto-generated captions are available."""


@dataclass
class VideoInfo:
    video_id: str
    title: str
    channel: str
    duration: float
    url: str
    captions_path: Path
    captions_source: str  # "manual" or "auto"
    output_dir: Path


def fetch(url: str, output_root: Path, lang: str = "en") -> VideoInfo:
    """Download captions (manual preferred, auto fallback) and metadata for a YouTube URL.

    Raises :class:`CaptionsUnavailable` if no captions of the requested language exist
    or if yt-dlp claims to have downloaded a track but the .vtt does not land on disk.
    """
    output_root.mkdir(parents=True, exist_ok=True)

    # Single yt-dlp pass: probe metadata + write the matching subtitle track.
    # We over-request candidate languages ([lang, "lang.*"]) so yt-dlp grabs
    # whichever variant actually exists; we still pick the canonical one
    # ourselves below using `_pick_lang`.
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,  # don't fetch the video, only subs
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": [lang, f"{lang}.*"],
        "subtitlesformat": "vtt",
        "outtmpl": str(output_root / "%(id)s" / "%(id)s"),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    video_id = info["id"]
    output_dir = output_root / video_id
    output_dir.mkdir(parents=True, exist_ok=True)

    manual_subs = info.get("subtitles") or {}
    auto_subs = info.get("automatic_captions") or {}

    # Manual takes precedence.
    chosen_lang = _pick_lang(manual_subs, lang)
    source = "manual"
    if chosen_lang is None:
        chosen_lang = _pick_lang(auto_subs, lang)
        source = "auto"
    if chosen_lang is None:
        raise CaptionsUnavailable(
            f"No '{lang}' captions found for {url} (manual or auto-generated). Skipping."
        )

    # Strict path check. The previous implementation fell back to
    # `output_dir.glob(f"{video_id}.*.vtt")[0]`, which silently picked stale
    # files left by an earlier `--lang` run. Demanding the exact path keeps
    # cross-run confusion impossible.
    captions_path = output_dir / f"{video_id}.{chosen_lang}.vtt"
    if not captions_path.exists():
        raise CaptionsUnavailable(
            f"yt-dlp reported '{chosen_lang}' captions but {captions_path.name} "
            "did not land on disk."
        )

    return VideoInfo(
        video_id=video_id,
        title=info.get("title") or video_id,
        channel=info.get("uploader") or "",
        duration=float(info.get("duration") or 0),
        url=info.get("webpage_url") or url,
        captions_path=captions_path,
        captions_source=source,
        output_dir=output_dir,
    )


def _pick_lang(tracks: dict[str, object] | None, lang: str) -> str | None:
    """Pick the best matching language code from a yt-dlp subtitle dict.

    Order:
      1. Exact match on ``lang``.
      2. Alphabetically first regional variant (``{lang}-XX``).
      3. Alphabetically first dotted variant (``{lang}.orig``, etc.).

    Sorting keeps behaviour deterministic across yt-dlp versions, where dict
    iteration order may shift.
    """
    if not tracks:
        return None
    if lang in tracks:
        return lang
    candidates = sorted(
        code
        for code in tracks
        if code.startswith(f"{lang}-") or code.startswith(f"{lang}.")
    )
    return candidates[0] if candidates else None
