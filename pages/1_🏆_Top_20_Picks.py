"""Top-20 investable stocks across India + US, ranked on technicals, fundamentals and news."""

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import screener, theme as T, tradingview as tv, ui  # noqa: E402

ui.setup("Top 20 Picks", "🏆")
C = T.C

# ---------------------------------------------------------------- sidebar
ui.sidebar_brand()
T.sidebar_head("List composition")
mode = st.sidebar.radio("Composition", ["Best 20 overall", "Balanced 10 India + 10 US"],
                        label_visibility="collapsed")
T.sidebar_head("Blend weights")
w_t = st.sidebar.slider("Technical", 0.0, 1.0, 0.40, 0.05)
w_f = st.sidebar.slider("Fundamental", 0.0, 1.0, 0.45, 0.05)
w_n = st.sidebar.slider("News", 0.0, 1.0, 0.15, 0.05)
T.sidebar_head("Data")
if st.sidebar.button("Refresh data", use_container_width=True):
    st.cache_data.clear()


@st.cache_data(ttl=1800, show_spinner=False)
def _rank_both(w):
    """Scan India and the US at the same time (about half the wait of doing them in turn)."""
    import concurrent.futures as cf

    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        fi, fu = ex.submit(screener.rank, "IN", w), ex.submit(screener.rank, "US", w)
        return fi.result(), fu.result()


# ---------------------------------------------------------------- header
ui.hero(
    "Top 20 Investable Stocks",
    "Rule-based screen of ~120 India + US large-caps. Each name is scored −100…+100 from trend, "
    "momentum, fundamentals and news tone; overheated (RSI ≥ 80) or weak-fundamental stocks are excluded.",
    pills=[("Delayed data", "amber"), ("Not advice", "flat")],
)

with st.spinner("Scanning both markets — fundamentals for ~120 stocks, takes ~1 minute on first load…"):
    w = (w_t, w_f, w_n)
    ind, us = _rank_both(w)

if mode.startswith("Balanced"):
    top = pd.concat([ind.head(10), us.head(10)])
    top = top.sort_values("Score", ascending=False)
else:
    top = pd.concat([ind, us]).sort_values("Score", ascending=False).head(20)
top = top.reset_index(drop=True)

# ---------------------------------------------------------------- summary KPIs
if top.empty:
    ui.empty_note("<b>No stocks passed the screen.</b> Yahoo may be rate-limiting — try Refresh data in a minute.")
    ui.footer()
    st.stop()

n_in = int((top["Market"] == "IN").sum())
n_us = int((top["Market"] == "US").sum())
sectors = top["Sector"].where(~top["Sector"].isin(["—", None]), other=pd.NA).dropna()
top_sector = sectors.value_counts().index[0] if len(sectors) else "—"
best = top.iloc[0]
cols = st.columns(5)
T.kpi(cols[0], "Top pick", ui.short_sym(best["Symbol"]), f"score {best['Score']:+.1f}", "up")
T.kpi(cols[1], "Average score", f"{top['Score'].mean():+.1f}", f"of {len(top)} picks", T.sign_tone(top["Score"].mean()))
T.kpi(cols[2], "India / US", f"{n_in} / {n_us}", "picks by market", "flat")
T.kpi(cols[3], "Leading sector", str(top_sector), "most picks", "amber", small=True)
T.kpi(cols[4], "Avg 3M return", f"{top['3M %'].mean():+.1f}%" if top["3M %"].notna().any() else "—",
      "across picks", T.sign_tone(top["3M %"].mean()))

st.markdown("<div style='height:.8rem'></div>", unsafe_allow_html=True)

tab_cards, tab_table, tab_scores, tab_chart = st.tabs(["CARDS", "TABLE", "SCORES", "LIVE CHART"])

with tab_cards:
    ui.pick_cards(top)

with tab_table:
    view = top.copy()
    view.index += 1
    st.dataframe(
        view[["Market", "Symbol", "Name", "Sector", "Price", "Day %", "3M %", "Score", "Technical",
              "Fundamental", "News", "P/E", "ROE %", "Rev growth %", "RSI", "Analyst", "Upside %"]],
        use_container_width=True, height=760,
        column_config={
            "Score": st.column_config.ProgressColumn("Score", min_value=-100, max_value=100, format="%.1f"),
            **{c: st.column_config.NumberColumn(c, format="%.1f") for c in
               ["Day %", "3M %", "P/E", "ROE %", "Rev growth %", "RSI", "Upside %", "Price"]},
        },
    )
    st.download_button(
        "Download this list (CSV)",
        top.drop(columns=["Why"], errors="ignore").to_csv(index=False).encode("utf-8"),
        file_name="top20_picks.csv", mime="text/csv",
    )
    st.caption("Score = weighted blend of technical (trend, RSI, MACD, volume), fundamental (growth, ROE, margins, "
               "valuation, debt) and news tone, −100…+100.")

with tab_scores:
    d = top.iloc[::-1]
    fig = go.Figure()
    for mk, colr in (("IN", C["amber"]), ("US", C["blue"])):
        sub = d[d["Market"] == mk]
        fig.add_trace(go.Bar(
            x=sub["Score"], y=[ui.short_sym(s) for s in sub["Symbol"]], orientation="h",
            name="India" if mk == "IN" else "United States", marker_color=colr, marker_line_width=0,
            hovertemplate="%{y}: %{x:+.1f}<extra></extra>",
        ))
    fig.update_layout(height=max(420, 26 * len(d) + 80), barmode="overlay",
                      margin=dict(l=8, r=8, t=8, b=8), xaxis_title="Composite score (−100…+100)",
                      xaxis_title_font=dict(size=10, color=C["faint"]),
                      legend=dict(orientation="h", y=1.04, x=0))
    st.plotly_chart(T.style_axes(fig), use_container_width=True)

with tab_chart:
    pick = st.selectbox("Symbol", top["Symbol"].tolist(), format_func=ui.short_sym)
    mk = top.set_index("Symbol").loc[pick, "Market"]
    if mk == "IN":
        base = pick.replace(".NS", "")
        T.note("<b>NSE/BSE isn't available in TradingView's free embed.</b> Open the full live chart on TradingView:")
        st.link_button(f"Open {base} on TradingView ↗", f"https://www.tradingview.com/chart/?symbol=NSE:{base}")
    else:
        import streamlit.components.v1 as components
        components.html(tv.widget_html(pick.replace("-", "."), height=620), height=640)

ui.footer()
