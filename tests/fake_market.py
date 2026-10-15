"""Synthetic Yahoo/NSE stand-ins so the app can run offline (tests, screenshots)."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import yfinance as yf
from tests.conftest import make_ohlcv


def _seed(sym: str) -> int:
    return sum(ord(c) for c in sym) % 997


def fake_download(tickers, period="1y", interval="1d", **kw):
    syms = tickers if isinstance(tickers, (list, tuple)) else str(tickers).split()
    n = {"5d": 5, "3mo": 70, "6mo": 130, "1y": 260, "2y": 520, "5y": 1300, "6y": 1500}.get(period, 260)
    frames = {s: make_ohlcv(n, seed=_seed(s)) for s in syms}
    if len(syms) == 1 and not isinstance(tickers, (list, tuple)):
        return frames[syms[0]]
    return pd.concat(frames, axis=1)


class FakeTicker:
    def __init__(self, sym):
        self.sym = sym
        self.fast_info = {"last_price": 100.0, "previous_close": 99.0, "currency": "INR" if sym.endswith(".NS") else "USD"}
        self.news = [{"content": {"title": f"{sym} wins big order, profit jumps", "pubDate": "2026-10-14T08:00:00Z",
                                  "canonicalUrl": {"url": "http://x"}, "provider": {"displayName": "Wire"}}}]
        self.insider_transactions = None

    def history(self, period="1y", interval="1d", **kw):
        n = {"5d": 400, "1d": 75, "1mo": 22}.get(period, 520) if interval != "1d" else {"5d": 5, "1y": 260, "2y": 520, "5y": 1300, "6mo": 130, "3mo": 70}.get(period, 520)
        df = make_ohlcv(n, seed=_seed(self.sym))
        if interval != "1d":
            df.index = pd.date_range(end="2026-10-14 15:25", periods=n, freq="5min", tz="Asia/Kolkata")
        return df

    def get_info(self):
        return {"shortName": self.sym, "longName": f"{self.sym} Ltd", "trailingPE": 22.0 + _seed(self.sym) % 20, "forwardPE": 19.0,
                "returnOnEquity": 0.18, "profitMargins": 0.14, "operatingMargins": 0.2, "debtToEquity": 40.0,
                "revenueGrowth": 0.12, "earningsGrowth": 0.15, "priceToBook": 4.0, "sector": "Technology",
                "marketCap": 1e12, "currency": self.fast_info["currency"], "targetMeanPrice": 120.0,
                "recommendationKey": "buy", "currentPrice": 100.0, "regularMarketPreviousClose": 99.0}

    def get_income_stmt(self, **k): return pd.DataFrame()
    def get_balance_sheet(self, **k): return pd.DataFrame()


def _no_net(*a, **k):
    import requests

    raise requests.ConnectionError("network disabled (fake market)")


def install():
    import requests

    yf.download = fake_download
    yf.Ticker = FakeTicker
    requests.get = _no_net
    requests.Session.get = lambda self, *a, **k: _no_net()
    requests.post = _no_net





