"""Unit tests for :mod:`youtube_summarizer.framer`.

Network-dependent functions (``download_video``) and the actual ffmpeg binary
invocation are not tested here — they are covered by the manual integration
test documented in ``CONTRIBUTING.md``.
"""

from __future__ import annotations

import subprocess
import warnings
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from youtube_summarizer.framer import (
    FrameExtractionError,
    FrameResult,
    check_ffmpeg,
    extract_frame,
    extract_frames,
    pick_timestamp,
)
from youtube_summarizer.illustrator import Section

# ---------------------------------------------------------------------------
# pick_timestamp
# ---------------------------------------------------------------------------


class TestPickTimestamp:
    def test_default_fraction_is_25_percent(self) -> None:
        t = pick_timestamp(0.0, 100.0)
        assert t == pytest.approx(25.0)

    def test_custom_fraction(self) -> None:
        t = pick_timestamp(0.0, 100.0, offset_fraction=0.5)
        assert t == pytest.approx(50.0)

    def test_result_within_section_range(self) -> None:
        t = pick_timestamp(100.0, 200.0)
        assert 100.0 <= t <= 200.0

    def test_clamp_keeps_result_above_ts_start_plus_2(self) -> None:
        # 25% of 100-110 = 102.5, which is above ts_start+2=102 — no clamping needed
        t = pick_timestamp(100.0, 110.0)
        assert t >= 102.0

    def test_clamp_keeps_result_below_ts_end_minus_2(self) -> None:
        # Very short range where raw would exceed hi
        t = pick_timestamp(0.0, 8.0)
        assert t <= 6.0  # ts_end - 2 = 6.0

    def test_short_section_uses_midpoint(self) -> None:
        # Sections ≤ 4 s use the midpoint, not the clamped fraction.
        t = pick_timestamp(10.0, 12.0)
        assert t == pytest.approx(11.0)

    def test_exactly_4_seconds_uses_midpoint(self) -> None:
        t = pick_timestamp(0.0, 4.0)
        assert t == pytest.approx(2.0)

    def test_large_range_offset_not_clamped(self) -> None:
        # 25% of 0-1000 = 250 which is well inside [2, 998]
        t = pick_timestamp(0.0, 1000.0)
        assert t == pytest.approx(250.0)

    def test_fraction_at_start_clamps_to_ts_start_plus_2(self) -> None:
        # offset_fraction=0 → raw = ts_start; must clamp up to ts_start+2
        t = pick_timestamp(50.0, 60.0, offset_fraction=0.0)
        assert t == pytest.approx(52.0)  # clamped to ts_start + 2

    def test_fraction_at_end_clamps_to_ts_end_minus_2(self) -> None:
        # offset_fraction=1 → raw = ts_end; must clamp down to ts_end-2
        t = pick_timestamp(50.0, 60.0, offset_fraction=1.0)
        assert t == pytest.approx(58.0)  # clamped to ts_end - 2


# ---------------------------------------------------------------------------
# check_ffmpeg
# ---------------------------------------------------------------------------


class TestCheckFfmpeg:
    def test_raises_when_ffmpeg_not_on_path(self) -> None:
        with (
            patch("youtube_summarizer.framer.shutil.which", return_value=None),
            pytest.raises(RuntimeError, match="ffmpeg not found"),
        ):
            check_ffmpeg()

    def test_no_error_when_ffmpeg_available(self) -> None:
        with patch("youtube_summarizer.framer.shutil.which", return_value="/usr/bin/ffmpeg"):
            check_ffmpeg()  # should not raise

    def test_error_message_contains_install_instructions(self) -> None:
        with (
            patch("youtube_summarizer.framer.shutil.which", return_value=None),
            pytest.raises(RuntimeError) as exc_info,
        ):
            check_ffmpeg()
        msg = str(exc_info.value)
        assert "brew" in msg or "apt" in msg or "ffmpeg.org" in msg


# ---------------------------------------------------------------------------
# extract_frame
# ---------------------------------------------------------------------------


