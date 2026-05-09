Installation
============

Prerequisites
-------------

* Python 3.12 or later.
* An `Anthropic API key <https://console.anthropic.com/>`_.
* ``ffmpeg`` is **not** required — youtube-summarizer uses captions only, not audio.

Install from PyPI
-----------------

.. code-block:: bash

   pip install youtube-summarizer

Or, if you use `uv <https://docs.astral.sh/uv/>`_ (recommended):

.. code-block:: bash

   uv tool install youtube-summarizer

Configure the API key
---------------------

The tool reads ``ANTHROPIC_API_KEY`` from the environment.  The easiest way is to
create a ``.env`` file in the directory where you run the command:

.. code-block:: bash

   echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

Alternatively, export it in your shell profile:

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
