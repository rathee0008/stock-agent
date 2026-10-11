"""Sector heatmap: which parts of the India and US large-cap universes are moving today."""

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import screener, sectors, theme as T, ui  # noqa: E402

ui.setup("Sector Heatmap", "🗺️")
C = T.C

ui.sidebar_brand()
T.sidebar_head("View")
mkt = st.sidebar.radio("Market", ["India", "United States"], label_visibility="collapsed")
span = st.sidebar.radio("Change over", ["1 day", "1 week", "1 month"], horizontal=True)
T.sidebar_head("Data")
if st.sidebar.button("Refresh", use_container_width=True):
    st.cache_data.clear()

_LOOK = {"1 day": 1, "1 week": 5, "1 month": 21}


@st.cache_data(ttl=600, show_spinner=False)
def _load(market: str, lookback: int) -> pd.DataFrame:
    smap = sectors.sector_map(market)
    hist = screener.batch_history(list(smap), period="3mo", min_rows=lookback + 2)
    rows = []
    for s, df in hist.items():
        c = df["Close"].dropna()
        if len(c) <= lookback:
            continue
        rows.append({"Symbol": ui.short_sym(s), "Sector": smap[s], "Price": float(c.iloc[-1]),
                     "Change %": (float(c.iloc[-1]) / float(c.iloc[-1 - lookback]) - 1) * 100})
    return pd.DataFrame(rows)


ui.hero(
    "Sector Heatmap",
    "Equal-weighted tiles for the liquid large-caps in each market, grouped by sector. Green = up, red = down "
    "over the chosen window. Use it to see where money is rotating.",
    pills=[("Delayed data", "amber"), ("Equal-weighted", "flat")],
)

with st.spinner("Loading prices…"):
    df = _load("IN" if mkt == "India" else "US", _LOOK[span])

if df.empty:
    ui.empty_note("<b>No prices returned.</b> Yahoo may be rate-limiting. Try Refresh in a minute.")
    ui.footer()
    st.stop()

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
ui.footer()
