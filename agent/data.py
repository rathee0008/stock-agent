"""Data access layer — wraps yfinance for NSE/BSE and US tickers.

Yahoo Finance serves Indian equities as `<SYMBOL>.NS` (NSE) or `<SYMBOL>.BO`
(BSE). Intraday quotes are delayed ~15 min; daily history is complete. US
equities are plain tickers (`AAPL`, `MSFT`, ...) with no suffix.
"""

from __future__ import annotations

import datetime as _dt
import time
from dataclasses import dataclass, field
from typing import Any, Literal

import pandas as pd
import yfinance as yf

from . import nse_live as _nse

Market = Literal["IN", "US"]

# A few common aliases so users can type the obvious thing.
_ALIASES_IN = {
    "RELIANCE": "RELIANCE.NS",
    "TCS": "TCS.NS",
    "INFY": "INFY.NS",
    "HDFCBANK": "HDFCBANK.NS",
    "ICICIBANK": "ICICIBANK.NS",
    "SBIN": "SBIN.NS",
    "ITC": "ITC.NS",
    "LT": "LT.NS",
    "BHARTIARTL": "BHARTIARTL.NS",
    "NIFTY": "^NSEI",
    "SENSEX": "^BSESN",
    "BANKNIFTY": "^NSEBANK",
}

_ALIASES_US = {
    "SPX": "^GSPC",
    "SP500": "^GSPC",
    "SNP500": "^GSPC",
    "DOW": "^DJI",
    "DOWJONES": "^DJI",
    "NASDAQ": "^IXIC",
    "NASDAQ100": "^NDX",
    "VIX": "^VIX",
}


def normalize_ticker(raw: str, market: Market = "IN") -> str:
    """Turn user input into a Yahoo Finance symbol.

    India: ``reliance`` -> ``RELIANCE.NS``; ``TATamotors`` -> ``TATAMOTORS.NS``;
    an already-qualified ``INFY.NS`` or index ``^NSEI`` is passed through.

    US: ``aapl`` -> ``AAPL``; ``spx``/``dow``/``nasdaq`` map to the Yahoo
    index tickers; an already-qualified symbol (incl. ``BRK-B``) passes
    through unchanged.
    """
    s = raw.strip().upper()
    if not s:
        raise ValueError("empty ticker")

    if market == "US":
        if s.startswith("^"):
            return s
        return _ALIASES_US.get(s, s)

    if s.startswith("^") or s.endswith((".NS", ".BO")):
        return s
    if s in _ALIASES_IN:
        return _ALIASES_IN[s]
    return f"{s}.NS"


@dataclass
class StockData:
    ticker: str
    name: str
    currency: str
    price: float
    prev_close: float
    history: pd.DataFrame              # daily OHLCV, ~2y
    intraday: pd.DataFrame             # 5m bars for the last few sessions
    info: dict[str, Any] = field(default_factory=dict)
    news: list[dict[str, Any]] = field(default_factory=list)
    fetched_at: _dt.datetime = field(default_factory=lambda: _dt.datetime.now(_dt.UTC))

    @property
    def day_change_pct(self) -> float:
        if not self.prev_close:
            return 0.0
        return (self.price - self.prev_close) / self.prev_close * 100.0


def _first_float(info: dict[str, Any], *keys: str) -> float | None:
    for k in keys:
        v = info.get(k)
        if isinstance(v, (int, float)) and not pd.isna(v):
            return float(v)
    return None


