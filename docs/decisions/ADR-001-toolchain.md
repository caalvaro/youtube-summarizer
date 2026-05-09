# ADR-001: Python package toolchain for youtube-summarizer

**Status:** Accepted  
**Date:** 2026-05-08  
**Deciders:** Álvaro Carvalho  
**Repository:** https://github.com/caalvaro/youtube-summarizer

---

## Context

`youtube-summarizer` is a CLI tool that downloads YouTube captions, restructures them into
illustrated-ebook Markdown via the Anthropic Claude API, and (in future phases) aligns video
frames to the resulting sections. The project is at `v0.1.0` (Phase 1 complete) and must be
packaged for public distribution on PyPI, hosted on GitHub, and maintained as an open-source
project.

The existing baseline:

- `src/` layout with a single `youtube_summarizer` package.
- `setuptools` as the build backend.
- No CI, no linting config, no type-checking config, no tests, no docs.
- No pre-commit hooks, no community files, no license file.

Goals driving this ADR:

1. **Reproducible builds** across developer machines and CI with a single command.
2. **Enforced code quality** — linting, formatting, and strict typing in every commit.
3. **Safe, automated PyPI publishing** without long-lived secrets.
4. **Contributor-ready** open-source repository with clear contribution paths.
5. **Living documentation** auto-generated from docstrings and hosted for free.

---

## Decisions

### 1. Build backend — hatchling

**Options evaluated:**

| Backend | PEP 517 | `src/` layout | Dynamic version | Config verbosity |
|---|---|---|---|---|
| `setuptools` | ✓ | requires explicit config | via `__version__` | Medium-high |
| `flit-core` | ✓ | implicit | via `__version__` | Low |
| `hatchling` | ✓ | implicit | via `hatch-vcs` or static | Very low |
| `pdm-backend` | ✓ | implicit | via `pdm-vcs` | Low |

**Decision: `hatchling`.**

Hatchling is the reference backend used by PyPA's own tooling tutorials. It supports `src/`
layout with zero extra configuration, does not require a `MANIFEST.in`, and has first-class
support for dynamic versioning via `hatch-vcs` (not needed yet but easy to add). Its build
output is deterministic and it produces both sdist and wheel correctly from the same config.

`setuptools` remains the most widely deployed backend, but its implicit-glob behaviour and
`MANIFEST.in` footguns are well-documented pain points for maintainers. `flit-core` is simpler
but less extensible. `pdm-backend` is excellent but ties the project to a less ubiquitous
ecosystem.

**Consequence:** `pyproject.toml` gains a `[tool.hatch.build.targets.wheel]` stanza pointing at
`src/`; the `[build-system]` table changes to require `hatchling`.

---

### 2. Package manager — uv

**Options evaluated:**

| Tool | Speed | Lockfile | `src/` layout | Workspace | Maturity |
|---|---|---|---|---|---|
| `pip` + `venv` | Baseline | No (pip-compile) | Manual | No | Stable |
| `pip-tools` | ~pip | Yes (requirements.txt) | Manual | No | Stable |
| `poetry` | Moderate | Yes | Yes | Limited | Mature |
| `pdm` | Fast | Yes (PEP 582) | Yes | Yes | Growing |
| `uv` | 10–100× faster | Yes (`uv.lock`) | Yes | Yes | Astral-backed |

**Decision: `uv`.**

`uv` is a Rust-based Python package manager from Astral (the team behind `ruff`). It is
wire-compatible with PyPI, resolves dependencies 10–100× faster than pip, and produces a
cross-platform `uv.lock` lockfile that guarantees reproducibility without any extra tooling.
It supports PEP 735 `[dependency-groups]` natively, making it straightforward to separate
`dev`, `docs`, and `typing` dependency surfaces. It ships a single binary with no Python
dependency, so CI bootstrap is trivial via `astral-sh/setup-uv@v4`.

`poetry` is mature but ships its own resolver with known conflict-resolution quirks and wraps
`pyproject.toml` in non-standard sections. `pip-tools` is stable but manual and does not
support workspace-level operations.

**Workflow:**

```
uv sync --group dev          # install main + dev deps
uv sync --group docs         # install main + docs deps
uv run pytest                # run inside managed venv
uv build                     # produce sdist + wheel into dist/
uv publish                   # upload to PyPI
```

