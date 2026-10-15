"""Portfolio maths: FIFO lots, realised/unrealised P&L, Indian capital-gains tax estimate,
risk (correlation, beta, VaR) and ATR-based position sizing.

Pure functions over plain data so they can be unit-tested. Nothing here fetches prices.

Tax constants are editable (``IndiaTax``) because rates change with each Budget. Defaults
reflect listed-equity rules in force from 23 Jul 2024 (re-checked for FY 2026-27):
STCG 20%, LTCG 12.5% above ₹1.25 lakh a year, long-term = held more than 12 months,
plus 4% health & education cess. Surcharge is ignored. This is an estimate, not tax advice.
"""

from __future__ import annotations

import datetime as _dt
import math
from collections import defaultdict, deque
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


# ------------------------------------------------------------------ parsing
@dataclass
class Txn:
    side: str                  # BUY / SELL
    symbol: str                # Yahoo symbol
    qty: float
    price: float
    date: _dt.date | None = None


def parse_transactions(text: str, resolve=lambda s: s.upper()) -> tuple[list[Txn], list[str]]:
    """Parse portfolio text. Accepted lines (comma or space separated):

        BUY RELIANCE 10 2400 2024-06-03     dated purchase
        SELL RELIANCE 4 2900 2025-08-11     sale (needed for realised P&L / tax)
        RELIANCE 10 2400                    legacy: undated buy

    Returns ``(transactions, bad_lines)``. Transactions keep file order (FIFO uses dates when
    present, otherwise order).
    """
    txns: list[Txn] = []
    bad: list[str] = []
    for line in text.splitlines():
        parts = line.replace(",", " ").split()
        if not parts or parts[0].startswith("#"):
            continue
        try:
            if parts[0].upper() in ("BUY", "SELL"):
                side, sym, qty, px = parts[0].upper(), resolve(parts[1]), float(parts[2]), float(parts[3])
                d = _dt.date.fromisoformat(parts[4]) if len(parts) > 4 else None
            else:
                side, sym, qty, px, d = "BUY", resolve(parts[0]), float(parts[1]), float(parts[2]), None
            if qty <= 0 or px <= 0:
                raise ValueError
            txns.append(Txn(side, sym, qty, px, d))
        except (IndexError, ValueError):
            bad.append(line.strip())
    return txns, bad


# ------------------------------------------------------------------ FIFO
@dataclass
class Lot:
    symbol: str
    qty: float
    cost: float
    date: _dt.date | None


@dataclass
class Realised:
    symbol: str
    qty: float
    buy_price: float
    sell_price: float
    buy_date: _dt.date | None
    sell_date: _dt.date | None

    @property
    def pnl(self) -> float:
        return self.qty * (self.sell_price - self.buy_price)

    @property
    def days(self) -> int | None:
        if self.buy_date and self.sell_date:
            return (self.sell_date - self.buy_date).days
        return None


def fifo(txns: list[Txn]) -> tuple[list[Lot], list[Realised], list[str]]:
    """Match sells to the oldest buys. Returns (open lots, realised trades, warnings)."""
    ordered = sorted(enumerate(txns), key=lambda it: (it[1].date or _dt.date.min, it[0]))
    books: dict[str, deque[Lot]] = defaultdict(deque)
    realised: list[Realised] = []
    warns: list[str] = []
    for _, t in ordered:
        if t.side == "BUY":
            books[t.symbol].append(Lot(t.symbol, t.qty, t.price, t.date))
            continue
        need = t.qty
        book = books[t.symbol]
        while need > 1e-9 and book:
            lot = book[0]
            take = min(lot.qty, need)
            realised.append(Realised(t.symbol, take, lot.cost, t.price, lot.date, t.date))
            lot.qty -= take
            need -= take
            if lot.qty <= 1e-9:
                book.popleft()
        if need > 1e-9:
            warns.append(f"SELL {t.symbol}: {need:g} shares sold that were never bought in this list; ignored.")
    open_lots = [l for b in books.values() for l in b]
    return open_lots, realised, warns


def positions(open_lots: list[Lot]) -> dict[str, tuple[float, float]]:
    """Symbol -> (quantity, average cost) from open lots."""
    agg: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for l in open_lots:
        agg[l.symbol][0] += l.qty
        agg[l.symbol][1] += l.qty * l.cost
    return {s: (q, c / q) for s, (q, c) in agg.items() if q > 0}


