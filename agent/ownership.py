"""Ownership / institutional-holding data.

India: FII (Foreign Institutional/Portfolio Investors) vs DII (Domestic
Institutional Investors) shareholding %, sourced from BSE's public
shareholding-pattern API — the same JSON the bseindia.com shareholding-
pattern page itself renders from, unauthenticated. (NSE's equivalent API
sits behind Akamai bot-detection and refuses plain requests; BSE's does
not, so BSE is the source here. Every NSE-listed company is also listed
on BSE, so this covers NSE names too.)

US: there is no FII/DII split for US equities. Instead we surface Yahoo
Finance's institutional/insider ownership (via yfinance) — the closest
analog, presented under its own label rather than forced into FII/DII
terms.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

import pandas as pd
import requests
import yfinance as yf

_BSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.bseindia.com/",
    "Origin": "https://www.bseindia.com",
}

# Common large-caps — skip the search round-trip for the obvious ones.
_BSE_SCRIPCODE = {
    "RELIANCE": "500325", "TCS": "532540", "INFY": "500209", "HDFCBANK": "500180",
    "ICICIBANK": "532174", "SBIN": "500112", "ITC": "500875", "LT": "500510",
    "BHARTIARTL": "532454", "HINDUNILVR": "500696", "KOTAKBANK": "500247",
    "AXISBANK": "532215", "MARUTI": "532500", "TATAMOTORS": "500570",
    "TATASTEEL": "500470", "WIPRO": "507685", "SUNPHARMA": "524715",
    "ASIANPAINT": "500820", "BAJFINANCE": "500034", "TITAN": "500114",
    "ADANIENT": "512599", "NTPC": "532555", "ONGC": "500312", "POWERGRID": "532898",
}

_session = requests.Session()
_session.headers.update(_BSE_HEADERS)


def _get(url: str, params: dict | None = None, tries: int = 3):
    last: Exception | None = None
    for i in range(tries):
        try:
            r = _session.get(url, params=params, timeout=12)
            r.raise_for_status()
            return r.json()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(0.8 * (i + 1))
    raise LookupError(f"BSE request failed for {url}: {last}")


def bse_scripcode(nse_symbol: str) -> str | None:
    """Resolve a plain NSE symbol (e.g. RELIANCE) to its BSE scrip code."""
    sym = re.sub(r"\.(NS|BO)$", "", nse_symbol.strip().upper()).lstrip("^")
    if sym in _BSE_SCRIPCODE:
        return _BSE_SCRIPCODE[sym]
    try:
        r = _session.get(
            "https://api.bseindia.com/BseIndiaAPI/api/PeerSmartSearch/w",
            params={"Type": "SS", "text": sym, "flag": "site"},
            timeout=10,
        )
        r.raise_for_status()
        html = r.text
        codes = re.findall(r"liclick\('(\d+)','([^']+)'\)", html)
        for code, _name in codes:
            snippet = html.split(f"liclick('{code}'", 1)[1][:400]
            m = re.search(r"<strong>([A-Z0-9]+)</strong>", snippet)
            if m and m.group(1) == sym:
                return code
        return codes[0][0] if codes else None
    except Exception:
        return None


@dataclass
class FiiDiiTrend:
    scripcode: str
    quarters: pd.DataFrame = field(default_factory=pd.DataFrame)
    available: bool = True


def _quarter_list(scripcode: str, limit: int) -> list[dict]:
    data = _get(
        "https://api.bseindia.com/BseIndiaAPI/api/SHPQNewFormat/w",
        params={"scripcode": scripcode},
    )
    return (data.get("Table") or [])[:limit]


def _quarter_breakdown(scripcode: str, qtrid: float) -> dict[str, float]:
    pub = _get(
        "https://api.bseindia.com/BseIndiaAPI/api/Corp_shpSec_SHPPubShold_ng/w",
        params={"SCRIPCODE": scripcode, "QtrCode": f"{qtrid:.2f}"},
    )
    out = {"dii": 0.0, "fii": 0.0, "government": 0.0, "non_institutional": 0.0}
    for row in pub.get("Table1", []):
        lvl = (row.get("Fld_Level") or "").strip()
        pct = row.get("Fld_TotalPercentageOf_A_B_C2") or 0.0
        if lvl == "Sub Total B1":
            out["dii"] = pct
        elif lvl == "Sub Total B2":
            out["fii"] = pct
        elif lvl == "Sub Total B3":
            out["government"] = pct
        elif lvl == "Sub Total B4":
            out["non_institutional"] = pct

    summary = _get(
        "https://api.bseindia.com/BseIndiaAPI/api/CorporatesSHPSecuritybeta/w",
        params={"scripcode": scripcode, "qtrid": f"{qtrid:.2f}"},
    )
    promoter = 0.0
    for row in summary.get("Table1", []):
        if str(row.get("Fld_ShortName", "")).startswith("(A)"):
            promoter = row.get("Fld_TotalPercentageOf_A_B_C2") or 0.0
    out["promoter"] = promoter
    return out


def fii_dii_trend(nse_symbol: str, quarters: int = 8) -> FiiDiiTrend:
    """Last ``quarters`` of promoter/DII/FII/government/non-institutional %
    for an NSE/BSE-listed company, oldest first.
    """
    scripcode = bse_scripcode(nse_symbol)
    if not scripcode:
        return FiiDiiTrend(scripcode="", available=False)

    qlist = _quarter_list(scripcode, quarters)
    rows = []
    for q in qlist:
        try:
            b = _quarter_breakdown(scripcode, float(q["qtrid"]))
        except Exception:
            continue
        rows.append({"quarter": q["qtr"], "qtrid": q["qtrid"], **b})

    if not rows:
        return FiiDiiTrend(scripcode=scripcode, available=False)

    df = pd.DataFrame(rows).iloc[::-1].reset_index(drop=True)  # oldest -> newest
    return FiiDiiTrend(scripcode=scripcode, quarters=df, available=True)


@dataclass
class UsOwnership:
    top_institutions: pd.DataFrame = field(default_factory=pd.DataFrame)
    pct_institutions: float | None = None
    pct_insiders: float | None = None
    holder_count: int | None = None
    available: bool = True


def us_institutional_ownership(ticker: str) -> UsOwnership:
    """Institutional/insider ownership for a US ticker, via yfinance
    (Yahoo Finance) — the closest available analog to FII/DII for US names.
    """
    try:
        tk = yf.Ticker(ticker)
        holders = tk.institutional_holders
        major = tk.major_holders
    except Exception:
        return UsOwnership(available=False)

    pct_inst = pct_ins = None
    holder_count = None
    if major is not None and not major.empty:
        val_col = major.columns[0]
        for label, row in major.iterrows():
            key = str(label)
            v = row[val_col]
            if key == "institutionsPercentHeld":
                pct_inst = float(v) * 100
            elif key == "insidersPercentHeld":
                pct_ins = float(v) * 100
            elif key == "institutionsCount":
                holder_count = int(v)

    if holders is None:
        holders = pd.DataFrame()
    elif "pctHeld" in holders.columns:
        holders = holders.copy()
        holders["pctHeld"] = holders["pctHeld"] * 100

    available = not holders.empty or pct_inst is not None
    return UsOwnership(
        top_institutions=holders,
        pct_institutions=pct_inst,
        pct_insiders=pct_ins,
        holder_count=holder_count,
        available=available,
    )
