"""Screener with saved filters: filter the scored universe, save/load presets as JSON or in the URL."""

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import cache, screener, theme as T, ui  # noqa: E402
from agent.presets import PRESETS  # noqa: E402

ui.setup("Screener", "🔍")

# Strategy presets live in agent/presets.py (shared with the Top 20 page and the daily job).
DEFAULT = PRESETS["Quality momentum"]

ui.sidebar_brand()
saved = st.session_state.setdefault("saved_filters", {})
qp = st.query_params.get("f")
if qp and "f_loaded" not in st.session_state:
    try:
        st.session_state["f"] = json.loads(qp)
    except Exception:  # noqa: BLE001
        pass
    st.session_state["f_loaded"] = True
cur = st.session_state.get("f", DEFAULT)

T.sidebar_head("Load")
choice = st.sidebar.selectbox("Preset", ["(current)"] + list(PRESETS) + list(saved), label_visibility="collapsed")
if choice != "(current)" and st.session_state.get("_last_choice") != choice:
    cur = PRESETS.get(choice) or saved[choice]
    st.session_state["f"] = cur
    st.session_state["_last_choice"] = choice
up = st.sidebar.file_uploader("…or upload filters (JSON)", type="json")
if up is not None and st.session_state.get("_up") != up.name:
    try:
        cur = json.load(up)
        st.session_state["f"], st.session_state["_up"] = cur, up.name
    except Exception:  # noqa: BLE001
        st.sidebar.error("Not a valid filters file.")

T.sidebar_head("Filters")
market = st.sidebar.radio("Market", ["Both", "India", "US"], index=["Both", "India", "US"].index(cur.get("market", "Both")), horizontal=True)
min_score = st.sidebar.slider("Min composite score", -100, 100, int(cur.get("min_score", 15)))
min_fund = st.sidebar.slider("Min fundamental score", -100, 100, int(cur.get("min_fund", 0)))
rsi_lo, rsi_hi = st.sidebar.slider("RSI between", 0, 100, tuple(cur.get("rsi", [0, 100])))
max_pe = st.sidebar.slider("Max P/E", 5, 200, int(cur.get("max_pe", 200)))
min_roe = st.sidebar.slider("Min ROE %", -50, 60, int(cur.get("min_roe", -50)))
min_rev = st.sidebar.slider("Min revenue growth %", -100, 100, int(cur.get("min_rev", -100)))
min_3m = st.sidebar.slider("Min 3-month return %", -100, 100, int(cur.get("min_3m", -100)))
min_upside = st.sidebar.slider("Min analyst upside %", -100, 100, int(cur.get("min_upside", -100)))
min_cap = st.sidebar.slider("Min market cap (bn, local ccy)", 0, 500, int(cur.get("min_cap", 0)))
analyst = st.sidebar.multiselect("Analyst rating (empty = any)", ["strong_buy", "buy", "hold", "underperform", "sell"],
                                 default=[a for a in cur.get("analyst", []) if a in ["strong_buy", "buy", "hold", "underperform", "sell"]])
T.sidebar_head("Blend weights")
w = (st.sidebar.slider("Technical", 0.0, 1.0, 0.40, 0.05), st.sidebar.slider("Fundamental", 0.0, 1.0, 0.45, 0.05),
     st.sidebar.slider("News", 0.0, 1.0, 0.15, 0.05))


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _rank(m: str, weights: tuple, b: int):
    return screener.rank(m, weights)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _both(weights: tuple, b: int):
    import concurrent.futures as cf

    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        fi, fu = ex.submit(screener.rank, "IN", weights), ex.submit(screener.rank, "US", weights)
        return pd.concat([fi.result(), fu.result()], ignore_index=True)


ui.hero("Screener", "Filter ~120 scored India + US large-caps by score, RSI, valuation and profitability, then save the "
        "filter set to reuse it.", pills=[("Delayed data", "amber"), ("Not advice", "flat")])
with st.spinner("Scoring the universe (about a minute on first load)…"):
    b = cache.bucket("IN", 6)
    if market == "India":
        df = _rank("IN", w, b)
    elif market == "US":
        df = _rank("US", w, cache.bucket("US", 6))
    else:
        df = _both(w, b)

