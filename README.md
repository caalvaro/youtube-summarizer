# youtube-summarizer

[![PyPI version](https://img.shields.io/pypi/v/youtube-summarizer.svg)](https://pypi.org/project/youtube-summarizer/)
[![CI](https://img.shields.io/github/actions/workflow/status/caalvaro/youtube-summarizer/ci.yml?branch=main&label=CI)](https://github.com/caalvaro/youtube-summarizer/actions)
[![Coverage](https://img.shields.io/codecov/c/github/caalvaro/youtube-summarizer)](https://codecov.io/gh/caalvaro/youtube-summarizer)
[![Docs](https://readthedocs.org/projects/youtube-summarizer/badge/?version=latest)](https://youtube-summarizer.readthedocs.io)
[![Python 3.13+](https://img.shields.io/badge/python-3.13+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Turn a YouTube URL into an illustrated-ebook Markdown summary powered by [Claude](https://www.anthropic.com/).

---

## How it works

**Phase 1 — summarise (`run`)**

```
YouTube URL
    │
    ▼
downloader.fetch()      ← yt-dlp: probe metadata, download .vtt captions
    │
    ▼
transcript.parse_vtt()  ← strip timing tags, deduplicate rolling auto-captions
    │
    ▼
transcript.to_chunks()  ← group into ~90-second segments
    │
    ▼
writer.restructure()    ← Claude: rewrite into clean ebook-style Markdown
    │
    ▼
output/<video_id>/summary.md   (each ## H2 carries a hidden timestamp comment)
```

**Phase 2 — illustrate (`illustrate`)**

```
output/<video_id>/summary.md
    │
    ▼
illustrator.parse_sections()  ← extract (heading, timestamp range) pairs
    │
    ▼
framer.download_video()       ← yt-dlp: low-res video-only stream
    │
    ▼
framer.extract_frame()        ← ffmpeg double-seek: one JPEG per section
    │
    ▼
illustrator.embed_frames()    ← inject ![alt](frames/section_NNN.jpg) lines
    │
    ▼
output/<video_id>/summary_illustrated.md
```

## Roadmap

| Phase | Status | Description |
|---|---|---|
| 1 | ✅ Done | Caption extraction → Markdown restructuring |
| 2 | ✅ Done | Frame extraction → illustrated Markdown (`summary_illustrated.md`) |
| 3 | 🔜 Next | Claude vision — select best frames (diagrams, demos, charts) |

Videos without captions (manual or auto-generated) are skipped — there is no audio-transcription fallback by design.

## Installation

```bash
pip install youtube-summarizer
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install youtube-summarizer
```

### Runtime prerequisites

| Prerequisite | Required for | Install |
|---|---|---|
| Python 3.13+ | all commands | [python.org](https://www.python.org/downloads/) |
| `ffmpeg` | `illustrate` command | `brew install ffmpeg` · `sudo apt install ffmpeg` · [ffmpeg.org](https://ffmpeg.org/download.html) |

## Setup

Create a `.env` file in your working directory and add your [Anthropic API key](https://console.anthropic.com/):

```bash
cp .env.example .env
# edit .env → ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

### Phase 1 — summarise

```bash
youtube-summarizer run "https://www.youtube.com/watch?v=VIDEO_ID"
```

Output is written to `output/<video_id>/`:

| File | Contents |
|---|---|
| `metadata.json` | Title, channel, duration, URL, caption source, provider, model |
| `<id>.<lang>.vtt` | Raw captions from yt-dlp |
| `transcript.txt` | Cleaned, timestamped flat transcript |
| `summary.md` | Structured ebook-style Markdown with hidden timestamp comments |

### Phase 2 — illustrate

```bash
youtube-summarizer illustrate output/<video_id>/
```

Requires `ffmpeg` on `PATH`. Output:

| File | Contents |
|---|---|
| `summary_illustrated.md` | `summary.md` with `![…](frames/section_NNN.jpg)` lines injected |
| `frames/section_NNN.jpg` | One representative JPEG per `## H2` section (800 px wide) |

Options:

```bash
# Overwrite summary.md in-place instead of creating summary_illustrated.md
youtube-summarizer illustrate output/<video_id>/ --in-place

# Keep the downloaded video after extraction
youtube-summarizer illustrate output/<video_id>/ --keep-video

# Skip sections whose JPEG already exists (useful for partial reruns)
youtube-summarizer illustrate output/<video_id>/ --skip-existing

# Use a higher-quality video for sharper frames
youtube-summarizer illustrate output/<video_id>/ --quality "bestvideo[height<=720]"
```

### Phase 1 options

```bash
# Select caption language (default: en)
youtube-summarizer run --lang pt "https://www.youtube.com/watch?v=..."

# Use Gemini instead of Claude
youtube-summarizer run --provider gemini "https://..."

# Override the model
youtube-summarizer run --model claude-sonnet-4-6 "https://..."
```

### Exit codes

| Code | Command | Meaning |
|---|---|---|
| `0` | both | Success |
| `1` | `run` | No captions available, captions parsed to empty, or LLM error |
| `1` | `illustrate` | Missing/invalid input files, parse failure, download error, or no frames extracted |
| `2` | `run` | Provider API key not set or provider misconfigured |
| `2` | `illustrate` | `ffmpeg` not found on `PATH` |

## Development

```bash
git clone https://github.com/caalvaro/youtube-summarizer.git
cd youtube-summarizer

# Install all deps (main + dev group)
uv sync --group dev

# Install pre-commit hooks
uv run pre-commit install

# Run the test suite
uv run pytest

# Lint + format check
uv run ruff check . && uv run ruff format --check .

# Type check
uv run mypy src/
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full contributor workflow and
[docs/decisions/](docs/decisions/) for Architecture Decision Records.

## License

[MIT](LICENSE) © 2026 Álvaro Carvalho
