"""Video download and frame extraction for Phase 2 (key-frame illustration).

Encapsulates all subprocess calls to ``yt-dlp`` and ``ffmpeg``. Returns
:class:`Path` objects and :class:`FrameResult` values; never modifies markdown.

The caller (:mod:`cli`) is responsible for progress reporting and for deciding
whether to keep or delete the downloaded video file.

ffmpeg command used for accurate frame extraction (double ``-ss`` pattern):

    ffmpeg -y \\
      -ss {timestamp}      ← coarse seek before -i (fast)
      -i {video_path}      ← input
      -ss 0.5              ← fine-seek 0.5 s after -i (accurate)
      -vframes 1           ← extract exactly one frame
      -vf scale=800:-1     ← resize to 800 px wide, preserve aspect ratio
      -q:v 3               ← JPEG quality (3 ≈ near-lossless thumbnail)
      {output_path}

The two ``-ss`` together give both speed and keyframe accuracy. A single
pre-input ``-ss`` is fast but snaps to the nearest keyframe; a single
post-input ``-ss`` is accurate but slow for long seeks on large files.
"""

from __future__ import annotations

import shutil
import subprocess
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .illustrator import Section

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class FrameExtractionError(RuntimeError):
    """Raised when ffmpeg exits with a non-zero return code."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class FrameResult:
    """The outcome of a single successful frame extraction."""

    section_index: int
    """Corresponds to :attr:`Section.index`."""

    path: Path
    """Absolute path to the extracted JPEG file."""

    timestamp: float
    """The exact second at which the frame was taken."""


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def check_ffmpeg() -> None:
    """Raise :class:`RuntimeError` with installation instructions if ``ffmpeg`` is not on PATH.

    Raises:
        RuntimeError: ffmpeg binary not found on ``PATH``.
    """
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found on PATH. Phase 2 requires ffmpeg for frame extraction.\n"
            "Install it with one of:\n"
            "  macOS:   brew install ffmpeg\n"
            "  Ubuntu:  sudo apt-get install ffmpeg\n"
            "  Windows: https://ffmpeg.org/download.html  (add to PATH after install)\n"
            "Then re-run the illustrate command."
        )


def pick_timestamp(ts_start: float, ts_end: float, offset_fraction: float = 0.25) -> float:
    """Choose the extraction timestamp within a section's range.

    Defaults to 25 % into the range — after the opening sentence of the
    section (which tends to be the speaker talking to camera) but before
    mid-section transitions.

    Clamped to ``[ts_start + 2, ts_end - 2]`` to avoid black frames at hard
    cuts near section boundaries. When the section is shorter than 4 seconds
    the clamp collapses and the midpoint is returned instead.

    Args:
        ts_start: Section start in seconds.
        ts_end: Section end in seconds.
        offset_fraction: Fraction of the range at which to sample (default 0.25).

    Returns:
        Timestamp in seconds.
    """
    duration = ts_end - ts_start
    if duration <= 4.0:
        # Too short to apply safe margin — just use the midpoint.
        return ts_start + duration / 2.0

    raw = ts_start + duration * offset_fraction
    lo = ts_start + 2.0
    hi = ts_end - 2.0
    return max(lo, min(raw, hi))


def extract_frame(video_path: Path, timestamp: float, output_path: Path) -> Path:
    """Extract a single JPEG frame at ``timestamp`` seconds using ffmpeg.

    Uses the double ``-ss`` pattern: coarse pre-input seek for speed, fine
    post-input seek for accuracy. Resizes to 800 px wide (aspect preserved)
    at JPEG quality 3.

    Args:
        video_path: Path to the downloaded video file.
        timestamp: Second at which to capture the frame.
        output_path: Destination path for the JPEG.

    Returns:
        ``output_path`` on success.

    Raises:
        :class:`FrameExtractionError`: ffmpeg exited non-zero.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        str(timestamp),
        "-i",
        str(video_path),
        "-ss",
        "0.5",
        "-vframes",
        "1",
        "-vf",
        "scale=800:-1",
        "-q:v",
        "3",
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise FrameExtractionError(
            f"ffmpeg timed out after 60 s while extracting frame at "
            f"t={timestamp:.2f}s from {video_path.name}. "
            "The file may be corrupted or on a slow/unresponsive network mount."
        ) from None

    if result.returncode != 0:
        raise FrameExtractionError(
            f"ffmpeg exited with code {result.returncode} while extracting "
            f"frame at t={timestamp:.2f}s from {video_path.name}.\n"
            f"stderr: {result.stderr[-500:]}"
        )

    return output_path


