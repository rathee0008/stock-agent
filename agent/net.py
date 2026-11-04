"""Guard rails for Yahoo downloads so a small host (Streamlit Cloud) never runs out of threads.

``yf.download(threads=True)`` starts a burst of threads on every call, and the live pages re-run it
every few seconds for every open browser session. On a thread-limited container that ends in
``RuntimeError: can't start new thread`` and a blank app. :func:`install` wraps ``yf.download`` once,
process-wide, so that every call (including future ones) is

* capped at ``MAX_THREADS`` worker threads, whatever ``threads=`` asked for, and
* limited to ``MAX_CONCURRENT`` simultaneous downloads across all sessions (extra calls wait their turn).
"""

from __future__ import annotations

import threading

MAX_THREADS = 4
MAX_CONCURRENT = 2

_gate = threading.BoundedSemaphore(MAX_CONCURRENT)
_installed = False


def cap_threads(value):
    """Map a ``threads=`` argument to a safe value: False/None/0/1 stay sequential, anything else is capped."""
    if value is False or value is None:
        return False
    if value is True:
        return MAX_THREADS
    try:
        n = int(value)
    except (TypeError, ValueError):
        return MAX_THREADS
    return False if n <= 1 else min(n, MAX_THREADS)


def install() -> None:
    """Wrap ``yfinance.download`` with the thread cap and concurrency gate (idempotent)."""
    global _installed
    if _installed:
        return
    try:
        import yfinance as yf
    except Exception:  # noqa: BLE001  (yfinance missing: nothing to guard)
        return
    original = yf.download

    def guarded(*args, **kwargs):
        kwargs["threads"] = cap_threads(kwargs.get("threads", True))
        with _gate:
            return original(*args, **kwargs)

    guarded.__wrapped__ = original  # type: ignore[attr-defined]
    yf.download = guarded
    _installed = True
