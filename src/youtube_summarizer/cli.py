"""Typer application for the youtube-summarizer command-line interface.

Kept separate from :mod:`youtube_summarizer.__main__` so that the CLI surface
can be exercised by :class:`typer.testing.CliRunner` without going through
``python -m`` entry-point semantics.
"""

from __future__ import annotations

import json

import typer
import yt_dlp.utils
from rich.console import Console

from . import downloader, transcript, writer
from .config import OUTPUT_DIR, get_settings

app = typer.Typer(help="Turn a YouTube URL into an illustrated-ebook markdown summary.")
console = Console()


@app.command()
def run(
    url: str = typer.Argument(..., help="YouTube video URL"),
    lang: str = typer.Option("en", "--lang", help="Caption language code (default: en)"),
) -> None:
    """Phase 1: download captions and produce a structured markdown summary."""
    settings = get_settings()
    if not settings.api_key:
        console.print(
            "[red]ANTHROPIC_API_KEY is not set. Add it to .env or your environment.[/red]"
        )
        raise typer.Exit(code=2)

    console.print(f"[cyan]Fetching captions for[/cyan] {url}")
    try:
        info = downloader.fetch(url, OUTPUT_DIR, lang=lang)
    except downloader.CaptionsUnavailable as exc:
        console.print(f"[yellow]{exc}[/yellow]")
        raise typer.Exit(code=1) from None
    except yt_dlp.utils.YoutubeDLError as exc:
        # Catches DownloadError, ExtractorError, and the wider yt-dlp tail —
        # surfaces a clean message instead of a raw traceback at the user.
        console.print(f"[red]Failed to fetch video: {exc}[/red]")
        raise typer.Exit(code=1) from None

    console.print(
        f"[green]Got captions[/green] ({info.captions_source}) — {info.title} "
        f"({transcript.format_timestamp(info.duration)})"
    )

    captions = transcript.parse_vtt(info.captions_path)
    if not captions:
        console.print("[red]Captions file parsed to empty. Aborting.[/red]")
        raise typer.Exit(code=1)

    chunks = transcript.to_chunks(captions)
    console.print(
        f"[cyan]Parsed[/cyan] {len(captions)} cues -> {len(chunks)} chunks "
        f"covering {transcript.format_timestamp(chunks[-1].end)}"
    )

    raw_transcript_path = info.output_dir / "transcript.txt"
    raw_transcript_path.write_text(
        "\n".join(f"[{c.start:.1f}-{c.end:.1f}] {c.text}" for c in captions),
        encoding="utf-8",
    )

    metadata_path = info.output_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "video_id": info.video_id,
                "title": info.title,
                "channel": info.channel,
                "duration": info.duration,
                "url": info.url,
                "captions_source": info.captions_source,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    console.print("[cyan]Asking Claude to restructure...[/cyan]")
    markdown = writer.restructure(
        title=info.title,
        channel=info.channel,
        chunks=chunks,
    )

    summary_path = info.output_dir / "summary.md"
    summary_path.write_text(markdown, encoding="utf-8")

    console.print(f"[green]Done.[/green] Wrote [bold]{summary_path}[/bold]")
