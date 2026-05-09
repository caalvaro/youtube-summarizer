Installation
============

Prerequisites
-------------

* Python 3.13 or later.
* ``ffmpeg`` — required only for the ``illustrate`` command (frame extraction).
  Not needed for Phase 1 summarisation.

  .. code-block:: bash

     # macOS
     brew install ffmpeg

     # Debian / Ubuntu
     sudo apt install ffmpeg

  Binaries for all platforms: `ffmpeg.org/download.html <https://ffmpeg.org/download.html>`_.

Install from PyPI
-----------------

.. code-block:: bash

   pip install youtube-summarizer

Or, if you use `uv <https://docs.astral.sh/uv/>`_ (recommended):

.. code-block:: bash

   uv tool install youtube-summarizer

Configure API keys
------------------

youtube-summarizer supports two LLM providers. Configure the one you want to use.

**Claude (default)**

Set ``ANTHROPIC_API_KEY``. Get a key at `console.anthropic.com <https://console.anthropic.com/>`_.

.. code-block:: bash

   echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env

**Gemini**

Set ``GOOGLE_API_KEY`` and point the provider at Gemini. Get a free key at
`aistudio.google.com/apikey <https://aistudio.google.com/apikey>`_.

.. code-block:: bash

   echo "GOOGLE_API_KEY=AIza..." >> .env
   echo "YT_SUMMARIZER_PROVIDER=gemini" >> .env

The easiest way to manage these is a ``.env`` file in the directory where you run the
command. Copy the bundled example to get started:

.. code-block:: bash

   cp .env.example .env
   # then edit .env with your actual keys

Alternatively, export the variables in your shell profile so they are always available:

.. code-block:: bash

   export ANTHROPIC_API_KEY="sk-ant-..."

Development install
-------------------

To contribute or run the test suite:

.. code-block:: bash

   git clone https://github.com/caalvaro/youtube-summarizer.git
   cd youtube-summarizer
   uv sync --group dev
   uv run pre-commit install

See :doc:`/contributing` for the full contributor workflow.