def _history_with_retry(symbol: str, period: str, attempts: int = 4) -> pd.DataFrame:
    """Yahoo intermittently times out on the cookie/crumb handshake or
    rate-limits, returning an empty frame. Retry with backoff, and fall back
    to progressively shorter windows and to ``yf.download``.
    """
    periods = [period]
    for p in ("1y", "6mo", "3mo"):
        if p not in periods:
            periods.append(p)

    last_err: Exception | None = None
    for i in range(attempts):
        p = periods[min(i, len(periods) - 1)]
        try:
            tk = yf.Ticker(symbol)
            df = tk.history(period=p, interval="1d", auto_adjust=False)
            if not df.empty and df["Close"].notna().any():
                return df
            df = yf.download(
                symbol, period=p, interval="1d", auto_adjust=False,
                progress=False, threads=False,
            )
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            if not df.empty and df["Close"].notna().any():
                return df
        except Exception as exc:  # noqa: BLE001
            last_err = exc
        time.sleep(1.5 * (i + 1))

    if last_err:
        raise LookupError(
            f"Could not fetch price data for '{symbol}' ({last_err}). Yahoo "
            f"may be rate-limiting — wait a minute and retry."
        )
    raise LookupError(
        f"No price history for '{symbol}'. Check the symbol "
        f"(e.g. RELIANCE, TATASTEEL, INFY, MARUTI) — it may be wrong, "
        f"delisted, or recently renamed."
    )


def fetch(raw_ticker: str, period: str = "2y", market: Market = "IN") -> StockData:
    """Fetch everything the analysis engine needs for one symbol."""
    symbol = normalize_ticker(raw_ticker, market)
    tk = yf.Ticker(symbol)

    history = _history_with_retry(symbol, period)
    history = history.dropna(subset=["Close"])
    if history.empty:
        raise LookupError(f"Only empty rows returned for '{symbol}'.")

    try:
        intraday = tk.history(period="5d", interval="5m", auto_adjust=False)
    except Exception:
        intraday = pd.DataFrame()

    try:
        info = tk.info or {}
    except Exception:
        info = {}

    try:
        news = tk.news or []
    except Exception:
        news = []

    price = _first_float(info, "currentPrice", "regularMarketPrice") or float(
        history["Close"].iloc[-1]
    )
    prev_close = _first_float(info, "regularMarketPreviousClose", "previousClose")
    if prev_close is None:
        prev_close = float(history["Close"].iloc[-2]) if len(history) > 1 else price

    return StockData(
        ticker=symbol,
        name=info.get("longName") or info.get("shortName") or symbol,
        currency=info.get("currency", "USD" if market == "US" else "INR"),
        price=price,
        prev_close=prev_close,
        history=history,
        intraday=intraday if intraday is not None else pd.DataFrame(),
        info=info,
        news=_clean_news(news),
    )


@dataclass
class LiveQuote:
    symbol: str
    name: str
    currency: str
    price: float
    prev_close: float
    day_open: float | None
    day_high: float | None
    day_low: float | None
    day_volume: float | None
    market_state: str                 # REGULAR / PREPRE / POST / CLOSED / ...
    bars: pd.DataFrame                 # intraday OHLCV for the chosen window
    interval: str
    source: str = "YAHOO"              # NSE = exchange real-time, YAHOO = ~15m delayed
    vwap: float | None = None          # session VWAP as published by the exchange
    has_bar_volume: bool = True        # False when per-bar volume is unavailable
    volume_delayed: bool = False       # volume bars lag the price candles
    fetched_at: _dt.datetime = field(default_factory=lambda: _dt.datetime.now(_dt.UTC))

    @property
    def is_realtime(self) -> bool:
        return self.source == "NSE"

    @property
    def change(self) -> float:
        return self.price - self.prev_close

    @property
    def change_pct(self) -> float:
        return (self.change / self.prev_close * 100.0) if self.prev_close else 0.0


# Valid Yahoo (period, interval) windows for intraday.
_INTRADAY_MAX_PERIOD = {"1m": "5d", "2m": "1mo", "5m": "1mo", "15m": "1mo", "30m": "1mo", "60m": "3mo"}


def _in_market_state() -> str:
    """NSE regular session is 09:15-15:30 IST, Mon-Fri. Derived from the
    clock rather than an extra slow Yahoo call."""
    ist = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=5, minutes=30)))
    mins = ist.hour * 60 + ist.minute
    if ist.weekday() >= 5:
        return "CLOSED"
    if mins < 9 * 60:
        return "CLOSED"
    if mins < 555:
        return "PRE"
    if mins <= 930:
        return "REGULAR"
    if mins <= 16 * 60:
        return "POST"
    return "CLOSED"


