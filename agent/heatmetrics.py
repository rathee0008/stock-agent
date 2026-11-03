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

# Crypto trades every day, so its daily bars are calendar days, not sessions.
SPANS_CRYPTO: dict[str, int | None] = {
    "1 day": 1, "1 week": 7, "1 month": 30, "3 months": 90, "6 months": 180, "YTD": None,
}


def fmt_price(v: float) -> str:
    """Price with enough decimals to be useful for both BTC (77,802.00) and SHIB (0.000012)."""
    v = float(v)
    if abs(v) >= 1:
        return f"{v:,.2f}"
    if v <= 0:
        return "0"
    return f"{v:.{min(12, max(4, 3 - math.floor(math.log10(v))))}f}"   # 4 significant digits for sub-$1 prices


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


FILTER_MODES = ("All", "Gainers only", "Losers only", "Volume spikes (⚡)", "Near 52-week high (▲)",
                "Near 52-week low (▼)")


def apply_filters(df: pd.DataFrame, mode: str = "All", top_n: int | None = None,
                  search: str = "", only: set[str] | None = None) -> pd.DataFrame:
    """Quick filters for the map. ``top_n`` keeps the N largest market caps; ``search`` is a substring
    match on the symbol; ``only`` restricts to a ticker set (e.g. a watchlist)."""
    out = df
    if mode == "Gainers only":
        out = out[out["Change %"] > 0]
    elif mode == "Losers only":
        out = out[out["Change %"] < 0]
    elif mode.startswith("Volume spikes"):
        out = out[out["VolX"].fillna(0) >= VOL_SPIKE]
    elif mode.startswith("Near 52-week high"):
        out = out[out["Pos52"].fillna(-1) >= 100 * (1 - NEAR_52W)]
    elif mode.startswith("Near 52-week low"):
        out = out[out["Pos52"].fillna(101) <= 100 * NEAR_52W]
    if top_n and "MCap" in out.columns and out["MCap"].notna().any():
        out = out.sort_values("MCap", ascending=False, na_position="last").head(int(top_n))
    q = search.strip().upper()
    if q:
        out = out[out["Symbol"].str.upper().str.contains(q, regex=False)]
    if only:
        out = out[out["Symbol"].str.upper().isin({s.upper() for s in only})]
    return out.reset_index(drop=True)


def top_movers(df: pd.DataFrame, n: int = 5) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(top ``n`` gainers, top ``n`` losers) by ``Change %``; losers only include negative moves."""
    s = df.dropna(subset=["Change %"]).sort_values("Change %", ascending=False)
    gain = s[s["Change %"] > 0].head(n)
    lose = s[s["Change %"] < 0].sort_values("Change %").head(n)
    return gain.reset_index(drop=True), lose.reset_index(drop=True)


def momentum_matrix(by_span: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Sector x window table of average % change, rows ordered by the longest window's strength.

    ``by_span`` maps a window label to a frame with ``Sector`` and ``Change %``. Adds a ``Trend``
    column: 'Accelerating' when the short window beats the long one (money flowing in now),
    'Fading' when the reverse, so rotation is visible at a glance.
    """
    cols = {}
    for label, d in by_span.items():
        if d is not None and len(d):
            cols[label] = d.groupby("Sector")["Change %"].mean()
    if not cols:
        return pd.DataFrame()
    m = pd.DataFrame(cols)
    labels = list(m.columns)
    if len(labels) >= 2:
        short, long_ = m[labels[0]], m[labels[-1]]
        m["Momentum"] = [
            "Accelerating" if s > l and s > 0 else "Fading" if s < l and l > 0 else "Weak" if s < 0 else "Steady"
            for s, l in zip(short, long_)
        ]
        m = m.sort_values(labels[-1], ascending=False)
    return m


def rrg(closes: pd.DataFrame, sector_of: dict[str, str], window: int = 20, mom: int = 5,
        trail: int = 5) -> dict[str, pd.DataFrame]:
    """Relative-rotation data per sector (equal-weighted sector index vs the all-stock index).

    ``ratio`` is relative strength vs its own ``window``-day average, scaled so 100 = in line;
    ``momentum`` is how that ratio changed over ``mom`` days (100 = flat). Returns the last
    ``trail`` points per sector with a ``Quadrant`` column: Leading / Weakening / Lagging / Improving.
    """
    c = closes.ffill().dropna(axis=1, how="all")
    cols = [s for s in c.columns if s in sector_of]
    if len(c) < window + mom + trail or len(cols) < 2:
        return {}
    norm = c[cols] / c[cols].bfill().iloc[0]
    market = norm.mean(axis=1)
    out: dict[str, pd.DataFrame] = {}
    for sec in sorted({sector_of[s] for s in cols}):
        members = [s for s in cols if sector_of[s] == sec]
        rs = norm[members].mean(axis=1) / market
        ratio = 100 * rs / rs.rolling(window).mean()
        momentum = 100 + (ratio / ratio.shift(mom) - 1) * 100
        d = pd.DataFrame({"ratio": ratio, "momentum": momentum}).dropna().tail(trail)
        if d.empty:
            continue
        d["Quadrant"] = [
            "Leading" if r >= 100 and m >= 100 else "Weakening" if r >= 100 else "Improving" if m >= 100 else "Lagging"
            for r, m in zip(d["ratio"], d["momentum"])
        ]
        out[sec] = d
    return out
