# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-05-09

### Added
- **Phase 2 — frame extraction & illustration.** New `illustrate` subcommand
  takes a Phase 1 output directory, downloads the video at low resolution via
  yt-dlp, extracts one representative JPEG frame per `## H2` section using
  ffmpeg, and produces `summary_illustrated.md` with embedded image references.
  - `youtube-summarizer illustrate output/<video_id>/`
  - `--in-place` overwrites `summary.md` instead of writing a separate file.
  - `--quality` passes a custom yt-dlp format selector (default:
    `bestvideo[height<=360]`).
  - `--keep-video` retains the downloaded video after extraction.
  - `--skip-existing` reuses frames already on disk without re-downloading.
  - Frames written to `output/<video_id>/frames/section_NNN.jpg`.
- **Pluggable LLM providers.** New `providers/` package introduces an
  `LLMProvider` Protocol; the orchestrator (`writer.restructure`) is now
  provider-agnostic. Two providers ship in-tree:
  - `ClaudeProvider` — Anthropic Claude (existing default).
  - `GeminiProvider` — Google Gemini via the `google-genai` SDK; free tier
    available at https://aistudio.google.com/apikey.
- `YT_SUMMARIZER_PROVIDER` env var (default `claude`) and `--provider`
  CLI flag select the active provider.
- `--model` CLI flag overrides the per-provider default model.
- `metadata.json` now records the `provider` and `model` used for each run.
- `py.typed` marker — package is now PEP 561 typed.

### Fixed
- **ffmpeg subprocess timeout.** `extract_frame()` now passes `timeout=60` to
  `subprocess.run`. A hung ffmpeg process (corrupted video or stalled network
  mount) is caught as `subprocess.TimeoutExpired` and re-raised as a
  `FrameExtractionError` with a clear message instead of blocking forever.
- **Inverted timestamp guard.** `parse_sections()` now warns and skips any
  `## H2` section whose `<!-- timestamp: X-Y -->` comment has `Y ≤ X`. Previously
  such a section would silently pass a negative duration to `pick_timestamp`,
  returning a timestamp before the section start.
- **Markdown image alt-text sanitization.** `embed_frames()` strips `[` and `]`
  from LLM-generated headings before writing `![alt](url)` image lines. A
  literal `]` in alt text terminates the Markdown image span early, producing
  invalid output.

### Changed
- **Soft-breaking:** `ANTHROPIC_API_KEY` is no longer read by `Settings`.
  Each provider class resolves its own API key (`ANTHROPIC_API_KEY` for
  Claude, `GOOGLE_API_KEY` / `GEMINI_API_KEY` for Gemini), failing fast at
  provider construction with a provider-specific message.
- `writer.restructure()` accepts an optional `provider=` kwarg for dependency
  injection; default behaviour (factory-built provider) is unchanged.
- Retry logic moved out of `writer.py` and into the shared `providers.base`
  module so each provider plugs in its own retriable-exception predicate.

### Runtime requirements
- **ffmpeg** must be on `PATH` to use the `illustrate` command. The command
  checks for its presence at startup and prints installation instructions if it
  is missing. No new Python package dependency is introduced.

### Dependencies
- Added `google-genai>=0.3.0` (core dep). Can be moved to an optional extra
  later if the install footprint becomes a concern.
- Full `pyproject.toml` rewrite: hatchling build backend, dependency groups, ruff, mypy,
  pytest, and coverage configuration.
- Pre-commit hook configuration (ruff, mypy, standard hygiene hooks).
- GitHub Actions CI workflow (`ci.yml`) — lint, type-check, and test on push/PR.
- GitHub Actions publish workflow (`publish.yml`) — OIDC trusted publishing to PyPI on
  `v*` tags.
- GitHub community files: `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`,
  `CODEOWNERS`, PR template, and issue templates.
- Sphinx documentation structure with furo theme and ReadTheDocs configuration.
- Architecture Decision Record: `docs/decisions/ADR-001-toolchain.md`.
- Test suite scaffolding: `tests/conftest.py`, `test_transcript.py`, `test_downloader.py`,
  `test_writer.py`.

## [0.1.0] - 2026-05-08

### Added
- Phase 1 pipeline: download YouTube captions via `yt-dlp`, parse VTT (including
  rolling/karaoke auto-caption deduplication), chunk into ~90-second segments, and
  restructure into ebook-style Markdown via the Anthropic Claude API.
- CLI entry point `youtube-summarizer` built with Typer and Rich.
- `--lang` option to select caption language (default: `en`).
- `YT_SUMMARIZER_MODEL` environment variable to override the Claude model.
- Output artefacts per video: `metadata.json`, raw `.vtt`, `transcript.txt`, `summary.md`.
- Hidden `<!-- timestamp: start-end -->` comments in each `## H2` section for downstream
  frame-alignment (Phase 2).

[Unreleased]: https://github.com/caalvaro/youtube-summarizer/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/caalvaro/youtube-summarizer/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/caalvaro/youtube-summarizer/releases/tag/v0.1.0
