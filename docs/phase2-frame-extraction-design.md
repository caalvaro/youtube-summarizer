# Phase 2 Design: Key-Frame Extraction and Markdown Illustration

**Status:** Proposed
**Author:** Álvaro Carvalho
**Date:** 2026-05-09
**Depends on:** Phase 1 (segmented transcript-to-markdown)

---

## 1. Problem Statement

Phase 1 produces a structured markdown document from a YouTube video transcript. Each
`## H2` section is annotated with a hidden comment recording its timestamp range:

```markdown
## Introduction to Attention Mechanisms
<!-- timestamp: 0.0-487.2 -->

The transformer architecture fundamentally changed...
```

These markers exist specifically to enable Phase 2: aligning visual frames from the video
to each prose section. Without images, the ebook-style document is text-only. With
well-chosen frames, each section gets an illustration that reinforces the content and
makes the document more navigable.

---

## 2. Requirements

### Functional
- Extract one representative frame per `## H2` section from the source video.
- Embed the frames into the markdown document immediately after the section heading.
- The output must be a valid, self-contained markdown file that renders correctly in
  standard viewers (GitHub, Obsidian, VS Code Preview, Typora).
- Phase 1 output (`summary.md`) must remain untouched; Phase 2 writes a new file.
- Phase 2 must be re-runnable independently — a user should be able to re-run it on
  an existing `summary.md` without re-running Phase 1.

### Non-Functional
- **Bandwidth-conscious:** downloading a 76-minute video at full quality (~2 GB) just
  to extract a handful of JPEG thumbnails is unacceptable. The lowest quality that
  produces a legible illustration must be chosen.
- **No required cloud calls:** frame extraction must work offline after the video is
  downloaded (unlike Phase 1, which requires an LLM API key).
- **Graceful degradation:** if a frame cannot be extracted for a section, warn and
  continue — one bad section should not abort the whole run.
- **Reproducible:** given the same `summary.md`, re-running Phase 2 produces
  identical output if the video hasn't changed.

### Constraints
- Existing stack: Python 3.13, `uv`, `yt-dlp`, `typer`, `rich`.
- `ffmpeg` must be available on `PATH` — it is the only reliable tool for
  seek-accurate frame extraction without loading the full video into memory.
- No new Python packages should be added just for video I/O; `subprocess` + `ffmpeg`
  is sufficient and avoids dependency-hell with `opencv-python` or `imageio`.

---

## 3. High-Level Design

```
┌─────────────────────────────── Phase 2 pipeline ───────────────────────────────┐
│                                                                                  │
│  summary.md  ──► illustrator.parse_sections()  ──►  [(heading, ts_start, ts_end)] │
│                                                          │                       │
│  metadata.json ──► url, video_id                         │                       │
│                       │                                  │                       │
│                       ▼                                  ▼                       │
│               framer.download_video() ──► video.mp4   framer.pick_timestamp()    │
│                       │                    │               │                     │
│                       └────────────────────┘               │                     │
│                                    │                       │                     │
│                                    ▼                       ▼                     │
│                           framer.extract_frame(video, t) ──► frame_NNN.jpg       │
│                                                                    │             │
│                  summary.md ──► illustrator.embed_frames() ◄───────┘             │
│                                         │                                        │
│                                         ▼                                        │
│                                summary_illustrated.md                            │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### Output directory after Phase 2

```
output/{video_id}/
├── {video_id}.en.vtt          # raw captions (Phase 1)
├── transcript.txt              # flat transcript (Phase 1)
├── metadata.json               # video metadata + provider info (Phase 1)
├── summary.md                  # structured markdown (Phase 1, unchanged)
├── summary_illustrated.md      # summary.md + embedded images (Phase 2)  ← NEW
├── video.mp4                   # downloaded video, deleted after extraction  ← NEW (temp)
└── frames/                     # extracted JPEG frames  ← NEW
    ├── section_001.jpg
    ├── section_002.jpg
    └── ...
```

---

## 4. Component Design

### 4.1 `illustrator.py` — Markdown parsing and frame embedding

Responsible for reading/writing markdown. Has no I/O side effects beyond file access —
all video concerns are delegated to `framer.py`.

```python
@dataclass
class Section:
    index: int          # 0-based position among all H2 headings
    heading: str        # the H2 text (without "## ")
    ts_start: float     # seconds
    ts_end: float       # seconds
    body_start: int     # line index where section body begins (after the comment)

