"""Alert rules, evaluation and delivery (Telegram / email).

Rules live in ``alerts.json`` at the repo root (edit it on the Alerts page or by hand) and
are evaluated by ``scripts/run_alerts.py`` — run it from the GitHub Actions schedule in
``.github/workflows/alerts.yml`` so alerts fire even when nobody has the dashboard open.

Rule types
  price_above / price_below   value = price
  pct_move                    value = |day change %| threshold
  rsi_above / rsi_below       value = RSI level
  volume_spike                value = multiple of the 20-day average volume
  score_above / score_below   value = composite score (-100..100)
  composite_flip              fires when the composite label changes (no value)

``evaluate`` is a pure function over snapshots, so it is unit-tested without network.
"""

from __future__ import annotations

import datetime as _dt
import json
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable

import requests

from . import config, log

RULE_TYPES = ["price_above", "price_below", "pct_move", "rsi_above", "rsi_below",
              "volume_spike", "score_above", "score_below", "composite_flip"]
ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "alerts.json"
STATE_PATH = ROOT / ".cache" / "alert_state.json"
COOLDOWN_H = 20          # a rule that fired will not fire again for this long


@dataclass
class Rule:
    symbol: str
    market: str
    type: str
    value: float | None = None
    note: str = ""

    @property
    def key(self) -> str:
        return f"{self.market}:{self.symbol}:{self.type}:{self.value}"

    @staticmethod
    def from_dict(d: dict) -> "Rule":
        v = d.get("value")
        return Rule(symbol=str(d["symbol"]).upper().strip(), market=str(d.get("market", "IN")).upper(),
                    type=d["type"], value=None if v in (None, "") else float(v), note=str(d.get("note", "")))


def load_config(path: Path = CONFIG_PATH) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return {"rules": [], "daily_brief": {"enabled": False, "markets": ["IN"]}, "watchlist": []}


def load_state(path: Path = STATE_PATH) -> dict:
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return {"fired": {}, "labels": {}}


def save_state(state: dict, path: Path = STATE_PATH) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state))
    except Exception as exc:  # noqa: BLE001
        log.record("alerts:state", exc)


def _check(rule: Rule, snap: dict, prev_label: str | None) -> str | None:
    v = rule.value
    price, day, rsi = snap.get("price"), snap.get("day_pct"), snap.get("rsi")
    vol, score, label = snap.get("vol_ratio"), snap.get("score"), snap.get("label")
    t = rule.type
    if t == "price_above" and price is not None and v is not None and price >= v:
        return f"price {price:,.2f} crossed above {v:,.2f}"
    if t == "price_below" and price is not None and v is not None and price <= v:
        return f"price {price:,.2f} fell below {v:,.2f}"
    if t == "pct_move" and day is not None and v is not None and abs(day) >= v:
        return f"moved {day:+.2f}% today (limit ±{v:g}%)"
    if t == "rsi_above" and rsi is not None and v is not None and rsi >= v:
        return f"RSI {rsi:.0f} is above {v:g} (overbought)"
    if t == "rsi_below" and rsi is not None and v is not None and rsi <= v:
        return f"RSI {rsi:.0f} is below {v:g} (oversold)"
    if t == "volume_spike" and vol is not None and v is not None and vol >= v:
        return f"volume {vol:.1f}× its 20-day average"
    if t == "score_above" and score is not None and v is not None and score >= v:
        return f"composite score {score:+.0f} is above {v:g}"
    if t == "score_below" and score is not None and v is not None and score <= v:
        return f"composite score {score:+.0f} is below {v:g}"
    if t == "composite_flip" and label and prev_label and label != prev_label:
        return f"composite call changed: {prev_label} → {label}"
    return None


