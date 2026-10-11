"""Where big money is moving: deal headlines (both markets) + US insider transactions.

India's NSE/BSE bulk/block-deal APIs are bot-protected, so India deal flow comes
from Google News RSS searches for those events. US uses Yahoo's Form-4 insider data.
"""

from __future__ import annotations

import concurrent.futures as cf
import email.utils
import os
import threading
import time
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
        low = txt.lower()
        kind = ("BUY" if ("purchase" in low or "buy" in low)
                else "SELL" if ("sale" in low or "sell" in low) else None)
        if kind:  # keep rows even when Yahoo leaves Value empty
            out.append({"Symbol": sym, "Insider": r.get("Insider"), "Role": r.get("Position"), "Type": kind,
                        "Shares": r.get("Shares"), "Value $": r.get("Value"), "Date": pd.to_datetime(r["Start Date"]).date()})
    return out


_SEC_UA = os.environ.get(
    "SEC_USER_AGENT",
    "stock-agent research app (https://github.com/rathee0008/stock-agent)",
)
_sec_lock = threading.Lock()
_sec_last = [0.0]
_CIK: dict[str, str] = {}
_ERRS: list[str] = []


def _sec_get(url: str, as_json: bool = False):
    """GET from SEC EDGAR, throttled to ~8 req/s across threads (limit is 10/s)."""
    with _sec_lock:
        wait = 0.125 - (time.time() - _sec_last[0])
        if wait > 0:
            time.sleep(wait)
        _sec_last[0] = time.time()
    r = requests.get(url, headers={"User-Agent": _SEC_UA}, timeout=15)
    r.raise_for_status()
    return r.json() if as_json else r.content


def _cik_for(sym: str) -> str | None:
    if not _CIK:
        data = _sec_get("https://www.sec.gov/files/company_tickers.json", as_json=True)
        for v in data.values():
            _CIK[str(v["ticker"]).upper()] = str(v["cik_str"]).zfill(10)
    return _CIK.get(sym.upper())


def _txt(node, path: str) -> str:
    el = node.find(path) if node is not None else None
    return (el.text or "").strip() if el is not None else ""


def _num(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _edgar_insider(sym: str, days: int, max_filings: int = 6) -> list[dict]:
    """Open-market buys (code P) and sells (code S) from recent SEC Form 4 filings."""
    cik = _cik_for(sym)
    if not cik:
        return []
    sub = _sec_get(f"https://data.sec.gov/submissions/CIK{cik}.json", as_json=True)
    rec = sub.get("filings", {}).get("recent", {})
    cutoff = (pd.Timestamp.now() - pd.Timedelta(days=days)).date()
    out: list[dict] = []
    seen = 0
    for form, fdate, acc, doc in zip(rec.get("form", []), rec.get("filingDate", []),
                                     rec.get("accessionNumber", []),
                                     rec.get("primaryDocument", [])):
        if form != "4":
            continue
        if pd.to_datetime(fdate).date() < cutoff:
            break  # the list is newest-first
        seen += 1
        if seen > max_filings:
            break
        raw_doc = doc.rsplit("/", 1)[-1]  # strip the xslF345X0N/ rendered-HTML prefix
        url = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}/{raw_doc}"
        try:
            root = ET.fromstring(_sec_get(url))
        except Exception as exc:  # noqa: BLE001
            _ERRS.append(f"{sym} form4: {type(exc).__name__}: {exc}"[:160])
            continue
        owner = _txt(root, "reportingOwner/reportingOwnerId/rptOwnerName")
        rel = root.find("reportingOwner/reportingOwnerRelationship")
        role = _txt(rel, "officerTitle")
        if not role and _txt(rel, "isDirector") in ("1", "true"):
            role = "Director"
        if not role and _txt(rel, "isTenPercentOwner") in ("1", "true"):
            role = "10% owner"
        for t in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
            kind = {"P": "BUY", "S": "SELL"}.get(_txt(t, "transactionCoding/transactionCode"))
            if not kind:
                continue
            shares = _num(_txt(t, "transactionAmounts/transactionShares/value"))
            price = _num(_txt(t, "transactionAmounts/transactionPricePerShare/value"))
            tdate = _txt(t, "transactionDate/value") or fdate
            out.append({
                "Symbol": sym, "Insider": owner, "Role": role, "Type": kind,
                "Shares": shares,
                "Value $": shares * price if shares is not None and price is not None else None,
                "Date": pd.to_datetime(tdate).date(),
            })
    return out


def us_insiders(days: int = 30) -> pd.DataFrame:
    """US insider buys/sells. Source: SEC EDGAR Form 4 (Yahoo's insider feed is
    unreliable from cloud hosts); falls back to Yahoo if EDGAR returns nothing."""
    syms = [s for s in US if "-" not in s]
    _ERRS.clear()
    rows: list[dict] = []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for f in [ex.submit(_edgar_insider, s, days) for s in syms]:
            try:
                rows += f.result()
            except Exception as exc:  # noqa: BLE001
                _ERRS.append(f"EDGAR: {type(exc).__name__}: {exc}"[:160])
    if not rows:
        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            for f in [ex.submit(_insider, s, days) for s in syms]:
                try:
                    rows += f.result()
                except Exception:  # noqa: BLE001
                    pass
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("Value $", ascending=False).reset_index(drop=True)


def last_errors() -> list[str]:
    """Distinct recent EDGAR errors, for on-page diagnostics when no trades return."""
    return list(dict.fromkeys(_ERRS))[:4]
