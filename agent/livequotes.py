"""Live price overlay for the Movers page: latest 1-minute prices for a handful of symbols, merged onto the
cached movers frame so the table can tick in place without re-running the heavy 1-year history download.

``apply_live`` and ``ticks`` are pure functions so they can be tested without the network.
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf


def fetch_prices(symbols: list[str]) -> dict[str, float]:
    """Latest 1-minute close per symbol from one batched Yahoo call; symbols with no bar are omitted."""
    syms = list(dict.fromkeys(s for s in symbols if s))
    if not syms:
        return {}
    try:
        raw = yf.download(syms, period="1d", interval="1m", auto_adjust=False, progress=False,
                          threads=4, group_by="ticker")
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, float] = {}
    for s in syms:
        try:
            close = raw[s]["Close"].dropna()
        except Exception:  # noqa: BLE001
            try:
                close = raw["Close"].dropna() if len(syms) == 1 else pd.Series(dtype=float)
            except Exception:  # noqa: BLE001
                close = pd.Series(dtype=float)
        if len(close):
            out[s] = float(close.iloc[-1])
    return out


def apply_live(df: pd.DataFrame, live: dict[str, float]) -> pd.DataFrame:
    """Return a copy of a movers frame with Price and Change % recomputed from live prices.

    The previous close is recovered from the frame itself (Price / (1 + Change %)), so the day change stays
    measured against the same base. Row order is kept, so ranks do not jump while the table is ticking.
    """
    out = df.copy()
    for i, r in out.iterrows():
        p = live.get(r["Symbol"])
        chg = r["Change %"]
        if p is None or p <= 0 or pd.isna(chg) or chg <= -100:
            continue
        prev = float(r["Price"]) / (1 + float(chg) / 100)
        out.at[i, "Price"] = p
        out.at[i, "Change %"] = (p / prev - 1) * 100
    return out


def rank_moves(prev: list[str], cur: list[str]) -> dict[str, int | str]:
    """Places gained since the previous poll for each symbol in ``cur`` (positive = moved up the list).

    A symbol absent from ``prev`` is reported as ``"new"``. Returns {} when there is no previous poll, so the
    first render shows no badges. Unmoved symbols are omitted.
    """
    if not prev:
        return {}
    old = {s: i for i, s in enumerate(prev)}
    out: dict[str, int | str] = {}
    for i, s in enumerate(cur):
        if s not in old:
            out[s] = "new"
        elif old[s] != i:
            out[s] = old[s] - i
    return out


def ticks(prev: dict[str, float], cur: dict[str, float]) -> dict[str, float]:
    """Signed price change since the previous poll, per symbol (0 for unchanged or first sight)."""
    return {s: (p - prev[s]) if s in prev else 0.0 for s, p in cur.items()}
