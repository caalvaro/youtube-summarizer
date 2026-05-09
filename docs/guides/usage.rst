Usage
=====

Basic usage
-----------

Pass a YouTube URL as the only required argument:

.. code-block:: bash

   youtube-summarizer "https://www.youtube.com/watch?v=VIDEO_ID"

Output files are written to ``output/<video_id>/``:

.. list-table::
   :widths: 30 70
   :header-rows: 1

   * - File
     - Contents
   * - ``metadata.json``
     - Title, channel, duration, URL, caption source (``manual`` or ``auto``)
   * - ``<id>.<lang>.vtt``
     - Raw captions downloaded by yt-dlp
   * - ``transcript.txt``
     - Cleaned, timestamped transcript (post-deduplication)
   * - ``summary.md``
     - Structured ebook-style Markdown — the primary deliverable

Options
-------

``--lang``
~~~~~~~~~~

Select the caption language (ISO 639-1 code). Defaults to ``en``.

.. code-block:: bash

   youtube-summarizer --lang pt "https://www.youtube.com/watch?v=VIDEO_ID"

Manual captions are preferred when available; youtube-summarizer falls back to
auto-generated captions automatically.

``YT_SUMMARIZER_MODEL`` environment variable
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Override the Claude model used for restructuring. The default is ``claude-opus-4-7``.

.. code-block:: bash

   YT_SUMMARIZER_MODEL=claude-sonnet-4-6 youtube-summarizer "https://..."

Reducing the model trades output quality for lower API cost.

Exit codes
----------

.. list-table::
   :widths: 10 90
   :header-rows: 1

   * - Code
     - Meaning
   * - ``0``
     - Success
   * - ``1``
     - No captions found, or captions parsed to empty
   * - ``2``
     - ``ANTHROPIC_API_KEY`` is not set

Programmatic use
----------------

The package modules can be imported directly:

.. code-block:: python

   from pathlib import Path
   from youtube_summarizer import downloader, transcript, writer

   info = downloader.fetch("https://www.youtube.com/watch?v=VIDEO_ID", Path("output"))
   captions = transcript.parse_vtt(info.captions_path)
   chunks = transcript.to_chunks(captions)
   markdown = writer.restructure(info.title, info.channel, chunks)
   print(markdown)

The ``<!-- timestamp: start-end -->`` comments embedded in each ``## H2`` section of the
Markdown output are used by Phase 2 of the pipeline to align video frames to sections.
