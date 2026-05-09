# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- `py.typed` marker — package is now PEP 561 typed.
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
