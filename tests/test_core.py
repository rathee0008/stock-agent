import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from agent import alerts, backtest as BT, cache, chat, fallback, flows, portfolio as PF, why
from agent import fundamental as F, news as N, signal as S, technical as TECH
from tests.conftest import make_ohlcv


# ------------------------------------------------------------------ cache
def test_bucket_rolls_with_ttl():
    t = 1_700_000_000
    assert cache.bucket("IN", now=t) == cache.bucket("IN", now=t + 1)
    assert cache.bucket("IN", now=t) != cache.bucket("IN", now=t + 4 * 3600)


def test_ttl_shorter_when_open(monkeypatch):
    monkeypatch.setattr(cache, "state", lambda m: "REGULAR")
    open_ttl = cache.ttl_for("IN")
    monkeypatch.setattr(cache, "state", lambda m: "CLOSED")
    assert open_ttl < cache.ttl_for("IN")


def test_stale_ok_returns_last_good(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "_DIR", tmp_path)
    df = make_ohlcv(50)
    val, stale = cache.stale_ok("k1", lambda: df)
    assert not stale
    def boom():
        raise RuntimeError("yahoo down")
    val2, stale2 = cache.stale_ok("k1", boom)
    assert stale2 and len(val2) == 50
    with pytest.raises(RuntimeError):
        cache.stale_ok("never-seen", boom)


# ------------------------------------------------------------------ fallback
def test_alpha_vantage_parse(monkeypatch):
    monkeypatch.setenv("ALPHAVANTAGE_API_KEY", "x")
    payload = {"Time Series (Daily)": {"2026-10-14": {"1. open": "10", "2. high": "11", "3. low": "9", "4. close": "10.5", "5. volume": "1000"},
                                       "2026-10-13": {"1. open": "9", "2. high": "10", "3. low": "8", "4. close": "9.5", "5. volume": "900"}}}

    class R:
        def raise_for_status(self): pass
        def json(self): return payload
    monkeypatch.setattr(fallback.requests, "get", lambda *a, **k: R())
    df = fallback.alpha_vantage("TCS.NS")
    assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"] and df["Close"].iloc[-1] == 10.5
    assert fallback._av_symbol("TCS.NS") == "TCS.BSE"


# ------------------------------------------------------------------ signal
def _parts(ohlcv, fund_score=None, news_score=None):
    tech = TECH.analyze(ohlcv)
    fund = F.FundamentalResult(score=fund_score or 0.0, label="x", metrics={}, signals=[("ROE", "solid", 6.0)] if fund_score is not None else [],
                               available=fund_score is not None)
    nw = N.NewsResult(score=news_score or 0.0, label="x", headlines=[], available=news_score is not None)
    return tech, fund, nw


def test_conflict_caps_confidence(ohlcv):
    tech, fund, nw = _parts(ohlcv, fund_score=40)
    tech.score = -40
    out = S.combine(tech, fund, nw, ohlcv)
    assert out.conflict and out.confidence_pct <= 45 and "disagree" in out.conflict_note


def test_agreement_not_flagged(ohlcv):
    tech, fund, nw = _parts(ohlcv, fund_score=30, news_score=30)
    tech.score = 35
    out = S.combine(tech, fund, nw, ohlcv)
    assert not out.conflict and out.confidence_pct > 45


def test_drivers_sorted_and_weighted(ohlcv):
    tech, fund, nw = _parts(ohlcv, fund_score=20)
    out = S.combine(tech, fund, nw, ohlcv)
    ws = [abs(d["weighted"]) for d in out.drivers]
    assert ws == sorted(ws, reverse=True) and {"Technical", "Fundamental"} >= {d["component"] for d in out.drivers}


# ------------------------------------------------------------------ technical weights
def test_group_weights_scale_points(ohlcv):
    base = TECH.analyze(ohlcv)
    tuned = TECH.analyze(ohlcv, group_weights={"Momentum": 0.0})
    mom = [s for s in tuned.signals if TECH.signal_group(s[0]) == "Momentum"]
    assert all(p == 0 for _, _, p in mom)
    assert base.score != tuned.score or not any(TECH.signal_group(s[0]) == "Momentum" and s[2] for s in base.signals)


# ------------------------------------------------------------------ backtest
def test_perf_metrics_known_values():
    r = pd.Series([0.1, -0.05, 0.1, 0.0])
    m = BT.perf_metrics(r, step=63)
    assert m["total"] == pytest.approx(1.1 * 0.95 * 1.1 - 1)
    assert m["max_dd"] == pytest.approx(-0.05)
    assert m["win_rate"] == 0.5