# ------------------------------------------------------------------ tax
@dataclass
class IndiaTax:
    stcg_rate: float = 0.20
    ltcg_rate: float = 0.125
    ltcg_exempt: float = 125_000.0
    long_term_days: int = 365          # "more than 12 months"
    cess: float = 0.04


def is_indian(symbol: str) -> bool:
    return symbol.upper().endswith((".NS", ".BO"))


def fy_bounds(fy_start_year: int) -> tuple[_dt.date, _dt.date]:
    return _dt.date(fy_start_year, 4, 1), _dt.date(fy_start_year + 1, 3, 31)


def current_fy_start(today: _dt.date | None = None) -> int:
    t = today or _dt.date.today()
    return t.year if t.month >= 4 else t.year - 1


@dataclass
class TaxSummary:
    fy: str
    stcg: float = 0.0
    ltcg: float = 0.0
    ltcg_taxable: float = 0.0
    tax: float = 0.0
    foreign_gain: float = 0.0          # US/other shares: shown, not taxed here
    undated: int = 0                   # sells without dates, excluded
    rows: list[dict] = field(default_factory=list)


def tax_summary(realised: list[Realised], fy_start: int, rates: IndiaTax | None = None) -> TaxSummary:
    """STCG/LTCG for Indian-listed equity sold in the given financial year.

    Losses: STCG losses offset STCG then LTCG; LTCG losses offset LTCG only (carry-forward
    and the ₹1.25 lakh exemption interplay are simplified).
    """
    r = rates or IndiaTax()
    lo, hi = fy_bounds(fy_start)
    out = TaxSummary(fy=f"FY {fy_start}-{str(fy_start + 1)[2:]}")
    stcg = ltcg = 0.0
    for x in realised:
        if x.sell_date is None or x.buy_date is None:
            out.undated += 1
            continue
        if not (lo <= x.sell_date <= hi):
            continue
        term = "LONG" if x.days > r.long_term_days else "SHORT"
        india = is_indian(x.symbol)
        out.rows.append({"Symbol": x.symbol, "Qty": x.qty, "Bought": x.buy_date, "Sold": x.sell_date,
                         "Days": x.days, "P&L": x.pnl, "Term": term if india else "FOREIGN"})
        if not india:
            out.foreign_gain += x.pnl
        elif term == "LONG":
            ltcg += x.pnl
        else:
            stcg += x.pnl
    # loss set-off
    st_net, lt_net = stcg, ltcg
    if st_net < 0:
        lt_net += st_net          # short-term loss reduces long-term gains
        st_net = 0.0
    taxable_lt = max(lt_net - r.ltcg_exempt, 0.0) if lt_net > 0 else 0.0
    base = max(st_net, 0.0) * r.stcg_rate + taxable_lt * r.ltcg_rate
    out.stcg, out.ltcg, out.ltcg_taxable = stcg, ltcg, taxable_lt
    out.tax = base * (1 + r.cess)
    return out


def lots_turning_long_term(open_lots: list[Lot], prices: dict[str, float], within_days: int = 45,
                           today: _dt.date | None = None, rates: IndiaTax | None = None) -> list[dict]:
    """Indian lots with a gain that become long-term soon (a tax-planning nudge, not advice)."""
    r = rates or IndiaTax()
    t = today or _dt.date.today()
    out = []
    for l in open_lots:
        if not is_indian(l.symbol) or l.date is None or l.symbol not in prices:
            continue
        held = (t - l.date).days
        left = r.long_term_days + 1 - held
        gain = l.qty * (prices[l.symbol] - l.cost)
        if 0 < left <= within_days and gain > 0:
            out.append({"Symbol": l.symbol, "Qty": l.qty, "Days to long-term": left, "Unrealised gain": gain})
    return sorted(out, key=lambda x: x["Days to long-term"])


# ------------------------------------------------------------------ risk
def daily_returns(closes: pd.DataFrame) -> pd.DataFrame:
    return closes.sort_index().ffill().pct_change().dropna(how="all")


def correlation(closes: pd.DataFrame, min_obs: int = 60) -> pd.DataFrame:
    rets = daily_returns(closes).dropna(axis=1, thresh=min_obs)
    return rets.corr() if rets.shape[1] > 1 else pd.DataFrame()