class TestExtractFrame:
    def test_raises_frame_extraction_error_on_nonzero_exit(self, tmp_path: Path) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        output = tmp_path / "frames" / "section_001.jpg"

        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stderr = "Error: invalid data found"

        with (
            patch("youtube_summarizer.framer.subprocess.run", return_value=mock_result),
            pytest.raises(FrameExtractionError, match="ffmpeg exited with code 1"),
        ):
            extract_frame(video, 12.5, output)

    def test_returns_output_path_on_success(self, tmp_path: Path) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        output = tmp_path / "frames" / "section_001.jpg"

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("youtube_summarizer.framer.subprocess.run", return_value=mock_result):
            returned = extract_frame(video, 12.5, output)

        assert returned == output

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        output = tmp_path / "frames" / "deep" / "nested" / "section_001.jpg"

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("youtube_summarizer.framer.subprocess.run", return_value=mock_result):
            extract_frame(video, 12.5, output)

        assert output.parent.exists()

    def test_ffmpeg_command_includes_double_ss(self, tmp_path: Path) -> None:
        """Verify the double -ss pattern is in the subprocess call."""
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        output = tmp_path / "section_001.jpg"

        mock_result = MagicMock()
        mock_result.returncode = 0
        captured: list[list[str]] = []

        def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
            captured.append(cmd)
            return mock_result

        with patch("youtube_summarizer.framer.subprocess.run", side_effect=fake_run):
            extract_frame(video, 45.0, output)

        assert captured, "subprocess.run was not called"
        cmd = captured[0]
        ss_indices = [i for i, arg in enumerate(cmd) if arg == "-ss"]
        assert len(ss_indices) == 2, "Expected exactly two -ss flags"
        # First -ss should be the timestamp value
        assert cmd[ss_indices[0] + 1] == "45.0"
        # Second -ss should be the fine-seek value 0.5
        assert cmd[ss_indices[1] + 1] == "0.5"

    def test_ffmpeg_command_includes_scale_filter(self, tmp_path: Path) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        output = tmp_path / "section_001.jpg"

        mock_result = MagicMock()
        mock_result.returncode = 0
        captured: list[list[str]] = []

        def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
            captured.append(cmd)
            return mock_result

        with patch("youtube_summarizer.framer.subprocess.run", side_effect=fake_run):
            extract_frame(video, 0.0, output)

        cmd = captured[0]
        assert "scale=800:-1" in cmd

    def test_ffmpeg_command_uses_vframes_1(self, tmp_path: Path) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        output = tmp_path / "section_001.jpg"

        mock_result = MagicMock()
        mock_result.returncode = 0
        captured: list[list[str]] = []

        def fake_run(cmd: list[str], **_kwargs: object) -> MagicMock:
            captured.append(cmd)
            return mock_result

        with patch("youtube_summarizer.framer.subprocess.run", side_effect=fake_run):
            extract_frame(video, 0.0, output)

        cmd = captured[0]
        assert "-vframes" in cmd
        vframes_idx = cmd.index("-vframes")
        assert cmd[vframes_idx + 1] == "1"


# ---------------------------------------------------------------------------
# extract_frame — timeout behaviour
# ---------------------------------------------------------------------------


class TestExtractFrameTimeout:
    def test_raises_frame_extraction_error_on_timeout(self, tmp_path: Path) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        output = tmp_path / "frames" / "section_001.jpg"

        with (
            patch(
                "youtube_summarizer.framer.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=60),
            ),
            pytest.raises(FrameExtractionError, match="timed out"),
        ):
            extract_frame(video, 12.5, output)

    def test_timeout_error_message_includes_timestamp(self, tmp_path: Path) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        output = tmp_path / "section_001.jpg"

        with (
            patch(
                "youtube_summarizer.framer.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="ffmpeg", timeout=60),
            ),
            pytest.raises(FrameExtractionError) as exc_info,
        ):
            extract_frame(video, 45.0, output)

        assert "45.00" in str(exc_info.value)

    def test_timeout_value_passed_to_subprocess_run(self, tmp_path: Path) -> None:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        output = tmp_path / "section_001.jpg"

        mock_result = MagicMock()
        mock_result.returncode = 0
        captured_kwargs: list[dict] = []

        def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
            captured_kwargs.append(kwargs)
            return mock_result

        with patch("youtube_summarizer.framer.subprocess.run", side_effect=fake_run):
            extract_frame(video, 12.5, output)

        assert captured_kwargs, "subprocess.run was not called"
        assert captured_kwargs[0].get("timeout") == 60


# ---------------------------------------------------------------------------
# extract_frames (non-network path — mocked download + extract)
# ---------------------------------------------------------------------------


def _make_sections(*ranges: tuple[float, float]) -> list[Section]:
    return [
        Section(
            index=i,
            heading=f"Section {i + 1}",
            ts_start=start,
            ts_end=end,
            body_start=0,
        )
        for i, (start, end) in enumerate(ranges)
    ]


