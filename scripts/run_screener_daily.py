"""Run every Screener preset against the scored universe and save the results as CSV.

Usage:  python scripts/run_screener_daily.py [--tag morning|evening]

Writes (relative to the repo root):
  data/screener/latest/<preset>.csv        overwritten each run
  data/screener/latest/_summary.md         match counts + top 5 per preset
  data/screener/history/<date>_<tag>/...   the same files, kept for history
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import re
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent import screener  # noqa: E402

# Keep in sync with PRESETS in pages/11_🔍_Screener.py.
_B = {"market": "Both", "min_score": -100, "min_fund": -100, "rsi": [0, 100], "max_pe": 200, "min_roe": -50,
      "min_rev": -100, "min_3m": -100, "min_upside": -100, "analyst": [], "min_cap": 0, "sectors": []}


def _p(**kw):
    return {**_B, **kw}


PRESETS = {
    "Quality momentum": _p(min_score=15, min_fund=10, rsi=[45, 72], max_pe=45, min_roe=12),
    "Quality compounders": _p(min_fund=25, min_roe=18, max_pe=60, min_rev=10, min_cap=10),
    "GARP (growth at fair price)": _p(min_fund=10, min_roe=15, max_pe=35, min_rev=12, min_3m=0),
    "Deep value": _p(min_fund=0, max_pe=15, min_roe=10, min_upside=10),
    "Cheap and profitable": _p(min_fund=5, max_pe=18, min_roe=15),
    "Momentum breakout": _p(min_score=30, rsi=[55, 78], min_3m=8),
    "Strong technicals": _p(min_score=30, rsi=[50, 78]),
    "Oversold quality": _p(min_fund=15, rsi=[0, 38], max_pe=40, min_roe=10),
    "Relative strength leaders": _p(min_score=20, min_3m=15, rsi=[50, 80], min_cap=10),
    "Growth acceleration": _p(min_fund=5, min_rev=20, min_3m=0, rsi=[45, 75]),
    "Analyst upside": _p(min_fund=5, min_upside=20, analyst=["buy", "strong_buy"]),
    "Large-cap safety": _p(min_fund=15, min_roe=12, max_pe=40, min_cap=50, rsi=[35, 70]),
}

COLS = ["Market", "Symbol", "Name", "Sector", "Price", "Day %", "3M %", "Score", "Technical", "Fundamental",
        "News", "P/E", "ROE %", "Rev growth %", "RSI", "Analyst", "Upside %"]


def apply_filters(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    """Same rules as the Screener page."""
    out = df.copy()
    if f["market"] == "India":
        out = out[out["Market"] == "IN"]
    elif f["market"] == "US":
        out = out[out["Market"] == "US"]
    out = out[out["Score"] >= f["min_score"]]
    out = out[out["Fundamental"] >= f["min_fund"]]
    lo, hi = f["rsi"]
    out = out[out["RSI"].between(lo, hi) | out["RSI"].isna()]
    if f["max_pe"] < 200:
        out = out[out["P/E"].isna() | (out["P/E"] <= f["max_pe"])]
    if f["min_roe"] > -50:
        out = out[out["ROE %"].isna() | (out["ROE %"] >= f["min_roe"])]
    if f["min_rev"] > -100:
        out = out[out["Rev growth %"].notna() & (out["Rev growth %"] >= f["min_rev"])]
    if f["min_3m"] > -100:
        out = out[out["3M %"].notna() & (out["3M %"] >= f["min_3m"])]
    if f["min_upside"] > -100:
        out = out[out["Upside %"].notna() & (out["Upside %"] >= f["min_upside"])]
    if f["min_cap"] > 0:
        out = out[out["Mkt cap"].notna() & (out["Mkt cap"] >= f["min_cap"] * 1e9)]
    if f["analyst"]:
        out = out[out["Analyst"].isin(f["analyst"])]
    if f["sectors"]:
        out = out[out["Sector"].isin(f["sectors"])]
    return out.sort_values("Score", ascending=False).reset_index(drop=True)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


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

    hist = ROOT / "data" / "screener" / "history" / f"{stamp}_{tag}"
    if hist.exists():
        shutil.rmtree(hist)
    shutil.copytree(latest, hist)


if __name__ == "__main__":
    main()