def parse_sections(markdown: str) -> list[Section]:
    """Extract all (heading, timestamp-range) pairs from a Phase 1 summary.

    A section is only yielded when it has a valid `<!-- timestamp: X-Y -->` comment
    directly after the heading. Headings without the comment are skipped with a warning.
    """

def embed_frames(markdown: str, frame_map: dict[int, Path]) -> str:
    """Inject `![heading](frames/section_NNN.jpg)` after each timestamp comment.

    frame_map maps section index → JPEG path. Sections not in the map are left
    unchanged (graceful degradation). Returns the modified markdown string.
    """
```

**Embedding format** (inserted between the `<!-- timestamp -->` comment and the first
paragraph of the section body):

```markdown
## Introduction to Attention Mechanisms
<!-- timestamp: 0.0-487.2 -->
![Introduction to Attention Mechanisms](frames/section_001.jpg)

The transformer architecture fundamentally changed...
```

The image path is relative to the markdown file's location so the document is
portable — moving `output/{video_id}/` to another machine keeps links intact.

---

### 4.2 `framer.py` — Video download and frame extraction

Encapsulates all subprocess calls. Returns paths; never modifies markdown.

```python
@dataclass
class FrameResult:
    section_index: int
    path: Path          # absolute path to the JPEG
    timestamp: float    # exact second at which the frame was taken

def download_video(url: str, output_dir: Path, quality: str = "bestvideo[height<=360]") -> Path:
    """Download the lowest-quality video stream sufficient for frame extraction.

    Uses yt-dlp with `merge_output_format` disabled (video-only stream) to avoid
    downloading audio. Returns the path to the downloaded file.

    The caller is responsible for deleting the file when no longer needed.
    """

def pick_timestamp(ts_start: float, ts_end: float, offset_fraction: float = 0.25) -> float:
    """Choose the extraction timestamp within a section's range.

    Defaults to 25% into the range (after the opening sentence of the section
    but before mid-section transitions). Clamped to [ts_start+2, ts_end-2] to
    avoid black frames at hard cuts.
    """

def extract_frame(video_path: Path, timestamp: float, output_path: Path) -> Path:
    """Extract a single JPEG frame at `timestamp` seconds using ffmpeg.

    Uses accurate seeking (`-ss` after `-i`) to avoid keyframe-only snapping.
    Raises `FrameExtractionError` if ffmpeg exits non-zero.
    """

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
    """High-level entry point: download video, extract one frame per section, return results.

    Downloads once, extracts all frames, then deletes the video (unless keep_video=True).
    When skip_existing=True, any section whose output JPEG already exists on disk is
    skipped without re-extracting — useful for resuming an interrupted run or iterating
    on the markdown without re-downloading the video. Default is False (always overwrite)
    to avoid serving stale frames after a Phase 1 re-run with different timestamp ranges.
    Calls on_frame after each successful extraction for progress reporting.
    Per-section failures are warned and skipped — they do not abort the loop.
    """

def check_ffmpeg() -> None:
    """Raise RuntimeError with installation instructions if ffmpeg is not on PATH."""
```

**ffmpeg command for accurate frame extraction:**

```bash
ffmpeg -y \
  -ss {timestamp}         \  # seek BEFORE -i for fast seek
  -i {video_path}         \
  -ss 0.5                 \  # fine-seek 0.5s AFTER -i for accuracy
  -vframes 1              \
  -vf scale=800:-1        \  # resize to 800 px wide, preserve aspect ratio
  -q:v 3                  \  # JPEG quality (2=best, 31=worst; 3 is near-lossless)
  {output_path}
```

The double `-ss` pattern (coarse seek before `-i`, fine seek after) gives both
speed and frame accuracy. A single post-input `-ss` is accurate but slow on long
videos; a single pre-input `-ss` is fast but snaps to the nearest keyframe.

The `-vf scale=800:-1` filter is applied unconditionally: it keeps file sizes
predictable (~30–80 KB per frame), prevents oversized images when the user
downloads at higher quality than 360p, and produces consistent illustration
widths across all sections regardless of the source resolution.

---

### 4.3 CLI — new `illustrate` subcommand

```python
@app.command()
def illustrate(
    output_dir: Path = typer.Argument(..., help="Path to a Phase 1 output directory"),
    quality: str = typer.Option(
        "bestvideo[height<=360]",
        "--quality",
        help="yt-dlp format selector for video download. Lower quality = faster download.",
    ),
    keep_video: bool = typer.Option(
        False, "--keep-video", help="Keep the downloaded video file after frame extraction."
    ),
    skip_existing: bool = typer.Option(
        False,
        "--skip-existing",
        help=(
            "Skip frame extraction for sections whose JPEG already exists on disk. "
            "Useful for resuming an interrupted run. Default is to always overwrite "
            "so stale frames from a previous Phase 1 run are never silently reused."
        ),
    ),
    in_place: bool = typer.Option(
        False, "--in-place", help="Overwrite summary.md instead of writing summary_illustrated.md."
    ),
) -> None:
    """Phase 2: extract key frames and embed them into the markdown summary."""
