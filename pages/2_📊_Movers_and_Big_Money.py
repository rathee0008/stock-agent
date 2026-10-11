"""Top gainers/losers and where big money is moving (US + India)."""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import bigmoney, screener  # noqa: E402

st.set_page_config(page_title="Movers and Big Money", page_icon="📊", layout="wide")
st.title("📊 Top Gainers / Losers & Big Money")
st.warning("⚠️ Not investment advice. Movers are computed over ~60 liquid large-caps per market "
           "(last close vs previous close, delayed data).")

days = st.sidebar.slider("Look-back (days) for deals/insiders", 3, 30, 7)
if st.sidebar.button("🔄 Refresh"):
    st.cache_data.clear()


@st.cache_data(ttl=300, show_spinner=False)
def _movers(m):
    return screener.movers(m)


@st.cache_data(ttl=900, show_spinner=False)
def _deals(m, d):
    return bigmoney.deal_headlines(m, d)


@st.cache_data(ttl=1800, show_spinner=False)
def _ins(d):
    return bigmoney.us_insiders(d)


cfg = {"Change %": st.column_config.NumberColumn(format="%+.2f%%"),
       "Vol vs 5d avg": st.column_config.NumberColumn("Volume x avg", format="%.1fx")}
for flag, name in (("IN", "🇮🇳 India"), ("US", "🇺🇸 United States")):
    st.header(name)
    g, l = _movers(flag)
    c1, c2 = st.columns(2)
    c1.subheader("🟢 Top gainers")
    c1.dataframe(g, hide_index=True, use_container_width=True, column_config=cfg)
    c2.subheader("🔴 Top losers")
    c2.dataframe(l, hide_index=True, use_container_width=True, column_config=cfg)
    st.caption("Volume x avg well above 1 on a big move suggests institutional participation.")

    st.subheader("💰 Big investments & deals in the news")
    d = _deals(flag, days)
    if d.empty:
        st.info("No deal headlines found.")
    else:
        d = d.copy()
        d["Published"] = d["Published"].dt.strftime("%d %b %H:%M UTC")
        st.dataframe(d[["Published", "Headline", "Source", "Link"]], hide_index=True,
                     use_container_width=True,
                     column_config={"Link": st.column_config.LinkColumn("Link", display_text="open")})

st.header("🕵️ US insider transactions (Form 4)")
ins = _ins(max(days, 14))
if ins.empty:
    st.info("No insider trades returned.")
else:
    b, s = st.tabs(["Buys", "Sells"])
    b.dataframe(ins[ins.Type == "BUY"], hide_index=True, use_container_width=True)
    s.dataframe(ins[ins.Type == "SELL"], hide_index=True, use_container_width=True)
st.caption("India bulk/block-deal exchange feeds are bot-protected; deal flow above comes from news. "
           "Per-stock FII/DII shareholding trends are on the main Analyze page.")
