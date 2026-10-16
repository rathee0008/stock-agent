"""Strategy presets shared by the Screener page, the Top 20 page and the daily job.

A preset is a full filter dict (same keys the Screener's sliders use). ``apply_filters``
applies one to a scored universe frame (the output of ``screener.rank`` for India + US).
"""

from __future__ import annotations

import re

import pandas as pd

_B = {"market": "Both", "min_score": -100, "min_fund": -100, "rsi": [0, 100], "max_pe": 200, "min_roe": -50,
      "min_rev": -100, "min_3m": -100, "min_upside": -100, "analyst": [], "min_cap": 0, "sectors": []}


def _p(**kw) -> dict:
    return {**_B, **kw}


# Strategy presets, built only from columns the scorer already produces.
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


def apply_filters(df: pd.DataFrame, f: dict) -> pd.DataFrame:
    """Filter a scored universe frame with a preset / filter dict; sorted by Score (desc)."""
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
