youtube-summarizer
==================

Turn a YouTube video into an illustrated-ebook Markdown summary powered by Claude or Gemini.

.. image:: https://img.shields.io/pypi/v/youtube-summarizer.svg
   :target: https://pypi.org/project/youtube-summarizer/
   :alt: PyPI version

.. image:: https://img.shields.io/github/actions/workflow/status/caalvaro/youtube-summarizer/ci.yml?branch=main
   :target: https://github.com/caalvaro/youtube-summarizer/actions
   :alt: CI status

.. image:: https://img.shields.io/codecov/c/github/caalvaro/youtube-summarizer
   :target: https://codecov.io/gh/caalvaro/youtube-summarizer
   :alt: Coverage

----

**youtube-summarizer** downloads a video's captions from YouTube and uses an LLM (Claude
or Gemini) to restructure them into clean, readable Markdown with headings, bold key terms,
and timestamp annotations. A second pass extracts representative video frames and embeds
them alongside each section, producing a fully illustrated ebook-ready document.

.. toctree::
   :maxdepth: 2
   :caption: User guide

   guides/installation
   guides/usage

.. toctree::
   :maxdepth: 1
   :caption: API reference

   api

.. toctree::
   :maxdepth: 1
   :caption: Project

   changelog
   contributing

Pipeline overview
-----------------

**Phase 1 — summarise**

.. code-block:: text

   YouTube URL
       │
       ▼
   downloader.fetch()      ← yt-dlp: probe metadata, download .vtt
       │
       ▼
   transcript.parse_vtt()  ← strip timing tags, deduplicate rolling cues
       │
       ▼
   transcript.to_chunks()  ← group into ~90-second segments
       │
       ▼
   writer.restructure()    ← LLM: rewrite into ebook-style Markdown
       │
       ▼
   output/<video_id>/summary.md   (each ## H2 carries a hidden timestamp comment)

**Phase 2 — illustrate**

.. code-block:: text

   output/<video_id>/summary.md
       │
       ▼
   illustrator.parse_sections()  ← extract (heading, timestamp range) pairs
       │
       ▼
   framer.download_video()       ← yt-dlp: low-res video-only stream
       │
       ▼
   framer.extract_frame()        ← ffmpeg double-seek: one JPEG per section
       │
       ▼
   illustrator.embed_frames()    ← inject ![alt](frames/section_NNN.jpg) lines
       │
       ▼
   output/<video_id>/summary_illustrated.md

Indices and tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
