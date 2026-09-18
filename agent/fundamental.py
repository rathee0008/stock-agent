"""Fundamental analysis — valuation, profitability, balance sheet, growth."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd


def _f(info: dict, *keys: str) -> float | None:
    for k in keys:
        v = info.get(k)
        if isinstance(v, (int, float)) and not pd.isna(v):
            return float(v)
    return None


@dataclass
class FundamentalResult:
    score: float                       # -100 .. +100
    label: str
    metrics: dict[str, Any] = field(default_factory=dict)
    signals: list[tuple[str, str, float]] = field(default_factory=list)
    available: bool = True


def _label(score: float) -> str:
    if score >= 40:
        return "Strong"
    if score >= 12:
        return "Above average"
    if score > -12:
        return "Average"
    if score > -40:
        return "Weak"
    return "Poor"


def analyze(info: dict) -> FundamentalResult:
    signals: list[tuple[str, str, float]] = []

    def add(name: str, note: str, pts: float) -> None:
        signals.append((name, note, pts))

    pe = _f(info, "trailingPE")
    fwd_pe = _f(info, "forwardPE")
    pb = _f(info, "priceToBook")
    peg = _f(info, "pegRatio", "trailingPegRatio")
    roe = _f(info, "returnOnEquity")
    profit_margin = _f(info, "profitMargins")
    op_margin = _f(info, "operatingMargins")
    d2e = _f(info, "debtToEquity")
    current_ratio = _f(info, "currentRatio")
    rev_growth = _f(info, "revenueGrowth")
    earnings_growth = _f(info, "earningsGrowth", "earningsQuarterlyGrowth")
    # yfinance has flip-flopped between fraction (0.004) and percent (0.4) here.
    div_yield = _f(info, "trailingAnnualDividendYield", "dividendYield")
    if div_yield is not None and div_yield > 1:
        div_yield = div_yield / 100.0
    market_cap = _f(info, "marketCap")

    if pe is not None:
        if pe <= 0:
            add("P/E", "negative earnings (loss-making)", -14)
        elif pe < 15:
            add("P/E", f"low ({pe:.1f}) — inexpensive vs earnings", 10)
        elif pe < 30:
            add("P/E", f"moderate ({pe:.1f})", 2)
        elif pe < 60:
            add("P/E", f"rich ({pe:.1f})", -6)
        else:
            add("P/E", f"very rich ({pe:.1f})", -12)

    if fwd_pe is not None and pe is not None and fwd_pe > 0:
        if fwd_pe < pe * 0.85:
            add("Forward P/E", "earnings expected to grow (fwd P/E well below trailing)", 6)
        elif fwd_pe > pe * 1.15:
            add("Forward P/E", "earnings expected to fall", -6)

    if peg is not None and peg > 0:
        if peg < 1:
            add("PEG", f"{peg:.2f} — growth cheap relative to price", 8)
        elif peg > 2.5:
            add("PEG", f"{peg:.2f} — expensive relative to growth", -6)

    if pb is not None:
        if pb < 1:
            add("P/B", f"{pb:.2f} — below book value", 6)
        elif pb > 8:
            add("P/B", f"{pb:.1f} — very high", -6)

    if roe is not None:
        if roe > 0.20:
            add("ROE", f"{roe*100:.0f}% — highly profitable on equity", 12)
        elif roe > 0.12:
            add("ROE", f"{roe*100:.0f}% — solid", 6)
        elif roe < 0:
            add("ROE", "negative — destroying equity value", -12)
        elif roe < 0.08:
            add("ROE", f"{roe*100:.0f}% — low", -5)

    if profit_margin is not None:
        if profit_margin > 0.15:
            add("Net margin", f"{profit_margin*100:.0f}% — strong", 8)
        elif profit_margin < 0:
            add("Net margin", "loss-making", -10)
        elif profit_margin < 0.03:
            add("Net margin", f"{profit_margin*100:.1f}% — thin", -4)

    if d2e is not None:
        # yfinance reports debt/equity as a percentage.
        if d2e > 200:
            add("Debt/Equity", f"{d2e/100:.1f}x — heavily leveraged", -12)
        elif d2e > 100:
            add("Debt/Equity", f"{d2e/100:.1f}x — elevated leverage", -6)
        elif d2e < 30:
            add("Debt/Equity", f"{d2e/100:.2f}x — low leverage", 6)

    if current_ratio is not None:
        if current_ratio < 1:
            add("Current ratio", f"{current_ratio:.2f} — short-term liquidity pressure", -6)
        elif current_ratio > 1.5:
            add("Current ratio", f"{current_ratio:.2f} — comfortable liquidity", 4)

    if rev_growth is not None:
        if rev_growth > 0.15:
            add("Revenue growth", f"{rev_growth*100:.0f}% YoY — fast", 10)
        elif rev_growth > 0.05:
            add("Revenue growth", f"{rev_growth*100:.0f}% YoY", 4)
        elif rev_growth < 0:
            add("Revenue growth", f"{rev_growth*100:.0f}% YoY — shrinking", -10)

    if earnings_growth is not None:
        if earnings_growth > 0.15:
            add("Earnings growth", f"{earnings_growth*100:.0f}% — expanding", 10)
        elif earnings_growth < -0.10:
            add("Earnings growth", f"{earnings_growth*100:.0f}% — contracting", -10)

    if div_yield is not None and div_yield > 0.03:
        add("Dividend yield", f"{div_yield*100:.1f}% — income support", 3)

    available = len(signals) > 0
    raw = sum(pts for _, _, pts in signals)
    # Normalise: cap contribution so a data-sparse name isn't over-penalised.
    score = float(max(-100.0, min(100.0, raw)))

    metrics = {
        "pe": pe,
        "forward_pe": fwd_pe,
        "pb": pb,
        "peg": peg,
        "roe": roe,
        "profit_margin": profit_margin,
        "operating_margin": op_margin,
        "debt_to_equity": d2e / 100 if d2e is not None else None,
        "current_ratio": current_ratio,
        "revenue_growth": rev_growth,
        "earnings_growth": earnings_growth,
        "dividend_yield": div_yield,
        "market_cap": market_cap,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "target_mean_price": _f(info, "targetMeanPrice"),
        "recommendation": info.get("recommendationKey"),
        "analyst_count": _f(info, "numberOfAnalystOpinions"),
    }

    return FundamentalResult(
        score=score if available else 0.0,
        label=_label(score) if available else "No data",
        metrics=metrics,
        signals=sorted(signals, key=lambda s: -abs(s[2])),
        available=available,
    )