def download_video(
    url: str,
    output_dir: Path,
    quality: str = "bestvideo[height<=360]",
) -> Path:
    """Download the lowest-quality video stream sufficient for frame extraction.

    Uses yt-dlp to fetch a video-only stream (no audio download). The caller
    is responsible for deleting the file when it is no longer needed.

    Args:
        url: YouTube (or other yt-dlp-supported) video URL.
        output_dir: Directory where the video file will be written.
        quality: yt-dlp format selector. Defaults to ``bestvideo[height<=360]``
            which typically yields a ~50-150 MB file for a 60-minute lecture.

    Returns:
        Path to the downloaded video file.

    Raises:
        RuntimeError: yt-dlp failed (network error, geo-block, private video, etc.).
    """
    import yt_dlp  # imported here so framer.py has no mandatory top-level dep

    output_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(output_dir / "video.%(ext)s")

    opts: dict[str, object] = {
        "quiet": True,
        "no_warnings": True,
        "format": quality,
        "outtmpl": output_template,
        # Never merge audio — we only need visual frames.
        "postprocessors": [],
        # Prevent the fallback glob from matching incomplete .part files if
        # the process is interrupted between extract_info returning and the
        # download being finalised.
        "nopart": True,
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Exception as exc:
        raise RuntimeError(
            f"Video download failed for {url!r}: {exc}\n"
            "Possible causes: network error, geo-restriction, private video, "
            "or yt-dlp format selector matched nothing. "
            "Try a different --quality value (e.g. 'bestvideo[height<=480]')."
        ) from exc

    # yt-dlp puts the actual extension in info["ext"].
    ext = (info or {}).get("ext", "mp4")
    candidate = output_dir / f"video.{ext}"
    if candidate.exists():
        return candidate

    # Fallback: yt-dlp sometimes writes a different extension than info["ext"].
    for path in sorted(output_dir.glob("video.*")):
        if path.suffix.lower() in {".mp4", ".webm", ".mkv", ".avi", ".mov"}:
            return path

    raise RuntimeError(
        f"yt-dlp reported success but no video file was found in {output_dir}. "
        "This is unexpected — check yt-dlp version or try a different --quality value."
    )


def extract_frames(
    url: str,
    sections: list[Section],
    output_dir: Path,
    *,
    quality: str = "bestvideo[height<=360]",
    keep_video: bool = False,
    skip_existing: bool = False,
    on_frame: Callable[[FrameResult], None] | None = None,
) -> list[FrameResult]:
    """High-level entry point: download video, extract one frame per section.

    Downloads the video once, extracts one JPEG per section, then deletes the
    video file (unless ``keep_video=True``). Per-section extraction failures
    are warned and skipped — they do not abort the loop.

    When ``skip_existing=True``, any section whose output JPEG already exists
    on disk is skipped without re-extracting. Default is ``False`` (always
    overwrite) to avoid serving stale frames after a Phase 1 re-run with
    different timestamp ranges.

    Args:
        url: Video URL to download.
        sections: List of :class:`Section` objects from :func:`illustrator.parse_sections`.
        output_dir: Phase 1 output directory (``output/{video_id}/``).
            Frames are written to ``output_dir/frames/section_NNN.jpg``.
        quality: yt-dlp format selector.
        keep_video: If ``True``, do not delete the downloaded video after extraction.
        skip_existing: If ``True``, skip sections whose JPEG already exists on disk.
        on_frame: Optional callback invoked after each successful extraction.

    Returns:
        List of :class:`FrameResult` for every successfully extracted frame,
        in section order.
    """
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    video_path = download_video(url, output_dir, quality=quality)

    results: list[FrameResult] = []
    try:
        for section in sections:
            frame_name = f"section_{section.index + 1:03d}.jpg"
            frame_path = frames_dir / frame_name

            if skip_existing and frame_path.exists():
                # NOTE: the reported timestamp is recalculated from the section
                # range, not read from stored state. If offset_fraction ever
                # becomes configurable and its value differs from the run that
                # produced the JPEG, the FrameResult.timestamp will silently
                # disagree with the actual frame content on disk.
                results.append(
                    FrameResult(
                        section_index=section.index,
                        path=frame_path,
                        timestamp=pick_timestamp(section.ts_start, section.ts_end),
                    )
                )
                if on_frame is not None:
                    on_frame(results[-1])
                continue

            timestamp = pick_timestamp(section.ts_start, section.ts_end)

            try:
                extract_frame(video_path, timestamp, frame_path)
            except FrameExtractionError as exc:
                warnings.warn(
                    f"Frame extraction failed for section {section.index + 1} "
                    f"('{section.heading}'): {exc}",
                    stacklevel=2,
                )
                continue

            result = FrameResult(
                section_index=section.index,
                path=frame_path,
                timestamp=timestamp,
            )
            results.append(result)

            if on_frame is not None:
                on_frame(result)

    finally:
        if not keep_video and video_path.exists():
            video_path.unlink()

    return results
