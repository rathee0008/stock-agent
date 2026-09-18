"""Combine the three views into one composite signal and a statistical range."""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .fundamental import FundamentalResult
from .news import NewsResult
from .technical import TechnicalResult

# Default blend. Technicals drive near-term moves; fundamentals anchor the
# medium term; news is a lighter tilt.
DEFAULT_WEIGHTS = {"technical": 0.45, "fundamental": 0.40, "news": 0.15}


@dataclass
class Projection:
    horizon_days: int
    expected_return_pct: float
    low_pct: float                     # ~1 std band
    high_pct: float
    low_price: float
    high_price: float
    expected_price: float


@dataclass
class CompositeSignal:
    score: float                       # -100 .. +100
    label: str                         # Strong Buy / Buy / Hold / Sell / Strong Sell
    confidence: str                    # Low / Moderate / High
    confidence_pct: float
    weights: dict[str, float]
    contributions: dict[str, float] = field(default_factory=dict)
    projections: list[Projection] = field(default_factory=list)
    rationale: list[str] = field(default_factory=list)


def _label(score: float) -> str:
    if score >= 40:
        return "Strong Buy (bias)"
    if score >= 15:
        return "Buy (bias)"
    if score > -15:
        return "Hold / Neutral"
    if score > -40:
        return "Sell (bias)"
    return "Strong Sell (bias)"


def _project(history: pd.DataFrame, tech: TechnicalResult, bias: float) -> list[Projection]:
    """A volatility band around a small drift.

    The drift is a damped function of the composite score and recent trend —
    this is a *statistical range*, not a forecast of where the price will be.
    """
    close = history["Close"]
    rets = np.log(close / close.shift()).dropna()
    daily_vol = float(rets.tail(120).std()) or float(rets.std()) or 0.02
    price = tech.price

    # Blend recent realised drift with the model bias, then damp hard.
    realised_drift = float(rets.tail(60).mean())
    model_drift = (bias / 100.0) * 0.0009            # +/-9 bps per day at score 100
    daily_drift = 0.35 * realised_drift + 0.65 * model_drift

    out: list[Projection] = []
    for days in (5, 21, 63):
        exp_ret = daily_drift * days
        sigma = daily_vol * math.sqrt(days)
        lo, hi = exp_ret - sigma, exp_ret + sigma
        out.append(
            Projection(
                horizon_days=days,
                expected_return_pct=exp_ret * 100,
                low_pct=lo * 100,
                high_pct=hi * 100,
                low_price=price * (1 + lo),
                high_price=price * (1 + hi),
                expected_price=price * (1 + exp_ret),
            )
        )
    return out


def combine(
    tech: TechnicalResult,
    fund: FundamentalResult,
    news: NewsResult,
    history: pd.DataFrame,
    weights: dict[str, float] | None = None,
) -> CompositeSignal:
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update(weights)

    # Re-normalise over the components we actually have data for.
    active = {"technical": True, "fundamental": fund.available, "news": news.available}
    wsum = sum(w[k] for k, on in active.items() if on) or 1.0
    eff = {k: (w[k] / wsum if active[k] else 0.0) for k in w}

    parts = {
        "technical": tech.score * eff["technical"],
        "fundamental": fund.score * eff["fundamental"],
        "news": news.score * eff["news"],
    }
    score = float(np.clip(sum(parts.values()), -100, 100))

    # Confidence: how much the components agree, plus data completeness.
    comp_scores = [tech.score]
    if fund.available:
        comp_scores.append(fund.score)
    if news.available:
        comp_scores.append(news.score)
    signs = [1 if s > 8 else -1 if s < -8 else 0 for s in comp_scores]
    agree = abs(sum(signs)) / len(signs)
    completeness = sum(active.values()) / 3
    conf_pct = round(100 * (0.55 * agree + 0.30 * completeness + 0.15 * min(1.0, abs(score) / 50)))
    confidence = "High" if conf_pct >= 67 else "Moderate" if conf_pct >= 40 else "Low"

    rationale: list[str] = []
    rationale.append(f"Technical: {tech.label} ({tech.score:+.0f}).")
    if fund.available:
        rationale.append(f"Fundamental: {fund.label} ({fund.score:+.0f}).")
    else:
        rationale.append("Fundamental: no usable data from source.")
    if news.available:
        rationale.append(f"News tone: {news.label} ({news.score:+.0f}).")
    for name, note, _ in tech.signals[:3]:
        rationale.append(f"• {name}: {note}")
    for name, note, _ in fund.signals[:3]:
        rationale.append(f"• {name}: {note}")

    return CompositeSignal(
        score=score,
        label=_label(score),
        confidence=confidence,
        confidence_pct=conf_pct,
        weights=eff,
        contributions=parts,
        projections=_project(history, tech, score),
        rationale=rationale,
    )
