"""Daily pre-market / post-market brief, and the chat-with-your-data context builder.

Facts are gathered once into a small dict (``build_context``); Claude (or a template when no
key is set) turns it into prose. The model only sees the facts we pass, never raw web text
beyond headlines we fetched.
"""

from __future__ import annotations

import datetime as _dt
import json

import pandas as pd

from . import bigmoney, config, log, market as _market, screener
from . import technical as _tech
from .data import _in_market_state, _us_market_state


def session_kind(mkt: str) -> str:
    """'pre' before/at the open, 'post' once the session is over."""
    st = _us_market_state() if mkt == "US" else _in_market_state()
    return "post" if st in ("POST", "REGULAR") or st == "CLOSED" and _dt.datetime.now(_dt.UTC).hour >= 10 else "pre"


def watch_snapshot(symbols: list[str]) -> list[dict]:
    """RSI / trend / day move for the user's own symbols (batched Yahoo call)."""
    if not symbols:
        return []
    hist = screener.batch_history(symbols, period="1y", min_rows=20)
    out = []
    for s in symbols:
        df = hist.get(s)
        if df is None or len(df) < 2:
            continue
        row = {"symbol": s.replace(".NS", ""), "price": float(df["Close"].iloc[-1]),
               "day_pct": float(df["Close"].iloc[-1] / df["Close"].iloc[-2] - 1) * 100}
        if len(df) >= 60:
            try:
                r = _tech.analyze(df)
                row.update(rsi=round(r.indicators.get("rsi") or 0), trend=r.label, score=round(r.score))
            except Exception as exc:  # noqa: BLE001
                log.record("brief:tech", exc)
        out.append(row)
    return out


def _headlines(mkt: str) -> list[str]:
    try:
        df = bigmoney.deal_headlines(mkt, 2, 6)
        return df["Headline"].tolist() if df is not None and not df.empty and "Headline" in df else []
    except Exception as exc:  # noqa: BLE001
        log.record("brief:deals", exc)
        return []


def build_context(mkt: str = "IN", watch: list[str] | None = None, holdings: dict | None = None) -> dict:
    full = screener.movers_frame(mkt)
    g, l = screener.split_movers(full, 5)
    sec = screener.sector_averages(full)
    ctx = {
        "market": mkt,
        "as_of": _dt.datetime.now(_dt.UTC).isoformat(timespec="minutes"),
        "indices": _market.index_quotes(),
        "breadth": {"advancers": int((full["Change %"] > 0).sum()), "decliners": int((full["Change %"] < 0).sum())},
        "top_gainers": g[["Symbol", "Change %", "Vol vs 5d avg"]].round(2).to_dict("records"),
        "top_losers": l[["Symbol", "Change %", "Vol vs 5d avg"]].round(2).to_dict("records"),
        "sectors": {k: round(v, 2) for k, v in sorted(sec.items(), key=lambda kv: -kv[1])},
        "deal_headlines": _headlines(mkt),
        "watchlist": watch_snapshot(watch or []),
    }
    if holdings:
        hs = watch_snapshot(list(holdings))
        for h in hs:
            q, c = holdings.get(h["symbol"], holdings.get(h["symbol"] + ".NS", (0, 0)))
            if q and c:
                h["pnl_pct"] = round((h["price"] / c - 1) * 100, 1)
        ctx["holdings"] = hs
    return ctx


_SYSTEM = """You write a concise market brief for one retail investor, using ONLY the JSON facts given.
Sections: 1) Market in one paragraph (indices, breadth, leading/lagging sectors). 2) Movers worth knowing (why, if the
facts say; otherwise say unclear). 3) Your watchlist and holdings (only if present: flag RSI>70/<30, big moves, big
P&L swings). 4) What to watch next session. Under 300 words, plain language, no price targets, no buy/sell calls.
End with one line: research only, not investment advice."""


def template_brief(ctx: dict, kind: str = "post") -> str:
    ix = ", ".join(f"{q['name']} {q['chg_pct']:+.2f}%" for q in ctx["indices"][:4]) or "index data unavailable"
    b = ctx["breadth"]
    secs = list(ctx["sectors"].items())
    lead = ", ".join(f"{k} {v:+.1f}%" for k, v in secs[:2])
    lag = ", ".join(f"{k} {v:+.1f}%" for k, v in secs[-2:])
    lines = [f"### {'Post-market' if kind == 'post' else 'Pre-market'} brief · {ctx['market']}",
             f"**Market:** {ix}. Breadth {b['advancers']} up / {b['decliners']} down. Leading: {lead}. Lagging: {lag}.", "",
             "**Movers**"]
    for r in ctx["top_gainers"][:3]:
        lines.append(f"- ▲ {r['Symbol'].replace('.NS', '')} {r['Change %']:+.2f}% (volume {r['Vol vs 5d avg']:.1f}× avg)")
    for r in ctx["top_losers"][:3]:
        lines.append(f"- ▼ {r['Symbol'].replace('.NS', '')} {r['Change %']:+.2f}% (volume {r['Vol vs 5d avg']:.1f}× avg)")
    for title, key in (("Your watchlist", "watchlist"), ("Your holdings", "holdings")):
        rows = ctx.get(key) or []
        if rows:
            lines += ["", f"**{title}**"]
            for w in rows:
                flag = " · RSI overbought" if w.get("rsi", 0) >= 70 else " · RSI oversold" if 0 < w.get("rsi", 0) <= 30 else ""
                pnl = f" · P&L {w['pnl_pct']:+.1f}%" if "pnl_pct" in w else ""
                lines.append(f"- {w['symbol']} {w['day_pct']:+.2f}%{pnl}{flag}")
    if ctx.get("deal_headlines"):
        lines += ["", "**Deal headlines**"] + [f"- {h}" for h in ctx["deal_headlines"][:4]]
    lines += ["", "_Rule-based summary. Research only, not investment advice._"]
    return "\n".join(lines)


def generate(ctx: dict, kind: str = "post", use_llm: bool = True) -> tuple[str, str]:
    key = config.get("ANTHROPIC_API_KEY")
    if use_llm and key:
        try:
            import anthropic

            msg = anthropic.Anthropic(api_key=key).messages.create(
                model=config.get("STOCK_AGENT_MODEL", "claude-sonnet-5"), max_tokens=900, system=_SYSTEM,
                messages=[{"role": "user", "content": f"Write the {kind}-market brief.\n\n" + json.dumps(ctx, default=str)}])
            text = "".join(b.text for b in msg.content if b.type == "text").strip()
            if text:
                return text, "claude"
        except Exception as exc:  # noqa: BLE001
            log.record("claude:brief", exc)
    return template_brief(ctx, kind), "template"
