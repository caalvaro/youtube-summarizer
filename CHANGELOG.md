# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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

### Changed
- **Soft-breaking:** `ANTHROPIC_API_KEY` is no longer read by `Settings`.
  Each provider class resolves its own API key (`ANTHROPIC_API_KEY` for
  Claude, `GOOGLE_API_KEY` / `GEMINI_API_KEY` for Gemini), failing fast at
  provider construction with a provider-specific message.
- `writer.restructure()` accepts an optional `provider=` kwarg for dependency
  injection; default behaviour (factory-built provider) is unchanged.
- Retry logic moved out of `writer.py` and into the shared `providers.base`
  module so each provider plugs in its own retriable-exception predicate.

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

[Unreleased]: https://github.com/caalvaro/youtube-summarizer/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/caalvaro/youtube-summarizer/releases/tag/v0.1.0
