"""CLI tests for the ``illustrate`` subcommand.

The framer module is mocked throughout so these tests exercise CLI logic only —
no network calls, no ffmpeg, no yt-dlp.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from youtube_summarizer.cli import app
from youtube_summarizer.framer import FrameResult
from youtube_summarizer.illustrator import Section

runner = CliRunner()

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_VALID_SUMMARY = """\
# My Video

## Introduction
<!-- timestamp: 0.0-120.0 -->
Intro body.

## Core Concepts
<!-- timestamp: 120.0-480.0 -->
Main body.
"""

_VALID_METADATA = {
    "video_id": "abc123",
    "title": "My Video",
    "channel": "Test Channel",
    "duration": 600.0,
    "url": "https://www.youtube.com/watch?v=abc123",
    "captions_source": "manual",
    "provider": "claude",
    "model": "claude-3-5-haiku-20241022",
}


@pytest.fixture()
def phase1_dir(tmp_path: Path) -> Path:
    """A minimal Phase 1 output directory."""
    d = tmp_path / "abc123"
    d.mkdir()
    (d / "metadata.json").write_text(json.dumps(_VALID_METADATA), encoding="utf-8")
    (d / "summary.md").write_text(_VALID_SUMMARY, encoding="utf-8")
    return d


def _fake_extract_frames(
    url: str,
    sections: list[Section],
    output_dir: Path,
    *,
    quality: str = "bestvideo[height<=360]",
    keep_video: bool = False,
    skip_existing: bool = False,
    on_frame: object = None,
) -> list[FrameResult]:
    """Fake framer.extract_frames that creates stub JPEGs and returns FrameResults."""
    frames_dir = output_dir / "frames"
    frames_dir.mkdir(exist_ok=True)
    results = []
    for section in sections:
        frame_path = frames_dir / f"section_{section.index + 1:03d}.jpg"
        frame_path.write_bytes(b"fake-jpeg")
        result = FrameResult(
            section_index=section.index,
            path=frame_path,
            timestamp=section.ts_start + 1.0,
        )
        results.append(result)
        if callable(on_frame):
            on_frame(result)
    return results


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestIllustratHappyPath:
    def test_exits_zero_on_success(self, phase1_dir: Path) -> None:
        with (
            patch("youtube_summarizer.cli.framer.check_ffmpeg"),
            patch(
                "youtube_summarizer.cli.framer.extract_frames",
                side_effect=_fake_extract_frames,
            ),
        ):
            result = runner.invoke(app, ["illustrate", str(phase1_dir)])
        assert result.exit_code == 0, result.output

    def test_writes_summary_illustrated_md(self, phase1_dir: Path) -> None:
        with (
            patch("youtube_summarizer.cli.framer.check_ffmpeg"),
            patch(
                "youtube_summarizer.cli.framer.extract_frames",
                side_effect=_fake_extract_frames,
            ),
        ):
            runner.invoke(app, ["illustrate", str(phase1_dir)])

        out = phase1_dir / "summary_illustrated.md"
        assert out.exists()
        content = out.read_text(encoding="utf-8")
        assert "section_001.jpg" in content
        assert "section_002.jpg" in content

    def test_in_place_overwrites_summary_md(self, phase1_dir: Path) -> None:
        with (
            patch("youtube_summarizer.cli.framer.check_ffmpeg"),
            patch(
                "youtube_summarizer.cli.framer.extract_frames",
                side_effect=_fake_extract_frames,
            ),
        ):
            result = runner.invoke(app, ["illustrate", str(phase1_dir), "--in-place"])

        assert result.exit_code == 0, result.output
        content = (phase1_dir / "summary.md").read_text(encoding="utf-8")
        assert "section_001.jpg" in content
        # summary_illustrated.md should NOT exist when --in-place is used
        assert not (phase1_dir / "summary_illustrated.md").exists()

    def test_summary_md_not_modified_by_default(self, phase1_dir: Path) -> None:
        original = (phase1_dir / "summary.md").read_text(encoding="utf-8")
        with (
            patch("youtube_summarizer.cli.framer.check_ffmpeg"),
            patch(
                "youtube_summarizer.cli.framer.extract_frames",
                side_effect=_fake_extract_frames,
            ),
        ):
            runner.invoke(app, ["illustrate", str(phase1_dir)])

        after = (phase1_dir / "summary.md").read_text(encoding="utf-8")
        assert after == original


# ---------------------------------------------------------------------------
# Missing / malformed inputs
# ---------------------------------------------------------------------------


class TestIllustrateInputErrors:
    def test_missing_metadata_json_exits_one(self, tmp_path: Path) -> None:
        d = tmp_path / "vid"
        d.mkdir()
        (d / "summary.md").write_text(_VALID_SUMMARY, encoding="utf-8")

        result = runner.invoke(app, ["illustrate", str(d)])
        assert result.exit_code == 1
        assert "metadata.json" in result.output

    def test_missing_summary_md_exits_one(self, tmp_path: Path) -> Path:
        d = tmp_path / "vid"
        d.mkdir()
        (d / "metadata.json").write_text(json.dumps(_VALID_METADATA), encoding="utf-8")

        result = runner.invoke(app, ["illustrate", str(d)])
        assert result.exit_code == 1
        assert "summary.md" in result.output

    def test_malformed_metadata_json_exits_one(self, tmp_path: Path) -> None:
        d = tmp_path / "vid"
        d.mkdir()
        (d / "metadata.json").write_text("{not valid json", encoding="utf-8")
        (d / "summary.md").write_text(_VALID_SUMMARY, encoding="utf-8")

        result = runner.invoke(app, ["illustrate", str(d)])
        assert result.exit_code == 1

    def test_metadata_json_missing_url_field_exits_one(self, tmp_path: Path) -> None:
        d = tmp_path / "vid"
        d.mkdir()
        bad = {k: v for k, v in _VALID_METADATA.items() if k != "url"}
        (d / "metadata.json").write_text(json.dumps(bad), encoding="utf-8")
        (d / "summary.md").write_text(_VALID_SUMMARY, encoding="utf-8")

        result = runner.invoke(app, ["illustrate", str(d)])
        assert result.exit_code == 1

    def test_summary_with_no_timestamp_comments_exits_one(self, tmp_path: Path) -> None:
        d = tmp_path / "vid"
        d.mkdir()
        (d / "metadata.json").write_text(json.dumps(_VALID_METADATA), encoding="utf-8")
        (d / "summary.md").write_text("# Title\n\n## Section\nNo comment.\n", encoding="utf-8")

        with patch("youtube_summarizer.cli.framer.check_ffmpeg"):
            result = runner.invoke(app, ["illustrate", str(d)])

        assert result.exit_code == 1


# ---------------------------------------------------------------------------
# ffmpeg / framer errors
# ---------------------------------------------------------------------------


class TestIllustrateFramerErrors:
    def test_missing_ffmpeg_exits_two(self, phase1_dir: Path) -> None:
        with patch(
            "youtube_summarizer.cli.framer.check_ffmpeg",
            side_effect=RuntimeError("ffmpeg not found on PATH."),
        ):
            result = runner.invoke(app, ["illustrate", str(phase1_dir)])

        assert result.exit_code == 2
        assert "ffmpeg" in result.output

    def test_video_download_failure_exits_one(self, phase1_dir: Path) -> None:
        with (
            patch("youtube_summarizer.cli.framer.check_ffmpeg"),
            patch(
                "youtube_summarizer.cli.framer.extract_frames",
                side_effect=RuntimeError("Download failed: network error"),
            ),
        ):
            result = runner.invoke(app, ["illustrate", str(phase1_dir)])

        assert result.exit_code == 1
        assert "Download failed" in result.output

    def test_no_frames_extracted_exits_one(self, phase1_dir: Path) -> None:
        # extract_frames returns empty list (all sections failed)
        with (
            patch("youtube_summarizer.cli.framer.check_ffmpeg"),
            patch(
                "youtube_summarizer.cli.framer.extract_frames",
                return_value=[],
            ),
        ):
            result = runner.invoke(app, ["illustrate", str(phase1_dir)])

        assert result.exit_code == 1
        assert "No frames" in result.output
