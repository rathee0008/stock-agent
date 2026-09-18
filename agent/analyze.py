"""Top-level orchestrator: ticker in, full analysis dict out."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from . import data as _data
from . import fundamental as _fund
from . import news as _news
from . import signal as _signal
from . import technical as _tech


def analyze_stock(
    ticker: str,
    weights: dict[str, float] | None = None,
    period: str = "2y",
    market: str = "IN",
) -> dict[str, Any]:
    sd = _data.fetch(ticker, period=period, market=market)

    tech = _tech.analyze(sd.history)
    fund = _fund.analyze(sd.info)
    news = _news.analyze(sd.news)
    comp = _signal.combine(tech, fund, news, sd.history, weights=weights)

    return {
        "ticker": sd.ticker,
        "market": market,
        "name": sd.name,
        "currency": sd.currency,
        "price": sd.price,
        "prev_close": sd.prev_close,
        "day_change_pct": sd.day_change_pct,
        "fetched_at": sd.fetched_at.isoformat(),
        "history": sd.history,
        "intraday": sd.intraday,
        "info": sd.info,
        "technical": {
            "score": tech.score,
            "label": tech.label,
            "indicators": tech.indicators,
            "signals": tech.signals,
            "frame": tech.frame,
        },
        "fundamental": {
            "score": fund.score,
            "label": fund.label,
            "metrics": fund.metrics,
            "signals": fund.signals,
            "available": fund.available,
        },
        "news": {
            "score": news.score,
            "label": news.label,
            "headlines": news.headlines,
            "available": news.available,
        },
        "signal": {
            "score": comp.score,
            "label": comp.label,
            "confidence": comp.confidence,
            "confidence_pct": comp.confidence_pct,
            "weights": comp.weights,
            "contributions": comp.contributions,
            "projections": [asdict(p) for p in comp.projections],
            "rationale": comp.rationale,
        },
    }
