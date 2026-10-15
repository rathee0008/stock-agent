"""Sector heatmap: which parts of the India and US large-cap universes are moving today."""

import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import cache, liveheat, screener, sectors, theme as T, ui  # noqa: E402

ui.setup("Sector Heatmap", "🗺️")
C = T.C

ui.sidebar_brand()
T.sidebar_head("View")
span = st.sidebar.radio("Change over", ["1 day", "1 week", "1 month", "3 months"], horizontal=True)
T.sidebar_head("Data")
if st.sidebar.button("Refresh", use_container_width=True):
    st.cache_data.clear()

_LOOK = {"1 day": 1, "1 week": 5, "1 month": 21, "3 months": 63}


@st.cache_data(ttl=45, show_spinner=False)
def _live(market: str, tick: int) -> dict:
    """Intraday last price vs previous close. ``tick`` makes the cache expire with the refresh interval."""
    return screener.live_prices(list(sectors.sector_map(market)))


def _apply_live(df: pd.DataFrame, market: str, tick: int) -> pd.DataFrame:
    """Overwrite price / 1-day change with live values; returns df unchanged if the feed is empty."""
    lp = _live(market, tick)
    if not lp:
        return df
    smap = sectors.sector_map(market)
    inv = {ui.short_sym(k): k for k in smap}
    df = df.copy()
    for i, r in df.iterrows():
        k = inv.get(r["Symbol"])
        if k in lp:
            px_, prev = lp[k]
            df.at[i, "Price"] = px_
            df.at[i, "1D %"] = (px_ / prev - 1) * 100
            if _LOOK_SEL == 1:
                df.at[i, "Change %"] = (px_ / prev - 1) * 100
    return df


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _load(market: str, lookback: int, b: int) -> pd.DataFrame:
    """``b`` is a market-hours-aware cache bucket (short while open, long when closed)."""
    smap = sectors.sector_map(market)
    hist = screener.batch_history(list(smap), period="6mo", min_rows=lookback + 2)
    rows = []
    for s, df in hist.items():
        c = df["Close"].dropna()
        if len(c) <= lookback:
            continue
        rows.append({"Symbol": ui.short_sym(s), "Y": s, "Sector": smap[s], "Price": float(c.iloc[-1]),
                     "Change %": (float(c.iloc[-1]) / float(c.iloc[-1 - lookback]) - 1) * 100,
                     "1D %": (float(c.iloc[-1]) / float(c.iloc[-2]) - 1) * 100,
                     "Trend": [float(x) for x in c.tail(30)]})
    return pd.DataFrame(rows)


ui.hero(
    "Sector Heatmap",
    "Equal-weighted tiles for the liquid large-caps in each market, grouped by sector. Green = up, red = down "
    "over the chosen window. Use it to see where money is rotating.",
    pills=[("Delayed data", "amber"), ("Equal-weighted", "flat"), ("Live mode available", "flat")],
)