def evaluate(rules: list[Rule], snapshots: dict[str, dict], state: dict | None = None,
             now: _dt.datetime | None = None) -> tuple[list[dict], dict]:
    """Return ``(events, new_state)``. ``snapshots`` is keyed ``"MARKET:SYMBOL"``."""
    now = now or _dt.datetime.now(_dt.UTC)
    state = json.loads(json.dumps(state or {"fired": {}, "labels": {}}))
    events: list[dict] = []
    for r in rules:
        sk = f"{r.market}:{r.symbol}"
        snap = snapshots.get(sk)
        if not snap:
            continue
        msg = _check(r, snap, state["labels"].get(sk))
        if msg:
            last = state["fired"].get(r.key)
            fresh = last is None or (now - _dt.datetime.fromisoformat(last)).total_seconds() > COOLDOWN_H * 3600
            if fresh or r.type == "composite_flip":
                events.append({"rule": r.key, "symbol": r.symbol, "market": r.market, "message": msg, "note": r.note,
                               "price": snap.get("price")})
                state["fired"][r.key] = now.isoformat()
    for sk, snap in snapshots.items():          # remember labels after checking flips
        if snap.get("label"):
            state["labels"][sk] = snap["label"]
    return events, state


def snapshot(symbol: str, market: str = "IN") -> dict[str, Any]:
    """Compact numbers an alert rule can test. Uses the full analysis engine."""
    from .analyze import analyze_stock

    a = analyze_stock(symbol, market=market)
    ind = a["technical"]["indicators"]
    return {"price": a["price"], "day_pct": a["day_change_pct"], "rsi": ind.get("rsi"),
            "vol_ratio": ind.get("volume_ratio"), "score": a["signal"]["score"], "label": a["signal"]["label"],
            "currency": a["currency"], "name": a["name"]}


def snapshots_for(rules: list[Rule], fn: Callable[[str, str], dict] = snapshot) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for r in rules:
        sk = f"{r.market}:{r.symbol}"
        if sk in out:
            continue
        try:
            out[sk] = fn(r.symbol, r.market)
        except Exception as exc:  # noqa: BLE001 - one bad symbol must not stop the run
            log.record(f"alerts:{sk}", exc)
    return out


def format_events(events: list[dict]) -> str:
    lines = ["Stock Agent alerts"]
    for e in events:
        tail = f" — {e['note']}" if e.get("note") else ""
        lines.append(f"• {e['symbol']} ({e['market']}): {e['message']}{tail}")
    lines.append("Research alert, not investment advice.")
    return "\n".join(lines)


# ------------------------------------------------------------------ delivery
def send_telegram(text: str) -> bool:
    token, chat = config.get("TELEGRAM_BOT_TOKEN"), config.get("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    try:
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                          data={"chat_id": chat, "text": text[:4000], "disable_web_page_preview": "true"}, timeout=15)
        r.raise_for_status()
        return True
    except Exception as exc:  # noqa: BLE001
        log.record("alerts:telegram", exc)
        return False


def send_email(subject: str, body: str) -> bool:
    host, user, pw = config.get("SMTP_HOST"), config.get("SMTP_USER"), config.get("SMTP_PASSWORD")
    to = config.get("ALERT_EMAIL_TO") or user
    if not (host and user and pw and to):
        return False
    try:
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, user, to
        msg.set_content(body)
        with smtplib.SMTP(host, int(config.get("SMTP_PORT", "587")), timeout=20) as s:
            s.starttls()
            s.login(user, pw)
            s.send_message(msg)
        return True
    except Exception as exc:  # noqa: BLE001
        log.record("alerts:email", exc)
        return False


def deliver(subject: str, body: str) -> dict[str, bool]:
    return {"telegram": send_telegram(f"{subject}\n\n{body}"), "email": send_email(subject, body)}


def channels_configured() -> dict[str, bool]:
    return {"telegram": bool(config.get("TELEGRAM_BOT_TOKEN") and config.get("TELEGRAM_CHAT_ID")),
            "email": bool(config.get("SMTP_HOST") and config.get("SMTP_USER") and config.get("SMTP_PASSWORD"))}
