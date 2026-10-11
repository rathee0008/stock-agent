"""Backtest: would the technical score have beaten the market? (technical-only, monthly rebalance)."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import screener, technical as _tech, theme as T, ui, universe  # noqa: E402

ui.setup("Backtest", "🧪")
C = T.C

ui.sidebar_brand()
T.sidebar_head("Test setup")
mkt = st.sidebar.radio("Market", ["India", "United States"], label_visibility="collapsed")
top_n = st.sidebar.slider("Hold the top N by score", 5, 20, 10)
hold = st.sidebar.select_slider("Rebalance every", options=[10, 21, 42, 63], value=21,
                                format_func=lambda d: {10: "2 weeks", 21: "1 month", 42: "2 months", 63: "3 months"}[d])
T.sidebar_head("Data")
if st.sidebar.button("Refresh", use_container_width=True):
    st.cache_data.clear()

WARMUP = 252  # bars needed before the first score (200-day average etc.)


@st.cache_data(ttl=3600, show_spinner=False)
def _run(market: str, n: int, step: int) -> dict:
    syms = universe.symbols("IN" if market == "India" else "US")
    hist = screener.batch_history(syms, period="5y", min_rows=WARMUP + step + 5)
    closes = pd.DataFrame({s: d["Close"] for s, d in hist.items()}).sort_index().ffill()
    if closes.empty:
        return {}
    dates = list(range(WARMUP, len(closes) - step, step))
    rows = []
    for i in dates:
        scores = {}
        for s, d in hist.items():
            sub = d.loc[:closes.index[i]]
            if len(sub) < WARMUP:
                continue
            try:
                scores[s] = _tech.analyze(sub).score
            except Exception:  # noqa: BLE001
                continue
        if len(scores) < n:
            continue
        picks = sorted(scores, key=scores.get, reverse=True)[:n]
        fwd = closes.iloc[i + step] / closes.iloc[i] - 1
        rows.append({
            "Date": closes.index[i], "Strategy": float(fwd[picks].mean()),
            "Universe": float(fwd[list(scores)].mean()), "Picks": ", ".join(ui.short_sym(p) for p in picks[:5]),
        })
    return {"periods": pd.DataFrame(rows), "n_syms": len(hist)}


ui.hero(
    "Backtest",
    "Each rebalance date, rank every stock by the technical score using only data available at that time, hold the "
    "top N until the next date, and compare with holding the whole universe equally.",
    pills=[("Technical score only", "amber"), ("Past results", "flat")],
)

with st.spinner("Replaying history. This takes up to a minute on first run…"):
    res = _run(mkt, top_n, hold)

pdf = res.get("periods") if res else None
if pdf is None or pdf.empty:
    ui.empty_note("<b>Not enough history returned.</b> Yahoo may be rate-limiting. Try Refresh in a minute.")
    ui.footer()
    st.stop()

pdf = pdf.copy()
pdf["Excess"] = pdf["Strategy"] - pdf["Universe"]
cum_s = (1 + pdf["Strategy"]).cumprod() * 100
cum_u = (1 + pdf["Universe"]).cumprod() * 100
years = max(len(pdf) * hold / 252, 0.1)
cagr_s = (cum_s.iloc[-1] / 100) ** (1 / years) - 1
cagr_u = (cum_u.iloc[-1] / 100) ** (1 / years) - 1
hit = float((pdf["Excess"] > 0).mean() * 100)
dd = float(((cum_s / cum_s.cummax()) - 1).min() * 100)

k = st.columns(4)
T.kpi(k[0], "Strategy CAGR", f"{cagr_s * 100:+.1f}%", f"universe {cagr_u * 100:+.1f}%", T.sign_tone(cagr_s - cagr_u))
T.kpi(k[1], "Beat the universe", f"{hit:.0f}%", f"of {len(pdf)} periods", "up" if hit >= 50 else "down")
T.kpi(k[2], "Avg excess / period", f"{pdf['Excess'].mean() * 100:+.2f}%", "strategy minus universe",
      T.sign_tone(pdf["Excess"].mean()))
T.kpi(k[3], "Worst drawdown", f"{dd:.1f}%", "strategy, period-end", "down")
st.markdown("<div style='height:.8rem'></div>", unsafe_allow_html=True)

fig = go.Figure()
fig.add_trace(go.Scatter(x=pdf["Date"], y=cum_s, name=f"Top {top_n} by score", line=dict(color=C["amber"], width=2.4)))
fig.add_trace(go.Scatter(x=pdf["Date"], y=cum_u, name="Whole universe (equal weight)", line=dict(color=C["blue"], width=1.8)))
fig.update_layout(height=420, margin=dict(l=8, r=8, t=8, b=8), yaxis_title="Growth of 100",
                  yaxis_title_font=dict(size=10, color=C["faint"]), legend=dict(orientation="h", y=1.08, x=0))
st.plotly_chart(T.style_axes(fig), use_container_width=True)

ui.table_title("Recent periods", "flat")
rows = []
for _, r in pdf.iloc[::-1].head(12).iterrows():
    ec = T.tone_color(T.sign_tone(r["Excess"]))
    rows.append(
        f'<tr><td>{r["Date"]:%d %b %Y}</td><td>{ui._pct(r["Strategy"] * 100, 1)}</td>'
        f'<td>{ui._pct(r["Universe"] * 100, 1)}</td><td style="color:{ec};font-weight:700">'
        f'{ui._pct(r["Excess"] * 100, 1)}</td><td class="dim wrap">{ui._e(r["Picks"])} …</td></tr>'
    )
st.markdown(
    '<div class="ttw"><table class="tt"><thead><tr><th>Start</th><th>Strategy</th><th>Universe</th>'
    "<th>Excess</th><th>Top picks</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>",
    unsafe_allow_html=True,
)
st.caption(
    f"Tested on {res['n_syms']} stocks that exist today, so the result is flattered by survivorship (stocks that "
    "dropped out are missing). No trading costs or taxes. Fundamentals and news are left out because Yahoo does not "
    "give point-in-time history. Past performance does not predict future returns."
)
ui.footer()
