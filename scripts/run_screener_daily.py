"""Run every Screener preset against the scored universe and save the results as CSV.

Usage:  python scripts/run_screener_daily.py [--tag morning|evening]

Writes (relative to the repo root):
  data/screener/latest/<preset>.csv        overwritten each run
  data/screener/latest/_summary.md         match counts + top 5 per preset
  data/screener/history/<date>_<tag>/...   the same files, kept for history
  data/screener/latest/top20.csv           the default Top 20 (best 20 overall)
  data/screener/top20_history.csv          one row per pick per run; the Top 20 page reads it
                                           for "days in top 20", rank trend and past-pick results
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import picks_extra, screener  # noqa: E402
from agent.presets import PRESETS, apply_filters, slug  # noqa: E402

COLS = ["Market", "Symbol", "Name", "Sector", "Price", "Day %", "3M %", "Score", "Technical", "Fundamental",
        "News", "P/E", "ROE %", "Rev growth %", "RSI", "Analyst", "Upside %"]


def universe() -> pd.DataFrame:
    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        fi, fu = ex.submit(screener.rank, "IN"), ex.submit(screener.rank, "US")
        return pd.concat([fi.result(), fu.result()], ignore_index=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="run")
    tag = ap.parse_args().tag
    ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    stamp = ist.strftime("%Y-%m-%d")

    df = universe()
    if df.empty:
        sys.exit("Universe came back empty (data source down?); nothing written.")

    latest = ROOT / "data" / "screener" / "latest"
    if latest.exists():
        shutil.rmtree(latest)
    latest.mkdir(parents=True)

    lines = [f"# Screener results — {stamp} {tag} (IST)", "", f"Universe scored: {len(df)} stocks. Not investment advice.", "",
             "| Preset | Matches | Top 5 by score |", "|---|---|---|"]
    for name, f in PRESETS.items():
        out = apply_filters(df, f)
        out[[c for c in COLS if c in out.columns]].to_csv(latest / f"{slug(name)}.csv", index=False, float_format="%.2f")
        top = ", ".join(out["Symbol"].head(5)) or "—"
        lines.append(f"| {name} | {len(out)} | {top} |")
        print(f"{name}: {len(out)} matches")
    (latest / "_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Default Top 20 (best 20 overall, default weights): saved for the page's pick history.
    top20 = df.sort_values("Score", ascending=False).head(20).reset_index(drop=True)
    top20[[c for c in COLS if c in top20.columns]].to_csv(latest / "top20.csv", index=False, float_format="%.2f")
    picks_extra.append_top20(ROOT / "data" / "screener" / "top20_history.csv", stamp, tag, top20)

    hist = ROOT / "data" / "screener" / "history" / f"{stamp}_{tag}"
    if hist.exists():
        shutil.rmtree(hist)
    shutil.copytree(latest, hist)


if __name__ == "__main__":
    main()
