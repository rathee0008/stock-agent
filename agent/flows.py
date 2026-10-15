"""Institutional-flow data for the Movers page (India).

All sources are NSE's public files/APIs. They are bot-protected and sometimes refuse
non-Indian hosts, so every function is best-effort: it returns an empty frame on
failure (and logs why) and the page degrades to the news-based feed.

  * delivery %      : sec_bhavdata_full_<DDMMYYYY>.csv  (nsearchives.nseindia.com)
  * bulk / block    : bulk.csv / block.csv               (nsearchives.nseindia.com)
  * FII / DII cash  : /api/fiidiiTradeReact              (needs a browser-like session)

Parsers are separate pure functions so they can be tested offline.
"""

from __future__ import annotations

import datetime as _dt
import io

import pandas as pd
import requests

from . import log, nse_live

_ARCH = "https://nsearchives.nseindia.com"
_UA = nse_live._UA


# ------------------------------------------------------------------ parsers
def parse_bhavcopy(text: str) -> pd.DataFrame:
    """sec_bhavdata_full csv -> Symbol, Delivery %, Traded qty, Delivered qty (EQ series only)."""
    df = pd.read_csv(io.StringIO(text), skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    if not {"SYMBOL", "SERIES", "DELIV_PER"} <= set(df.columns):
        return pd.DataFrame()
    df = df[df["SERIES"].str.strip() == "EQ"].copy()
    df["DELIV_PER"] = pd.to_numeric(df["DELIV_PER"], errors="coerce")
    df["TTL_TRD_QNTY"] = pd.to_numeric(df.get("TTL_TRD_QNTY"), errors="coerce")
    df["DELIV_QTY"] = pd.to_numeric(df.get("DELIV_QTY"), errors="coerce")
    out = pd.DataFrame({
        "Symbol": df["SYMBOL"].str.strip() + ".NS",
        "Delivery %": df["DELIV_PER"],
        "Traded qty": df["TTL_TRD_QNTY"],
        "Delivered qty": df["DELIV_QTY"],
        "Date": df["DATE1"].str.strip() if "DATE1" in df else None,
    })
    return out.dropna(subset=["Delivery %"]).reset_index(drop=True)


def parse_deals(text: str, kind: str) -> pd.DataFrame:
    """NSE bulk.csv / block.csv -> tidy frame."""
    df = pd.read_csv(io.StringIO(text), skipinitialspace=True)
    df.columns = [c.strip() for c in df.columns]
    ren = {"Symbol": "Symbol", "Client Name": "Client", "Buy/Sell": "Side", "Buy/Sell ": "Side",
           "Quantity Traded": "Qty", "Trade Price / Wght. Avg. Price": "Price", "Date": "Date",
           "Security Name": "Name"}
    df = df.rename(columns={k: v for k, v in ren.items() if k in df.columns})
    need = {"Symbol", "Client", "Side", "Qty", "Price"}
    if not need <= set(df.columns):
        return pd.DataFrame()
    for c in ("Qty", "Price"):
        df[c] = pd.to_numeric(df[c].astype(str).str.replace(",", ""), errors="coerce")
    df["Side"] = df["Side"].astype(str).str.strip().str.upper().map(lambda x: "BUY" if x.startswith("B") else "SELL")
    df["Value (Cr)"] = df["Qty"] * df["Price"] / 1e7
    df["Symbol"] = df["Symbol"].astype(str).str.strip() + ".NS"
    df["Kind"] = kind
    keep = [c for c in ("Date", "Symbol", "Name", "Client", "Side", "Qty", "Price", "Value (Cr)", "Kind") if c in df.columns]
    return df[keep].dropna(subset=["Qty"]).sort_values("Value (Cr)", ascending=False).reset_index(drop=True)


def parse_fii_dii(payload: list[dict]) -> pd.DataFrame:
    rows = []
    for r in payload or []:
        try:
            rows.append({"Category": r.get("category"), "Date": r.get("date"),
                         "Buy (Cr)": float(str(r.get("buyValue")).replace(",", "")),
                         "Sell (Cr)": float(str(r.get("sellValue")).replace(",", "")),
                         "Net (Cr)": float(str(r.get("netValue")).replace(",", ""))})
        except (TypeError, ValueError):
            continue
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ fetchers
def _get(url: str, timeout: int = 15) -> str:
    r = requests.get(url, headers={"User-Agent": _UA, "Accept": "*/*"}, timeout=timeout)
    r.raise_for_status()
    return r.text


def delivery(max_back: int = 7, today: _dt.date | None = None) -> pd.DataFrame:
    """Latest available delivery-% bhavcopy (walks back over weekends/holidays)."""
    d = today or _dt.date.today()
    for _ in range(max_back):
        d_try, d = d, d - _dt.timedelta(days=1)
        if d_try.weekday() >= 5:
            continue
        url = f"{_ARCH}/products/content/sec_bhavdata_full_{d_try:%d%m%Y}.csv"
        try:
            df = parse_bhavcopy(_get(url))
        except Exception as exc:  # noqa: BLE001
            log.record("flows:bhavcopy", f"{d_try}: {exc}", "debug")
            continue
        if not df.empty:
            log.mark_ok("flows:bhavcopy", str(d_try))
            df["As of"] = d_try
            return df
    log.record("flows:bhavcopy", "no bhavcopy reachable (NSE may block this host)")
    return pd.DataFrame()


def deals() -> pd.DataFrame:
    frames = []
    for kind, path in (("BULK", "bulk.csv"), ("BLOCK", "block.csv")):
        try:
            f = parse_deals(_get(f"{_ARCH}/content/equities/{path}"), kind)
            if not f.empty:
                frames.append(f)
        except Exception as exc:  # noqa: BLE001
            log.record(f"flows:{kind.lower()}", exc)
    if not frames:
        return pd.DataFrame()
    log.mark_ok("flows:deals")
    return pd.concat(frames, ignore_index=True).sort_values("Value (Cr)", ascending=False).reset_index(drop=True)


def fii_dii() -> pd.DataFrame:
    try:
        s = nse_live._new_session("RELIANCE")
        r = s.get("https://www.nseindia.com/api/fiidiiTradeReact", timeout=10,
                  headers={"Accept": "application/json", "X-Requested-With": "XMLHttpRequest",
                           "Referer": "https://www.nseindia.com/reports/fii-dii"})
        r.raise_for_status()
        df = parse_fii_dii(r.json())
        if not df.empty:
            log.mark_ok("flows:fii_dii")
        return df
    except Exception as exc:  # noqa: BLE001
        log.record("flows:fii_dii", exc)
        return pd.DataFrame()


def deals_by_symbol(df: pd.DataFrame) -> dict[str, str]:
    """Symbol -> one-line summary of the largest deal, for the 'why moving' tags."""
    out: dict[str, str] = {}
    if df is None or df.empty:
        return out
    for sym, g in df.groupby("Symbol"):
        top = g.iloc[0]
        out[sym] = f"{top['Kind'].title()} deal: {top['Client']} {top['Side'].lower()} ₹{top['Value (Cr)']:.0f} Cr"
    return out
