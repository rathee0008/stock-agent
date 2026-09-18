"""Command-line runner:  python cli.py RELIANCE  [--json]"""

from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

load_dotenv()

from agent.analyze import analyze_stock  # noqa: E402
from agent.llm import synthesize  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description="India/US stock analysis agent")
    ap.add_argument("ticker", help="NSE symbol (RELIANCE, TCS, INFY) or US symbol (AAPL, MSFT)")
    ap.add_argument("--market", choices=["IN", "US"], default="IN", help="IN (default) or US")
    ap.add_argument("--period", default="2y")
    ap.add_argument("--json", action="store_true", help="dump raw analysis as JSON")
    ap.add_argument("--no-llm", action="store_true", help="skip Claude synthesis")
    args = ap.parse_args()

    try:
        a = analyze_stock(args.ticker, period=args.period, market=args.market)
    except (LookupError, ValueError) as exc:
        raise SystemExit(f"error: {exc}")

    if args.json:
        drop = {"history", "intraday", "info"}
        a2 = {k: v for k, v in a.items() if k not in drop}
        a2["technical"] = {k: v for k, v in a2["technical"].items() if k != "frame"}
        print(json.dumps(a2, default=str, indent=2))
        return

    sig = a["signal"]
    print(f"\n{a['name']}  ({a['ticker']})")
    print(f"Price: {a['currency']} {a['price']:,.2f}  ({a['day_change_pct']:+.2f}% today)")
    print(f"Composite: {sig['label']}  score {sig['score']:+.0f}/100  "
          f"confidence {sig['confidence']} ({sig['confidence_pct']}%)")
    print(f"  technical {a['technical']['score']:+.0f} · "
          f"fundamental {a['fundamental']['score']:+.0f} · "
          f"news {a['news']['score']:+.0f}")
    print("-" * 60)

    if args.no_llm:
        from agent.llm import _template
        print(_template(a))
    else:
        text, source = synthesize(a)
        print(text)
        print(f"\n[synthesis: {source}]")


if __name__ == "__main__":
    main()