```

**Execution flow:**

1. Load `metadata.json` from `output_dir` to get `url` and `video_id`.
2. Read `summary.md`, call `illustrator.parse_sections()`.
3. Check ffmpeg availability; abort with instructions if missing.
4. Call `framer.extract_frames()` with a Rich progress bar callback.
5. Call `illustrator.embed_frames()` with the resulting `frame_map`.
6. Write `summary_illustrated.md` (or overwrite `summary.md` if `--in-place`).

---

## 5. Data Model

### Section (parsed from summary.md)

| Field | Type | Description |
|---|---|---|
| `index` | `int` | 0-based section number |
| `heading` | `str` | Text of the `## H2` heading |
| `ts_start` | `float` | Section start in seconds |
| `ts_end` | `float` | Section end in seconds |
| `body_start` | `int` | Line index after the timestamp comment |

### FrameResult

| Field | Type | Description |
|---|---|---|
| `section_index` | `int` | Corresponds to `Section.index` |
| `path` | `Path` | Absolute path to the JPEG file |
| `timestamp` | `float` | The second at which the frame was taken |

---

## 6. Error Handling

| Failure | Behaviour |
|---|---|
| `ffmpeg` not on PATH | `RuntimeError` at startup with installation instructions; exit code 2 |
| Video download fails (network, geo-block, private) | `RuntimeError`; abort Phase 2 entirely |
| Single frame extraction fails | `warnings.warn`; skip that section; continue with others |
| `summary.md` has no timestamp comments | `ValueError`; clean message; exit code 1 |
| `summary.md` has partial timestamp comments | `warnings.warn` for skipped sections; continue |
| `metadata.json` missing or malformed | `ValueError`; instruct user to re-run Phase 1 |

---

## 7. Trade-off Analysis

### T1: Full video download vs. segment-only download

**Full download at 360p**
- ✅ One yt-dlp invocation; simple; robust against servers that block range requests.
- ✅ Allows re-extraction without re-download (`--keep-video`).
- ❌ ~50–150 MB for a typical 60-minute video at 360p.

**`--download-sections` (yt-dlp ≥ 2022.09)**
- ✅ Downloads only ~5 s around each target timestamp; ~1–5 MB total.
- ❌ Multiple yt-dlp invocations or complex multi-range syntax.
- ❌ Not all servers honour `Range` headers; yt-dlp may silently fall back to full download anyway.
- ❌ Requires a newer yt-dlp and is marked experimental.

**Decision:** Full download at 360p for the initial implementation. Add `--download-sections`
as an opt-in flag once the happy path is stable. The `quality` option already lets
power users trade resolution for download size.

---

### T2: Frame selection — midpoint vs. smart selection

**Fixed offset (default: 25% into range)**
- ✅ Zero extra cost; deterministic; no API key required.
- ❌ May land on a title slide, transition, or speaker close-up rather than the
  conceptual content being discussed.

**Vision-model scoring (future `--smart-frames` flag)**
- ✅ Can reject black frames, slides with no content, near-duplicate frames.
- ✅ Can select the frame where the speaker is pointing at a diagram.
- ❌ Requires an additional API call per section (cost + latency).
- ❌ Adds provider dependency to what is otherwise an offline step.

**Decision:** Fixed offset (25%) for MVP. The 25% heuristic skips the opening
statement of a section (which tends to be the speaker talking to camera) and lands
in the explanatory body. A `--smart-frames` flag is the natural Phase 2.1 upgrade.

---

### T3: New `illustrate` command vs. integrated `--illustrate` flag on `run`

**Separate `illustrate` command**
- ✅ Phase 2 is independently re-runnable (no need to re-download captions or call LLM).
- ✅ `run` stays focused; `illustrate` has its own failure surface.
- ✅ Users who only want the text summary don't pay the ffmpeg/video-download cost.
- ❌ Slightly more CLI surface to document.

