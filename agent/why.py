"""Explain why a stock is moving: rule-based tags first, optional Claude summary on top.

``explain`` is pure (no network) so it can be tested. It combines price/volume facts,
52-week position, sector context, delivery %, exchange deals and the newest headline.
"""

from __future__ import annotations

import pandas as pd

from . import config, log


def explain(row: dict, sector_avg: dict[str, float] | None = None, deal_note: str | None = None,
            headline: str | None = None) -> list[str]:
    """Return short reason tags, strongest first."""
    tags: list[str] = []
    chg = float(row.get("Change %") or 0)
    vol = row.get("Vol vs 5d avg")
    gap = row.get("Gap %")
    pos = row.get("52W pos %")
    deliv = row.get("Delivery %")
    sec = row.get("Sector")

    if headline:
        tags.append(f"News: {headline}")
    if deal_note:
        tags.append(deal_note)
    if vol is not None and pd.notna(vol) and vol >= 2.0:
        tags.append(f"Volume {vol:.1f}× the 5-day average")
    elif vol is not None and pd.notna(vol) and vol >= 1.5:
        tags.append(f"Elevated volume ({vol:.1f}×)")
    if deliv is not None and pd.notna(deliv) and deliv >= 60:
        tags.append(f"High delivery {deliv:.0f}% (real buying/selling, not intraday churn)" if chg else f"High delivery {deliv:.0f}%")
    elif deliv is not None and pd.notna(deliv) and deliv <= 25:
        tags.append(f"Low delivery {deliv:.0f}% (mostly intraday trading)")
    if gap is not None and pd.notna(gap) and abs(gap) >= 1.5:
        tags.append(f"Gapped {'up' if gap > 0 else 'down'} {abs(gap):.1f}% at the open")
    if pos is not None and pd.notna(pos):
        if pos >= 97:
            tags.append("At its 52-week high")
        elif pos <= 3:
            tags.append("At its 52-week low")
    if sec and sector_avg and sec in sector_avg:
        sa = sector_avg[sec]
        if abs(chg) >= 1 and (chg > 0) == (sa > 0) and abs(sa) >= 0.7:
            tags.append(f"Moving with its sector ({sec} {sa:+.1f}%)")
        elif abs(chg - sa) >= 2:
            tags.append(f"Stock-specific: {sec} is {sa:+.1f}% but this is {chg:+.1f}%")
    return tags[:4] or ["No clear catalyst in price, volume or news data"]


def claude_summary(items: list[dict]) -> dict[str, str]:
    """One batched Claude call -> {symbol: one-sentence reason}. Empty dict without a key."""
    key = config.get("ANTHROPIC_API_KEY")
    if not key or not items:
        return {}
    import json

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model=config.get("STOCK_AGENT_MODEL", "claude-sonnet-5"),
            max_tokens=900,
            system=("You explain large single-day stock moves for a retail investor. Use ONLY the facts "
                    "given (price change, volume, delivery, deals, sector move, headlines). If the facts do "
                    "not explain the move, say the cause is unclear. One sentence per stock, max 28 words, "
                    "no advice. Return strict JSON: {\"SYMBOL\": \"sentence\", ...}."),
            messages=[{"role": "user", "content": json.dumps(items, default=str)}],
        )
        text = "".join(b.text for b in msg.content if b.type == "text")
        start, end = text.find("{"), text.rfind("}")
        return {k: str(v) for k, v in json.loads(text[start:end + 1]).items()}
    except Exception as exc:  # noqa: BLE001
        log.record("claude:why", exc)
        return {}
