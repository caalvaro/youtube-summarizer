# Contributing to youtube-summarizer

Thank you for your interest in contributing. This document covers everything you need to go
from a fresh clone to an accepted pull request.

## Prerequisites

| Tool | Install |
|---|---|
| [uv](https://docs.astral.sh/uv/) | `curl -Ls https://astral.sh/uv \| sh` |
| Python 3.12+ | `uv python install 3.12` |
| Git | System package manager |

## Local development setup

```bash
git clone https://github.com/caalvaro/youtube-summarizer.git
cd youtube-summarizer

# Install all dependencies (main + dev group)
uv sync --group dev

# Install pre-commit hooks (runs ruff + mypy on every commit)
uv run pre-commit install

# Copy the env template and add your Anthropic API key
cp .env.example .env
# edit .env → ANTHROPIC_API_KEY=sk-ant-...
```

## Running the quality checks

```bash
# Lint
uv run ruff check .

# Format check (does not modify files)
uv run ruff format --check .

# Auto-fix lint + format
uv run ruff check --fix . && uv run ruff format .

# Type check
uv run mypy src/

# Run the test suite
uv run pytest

# Run all pre-commit hooks on every file
uv run pre-commit run --all-files
```

All of these must pass before a PR is ready for review.

## Project structure

```
src/youtube_summarizer/   # Package source
tests/                    # pytest test suite
docs/                     # Sphinx documentation source
docs/decisions/           # Architecture Decision Records
.github/workflows/        # CI + publish pipelines
```

## Branching and commit conventions

- Branch from `main`:  `git checkout -b feat/my-feature` or `fix/issue-123`.
- Keep commits small and focused; one logical change per commit.
- Write commit messages in imperative mood: *"Add frame-selection module"*, not
  *"Added frame-selection module"*.
- Do not commit directly to `main` — the pre-commit hook will block you.

## Opening a pull request

1. Ensure all checks pass locally.
2. Update `CHANGELOG.md` — add a line under `[Unreleased]` describing your change.
3. Push your branch and open a PR against `main`.
4. Fill out the PR template fully. Incomplete templates slow review.
5. A maintainer will review and may request changes. Once approved and CI is green, it
   will be merged via squash merge.

## Architecture Decision Records

Significant design decisions are documented in `docs/decisions/`. If your PR changes an
existing architectural choice (e.g. swaps a dependency, changes the data model), please
either update the relevant ADR or create a new one with **Status: Proposed** for discussion
before implementation.

## Code style

- All public functions and classes must have Google-style docstrings and complete type
  annotations.
- Prefer `pathlib.Path` over `os.path` (enforced by ruff `PTH` rules).
- Prefer `dataclasses` for plain data containers.
- Do not add `# type: ignore` without a comment explaining why; suppressions are reviewed
  carefully.

## Reporting security vulnerabilities

Please do **not** open a public issue. See [SECURITY.md](SECURITY.md) for the private
disclosure process.