**`--illustrate` flag on `run`**
- ✅ One command covers the full pipeline; simpler mental model.
- ❌ Any Phase 2 failure aborts or complicates the Phase 1 result.
- ❌ Users must re-run the entire pipeline (including LLM calls) to retry frame extraction.

**Decision:** Separate `illustrate` command. This also makes it easier to add a
future `run --illustrate` shortcut that calls both internally, without baking
the dependency in from the start.

---

### T4: Image format — JPEG vs. WebP vs. PNG

**JPEG**
- ✅ Universal support in all markdown renderers and PDF converters.
- ✅ Compact at quality 3 (~30–100 KB per frame for 360p content).
- ❌ Lossy; irrelevant for thumbnail-grade illustration.

**WebP**
- ✅ ~25% smaller than JPEG at equivalent quality.
- ❌ Not supported in all markdown renderers (notably some Obsidian versions, older VS Code Preview).

**PNG**
- ✅ Lossless.
- ❌ 5–10× larger than JPEG for photographic frames; unacceptable for document embedding.

**Decision:** JPEG at ffmpeg quality 3. Best compatibility, acceptable size.

---

### T5: Re-run safety — always overwrite vs. skip existing frames

**Always overwrite (default)**
- ✅ Correct after a Phase 1 re-run: timestamp ranges may have shifted, so an old
  `section_003.jpg` extracted at t=142 s might now belong to a different section body.
- ✅ Deterministic — running `illustrate` twice on the same input always produces
  the same output directory state.
- ❌ Re-downloads and re-extracts even when nothing changed.

**`--skip-existing` flag (opt-in incremental mode)**
- ✅ Fast resume after a network interruption mid-run.
- ✅ Useful when iterating on the markdown text (Phase 1) without changing timestamp ranges.
- ❌ Silently serves stale frames if Phase 1 was re-run and timestamp ranges shifted.

**Decision:** Overwrite by default; `--skip-existing` as an explicit opt-in. The default
protects correctness; the flag optimises for the common "resume interrupted run" case
where the user knows the timestamps haven't changed.

---

## 8. Testing Strategy

| Layer | What to test |
|---|---|
| `illustrator.parse_sections` | Valid markdown; missing timestamp comments; malformed timestamp format; multiple H2s |
| `illustrator.embed_frames` | Frame injected in correct position; sections not in `frame_map` unchanged; no double-injection on re-run |
| `framer.pick_timestamp` | Within range; 25% offset; clamp at short sections (< 4 s) |
| `framer.check_ffmpeg` | Raises when not on PATH; no-op when available |
| `framer.extract_frame` | Raises `FrameExtractionError` on non-zero ffmpeg exit (mock subprocess) |
| `framer.extract_frames` | Section failure warns and continues; `on_frame` callback fires |
| CLI `illustrate` | Missing `metadata.json`; missing `summary.md`; no timestamp comments; happy path (mocked framer) |

`framer.download_video` and the actual ffmpeg invocation are not unit-tested — they
require network and a system binary. They are covered by a manual integration test
documented in `CONTRIBUTING.md`.

---

## 9. Implementation Plan

| Step | Module | Notes |
|---|---|---|
| 1 | `illustrator.py` | `parse_sections`, `embed_frames` — pure functions, easy to test first |
| 2 | `framer.py` | `check_ffmpeg`, `pick_timestamp`, `extract_frame` — mock subprocess in tests |
| 3 | `framer.py` | `download_video`, `extract_frames` — wires yt-dlp + the above |
| 4 | `cli.py` | Add `illustrate` command; hook up Rich progress bar |
| 5 | `tests/test_illustrator.py` | Full unit coverage for parsing and embedding |
| 6 | `tests/test_framer.py` | Unit coverage for non-network functions |
| 7 | `pyproject.toml` | No new Python deps; add `ffmpeg` note to README |
| 8 | Integration test | Run end-to-end on a short known video; verify frame files and markdown links |

---

## 10. Deferred to Phase 2.1

**Multiple frames per section:** Long sections (> 5 minutes) might benefit from 2–3
frames spread across the range. `extract_frames` is designed to accept a future
`frames_per_section: int` parameter — the per-section loop already isolates the
extraction logic cleanly. Deferred to Phase 2.1; MVP is one frame per section.
