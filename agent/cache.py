"""Market-hours-aware caching.

``st.cache_data(ttl=...)`` takes a fixed TTL, but the right freshness depends on
whether the market is open. ``bucket(market)`` returns an integer that changes
every ``ttl`` seconds — short while the session is open, long once it is closed —
so passing it as an argument to a cached function gives an adaptive TTL:

    @st.cache_data(ttl=86400, show_spinner=False)
    def _movers(market, b): ...
    _movers("IN", cache.bucket("IN"))

``disk_cache`` additionally persists a pickled result under ``.cache/`` so a cold
start (Streamlit Cloud wakes from sleep) can serve the last good value while Yahoo
is rate-limiting.
"""

from __future__ import annotations

import hashlib
import os
import pickle
import time
from pathlib import Path
from typing import Any, Callable

from . import log
from .data import _in_market_state, _us_market_state

OPEN_TTL = 120          # seconds while the session is open
PRE_POST_TTL = 600
CLOSED_TTL = 3 * 3600   # data cannot change when the market is shut


def state(market: str) -> str:
    return _us_market_state() if market == "US" else _in_market_state()


def ttl_for(market: str) -> int:
    s = state(market)
    if s == "REGULAR":
        return OPEN_TTL
    if s in ("PRE", "POST"):
        return PRE_POST_TTL
    return CLOSED_TTL


def bucket(market: str = "IN", scale: float = 1.0, now: float | None = None) -> int:
    """Integer that changes every ``ttl_for(market) * scale`` seconds."""
    t = time.time() if now is None else now
    return int(t // max(int(ttl_for(market) * scale), 1))


def both_bucket(scale: float = 1.0) -> int:
    """Bucket for pages that show both markets: follows whichever is open."""
    return bucket("IN", scale) * 1_000_003 + bucket("US", scale)


# ------------------------------------------------------------------ disk cache
_DIR = Path(os.environ.get("STOCK_AGENT_CACHE", Path(__file__).resolve().parents[1] / ".cache"))


def _path(key: str) -> Path:
    return _DIR / (hashlib.sha1(key.encode()).hexdigest()[:24] + ".pkl")


def disk_get(key: str, max_age: float | None = None) -> Any | None:
    p = _path(key)
    try:
        if not p.exists():
            return None
        if max_age is not None and time.time() - p.stat().st_mtime > max_age:
            return None
        with p.open("rb") as f:
            return pickle.load(f)
    except Exception as exc:  # noqa: BLE001
        log.record("disk_cache", exc, "debug")
        return None


def disk_put(key: str, value: Any) -> None:
    try:
        _DIR.mkdir(parents=True, exist_ok=True)
        tmp = _path(key).with_suffix(".tmp")
        with tmp.open("wb") as f:
            pickle.dump(value, f)
        tmp.replace(_path(key))
    except Exception as exc:  # noqa: BLE001
        log.record("disk_cache", exc, "debug")


def stale_ok(key: str, fn: Callable[[], Any], fresh_for: float = 0.0) -> tuple[Any, bool]:
    """Run ``fn``; on success store it, on failure return the last stored value.

    Returns ``(value, was_stale)``. Raises only if there is no stored fallback.
    """
    if fresh_for:
        hit = disk_get(key, max_age=fresh_for)
        if hit is not None:
            return hit, False
    try:
        val = fn()
        if val is not None and not (hasattr(val, "empty") and val.empty):
            disk_put(key, val)
        return val, False
    except Exception as exc:  # noqa: BLE001
        log.record(f"fetch:{key[:40]}", exc)
        old = disk_get(key)
        if old is None:
            raise
        return old, True
