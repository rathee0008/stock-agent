"""Rank a universe: batch prices -> technical + fundamental score -> news on the shortlist.

Reuses the single-stock engines (technical / fundamental / news / signal) so the
Top-N list and the per-ticker Analyze page can never disagree.
"""

from __future__ import annotations

import concurrent.futures as cf
from typing import Any

import pandas as pd
import yfinance as yf

from . import fundamental as _fund
from . import news as _news
from . import technical as _tech
from .data import get_info
from .sectors import sector_map
from .universe import symbols


def batch_history(syms: list[str], period: str = "1y", min_rows: int = 60) -> dict[str, pd.DataFrame]:
    """One Yahoo call for the whole universe (far faster than per-symbol)."""
    raw = yf.download(syms, period=period, interval="1d", auto_adjust=False,
                      progress=False, threads=True, group_by="ticker")
    out: dict[str, pd.DataFrame] = {}
    for s in syms:
        try:
            df = raw[s].dropna(subset=["Close"])
            if len(df) >= min_rows:
                out[s] = df
        except Exception:  # noqa: BLE001
            continue
    return out


def live_prices(syms: list[str]) -> dict[str, tuple[float, float]]:
    """{symbol: (last price, previous close)} from 5-minute bars (Yahoo, ~15 min delayed).

    Previous close is the last close of the prior trading day found in the bars, so the
    change is "today vs yesterday's close" even before the first bar of a new session.
    """
    raw = yf.download(syms, period="5d", interval="5m", auto_adjust=False, progress=False,
                      threads=True, group_by="ticker", prepost=False)
    out: dict[str, tuple[float, float]] = {}
    for s in syms:
        try:
            c = raw[s]["Close"].dropna()
            if c.empty:
                continue
            days = c.index.normalize()
            today = days[-1]
            prev = c[days < today]
            if prev.empty:
                continue
            out[s] = (float(c.iloc[-1]), float(prev.iloc[-1]))
        except Exception:  # noqa: BLE001
            continue
    return out


def _info_and_news(sym: str) -> tuple[dict, list]:
    tk = yf.Ticker(sym)
    info = get_info(sym)
    try:
        from .data import _clean_news
        news = _clean_news(tk.news or [])
    except Exception:  # noqa: BLE001
        news = []
    return info, news


def _why(signals, n: int = 2) -> str:
    """Strongest positive reasons from (name, text, points) signal tuples."""
    pos = sorted((x for x in (signals or []) if x[2] > 0), key=lambda x: -x[2])[:n]
    return "; ".join(f"{a}: {b}" for a, b, _ in pos)


def movers_frame(market: str) -> pd.DataFrame:
    """Every universe stock's last-day move, with gap %, 52-week position and sector."""
    hist = batch_history(symbols(market), period="1y", min_rows=2)
    smap = sector_map(market)
    rows = []
    for s, df in hist.items():
        c = df["Close"]
        if len(c) < 2:
            continue
        hi, lo = float(df["High"].max()), float(df["Low"].min())
        opn = float(df["Open"].iloc[-1]) if "Open" in df else float("nan")
        rows.append({"Symbol": s, "Price": c.iloc[-1], "Change %": (c.iloc[-1] / c.iloc[-2] - 1) * 100,
                     "Volume": df["Volume"].iloc[-1],
                     "Vol vs 5d avg": df["Volume"].iloc[-1] / max(df["Volume"].tail(5).mean(), 1),
                     "Gap %": (opn / float(c.iloc[-2]) - 1) * 100 if opn == opn else float("nan"),
                     "52W pos %": (float(c.iloc[-1]) - lo) / max(hi - lo, 1e-9) * 100,
                     "Sector": smap.get(s, "—"),
                     "As of": df.index[-1].date()})
    return pd.DataFrame(rows).sort_values("Change %", ascending=False).reset_index(drop=True)


def split_movers(d: pd.DataFrame, top: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    return d.head(top).reset_index(drop=True), d.tail(top).iloc[::-1].reset_index(drop=True)


def sector_averages(d: pd.DataFrame) -> dict[str, float]:
    """Mean day change per sector over every stock in the universe frame."""
    if d is None or d.empty:
        return {}
    return d.groupby("Sector")["Change %"].mean().to_dict()


def movers(market: str, top: int = 10) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Day gainers / losers across the universe (last close vs previous close)."""
    return split_movers(movers_frame(market), top)


def rank(market: str, w: tuple[float, float, float] = (0.40, 0.45, 0.15),
         shortlist: int = 40) -> pd.DataFrame:
    """Score every symbol; fetch fundamentals for all, news for the shortlist."""
    syms = symbols(market)
    smap = sector_map(market)
    hist = batch_history(syms)

    tech: dict[str, Any] = {}
    for s, df in hist.items():
        try:
            tech[s] = _tech.analyze(df)
        except Exception:  # noqa: BLE001
            pass

    infos: dict[str, tuple[dict, list]] = {}
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(_info_and_news, s): s for s in tech}
        for f in cf.as_completed(futs):
            try:
                infos[futs[f]] = f.result()
            except Exception:  # noqa: BLE001
                infos[futs[f]] = ({}, [])

    rows = []
    for s, t in tech.items():
        info, news = infos.get(s, ({}, []))
        f = _fund.analyze(info)
        n = _news.analyze(news)
        # missing fundamentals/news -> neutral 0 and weight redistributed
        ws = {"t": w[0], "f": w[1] if f.available else 0, "n": w[2] if n.available else 0}
        tot = sum(ws.values()) or 1
        score = (t.score * ws["t"] + f.score * ws["f"] + n.score * ws["n"]) / tot
        close = hist[s]["Close"]
        m = f.metrics or {}
        rows.append({
            "Symbol": s, "Name": info.get("shortName") or s, "Sector": info.get("sector") or smap.get(s, "—"),
            "Price": close.iloc[-1], "Day %": (close.iloc[-1] / close.iloc[-2] - 1) * 100,
            "3M %": (close.iloc[-1] / close.iloc[-63] - 1) * 100 if len(close) > 63 else None,
            "Score": round(score, 1), "Technical": round(t.score), "Fundamental": round(f.score),
            "News": round(n.score), "Mkt cap": info.get("marketCap"),
            "P/E": info.get("trailingPE"), "ROE %": (info.get("returnOnEquity") or 0) * 100 or None,
            "Rev growth %": (info.get("revenueGrowth") or 0) * 100 or None,
            "Analyst": info.get("recommendationKey", "—"),
            "Upside %": ((info["targetMeanPrice"] / close.iloc[-1] - 1) * 100
                         if info.get("targetMeanPrice") else None),
            "RSI": (t.indicators or {}).get("rsi"),
            "Why": _why(t.signals) + " · " + _why(f.signals),
            "Market": market, "_fund_ok": f.available,
        })
    df = pd.DataFrame(rows)
    # Investable = decent fundamentals AND not overheated; keeps momentum-only junk out.
    df["RSI"] = pd.to_numeric(df["RSI"], errors="coerce")
    ok_rsi = df["RSI"].fillna(50) < 80
    good = df[df["_fund_ok"] & (df["Fundamental"] > -10) & ok_rsi]
    if len(good) < 10:  # Yahoo fundamentals flaky -> backfill with technical/news-only picks
        rest = df[~df["_fund_ok"] & ok_rsi].sort_values("Score", ascending=False)
        good = pd.concat([good, rest.head(10 - len(good))])
    return (good.drop(columns="_fund_ok")
            .sort_values("Score", ascending=False).reset_index(drop=True))
