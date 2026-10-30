import numpy as np
import pandas as pd

from agent import indexchart as IC


def _frame(n=300, seed=1):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    return pd.DataFrame({"Open": close - 0.3, "High": close + 1, "Low": close - 1,
                         "Close": close, "Volume": rng.integers(1_000, 5_000, n).astype(float)}, index=idx)


def test_rsi_bounds_and_flat_series():
    df = _frame()
    r = IC.rsi(df["Close"]).dropna()
    assert ((r >= 0) & (r <= 100)).all()
    up = pd.Series(np.arange(1, 60, dtype=float))
    assert IC.rsi(up).iloc[-1] > 99


def test_macd_hist_is_line_minus_signal():
    m = IC.macd(_frame()["Close"])
    assert np.allclose(m["hist"], m["macd"] - m["signal"])


def test_bollinger_ordering():
    bb = IC.bollinger(_frame()["Close"]).dropna()
    assert (bb["upper"] >= bb["mid"]).all() and (bb["mid"] >= bb["lower"]).all()


def test_oscillator_ranges():
    df = _frame()
    k = IC.stochastic(df)["k"].dropna()
    assert ((k >= 0) & (k <= 100)).all()
    w = IC.williams_r(df).dropna()
    assert ((w >= -100) & (w <= 0)).all()
    m = IC.mfi(df).dropna()
    assert ((m >= 0) & (m <= 100)).all()
    assert (IC.adx(df)["adx"].dropna() >= 0).all()


def test_supertrend_follows_a_strong_uptrend():
    n = 120
    idx = pd.date_range("2025-01-01", periods=n, freq="B")
    c = pd.Series(np.linspace(100, 200, n), index=idx)
    df = pd.DataFrame({"Open": c, "High": c + 1, "Low": c - 1, "Close": c, "Volume": 1.0})
    st = IC.supertrend(df)
    assert bool(st["up"].iloc[-1]) and st["line"].iloc[-1] < c.iloc[-1]


def test_vwap_resets_each_day():
    idx = pd.to_datetime(["2025-01-01 09:15", "2025-01-01 09:20", "2025-01-02 09:15"])
    df = pd.DataFrame({"Open": 1.0, "High": [10, 10, 50], "Low": [10, 10, 50],
                       "Close": [10, 10, 50], "Volume": [1.0, 1.0, 1.0]}, index=idx)
    v = IC.vwap(df)
    assert v.iloc[1] == 10 and v.iloc[2] == 50


def test_resample_weekly_ohlcv():
    df = _frame(60)
    w = IC.resample_ohlcv(df, "W-FRI")
    assert w["High"].max() == df["High"].max() and w["Volume"].sum() == df["Volume"].sum()


def test_build_figure_all_indicators_and_readout():
    df = _frame()
    fig = IC.build_figure(df, IC.ALL_INDICATORS)
    assert len(fig.data) > 10
    rows = IC.readout(df)
    b, s, n = IC.summary(rows)
    assert rows and b + s + n == len(rows)


def test_build_figure_without_volume():
    df = _frame()
    df["Volume"] = np.nan
    fig = IC.build_figure(df, ["Volume", "VWAP", "RSI"])
    names = [t.name for t in fig.data]
    assert "Volume" not in names and "VWAP" not in names and "RSI 14" in names
