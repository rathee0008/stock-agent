"""Lightweight headline sentiment.

A lexicon scorer runs with no dependencies. If an Anthropic key is present
the caller can upgrade this in ``llm.py``; this module stays offline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

_POSITIVE = {
    "surge", "surges", "jump", "jumps", "gain", "gains", "rally", "rallies",
    "beat", "beats", "record", "high", "profit", "profits", "growth", "grows",
    "upgrade", "upgraded", "outperform", "bullish", "wins", "win", "award",
    "order", "orders", "expansion", "expands", "acquire", "acquires", "acquisition",
    "dividend", "buyback", "strong", "boost", "boosts", "rises", "rise", "soars",
}
_NEGATIVE = {
    "fall", "falls", "drop", "drops", "plunge", "plunges", "slump", "decline",
    "declines", "loss", "losses", "miss", "misses", "downgrade", "downgraded",
    "underperform", "bearish", "probe", "fraud", "lawsuit", "penalty", "fine",
    "fined", "resign", "resigns", "cut", "cuts", "weak", "warning", "warns",
    "default", "debt", "layoff", "layoffs", "scam", "raid", "slips", "slide",
}


@dataclass
class NewsResult:
    score: float                       # -100 .. +100
    label: str
    headlines: list[dict[str, Any]] = field(default_factory=list)
    available: bool = True


def _label(score: float) -> str:
    if score >= 30:
        return "Positive"
    if score > -30:
        return "Mixed / Neutral"
    return "Negative"


def analyze(news: list[dict[str, Any]]) -> NewsResult:
    if not news:
        return NewsResult(score=0.0, label="No recent news", available=False)

    scored: list[dict[str, Any]] = []
    total = 0.0
    for item in news:
        words = {w.strip(".,:;!?'\"()").lower() for w in item["title"].split()}
        pos = len(words & _POSITIVE)
        neg = len(words & _NEGATIVE)
        s = pos - neg
        total += s
        tag = "positive" if s > 0 else "negative" if s < 0 else "neutral"
        scored.append({**item, "sentiment": tag, "hits": s})

    # Average per-headline tone, scaled to a bounded score.
    avg = total / len(news)
    score = float(max(-100.0, min(100.0, avg * 45.0)))
    return NewsResult(score=score, label=_label(score), headlines=scored, available=True)