def _us_market_state() -> str:
    """NYSE/NASDAQ regular session is 09:30-16:00 ET, Mon-Fri, with a
    04:00-09:30 pre-market and 16:00-20:00 post-market window."""
    et = _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=-5)))  # approx. ET (no DST table)
    mins = et.hour * 60 + et.minute
    if et.weekday() >= 5:
        return "CLOSED"
    if mins < 4 * 60:
        return "CLOSED"
    if mins < 9 * 60 + 30:
        return "PRE"
    if mins <= 16 * 60:
        return "REGULAR"
    if mins <= 20 * 60:
        return "POST"
    return "CLOSED"


def _fetch_live_yahoo(
    raw_ticker: str, interval: str = "5m", period: str = "1d", market: Market = "IN"
) -> LiveQuote:
    """A light, short-lived fetch for the live chart — intraday bars plus the
    latest quote. Kept separate from :func:`fetch` so it can be cached with a
    much shorter TTL.

    Yahoo delays Indian intraday data by roughly 15 minutes; see
    :func:`fetch_live` for the real-time path.
    """
    symbol = normalize_ticker(raw_ticker, market)
    interval = interval if interval in _INTRADAY_MAX_PERIOD else "5m"
    if interval == "1m" and period not in ("1d", "5d"):
        period = "5d"

    tk = yf.Ticker(symbol)
    bars = pd.DataFrame()
    err: Exception | None = None
    for i in range(3):
        try:
            bars = tk.history(period=period, interval=interval, auto_adjust=False)
            if not bars.empty:
                break
        except Exception as exc:  # noqa: BLE001
            err = exc
        time.sleep(1.0 * (i + 1))
    if bars is None:
        bars = pd.DataFrame()
    bars = bars.dropna(subset=["Close"]) if not bars.empty else bars

    fi: dict[str, Any] = {}
    try:
        fi = dict(tk.fast_info or {})
    except Exception:
        fi = {}

    def pick(*keys):
        for k in keys:
            v = fi.get(k)
            if isinstance(v, (int, float)) and not pd.isna(v):
                return float(v)
        return None

    price = pick("last_price", "lastPrice")
    if price is None and not bars.empty:
        price = float(bars["Close"].iloc[-1])
    prev_close = pick("previous_close", "previousClose", "regular_market_previous_close")
    if prev_close is None and len(bars) > 1:
        # First bar of the current IST day back to the prior day's last close.
        prev_close = float(bars["Close"].iloc[0])
    if prev_close is None:
        prev_close = price or 0.0

    if err is not None and bars.empty and price is None:
        raise LookupError(
            f"No live data for '{symbol}' ({err}). Yahoo may be rate-limiting."
        )

    market_state = (
        _us_market_state() if market == "US" else _in_market_state()
    )

    day_hi = pick("day_high", "dayHigh")
    day_lo = pick("day_low", "dayLow")
    if not bars.empty:
        today = bars.index[-1].date()
        sess = bars[bars.index.date == today] if hasattr(bars.index, "date") else bars
        if not sess.empty:
            day_hi = day_hi or float(sess["High"].max())
            day_lo = day_lo or float(sess["Low"].min())

    return LiveQuote(
        symbol=symbol,
        name=symbol,
        currency=fi.get("currency") or ("USD" if market == "US" else "INR"),
        price=price or 0.0,
        prev_close=prev_close or 0.0,
        day_open=pick("open", "regularMarketOpen"),
        day_high=day_hi,
        day_low=day_lo,
        day_volume=pick("last_volume", "lastVolume"),
        market_state=str(market_state),
        bars=bars,
        interval=interval,
    )


