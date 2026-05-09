"""Sphinx configuration for youtube-summarizer documentation."""

from __future__ import annotations

import sys
from pathlib import Path

# Make the src/ package importable without installing.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# ---------------------------------------------------------------------------
# Project metadata
# ---------------------------------------------------------------------------

project = "youtube-summarizer"
author = "Álvaro Carvalho"
copyright = "2026, Álvaro Carvalho"  # noqa: A001

# Pull version from the package so it stays in sync with pyproject.toml.
from youtube_summarizer import __version__  # noqa: E402

version = __version__
release = __version__

# ---------------------------------------------------------------------------
# General configuration
# ---------------------------------------------------------------------------

extensions = [
    "sphinx.ext.autodoc",       # auto-generate API docs from docstrings
    "sphinx.ext.napoleon",      # Google-style docstring support
    "sphinx.ext.intersphinx",   # cross-reference Python stdlib
    "sphinx.ext.viewcode",      # add source links to API pages
    "sphinx_autodoc_typehints", # render PEP 484 annotations in docs
    "sphinx_copybutton",        # one-click copy on code blocks
    "myst_parser",              # allow .md files alongside .rst
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# ---------------------------------------------------------------------------
# Autodoc
# ---------------------------------------------------------------------------

autodoc_member_order = "bysource"
autodoc_typehints = "description"       # put type info in description, not signature
autodoc_typehints_format = "short"      # use short names (Path instead of pathlib.Path)
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}

# ---------------------------------------------------------------------------
# Napoleon (Google-style docstrings)
# ---------------------------------------------------------------------------

napoleon_google_docstring = True
napoleon_numpy_docstring = False
napoleon_include_init_with_doc = True
napoleon_use_rtype = False              # rtype already covered by typehints extension

# ---------------------------------------------------------------------------
# Intersphinx — link to Python stdlib docs
# ---------------------------------------------------------------------------

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "anthropic": ("https://python.anthropic.com", None),
}

# ---------------------------------------------------------------------------
# HTML output — furo theme
# ---------------------------------------------------------------------------

html_theme = "furo"
html_static_path = ["_static"]
html_title = "youtube-summarizer"

html_theme_options = {
    "source_repository": "https://github.com/caalvaro/youtube-summarizer",
    "source_branch": "main",
    "source_directory": "docs/",
    "footer_icons": [
        {
            "name": "GitHub",
            "url": "https://github.com/caalvaro/youtube-summarizer",
            "html": "",
            "class": "fa-brands fa-github fa-2x",
        },
    ],
}

# ---------------------------------------------------------------------------
# MyST parser (Markdown support)
# ---------------------------------------------------------------------------

myst_enable_extensions = ["colon_fence"]
