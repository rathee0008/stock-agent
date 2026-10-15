"""Top-level orchestrator: ticker in, full analysis dict out."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from . import backtest as _bt
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
    tuned_technical: bool = False,
) -> dict[str, Any]:
    sd = _data.fetch(ticker, period=period, market=market)

    tech = _tech.analyze(sd.history, group_weights=(_bt.load_weights() if tuned_technical else None))
    fund = _fund.analyze(sd.info)
    news = _news.analyze(sd.news)
    comp = _signal.combine(tech, fund, news, sd.history, weights=weights)
    comp.calibration = _bt.calibrated_statement(tech.score, market)
    freshness = _freshness(sd, news)

    return {
        "ticker": sd.ticker,
        "market": market,
        "name": sd.name,
        "currency": sd.currency,
        "price": sd.price,
        "prev_close": sd.prev_close,
        "day_change_pct": sd.day_change_pct,
        "fetched_at": sd.fetched_at.isoformat(),
        "freshness": freshness,
        "stale": sd.stale,
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
            "drivers": comp.drivers,
            "conflict": comp.conflict,
            "conflict_note": comp.conflict_note,
            "calibration": comp.calibration,
        },
    }


def _freshness(sd, news) -> dict[str, Any]:
    """Per-signal data age so the UI can show whether every input is from today."""
    now = pd.Timestamp.now(tz="UTC")
    last_bar = sd.history.index[-1]
    last_bar = last_bar.tz_convert("UTC") if last_bar.tzinfo else last_bar.tz_localize("UTC")
    newest_news = None
    for h in news.headlines:
        try:
            t = pd.to_datetime(h.get("published"), utc=True, unit="s" if isinstance(h.get("published"), (int, float)) else None)
        except Exception:  # noqa: BLE001
            continue
        if pd.notna(t) and (newest_news is None or t > newest_news):
            newest_news = t

    def age_h(ts):
        return None if ts is None else round((now - ts).total_seconds() / 3600, 1)

    return {
        "technical": {"as_of": last_bar.isoformat(), "age_h": age_h(last_bar), "source": sd.sources.get("price", "YAHOO")},
        "fundamental": {"as_of": sd.fetched_at.isoformat(), "age_h": 0.0, "source": sd.sources.get("info", "YAHOO"),
                        "note": "annual statements; refresh is quarterly"},
        "news": {"as_of": newest_news.isoformat() if newest_news is not None else None,
                 "age_h": age_h(newest_news), "source": sd.sources.get("news", "YAHOO")},
    }
