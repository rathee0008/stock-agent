"""Pure helpers for the sector heatmaps (no Streamlit, no network) so they can be unit-tested.

Covers: tile weighting (equal / market cap / traded value), the colour scale, colour-blind
palettes, per-stock event flags (volume spike, 52-week high / low) and sector relative strength.
"""

from __future__ import annotations

import math

import pandas as pd

# label -> trading-day lookback (None = year to date, computed from the dates)
SPANS: dict[str, int | None] = {
    "1 day": 1, "1 week": 5, "1 month": 21, "3 months": 63, "6 months": 126, "YTD": None,
}

SIZE_MODES = ("Equal", "Market cap", "Traded value")

# (rising, falling) tile colours. The colour-blind pair avoids red/green entirely.
PALETTES: dict[str, tuple[str, str]] = {
    "Green / red": ("#19D27A", "#FF3B4E"),
    "Blue / orange (colour-blind safe)": ("#3B9DFF", "#FF9F1C"),
}

SCALES = ("Auto", "±2%", "±3%", "±5%", "±10%")

VOL_SPIKE = 2.0      # today's volume vs its 20-day average
NEAR_52W = 0.02      # within 2% of the 52-week high / low


def hex_rgb(h: str) -> list[int]:
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def scale_limit(values: pd.Series, choice: str) -> float:
    """Symmetric colour limit. A fixed choice keeps colours comparable across days and markets."""
    if choice != "Auto":
        return float(choice.replace("±", "").replace("%", ""))
    v = values.dropna().abs()
    return max(2.0, float(v.quantile(0.9))) if len(v) else 2.0


def weights(df: pd.DataFrame, mode: str, floor_ratio: float = 0.25) -> list[float]:
    """One positive weight per row. Missing data falls back to the median so no tile vanishes.

    Cap-weighted maps are dominated by a few giants, so each weight is floored at
    ``floor_ratio`` x the median to keep the smallest names legible.
    """
    n = len(df)
    col = {"Market cap": "MCap", "Traded value": "Value"}.get(mode)
    if mode == "Equal" or col is None or col not in df.columns:
        return [1.0] * n
    s = pd.to_numeric(df[col], errors="coerce")
    s = s.where(s > 0)
    if s.notna().sum() == 0:
        return [1.0] * n
    med = float(s.median())
    s = s.fillna(med).clip(lower=med * floor_ratio)
    return [float(x) for x in s]


def flags(vol_x: float | None, pos52: float | None, near_hi: bool, near_lo: bool) -> str:
    """Short marker string shown on a tile: ⚡ volume spike, ▲ near 52-week high, ▼ near low."""
    out = ""
    if vol_x is not None and not math.isnan(vol_x) and vol_x >= VOL_SPIKE:
        out += "⚡"
    if near_hi:
        out += "▲"
    elif near_lo:
        out += "▼"
    return out


def rel_strength(sec_means: pd.Series, market_avg: float) -> pd.Series:
    """Sector average minus the all-stock average (percentage points)."""
    return sec_means - market_avg


def fmt_cap(v: float | None, cur: str) -> str:
    """Compact market cap: 2.9T / 450B (US) or 19.4L Cr style is avoided - plain T/B/M for both."""
    if v is None or (isinstance(v, float) and math.isnan(v)) or v <= 0:
        return "—"
    for div, suf in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if v >= div:
            return f"{cur}{v / div:.1f}{suf}"
    return f"{cur}{v:,.0f}"


def parse_tickers(text: str) -> set[str]:
    """'reliance, AAPL, tcs.ns' -> {'RELIANCE', 'AAPL', 'TCS'} (exchange suffixes stripped)."""
    out = set()
    for tok in text.replace("\n", ",").split(","):
        t = tok.strip().upper()
        if t.endswith((".NS", ".BO")):
            t = t[:-3]
        if t:
            out.add(t)
    return out


_NEUTRAL = (27, 30, 36)
_BG = (10, 11, 13)


def tile_color(v: float, lim: float, up: str, dn: str, dim: bool = False) -> str:
    """rgb() string matching the live map's colour ramp: neutral grey -> full colour at +/-lim."""
    k = min(abs(v) / (lim or 1.0), 1.0) ** 0.75
    full = hex_rgb(up if v >= 0 else dn)
    rgb = [round(n + (f - n) * k) for n, f in zip(_NEUTRAL, full)]
    if dim:  # fade toward the page background so small moves recede
        rgb = [round(c * 0.4 + b * 0.6) for c, b in zip(rgb, _BG)]
    return f"rgb({rgb[0]},{rgb[1]},{rgb[2]})"