**Consequence:** contributors install `uv` once (`curl -Ls https://astral.sh/uv | sh`); no
`requirements*.txt` files are maintained; `uv.lock` is committed to the repository.

---

### 3. Linting and formatting — ruff

**Options evaluated:**

| Tool | Speed | Rules covered | Config file | Single tool |
|---|---|---|---|---|
| `flake8` + `black` + `isort` | Moderate | E/W/F + style + imports | Multiple | No |
| `pylint` + `black` | Slow | Very broad | Multiple | No |
| `ruff` | Rust, ~100× flake8 | E/W/F/I/UP/B/SIM/N/ANN/C4/PTH + more | `pyproject.toml` | Yes |

**Decision: `ruff` for both linting and formatting.**

Ruff implements a superset of flake8, isort, pyupgrade, flake8-bugbear, pep8-naming, and
dozens of other plugins in a single Rust binary. It replaces the entire
`flake8 + black + isort` stack with a configuration that lives entirely in `pyproject.toml`.
Its formatter is Black-compatible (same AST guarantees) so existing Black-formatted code
passes without changes.

Rule selection for this project:

| Code | Plugin | Rationale |
|---|---|---|
| `E`, `W` | pycodestyle | PEP 8 baseline |
| `F` | pyflakes | Undefined names, unused imports |
| `I` | isort | Import ordering |
| `UP` | pyupgrade | Keep syntax current with Python 3.12 |
| `B` | flake8-bugbear | Common bug patterns |
| `SIM` | flake8-simplify | Unnecessary complexity |
| `N` | pep8-naming | Consistent naming conventions |
| `ANN` | flake8-annotations | Enforce type annotations |
| `C4` | flake8-comprehensions | Idiomatic comprehensions |
| `PTH` | flake8-use-pathlib | Prefer `pathlib` over `os.path` |
| `RUF` | ruff-specific | Ruff's own rules |

`ANN101`/`ANN102` (annotate `self`/`cls`) and `ANN401` (disallow `Any`) are suppressed as
they produce noise without safety benefit. Tests are excluded from `ANN` rules entirely.

**Consequence:** `.flake8`, `setup.cfg` linting sections, and any `black`/`isort` config
are not needed. A single `[tool.ruff]` block in `pyproject.toml` covers everything.

---

### 4. Type checking — mypy (strict)

**Options evaluated:**

| Tool | Strictness | Speed | IDE support | Stubs ecosystem |
|---|---|---|---|---|
| `mypy` | Configurable up to strict | Moderate | Excellent | Excellent |
| `pyright` | Configurable | Fast | Excellent (VS Code) | Good |
| `pytype` | Fixed | Slow | Limited | Limited |

**Decision: `mypy` with `strict = true`.**

`mypy` is the de-facto standard for Python static type checking. `strict` mode enables:

- `--disallow-untyped-defs` — every function must be annotated.
- `--disallow-any-generics` — no bare `list`, `dict`, etc.
- `--warn-return-any` — functions must not silently return `Any`.
- `--no-implicit-reexport` — exported symbols must be explicit in `__all__`.

`yt_dlp` has no published stubs; its module is silenced via an `[[tool.mypy.overrides]]` block.

`pyright` is excellent (especially in VS Code via Pylance) and may be added as a secondary
check in future, but `mypy` is chosen as the primary gate because its error messages are more
widely understood across the Python ecosystem.

**Known issue in `writer.py`:** the line `if not anthropic:` tests the truthiness of the
imported module object, which is always truthy. The intent is to guard against a missing API
key — this should be replaced with `if not ANTHROPIC_API_KEY:` from `config`. This is a bug
to be fixed before `v1.0.0` but is tracked here rather than silently suppressed.

**Consequence:** all public functions must carry complete type annotations. New code that
fails `mypy --strict` does not merge.

---

### 5. Pre-commit hooks

**Decision: `pre-commit` framework.**

The following hooks run on every `git commit` locally and are mirrored in CI:

| Hook | Source | Purpose |
|---|---|---|
| `ruff-pre-commit` (check) | `astral-sh/ruff-pre-commit` | Lint |
| `ruff-pre-commit` (format) | `astral-sh/ruff-pre-commit` | Format |
| `mypy` | local (uv run) | Type check |
| `trailing-whitespace` | `pre-commit-hooks` | Whitespace hygiene |
| `end-of-file-fixer` | `pre-commit-hooks` | Newline at EOF |
| `check-toml` | `pre-commit-hooks` | Valid TOML |
| `check-yaml` | `pre-commit-hooks` | Valid YAML |
| `check-merge-conflict` | `pre-commit-hooks` | Stray conflict markers |
| `no-commit-to-branch` | `pre-commit-hooks` | Block direct commits to `main` |