def test_backtest_runs_and_calibrates(universe_hist):
    res = BT.run(universe_hist, top_n=5, step=21, cost_bps=20, max_dates=14)
    assert not res.periods.empty and {"Strategy", "Universe", "Gross", "Excess"} <= set(res.periods.columns)
    assert (res.periods["Gross"] >= res.periods["Strategy"] - 1e-12).all()      # costs only subtract
    assert res.metrics["cost_drag_pa"] >= 0 and "in_sample" in res.metrics
    assert not res.calibration.empty and res.calibration["p_up"].between(0, 1).all()
    assert set(res.samples.columns) >= {"score", "fwd", "g_Trend", "g_Momentum"}


def test_zero_cost_equals_gross(universe_hist):
    res = BT.run(universe_hist, top_n=5, step=21, cost_bps=0, max_dates=6)
    assert np.allclose(res.periods["Gross"], res.periods["Strategy"])


def test_signal_lab_detects_planted_signal():
    rng = np.random.default_rng(1)
    rows = []
    for d in pd.date_range("2024-01-01", periods=30, freq="MS"):
        x = rng.normal(size=40)
        rows += [{"date": d, "sym": i, "score": 0, "fwd": x[i] * 0.05 + rng.normal(0, 0.01), "g_Good": x[i], "g_Noise": rng.normal()} for i in range(40)]
    lab = BT.signal_lab(pd.DataFrame(rows))
    assert lab.iloc[0]["Group"] == "Good" and lab.iloc[0]["IC"] > 0.5
    w = BT.suggest_group_weights(lab)
    assert 1.0 < w["Good"] <= 1.6 and w["Noise"] == 1.0


def test_calibrated_statement(tmp_path, monkeypatch):
    monkeypatch.setattr(BT, "_CAL_FILE", tmp_path / "c.json")
    cal = pd.DataFrame({"n": [200], "p_up": [0.6], "mean_ret": [0.012], "median_ret": [0.01], "base_p_up": [0.54]},
                       index=pd.Index(["Bullish"], name="Band"))
    BT.save_calibration(cal, "IN", 21)
    msg = BT.calibrated_statement(30, "IN")
    assert "60%" in msg and "n=200" in msg and "not a forecast" in msg
    assert BT.calibrated_statement(-60, "IN") is None          # band with no data


# ------------------------------------------------------------------ flows / why
BHAV = ("SYMBOL, SERIES, DATE1, TTL_TRD_QNTY, DELIV_QTY, DELIV_PER\n"
        "TCS, EQ, 14-Oct-2026, 1000, 650, 65.00\nXYZ, BE, 14-Oct-2026, 10, 10, 100.00\nINFY, EQ, 14-Oct-2026, 500, 100, 20.00\n")
BULK = ("Date,Symbol,Security Name,Client Name,Buy/Sell,Quantity Traded,Trade Price / Wght. Avg. Price,Remarks\n"
        "14-OCT-2026,TCS,Tata,ABC FUND,BUY,\"1,000,000\",4000.00,-\n14-OCT-2026,INFY,Infosys,XYZ LTD,SELL,500000,1500.0,-\n")


def test_parse_bhavcopy():
    df = flows.parse_bhavcopy(BHAV)
    assert list(df["Symbol"]) == ["TCS.NS", "INFY.NS"] and df.loc[0, "Delivery %"] == 65.0


def test_parse_deals():
    df = flows.parse_deals(BULK, "BULK")
    assert df.iloc[0]["Symbol"] == "TCS.NS" and df.iloc[0]["Value (Cr)"] == pytest.approx(400.0)
    assert set(df["Side"]) == {"BUY", "SELL"}
    note = flows.deals_by_symbol(df)["TCS.NS"]
    assert "ABC FUND" in note and "buy" in note


def test_parse_fii_dii():
    df = flows.parse_fii_dii([{"category": "FII/FPI *", "date": "14-Oct-2026", "buyValue": "10,000.5", "sellValue": "12,000.0", "netValue": "-1,999.5"}])
    assert df.loc[0, "Net (Cr)"] == -1999.5


def test_delivery_walks_back(monkeypatch):
    calls = []
    def fake_get(url, timeout=15):
        calls.append(url)
        if "13102026" not in url:
            raise RuntimeError("404")
        return BHAV
    monkeypatch.setattr(flows, "_get", fake_get)
    df = flows.delivery(today=dt.date(2026, 10, 15))      # Thu: 15th fails, 14th fails, 13th ok
    assert not df.empty and len(calls) == 3