def _view(mkt: str, live: bool) -> None:
    global _LOOK_SEL
    _M = "IN" if mkt == "India" else "US"
    with st.spinner("Loading prices…"):
        df = _load(_M, _LOOK[span], cache.bucket(_M, 3))
        if live:
            _LOOK_SEL = _LOOK[span]
            df = _apply_live(df, _M, int(time.time() // 60))
            df["Change %"] = df["1D %"]   # live mode is always "today vs previous close"

    if df.empty:
        ui.empty_note("<b>No prices returned.</b> Yahoo may be rate-limiting. Try Refresh in a minute.")
        return

    sec = df.groupby("Sector")["Change %"].agg(["mean", "count"]).sort_values("mean", ascending=False)
    best, worst = sec.index[0], sec.index[-1]
    k = st.columns(4)
    T.kpi(k[0], "Leading sector", str(best), f"{sec.loc[best, 'mean']:+.2f}% avg", "up", small=True)
    T.kpi(k[1], "Lagging sector", str(worst), f"{sec.loc[worst, 'mean']:+.2f}% avg", "down", small=True)
    T.kpi(k[2], "Advancers / decliners", f"{int((df['Change %'] > 0).sum())} / {int((df['Change %'] < 0).sum())}",
          f"of {len(df)} stocks", "flat")
    T.kpi(k[3], "Market average", f"{df['Change %'].mean():+.2f}%", span, T.sign_tone(df["Change %"].mean()))
    st.markdown("<div style='height:.8rem'></div>", unsafe_allow_html=True)

    lim = max(2.0, float(df["Change %"].abs().quantile(0.9)))
    if live:
        components.html(liveheat.build_html(df, None, lim, 560, "Prices stream from Yahoo; they are exchange-delayed where Yahoo says so."),
                        height=640 + 36 * int(df['Sector'].nunique()) + 110)
    else:
        fig = px.treemap(
            df.assign(All=mkt), path=["All", "Sector", "Symbol"], values=[1] * len(df), color="Change %",
            color_continuous_scale=[(0, C["down"]), (0.5, "#1B1E24"), (1, C["up"])],
            range_color=(-lim, lim), custom_data=["Change %", "Price"],
        )
        fig.update_traces(
            texttemplate="%{label}<br>%{customdata[0]:+.1f}%", textfont=dict(family="monospace", size=13),
            hovertemplate="%{label}: %{customdata[0]:+.2f}%<extra></extra>", marker_line_width=1,
            marker_line_color="#0A0B0D",
        )
        fig.update_layout(height=560, margin=dict(l=0, r=0, t=0, b=0), coloraxis_showscale=False)
        st.plotly_chart(fig, use_container_width=True)

    if not live:  # in live mode the ranking is part of the streaming block above
        ui.table_title("Sector ranking", "flat")
        rows = []
        mx = max(float(sec["mean"].abs().max()), 0.01)
        for name, r in sec.iterrows():
            col = T.tone_color(T.sign_tone(r["mean"]))
            w = min(60, abs(float(r["mean"])) / mx * 60)
            rows.append(
                f'<tr><td><b>{ui._e(name)}</b></td><td class="dim">{int(r["count"])}</td>'
                f'<td class="chg" style="color:{col}"><span class="bar" style="width:{w:.0f}px;background:{col}"></span>'
                f'{ui._pct(r["mean"])}</td></tr>'
            )
        st.markdown(
            '<div class="ttw"><table class="tt"><thead><tr><th>Sector</th><th>Stocks</th><th>Avg change</th></tr></thead>'
            "<tbody>" + "".join(rows) + "</tbody></table></div>",
            unsafe_allow_html=True,
        )
    T.rule("Drill into a sector")
    pick = st.selectbox("Sector", list(sec.index), label_visibility="collapsed")
    sub = df[df["Sector"] == pick].sort_values("Change %", ascending=False)
    c1, c2 = st.columns([1, 1])
    with c1:
        fig = go.Figure(go.Bar(x=sub["Change %"], y=sub["Symbol"], orientation="h",
                               marker_color=[C["up"] if v >= 0 else C["down"] for v in sub["Change %"]],
                               hovertemplate="%{y}: %{x:+.2f}%<extra></extra>"))
        fig.update_layout(height=max(260, 28 * len(sub) + 60), margin=dict(l=8, r=8, t=8, b=8),
                          yaxis=dict(autorange="reversed"), xaxis_title=f"Change over {span}",
                          xaxis_title_font=dict(size=10, color=C["faint"]))
        st.plotly_chart(T.style_axes(fig), use_container_width=True)
    with c2:
        st.dataframe(
            sub[["Symbol", "Price", "Change %", "1D %", "Trend"]], use_container_width=True, hide_index=True,
            column_config={
                "Price": st.column_config.NumberColumn(format="%.2f"),
                "Change %": st.column_config.NumberColumn(format="%+.2f"),
                "1D %": st.column_config.NumberColumn(format="%+.2f"),
                "Trend": st.column_config.LineChartColumn("30-day trend"),
            },
        )
        st.caption("Open any of these on the Analyze page by typing the symbol in the left rail.")
    if live:
        st.caption("Live ticks stream straight to your browser (no page refresh). The summary cards above are a "
                   "snapshot from when you switched Live on; the map's own header updates tick by tick. "
                   "Live mode shows today's change vs the previous close. Tiles stay still while the exchange is closed.")


c_m, c_l = st.columns([2, 1])
with c_m:
    mkt = st.radio("Market", ["India", "United States"], horizontal=True, label_visibility="collapsed")
with c_l:
    live = st.toggle("Live", value=False, help="Stream live price ticks into the map (today vs previous close).")
_LOOK_SEL = 0
_view(mkt, live)
ui.footer()
