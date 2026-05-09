Usage
=====

Phase 1 — summarise
--------------------

Pass a YouTube URL to the ``run`` command:

.. code-block:: bash

   youtube-summarizer run "https://www.youtube.com/watch?v=VIDEO_ID"

Output is written to ``output/<video_id>/``:

.. list-table::
   :widths: 30 70
   :header-rows: 1

   * - File
     - Contents
   * - ``metadata.json``
     - Title, channel, duration, URL, caption source, provider, and model used
   * - ``<id>.<lang>.vtt``
     - Raw captions downloaded by yt-dlp
   * - ``transcript.txt``
     - Cleaned, timestamped flat transcript (post-deduplication)
   * - ``summary.md``
     - Structured ebook-style Markdown — the primary deliverable

Phase 1 options
~~~~~~~~~~~~~~~

``--lang``
^^^^^^^^^^

Select the caption language (ISO 639-1 code). Defaults to ``en``.

.. code-block:: bash

   youtube-summarizer run --lang pt "https://www.youtube.com/watch?v=VIDEO_ID"

Manual captions are preferred when available; youtube-summarizer falls back to
auto-generated captions automatically.

``--provider``
^^^^^^^^^^^^^^

Select the LLM provider. Supported values: ``claude`` (default) and ``gemini``.

.. code-block:: bash

   youtube-summarizer run --provider gemini "https://..."

Can also be set via the ``YT_SUMMARIZER_PROVIDER`` environment variable:

.. code-block:: bash

   YT_SUMMARIZER_PROVIDER=gemini youtube-summarizer run "https://..."

``--model``
^^^^^^^^^^^

Override the model used by the selected provider. Each provider has a built-in
default (``claude-opus-4-7`` for Claude, ``gemini-3-flash-preview`` for Gemini).

.. code-block:: bash

   youtube-summarizer run --model claude-sonnet-4-6 "https://..."

Can also be set via the ``YT_SUMMARIZER_MODEL`` environment variable:

.. code-block:: bash

   YT_SUMMARIZER_MODEL=claude-sonnet-4-6 youtube-summarizer run "https://..."

Reducing the model trades output quality for lower API cost.

``--segment-chars``
^^^^^^^^^^^^^^^^^^^

Target transcript character count per LLM call. Videos whose transcript exceeds
this threshold are split into multiple segments, each processed by a separate LLM
call whose output is appended in order. Default: ``12000``.

.. code-block:: bash

   # Use smaller segments for stricter token budgets
   youtube-summarizer run --segment-chars 6000 "https://..."

Phase 2 — illustrate
---------------------

Once Phase 1 has produced ``output/<video_id>/summary.md``, run the ``illustrate``
command to extract representative video frames and embed them:

.. code-block:: bash

   youtube-summarizer illustrate output/<video_id>/

Requires ``ffmpeg`` on ``PATH`` (see :doc:`installation`). Output files:

.. list-table::
   :widths: 35 65
   :header-rows: 1

   * - File
     - Contents
   * - ``summary_illustrated.md``
     - ``summary.md`` with ``![…](frames/section_NNN.jpg)`` lines injected
   * - ``frames/section_NNN.jpg``
     - One representative JPEG per ``## H2`` section

Phase 2 options
~~~~~~~~~~~~~~~

``--in-place``
^^^^^^^^^^^^^^

Overwrite ``summary.md`` instead of writing a separate ``summary_illustrated.md``:

.. code-block:: bash

   youtube-summarizer illustrate output/<video_id>/ --in-place

``--keep-video``
^^^^^^^^^^^^^^^^

Keep the downloaded video file on disk after frame extraction (deleted by default):

.. code-block:: bash

   youtube-summarizer illustrate output/<video_id>/ --keep-video

``--skip-existing``
^^^^^^^^^^^^^^^^^^^

Skip sections whose frame JPEG already exists. Useful for resuming a partial run:

.. code-block:: bash

   youtube-summarizer illustrate output/<video_id>/ --skip-existing

``--quality``
^^^^^^^^^^^^^

yt-dlp format selector for the video download. Default: ``bestvideo[height<=360]``.
Increase for sharper frames at the cost of a larger download:

.. code-block:: bash

   youtube-summarizer illustrate output/<video_id>/ --quality "bestvideo[height<=720]"

Exit codes
----------

.. list-table::
   :widths: 10 20 70
   :header-rows: 1

   * - Code
     - Command
     - Meaning
   * - ``0``
     - both
     - Success
   * - ``1``
     - ``run``
     - No captions available, captions parsed to empty, or LLM error
   * - ``1``
     - ``illustrate``
     - Missing/invalid input files, parse failure, download error, or no frames extracted
   * - ``2``
     - ``run``
     - Provider API key not set or provider misconfigured
   * - ``2``
     - ``illustrate``
     - ``ffmpeg`` not found on ``PATH``

Programmatic use
----------------

The package modules can be imported directly for programmatic use:

.. code-block:: python

   from pathlib import Path
   from youtube_summarizer import downloader, transcript, writer
   from youtube_summarizer.providers import get_provider
   from youtube_summarizer.config import get_settings

   settings = get_settings()              # reads env vars
   provider = get_provider(settings)      # ClaudeProvider or GeminiProvider

   info = downloader.fetch("https://www.youtube.com/watch?v=VIDEO_ID", Path("output"))
   captions = transcript.parse_vtt(info.captions_path)
   chunks = transcript.to_chunks(captions)
   markdown = writer.restructure(
       title=info.title,
       channel=info.channel,
       chunks=chunks,
       provider=provider,
   )
   print(markdown)

The ``<!-- timestamp: start-end -->`` comments embedded in each ``## H2`` section of the
Markdown output are used by Phase 2 to align extracted video frames to the correct section.
