"""Shared pytest fixtures for the youtube-summarizer test suite."""

from __future__ import annotations

from pathlib import Path

import pytest

from youtube_summarizer.transcript import Caption, Chunk

# ---------------------------------------------------------------------------
# Raw VTT samples
# ---------------------------------------------------------------------------

SIMPLE_VTT = """\
WEBVTT

00:00:00.000 --> 00:00:02.500
Hello, welcome to this video.

00:00:02.500 --> 00:00:06.000
Today we will cover three topics.

00:00:06.000 --> 00:00:10.000
The first topic is Python packaging.

"""

# Auto-caption VTT that uses the rolling/karaoke format:
# each cue contains the previous cue's text plus new words.
ROLLING_VTT = """\
WEBVTT

00:00:00.000 --> 00:00:02.000
Hello world

00:00:01.500 --> 00:00:04.000
Hello world this is

00:00:03.500 --> 00:00:06.000
Hello world this is a test

00:00:05.500 --> 00:00:08.000
and another sentence

"""


@pytest.fixture()
def simple_vtt_file(tmp_path: Path) -> Path:
    """A clean VTT file with no rolling duplicates."""
    p = tmp_path / "video123.en.vtt"
    p.write_text(SIMPLE_VTT, encoding="utf-8")
    return p


@pytest.fixture()
def rolling_vtt_file(tmp_path: Path) -> Path:
    """A VTT file in auto-caption karaoke/rolling format."""
    p = tmp_path / "video456.en.vtt"
    p.write_text(ROLLING_VTT, encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Pre-built domain objects
# ---------------------------------------------------------------------------

@pytest.fixture()
def three_captions() -> list[Caption]:
    """Three simple captions spanning 10 seconds."""
    return [
        Caption(start=0.0, end=2.5, text="Hello, welcome to this video."),
        Caption(start=2.5, end=6.0, text="Today we will cover three topics."),
        Caption(start=6.0, end=10.0, text="The first topic is Python packaging."),
    ]


@pytest.fixture()
def two_chunks() -> list[Chunk]:
    """Two pre-built chunks for writer tests."""
    return [
        Chunk(start=0.0, end=45.0, text="Introduction to the topic at hand."),
        Chunk(start=45.0, end=90.0, text="Deep dive into implementation details."),
    ]