Contributors install once with `uv run pre-commit install`.

---

### 6. Testing — pytest + pytest-cov

**Decision: `pytest` with `pytest-cov` for coverage.**

`pytest` is the dominant testing framework in the Python ecosystem. Coverage is measured via
`pytest-cov` (which wraps `coverage.py`) and emitted in both terminal (missing-lines) and XML
formats. The XML report is consumed by Codecov in CI for PR annotations.

Test surface for Phase 1:

- `test_transcript.py` — VTT parsing (including rolling-caption deduplication), chunking,
  timestamp formatting.
- `test_downloader.py` — `_pick_lang` logic, `CaptionsUnavailable` propagation (yt-dlp
  mocked via `unittest.mock.patch`).
- `test_writer.py` — `_build_user_message` output shape, `restructure` return value
  (Anthropic client mocked).

Phases 2 and 3 will require additional test files as new modules are introduced.

**Coverage target:** 80 % line coverage as a CI gate; this will increase as the project
matures.

---

### 7. Documentation — Sphinx + furo + ReadTheDocs

**Options evaluated:**

| Stack | Auto-API | Type hints | Theme | RTD support |
|---|---|---|---|---|
| MkDocs + Material | Via mkdocstrings | Partial | Modern | Good |
| Sphinx + RTD theme | autodoc | Full (typehints ext) | Classic | Native |
| Sphinx + furo | autodoc | Full (typehints ext) | Modern | Native |

**Decision: Sphinx with the `furo` theme, hosted on ReadTheDocs.**

Sphinx is the reference documentation system for the Python ecosystem. `furo` is a clean,
accessible, dark-mode-capable theme used by projects such as pip, black, and cryptography.
`sphinx-autodoc-typehints` renders PEP 484 annotations directly in the generated API docs
without requiring a separate `:type:` field in every docstring.

ReadTheDocs provides free hosting, webhook-triggered builds on every push to `main`, and
versioned documentation tied to Git tags — all with zero infrastructure cost.

The Sphinx configuration uses:
- `autodoc` — auto-generate API reference from docstrings.
- `napoleon` — accept Google-style docstrings (more readable than RST in source).
- `sphinx-autodoc-typehints` — pull type annotations into the API docs.
- `sphinx-copybutton` — one-click copy on code blocks.
- `intersphinx` — cross-reference Python stdlib docs.

---

### 8. CI/CD — GitHub Actions with OIDC trusted publishing

**Pipeline layout:**

```
.github/workflows/
├── ci.yml        # runs on every push and PR to main
└── publish.yml   # runs when a v* tag is pushed
```

**`ci.yml` jobs:**

| Job | Steps |
|---|---|
| `quality` | checkout → setup-uv → `uv sync --group dev` → `ruff check` → `ruff format --check` → `mypy src/` |
| `test` | checkout → setup-uv → `uv sync --group dev` → `pytest` → upload coverage to Codecov |

**`publish.yml` jobs:**

| Job | Steps |
|---|---|
| `build` | checkout → setup-uv → `uv sync` → `uv build` → upload dist artifact |
| `publish` | download dist artifact → `pypa/gh-action-pypi-publish` (OIDC) |

**PyPI OIDC trusted publishing** eliminates the need for long-lived API tokens. The publishing
workflow requests a short-lived OIDC token from GitHub, which PyPI validates against the
registered trusted publisher configuration. To activate this, the maintainer must visit
`pypi.org/manage/account/publishing/` once and register:
- Owner: `caalvaro`
- Repository: `youtube-summarizer`
- Workflow: `publish.yml`
- Environment: `pypi`

**Release process:**

```bash
# 1. Update CHANGELOG.md and bump version in pyproject.toml
# 2. Commit and push to main
git tag v0.2.0
git push origin v0.2.0
# publish.yml triggers automatically
```

---

### 9. Versioning strategy — Semantic Versioning

**Decision: SemVer (`MAJOR.MINOR.PATCH`).**

The project is a CLI tool and importable library. SemVer communicates compatibility guarantees
clearly to downstream consumers:

