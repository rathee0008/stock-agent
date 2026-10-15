"""Top gainers/losers with the reasons they moved, and where big money is flowing (US + India)."""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import bigmoney, cache, flows, market, screener, theme as T, ui, why  # noqa: E402

ui.setup("Movers and Big Money", "📊")

# ---------------------------------------------------------------- sidebar
ui.sidebar_brand()
T.sidebar_head("Window")
days = st.sidebar.slider("Look-back (days) for deals/insiders", 3, 30, 7)
T.sidebar_head("Explain moves")
want_news = st.sidebar.checkbox("Look up a headline for each mover", value=True)
want_llm = st.sidebar.checkbox("Claude one-line explanations", value=False,
                               help="Needs ANTHROPIC_API_KEY. One batched call per market.")
T.sidebar_head("Data")
if st.sidebar.button("Refresh", use_container_width=True):
    st.cache_data.clear()


# The trailing ``b`` argument is a cache.bucket(): it rolls every 2 minutes while the market
# is open and every 3 hours when it is shut, so the TTL adapts to whether data can change.
@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _frame(m, b):
    return screener.movers_frame(m)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _deals(m, d, b):
    return bigmoney.deal_headlines(m, d)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _ins(d, b):
    return bigmoney.us_insiders(d)


@st.cache_data(ttl=3600, show_spinner=False)
def _idx(b):
    return market.index_quotes()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _delivery(b):
    return flows.delivery()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _exch_deals(b):
    return flows.deals()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _fiidii(b):
    return flows.fii_dii()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _heads(syms: tuple, m: str, b: int):
    return bigmoney.headlines_for(list(syms), m)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _llm(items_key: str, items: list):
    return why.claude_summary(items)


# ---------------------------------------------------------------- header
ui.hero(
    "Movers & Big Money",
    "Day gainers and losers across ~60 liquid large-caps per market, with the reasons they moved: volume, "
    "delivery %, gaps, 52-week position, sector, exchange deals and the newest headline.",
    pills=[("Last close vs previous", "amber"), ("Delayed data", "flat")],
)
ui.market_strip(_idx(cache.both_bucket(0.5)))

tab_in, tab_us, tab_flow, tab_ins = st.tabs(["🇮🇳 INDIA", "🇺🇸 UNITED STATES", "🏦 FLOWS (INDIA)", "🕵️ INSIDERS (FORM 4)"])


def _enrich(flag: str, g: pd.DataFrame, l: pd.DataFrame, full: pd.DataFrame):
    """Attach delivery %, reason tags and (optionally) a Claude sentence to each mover row."""
    b = cache.bucket(flag)
    sec_avg = screener.sector_averages(full)
    dl = _delivery(b) if flag == "IN" else pd.DataFrame()
    dmap = dict(zip(dl["Symbol"], dl["Delivery %"])) if not dl.empty else {}
    ed = _exch_deals(b) if flag == "IN" else pd.DataFrame()
    dnote = flows.deals_by_symbol(ed)
    syms = tuple(list(g["Symbol"]) + list(l["Symbol"]))
    heads = _heads(syms, flag, b) if want_news else {}
    out = []
    for df in (g, l):
        df = df.copy()
        df["Delivery %"] = df["Symbol"].map(dmap)
        whys, facts = [], []
        for _, r in df.iterrows():
            row = r.to_dict()
            h = heads.get(r["Symbol"])
            tags = why.explain(row, sec_avg, dnote.get(r["Symbol"]), h["Headline"][:90] if h else None)
            whys.append(tags)
            facts.append({"symbol": ui.short_sym(r["Symbol"]), "change_pct": round(float(r["Change %"]), 2),
                          "facts": tags, "headline": h["Headline"] if h else None})
        df["Why"] = whys
        out.append((df, facts))
    if want_llm:
        items = out[0][1] + out[1][1]
        sentences = _llm(f"{flag}-{b}", items)
        for df, _ in out:
            df["Why"] = [[sentences[ui.short_sym(s)]] if ui.short_sym(s) in sentences else w
                         for s, w in zip(df["Symbol"], df["Why"])]
    return out[0][0], out[1][0]


