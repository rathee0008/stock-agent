"""Backtest: would the technical score have beaten the market? Costs, Sharpe, benchmark,
out-of-sample split, calibration of score bands and a signal lab that tunes technical weights."""

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import backtest as BT, cache, screener, theme as T, ui, universe  # noqa: E402

ui.setup("Backtest", "🧪")
C = T.C

ui.sidebar_brand()
T.sidebar_head("Test setup")
mkt = st.sidebar.radio("Market", ["India", "United States"], label_visibility="collapsed")
top_n = st.sidebar.slider("Hold the top N by score", 5, 20, 10)
hold = st.sidebar.select_slider("Rebalance every", options=[10, 21, 42, 63], value=21,
                                format_func=lambda d: {10: "2 weeks", 21: "1 month", 42: "2 months", 63: "3 months"}[d])
cost_bps = st.sidebar.slider("Trading cost per side (bps)", 0, 60, 20, 5,
                             help="Brokerage + STT/impact. 20 bps = 0.20% each way.")
rf = st.sidebar.number_input("Risk-free rate (% a year)", 0.0, 15.0, 6.5 if mkt == "India" else 4.0, 0.25) / 100
T.sidebar_head("Data")
if st.sidebar.button("Refresh", use_container_width=True):
    st.cache_data.clear()

M = "IN" if mkt == "India" else "US"
BENCH = "^NSEI" if M == "IN" else "^GSPC"


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _run(market: str, n: int, step: int, cost: float, rf_: float, tuned: bool):
    import yfinance as yf

    syms = universe.symbols(market)
    hist = screener.batch_history(syms, period="6y", min_rows=BT.WARMUP + step + 5)
    bench = None
    try:
        b = yf.download(BENCH_FOR[market], period="6y", interval="1d", progress=False, auto_adjust=False)
        if isinstance(b.columns, pd.MultiIndex):
            b.columns = b.columns.get_level_values(0)
        bench = b["Close"].dropna()
    except Exception:  # noqa: BLE001
        pass
    gw = BT.load_weights() if tuned else None
    return BT.run(hist, top_n=n, step=step, cost_bps=cost, bench_close=bench, rf_annual=rf_, group_weights=gw)


BENCH_FOR = {"IN": "^NSEI", "US": "^GSPC"}
tuned = st.sidebar.checkbox("Use tuned technical weights", value=False,
                            help="Apply the group weights saved from the Signal lab below.",
                            disabled=BT.load_weights() is None)

ui.hero(
    "Backtest",
    "Each rebalance date, rank every stock by the technical score using only data available at that time, hold the "
    "top N until the next date, and compare with the whole universe and the index, after trading costs.",
    pills=[("Technical score only", "amber"), ("Past results", "flat")],
)

with st.spinner("Replaying history. This takes a minute or two on first run…"):
    res = _run(M, top_n, hold, float(cost_bps), float(rf), tuned)

pdf = res.periods
if pdf is None or pdf.empty:
    ui.empty_note("<b>Not enough history returned.</b> Yahoo may be rate-limiting. Try Refresh in a minute.")
    ui.footer()
    st.stop()

BT.save_calibration(res.calibration, M, hold)
m = res.metrics
ms, mu = m["strategy"], m["universe"]
mb = m.get("benchmark")

k = st.columns(5)
T.kpi(k[0], "Strategy CAGR", f"{ms['cagr'] * 100:+.1f}%", f"universe {mu['cagr'] * 100:+.1f}%",
      T.sign_tone(ms["cagr"] - mu["cagr"]))
T.kpi(k[1], "Sharpe", f"{ms['sharpe']:.2f}", f"universe {mu['sharpe']:.2f}", T.sign_tone(ms["sharpe"] - mu["sharpe"]))
T.kpi(k[2], "Max drawdown", f"{ms['max_dd'] * 100:.1f}%", f"universe {mu['max_dd'] * 100:.1f}%", "down")
T.kpi(k[3], "Beat universe", f"{m['beat_universe_pct']:.0f}%", f"of {len(pdf)} periods",
      "up" if m["beat_universe_pct"] >= 50 else "down")
T.kpi(k[4], "Cost drag", f"{m['cost_drag_pa'] * 100:.1f}% / yr", f"turnover {m['avg_turnover'] * 100:.0f}% a period", "amber")
st.markdown("<div style='height:.8rem'></div>", unsafe_allow_html=True)

