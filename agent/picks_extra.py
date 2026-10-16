"""Extra per-stock context for the Top 20 page: risk columns, liquidity, sector cap, position size,
pick history (days in top 20, rank trend, how past picks did) and data-freshness flags.

Pure functions where possible (easy to test); the only network calls are ``market_extras`` (one
batched Yahoo download) and ``next_earnings`` (best effort, one small call per symbol).
"""

from __future__ import annotations

import concurrent.futures as cf
import math
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

HISTORY_COLS = ["date", "tag", "rank", "symbol", "score", "price", "market"]
NO_SECTOR = {"", "—", "None", "nan"}


# ------------------------------------------------------------------ price-derived risk / liquidity
def atr_pct(df: pd.DataFrame, n: int = 14) -> float | None:
    """Average true range over ``n`` days as % of the last close."""
    if df is None or len(df) < n + 1:
        return None
    h, lo, c = df["High"], df["Low"], df["Close"]
    prev = c.shift(1)
    tr = pd.concat([h - lo, (h - prev).abs(), (lo - prev).abs()], axis=1).max(axis=1)
    last = float(c.iloc[-1])
    if not last or math.isnan(last):
        return None
    v = float(tr.tail(n).mean())
    return None if math.isnan(v) else v / last * 100


def extras_from_history(hist: dict[str, pd.DataFrame], today: date | None = None, stale_days: int = 4) -> pd.DataFrame:
    """One row per symbol: ATR %, % below the 52-week high, 20-day average turnover, last bar, stale flag."""
    today = today or date.today()
    rows = []
    for sym, df in hist.items():
        try:
            close = df["Close"]
            last_bar = df.index[-1].date()
            hi52 = float(df["High"].tail(252).max())
            turnover = float((df["Close"] * df["Volume"]).tail(20).mean())
            rows.append({
                "Symbol": sym,
                "ATR %": atr_pct(df),
                "From 52w high %": (float(close.iloc[-1]) / hi52 - 1) * 100 if hi52 else None,
                "Avg turnover": turnover if turnover == turnover else None,
                "Last bar": last_bar,
                "Stale": (today - last_bar).days > stale_days,
            })
        except Exception:  # noqa: BLE001 - one bad symbol must not drop the rest
            continue
    return pd.DataFrame(rows, columns=["Symbol", "ATR %", "From 52w high %", "Avg turnover", "Last bar", "Stale"])


def market_extras(symbols: list[str]) -> pd.DataFrame:
    """Batched Yahoo download for the whole pool, reduced to ``extras_from_history``."""
    from . import screener

    return extras_from_history(screener.batch_history(list(symbols), period="1y", min_rows=30))


def _first_date(v) -> date | None:
    if v is None:
        return None
    if isinstance(v, (list, tuple, np.ndarray, pd.Series)):
        v = next((x for x in v if x is not None), None)
        if v is None:
            return None
    try:
        ts = pd.Timestamp(v)
        return None if pd.isna(ts) else ts.date()
    except Exception:  # noqa: BLE001
        return None


def next_earnings(symbols: list[str], today: date | None = None) -> dict[str, date | None]:
    """Next earnings date per symbol (best effort; ``None`` when Yahoo has nothing)."""
    import yfinance as yf

    today = today or date.today()

    def one(sym: str) -> date | None:
        try:
            cal = yf.Ticker(sym).calendar
            if isinstance(cal, dict):
                d = _first_date(cal.get("Earnings Date"))
            elif isinstance(cal, pd.DataFrame) and "Earnings Date" in cal.index:
                d = _first_date(cal.loc["Earnings Date"].dropna().tolist())
            else:
                d = None
            return d if d and d >= today else None
        except Exception:  # noqa: BLE001
            return None

    out: dict[str, date | None] = {}
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for s, d in zip(symbols, ex.map(one, symbols)):
            out[s] = d
    return out


def earnings_label(d: date | None, today: date | None = None, warn_days: int = 7) -> str:
    """'18 Oct (in 2d) ⚠' — the warning shows when results are within ``warn_days``."""
    if d is None:
        return "—"
    today = today or date.today()
    n = (d - today).days
    if n < 0:
        return "—"
    return f"{d.strftime('%d %b')} (in {n}d)" + (" ⚠" if n <= warn_days else "")


# ------------------------------------------------------------------ list shaping
def cap_sector(df: pd.DataFrame, per_sector: int) -> pd.DataFrame:
    """Keep at most ``per_sector`` rows per sector, preserving order. 0 / None means no cap.

    Rows with no known sector are never capped (we can't tell what they are)."""
    if not per_sector or df.empty:
        return df
    seen: dict[str, int] = {}
    keep = []
    for _, r in df.iterrows():
        s = str(r.get("Sector"))
        if s in NO_SECTOR:
            keep.append(True)
            continue
        seen[s] = seen.get(s, 0) + 1
        keep.append(seen[s] <= per_sector)
    return df[keep]