def _market_tab(flag: str) -> None:
    full = _frame(flag, cache.bucket(flag))
    if full is None or full.empty:
        ui.empty_note("<b>No prices returned.</b> Yahoo may be rate-limiting. Try Refresh in a minute.")
        return
    g, l = screener.split_movers(full)
    g, l = _enrich(flag, g, l, full)
    both = [g, l]
    k = st.columns(4)
    bg, bl = g.iloc[0], l.iloc[0]
    unusual = int(sum((x["Vol vs 5d avg"] >= 1.5).sum() for x in both))
    adv = int((full["Change %"] > 0).sum())
    T.kpi(k[0], "Top gainer", ui.short_sym(bg["Symbol"]), f"{bg['Change %']:+.2f}%", "up")
    T.kpi(k[1], "Top loser", ui.short_sym(bl["Symbol"]), f"{bl['Change %']:+.2f}%", "down")
    T.kpi(k[2], "Unusual volume", f"{unusual}", "movers trading ≥1.5× avg", "amber")
    T.kpi(k[3], "Breadth", f"{adv} / {len(full) - adv}", "advancers / decliners", T.sign_tone(adv - (len(full) - adv)))
    st.markdown("<div style='height:.7rem'></div>", unsafe_allow_html=True)
    ui.table_title("Top gainers", "up")
    ui.movers_table(g, flag)
    st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)
    ui.table_title("Top losers", "down")
    ui.movers_table(l, flag)
    if flag == "IN" and "Delivery %" in g and not (g["Delivery %"].notna().any() or l["Delivery %"].notna().any()):
        st.caption("Delivery % unavailable: NSE's bhavcopy could not be reached from this host.")
    T.rule("Big investments & deals in the news")
    ui.feed(_deals(flag, days, cache.bucket(flag, 5)), empty="No deal headlines found.")


with tab_in:
    _market_tab("IN")
with tab_us:
    _market_tab("US")

with tab_flow:
    b = cache.bucket("IN", 5)
    ui.table_title("FII / DII cash-market activity (₹ crore, provisional)", "amber")
    fd = _fiidii(b)
    if fd.empty:
        ui.empty_note("<b>FII/DII figures unavailable.</b> NSE blocks some hosts. See the per-stock FII/DII "
                      "shareholding trend on the Analyze page instead.")
    else:
        rows = []
        for _, r in fd.iterrows():
            col = T.tone_color(T.sign_tone(r["Net (Cr)"]))
            rows.append(f'<tr><td><b>{ui._e(r["Category"])}</b></td><td class="dim">{ui._e(r["Date"])}</td>'
                        f'<td>{r["Buy (Cr)"]:,.0f}</td><td>{r["Sell (Cr)"]:,.0f}</td>'
                        f'<td class="chg" style="color:{col}">{r["Net (Cr)"]:+,.0f}</td></tr>')
        st.markdown('<div class="ttw"><table class="tt"><thead><tr><th>Category</th><th>Date</th><th>Buy</th>'
                    '<th>Sell</th><th>Net</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>",
                    unsafe_allow_html=True)
    st.markdown("<div style='height:.8rem'></div>", unsafe_allow_html=True)
    ui.table_title("Bulk & block deals (latest session)", "amber")
    ed = _exch_deals(b)
    if ed.empty:
        ui.empty_note("<b>Exchange deal files unavailable.</b> The news feed on the India tab still lists deal headlines.")
    else:
        side = st.radio("Side", ["All", "BUY", "SELL"], horizontal=True, label_visibility="collapsed")
        view = ed if side == "All" else ed[ed["Side"] == side]
        rows = []
        for _, r in view.head(40).iterrows():
            col = T.tone_color("up" if r["Side"] == "BUY" else "down")
            rows.append(f'<tr><td><b>{ui.symlink(r["Symbol"], "IN")}</b></td><td class="dim wrap">{ui._e(r["Client"])}</td>'
                        f'<td style="color:{col};font-weight:700">{r["Side"]}</td><td>{r["Qty"]:,.0f}</td>'
                        f'<td>{r["Price"]:,.2f}</td><td>{r["Value (Cr)"]:,.1f}</td><td class="dim">{r["Kind"]}</td></tr>')
        st.markdown('<div class="ttw"><table class="tt"><thead><tr><th>Symbol</th><th>Client</th><th>Side</th>'
                    '<th>Qty</th><th>Price</th><th>Value (Cr)</th><th>Type</th></tr></thead><tbody>' + "".join(rows)
                    + "</tbody></table></div>", unsafe_allow_html=True)
    st.caption("Source: NSE public files. Delivery % = share of traded quantity actually taken for delivery; "
               "a big move on high delivery is usually more meaningful than one on intraday churn.")

with tab_ins:
    ins = _ins(max(days, 14), cache.bucket("US", 5))
    if ins.empty:
        ui.empty_note("<b>No insider trades returned.</b> Source: SEC EDGAR Form 4.")
        errs = bigmoney.last_errors()
        if errs:
            st.caption("Diagnostics: " + " | ".join(errs))
    else:
        b_, s_ = st.tabs(["BUYS", "SELLS"])
        with b_:
            ui.insider_table(ins[ins.Type == "BUY"], "No open-market buys in this window.")
        with s_:
            ui.insider_table(ins[ins.Type == "SELL"], "No open-market sales in this window.")
    st.caption("Exchange bulk/block-deal and FII/DII data is on the Flows tab. Per-stock FII/DII shareholding trends "
               "are on the main Analyze page.")

ui.footer()