class TestExtractFrames:
    def _mock_download(self, tmp_path: Path) -> Path:
        video = tmp_path / "video.mp4"
        video.write_bytes(b"fake")
        return video

    def test_calls_on_frame_callback_for_each_success(self, tmp_path: Path) -> None:
        sections = _make_sections((0.0, 120.0), (120.0, 240.0))
        video_path = self._mock_download(tmp_path)

        fired: list[FrameResult] = []

        def fake_download(*_a: object, **_kw: object) -> Path:
            return video_path

        def fake_extract(vp: Path, ts: float, op: Path) -> Path:
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_bytes(b"jpg")
            return op

        with (
            patch("youtube_summarizer.framer.download_video", side_effect=fake_download),
            patch("youtube_summarizer.framer.extract_frame", side_effect=fake_extract),
        ):
            results = extract_frames(
                url="https://example.com",
                sections=sections,
                output_dir=tmp_path,
                on_frame=fired.append,
            )

        assert len(results) == 2
        assert len(fired) == 2

    def test_failed_section_warns_and_continues(self, tmp_path: Path) -> None:
        sections = _make_sections((0.0, 60.0), (60.0, 120.0), (120.0, 180.0))
        video_path = self._mock_download(tmp_path)

        call_count = 0

        def fake_download(*_a: object, **_kw: object) -> Path:
            return video_path

        def fake_extract(vp: Path, ts: float, op: Path) -> Path:
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise FrameExtractionError("simulated ffmpeg failure")
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_bytes(b"jpg")
            return op

        with (
            patch("youtube_summarizer.framer.download_video", side_effect=fake_download),
            patch("youtube_summarizer.framer.extract_frame", side_effect=fake_extract),
            warnings.catch_warnings(record=True) as w,
        ):
            warnings.simplefilter("always")
            results = extract_frames(
                url="https://example.com",
                sections=sections,
                output_dir=tmp_path,
            )

        # Two sections succeeded, one failed
        assert len(results) == 2
        # A warning was emitted for the failure
        assert any("simulated ffmpeg failure" in str(warning.message) for warning in w)

    def test_video_deleted_after_extraction_by_default(self, tmp_path: Path) -> None:
        sections = _make_sections((0.0, 60.0))
        video_path = self._mock_download(tmp_path)

        def fake_download(*_a: object, **_kw: object) -> Path:
            return video_path

        def fake_extract(vp: Path, ts: float, op: Path) -> Path:
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_bytes(b"jpg")
            return op

        with (
            patch("youtube_summarizer.framer.download_video", side_effect=fake_download),
            patch("youtube_summarizer.framer.extract_frame", side_effect=fake_extract),
        ):
            extract_frames(
                url="https://example.com",
                sections=sections,
                output_dir=tmp_path,
                keep_video=False,
            )

        assert not video_path.exists()

    def test_video_kept_when_keep_video_true(self, tmp_path: Path) -> None:
        sections = _make_sections((0.0, 60.0))
        video_path = self._mock_download(tmp_path)

        def fake_download(*_a: object, **_kw: object) -> Path:
            return video_path

        def fake_extract(vp: Path, ts: float, op: Path) -> Path:
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_bytes(b"jpg")
            return op

        with (
            patch("youtube_summarizer.framer.download_video", side_effect=fake_download),
            patch("youtube_summarizer.framer.extract_frame", side_effect=fake_extract),
        ):
            extract_frames(
                url="https://example.com",
                sections=sections,
                output_dir=tmp_path,
                keep_video=True,
            )

        assert video_path.exists()

    def test_skip_existing_skips_sections_with_existing_jpeg(self, tmp_path: Path) -> None:
        sections = _make_sections((0.0, 60.0), (60.0, 120.0))
        video_path = self._mock_download(tmp_path)

        frames_dir = tmp_path / "frames"
        frames_dir.mkdir()
        existing = frames_dir / "section_001.jpg"
        existing.write_bytes(b"existing")

        extract_call_count = 0

        def fake_download(*_a: object, **_kw: object) -> Path:
            return video_path

        def fake_extract(vp: Path, ts: float, op: Path) -> Path:
            nonlocal extract_call_count
            extract_call_count += 1
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_bytes(b"jpg")
            return op

        with (
            patch("youtube_summarizer.framer.download_video", side_effect=fake_download),
            patch("youtube_summarizer.framer.extract_frame", side_effect=fake_extract),
        ):
            results = extract_frames(
                url="https://example.com",
                sections=sections,
                output_dir=tmp_path,
                skip_existing=True,
            )

        # Both sections returned, but extract_frame only called once (for section 2)
        assert len(results) == 2
        assert extract_call_count == 1

    def test_frame_names_follow_section_nnn_convention(self, tmp_path: Path) -> None:
        sections = _make_sections((0.0, 60.0), (60.0, 120.0))
        video_path = self._mock_download(tmp_path)

        def fake_download(*_a: object, **_kw: object) -> Path:
            return video_path

        def fake_extract(vp: Path, ts: float, op: Path) -> Path:
            op.parent.mkdir(parents=True, exist_ok=True)
            op.write_bytes(b"jpg")
            return op

        with (
            patch("youtube_summarizer.framer.download_video", side_effect=fake_download),
            patch("youtube_summarizer.framer.extract_frame", side_effect=fake_extract),
        ):
            results = extract_frames(
                url="https://example.com",
                sections=sections,
                output_dir=tmp_path,
            )

        names = [r.path.name for r in results]
        assert names == ["section_001.jpg", "section_002.jpg"]

    def test_video_deleted_even_on_extraction_failure(self, tmp_path: Path) -> None:
        """The finally-block must clean up the video even when every section fails."""
        sections = _make_sections((0.0, 60.0))
        video_path = self._mock_download(tmp_path)

        def fake_download(*_a: object, **_kw: object) -> Path:
            return video_path

        def fake_extract(vp: Path, ts: float, op: Path) -> Path:
            raise FrameExtractionError("always fails")

        with (
            patch("youtube_summarizer.framer.download_video", side_effect=fake_download),
            patch("youtube_summarizer.framer.extract_frame", side_effect=fake_extract),
            warnings.catch_warnings(record=True),
        ):
            warnings.simplefilter("always")
            extract_frames(
                url="https://example.com",
                sections=sections,
                output_dir=tmp_path,
                keep_video=False,
            )

        assert not video_path.exists()
