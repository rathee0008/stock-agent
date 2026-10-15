"""Tiny failure log so one broken data source never blanks a page silently.

``record`` keeps the most recent failures in memory (shown in the sidebar
"System status" panel) and mirrors them to the standard logger.
"""

from __future__ import annotations

import collections
import datetime as _dt
import logging
import threading

_log = logging.getLogger("stock-agent")
_lock = threading.Lock()
_events: collections.deque[dict] = collections.deque(maxlen=60)
_ok: dict[str, str] = {}


def record(source: str, exc: BaseException | str, level: str = "warning") -> None:
    msg = f"{type(exc).__name__}: {exc}" if isinstance(exc, BaseException) else str(exc)
    msg = msg[:220]
    with _lock:
        _events.appendleft({"t": _dt.datetime.now(_dt.UTC), "source": source, "msg": msg, "level": level})
    getattr(_log, level, _log.warning)("%s: %s", source, msg)


def mark_ok(source: str, detail: str = "") -> None:
    with _lock:
        _ok[source] = f"{_dt.datetime.now(_dt.UTC):%H:%M:%S}Z {detail}".strip()


def recent(n: int = 15) -> list[dict]:
    with _lock:
        return list(_events)[:n]


def last_ok() -> dict[str, str]:
    with _lock:
        return dict(_ok)


def safe(source: str, default=None):
    """Decorator: log and swallow exceptions, returning ``default`` instead."""

    def deco(fn):
        def wrapper(*a, **k):
            try:
                return fn(*a, **k)
            except Exception as exc:  # noqa: BLE001
                record(source, exc)
                return default

        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper

    return deco