# sectors depend on the loaded universe
all_sectors = sorted({s for s in df.get("Sector", pd.Series(dtype=str)).dropna() if s and s != "—"})
sel_sectors = st.sidebar.multiselect("Sectors (empty = all)", all_sectors, default=[s for s in cur.get("sectors", []) if s in all_sectors])

filters = {"market": market, "min_score": min_score, "min_fund": min_fund, "rsi": [rsi_lo, rsi_hi],
           "max_pe": max_pe, "min_roe": min_roe, "min_rev": min_rev, "min_3m": min_3m, "min_upside": min_upside,
           "analyst": analyst, "min_cap": min_cap, "sectors": sel_sectors}
st.session_state["f"] = filters
try:
    st.query_params["f"] = json.dumps(filters, separators=(",", ":"))
except Exception:  # noqa: BLE001
    pass

out = df.copy()
out = out[out["Score"] >= min_score]
out = out[out["Fundamental"] >= min_fund]
out = out[out["RSI"].between(rsi_lo, rsi_hi) | out["RSI"].isna()]
out = out[out["P/E"].isna() | (out["P/E"] <= max_pe)] if max_pe < 200 else out
out = out[out["ROE %"].isna() | (out["ROE %"] >= min_roe)] if min_roe > -50 else out
if min_rev > -100:
    out = out[out["Rev growth %"].notna() & (out["Rev growth %"] >= min_rev)]
if min_3m > -100:
    out = out[out["3M %"].notna() & (out["3M %"] >= min_3m)]
if min_upside > -100:
    out = out[out["Upside %"].notna() & (out["Upside %"] >= min_upside)]
if min_cap > 0:
    out = out[out["Mkt cap"].notna() & (out["Mkt cap"] >= min_cap * 1e9)]
if analyst:
    out = out[out["Analyst"].isin(analyst)]
if sel_sectors:
    out = out[out["Sector"].isin(sel_sectors)]
out = out.sort_values("Score", ascending=False).reset_index(drop=True)

k = st.columns(3)
T.kpi(k[0], "Matches", f"{len(out)}", f"of {len(df)} scored", "amber")
T.kpi(k[1], "Avg score", f"{out['Score'].mean():+.1f}" if len(out) else "—", "matches", T.sign_tone(out["Score"].mean() if len(out) else 0))
T.kpi(k[2], "Avg P/E", f"{out['P/E'].mean():.1f}" if len(out) and out["P/E"].notna().any() else "—", "matches", "flat")
st.markdown("<div style='height:.6rem'></div>", unsafe_allow_html=True)

if out.empty:
    ui.empty_note("<b>No stocks match.</b> Loosen a filter, or load a preset from the left rail.")
else:
    st.dataframe(
        out[["Market", "Symbol", "Name", "Sector", "Price", "Day %", "3M %", "Score", "Technical", "Fundamental",
             "News", "P/E", "ROE %", "Rev growth %", "RSI", "Analyst", "Upside %"]],
        use_container_width=True, height=620, hide_index=True,
        column_config={"Score": st.column_config.ProgressColumn("Score", min_value=-100, max_value=100, format="%.1f"),
                       **{c: st.column_config.NumberColumn(c, format="%.1f") for c in ["Day %", "3M %", "P/E", "ROE %", "Rev growth %", "RSI", "Upside %", "Price"]}},
    )
    st.download_button("Download results (CSV)", out.drop(columns=["Why"], errors="ignore").to_csv(index=False).encode(), "screen.csv", "text/csv")

T.rule("Save this filter set")
c1, c2, c3 = st.columns([2, 1, 1])
name = c1.text_input("Name", placeholder="e.g. My value screen", label_visibility="collapsed")
if c2.button("Save in this session", disabled=not name.strip()):
    saved[name.strip()] = filters
    st.success(f"Saved “{name.strip()}”. It appears in the Preset list until you close the tab.")
c3.download_button("Download filters", json.dumps(filters, indent=2), "filters.json", "application/json")
st.caption("Saved sets live only in this browser session. To keep them: download the JSON and upload it next time, or "
           "bookmark this page, because the current filters are stored in the page URL.")
ui.footer()
