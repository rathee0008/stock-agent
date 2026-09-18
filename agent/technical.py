"""Technical analysis — indicators plus a bounded directional score."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0.0, np.nan)
    return 100.0 - 100.0 / (1.0 + rs)


def _macd(close: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    line = ema12 - ema26
    signal = line.ewm(span=9, adjust=False).mean()
    return line, signal, line - signal


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hl = df["High"] - df["Low"]
    hc = (df["High"] - df["Close"].shift()).abs()
    lc = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


def _swing_levels(df: pd.DataFrame, window: int = 10, lookback: int = 120) -> dict:
    recent = df.tail(lookback)
    highs = recent["High"]
    lows = recent["Low"]
    is_high = highs == highs.rolling(window * 2 + 1, center=True).max()
    is_low = lows == lows.rolling(window * 2 + 1, center=True).min()
    res = sorted(highs[is_high].dropna().tolist())
    sup = sorted(lows[is_low].dropna().tolist())
    price = float(df["Close"].iloc[-1])
    resistance = next((r for r in res if r > price), max(res) if res else None)
    support = next((s for s in reversed(sup) if s < price), min(sup) if sup else None)
    return {"support": support, "resistance": resistance}


@dataclass
class TechnicalResult:
    score: float                       # -100 .. +100
    label: str
    price: float
    indicators: dict[str, Any] = field(default_factory=dict)
    signals: list[tuple[str, str, float]] = field(default_factory=list)  # (name, note, contribution)
    frame: pd.DataFrame | None = None


def _label(score: float) -> str:
    if score >= 45:
        return "Strongly Bullish"
    if score >= 15:
        return "Bullish"
    if score > -15:
        return "Neutral"
    if score > -45:
        return "Bearish"
    return "Strongly Bearish"


def analyze(history: pd.DataFrame) -> TechnicalResult:
    df = history.copy()
    close = df["Close"]

    df["SMA20"] = close.rolling(20).mean()
    df["SMA50"] = close.rolling(50).mean()
    df["SMA200"] = close.rolling(200).mean()
    df["EMA20"] = close.ewm(span=20, adjust=False).mean()
    df["RSI"] = _rsi(close)
    df["MACD"], df["MACD_SIGNAL"], df["MACD_HIST"] = _macd(close)
    mid = close.rolling(20).mean()
    sd = close.rolling(20).std()
    df["BB_UP"], df["BB_LOW"] = mid + 2 * sd, mid - 2 * sd
    df["ATR"] = _atr(df)
    df["VOL_SMA20"] = df["Volume"].rolling(20).mean()

    last = df.iloc[-1]
    price = float(last["Close"])
    signals: list[tuple[str, str, float]] = []

    def add(name: str, note: str, pts: float) -> None:
        signals.append((name, note, pts))

    # --- Trend: price vs moving averages -----------------------------------
    if not np.isnan(last["SMA50"]):
        if price > last["SMA50"]:
            add("Price vs 50-DMA", "above 50-day average", 12)
        else:
            add("Price vs 50-DMA", "below 50-day average", -12)
    if not np.isnan(last["SMA200"]):
        if price > last["SMA200"]:
            add("Price vs 200-DMA", "above 200-day average (long-term uptrend)", 16)
        else:
            add("Price vs 200-DMA", "below 200-day average (long-term downtrend)", -16)
    if not np.isnan(last["SMA50"]) and not np.isnan(last["SMA200"]):
        prev = df.iloc[-20]
        if last["SMA50"] > last["SMA200"] and prev["SMA50"] <= prev["SMA200"]:
            add("Golden cross", "50-DMA crossed above 200-DMA recently", 12)
        elif last["SMA50"] < last["SMA200"] and prev["SMA50"] >= prev["SMA200"]:
            add("Death cross", "50-DMA crossed below 200-DMA recently", -12)

    # --- RSI --------------------------------------------------------------
    rsi = float(last["RSI"]) if not np.isnan(last["RSI"]) else 50.0
    if rsi >= 70:
        add("RSI", f"overbought ({rsi:.0f})", -10)
    elif rsi <= 30:
        add("RSI", f"oversold ({rsi:.0f}) — mean-reversion setup", 10)
    elif rsi >= 55:
        add("RSI", f"bullish momentum ({rsi:.0f})", 5)
    elif rsi <= 45:
        add("RSI", f"weak momentum ({rsi:.0f})", -5)

    # --- MACD ------------------------------------------------------------
    if not np.isnan(last["MACD_HIST"]):
        prev_hist = df["MACD_HIST"].iloc[-2]
        if last["MACD_HIST"] > 0 and prev_hist <= 0:
            add("MACD", "bullish crossover", 12)
        elif last["MACD_HIST"] < 0 and prev_hist >= 0:
            add("MACD", "bearish crossover", -12)
        elif last["MACD_HIST"] > 0:
            add("MACD", "above signal line", 6)
        else:
            add("MACD", "below signal line", -6)

    # --- Bollinger position --------------------------------------------
    if not np.isnan(last["BB_UP"]):
        if price > last["BB_UP"]:
            add("Bollinger", "above upper band (stretched)", -6)
        elif price < last["BB_LOW"]:
            add("Bollinger", "below lower band (stretched down)", 6)

    # --- Momentum (returns) ------------------------------------------
    for days, w, name in ((21, 6, "1-month"), (63, 8, "3-month"), (126, 6, "6-month")):
        if len(close) > days:
            ret = (price / close.iloc[-1 - days] - 1) * 100
            add(f"{name} return", f"{ret:+.1f}%", float(np.clip(ret / 3.0, -w, w)))

    # --- Volume confirmation --------------------------------------
    if not np.isnan(last["VOL_SMA20"]) and last["VOL_SMA20"] > 0:
        vr = last["Volume"] / last["VOL_SMA20"]
        chg = price - float(df["Close"].iloc[-2])
        if vr > 1.5 and chg > 0:
            add("Volume", f"{vr:.1f}x average on an up day", 8)
        elif vr > 1.5 and chg < 0:
            add("Volume", f"{vr:.1f}x average on a down day", -8)

    # --- 52-week range position -----------------------------------
    yr = close.tail(252)
    hi, lo = float(yr.max()), float(yr.min())
    if hi > lo:
        pos = (price - lo) / (hi - lo)
        if pos > 0.95:
            add("52-week range", "at/near 52-week high", 6)
        elif pos < 0.05:
            add("52-week range", "at/near 52-week low", -6)

    raw = sum(pts for _, _, pts in signals)
    score = float(np.clip(raw, -100, 100))

    levels = _swing_levels(df)
    atr = float(last["ATR"]) if not np.isnan(last["ATR"]) else float(close.std())

    indicators = {
        "rsi": rsi,
        "macd": float(last["MACD"]) if not np.isnan(last["MACD"]) else None,
        "macd_hist": float(last["MACD_HIST"]) if not np.isnan(last["MACD_HIST"]) else None,
        "sma20": _safe(last["SMA20"]),
        "sma50": _safe(last["SMA50"]),
        "sma200": _safe(last["SMA200"]),
        "atr": atr,
        "atr_pct": atr / price * 100 if price else None,
        "bb_upper": _safe(last["BB_UP"]),
        "bb_lower": _safe(last["BB_LOW"]),
        "week52_high": hi,
        "week52_low": lo,
        "support": levels["support"],
        "resistance": levels["resistance"],
        "volume_ratio": _safe(last["Volume"] / last["VOL_SMA20"])
        if not np.isnan(last["VOL_SMA20"]) and last["VOL_SMA20"]
        else None,
    }

    return TechnicalResult(
        score=score,
        label=_label(score),
        price=price,
        indicators=indicators,
        signals=sorted(signals, key=lambda s: -abs(s[2])),
        frame=df,
    )


def _safe(v: Any) -> float | None:
    try:
        f = float(v)
        return None if np.isnan(f) else f
    except (TypeError, ValueError):
        return None