def test_why_tags():
    row = {"Change %": 5.0, "Vol vs 5d avg": 2.6, "Gap %": 2.1, "52W pos %": 99, "Sector": "IT", "Delivery %": 72}
    tags = why.explain(row, {"IT": 1.8}, "Block deal: X buy ₹100 Cr", "TCS wins order")
    joined = " | ".join(tags)
    assert tags[0].startswith("News:") and "Block deal" in joined and len(tags) <= 4
    quiet = why.explain({"Change %": 0.3, "Vol vs 5d avg": 1.0}, {}, None, None)
    assert quiet == ["No clear catalyst in price, volume or news data"]


# ------------------------------------------------------------------ alerts
NOW = dt.datetime(2026, 10, 15, 6, 0, tzinfo=dt.UTC)


def test_alert_rules_and_cooldown():
    rules = [alerts.Rule.from_dict(d) for d in [
        {"symbol": "tcs", "market": "IN", "type": "price_above", "value": 4000},
        {"symbol": "TCS", "market": "IN", "type": "rsi_above", "value": 70},
        {"symbol": "TCS", "market": "IN", "type": "price_below", "value": 3000}]]
    snaps = {"IN:TCS": {"price": 4100, "rsi": 75, "day_pct": 1, "label": "Buy (bias)"}}
    ev, st = alerts.evaluate(rules, snaps, None, NOW)
    assert {e["rule"].split(":")[2] for e in ev} == {"price_above", "rsi_above"}
    ev2, st2 = alerts.evaluate(rules, snaps, st, NOW + dt.timedelta(hours=2))
    assert ev2 == []                                            # cooldown
    ev3, _ = alerts.evaluate(rules, snaps, st, NOW + dt.timedelta(hours=25))
    assert len(ev3) == 2


def test_composite_flip():
    r = [alerts.Rule.from_dict({"symbol": "TCS", "market": "IN", "type": "composite_flip"})]
    ev, st = alerts.evaluate(r, {"IN:TCS": {"label": "Hold / Neutral"}}, None, NOW)
    assert ev == []                                             # first sight: no baseline
    ev, st = alerts.evaluate(r, {"IN:TCS": {"label": "Buy (bias)"}}, st, NOW)
    assert len(ev) == 1 and "Hold / Neutral → Buy (bias)" in ev[0]["message"]
    ev, _ = alerts.evaluate(r, {"IN:TCS": {"label": "Buy (bias)"}}, st, NOW)
    assert ev == []


def test_snapshots_tolerate_failures():
    rules = [alerts.Rule("A", "IN", "price_above", 1), alerts.Rule("B", "IN", "price_above", 1)]
    def fn(s, m):
        if s == "A":
            raise RuntimeError("x")
        return {"price": 5}
    out = alerts.snapshots_for(rules, fn)
    assert list(out) == ["IN:B"]


def test_no_channels_means_no_send(monkeypatch):
    for k in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"):
        monkeypatch.delenv(k, raising=False)
    assert alerts.deliver("s", "b") == {"telegram": False, "email": False}


# ------------------------------------------------------------------ portfolio
def test_parse_and_fifo():
    txt = "BUY TCS 10 100 2024-01-01\nBUY TCS 10 120 2024-06-01\nSELL TCS 15 150 2025-07-01\nINFY 5 50\nbad line"
    tx, bad = PF.parse_transactions(txt)
    assert len(tx) == 4 and bad == ["bad line"]
    lots, real, warns = PF.fifo(tx)
    assert [round(r.qty) for r in real] == [10, 5] and real[0].buy_price == 100 and real[1].buy_price == 120
    pos = PF.positions(lots)
    assert pos["TCS"] == (5.0, 120.0) and pos["INFY"] == (5.0, 50.0) and not warns


def test_oversell_warns():
    tx, _ = PF.parse_transactions("BUY A 1 10 2024-01-01\nSELL A 3 20 2024-02-01")
    _, real, warns = PF.fifo(tx)
    assert sum(r.qty for r in real) == 1 and warns


