"""Top gainers/losers and where big money is moving (US + India)."""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import bigmoney, market, screener, theme as T, ui  # noqa: E402

ui.setup("Movers and Big Money", "📊")

# ---------------------------------------------------------------- sidebar
ui.sidebar_brand()
T.sidebar_head("Window")
days = st.sidebar.slider("Look-back (days) for deals/insiders", 3, 30, 7)
T.sidebar_head("Data")
if st.sidebar.button("Refresh", use_container_width=True):
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


@st.cache_data(ttl=300, show_spinner=False)
def _idx():
    return market.index_quotes()


# ---------------------------------------------------------------- header
ui.hero(
    "Movers & Big Money",
    "Day gainers and losers across ~60 liquid large-caps per market, plus deal headlines and US insider "
    "transactions. Volume × avg well above 1 on a big move hints at institutional participation.",
    pills=[("Last close vs previous", "amber"), ("Delayed data", "flat")],
)
ui.market_strip(_idx())

tab_in, tab_us, tab_ins = st.tabs(["🇮🇳 INDIA", "🇺🇸 UNITED STATES", "🕵️ INSIDERS (FORM 4)"])


def _market_tab(flag: str) -> None:
    g, l = _movers(flag)
    both = [x for x in (g, l) if x is not None and not x.empty]
    if both:
        k = st.columns(3)
        bg, bl = g.iloc[0], l.iloc[0]
        unusual = int(sum((x["Vol vs 5d avg"] >= 1.5).sum() for x in both))
        T.kpi(k[0], "Top gainer", ui.short_sym(bg["Symbol"]), f"{bg['Change %']:+.2f}%", "up")
        T.kpi(k[1], "Top loser", ui.short_sym(bl["Symbol"]), f"{bl['Change %']:+.2f}%", "down")
        T.kpi(k[2], "Unusual volume", f"{unusual}", "movers trading ≥1.5× avg", "amber")
        st.markdown("<div style='height:.7rem'></div>", unsafe_allow_html=True)
    c1, c2 = st.columns(2)
    with c1:
        ui.table_title("Top gainers", "up")
        ui.movers_table(g)
    with c2:
        ui.table_title("Top losers", "down")
        ui.movers_table(l)
    T.rule("Big investments & deals in the news")
    ui.feed(_deals(flag, days), empty="No deal headlines found.")


with tab_in:
    _market_tab("IN")
with tab_us:
    _market_tab("US")

with tab_ins:
    ins = _ins(max(days, 14))
    if ins.empty:
        ui.empty_note("<b>No insider trades returned.</b> Source: SEC EDGAR Form 4.")
        errs = bigmoney.last_errors()
        if errs:
            st.caption("Diagnostics: " + " | ".join(errs))
    else:
        b, s = st.tabs(["BUYS", "SELLS"])
        with b:
            ui.insider_table(ins[ins.Type == "BUY"], "No open-market buys in this window.")
        with s:
            ui.insider_table(ins[ins.Type == "SELL"], "No open-market sales in this window.")
    st.caption("India bulk/block-deal exchange feeds are bot-protected; India deal flow comes from news. "
               "Per-stock FII/DII shareholding trends are on the main Analyze page.")

ui.footer()
