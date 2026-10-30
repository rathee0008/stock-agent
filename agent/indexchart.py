"""Built-in index chart: candlesticks plus a full indicator set, computed locally.

Why this exists: TradingView's free embed refuses NSE and most index symbols (NIFTY,
BANKNIFTY, IXIC, SPX, ...) with "only available on TradingView", so those cannot rely
on it. This module draws the same kind of chart from Yahoo data we already fetch
(~15 min delayed), with every indicator computed here in pandas.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from . import theme as T

# ---------------------------------------------------------------------------
# indicators (all take an OHLCV frame and return Series / DataFrame)
# ---------------------------------------------------------------------------


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def bollinger(s: pd.Series, n: int = 20, k: float = 2.0) -> pd.DataFrame:
    mid = s.rolling(n).mean()
    sd = s.rolling(n).std(ddof=0)
    return pd.DataFrame({"mid": mid, "upper": mid + k * sd, "lower": mid - k * sd})


def rsi(s: pd.Series, n: int = 14) -> pd.Series:
    d = s.diff()
    up = d.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    out = 100 - 100 / (1 + up / dn.replace(0, np.nan))
    return out.where(~((dn == 0) & (up > 0)), 100.0)  # only gains in the window -> RSI 100


def macd(s: pd.Series, fast: int = 12, slow: int = 26, sig: int = 9) -> pd.DataFrame:
    line = ema(s, fast) - ema(s, slow)
    signal = line.ewm(span=sig, adjust=False).mean()
    return pd.DataFrame({"macd": line, "signal": signal, "hist": line - signal})


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["Close"].shift()
    return pd.concat([df["High"] - df["Low"], (df["High"] - pc).abs(), (df["Low"] - pc).abs()],
                     axis=1).max(axis=1)


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / n, adjust=False).mean()


def stochastic(df: pd.DataFrame, n: int = 14, d: int = 3) -> pd.DataFrame:
    lo, hi = df["Low"].rolling(n).min(), df["High"].rolling(n).max()
    k = 100 * (df["Close"] - lo) / (hi - lo).replace(0, np.nan)
    return pd.DataFrame({"k": k, "d": k.rolling(d).mean()})


def adx(df: pd.DataFrame, n: int = 14) -> pd.DataFrame:
    up, dn = df["High"].diff(), -df["Low"].diff()
    plus = pd.Series(np.where((up > dn) & (up > 0), up, 0.0), index=df.index)
    minus = pd.Series(np.where((dn > up) & (dn > 0), dn, 0.0), index=df.index)
    tr = true_range(df).ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * plus.ewm(alpha=1 / n, adjust=False).mean() / tr
    mdi = 100 * minus.ewm(alpha=1 / n, adjust=False).mean() / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return pd.DataFrame({"adx": dx.ewm(alpha=1 / n, adjust=False).mean(), "+di": pdi, "-di": mdi})


def cci(df: pd.DataFrame, n: int = 20) -> pd.Series:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    mad = tp.rolling(n).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
    return (tp - tp.rolling(n).mean()) / (0.015 * mad.replace(0, np.nan))


def williams_r(df: pd.DataFrame, n: int = 14) -> pd.Series:
    lo, hi = df["Low"].rolling(n).min(), df["High"].rolling(n).max()
    return -100 * (hi - df["Close"]) / (hi - lo).replace(0, np.nan)


def obv(df: pd.DataFrame) -> pd.Series:
    return (np.sign(df["Close"].diff()).fillna(0) * df["Volume"]).cumsum()


def mfi(df: pd.DataFrame, n: int = 14) -> pd.Series:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    flow = tp * df["Volume"]
    pos = flow.where(tp > tp.shift(), 0.0).rolling(n).sum()
    neg = flow.where(tp < tp.shift(), 0.0).rolling(n).sum()
    return 100 - 100 / (1 + pos / neg.replace(0, np.nan))


def vwap(df: pd.DataFrame) -> pd.Series:
    """Session VWAP: resets each calendar day. Needs per-bar volume (NaN without it)."""
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    day = df.index.normalize() if hasattr(df.index, "normalize") else df.index
    pv = (tp * df["Volume"]).groupby(day).cumsum()
    v = df["Volume"].groupby(day).cumsum().replace(0, np.nan)
    return pv / v


def supertrend(df: pd.DataFrame, n: int = 10, mult: float = 3.0) -> pd.DataFrame:
    a = atr(df, n)
    hl2 = (df["High"] + df["Low"]) / 2
    ub, lb = (hl2 + mult * a).to_numpy(), (hl2 - mult * a).to_numpy()
    close = df["Close"].to_numpy()
    fu, fl = ub.copy(), lb.copy()
    st = np.full(len(df), np.nan)
    up = np.ones(len(df), dtype=bool)
    for i in range(1, len(df)):
        if np.isnan(ub[i]) or np.isnan(fu[i - 1]):
            continue
        fu[i] = ub[i] if (ub[i] < fu[i - 1] or close[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lb[i] if (lb[i] > fl[i - 1] or close[i - 1] < fl[i - 1]) else fl[i - 1]
        if close[i] > fu[i - 1]:
            up[i] = True
        elif close[i] < fl[i - 1]:
            up[i] = False
        else:
            up[i] = up[i - 1]
        st[i] = fl[i] if up[i] else fu[i]
    return pd.DataFrame({"line": st, "up": up}, index=df.index)


def ichimoku(df: pd.DataFrame) -> pd.DataFrame:
    def mid(n):
        return (df["High"].rolling(n).max() + df["Low"].rolling(n).min()) / 2
    tenkan, kijun = mid(9), mid(26)
    return pd.DataFrame({"tenkan": tenkan, "kijun": kijun,
                         "span_a": ((tenkan + kijun) / 2).shift(26), "span_b": mid(52).shift(26)})


# ---------------------------------------------------------------------------
# catalog: what the page offers
# ---------------------------------------------------------------------------
OVERLAYS = ["SMA 20", "SMA 50", "SMA 200", "EMA 9", "EMA 21", "Bollinger Bands",
            "VWAP", "Supertrend", "Ichimoku Cloud"]
PANELS = ["Volume", "RSI", "MACD", "Stochastic", "ADX / DI", "CCI", "ATR",
          "Williams %R", "OBV", "Money Flow Index"]
ALL_INDICATORS = OVERLAYS + PANELS
DEFAULT_INDICATORS = ["SMA 20", "SMA 50", "EMA 21", "Bollinger Bands", "Volume", "RSI", "MACD"]


# ---------------------------------------------------------------------------
# data
# ---------------------------------------------------------------------------
INTRADAY = {"1 min": "1m", "5 min": "5m", "15 min": "15m", "1 hour": "60m"}
DAILY = {"Daily": None, "Weekly": "W-FRI", "Monthly": "ME"}


def resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    out = df.resample(rule).agg({"Open": "first", "High": "max", "Low": "min",
                                 "Close": "last", "Volume": "sum"})
    return out.dropna(subset=["Close"])


def load_bars(yahoo_symbol: str, timeframe: str, market: str = "IN") -> pd.DataFrame:
    """OHLCV bars for ``timeframe`` (a key of INTRADAY or DAILY). Raises LookupError."""
    from . import data as _data

    if timeframe in INTRADAY:
        interval = INTRADAY[timeframe]
        period = "5d" if interval in ("1m", "5m") else "1mo"
        q = _data._fetch_live_yahoo(yahoo_symbol, interval=interval, period=period, market=market)
        bars = q.bars
    else:
        bars = _data._history_with_retry(_data.normalize_ticker(yahoo_symbol, market), "5y")
        if DAILY.get(timeframe):
            bars = resample_ohlcv(bars, DAILY[timeframe])
    if bars is None or bars.empty:
        raise LookupError(f"No bars returned for {yahoo_symbol} ({timeframe}).")
    cols = [c for c in ("Open", "High", "Low", "Close", "Volume") if c in bars.columns]
    bars = bars[cols].dropna(subset=["Close"]).copy()
    if "Volume" not in bars:
        bars["Volume"] = np.nan
    return bars


# ---------------------------------------------------------------------------
# figure
# ---------------------------------------------------------------------------
def build_figure(df: pd.DataFrame, indicators: list[str], title: str = "",
                 height: int = 760, max_bars: int = 260) -> go.Figure:
    """Candles with the chosen overlays on top and one sub-panel per chosen oscillator."""
    C = T.C
    full = df  # indicators are computed on all history, then the view is trimmed
    panels = [p for p in PANELS if p in indicators]
    has_vol = full["Volume"].notna().any() and (full["Volume"].fillna(0) > 0).any()
    if "Volume" in panels and not has_vol:
        panels.remove("Volume")
    rows = 1 + len(panels)
    heights = [0.55] + [0.45 / max(len(panels), 1)] * len(panels) if panels else [1.0]
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True, vertical_spacing=0.02,
                        row_heights=heights)

    view = full.tail(max_bars)
    x = view.index
    # Category axis would hide gaps; use a date axis and let rangebreaks hide weekends.
    fig.add_trace(go.Candlestick(
        x=x, open=view["Open"], high=view["High"], low=view["Low"], close=view["Close"],
        name="Price", increasing_line_color=C["up"], decreasing_line_color=C["down"],
        increasing_fillcolor=C["up"], decreasing_fillcolor=C["down"], showlegend=False), row=1, col=1)

    def line(series, name, color, row=1, dash=None, width=1.2):
        s = series.reindex(x)
        fig.add_trace(go.Scatter(x=x, y=s, name=name, mode="lines", connectgaps=False,
                                 line=dict(color=color, width=width, dash=dash)), row=row, col=1)

    close = full["Close"]
    palette = {"SMA 20": C["amber"], "SMA 50": C["blue"], "SMA 200": "#B084F5",
               "EMA 9": "#2EC4B6", "EMA 21": "#F7B801"}
    for name in ("SMA 20", "SMA 50", "SMA 200"):
        if name in indicators:
            line(sma(close, int(name.split()[1])), name, palette[name])
    for name in ("EMA 9", "EMA 21"):
        if name in indicators:
            line(ema(close, int(name.split()[1])), name, palette[name], dash="dot")
    if "Bollinger Bands" in indicators:
        bb = bollinger(close)
        line(bb["upper"], "BB upper", C["dim"], dash="dash", width=1)
        line(bb["lower"], "BB lower", C["dim"], dash="dash", width=1)
        line(bb["mid"], "BB mid", C["faint"], width=1)
    if "VWAP" in indicators and has_vol:
        line(vwap(full), "VWAP", "#FF6FB5", dash="dashdot")
    if "Supertrend" in indicators:
        st = supertrend(full)
        line(st["line"].where(st["up"]), "Supertrend ↑", C["up"], width=1.6)
        line(st["line"].where(~st["up"]), "Supertrend ↓", C["down"], width=1.6)
    if "Ichimoku Cloud" in indicators:
        ic = ichimoku(full)
        line(ic["tenkan"], "Tenkan", "#4C8DFF", width=1)
        line(ic["kijun"], "Kijun", "#F6465D", width=1)
        line(ic["span_a"], "Span A", "rgba(14,203,129,.55)", width=1)
        line(ic["span_b"], "Span B", "rgba(246,70,93,.55)", width=1)

    r = 1

    def hline(row, y, color=None):
        fig.add_hline(y=y, line=dict(color=color or C["faint"], width=1, dash="dot"), row=row, col=1)

    def label(row, text):
        fig.update_yaxes(title_text=text, title_font=dict(size=10, color=C["dim"]), row=row, col=1)

    for p in panels:
        r += 1
        if p == "Volume":
            colors = np.where(view["Close"] >= view["Open"], C["up"], C["down"])
            fig.add_trace(go.Bar(x=x, y=view["Volume"], marker_color=colors, opacity=.7,
                                 name="Volume", showlegend=False), row=r, col=1)
        elif p == "RSI":
            line(rsi(close), "RSI 14", C["amber"], row=r)
            hline(r, 70, C["down"]); hline(r, 30, C["up"])
        elif p == "MACD":
            m = macd(close).reindex(x)
            fig.add_trace(go.Bar(x=x, y=m["hist"], marker_color=np.where(m["hist"] >= 0, C["up"], C["down"]),
                                 opacity=.6, name="Hist", showlegend=False), row=r, col=1)
            line(macd(close)["macd"], "MACD", C["blue"], row=r)
            line(macd(close)["signal"], "Signal", C["amber"], row=r)
        elif p == "Stochastic":
            s = stochastic(full)
            line(s["k"], "%K", C["blue"], row=r); line(s["d"], "%D", C["amber"], row=r)
            hline(r, 80, C["down"]); hline(r, 20, C["up"])
        elif p == "ADX / DI":
            a = adx(full)
            line(a["adx"], "ADX", C["text"], row=r)
            line(a["+di"], "+DI", C["up"], row=r, width=1); line(a["-di"], "-DI", C["down"], row=r, width=1)
            hline(r, 25)
        elif p == "CCI":
            line(cci(full), "CCI 20", C["amber"], row=r)
            hline(r, 100, C["down"]); hline(r, -100, C["up"])
        elif p == "ATR":
            line(atr(full), "ATR 14", C["amber"], row=r)
        elif p == "Williams %R":
            line(williams_r(full), "%R 14", C["amber"], row=r)
            hline(r, -20, C["down"]); hline(r, -80, C["up"])
        elif p == "OBV":
            line(obv(full), "OBV", C["amber"], row=r)
        elif p == "Money Flow Index":
            line(mfi(full), "MFI 14", C["amber"], row=r)
            hline(r, 80, C["down"]); hline(r, 20, C["up"])
        label(r, p.split(" /")[0].replace("Money Flow Index", "MFI"))

    intraday = len(full) > 2 and (full.index[1] - full.index[0]) < pd.Timedelta(days=1)
    for i in range(1, rows + 1):
        fig.update_xaxes(rangeslider_visible=False, row=i, col=1)
    # Hide non-trading gaps (weekends; overnight for intraday) so candles sit side by side.
    breaks = [dict(bounds=["sat", "mon"])]
    if intraday and hasattr(x, "hour") and len(x) > 0:
        hrs = x.hour + x.minute / 60
        breaks.append(dict(bounds=[float(hrs.max()) + 1 / 60, float(hrs.min())], pattern="hour"))
    fig.update_xaxes(rangebreaks=breaks)
    fig.update_layout(
        title=title, height=height, margin=dict(l=8, r=8, t=34, b=8), hovermode="x unified",
        xaxis_rangeslider_visible=False, legend=dict(orientation="h", y=1.02, x=0, font=dict(size=10)),
    )
    return fig


# ---------------------------------------------------------------------------
# readout: bullish / bearish / neutral per indicator (rules of thumb, not advice)
# ---------------------------------------------------------------------------
def readout(df: pd.DataFrame) -> list[tuple[str, str, str]]:
    """[(indicator, value, 'Bullish' | 'Bearish' | 'Neutral')] from the latest bar."""
    out: list[tuple[str, str, str]] = []
    if len(df) < 30:
        return out
    c = df["Close"]
    last = float(c.iloc[-1])

    def add(name, val, view):
        out.append((name, val, view))

    r = float(rsi(c).iloc[-1])
    add("RSI 14", f"{r:.1f}", "Bearish" if r >= 70 else "Bullish" if r <= 30 else "Neutral")
    m = macd(c).iloc[-1]
    add("MACD", f"{m['macd']:.2f} vs {m['signal']:.2f}", "Bullish" if m["macd"] > m["signal"] else "Bearish")
    s = stochastic(df).iloc[-1]
    add("Stochastic %K", f"{s['k']:.1f}", "Bearish" if s["k"] >= 80 else "Bullish" if s["k"] <= 20 else "Neutral")
    a = adx(df).iloc[-1]
    trend = "Bullish" if a["+di"] > a["-di"] else "Bearish"
    add("ADX", f"{a['adx']:.1f}", trend if a["adx"] >= 25 else "Neutral")
    k = cci(df).iloc[-1]
    add("CCI 20", f"{k:.0f}", "Bearish" if k >= 100 else "Bullish" if k <= -100 else "Neutral")
    for n in (20, 50, 200):
        if len(c) > n:
            v = float(sma(c, n).iloc[-1])
            add(f"SMA {n}", f"{v:,.1f}", "Bullish" if last > v else "Bearish")
    for n in (9, 21):
        v = float(ema(c, n).iloc[-1])
        add(f"EMA {n}", f"{v:,.1f}", "Bullish" if last > v else "Bearish")
    bb = bollinger(c).iloc[-1]
    add("Bollinger", f"{bb['lower']:,.0f} – {bb['upper']:,.0f}",
        "Bearish" if last > bb["upper"] else "Bullish" if last < bb["lower"] else "Neutral")
    st = supertrend(df).iloc[-1]
    add("Supertrend", "up" if st["up"] else "down", "Bullish" if st["up"] else "Bearish")
    return [(n, v, t) for n, v, t in out if not (isinstance(v, str) and v == "nan")]


def summary(rows: list[tuple[str, str, str]]) -> tuple[int, int, int]:
    b = sum(1 for *_, t in rows if t == "Bullish")
    s = sum(1 for *_, t in rows if t == "Bearish")
    return b, s, len(rows) - b - s
