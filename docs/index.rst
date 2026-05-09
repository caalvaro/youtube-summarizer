youtube-summarizer
==================

Turn a YouTube video into an illustrated-ebook Markdown summary powered by Claude.

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

**youtube-summarizer** downloads a video's captions from YouTube and passes them to the
Anthropic Claude API, which restructures them into clean, readable Markdown with headings,
bold key terms, and timestamp annotations ready for illustrated-ebook assembly.

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
   writer.restructure()    ← Claude: rewrite into ebook-style Markdown
       │
       ▼
   output/<video_id>/summary.md

Indices and tables
------------------

* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`
