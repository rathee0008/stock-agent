"""Cross-asset live snapshot: equity indices, crypto, commodities, dollar, USD/INR and US Treasury yields.

One batched Yahoo call for 1-minute bars (latest price + sparkline) and one for daily closes (previous
close), merged per instrument in ``build_row``. Anything the batch misses falls back to the symbol's
quote metadata, the same way the World Heatmap page does.

Treasury yields are quoted in percent, so their move is reported in basis points, not percent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

LIVE_MAX_AGE_MIN = 20  # last bar younger than this = "live"; older = market closed / feed paused
SPARK_POINTS = 60


@dataclass(frozen=True)
class Instrument:
    group: str
    label: str
    symbol: str
    kind: str = "price"  # "price" (move in %) or "yield" (move in bps)
    dp: int = 2          # decimals shown


GROUPS = ["India", "US", "World indices", "Commodities", "Crypto", "Dollar, rupee & yields"]

INSTRUMENTS: list[Instrument] = [
    Instrument("India", "NIFTY 50", "^NSEI"),
    Instrument("India", "SENSEX", "^BSESN"),
    Instrument("India", "BANK NIFTY", "^NSEBANK"),
    Instrument("India", "INDIA VIX", "^INDIAVIX"),
    Instrument("US", "S&P 500", "^GSPC"),
    Instrument("US", "NASDAQ", "^IXIC"),
    Instrument("US", "DOW JONES", "^DJI"),
    Instrument("US", "RUSSELL 2000", "^RUT"),
    Instrument("US", "VIX", "^VIX"),
    Instrument("World indices", "NIKKEI 225", "^N225"),
    Instrument("World indices", "KOSPI", "^KS11"),
    Instrument("World indices", "HANG SENG", "^HSI"),
    Instrument("World indices", "SHANGHAI", "000001.SS"),
    Instrument("World indices", "FTSE 100", "^FTSE"),
    Instrument("World indices", "DAX", "^GDAXI"),
    Instrument("World indices", "CAC 40", "^FCHI"),
    Instrument("Commodities", "GOLD (US$/oz)", "GC=F"),
    Instrument("Commodities", "SILVER (US$/oz)", "SI=F", dp=3),
    Instrument("Commodities", "CRUDE OIL WTI", "CL=F"),
    Instrument("Commodities", "CRUDE OIL BRENT", "BZ=F"),
    Instrument("Crypto", "BITCOIN", "BTC-USD"),
    Instrument("Dollar, rupee & yields", "US DOLLAR INDEX (DXY)", "DX-Y.NYB", dp=3),
    Instrument("Dollar, rupee & yields", "USD / INR", "INR=X", dp=3),
    Instrument("Dollar, rupee & yields", "US 3M T-BILL", "^IRX", "yield", 3),
    Instrument("Dollar, rupee & yields", "US 5Y YIELD", "^FVX", "yield", 3),
    Instrument("Dollar, rupee & yields", "US 10Y YIELD", "^TNX", "yield", 3),
    Instrument("Dollar, rupee & yields", "US 30Y YIELD", "^TYX", "yield", 3),
]

COLUMNS = ["group", "label", "symbol", "kind", "dp", "price", "prev", "chg", "move", "unit",
           "asof", "age_min", "live", "spark"]


def _norm(series: pd.Series | None, kind: str) -> pd.Series:
    """Clean closes; some Yahoo yield symbols are quoted as yield x 10, so rescale those."""
    if series is None:
        return pd.Series(dtype=float)
    s = pd.to_numeric(series, errors="coerce").dropna().astype(float)
    if kind == "yield" and len(s) and s.median() > 25:
        s = s / 10
    return s


def _utc(ts) -> datetime:
    ts = pd.Timestamp(ts)
    ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.to_pydatetime()


def _stride(values: list[float], n: int = SPARK_POINTS) -> list[float]:
    if len(values) <= n:
        return values
    step = len(values) / n
    out = [values[int(i * step)] for i in range(n)]
    out[-1] = values[-1]
    return out


def _finish(inst: Instrument, last: float, prev: float | None, ts, spark: list[float],
            now: datetime) -> dict:
    if inst.kind == "yield":
        chg = None if prev is None else last - prev
        move = None if prev is None else (last - prev) * 100  # basis points
        unit = "bps"
    else:
        chg = None if prev is None else last - prev
        move = None if prev in (None, 0) else (last / prev - 1) * 100
        unit = "%"
    when = _utc(ts)
    age = (now - when).total_seconds() / 60
    return {"group": inst.group, "label": inst.label, "symbol": inst.symbol, "kind": inst.kind,
            "dp": inst.dp, "price": last, "prev": prev, "chg": chg, "move": move, "unit": unit,
            "asof": when, "age_min": age, "live": age <= LIVE_MAX_AGE_MIN, "spark": spark}


def build_row(inst: Instrument, daily: pd.Series | None, intraday: pd.Series | None,
              now: datetime | None = None) -> dict | None:
    """Merge daily + intraday closes into one display row; None when there is no usable price."""
    now = now or datetime.now(timezone.utc)
    d, i = _norm(daily, inst.kind), _norm(intraday, inst.kind)
    if i.empty and d.empty:
        return None
    if not i.empty:
        ts, last = i.index[-1], float(i.iloc[-1])
        session = ts.date()  # exchange-local trading date of the latest bar
        prior = d[[x.date() < session for x in d.index]]
        prev = float(prior.iloc[-1]) if len(prior) else None
        day = i[[x.date() == session for x in i.index]]
        spark = _stride([float(v) for v in day])
    else:
        ts, last = d.index[-1], float(d.iloc[-1])
        prev = float(d.iloc[-2]) if len(d) > 1 else None
        spark = [float(v) for v in d.tail(30)]
    return _finish(inst, last, prev, ts, spark, now)


def _meta_row(inst: Instrument, now: datetime) -> dict | None:
    """Fallback for symbols the batch download missed: live price vs previous close from quote metadata."""
    try:
        t = yf.Ticker(inst.symbol)
        t.history(period="1d")
        m = t.history_metadata or {}
        last, prev, ts = m.get("regularMarketPrice"), m.get("chartPreviousClose"), m.get("regularMarketTime")
        if not last:
            return None
        if inst.kind == "yield" and float(last) > 25:
            last, prev = float(last) / 10, (float(prev) / 10 if prev else None)
        when = ts if hasattr(ts, "tzinfo") else datetime.fromtimestamp(ts or 0, tz=timezone.utc)
        return _finish(inst, float(last), float(prev) if prev else None, when, [], now)
    except Exception:  # noqa: BLE001
        return None


def _download(symbols: list[str], period: str, interval: str):
    try:
        return yf.download(symbols, period=period, interval=interval, auto_adjust=False, progress=False,
                           threads=True, group_by="ticker")
    except Exception:  # noqa: BLE001
        return None


def _close(raw, symbol: str) -> pd.Series | None:
    if raw is None:
        return None
    try:
        return raw[symbol]["Close"].dropna()
    except Exception:  # noqa: BLE001
        return None


def fetch_snapshot(instruments: list[Instrument] | None = None) -> pd.DataFrame:
    """One row per instrument that returned a price, in INSTRUMENTS order."""
    instruments = instruments or INSTRUMENTS
    syms = [x.symbol for x in instruments]
    daily = _download(syms, "10d", "1d")
    intra = _download(syms, "5d", "1m")
    now = datetime.now(timezone.utc)
    rows = []
    for inst in instruments:
        row = build_row(inst, _close(daily, inst.symbol), _close(intra, inst.symbol), now)
        row = row or _meta_row(inst, now)
        if row:
            rows.append(row)
    return pd.DataFrame(rows, columns=COLUMNS)