def test_tax_short_long_and_exemption():
    d = dt.date
    real = [PF.Realised("TCS.NS", 10, 100, 150, d(2024, 1, 1), d(2025, 7, 1)),      # long, +500
            PF.Realised("INFY.NS", 10, 100, 130, d(2025, 5, 1), d(2025, 9, 1)),     # short, +300
            PF.Realised("AAPL", 1, 100, 200, d(2024, 1, 1), d(2025, 9, 1))]          # foreign
    ts = PF.tax_summary(real, 2025, PF.IndiaTax(ltcg_exempt=0))
    assert ts.stcg == 300 and ts.ltcg == 500 and ts.foreign_gain == 100
    assert ts.tax == pytest.approx((300 * 0.20 + 500 * 0.125) * 1.04)
    big = [PF.Realised("TCS.NS", 100, 100, 3000, d(2023, 1, 1), d(2025, 7, 1))]       # +290,000 long
    t2 = PF.tax_summary(big, 2025)
    assert t2.ltcg_taxable == pytest.approx(290_000 - 125_000) and t2.tax == pytest.approx(165_000 * 0.125 * 1.04)
    assert PF.tax_summary(big, 2024).tax == 0                                          # other FY


def test_short_term_loss_offsets_long_term():
    d = dt.date
    real = [PF.Realised("A.NS", 1, 100, 200, d(2023, 1, 1), d(2025, 6, 1)),           # long +100
            PF.Realised("B.NS", 1, 100, 60, d(2025, 3, 1), d(2025, 6, 2))]            # short -40
    ts = PF.tax_summary(real, 2025, PF.IndiaTax(ltcg_exempt=0))
    assert ts.tax == pytest.approx(60 * 0.125 * 1.04)


def test_long_term_boundary_is_more_than_12_months():
    d = dt.date
    one = [PF.Realised("A.NS", 1, 100, 200, d(2024, 6, 1), d(2025, 6, 1))]          # 365 days: still short
    two = [PF.Realised("A.NS", 1, 100, 200, d(2024, 6, 1), d(2025, 6, 2))]          # 366 days: long
    assert PF.tax_summary(one, 2025).stcg == 100 and PF.tax_summary(two, 2025).ltcg == 100


def test_lots_turning_long_term():
    lots = [PF.Lot("A.NS", 10, 100, dt.date(2025, 10, 1))]
    out = PF.lots_turning_long_term(lots, {"A.NS": 150}, 45, today=dt.date(2026, 9, 20))
    assert out and out[0]["Days to long-term"] == 12


def test_var_beta_and_contributions():
    rng = np.random.default_rng(3)
    idx = pd.bdate_range("2025-01-01", periods=400)
    mkt = pd.Series(rng.normal(0, 0.01, 400), index=idx)
    a = 1.5 * mkt + rng.normal(0, 0.003, 400)
    b = rng.normal(0, 0.01, 400)
    closes = pd.DataFrame({"A": 100 * (1 + a).cumprod(), "B": 100 * (1 + pd.Series(b, index=idx)).cumprod()}, index=idx)
    assert PF.beta(a, mkt) == pytest.approx(1.5, abs=0.1)
    port = PF.portfolio_returns(closes, {"A": 1, "B": 1})
    v = PF.var_cvar(port, 0.95)
    assert v["cvar"] >= v["hist_var"] > 0 and PF.var_cvar(port, 0.95, 10)["hist_var"] == pytest.approx(v["hist_var"] * np.sqrt(10))
    rc = PF.risk_contributions(closes, {"A": 1, "B": 1})
    assert rc.sum() == pytest.approx(1.0) and abs(PF.correlation(closes).loc["A", "B"]) < 0.3
    assert PF.hhi(pd.Series({"x": 1, "y": 1})) == 0.5


def test_position_size():
    z = PF.position_size(1_000_000, 1.0, 1000, 20, atr_mult=2)      # stop 960, risk/share 40, budget 10,000
    assert z.stop == 960 and z.qty == 250 and z.risk_amount == 10_000 and z.pct_of_capital == 25.0 and not z.capped
    c = PF.position_size(1_000_000, 2.0, 1000, 10, atr_mult=1, max_position_pct=10)   # wants 2,000 sh, cap 100
    assert c.qty == 100 and c.capped
    assert PF.position_size(1000, 1, 100, 0) is None
    s = PF.position_size(100_000, 1, 100, 5, side="SHORT")
    assert s.stop == 110 and s.qty == 100


# ------------------------------------------------------------------ chat
def test_extract_symbols():
    assert chat.extract_symbols("Why is RELIANCE rated Hold?") == [("RELIANCE", "IN")]
    assert chat.extract_symbols("Compare tcs and NVDA today") == [("TCS", "IN"), ("NVDA", "US")]
    assert chat.extract_symbols("what is the weather") == []
    assert chat.extract_symbols("is $AMD overbought") == [("AMD", "US")]


def test_chat_offline_without_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(chat, "gather", lambda q, e=None: ({"stocks": []}, []))
    text, src = chat.answer("hello")
    assert src == "template" and "API key" in text
