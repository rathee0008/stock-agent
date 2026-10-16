"""Top-20 investable stocks across India + US, ranked on technicals, fundamentals and news."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import livepicks, log as _log, picks_extra as X, screener, theme as T, tradingview as tv, ui  # noqa: E402
from agent.presets import PRESETS, apply_filters  # noqa: E402

ui.setup("Top 20 Picks", "🏆")
C = T.C
ROOT = Path(__file__).resolve().parents[1]
HIST_PATH = ROOT / "data" / "screener" / "top20_history.csv"  # written by scripts/run_screener_daily.py

MODES = ["Best 20 overall", "Balanced 10 India + 10 US"]
STRATS = ["Blended (default)"] + list(PRESETS)

# ---------------------------------------------------------------- settings live in the URL (bookmark / share)
_DEFAULTS = {"t20_mode": MODES[0], "t20_strat": STRATS[0], "t20_wt": 0.40, "t20_wf": 0.45, "t20_wn": 0.15,
             "t20_cap": 0, "t20_mcap": 0, "t20_turn": 0, "t20_capin": 1_000_000, "t20_capus": 10_000, "t20_risk": 1.0}
_QKEY = {"t20_mode": "m", "t20_strat": "s", "t20_wt": "wt", "t20_wf": "wf", "t20_wn": "wn", "t20_cap": "cap",
         "t20_mcap": "mc", "t20_turn": "tv", "t20_capin": "ci", "t20_capus": "cu", "t20_risk": "rk"}
_BOUNDS = {"t20_wt": (0.0, 1.0), "t20_wf": (0.0, 1.0), "t20_wn": (0.0, 1.0), "t20_cap": (0, 10), "t20_mcap": (0, 500),
           "t20_turn": (0, 5000), "t20_capin": (0, 10**9), "t20_capus": (0, 10**9), "t20_risk": (0.25, 3.0)}
if "t20_init" not in st.session_state:
    st.session_state["t20_init"] = True
    for _k, _d in _DEFAULTS.items():
        _raw = st.query_params.get(_QKEY[_k])
        _v = _d
        if _raw is not None:
            try:
                if isinstance(_d, str):
                    _v = _raw if _raw in (MODES if _k == "t20_mode" else STRATS) else _d
                else:
                    _v = int(float(_raw)) if isinstance(_d, int) else float(_raw)
                    lo, hi = _BOUNDS[_k]
                    _v = type(_d)(min(max(_v, lo), hi))
            except (ValueError, KeyError):
                _v = _d
        st.session_state[_k] = _v

# ---------------------------------------------------------------- sidebar
ui.sidebar_brand()
T.sidebar_head("Strategy")
strat = st.sidebar.selectbox("Strategy", STRATS, key="t20_strat", label_visibility="collapsed",
                             help="Re-rank the same scored universe through one of the Screener's strategy presets.")
T.sidebar_head("List composition")
mode = st.sidebar.radio("Composition", MODES, key="t20_mode", label_visibility="collapsed")
T.sidebar_head("Diversification and liquidity")
sector_cap = st.sidebar.slider("Max picks per sector (0 = no cap)", 0, 10, key="t20_cap")
min_mcap = st.sidebar.slider("Min market cap (bn, local ccy)", 0, 500, key="t20_mcap")
min_turn = st.sidebar.slider("Min avg daily turnover (mn, local ccy)", 0, 5000, step=50, key="t20_turn",
                             help="20-day average of price x volume, in ₹ for India and $ for US. 0 = off.")
T.sidebar_head("Blend weights")
w_t = st.sidebar.slider("Technical", 0.0, 1.0, step=0.05, key="t20_wt")
w_f = st.sidebar.slider("Fundamental", 0.0, 1.0, step=0.05, key="t20_wf")
w_n = st.sidebar.slider("News", 0.0, 1.0, step=0.05, key="t20_wn")
T.sidebar_head("Position sizing hint")
risk_pct = st.sidebar.slider("Risk per trade (% of capital)", 0.25, 3.0, step=0.25, key="t20_risk")
cap_in = st.sidebar.number_input("Capital: India (₹)", min_value=0, step=100_000, key="t20_capin")
cap_us = st.sidebar.number_input("Capital: US ($)", min_value=0, step=1_000, key="t20_capus")
T.sidebar_head("Data")
if st.sidebar.button("Refresh data", use_container_width=True):
    st.cache_data.clear()

try:  # keep the setup in the URL so a bookmark restores it
    for _k, _q in _QKEY.items():
        st.query_params[_q] = str(st.session_state[_k])
except Exception:  # noqa: BLE001
    pass


@st.cache_data(ttl=1800, show_spinner=False)
def _rank_both(w):
    """Scan India and the US at the same time (about half the wait of doing them in turn)."""
    import concurrent.futures as cf

    with cf.ThreadPoolExecutor(max_workers=2) as ex:
        fi, fu = ex.submit(screener.rank, "IN", w), ex.submit(screener.rank, "US", w)
        return fi.result(), fu.result()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _extras(symbols: tuple) -> pd.DataFrame:
    return X.market_extras(list(symbols))


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _earnings(symbols: tuple) -> dict:
    return X.next_earnings(list(symbols))


@st.cache_data(ttl=3600, show_spinner=False)
def _history(mtime: float) -> pd.DataFrame:
    return X.load_history(HIST_PATH)


# ---------------------------------------------------------------- header
ui.hero(
    "Top 20 Investable Stocks",
    "Rule-based screen of ~120 India + US large-caps. Each name is scored −100…+100 from trend, "
    "momentum, fundamentals and news tone; overheated (RSI ≥ 80) or weak-fundamental stocks are excluded.",
    pills=[("Delayed data", "amber"), ("Not advice", "flat")],
)

with st.spinner("Scanning both markets — fundamentals for ~120 stocks, takes ~1 minute on first load…"):
    w = (w_t, w_f, w_n)
    try:
        ind, us = _rank_both(w)
    except Exception as exc:  # noqa: BLE001 - one failed source must not blank the page
        _log.record("top20:rank", exc)
        ind = us = pd.DataFrame()
        st.error(f"Scan failed ({type(exc).__name__}). Try Refresh data in a minute; details are under System status.")

if ind.empty and us.empty:
    ui.empty_note("<b>No stocks scored.</b> Yahoo may be rate-limiting. Try Refresh data in a minute.")
    ui.footer()
    st.stop()

# ---------------------------------------------------------------- build the candidate pool
all_pool = pd.concat([ind, us], ignore_index=True)
try:
    _ex = _extras(tuple(all_pool["Symbol"]))
except Exception as exc:  # noqa: BLE001 - risk columns are a bonus; never block the list
    _log.record("top20:extras", exc)
    _ex = X.extras_from_history({})
all_pool = all_pool.merge(_ex, on="Symbol", how="left")

pool = all_pool
if strat != STRATS[0]:
    pool = apply_filters(pool, PRESETS[strat])
if min_mcap:
    pool = pool[pool["Mkt cap"].notna() & (pool["Mkt cap"] >= min_mcap * 1e9)]
if min_turn:
    pool = pool[pool["Avg turnover"].notna() & (pool["Avg turnover"] >= min_turn * 1e6)]
pool = pool.sort_values("Score", ascending=False).reset_index(drop=True)

_bal = mode.startswith("Balanced")


def _select(frame: pd.DataFrame, n: int) -> pd.DataFrame:
    """Apply the sector cap, then take n names (balanced = n/2 per market)."""
    if _bal:
        parts = [X.cap_sector(frame[frame["Market"] == m], sector_cap).head(n // 2) for m in ("IN", "US")]
        return pd.concat(parts).sort_values("Score", ascending=False).reset_index(drop=True)
    return X.cap_sector(frame, sector_cap).head(n).reset_index(drop=True)


top = _select(pool, 20)
live_pool = _select(pool, 40)

# ---------------------------------------------------------------- summary KPIs
if top.empty:
    ui.empty_note("<b>No stocks passed.</b> Loosen the strategy, sector cap, market-cap or turnover filter in the left rail "
                  "(or try Refresh data in a minute if Yahoo is rate-limiting).")
    ui.footer()
    st.stop()

# ---------------------------------------------------------------- enrich the 20 picks
_hist = _history(HIST_PATH.stat().st_mtime if HIST_PATH.exists() else 0.0)
top = top.merge(X.history_features(_hist, top["Symbol"].tolist()), on="Symbol", how="left")
try:
    _earn = _earnings(tuple(top["Symbol"]))
except Exception as exc:  # noqa: BLE001
    _log.record("top20:earnings", exc)
    _earn = {}
top["Earnings"] = [X.earnings_label(_earn.get(s)) for s in top["Symbol"]]
_sz = [X.position_size(p, a, cap_in if m == "IN" else cap_us, risk_pct)
       for p, a, m in zip(top["Price"], top["ATR %"], top["Market"])]
top["Shares"] = [s[0] for s in _sz]
top["Position"] = [s[1] for s in _sz]
top["Stop"] = [s[2] for s in _sz]
top["Data"] = np.where(top["Stale"].fillna(False).astype(bool), "⚠ stale", "")

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

st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)


def _asof(mkt: str) -> str:
    d = all_pool.loc[all_pool["Market"] == mkt, "Last bar"].dropna()
    return pd.Timestamp(d.max()).strftime("%d %b") if len(d) else "n/a"


_stale_n = int((top["Data"] != "").sum())
_note = (f"<b>Data as of:</b> India {_asof('IN')} · US {_asof('US')} (last daily bar). "
         f"Strategy: <b>{strat}</b>" + (f" · max {sector_cap} per sector" if sector_cap else "") + ".")
if _stale_n:
    _note += f" <b>⚠ {_stale_n} pick(s) have price data older than 4 days</b> (market holiday or a data gap)."
if len(top) < (20 if not _bal else 20):
    _note += f" Only {len(top)} stocks pass these filters."
T.note(_note)
st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)

tab_live, tab_cards, tab_table, tab_scores, tab_chart = st.tabs(["LIVE RANKING", "CARDS", "TABLE", "SCORES", "LIVE CHART"])

with tab_live:
    T.note("<b>Live re-ranking.</b> Prices stream into your browser and the list re-scores itself on every tick: "
           "base score (computed once) plus a live tilt from today's move. Rows glide to their new rank; "
           "stocks entering the top 20 are tagged NEW. Prices only move while the exchange is open.")
    components.html(livepicks.build_html(live_pool.reset_index(drop=True), 20, _bal), height=20 * 46 + 190, scrolling=False)

with tab_cards:
    ui.pick_cards(top)

with tab_table:
    view = top.copy()
    view.index += 1
    st.dataframe(
        view[["Market", "Symbol", "Name", "Sector", "Price", "Day %", "3M %", "Score", "Technical",
              "Fundamental", "News", "P/E", "ROE %", "Rev growth %", "RSI", "Analyst", "Upside %",
              "Why", "ATR %", "From 52w high %", "Earnings", "Days in top 20", "Rank trend",
              "Shares", "Position", "Stop", "Data"]],
        use_container_width=True, height=760,
        column_config={
            "Score": st.column_config.ProgressColumn("Score", min_value=-100, max_value=100, format="%.1f"),
            "Rank trend": st.column_config.LineChartColumn("Rank trend (last 5 runs)", y_min=0, y_max=21,
                                                           help="Higher = better rank. Needs the twice-daily job's history."),
            "Days in top 20": st.column_config.NumberColumn("Days in top 20", format="%d"),
            "Shares": st.column_config.NumberColumn("Shares", format="%d"),
            "Position": st.column_config.NumberColumn("Position value", format="%.0f"),
            "Stop": st.column_config.NumberColumn("Stop (2×ATR)", format="%.2f"),
            **{c: st.column_config.NumberColumn(c, format="%.1f") for c in
               ["Day %", "3M %", "P/E", "ROE %", "Rev growth %", "RSI", "Upside %", "ATR %", "From 52w high %"]},
            "Price": st.column_config.NumberColumn("Price", format="%.2f"),
        },
    )
    st.download_button(
        "Download this list (CSV)",
        top.drop(columns=["Rank trend", "Stale"], errors="ignore").to_csv(index=False).encode("utf-8"),
        file_name="top20_picks.csv", mime="text/csv",
    )
    st.caption("Score = weighted blend of technical (trend, RSI, MACD, volume), fundamental (growth, ROE, margins, "
               "valuation, debt) and news tone, −100…+100. ATR % = 14-day average true range as % of price. "
               "Shares/Position/Stop: risk the chosen % of capital to a stop 2×ATR below the price, never more than "
               "the capital: a sizing illustration, not advice. ⚠ on Earnings = results within 7 days. "
               "Your settings are saved in this page's URL: bookmark or share it to keep your setup.")

    T.rule("Act on picks")
    sel = st.multiselect("Select picks", top["Symbol"].tolist(), format_func=ui.short_sym, key="t20_sel",
                         label_visibility="collapsed", placeholder="Choose picks to send to Watchlist or Compare")
    a1, a2 = st.columns(2)
    if a1.button("Add to Watchlist", disabled=not sel, use_container_width=True):
        st.session_state["wl_add"] = sel
        st.switch_page("pages/3_⭐_Watchlist.py")
    if a2.button("Compare (select exactly 2)", disabled=len(sel) != 2, use_container_width=True):
        st.session_state["cmp"] = sel
        st.switch_page("pages/10_⚖️_Compare.py")

    T.rule("How did past picks do?")
    _prices = dict(zip(all_pool["Symbol"], all_pool["Price"]))
    _past, _label = X.past_picks_performance(_hist, _prices)
    if _past.empty:
        st.caption("Not enough history yet. The twice-daily job saves each run's top 20; a comparison appears once "
                   "there is a saved run at least 7 days old.")
    else:
        pc = st.columns(3)
        T.kpi(pc[0], "Median return", f"{_past['Return %'].median():+.1f}%", f"since run {_label}",
              T.sign_tone(_past["Return %"].median()))
        T.kpi(pc[1], "Hit rate", f"{(_past['Return %'] > 0).mean() * 100:.0f}%", f"of {len(_past)} picks up", "flat")
        T.kpi(pc[2], "Best / worst", f"{_past['Return %'].max():+.0f}% / {_past['Return %'].min():+.0f}%",
              "single picks", "amber", small=True)
        st.dataframe(_past.sort_values("Return %", ascending=False).reset_index(drop=True), use_container_width=True,
                     hide_index=True, column_config={c: st.column_config.NumberColumn(c, format="%.2f")
                                                     for c in ["Price then", "Price now", "Return %"]})
        st.caption("Simple price change since that run, ignoring costs and dividends. Past results do not predict future returns.")

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
        components.html(tv.widget_html(pick.replace("-", "."), height=620), height=640)

ui.footer()
