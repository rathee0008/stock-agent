"""Where big money is moving: deal headlines (both markets) + US insider transactions.

India's NSE/BSE bulk/block-deal APIs are bot-protected, so India deal flow comes
from Google News RSS searches for those events. US uses Yahoo's Form-4 insider data.
"""

from __future__ import annotations

import concurrent.futures as cf
import email.utils
import urllib.parse
import xml.etree.ElementTree as ET

import pandas as pd
import requests
import yfinance as yf

from .universe import US

_QUERIES = {
    "IN": ["bulk deal NSE shares stake sold bought", "block deal Nifty Sensex stock stake", "acquires stake crore shares NSE",
           "FII DII buying stake stock market India", "mutual fund picks up stake shares crore"],
    "US": ["acquires stake billion shares NYSE Nasdaq", "13F new position stake hedge fund buys shares",
           "activist investor stake stock", "invests billion stake in company shares jump"],
}
_LOCALE = {"IN": "hl=en-IN&gl=IN&ceid=IN:en", "US": "hl=en-US&gl=US&ceid=US:en"}


def _rss(query: str, market: str, days: int) -> list[dict]:
    q = urllib.parse.quote(f"{query} when:{days}d")
    r = requests.get(f"https://news.google.com/rss/search?q={q}&{_LOCALE[market]}",
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
    r.raise_for_status()
    out = []
    for it in ET.fromstring(r.content).iter("item"):
        t = it.findtext("title") or ""
        src = it.findtext("source") or ""
        out.append({"Headline": t.rsplit(" - ", 1)[0], "Source": src, "Link": it.findtext("link"),
                    "Published": pd.to_datetime(email.utils.parsedate_to_datetime(it.findtext("pubDate")), utc=True),
                    "Topic": query})
    return out


def deal_headlines(market: str, days: int = 7, limit: int = 40) -> pd.DataFrame:
    rows: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for f in [ex.submit(_rss, q, market, days) for q in _QUERIES[market]]:
            try:
                rows += f.result()
            except Exception:  # noqa: BLE001
                pass
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows).drop_duplicates("Headline").sort_values("Published", ascending=False)
    return df.head(limit).reset_index(drop=True)


def _insider(sym: str, days: int) -> list[dict]:
    df = yf.Ticker(sym).insider_transactions
    if df is None or df.empty:
        return []
    df = df[pd.to_datetime(df["Start Date"]) >= pd.Timestamp.now() - pd.Timedelta(days=days)]
    out = []
    for _, r in df.iterrows():
        txt = str(r.get("Text", ""))
        kind = "BUY" if "purchase" in txt.lower() else "SELL" if "sale" in txt.lower() else None
        if kind and (r.get("Value") or 0) > 0:
            out.append({"Symbol": sym, "Insider": r.get("Insider"), "Role": r.get("Position"), "Type": kind,
                        "Shares": r.get("Shares"), "Value $": r.get("Value"), "Date": pd.to_datetime(r["Start Date"]).date()})
    return out


def us_insiders(days: int = 30) -> pd.DataFrame:
    rows: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for f in [ex.submit(_insider, s, days) for s in US if "-" not in s]:
            try:
                rows += f.result()
            except Exception:  # noqa: BLE001
                pass
    return pd.DataFrame(rows).sort_values("Value $", ascending=False).reset_index(drop=True) if rows else pd.DataFrame()
