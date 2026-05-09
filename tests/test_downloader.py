"""Tests for youtube_summarizer.downloader."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from youtube_summarizer.downloader import (
    CaptionsUnavailableError,
    VideoInfo,
    _pick_lang,
    fetch,
)

# ---------------------------------------------------------------------------
# _pick_lang (private helper — tested directly because it encodes
# non-trivial language-matching logic worth isolating)
# ---------------------------------------------------------------------------


class TestPickLang:
    def test_exact_match(self) -> None:
        tracks = {"en": [...], "fr": [...]}
        assert _pick_lang(tracks, "en") == "en"

    def test_prefix_match_with_dash(self) -> None:
        tracks = {"en-US": [...], "fr": [...]}
        assert _pick_lang(tracks, "en") == "en-US"

    def test_prefix_match_with_dot(self) -> None:
        tracks = {"en.orig": [...]}
        assert _pick_lang(tracks, "en") == "en.orig"

    def test_no_match_returns_none(self) -> None:
        tracks = {"fr": [...], "de": [...]}
        assert _pick_lang(tracks, "en") is None

    def test_empty_dict_returns_none(self) -> None:
        assert _pick_lang({}, "en") is None

    def test_none_input_returns_none(self) -> None:
        # yt-dlp may return None for subtitle dicts
        assert _pick_lang(None, "en") is None  # type: ignore[arg-type]

    def test_exact_takes_precedence_over_prefix(self) -> None:
        tracks = {"en": [...], "en-US": [...]}
        assert _pick_lang(tracks, "en") == "en"

    def test_multiple_regional_variants_picked_deterministically(self) -> None:
        """When several regional variants exist, the first alphabetically is chosen.

        Regression: previously this returned whichever code yt-dlp put first in
        its dict, which differed across yt-dlp versions and made local debugging
        irreproducible. Sorting fixes the order.
        """
        # Insert in order that's NOT alphabetical to defeat dict-iteration luck.
        tracks = {"en-US": [...], "en-GB": [...], "en-CA": [...]}
        assert _pick_lang(tracks, "en") == "en-CA"


# ---------------------------------------------------------------------------
# CaptionsUnavailableError
# ---------------------------------------------------------------------------


class TestCaptionsUnavailableError:
    def test_is_exception(self) -> None:
        exc = CaptionsUnavailableError("no captions")
        assert isinstance(exc, Exception)

    def test_message_preserved(self) -> None:
        exc = CaptionsUnavailableError("no captions for https://example.com")
        assert "https://example.com" in str(exc)


# ---------------------------------------------------------------------------
# fetch — integration path (yt-dlp fully mocked)
# ---------------------------------------------------------------------------


def _make_ydl_info(
    *,
    video_id: str = "abc123",
    title: str = "Test Video",
    uploader: str = "Test Channel",
    duration: int = 300,
    manual_subs: dict | None = None,
    auto_subs: dict | None = None,
) -> dict:
    """Build a minimal yt-dlp info dict."""
    return {
        "id": video_id,
        "title": title,
        "uploader": uploader,
        "duration": duration,
        "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
        "subtitles": manual_subs or {},
        "automatic_captions": auto_subs or {},
    }


class TestFetch:
    def test_raises_when_no_captions_available(self, tmp_path: Path) -> None:
        info = _make_ydl_info(manual_subs={}, auto_subs={})

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = info

        with (
            patch("youtube_summarizer.downloader.yt_dlp.YoutubeDL", return_value=mock_ydl),
            pytest.raises(CaptionsUnavailableError, match="No 'en' captions"),
        ):
            fetch("https://www.youtube.com/watch?v=abc123", tmp_path)

    def test_prefers_manual_over_auto_captions(self, tmp_path: Path) -> None:
        """When both manual and auto captions exist, manual is chosen."""
        video_id = "abc123"
        info = _make_ydl_info(
            video_id=video_id,
            manual_subs={"en": [{"url": "...", "ext": "vtt"}]},
            auto_subs={"en": [{"url": "...", "ext": "vtt"}]},
        )

        # Create the VTT file that yt-dlp would have written
        output_dir = tmp_path / video_id
        output_dir.mkdir(parents=True)
        vtt_path = output_dir / f"{video_id}.en.vtt"
        vtt_path.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello\n\n")

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = info

        with patch("youtube_summarizer.downloader.yt_dlp.YoutubeDL", return_value=mock_ydl):
            result = fetch("https://www.youtube.com/watch?v=abc123", tmp_path)

        assert result.captions_source == "manual"

    def test_falls_back_to_auto_when_no_manual(self, tmp_path: Path) -> None:
        video_id = "abc123"
        info = _make_ydl_info(
            video_id=video_id,
            manual_subs={},
            auto_subs={"en": [{"url": "...", "ext": "vtt"}]},
        )

        output_dir = tmp_path / video_id
        output_dir.mkdir(parents=True)
        vtt_path = output_dir / f"{video_id}.en.vtt"
        vtt_path.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello\n\n")

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = info

        with patch("youtube_summarizer.downloader.yt_dlp.YoutubeDL", return_value=mock_ydl):
            result = fetch("https://www.youtube.com/watch?v=abc123", tmp_path)

        assert result.captions_source == "auto"

    def test_strict_expected_path_required(self, tmp_path: Path) -> None:
        """A stale .vtt from a previous --lang run must NOT be accepted.

        Regression: the old glob fallback ``output_dir.glob(f"{video_id}.*.vtt")``
        would silently pick a leftover ``en-GB.vtt`` when the current run asked
        for ``en-US``. We now demand the exact expected path.
        """
        video_id = "abc123"
        info = _make_ydl_info(
            video_id=video_id,
            manual_subs={"en-US": [{"url": "...", "ext": "vtt"}]},
        )

        # Plant a stale VTT from a hypothetical previous run.
        output_dir = tmp_path / video_id
        output_dir.mkdir(parents=True)
        stale = output_dir / f"{video_id}.en-GB.vtt"
        stale.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nStale\n\n")

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = info

        with (
            patch("youtube_summarizer.downloader.yt_dlp.YoutubeDL", return_value=mock_ydl),
            pytest.raises(CaptionsUnavailableError, match="did not land on disk"),
        ):
            fetch("https://www.youtube.com/watch?v=abc123", tmp_path)

    def test_returns_video_info_dataclass(self, tmp_path: Path) -> None:
        video_id = "abc123"
        info = _make_ydl_info(
            video_id=video_id,
            manual_subs={"en": [{"url": "...", "ext": "vtt"}]},
        )

        output_dir = tmp_path / video_id
        output_dir.mkdir(parents=True)
        vtt_path = output_dir / f"{video_id}.en.vtt"
        vtt_path.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nHello\n\n")

        mock_ydl = MagicMock()
        mock_ydl.__enter__ = MagicMock(return_value=mock_ydl)
        mock_ydl.__exit__ = MagicMock(return_value=False)
        mock_ydl.extract_info.return_value = info

        with patch("youtube_summarizer.downloader.yt_dlp.YoutubeDL", return_value=mock_ydl):
            result = fetch("https://www.youtube.com/watch?v=abc123", tmp_path)

        assert isinstance(result, VideoInfo)
        assert result.video_id == video_id
        assert result.title == "Test Video"
        assert result.channel == "Test Channel"
        assert result.duration == pytest.approx(300.0)
