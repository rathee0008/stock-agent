"""Secondary price sources used only when Yahoo fails or is rate-limited.

Order tried by :func:`daily_history`:
  1. Alpha Vantage  (needs ``ALPHAVANTAGE_API_KEY``; India via ``.BSE`` symbols, US plain)
  2. Stooq          (no key; US tickers as ``aapl.us``)
  3. Last good copy from the on-disk cache (flagged as stale by the caller)

Everything returns a frame shaped like yfinance's (Open/High/Low/Close/Volume on a
DatetimeIndex) so callers need no special cases.
"""

from __future__ import annotations

import io

import pandas as pd
import requests

from . import config, log

_COLS = ["Open", "High", "Low", "Close", "Volume"]


def _av_symbol(yahoo: str) -> str | None:
    s = yahoo.upper()
    if s.startswith("^") or "=" in s:
        return None
    if s.endswith(".NS"):
        return s[:-3] + ".BSE"      # Alpha Vantage lists Indian equities on BSE
    if s.endswith(".BO"):
        return s[:-3] + ".BSE"
    return s


def alpha_vantage(yahoo: str, timeout: int = 15) -> pd.DataFrame:
    key = config.get("ALPHAVANTAGE_API_KEY")
    sym = _av_symbol(yahoo)
    if not key or not sym:
        return pd.DataFrame()
    r = requests.get(
        "https://www.alphavantage.co/query",
        params={"function": "TIME_SERIES_DAILY", "symbol": sym, "outputsize": "full", "apikey": key},
        timeout=timeout,
    )
    r.raise_for_status()
    ts = (r.json() or {}).get("Time Series (Daily)")
    if not ts:
        # outputsize=full is premium on some plans; retry compact (last ~100 days)
        r = requests.get(
            "https://www.alphavantage.co/query",
            params={"function": "TIME_SERIES_DAILY", "symbol": sym, "outputsize": "compact", "apikey": key},
            timeout=timeout,
        )
        ts = (r.json() or {}).get("Time Series (Daily)")
    if not ts:
        return pd.DataFrame()
    df = pd.DataFrame.from_dict(ts, orient="index").astype(float)
    df.columns = [c.split(". ", 1)[-1].title() for c in df.columns]
    df.index = pd.to_datetime(df.index)
    return df.sort_index()[_COLS]


def stooq(yahoo: str, timeout: int = 15) -> pd.DataFrame:
    s = yahoo.lower()
    if s.endswith((".ns", ".bo")) or s.startswith("^") or "=" in s:
        return pd.DataFrame()       # Stooq has no NSE/BSE coverage
    sym = s.replace("-", ".") + ".us"
    r = requests.get("https://stooq.com/q/d/l/", params={"s": sym, "i": "d"}, timeout=timeout,
                     headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    if "Date" not in r.text[:40]:
        return pd.DataFrame()
    df = pd.read_csv(io.StringIO(r.text), parse_dates=["Date"], index_col="Date")
    return df.sort_index()[_COLS] if set(_COLS) <= set(df.columns) else pd.DataFrame()


def daily_history(yahoo: str, period_days: int = 730) -> tuple[pd.DataFrame, str]:
    """Return ``(frame, source_name)``; empty frame and ``""`` if every source failed."""
    for name, fn in (("ALPHAVANTAGE", alpha_vantage), ("STOOQ", stooq)):
        try:
            df = fn(yahoo)
        except Exception as exc:  # noqa: BLE001
            log.record(f"fallback:{name}", exc)
            continue
        if df is not None and not df.empty:
            cutoff = df.index.max() - pd.Timedelta(days=period_days)
            log.mark_ok(f"fallback:{name}", yahoo)
            return df[df.index >= cutoff], name
    return pd.DataFrame(), ""