def position_size(price: float, atr_percent: float | None, capital: float, risk_pct: float,
                  stop_mult: float = 2.0) -> tuple[int | None, float | None, float | None]:
    """(shares, position value, stop price) risking ``risk_pct`` % of ``capital`` to a stop
    ``stop_mult`` x ATR below the price. Position value never exceeds the capital."""
    if not price or price <= 0 or not atr_percent or atr_percent <= 0 or capital <= 0 or risk_pct <= 0:
        return None, None, None
    risk_per_share = stop_mult * atr_percent / 100 * price
    shares = int((capital * risk_pct / 100) // risk_per_share)
    shares = min(shares, int(capital // price))
    stop = price - risk_per_share
    return shares, shares * price, max(stop, 0.0)


# ------------------------------------------------------------------ pick history
def append_top20(path: Path, stamp: str, tag: str, top: pd.DataFrame) -> pd.DataFrame:
    """Add this run's top-20 to the history CSV (replacing any earlier rows for the same date + tag)."""
    path = Path(path)
    new = pd.DataFrame({
        "date": stamp, "tag": tag, "rank": range(1, len(top) + 1), "symbol": top["Symbol"].tolist(),
        "score": top["Score"].round(1).tolist(), "price": top["Price"].round(2).tolist(),
        "market": top["Market"].tolist(),
    })
    if path.exists():
        old = pd.read_csv(path, dtype={"date": str, "tag": str})
        old = old[~((old["date"] == stamp) & (old["tag"] == tag))]
        new = pd.concat([old, new], ignore_index=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    new[HISTORY_COLS].to_csv(path, index=False)
    return new


def load_history(path: Path) -> pd.DataFrame:
    try:
        h = pd.read_csv(path, dtype={"date": str, "tag": str})
        return h if set(HISTORY_COLS) <= set(h.columns) else pd.DataFrame(columns=HISTORY_COLS)
    except Exception:  # noqa: BLE001 - missing / unreadable history just means "no history yet"
        return pd.DataFrame(columns=HISTORY_COLS)


_TAG_ORDER = {"morning": 0, "run": 1, "evening": 2}


def _runs(hist: pd.DataFrame) -> list[tuple[str, str]]:
    runs = hist[["date", "tag"]].drop_duplicates().to_records(index=False).tolist()
    return sorted(runs, key=lambda r: (r[0], _TAG_ORDER.get(r[1], 1)))


def history_features(hist: pd.DataFrame, symbols: list[str], n_runs: int = 5, top_n: int = 20) -> pd.DataFrame:
    """Per symbol: distinct days seen in the top list, and a rank trend over the last ``n_runs`` runs.

    The trend is ``top_n + 1 - rank`` (higher = better), 0 for runs where the stock was not listed,
    so a rising line means a rising rank."""
    cols = ["Symbol", "Days in top 20", "Rank trend"]
    if hist is None or hist.empty:
        return pd.DataFrame({"Symbol": symbols, "Days in top 20": [None] * len(symbols), "Rank trend": [None] * len(symbols)}, columns=cols)
    runs = _runs(hist)[-n_runs:]
    rank = {(r.date, r.tag, r.symbol): r.rank for r in hist.itertuples()}
    days = hist.groupby("symbol")["date"].nunique()
    rows = []
    for s in symbols:
        trend = [float(top_n + 1 - rank[(d, t, s)]) if (d, t, s) in rank else 0.0 for d, t in runs]
        rows.append({"Symbol": s, "Days in top 20": int(days.get(s, 0)) or None,
                     "Rank trend": trend if any(trend) else None})
    return pd.DataFrame(rows, columns=cols)


def past_picks_performance(hist: pd.DataFrame, prices: dict[str, float], min_age_days: int = 7,
                           today: date | None = None) -> tuple[pd.DataFrame, str | None]:
    """Return since the latest run that is at least ``min_age_days`` old: (table, run label).

    Empty table + ``None`` when history is too young."""
    empty = pd.DataFrame(columns=["Symbol", "Rank then", "Price then", "Price now", "Return %"])
    if hist is None or hist.empty:
        return empty, None
    today = today or date.today()
    ok = [r for r in _runs(hist) if (today - datetime.strptime(r[0], "%Y-%m-%d").date()).days >= min_age_days]
    if not ok:
        return empty, None
    d, t = ok[-1]
    snap = hist[(hist["date"] == d) & (hist["tag"] == t)].sort_values("rank")
    rows = []
    for r in snap.itertuples():
        now = prices.get(r.symbol)
        if now and r.price:
            rows.append({"Symbol": r.symbol, "Rank then": int(r.rank), "Price then": float(r.price),
                         "Price now": float(now), "Return %": (float(now) / float(r.price) - 1) * 100})
    return pd.DataFrame(rows, columns=empty.columns), f"{d} {t}"
