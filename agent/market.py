"""Index / macro quotes for the market strip (one batched Yahoo call)."""

from __future__ import annotations

import pandas as pd
import yfinance as yf

INDICES = [
    ("NIFTY 50", "^NSEI"), ("SENSEX", "^BSESN"), ("BANK NIFTY", "^NSEBANK"),
    ("S&P 500", "^GSPC"), ("NASDAQ", "^IXIC"), ("DOW", "^DJI"),
    ("GOLD", "GC=F"), ("USD/INR", "INR=X"),
]


def index_quotes() -> list[dict]:
    """Last close and day change for each index; missing symbols are skipped."""
    syms = [s for _, s in INDICES]
    try:
        raw = yf.download(syms, period="5d", interval="1d", auto_adjust=False,
                          progress=False, threads=True, group_by="ticker")
    except Exception:  # noqa: BLE001
        return []
    out: list[dict] = []
    for name, sym in INDICES:
        try:
            close = raw[sym]["Close"].dropna()
            if len(close) < 2:
                continue
            last, prev = float(close.iloc[-1]), float(close.iloc[-2])
            out.append({"name": name, "price": last, "chg_pct": (last / prev - 1) * 100})
        except Exception:  # noqa: BLE001
            continue
    return out
