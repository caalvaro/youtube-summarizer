"""Provider-agnostic primitives: the :class:`LLMProvider` Protocol and a
retry helper shared by all concrete providers.

Provider implementations live in sibling modules (``claude.py``, ``gemini.py``).
The orchestrator (:mod:`youtube_summarizer.writer`) depends only on this
module's public Protocol — concrete provider classes are interchangeable
behind it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol, TypeVar, runtime_checkable

T = TypeVar("T")


@runtime_checkable
class LLMProvider(Protocol):
    """The contract every LLM provider satisfies.

    A provider takes a ``(system, user)`` prompt pair and returns the raw text
    response. Provider-specific concerns — API-key resolution, SDK construction,
    streaming, max-token budgets, retry policy — are encapsulated inside the
    implementation. Callers treat providers as opaque text-in / text-out
    endpoints.

    Implementations are *not* required to inherit from this Protocol; satisfying
    the structural shape is enough. The ``runtime_checkable`` decorator lets
    callers (and tests) assert ``isinstance(x, LLMProvider)`` when useful.
    """

    name: str
    """Stable provider identifier, used in error messages and logging."""

    model: str
    """Resolved model identifier (provider's default if the user didn't override)."""

    def generate(self, *, system: str, user: str) -> str:
        """Send the prompt pair to the LLM and return the raw text response.

        Implementations should retry on transient errors and raise on permanent
        ones (auth failure, bad request, content policy). The text returned
        here is forwarded *verbatim* to the orchestrator's post-condition
        validation — providers should not strip, reformat, or post-process it.
        """


def retry_call[T](
    call: Callable[[], T],
    *,
    is_retriable: Callable[[BaseException], bool],
    retries: int = 3,
    base_delay: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run ``call`` with exponential-backoff retries on transient errors.

    Each provider supplies its own ``is_retriable`` predicate, since the typed
    exception hierarchies differ across SDKs. ``sleep`` is injectable so tests
    can assert backoff behaviour without sleeping real seconds.

    The schedule is ``base_delay * 2 ** attempt`` for attempt 0, 1, … so with
    the defaults (``retries=3, base_delay=1.0``) the caller sees waits of
    1s and 2s before the third and final attempt fails.

    Args:
        call: Zero-arg callable that performs the request and returns the
            success value, or raises on failure.
        is_retriable: Predicate; returns ``True`` if the exception is worth
            retrying (rate-limit jitter, 5xx, network blip).
        retries: Total attempts (not *additional* retries). Default 3.
        base_delay: First-attempt backoff, in seconds.
        sleep: Sleep function. Override for tests.

    Returns:
        The return value of ``call`` once it succeeds.

    Raises:
        BaseException: re-raises the final exception when ``call`` keeps
            failing OR raises a non-retriable exception.
    """
    for attempt in range(retries):
        try:
            return call()
        except Exception as exc:
            if not is_retriable(exc) or attempt == retries - 1:
                raise
            sleep(base_delay * (2**attempt))
    # Defensive: the loop either returns or re-raises. This line is unreachable
    # but satisfies type-checkers that can't prove the loop exits.
    raise RuntimeError("unreachable: retry loop exhausted without return")
