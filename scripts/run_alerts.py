#!/usr/bin/env python3
"""Evaluate alert rules / send the daily brief. Designed for cron or GitHub Actions.

    python scripts/run_alerts.py                 # check rules, send alerts if any fired
    python scripts/run_alerts.py --dry-run       # print what would be sent
    python scripts/run_alerts.py --brief post    # send the post-market brief (IN by default)
    python scripts/run_alerts.py --test          # send a test message to every configured channel
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import alerts, briefing, universe  # noqa: E402


def _watchlist_for(m: str, wl: list[str]) -> list[str]:
    out = []
    for s in wl:
        u = s.upper()
        is_in = u.endswith((".NS", ".BO")) or u in universe.IN
        if (m == "IN") == is_in:
            out.append(u if (m == "US" or u.endswith((".NS", ".BO"))) else f"{u}.NS")
    return out



def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--brief", choices=["pre", "post"])
    ap.add_argument("--market", action="append", help="IN or US (repeatable); default from alerts.json")
    ap.add_argument("--test", action="store_true")
    args = ap.parse_args()

    if args.test:
        print("channels:", alerts.channels_configured())
        print(alerts.deliver("Stock Agent test", "If you can read this, alerts are wired up."))
        return 0

    cfg = alerts.load_config()
    if args.brief:
        markets = args.market or cfg.get("daily_brief", {}).get("markets", ["IN"])
        for m in markets:
            watch = _watchlist_for(m, cfg.get("watchlist", []))
            ctx = briefing.build_context(m, watch=watch)
            text, src = briefing.generate(ctx, args.brief)
            print(text)
            if not args.dry_run:
                print(alerts.deliver(f"{m} {args.brief}-market brief", text))
        return 0

    rules = [alerts.Rule.from_dict(r) for r in cfg.get("rules", [])]
    if not rules:
        print("No rules in alerts.json")
        return 0
    snaps = alerts.snapshots_for(rules)
    events, state = alerts.evaluate(rules, snaps, alerts.load_state())
    if events:
        body = alerts.format_events(events)
        print(body)
        if not args.dry_run:
            print(alerts.deliver("Stock Agent alert", body))
    else:
        print(f"Checked {len(rules)} rules on {len(snaps)} symbols: nothing fired.")
    if not args.dry_run:
        alerts.save_state(state)
    return 0


if __name__ == "__main__":
    sys.exit(main())
