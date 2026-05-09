"""Typer application for the youtube-summarizer command-line interface.

Kept separate from :mod:`youtube_summarizer.__main__` so that the CLI surface
can be exercised by :class:`typer.testing.CliRunner` without going through
``python -m`` entry-point semantics.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import typer
import yt_dlp.utils
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from . import downloader, framer, illustrator, transcript, writer
from .config import OUTPUT_DIR, get_settings
from .framer import FrameResult
from .providers import LLMProvider, get_provider

app = typer.Typer(help="Turn a YouTube URL into an illustrated-ebook markdown summary.")
console = Console()


@app.command()
def run(
    url: str = typer.Argument(..., help="YouTube video URL"),
    lang: str = typer.Option("en", "--lang", help="Caption language code (default: en)"),
    provider_name: str | None = typer.Option(
        None,
        "--provider",
        help="LLM provider: 'claude' or 'gemini'. Overrides YT_SUMMARIZER_PROVIDER.",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Model identifier. Overrides YT_SUMMARIZER_MODEL.",
    ),
    segment_chars: int = typer.Option(
        12_000,
        "--segment-chars",
        help=(
            "Target transcript characters per LLM segment for long videos. "
            "Videos whose total transcript exceeds this threshold are split into "
            "multiple segments, each processed by a separate LLM call. "
            "Default: 12 000."
        ),
    ),
) -> None:
    """Phase 1: download captions and produce a structured markdown summary."""
    # Build the provider first — we'd rather fail on misconfiguration BEFORE
    # spending several seconds in yt-dlp.
    settings = get_settings()
    if provider_name is not None:
        settings = replace(settings, provider=provider_name)
    if model is not None:
        settings = replace(settings, model=model)

    try:
        provider = get_provider(settings)
    except (ValueError, RuntimeError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from None

    console.print(f"[cyan]Provider:[/cyan] {provider.name} ([bold]{provider.model}[/bold])")
    console.print(f"[cyan]Fetching captions for[/cyan] {url}")
    try:
        info = downloader.fetch(url, OUTPUT_DIR, lang=lang)
    except downloader.CaptionsUnavailableError as exc:
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
                "provider": provider.name,
                "model": provider.model,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    summary_path = info.output_dir / "summary.md"
    console.print(f"[cyan]Asking {provider.name} to restructure...[/cyan]")
    _summarise(info, chunks, provider, summary_path, segment_chars=segment_chars)

    console.print(f"[green]Done.[/green] Wrote [bold]{summary_path}[/bold]")


@app.command()
def illustrate(
    output_dir: Path = typer.Argument(
        ...,
        help=("Phase 1 output directory produced by the 'run' command (e.g. output/abc123/)."),
    ),
    in_place: bool = typer.Option(
        False,
        "--in-place",
        help=(
            "Overwrite summary.md in-place instead of writing a separate "
            "summary_illustrated.md file."
        ),
    ),
    quality: str = typer.Option(
        "bestvideo[height<=360]",
        "--quality",
        help="yt-dlp format selector for the video download.",
    ),
    keep_video: bool = typer.Option(
        False,
        "--keep-video",
        help="Keep the downloaded video file after frame extraction.",
    ),
    skip_existing: bool = typer.Option(
        False,
        "--skip-existing",
        help="Skip sections whose frame JPEG already exists on disk.",
    ),
) -> None:
    """Phase 2: extract video frames and embed them into the markdown summary."""
    metadata_path = output_dir / "metadata.json"
    summary_path = output_dir / "summary.md"

    if not metadata_path.exists():
        console.print(
            f"[red]metadata.json not found in {output_dir}. "
            "Run the 'run' command first to produce Phase 1 output.[/red]"
        )
        raise typer.Exit(code=1)

    if not summary_path.exists():
        console.print(
            f"[red]summary.md not found in {output_dir}. "
            "Run the 'run' command first to produce Phase 1 output.[/red]"
        )
        raise typer.Exit(code=1)

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        console.print(f"[red]Failed to parse metadata.json: {exc}[/red]")
        raise typer.Exit(code=1) from None

    url: str | None = metadata.get("url")
    if not url:
        console.print("[red]metadata.json is missing the 'url' field.[/red]")
        raise typer.Exit(code=1)

    try:
        framer.check_ffmpeg()
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=2) from None

    markdown = summary_path.read_text(encoding="utf-8")
    try:
        sections = illustrator.parse_sections(markdown)
    except ValueError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from None

    console.print(
        f"[cyan]Found {len(sections)} section(s) to illustrate.[/cyan] "
        "Downloading video for frame extraction…"
    )

    with Progress(
        SpinnerColumn(spinner_name="line"), TextColumn("{task.description}"), console=console
    ) as progress:
        task_id = progress.add_task("Downloading video…", total=None)

        def on_frame(result: FrameResult) -> None:
            progress.update(
                task_id,
                description=(
                    f"Extracted frame {result.section_index + 1} / {len(sections)}  "
                    f"(t={result.timestamp:.1f}s)"
                ),
            )

        try:
            frame_results = framer.extract_frames(
                url,
                sections,
                output_dir,
                quality=quality,
                keep_video=keep_video,
                skip_existing=skip_existing,
                on_frame=on_frame,
            )
        except RuntimeError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(code=1) from None

    if not frame_results:
        console.print("[red]No frames were extracted — all sections failed.[/red]")
        raise typer.Exit(code=1)

    frame_map: dict[int, Path] = {r.section_index: r.path for r in frame_results}
    illustrated = illustrator.embed_frames(markdown, frame_map)

    if in_place:
        summary_path.write_text(illustrated, encoding="utf-8")
        console.print(f"[green]Done.[/green] Updated [bold]{summary_path}[/bold] in-place.")
    else:
        out_path = output_dir / "summary_illustrated.md"
        out_path.write_text(illustrated, encoding="utf-8")
        console.print(f"[green]Done.[/green] Wrote [bold]{out_path}[/bold]")


def _summarise(
    info: downloader.VideoInfo,
    chunks: list[transcript.Chunk],
    provider: LLMProvider,
    summary_path: Path,
    *,
    segment_chars: int = 12_000,
) -> str:
    """Run the LLM restructuring step with incremental file writing and a progress bar.

    Truncates ``summary_path`` before the first segment so callers always get a
    clean file regardless of prior runs. Each segment's output is appended
    immediately after it completes, so a partial file is left on disk if the
    run is interrupted mid-way.

    Returns the combined markdown string (same value that was written to disk).
    """
    # Truncate / create the file before any LLM call so that a later failure
    # leaves the file in a known state rather than containing stale content.
    summary_path.write_text("", encoding="utf-8")

    with Progress(
        SpinnerColumn(spinner_name="line"), TextColumn("{task.description}"), console=console
    ) as progress:
        task_id = progress.add_task("Preparing...", total=None)

        def on_segment(
            index: int,
            total: int,
            text: str,
            seg: list[transcript.Chunk],
        ) -> None:
            start = transcript.format_timestamp(seg[0].start)
            end = transcript.format_timestamp(seg[-1].end)
            progress.update(
                task_id,
                description=(f"Segment {index + 1} / {total}  [{start}-{end}]"),
            )
            with summary_path.open("a", encoding="utf-8") as fh:
                if index > 0:
                    fh.write("\n\n")
                fh.write(text)

        try:
            return writer.restructure(
                title=info.title,
                channel=info.channel,
                chunks=chunks,
                provider=provider,
                segment_chars=segment_chars,
                on_segment=on_segment,
            )
        except ValueError as exc:
            console.print(f"[red]LLM output rejected: {exc}[/red]")
            raise typer.Exit(code=1) from None
        except Exception as exc:
            # Surface quota/auth errors as clean messages instead of raw tracebacks.
            exc_str = str(exc)
            if "429" in exc_str or "RESOURCE_EXHAUSTED" in exc_str:
                if "PerDay" in exc_str or "per_day" in exc_str.lower():
                    console.print(
                        "[red]Gemini daily quota exhausted.[/red] "
                        f"The free tier for [bold]{provider.model}[/bold] has no remaining "
                        "daily allowance. Options:\n"
                        "  • Enable billing in Google AI Studio and retry\n"
                        "  • Switch to a model with free-tier access:  "
                        "[bold]--model gemini-2.0-flash[/bold]"
                    )
                else:
                    console.print(
                        "[red]Gemini rate limit hit (429).[/red] "
                        "The request was throttled. Wait a minute and retry."
                    )
                raise typer.Exit(code=1) from None
            raise
