"""Optional Claude-written synthesis of the computed analysis.

If ``ANTHROPIC_API_KEY`` is missing or the SDK call fails, ``synthesize``
returns a deterministic template instead so the app always has narrative text.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Any

MODEL = os.environ.get("STOCK_AGENT_MODEL", "claude-sonnet-5")

_SYSTEM = """You are an equities analyst assistant for Indian (NSE/BSE) stocks.
You are given pre-computed technical indicators, fundamental ratios and news
sentiment for one company. Write a concise, balanced briefing for a retail
investor doing their own research.

Rules:
- Use only the numbers provided. Do not invent data or price targets.
- Give a clear structure: Snapshot, Technical picture, Fundamental picture,
  News, What would change the view (bull vs bear triggers), Key risks.
- Be plain-spoken. No hype. Note when data is missing or thin.
- This is analysis and education, not personalised investment advice, and you
  must say so in one short closing line.
- Keep it under 400 words. Use short markdown sections."""


def _payload(analysis: dict[str, Any]) -> str:
    slim = {
        "ticker": analysis["ticker"],
        "name": analysis["name"],
        "price": analysis["price"],
        "day_change_pct": analysis["day_change_pct"],
        "currency": analysis["currency"],
        "composite": {
            "score": analysis["signal"]["score"],
            "label": analysis["signal"]["label"],
            "confidence": analysis["signal"]["confidence"],
            "weights": analysis["signal"]["weights"],
        },
        "projections": analysis["signal"]["projections"],
        "technical": {
            "score": analysis["technical"]["score"],
            "label": analysis["technical"]["label"],
            "indicators": analysis["technical"]["indicators"],
            "signals": analysis["technical"]["signals"][:8],
        },
        "fundamental": {
            "score": analysis["fundamental"]["score"],
            "label": analysis["fundamental"]["label"],
            "metrics": analysis["fundamental"]["metrics"],
            "signals": analysis["fundamental"]["signals"][:8],
        },
        "news": {
            "score": analysis["news"]["score"],
            "label": analysis["news"]["label"],
            "headlines": [h["title"] for h in analysis["news"]["headlines"][:8]],
        },
    }
    return json.dumps(slim, default=str, indent=2)


def synthesize(analysis: dict[str, Any]) -> tuple[str, str]:
    """Return (markdown_text, source) where source is 'claude' or 'template'."""
    key = os.environ.get("ANTHROPIC_API_KEY")
    if key:
        try:
            import anthropic

            client = anthropic.Anthropic(api_key=key)
            msg = client.messages.create(
                model=MODEL,
                max_tokens=1200,
                system=_SYSTEM,
                messages=[
                    {
                        "role": "user",
                        "content": "Here is the computed analysis JSON:\n\n"
                        + _payload(analysis)
                        + "\n\nWrite the briefing.",
                    }
                ],
            )
            text = "".join(b.text for b in msg.content if b.type == "text")
            if text.strip():
                return text.strip(), "claude"
        except Exception as exc:  # noqa: BLE001 - fall back on any failure
            return _template(analysis, note=f"(Claude call failed: {exc})"), "template"
    return _template(analysis), "template"


def _template(analysis: dict[str, Any], note: str = "") -> str:
    s = analysis["signal"]
    t = analysis["technical"]
    f = analysis["fundamental"]
    n = analysis["news"]
    lines = [
        f"### {analysis['name']} ({analysis['ticker']})",
        f"Price {analysis['currency']} {analysis['price']:.2f} "
        f"({analysis['day_change_pct']:+.2f}% today).",
        "",
        f"**Composite view:** {s['label']} — score {s['score']:+.0f}/100, "
        f"confidence {s['confidence']}.",
        "",
        "**Technical picture**",
        f"- {t['label']} (score {t['score']:+.0f}).",
    ]
    lines += [f"- {name}: {note_}" for name, note_, _ in t["signals"][:5]]
    lines += ["", "**Fundamental picture**"]
    if f["available"]:
        lines.append(f"- {f['label']} (score {f['score']:+.0f}).")
        lines += [f"- {name}: {note_}" for name, note_, _ in f["signals"][:5]]
    else:
        lines.append("- No usable fundamental data returned by the source.")
    lines += ["", "**News**", f"- Tone: {n['label']}."]
    lines += [f"- {h['title']}" for h in n["headlines"][:4]]
    lines += ["", "**Statistical range (not a forecast)**"]
    for p in s["projections"]:
        lines.append(
            f"- {p['horizon_days']}d: expected {p['expected_return_pct']:+.1f}% "
            f"(band {p['low_pct']:+.1f}% to {p['high_pct']:+.1f}%)"
        )
    if note:
        lines += ["", f"_{note}_"]
    lines += [
        "",
        "_This is automated analysis for research and education, not "
        "personalised investment advice._",
    ]
    return "\n".join(lines)
