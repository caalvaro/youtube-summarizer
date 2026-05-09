# youtube-summarizer

[![PyPI version](https://img.shields.io/pypi/v/youtube-summarizer.svg)](https://pypi.org/project/youtube-summarizer/)
[![CI](https://img.shields.io/github/actions/workflow/status/caalvaro/youtube-summarizer/ci.yml?branch=main&label=CI)](https://github.com/caalvaro/youtube-summarizer/actions)
[![Coverage](https://img.shields.io/codecov/c/github/caalvaro/youtube-summarizer)](https://codecov.io/gh/caalvaro/youtube-summarizer)
[![Docs](https://readthedocs.org/projects/youtube-summarizer/badge/?version=latest)](https://youtube-summarizer.readthedocs.io)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

Turn a YouTube URL into an illustrated-ebook Markdown summary powered by [Claude](https://www.anthropic.com/).

---

## How it works

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
output/<video_id>/summary.md
```

Each `## H2` section in the output carries a hidden `<!-- timestamp: start-end -->` comment
so Phase 2 can align video frames to sections.

## Roadmap

| Phase | Status | Description |
|---|---|---|
| 1 | ✅ Done | Caption extraction → Markdown restructuring |
| 2 | 🔜 Next | Frame extraction via Claude vision (pick diagrams, demos, charts) |
| 3 | 🔜 Next | Stitch frames into Markdown → illustrated ebook |

Videos without captions (manual or auto-generated) are skipped — there is no audio-transcription fallback by design.

## Installation

```bash
pip install youtube-summarizer
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv tool install youtube-summarizer
```

## Setup

Create a `.env` file in your working directory and add your [Anthropic API key](https://console.anthropic.com/):

```bash
cp .env.example .env
# edit .env → ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

```bash
youtube-summarizer "https://www.youtube.com/watch?v=VIDEO_ID"
```

Output is written to `output/<video_id>/`:

| File | Contents |
|---|---|
| `metadata.json` | Title, channel, duration, URL, caption source |
| `<id>.<lang>.vtt` | Raw captions from yt-dlp |
| `transcript.txt` | Cleaned, timestamped flat transcript |
| `summary.md` | Structured ebook-style Markdown — the deliverable |

### Options

```bash
# Select caption language (default: en)
youtube-summarizer --lang pt "https://www.youtube.com/watch?v=..."

# Use a different Claude model (default: claude-opus-4-7)
YT_SUMMARIZER_MODEL=claude-sonnet-4-6 youtube-summarizer "https://..."
```

### Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | No captions available, or captions parsed to empty |
| `2` | `ANTHROPIC_API_KEY` not set |

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
