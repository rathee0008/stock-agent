"""Unit tests for the Top 20 page helpers (no network)."""

from datetime import date

import pandas as pd

from agent import picks_extra as X
from agent.presets import PRESETS, apply_filters, slug
from tests.conftest import make_ohlcv


def _frame():
    return pd.DataFrame({
        "Market": ["IN", "US", "US", "IN"], "Symbol": ["A.NS", "B", "C", "D.NS"], "Score": [50, 40, 30, 20],
        "Fundamental": [20, 20, 5, 30], "RSI": [60, 60, 85, 30], "P/E": [12, 30, 10, 80], "ROE %": [20, 15, 30, 5],
        "Rev growth %": [25, 5, 30, 40], "3M %": [10, 20, 5, -5], "Upside %": [25, 5, 30, 10],
        "Mkt cap": [6e10, 6e10, 1e9, 6e10], "Analyst": ["buy", "hold", "buy", "hold"],
        "Sector": ["Tech", "Tech", "Energy", "Energy"],
    })


def test_presets_all_run_and_sort():
    df = _frame()
    for f in PRESETS.values():
        out = apply_filters(df, f)
        assert list(out["Score"]) == sorted(out["Score"], reverse=True)


def test_slug():
    assert slug("GARP (growth at fair price)") == "garp_growth_at_fair_price"


def test_atr_and_extras():
    df = make_ohlcv(300, seed=3)
    a = X.atr_pct(df)
    assert a is not None and 0 < a < 10
    ex = X.extras_from_history({"S": df, "SHORT": df.head(5)}, today=date(2026, 10, 15))
    r = ex.set_index("Symbol").loc["S"]
    assert r["From 52w high %"] <= 0 and r["Avg turnover"] > 0
    assert not r["Stale"]
    ex2 = X.extras_from_history({"S": df}, today=date(2026, 11, 30))
    assert bool(ex2.iloc[0]["Stale"])


def test_earnings_label():
    t = date(2026, 10, 16)
    assert X.earnings_label(None, t) == "—"
    assert X.earnings_label(date(2026, 10, 18), t).endswith("⚠")
    assert "⚠" not in X.earnings_label(date(2026, 11, 18), t)
    assert X.earnings_label(date(2026, 10, 1), t) == "—"


def test_cap_sector():
    df = pd.DataFrame({"Symbol": list("abcde"), "Sector": ["E", "E", "E", "T", "—"]})
    assert list(X.cap_sector(df, 2)["Symbol"]) == ["a", "b", "d", "e"]
    assert len(X.cap_sector(df, 0)) == 5


def test_position_size():
    sh, val, stop = X.position_size(100.0, 2.0, 100_000, 1.0)  # risk 1000, per share 4 -> 250 shares
    assert sh == 250 and val == 25_000 and stop == 96.0
    sh, val, _ = X.position_size(100.0, 0.1, 1_000, 5.0)  # capped by capital
    assert sh == 10 and val == 1_000
    assert X.position_size(100.0, None, 1000, 1.0) == (None, None, None)
    assert X.position_size(0, 2.0, 1000, 1.0) == (None, None, None)


def _top(symbols, scores=None):
    return pd.DataFrame({"Symbol": symbols, "Score": scores or [50 - i for i in range(len(symbols))],
                         "Price": [100.0 + i for i in range(len(symbols))], "Market": ["US"] * len(symbols)})


def test_history_roundtrip_and_features(tmp_path):
    p = tmp_path / "h.csv"
    X.append_top20(p, "2026-10-01", "morning", _top(["A", "B", "C"]))
    X.append_top20(p, "2026-10-01", "evening", _top(["B", "A", "D"]))
    h = X.append_top20(p, "2026-10-02", "morning", _top(["A", "B", "E"]))
    X.append_top20(p, "2026-10-02", "morning", _top(["A", "B", "E"]))  # same run again: replaced, not duplicated
    h = X.load_history(p)
    assert len(h) == 9
    f = X.history_features(h, ["A", "C", "Z"]).set_index("Symbol")
    assert f.loc["A", "Days in top 20"] == 2
    assert f.loc["A", "Rank trend"] == [20.0, 19.0, 20.0]
    assert f.loc["C", "Rank trend"] == [18.0, 0.0, 0.0]
    assert pd.isna(f.loc["Z", "Days in top 20"]) and f.loc["Z", "Rank trend"] is None


def test_history_missing_file(tmp_path):
    h = X.load_history(tmp_path / "nope.csv")
    assert h.empty
    f = X.history_features(h, ["A"])
    assert f["Days in top 20"].isna().all()


def test_past_picks(tmp_path):
    p = tmp_path / "h.csv"
    X.append_top20(p, "2026-10-01", "evening", _top(["A", "B"]))
    X.append_top20(p, "2026-10-14", "evening", _top(["A", "B"]))
    h = X.load_history(p)
    out, label = X.past_picks_performance(h, {"A": 110.0, "B": 90.0}, today=date(2026, 10, 16))
    assert label == "2026-10-01 evening"
    r = out.set_index("Symbol")["Return %"]
    assert round(r["A"], 1) == 10.0 and r["B"] < 0
    out2, label2 = X.past_picks_performance(h, {"A": 1.0}, today=date(2026, 10, 5))
    assert label2 is None and out2.empty
