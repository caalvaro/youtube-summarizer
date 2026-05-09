"""``python -m youtube_summarizer`` entry point.

The Typer application lives in :mod:`youtube_summarizer.cli`; this module
exists only so the package is invocable via ``python -m``.
"""

from __future__ import annotations

from .cli import app

if __name__ == "__main__":
    app()