def _clean_news(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in raw[:15]:
        # yfinance has shipped two shapes for news items over time.
        content = item.get("content", item)
        title = content.get("title") or item.get("title")
        if not title:
            continue
        pub = (
            content.get("pubDate")
            or content.get("displayTime")
            or item.get("providerPublishTime")
        )
        link = ""
        if isinstance(content.get("canonicalUrl"), dict):
            link = content["canonicalUrl"].get("url", "")
        link = link or content.get("link") or item.get("link", "")
        publisher = ""
        if isinstance(content.get("provider"), dict):
            publisher = content["provider"].get("displayName", "")
        publisher = publisher or item.get("publisher", "")
        out.append(
            {"title": title, "publisher": publisher, "link": link, "published": pub}
        )
    return out


# --------------------------------------------------------------------------
# Real-time path
# --------------------------------------------------------------------------
def _borrow_yahoo_volume(bars: pd.DataFrame, symbol: str, interval: str) -> tuple[pd.DataFrame, bool]:
    """NSE's chart feed carries price but no per-bar volume. Yahoo has volume
    on the same bar grid, ~15 min behind, so we graft it on for the bars it
    covers and leave the most recent ones at zero.

    Returns ``(bars, delayed)`` — ``delayed`` is True when any volume landed.
    """
    try:
        vol = yf.Ticker(symbol).history(period="1d", interval=interval,
                                        auto_adjust=False)
    except Exception:  # noqa: BLE001
        return bars, False
    if vol is None or vol.empty or "Volume" not in vol:
        return bars, False

    v = vol["Volume"]
    try:
        if v.index.tz is None:
            v.index = v.index.tz_localize("Asia/Kolkata")
        else:
            v.index = v.index.tz_convert("Asia/Kolkata")
        bidx = bars.index.tz_convert("Asia/Kolkata") if bars.index.tz is not None else bars.index
        aligned = v.reindex(bidx).to_numpy()
    except Exception:  # noqa: BLE001
        return bars, False

    bars = bars.copy()
    bars["Volume"] = pd.Series(aligned, index=bars.index).fillna(0.0)
    return bars, bool(bars["Volume"].sum() > 0)


def _fetch_live_nse(raw_ticker: str, interval: str, market: Market) -> LiveQuote | None:
    """Exchange real-time quote + candles, or ``None`` if this symbol/market
    is not served by the NSE provider or NSE refuses."""
    if market != "IN":
        return None
    symbol = normalize_ticker(raw_ticker, market)
    base = _nse.nse_base_symbol(symbol)
    if not base:
        return None

    try:
        snap = _nse.snapshot(base, interval=interval)
    except Exception:  # noqa: BLE001 — any failure means "use Yahoo"
        return None

    bars = snap["bars"]
    if bars is None or bars.empty or not snap.get("price"):
        return None

    bars, vol_delayed = _borrow_yahoo_volume(bars, symbol, interval)

    return LiveQuote(
        symbol=symbol,
        name=snap.get("name") or symbol,
        currency="INR",
        price=float(snap["price"]),
        prev_close=float(snap.get("prev_close") or snap["price"]),
        day_open=snap.get("day_open"),
        day_high=snap.get("day_high"),
        day_low=snap.get("day_low"),
        day_volume=snap.get("day_volume"),
        # NSE tells us the session state outright ("PO" = pre-open,
        # "NM" = normal market); fall back to the clock for anything else.
        market_state={"PO": "PRE", "NM": "REGULAR"}.get(
            str(snap.get("status") or "").upper(), _in_market_state()),
        bars=bars,
        interval=interval,
        source="NSE",
        vwap=snap.get("vwap"),
        has_bar_volume=vol_delayed,
        volume_delayed=vol_delayed,
    )


def fetch_live(
    raw_ticker: str, interval: str = "5m", period: str = "1d", market: Market = "IN"
) -> LiveQuote:
    """Live chart data for one symbol.

    Prefers NSE's own real-time feed for single-session Indian equity views
    (``period == "1d"``); falls back to the ~15 min delayed Yahoo feed for
    indices, BSE symbols, US tickers, multi-day windows, and whenever NSE is
    unreachable. Check :attr:`LiveQuote.source` to see which one answered.
    """
    if market == "IN" and period == "1d":
        q = _fetch_live_nse(raw_ticker, interval, market)
        if q is not None:
            return q
    return _fetch_live_yahoo(raw_ticker, interval=interval, period=period, market=market)
