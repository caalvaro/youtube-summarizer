"""youtube-summarizer: turn YouTube videos into illustrated-ebook markdown summaries.

Typical usage via the CLI::

    youtube-summarizer "https://www.youtube.com/watch?v=VIDEO_ID"

Or programmatically::

    from youtube_summarizer import downloader, transcript, writer
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("youtube-summarizer")
except PackageNotFoundError:  # editable install / running from source tree
    __version__ = "0.0.0"

__all__ = ["__version__"]
