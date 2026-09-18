"""Real-time NSE quote/chart provider.

Yahoo Finance (via ``yfinance``) publishes Indian equities on a ~15 minute
delay, so the live tab was never actually live. NSE's own website is fed by
the exchange in real time and the endpoints its front-end calls are plain
JSON:

``/api/NextApi/apiClient/GetQuoteApi?functionName=getSymbolData``
    LTP, open/high/low, previous close, session VWAP (``averagePrice``),
    total traded volume, five-deep order book.

``/api/NextApi/apiClient/GetQuoteApi?functionName=getSymbolChartData``
    ``days=1D`` returns the current session's tick series as
    ``[epoch_ms, price, status, change, pct]`` — the exact series NSE draws
    on its own quote page. Resampling it gives real-time candles.

Both sit behind Akamai and need a browser-shaped session (cookies from a
real page load + ``Referer``/``X-Requested-With``), which ``_session()``
handles. Everything here is best-effort: any failure raises ``NSEUnavailable``
and :mod:`agent.data` silently falls back to the delayed Yahoo feed.

Caveats worth knowing:
  * Timestamps are IST wall-clock encoded as epoch ms, so they are localised
    rather than converted.
  * The tick series carries no per-bar volume — only the session total. The
    caller decides what to do about the volume panel.
  * NSE rate-limits and geo-filters; from a non-Indian host (Streamlit
    Community Cloud runs in the US) it may refuse outright.
"""

from __future__ import annotations

import datetime as _dt
import threading
import time
from typing import Any

import pandas as pd
import requests

BASE = "https://www.nseindia.com"
_API = BASE + "/api/NextApi/apiClient/GetQuoteApi"
IST = _dt.timezone(_dt.timedelta(hours=5, minutes=30))

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

_SESSION_TTL = 240.0          # re-bootstrap cookies every few minutes
_lock = threading.Lock()
_sess: requests.Session | None = None
_sess_born: float = 0.0


class NSEUnavailable(RuntimeError):
    """NSE refused, timed out, or returned something unusable."""


def _new_session(symbol: str) -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    # Two hops: the landing page mints the base cookies, the quote page adds
    # the ones the quote API checks.
    s.get(BASE + "/", timeout=8)
    s.get(f"{BASE}/get-quotes/equity?symbol={symbol}", timeout=8)
    return s


def _session(symbol: str, force: bool = False) -> requests.Session:
    global _sess, _sess_born
    with _lock:
        fresh = _sess is not None and (time.time() - _sess_born) < _SESSION_TTL
        if force or not fresh:
            _sess = _new_session(symbol)
            _sess_born = time.time()
        return _sess


def _get_json(params: dict[str, Any], symbol: str) -> Any:
    last: Exception | None = None
    for attempt in range(2):
        try:
            s = _session(symbol, force=attempt > 0)
            r = s.get(
                _API,
                params=params,
                timeout=8,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": f"{BASE}/get-quotes/equity?symbol={symbol}",
                },
            )
            if r.status_code in (401, 403, 503):
                raise NSEUnavailable(f"NSE returned HTTP {r.status_code}")
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.6)
    raise NSEUnavailable(str(last))


# --------------------------------------------------------------------------
# Symbol handling
# --------------------------------------------------------------------------
def nse_base_symbol(yahoo_symbol: str) -> str | None:
    """``RELIANCE.NS`` -> ``RELIANCE``. Returns ``None`` for anything this
    provider cannot serve (BSE-only symbols, indices, US tickers)."""
    s = (yahoo_symbol or "").strip().upper()
    if not s or s.startswith("^") or s.endswith(".BO"):
        return None
    if s.endswith(".NS"):
        s = s[:-3]
    elif "." in s or "-" in s:
        return None
    return s or None


def _identifier(base: str, series: str = "EQ") -> str:
    return f"{base}{series}N"


# --------------------------------------------------------------------------
# Endpoints
# --------------------------------------------------------------------------
def quote(base: str, series: str = "EQ") -> dict[str, Any]:
    """Live quote block for one NSE equity."""
    j = _get_json(
        {"functionName": "getSymbolData", "marketType": "N",
         "series": series, "symbol": base},
        base,
    )
    rows = (j or {}).get("equityResponse") or []
    if not rows:
        raise NSEUnavailable(f"no equityResponse for {base}")
    return rows[0]


def intraday_ticks(base: str, series: str = "EQ") -> pd.DataFrame:
    """Current session's tick series, indexed tz-aware in IST."""
    j = _get_json(
        {"functionName": "getSymbolChartData",
         "symbol": _identifier(base, series), "days": "1D"},
        base,
    )
    raw = (j or {}).get("grapthData") or []
    rows = [(p[0], float(p[1])) for p in raw
            if isinstance(p, (list, tuple)) and len(p) >= 2 and p[1] is not None]
    if not rows:
        raise NSEUnavailable(f"empty chart series for {base}")

    df = pd.DataFrame(rows, columns=["ts", "price"])
    # Epoch ms carrying IST wall-clock: read naive, then stamp as IST.
    idx = pd.to_datetime(df["ts"], unit="ms").dt.tz_localize(IST)
    return pd.DataFrame({"price": df["price"].to_numpy()}, index=idx).sort_index()


_RULE = {"1m": "1min", "2m": "2min", "5m": "5min",
         "15m": "15min", "30m": "30min", "60m": "60min"}


def candles(ticks: pd.DataFrame, interval: str = "5m") -> pd.DataFrame:
    """Resample the tick series into OHLC bars (no volume — NSE's chart feed
    does not carry it)."""
    rule = _RULE.get(interval, "5min")
    o = ticks["price"].resample(rule, label="left", closed="left").ohlc().dropna(how="all")
    o.columns = ["Open", "High", "Low", "Close"]
    o["Volume"] = 0.0
    return o


def _f(d: dict[str, Any], *keys: str) -> float | None:
    for k in keys:
        v = d.get(k)
        if isinstance(v, (int, float)) and not pd.isna(v) and v != 0:
            return float(v)
    return None


def snapshot(base: str, interval: str = "5m", series: str = "EQ") -> dict[str, Any]:
    """Everything the live tab needs, in one call: quote fields plus resampled
    real-time candles."""
    q = quote(base, series)
    meta = q.get("metaData") or {}
    trade = q.get("tradeInfo") or {}
    book = q.get("orderBook") or {}

    ticks = intraday_ticks(base, series)
    bars = candles(ticks, interval)

    last = (_f(book, "lastPrice") or _f(trade, "lastPrice")
            or (float(ticks["price"].iloc[-1]) if len(ticks) else None))
    return {
        "source": "NSE",
        "name": meta.get("companyName") or base,
        "price": last,
        "prev_close": _f(meta, "previousClose", "basePrice"),
        "day_open": _f(meta, "open"),
        "day_high": _f(meta, "dayHigh"),
        "day_low": _f(meta, "dayLow"),
        "day_volume": _f(trade, "totalTradedVolume", "quantitytraded"),
        "vwap": _f(meta, "averagePrice"),
        "status": str(meta.get("symbolStatus") or ""),
        "last_update": q.get("lastUpdateTime"),
        "bars": bars,
        "ticks": ticks,
        "has_bar_volume": False,
    }