- `PATCH` — bug fixes, no API changes.
- `MINOR` — new features, backwards-compatible.
- `MAJOR` — breaking API or CLI changes.

Version is declared once in `pyproject.toml` (`version = "0.1.0"`) and re-exported from
`youtube_summarizer/__init__.py` as `__version__`. There is no dynamic version derivation
from Git tags at this stage; this can be added via `hatch-vcs` if the release cadence
warrants it.

---

### 10. Branch and protection strategy

**Decision:**

- `main` is the single integration branch. All changes land via pull request.
- Branch protection rules (configure in GitHub → Settings → Branches):
  - Require at least 1 approving review.
  - Require status checks to pass before merging (`quality`, `test`).
  - Do not allow force-pushes.
- Feature branches: `feat/<short-description>`.
- Bug-fix branches: `fix/<short-description>`.
- Release branches are not used; tags drive releases.

---

## Project structure (post-ADR)

```
youtube-summarizer/
├── .github/
│   ├── ISSUE_TEMPLATE/
│   │   ├── bug_report.yml
│   │   └── feature_request.yml
│   ├── workflows/
│   │   ├── ci.yml
│   │   └── publish.yml
│   ├── CODEOWNERS
│   └── pull_request_template.md
├── docs/
│   ├── decisions/
│   │   └── ADR-001-toolchain.md          ← this file
│   ├── guides/
│   │   ├── installation.rst
│   │   └── usage.rst
│   ├── _static/
│   ├── conf.py
│   └── index.rst
├── src/
│   └── youtube_summarizer/
│       ├── __init__.py                   ← exports __version__, __all__
│       ├── __main__.py                   ← Typer CLI entry point
│       ├── config.py                     ← env-var config
│       ├── downloader.py                 ← yt-dlp wrapper
│       ├── transcript.py                 ← VTT parser + chunker
│       ├── writer.py                     ← Claude API wrapper
│       └── py.typed                      ← PEP 561 marker
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_transcript.py
│   ├── test_downloader.py
│   └── test_writer.py
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── .readthedocs.yaml
├── CHANGELOG.md
├── CODE_OF_CONDUCT.md
├── CONTRIBUTING.md
├── LICENSE
├── README.md
├── SECURITY.md
├── pyproject.toml
└── uv.lock                               ← committed, generated by uv
```

---

## Consequences

**What becomes easier:**

- A new contributor can go from `git clone` to a passing test suite with three commands:
  `uv sync --group dev`, `uv run pre-commit install`, `uv run pytest`.
- Publishing a new release is a single `git tag` + `git push`.
- Type errors and style violations are caught locally before CI ever runs.
- API documentation is always in sync with source code via autodoc.

**What becomes harder:**

- Contributors must install `uv` and `pre-commit` (both are single-binary installs with no
  Python dependency; the CONTRIBUTING guide covers this).
- `mypy --strict` requires annotations on all functions, including private helpers. Legacy
  code written before this ADR must be annotated incrementally.
- OIDC trusted publishing requires a one-time manual setup step on PyPI.

**What to revisit before v1.0.0:**

1. Fix the `if not anthropic:` bug in `writer.py`.
2. Validate `claude-opus-4-7` model name when it becomes available; update `config.py`
   default if the string changes.
3. Consider `hatch-vcs` for automatic version derivation from Git tags.
4. Evaluate adding `pyright` as a secondary type check in CI.
5. Add a `test_config.py` covering the `MODEL`/`ANTHROPIC_API_KEY` env-var overrides.

---

## Action items (in order)

- [ ] Verify `youtube-summarizer` name is available on PyPI (`pip index versions youtube-summarizer`).
- [ ] Apply all changes from this ADR (pyproject.toml, config files, workflows, tests, docs).
- [ ] Create GitHub repository `caalvaro/youtube-summarizer`, push, and set branch protection.
- [ ] Register OIDC trusted publisher on `pypi.org` (owner: `caalvaro`, repo:
      `youtube-summarizer`, workflow: `publish.yml`, environment: `pypi`).
- [ ] Connect ReadTheDocs to the repository via the RTD dashboard.
- [ ] Add `ANTHROPIC_API_KEY` and `CODECOV_TOKEN` as repository secrets in GitHub Settings.
- [ ] Run `uv run pre-commit run --all-files` locally and fix any remaining violations.
- [ ] Tag `v0.1.0` to trigger the first PyPI publish.
