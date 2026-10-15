"""'Ask the agent': answer questions using the app's own data as context.

Flow: pull ticker mentions out of the question -> run the real analysis engine for up to
two of them (so numbers match the Analyze page) -> add the market snapshot -> ask Claude to
answer using only that context. Without an API key the agent still returns the rule-based
analysis for the mentioned stock instead of failing.
"""

from __future__ import annotations

import json
import re

from . import config, log, universe
from .analyze import analyze_stock

_KNOWN_IN = set(universe.IN)
_KNOWN_US = set(universe.US)
_STOP = {"WHY", "WHAT", "HOW", "IS", "THE", "A", "AN", "AND", "OR", "TO", "OF", "IN", "ON", "AT", "FOR", "DOWN", "UP",
         "TODAY", "ARE", "DID", "DO", "BUY", "SELL", "HOLD", "I", "IT", "MY", "ME", "WITH", "VS", "NSE", "BSE", "US", "RSI",
         "PE", "ETF", "SIP", "CAN", "WILL", "NOW", "THIS", "THAT", "WEEK", "MONTH", "OK", "ABOUT", "TELL"}


def extract_symbols(question: str, limit: int = 2) -> list[tuple[str, str]]:
    """Find (symbol, market) mentions: known universe names, $TICKER, or ALLCAPS words."""
    found: list[tuple[str, str]] = []
    for tok in re.findall(r"[$]?[A-Za-z][A-Za-z&\-]{0,14}", question):
        raw = tok.lstrip("$").upper()
        if raw in _STOP:
            continue
        explicit = tok.startswith("$") or tok.isupper()
        if raw in _KNOWN_IN:
            cand = (raw, "IN")
        elif raw in _KNOWN_US:
            cand = (raw, "US")
        elif explicit and len(raw) >= 2:
            cand = (raw, "IN")      # caller may retry as US if the lookup fails
        else:
            continue
        if cand not in found:
            found.append(cand)
        if len(found) >= limit:
            break
    return found


def _compact(a: dict) -> dict:
    s = a["signal"]
    return {
        "symbol": a["ticker"], "name": a["name"], "price": round(a["price"], 2), "currency": a["currency"],
        "day_change_pct": round(a["day_change_pct"], 2),
        "composite": {"label": s["label"], "score": round(s["score"]), "confidence": s["confidence"],
                      "conflict": s.get("conflict_note") or None, "history": s.get("calibration")},
        "technical": {"score": round(a["technical"]["score"]), "rsi": a["technical"]["indicators"].get("rsi"),
                      "support": a["technical"]["indicators"].get("support"),
                      "resistance": a["technical"]["indicators"].get("resistance")},
        "fundamental": {"score": round(a["fundamental"]["score"]), "metrics": a["fundamental"]["metrics"]},
        "news": [h["title"] for h in a["news"]["headlines"][:6]],
        "top_drivers": [f"{d['name']}: {d['note']} ({d['weighted']:+.1f})" for d in s.get("drivers", [])[:6]],
    }


def gather(question: str, extra: dict | None = None) -> tuple[dict, list[str]]:
    ctx: dict = {"stocks": [], **(extra or {})}
    notes: list[str] = []
    for sym, mkt in extract_symbols(question):
        for m in ([mkt] if mkt == "US" or sym in _KNOWN_IN else ["IN", "US"]):
            try:
                ctx["stocks"].append(_compact(analyze_stock(sym, market=m)))
                break
            except Exception as exc:  # noqa: BLE001
                log.record(f"chat:{sym}", exc, "debug")
        else:
            notes.append(f"Could not fetch data for {sym}.")
    return ctx, notes


_SYSTEM = """You are the Q&A assistant inside a stock research dashboard for an Indian retail investor.
Answer using ONLY the JSON context provided (computed analysis, drivers, headlines, market snapshot). If the context
does not contain the answer, say what is missing instead of guessing. Never invent prices, targets or news. Explain
the reasoning behind the composite call using the listed drivers. Be concise (under 220 words), plain language. You
may discuss what the data suggests but must not tell the user to buy or sell; end any stock answer with: Research
only, not investment advice."""


def answer(question: str, history: list[dict] | None = None, extra: dict | None = None) -> tuple[str, str]:
    ctx, notes = gather(question, extra)
    key = config.get("ANTHROPIC_API_KEY")
    if key:
        try:
            import anthropic

            msgs = [m for m in (history or [])[-6:] if m["role"] in ("user", "assistant")]
            msgs.append({"role": "user", "content": f"Context:\n{json.dumps(ctx, default=str)}\n\nQuestion: {question}"})
            r = anthropic.Anthropic(api_key=key).messages.create(
                model=config.get("STOCK_AGENT_MODEL", "claude-sonnet-5"), max_tokens=700, system=_SYSTEM, messages=msgs)
            text = "".join(b.text for b in r.content if b.type == "text").strip()
            if text:
                return text + ("\n\n" + " ".join(notes) if notes else ""), "claude"
        except Exception as exc:  # noqa: BLE001
            log.record("claude:chat", exc)
    return _offline(ctx, notes), "template"


def _offline(ctx: dict, notes: list[str]) -> str:
    if not ctx["stocks"]:
        return ("Add an Anthropic API key to enable free-form answers. I can still explain a stock if you mention "
                "its symbol, e.g. “Why is RELIANCE rated Hold?”. " + " ".join(notes))
    out = []
    for s in ctx["stocks"]:
        c = s["composite"]
        out.append(f"**{s['name']} ({s['symbol']})** — {c['label']}, score {c['score']:+d}, confidence {c['confidence']}. "
                   f"Price {s['currency']} {s['price']:,} ({s['day_change_pct']:+.2f}% today).")
        if c.get("conflict"):
            out.append(f"_{c['conflict']}_")
        out += [f"- {d}" for d in s["top_drivers"][:5]]
        if c.get("history"):
            out.append(c["history"])
    out.append("_Rule-based answer (no Anthropic key set). Research only, not investment advice._")
    return "\n".join(out)
