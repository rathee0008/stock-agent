"""Top-20 investable stocks across India + US, ranked on technicals, fundamentals and news."""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import screener, tradingview as tv  # noqa: E402

st.set_page_config(page_title="Top 20 Picks", page_icon="🏆", layout="wide")
st.title("🏆 Top 20 Investable Stocks — India + US")
st.warning("⚠️ Not investment advice. Rule-based screen of ~120 large-caps on delayed Yahoo data; "
           "do your own research before investing.")

mode = st.sidebar.radio("List composition", ["Best 20 overall", "Balanced 10 India + 10 US"])
w_t = st.sidebar.slider("Technical", 0.0, 1.0, 0.40, 0.05)
w_f = st.sidebar.slider("Fundamental", 0.0, 1.0, 0.45, 0.05)
w_n = st.sidebar.slider("News", 0.0, 1.0, 0.15, 0.05)


@st.cache_data(ttl=1800, show_spinner=False)
def _rank(market, w):
    return screener.rank(market, w)


if st.sidebar.button("🔄 Refresh data"):
    st.cache_data.clear()

with st.spinner("Scanning both markets — fundamentals for ~120 stocks, takes ~1 minute on first load…"):
    w = (w_t, w_f, w_n)
    ind, us = _rank("IN", w), _rank("US", w)

if mode.startswith("Balanced"):
    top = pd.concat([ind.head(10), us.head(10)])
else:
    top = pd.concat([ind, us]).sort_values("Score", ascending=False).head(20)
top = top.reset_index(drop=True)
top.index += 1

st.dataframe(
    top[["Market", "Symbol", "Name", "Sector", "Price", "Day %", "3M %", "Score", "Technical", "Fundamental",
         "News", "P/E", "ROE %", "Rev growth %", "RSI", "Analyst", "Upside %"]],
    use_container_width=True, height=760,
    column_config={
        "Score": st.column_config.ProgressColumn("Score", min_value=-100, max_value=100, format="%.1f"),
        **{c: st.column_config.NumberColumn(c, format="%.1f") for c in
           ["Day %", "3M %", "P/E", "ROE %", "Rev growth %", "RSI", "Upside %", "Price"]},
    },
)
st.caption("Score = weighted blend of technical (trend, RSI, MACD, volume), fundamental (growth, ROE, margins, "
           "valuation, debt) and news tone, −100…+100. Stocks with RSI ≥ 80 (overheated) or weak fundamentals are excluded.")

st.subheader("Why they made the list")
for i, r in top.iterrows():
    with st.expander(f"#{i} {r['Symbol']} — {r['Name']}  ·  score {r['Score']}"):
        st.write(r["Why"] or "—")

st.subheader("📺 Live TradingView chart")
pick = st.selectbox("Symbol", top["Symbol"].tolist())
mk = top.set_index("Symbol").loc[pick, "Market"]
if mk == "IN":
    base = pick.replace(".NS", "")
    st.info("TradingView's free embed doesn't carry NSE data — open the live chart on TradingView.")
    st.link_button("Open on TradingView ↗", f"https://www.tradingview.com/chart/?symbol=NSE:{base}")
else:
    import streamlit.components.v1 as components
    components.html(tv.widget_html(pick.replace("-", "."), height=620), height=640)