def beta(asset_rets: pd.Series, bench_rets: pd.Series) -> float | None:
    df = pd.concat([asset_rets, bench_rets], axis=1, join="inner").dropna()
    if len(df) < 60 or df.iloc[:, 1].var() == 0:
        return None
    return float(df.iloc[:, 0].cov(df.iloc[:, 1]) / df.iloc[:, 1].var())


def portfolio_returns(closes: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    cols = [c for c in weights if c in closes]
    w = pd.Series({c: weights[c] for c in cols})
    w = w / w.sum()
    return daily_returns(closes[cols]).fillna(0.0).mul(w, axis=1).sum(axis=1)


def var_cvar(rets: pd.Series, conf: float = 0.95, horizon: int = 1) -> dict:
    """Historical and parametric (normal) VaR as positive loss fractions, plus CVaR.

    Horizon scaling uses sqrt(time), which understates risk in fat-tailed markets.
    """
    r = rets.dropna()
    if len(r) < 60:
        return {}
    q = float(np.quantile(r, 1 - conf))
    tail = r[r <= q]
    z = {0.90: 1.2816, 0.95: 1.6449, 0.99: 2.3263}.get(round(conf, 2), 1.6449)
    scale = math.sqrt(horizon)
    return {"hist_var": -q * scale, "cvar": -float(tail.mean()) * scale if len(tail) else float("nan"),
            "param_var": max(0.0, -(float(r.mean()) - z * float(r.std(ddof=1)))) * scale,
            "daily_vol": float(r.std(ddof=1)), "ann_vol": float(r.std(ddof=1)) * math.sqrt(252), "n": len(r)}


def risk_contributions(closes: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    """Each holding's share of total portfolio variance (sums to 1)."""
    cols = [c for c in weights if c in closes]
    rets = daily_returns(closes[cols]).dropna()
    if rets.shape[0] < 60 or len(cols) < 1:
        return pd.Series(dtype=float)
    w = np.array([weights[c] for c in cols], dtype=float)
    w = w / w.sum()
    cov = rets.cov().values
    port_var = float(w @ cov @ w)
    if port_var <= 0:
        return pd.Series(dtype=float)
    contrib = w * (cov @ w) / port_var
    return pd.Series(contrib, index=cols).sort_values(ascending=False)


def sector_concentration(values: dict[str, float], sectors: dict[str, str]) -> pd.Series:
    s = defaultdict(float)
    for sym, v in values.items():
        s[sectors.get(sym, "Other")] += v
    ser = pd.Series(s)
    return (ser / ser.sum()).sort_values(ascending=False) if ser.sum() else ser


def hhi(weights: pd.Series) -> float:
    """Herfindahl index 0..1 (1 = single stock). Effective number of holdings = 1 / HHI."""
    w = weights / weights.sum()
    return float((w ** 2).sum())


# ------------------------------------------------------------------ sizing
@dataclass
class Sizing:
    entry: float
    stop: float
    risk_per_share: float
    qty: int
    position_value: float
    risk_amount: float
    pct_of_capital: float
    capped: bool = False


def position_size(capital: float, risk_pct: float, entry: float, atr: float, atr_mult: float = 2.0,
                  max_position_pct: float = 25.0, side: str = "LONG", stop: float | None = None) -> Sizing | None:
    """Shares to buy so that hitting the stop loses ``risk_pct`` of capital.

    Stop defaults to ``entry -/+ atr_mult * ATR``. Quantity is capped so no position exceeds
    ``max_position_pct`` of capital.
    """
    if capital <= 0 or entry <= 0 or risk_pct <= 0:
        return None
    if stop is None:
        stop = entry - atr_mult * atr if side == "LONG" else entry + atr_mult * atr
    rps = abs(entry - stop)
    if rps <= 0 or (side == "LONG" and stop >= entry) or (side == "SHORT" and stop <= entry):
        return None
    risk_amt = capital * risk_pct / 100
    qty = int(risk_amt // rps)
    cap_qty = int((capital * max_position_pct / 100) // entry)
    capped = qty > cap_qty
    qty = max(min(qty, cap_qty), 0)
    val = qty * entry
    return Sizing(entry, stop, rps, qty, val, qty * rps, val / capital * 100, capped)
