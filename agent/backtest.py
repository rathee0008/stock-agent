"""Backtest engine (technical score only — Yahoo has no point-in-time fundamentals/news).

Produces, from one replay of history:
  * strategy vs equal-weight universe vs an index benchmark, with trading costs,
  * risk-adjusted metrics (CAGR, volatility, Sharpe, max drawdown, hit rate),
  * an in-sample / out-of-sample split so over-fitting is visible,
  * a **calibration table**: for each technical-score band, how often the stock was
    higher N days later (and the average return) — used to turn a score into an
    honest "historically X% of the time" statement,
  * a **signal lab**: rank-IC of each technical signal group vs forward returns,
    which suggests group weights for :func:`agent.technical.analyze`.

Everything here is pure pandas/numpy so it can be unit-tested with synthetic data.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from . import technical as _tech

WARMUP = 252
BANDS = [(-101, -45, "Strongly bearish"), (-45, -15, "Bearish"), (-15, 15, "Neutral"),
         (15, 45, "Bullish"), (45, 101, "Strongly bullish")]

_CAL_FILE = Path(__file__).resolve().parents[1] / ".cache" / "calibration.json"
_WEIGHT_FILE = Path(__file__).resolve().parents[1] / ".cache" / "tech_weights.json"


@dataclass
class BacktestResult:
    periods: pd.DataFrame                      # one row per rebalance
    samples: pd.DataFrame                      # (score, group points, fwd return) per stock-date
    metrics: dict = field(default_factory=dict)
    calibration: pd.DataFrame = field(default_factory=pd.DataFrame)
    lab: pd.DataFrame = field(default_factory=pd.DataFrame)
    n_syms: int = 0


# ------------------------------------------------------------------ metrics
def perf_metrics(returns: pd.Series, step: int, rf_annual: float = 0.0) -> dict:
    """Metrics for a series of per-period returns, each period spanning ``step`` trading days."""
    r = returns.dropna().astype(float)
    if r.empty:
        return {}
    ppy = 252 / step
    growth = float((1 + r).prod())
    years = max(len(r) / ppy, 1e-9)
    cagr = growth ** (1 / years) - 1
    vol = float(r.std(ddof=1) * math.sqrt(ppy)) if len(r) > 1 else float("nan")
    ex = r - rf_annual / ppy
    sharpe = float(ex.mean() / r.std(ddof=1) * math.sqrt(ppy)) if len(r) > 1 and r.std(ddof=1) > 0 else float("nan")
    curve = (1 + r).cumprod()
    dd = float((curve / curve.cummax() - 1).min())
    return {"cagr": cagr, "vol": vol, "sharpe": sharpe, "max_dd": dd, "periods": len(r),
            "total": growth - 1, "win_rate": float((r > 0).mean())}


def _band(score: float) -> str:
    for lo, hi, name in BANDS:
        if lo <= score < hi:
            return name
    return BANDS[-1][2]


def calibration_table(samples: pd.DataFrame) -> pd.DataFrame:
    """P(up), mean and median forward return by technical-score band."""
    if samples.empty:
        return pd.DataFrame()
    s = samples.copy()
    s["Band"] = s["score"].map(_band)
    base = float((s["fwd"] > 0).mean())
    g = s.groupby("Band")["fwd"]
    out = pd.DataFrame({
        "n": g.size(),
        "p_up": g.apply(lambda x: float((x > 0).mean())),
        "mean_ret": g.mean(),
        "median_ret": g.median(),
    })
    out["base_p_up"] = base
    order = [b[2] for b in BANDS]
    return out.reindex([o for o in order if o in out.index])


def signal_lab(samples: pd.DataFrame, min_dates: int = 8) -> pd.DataFrame:
    """Cross-sectional rank IC per signal group, averaged over rebalance dates."""
    cols = [c for c in samples.columns if c.startswith("g_")]
    rows = []
    for c in cols:
        ics = []
        for _, d in samples.groupby("date"):
            if d[c].nunique() < 3 or len(d) < 8:
                continue
            ics.append(d[c].rank().corr(d["fwd"].rank()))
        ics = pd.Series(ics).dropna()
        if len(ics) < min_dates:
            continue
        t = float(ics.mean() / (ics.std(ddof=1) / math.sqrt(len(ics)))) if ics.std(ddof=1) > 0 else float("nan")
        rows.append({"Group": c[2:], "IC": float(ics.mean()), "t_stat": t,
                     "IC>0 %": float((ics > 0).mean() * 100), "dates": len(ics)})
    return pd.DataFrame(rows).sort_values("IC", ascending=False).reset_index(drop=True) if rows else pd.DataFrame()


def suggest_group_weights(lab: pd.DataFrame, floor: float = 0.4, cap: float = 1.6) -> dict[str, float]:
    """Map IC to multipliers around 1.0, bounded so no group is switched off or dominates.

    Only groups with |t| >= 1 move away from 1.0 — noise should not change the model.
    """
    if lab is None or lab.empty:
        return {}
    scale = max(float(lab["IC"].abs().max()), 1e-9)
    out = {}
    for _, r in lab.iterrows():
        if abs(r["t_stat"]) < 1.0 or math.isnan(r["t_stat"]):
            out[r["Group"]] = 1.0
        else:
            out[r["Group"]] = float(np.clip(1.0 + 0.6 * r["IC"] / scale, floor, cap))
    return out


# ------------------------------------------------------------------ engine
def run(hist: dict[str, pd.DataFrame], top_n: int = 10, step: int = 21, cost_bps: float = 20.0,
        bench_close: pd.Series | None = None, rf_annual: float = 0.0,
        group_weights: dict[str, float] | None = None, max_dates: int | None = None) -> BacktestResult:
    closes = pd.DataFrame({s: d["Close"] for s, d in hist.items()}).sort_index().ffill()
    if closes.empty:
        return BacktestResult(pd.DataFrame(), pd.DataFrame())
    idxs = list(range(WARMUP, len(closes) - step, step))
    if max_dates:
        idxs = idxs[-max_dates:]
    rows, samples = [], []
    prev: set[str] = set()
    for i in idxs:
        date = closes.index[i]
        scores, groups = {}, {}
        for s, d in hist.items():
            sub = d.loc[:date].tail(WARMUP + 70)
            if len(sub) < WARMUP:
                continue
            try:
                res = _tech.analyze(sub, group_weights=group_weights)
            except Exception:  # noqa: BLE001
                continue
            scores[s] = res.score
            g = {k: 0.0 for k in _tech.GROUPS}
            for name, _, pts in res.signals:
                g[_tech.signal_group(name)] = g.get(_tech.signal_group(name), 0.0) + pts
            groups[s] = g
        if len(scores) < max(top_n, 8):
            continue
        fwd = closes.iloc[i + step] / closes.iloc[i] - 1
        picks = sorted(scores, key=scores.get, reverse=True)[:top_n]
        turnover = 1.0 if not prev else len(set(picks) - prev) / top_n
        cost = turnover * 2 * cost_bps / 1e4            # buy the new, sell the old
        gross = float(fwd[picks].mean())
        rows.append({
            "Date": date, "Gross": gross, "Strategy": gross - cost,
            "Universe": float(fwd[list(scores)].mean()), "Turnover": turnover,
            "Benchmark": (float(bench_close.asof(closes.index[i + step]) / bench_close.asof(date) - 1)
                          if bench_close is not None and len(bench_close) else np.nan),
            "Picks": ", ".join(p.replace(".NS", "") for p in picks[:5]),
        })
        prev = set(picks)
        for s in scores:
            samples.append({"date": date, "sym": s, "score": scores[s], "fwd": float(fwd[s]),
                            **{f"g_{k}": v for k, v in groups[s].items()}})
    periods = pd.DataFrame(rows)
    smp = pd.DataFrame(samples)
    if periods.empty:
        return BacktestResult(periods, smp, n_syms=len(hist))
    periods["Excess"] = periods["Strategy"] - periods["Universe"]
    m = {"strategy": perf_metrics(periods["Strategy"], step, rf_annual),
         "universe": perf_metrics(periods["Universe"], step, rf_annual)}
    if periods["Benchmark"].notna().any():
        m["benchmark"] = perf_metrics(periods["Benchmark"], step, rf_annual)
    m["beat_universe_pct"] = float((periods["Excess"] > 0).mean() * 100)
    m["avg_turnover"] = float(periods["Turnover"].mean())
    m["cost_drag_pa"] = float((periods["Gross"] - periods["Strategy"]).mean() * 252 / step)
    half = len(periods) // 2
    if half >= 4:
        m["in_sample"] = perf_metrics(periods["Strategy"].iloc[:half], step, rf_annual)
        m["out_sample"] = perf_metrics(periods["Strategy"].iloc[half:], step, rf_annual)
        m["in_sample"]["excess_pa"] = float(periods["Excess"].iloc[:half].mean() * 252 / step)
        m["out_sample"]["excess_pa"] = float(periods["Excess"].iloc[half:].mean() * 252 / step)
    return BacktestResult(periods, smp, m, calibration_table(smp), signal_lab(smp), len(hist))


# ------------------------------------------------------------------ persistence
def save_calibration(cal: pd.DataFrame, market: str, step: int) -> None:
    if cal is None or cal.empty:
        return
    try:
        _CAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(_CAL_FILE.read_text()) if _CAL_FILE.exists() else {}
        data[market] = {"step": step, "rows": cal.reset_index().to_dict("records"),
                        "saved": pd.Timestamp.now("UTC").isoformat()}
        _CAL_FILE.write_text(json.dumps(data, default=float))
    except Exception:  # noqa: BLE001
        pass


def load_calibration(market: str) -> dict | None:
    try:
        return json.loads(_CAL_FILE.read_text()).get(market)
    except Exception:  # noqa: BLE001
        return None


def calibrated_statement(tech_score: float, market: str) -> str | None:
    """'Historically X% of stocks in this band were higher 21d later (n=…; base Y%)'."""
    cal = load_calibration(market)
    if not cal:
        return None
    band = _band(tech_score)
    for r in cal["rows"]:
        if r.get("Band") == band and r.get("n", 0) >= 30:
            return (f"Historically, {r['p_up'] * 100:.0f}% of large-caps in the “{band}” technical band were higher "
                    f"{cal['step']} trading days later (avg {r['mean_ret'] * 100:+.1f}%, n={int(r['n'])}; "
                    f"all stocks: {r['base_p_up'] * 100:.0f}%). A past frequency, not a forecast.")
    return None


def save_weights(w: dict[str, float]) -> None:
    try:
        _WEIGHT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _WEIGHT_FILE.write_text(json.dumps(w))
    except Exception:  # noqa: BLE001
        pass


def load_weights() -> dict[str, float] | None:
    try:
        return json.loads(_WEIGHT_FILE.read_text())
    except Exception:  # noqa: BLE001
        return None