cum = lambda s: (1 + s).cumprod() * 100  # noqa: E731
fig = go.Figure()
fig.add_trace(go.Scatter(x=pdf["Date"], y=cum(pdf["Strategy"]), name=f"Top {top_n} by score (after costs)",
                         line=dict(color=C["amber"], width=2.4)))
fig.add_trace(go.Scatter(x=pdf["Date"], y=cum(pdf["Universe"]), name="Whole universe (equal weight)",
                         line=dict(color=C["blue"], width=1.8)))
if mb:
    fig.add_trace(go.Scatter(x=pdf["Date"], y=cum(pdf["Benchmark"].fillna(0)),
                             name="Nifty 50" if M == "IN" else "S&P 500", line=dict(color=C["faint"], width=1.6, dash="dot")))
fig.update_layout(height=420, margin=dict(l=8, r=8, t=8, b=8), yaxis_title="Growth of 100",
                  yaxis_title_font=dict(size=10, color=C["faint"]), legend=dict(orientation="h", y=1.08, x=0))
st.plotly_chart(T.style_axes(fig), use_container_width=True)

tab_oos, tab_cal, tab_lab, tab_rows = st.tabs(["OUT-OF-SAMPLE", "CALIBRATION", "SIGNAL LAB", "PERIODS"])

with tab_oos:
    if "in_sample" in m:
        a, b = m["in_sample"], m["out_sample"]
        c = st.columns(2)
        T.kpi(c[0], "First half (in-sample)", f"{a['cagr'] * 100:+.1f}% CAGR", f"Sharpe {a['sharpe']:.2f} · excess {a['excess_pa'] * 100:+.1f}%/yr", "flat")
        T.kpi(c[1], "Second half (out-of-sample)", f"{b['cagr'] * 100:+.1f}% CAGR", f"Sharpe {b['sharpe']:.2f} · excess {b['excess_pa'] * 100:+.1f}%/yr",
              T.sign_tone(b["excess_pa"]))
        st.caption("If the second half is much weaker than the first, the edge is probably noise or regime-specific.")
    else:
        st.info("Not enough periods to split. Try a shorter rebalance interval.")

with tab_cal:
    cal = res.calibration
    if cal is None or cal.empty:
        st.info("No calibration data.")
    else:
        show = cal.copy()
        show["p_up"] *= 100
        show["mean_ret"] *= 100
        show["median_ret"] *= 100
        show["base_p_up"] *= 100
        show.columns = ["Samples", f"Higher after {hold}d (%)", "Mean return (%)", "Median return (%)", "All stocks higher (%)"]
        st.dataframe(show.style.format({c: "{:.1f}" for c in show.columns[1:]}), use_container_width=True)
        st.caption("This table is what the Analyze page quotes as the historical hit-rate for a stock's technical band. "
                   "A band only matters if its number is clearly above or below the all-stocks column.")

with tab_lab:
    lab = res.lab
    if lab is None or lab.empty:
        st.info("Not enough dates for the signal lab.")
    else:
        sug = BT.suggest_group_weights(lab)
        view = lab.copy()
        view["Suggested weight ×"] = view["Group"].map(sug)
        st.dataframe(view.style.format({"IC": "{:+.3f}", "t_stat": "{:+.2f}", "IC>0 %": "{:.0f}",
                                        "Suggested weight ×": "{:.2f}"}), use_container_width=True, hide_index=True)
        st.caption("IC = rank correlation between a signal group's points and the next period's return across stocks. "
                   "Only groups with |t| ≥ 1 are re-weighted; bounded 0.4×–1.6×. Tuning on the same history you "
                   "evaluate on is over-fitting: check the out-of-sample tab after saving.")
        if st.button("Save these as tuned technical weights"):
            BT.save_weights(sug)
            st.success("Saved. Tick “Use tuned technical weights” (here or on the Analyze page) to apply them.")

with tab_rows:
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
    f"Tested on {res.n_syms} stocks that exist today, so results are flattered by survivorship (stocks that "
    "dropped out are missing). Costs are a flat per-side estimate; taxes and slippage on illiquid names are not "
    "modelled. Fundamentals and news are left out because Yahoo does not give point-in-time history. Past "
    "performance does not predict future returns."
)
ui.footer()
