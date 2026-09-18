"""Streamlit dashboard for the Indian-market stock analysis agent.

Run:  streamlit run app.py
"""

from __future__ import annotations

import datetime as dt
import os

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from dotenv import load_dotenv
from plotly.subplots import make_subplots

load_dotenv()

from agent import ownership as _own  # noqa: E402
from agent import tradingview as _tv  # noqa: E402
from agent.analyze import analyze_stock  # noqa: E402
from agent.data import fetch_live  # noqa: E402
from agent.llm import synthesize  # noqa: E402

st.set_page_config(page_title="Stock Analysis Agent", page_icon="📈", layout="wide")

# --------------------------------------------------------------------------
# Sidebar
# --------------------------------------------------------------------------
st.sidebar.title("📈 Stock Analysis Agent")
st.sidebar.caption("India (NSE/BSE) & US • Yahoo Finance data + live TradingView charts")

market_choice = st.sidebar.radio(
    "Market", ["🇮🇳 India (NSE/BSE)", "🇺🇸 United States"], horizontal=False,
)
market = "US" if market_choice.startswith("🇺🇸") else "IN"

if market == "IN":
    ticker = st.sidebar.text_input(
        "Ticker", value="RELIANCE",
        help="Plain NSE symbol, e.g. RELIANCE, TCS, INFY, HDFCBANK, TATASTEEL, MARUTI. "
        "Use SYMBOL.BO for BSE, ^NSEI for the Nifty 50.",
    ).strip()
else:
    ticker = st.sidebar.text_input(
        "Ticker", value="AAPL",
        help="Plain US symbol, e.g. AAPL, MSFT, TSLA, NVDA, AMZN. "
        "Use ^GSPC for the S&P 500, ^IXIC for the Nasdaq Composite.",
    ).strip()

period = st.sidebar.select_slider(
    "History window", options=["6mo", "1y", "2y", "5y"], value="2y"
)

st.sidebar.markdown("**Blend weights**")
w_tech = st.sidebar.slider("Technical", 0.0, 1.0, 0.45, 0.05)
w_fund = st.sidebar.slider("Fundamental", 0.0, 1.0, 0.40, 0.05)
w_news = st.sidebar.slider("News", 0.0, 1.0, 0.15, 0.05)

use_llm = st.sidebar.checkbox(
    "Claude synthesis",
    value=bool(os.environ.get("ANTHROPIC_API_KEY")),
    help="Needs ANTHROPIC_API_KEY in your environment or .env file.",
)
if use_llm and not os.environ.get("ANTHROPIC_API_KEY"):
    st.sidebar.warning("No ANTHROPIC_API_KEY found — will use the rule-based summary.")

run = st.sidebar.button("Analyze", type="primary", use_container_width=True)

st.sidebar.markdown("**Live chart**")
live_interval = st.sidebar.selectbox("Candle interval", ["1m", "5m", "15m", "30m", "60m"], index=1)
live_period = st.sidebar.selectbox("Session window", ["1d", "5d"], index=0)
live_auto = st.sidebar.checkbox("Auto-refresh", value=True)
live_every = st.sidebar.select_slider(
    "Refresh every", options=[15, 30, 60, 120, 300], value=60,
    format_func=lambda s: f"{s}s",
)

st.sidebar.markdown("---")
st.sidebar.caption(
    "⚠️ Automated analysis for research and education only. Not investment "
    "advice. Data may be delayed. Do your own due diligence."
)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=600)
def _run(ticker: str, weights: tuple, period: str, market: str) -> dict:
    w = {"technical": weights[0], "fundamental": weights[1], "news": weights[2]}
    return analyze_stock(ticker, weights=w, period=period, market=market)


@st.cache_data(show_spinner=False, ttl=20)
def _live(ticker: str, interval: str, period: str, bucket: int, market: str):
    """Short-TTL live fetch. ``bucket`` (a coarse timestamp) lets the fragment
    force a fresh pull on each auto-refresh while still de-duping rapid reruns.
    """
    return fetch_live(ticker, interval=interval, period=period, market=market)


@st.cache_data(show_spinner=False, ttl=6 * 3600)
def _fii_dii(symbol: str, quarters: int = 8):
    return _own.fii_dii_trend(symbol, quarters=quarters)


@st.cache_data(show_spinner=False, ttl=3600)
def _us_ownership(ticker: str):
    return _own.us_institutional_ownership(ticker)


@st.cache_data(show_spinner=False, ttl=1800)
def _synth(cache_key: str, analysis: dict, use_llm: bool) -> tuple[str, str]:
    """Cache the synthesis so tab switches / slider nudges don't re-hit the API."""
    if use_llm:
        return synthesize(analysis)
    from agent.llm import _template
    return _template(analysis), "template"


def _fmt(v, pct=False, money=False, cur="INR", nd=2):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "—"
    if pct:
        return f"{v*100:.1f}%" if abs(v) < 3 else f"{v:.1f}%"
    if money:
        if abs(v) >= 1e7:
            return f"{cur} {v/1e7:,.2f} Cr"
        return f"{cur} {v:,.{nd}f}"
    return f"{v:,.{nd}f}"


def _gauge(title: str, score: float) -> go.Figure:
    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=score,
            title={"text": title, "font": {"size": 14}},
            gauge={
                "axis": {"range": [-100, 100]},
                "bar": {"color": "#1f77b4"},
                "steps": [
                    {"range": [-100, -40], "color": "#f4c7c3"},
                    {"range": [-40, -15], "color": "#fbe6c5"},
                    {"range": [-15, 15], "color": "#eee"},
                    {"range": [15, 40], "color": "#d9ead3"},
                    {"range": [40, 100], "color": "#b6d7a8"},
                ],
            },
        )
    )
    fig.update_layout(height=220, margin=dict(l=20, r=20, t=40, b=10))
    return fig


def _price_chart(frame: pd.DataFrame, ind: dict) -> go.Figure:
    df = frame.tail(260)
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, row_heights=[0.6, 0.2, 0.2],
        vertical_spacing=0.03,
        subplot_titles=("Price · SMA20/50/200 · Bollinger", "Volume", "RSI(14)"),
    )
    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"], low=df["Low"],
            close=df["Close"], name="OHLC",
        ),
        row=1, col=1,
    )
    for col, color in (("SMA20", "#ff9800"), ("SMA50", "#2196f3"), ("SMA200", "#9c27b0")):
        if col in df:
            fig.add_trace(
                go.Scatter(x=df.index, y=df[col], name=col, line=dict(width=1, color=color)),
                row=1, col=1,
            )
    if "BB_UP" in df:
        fig.add_trace(go.Scatter(x=df.index, y=df["BB_UP"], name="BB up",
                                 line=dict(width=1, dash="dot", color="#aaa")), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["BB_LOW"], name="BB low",
                                 line=dict(width=1, dash="dot", color="#aaa"),
                                 fill="tonexty", fillcolor="rgba(150,150,150,0.08)"), row=1, col=1)
    for level, label, color in (
        (ind.get("support"), "Support", "#4caf50"),
        (ind.get("resistance"), "Resistance", "#f44336"),
    ):
        if level:
            fig.add_hline(y=level, line=dict(color=color, width=1, dash="dash"),
                          annotation_text=label, row=1, col=1)

    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Volume",
                         marker_color="#90a4ae"), row=2, col=1)
    if "RSI" in df:
        fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI",
                                 line=dict(color="#673ab7", width=1)), row=3, col=1)
        fig.add_hline(y=70, line=dict(color="#f44336", width=1, dash="dot"), row=3, col=1)
        fig.add_hline(y=30, line=dict(color="#4caf50", width=1, dash="dot"), row=3, col=1)

    fig.update_layout(height=680, margin=dict(l=10, r=10, t=30, b=10),
                      xaxis_rangeslider_visible=False, showlegend=True,
                      legend=dict(orientation="h", y=1.06))
    return fig


def _live_chart(q, cur: str, market: str = "IN") -> go.Figure:
    df = q.bars.copy()
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22],
        vertical_spacing=0.04,
    )
    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"], low=df["Low"],
            close=df["Close"], name=q.interval,
            increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
        ),
        row=1, col=1,
    )

    # Session VWAP (resets per trading day).
    session_tz = "America/New_York" if market == "US" else "Asia/Kolkata"
    if "Volume" in df and df["Volume"].sum() > 0:
        typ = (df["High"] + df["Low"] + df["Close"]) / 3
        day = df.index.tz_convert(session_tz).date if df.index.tz is not None else df.index.date
        grp = pd.Series(day, index=df.index)
        cum_pv = (typ * df["Volume"]).groupby(grp).cumsum()
        cum_v = df["Volume"].groupby(grp).cumsum().replace(0, pd.NA)
        fig.add_trace(
            go.Scatter(x=df.index, y=cum_pv / cum_v, name="VWAP",
                       line=dict(color="#ffb300", width=1.4)),
            row=1, col=1,
        )

    if q.prev_close:
        fig.add_hline(y=q.prev_close, line=dict(color="#90a4ae", width=1, dash="dash"),
                      annotation_text="prev close", annotation_position="top left",
                      row=1, col=1)
    if q.price:
        fig.add_hline(y=q.price, line=dict(color="#42a5f5", width=1),
                      annotation_text=f"{q.price:,.2f}", annotation_position="bottom left",
                      row=1, col=1)

    up = df["Close"] >= df["Open"]
    fig.add_trace(
        go.Bar(x=df.index, y=df["Volume"], name="Volume",
               marker_color=up.map({True: "#26a69a", False: "#ef5350"})),
        row=2, col=1,
    )

    # Hide non-trading gaps (nights / weekends) so candles sit flush.
    hour_gap = [16, 9.5] if market == "US" else [15.6, 9.25]
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"]), dict(bounds=hour_gap, pattern="hour")])
    fig.update_layout(
        height=560, margin=dict(l=10, r=10, t=10, b=10),
        xaxis_rangeslider_visible=False, showlegend=True,
        legend=dict(orientation="h", y=1.04), bargap=0,
    )
    fig.update_yaxes(title_text=cur, row=1, col=1)
    return fig


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
st.title("Stock Analysis Agent")

if not run and "last" not in st.session_state:
    st.info(
        "Pick a market and ticker in the sidebar and hit **Analyze**. "
        "The agent pulls live-ish price data, computes technical and "
        "fundamental scores, reads recent headlines, and blends them into a "
        "single view with a Claude-written briefing — plus a live TradingView "
        "chart and FII/DII (India) or institutional ownership (US) tabs."
    )
    st.stop()

if run:
    try:
        with st.spinner(f"Analyzing {ticker}…"):
            st.session_state["last"] = _run(ticker, (w_tech, w_fund, w_news), period, market)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not analyze '{ticker}': {exc}")
        st.stop()

a = st.session_state["last"]
sig = a["signal"]
cur = a["currency"]

# --- Header row ---------------------------------------------------------
c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
c1.subheader(f"{a['name']}")
c1.caption(f"{a['ticker']} · fetched {a['fetched_at'][:16].replace('T', ' ')} UTC")
c2.metric("Price", f"{cur} {a['price']:,.2f}", f"{a['day_change_pct']:+.2f}%")
c3.metric("Composite", f"{sig['score']:+.0f}", sig["label"])
c4.metric("Confidence", sig["confidence"], f"{sig['confidence_pct']}%")

st.warning(
    "⚠️ **Not investment advice.** This is automated, rule-based analysis on "
    "delayed data for research and education. Markets are uncertain; the "
    "'projection' below is a volatility band, not a forecast."
)

# --- Gauges -----------------------------------------------------------
g1, g2, g3, g4 = st.columns(4)
g1.plotly_chart(_gauge("Composite", sig["score"]), use_container_width=True)
g2.plotly_chart(_gauge("Technical", a["technical"]["score"]), use_container_width=True)
g3.plotly_chart(_gauge("Fundamental", a["fundamental"]["score"]), use_container_width=True)
g4.plotly_chart(_gauge("News tone", a["news"]["score"]), use_container_width=True)

own_tab_label = "🏦 FII/DII" if a.get("market") == "IN" else "🏦 Ownership"
tab_live, tab_tv, tab_brief, tab_chart, tab_tech, tab_fund, tab_own, tab_news = st.tabs(
    ["🔴 Live", "📺 TradingView", "📝 Briefing", "📊 Chart", "📉 Technical", "📋 Fundamental",
     own_tab_label, "📰 News"]
)

# --- Live chart ----------------------------------------------------
_MKT = {
    "REGULAR": "🟢 market open", "PRE": "🟡 pre-open", "PREPRE": "🟡 pre-open",
    "POST": "🟠 post-market", "POSTPOST": "🟠 closed", "CLOSED": "🔴 closed",
}


def _render_live() -> None:
    interval = st.session_state.get("_li", live_interval)
    period = st.session_state.get("_lp", live_period)
    bucket = int(dt.datetime.now().timestamp() // max(15, live_every)) if live_auto else 0
    try:
        q = _live(a["ticker"], interval, period, bucket, a.get("market", "IN"))
    except Exception as exc:  # noqa: BLE001
        st.error(f"Live data unavailable: {exc}")
        return

    if a.get("market") == "US":
        tz = dt.timezone(dt.timedelta(hours=-5))
        tz_label = "ET"
    else:
        tz = dt.timezone(dt.timedelta(hours=5, minutes=30))
        tz_label = "IST"

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric(f"Last price ({q.currency})", f"{q.price:,.2f}",
              f"{q.change:+,.2f}  ({q.change_pct:+.2f}%)")
    m2.metric("Day open", _fmt(q.day_open))
    m3.metric("Day high", _fmt(q.day_high))
    m4.metric("Day low", _fmt(q.day_low))
    m5.metric("Volume", f"{q.day_volume:,.0f}" if q.day_volume else "—")

    state = _MKT.get(q.market_state.upper(), f"· {q.market_state}")
    st.caption(
        f"{state} · {interval} candles · updated {q.fetched_at.astimezone(tz):%H:%M:%S} {tz_label}"
        + (f" · auto-refresh {live_every}s" if live_auto else " · auto-refresh off")
    )

    if q.bars is None or q.bars.empty:
        st.info("No intraday bars returned (market may be closed and Yahoo has "
                "not published the last session yet). Try the 5d window.")
        return
    st.plotly_chart(_live_chart(q, q.currency, a.get("market", "IN")), use_container_width=True,
                    key=f"live-{a['ticker']}")
    st.caption("VWAP resets each session. Delayed ~15 min — not a trading feed.")


with tab_live:
    st.session_state["_li"] = live_interval
    st.session_state["_lp"] = live_period
    if live_auto:
        # Reruns just this fragment on the interval — the analysis above is untouched.
        st.fragment(_render_live, run_every=live_every)()
    else:
        _render_live()

# --- TradingView --------------------------------------------------
with tab_tv:
    tv_symbol = _tv.tv_symbol(a["ticker"], a.get("market", "IN"))
    c1, c2 = st.columns([3, 1])
    tv_theme = c1.radio("Theme", ["dark", "light"], horizontal=True, label_visibility="collapsed")
    c2.caption(f"Symbol: `{tv_symbol}`")
    if a.get("market") == "IN":
        st.warning(
            "TradingView's free embeddable widget doesn't carry live NSE/BSE data "
            "unless you're signed in to TradingView in this browser — Indian-exchange "
            "real-time data needs a TradingView account, so the chart below may show "
            "'symbol not found'. It always works if you open it directly on "
            "TradingView instead:"
        )
        st.link_button(
            "Open on TradingView.com ↗",
            f"https://www.tradingview.com/chart/?symbol={tv_symbol}",
        )
    components.html(
        _tv.widget_html(tv_symbol, theme=tv_theme, height=650),
        height=660,
        scrolling=False,
    )
    st.caption(
        "Live TradingView chart — RSI, MACD, Bollinger Bands, SMA and volume are "
        "preloaded; use the widget's own indicator button (top toolbar) to add or "
        "remove studies, change timeframe, or draw on the chart."
    )

# --- Briefing -------------------------------------------------------
with tab_brief:
    with st.spinner("Writing synthesis…"):
        key = f"{a['ticker']}|{a['fetched_at']}|{round(a['signal']['score'])}|{use_llm}"
        text, source = _synth(key, a, use_llm)
    st.markdown(text)
    st.caption(
        f"Source: {'Claude (' + os.environ.get('STOCK_AGENT_MODEL', 'claude-sonnet-5') + ')' if source == 'claude' else 'rule-based template'}"
    )

    st.markdown("#### Statistical range (volatility band, not a forecast)")
    proj_df = pd.DataFrame(sig["projections"])
    proj_df["horizon"] = proj_df["horizon_days"].map({5: "1 week", 21: "1 month", 63: "3 months"})
    show = proj_df[["horizon", "expected_price", "low_price", "high_price",
                    "expected_return_pct", "low_pct", "high_pct"]].copy()
    show.columns = ["Horizon", f"Expected ({cur})", f"Low ({cur})", f"High ({cur})",
                    "Expected %", "Low %", "High %"]
    st.dataframe(show.style.format({
        f"Expected ({cur})": "{:,.2f}", f"Low ({cur})": "{:,.2f}", f"High ({cur})": "{:,.2f}",
        "Expected %": "{:+.1f}", "Low %": "{:+.1f}", "High %": "{:+.1f}",
    }), hide_index=True, use_container_width=True)

    st.markdown("#### How the score was built")
    for r in sig["rationale"]:
        st.markdown(r if r.startswith("•") else f"- {r}")

# --- Chart --------------------------------------------------------
with tab_chart:
    st.plotly_chart(_price_chart(a["technical"]["frame"], a["technical"]["indicators"]),
                    use_container_width=True)

# --- Technical ---------------------------------------------------
with tab_tech:
    ind = a["technical"]["indicators"]
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("RSI(14)", _fmt(ind["rsi"], nd=1))
    k2.metric("ATR %", _fmt(ind["atr_pct"], nd=2))
    k3.metric("50-DMA", _fmt(ind["sma50"]))
    k4.metric("200-DMA", _fmt(ind["sma200"]))
    k1.metric("52w high", _fmt(ind["week52_high"]))
    k2.metric("52w low", _fmt(ind["week52_low"]))
    k3.metric("Support", _fmt(ind["support"]))
    k4.metric("Resistance", _fmt(ind["resistance"]))
    st.markdown("#### Signals")
    tdf = pd.DataFrame(a["technical"]["signals"], columns=["Signal", "Note", "Points"])
    st.dataframe(
        tdf, hide_index=True, use_container_width=True,
        column_config={"Points": st.column_config.NumberColumn(format="%+d")},
    )

# --- Fundamental ------------------------------------------------
with tab_fund:
    m = a["fundamental"]["metrics"]
    if not a["fundamental"]["available"]:
        st.info("Yahoo Finance returned no usable fundamental data for this symbol.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("P/E (TTM)", _fmt(m["pe"], nd=1))
    c2.metric("Forward P/E", _fmt(m["forward_pe"], nd=1))
    c3.metric("P/B", _fmt(m["pb"], nd=2))
    c4.metric("PEG", _fmt(m["peg"], nd=2))
    c1.metric("ROE", _fmt(m["roe"], pct=True))
    c2.metric("Net margin", _fmt(m["profit_margin"], pct=True))
    c3.metric("Debt/Equity", _fmt(m["debt_to_equity"], nd=2))
    c4.metric("Rev growth", _fmt(m["revenue_growth"], pct=True))
    c1.metric("Earnings growth", _fmt(m["earnings_growth"], pct=True))
    c2.metric("Div yield", _fmt(m["dividend_yield"], pct=True))
    c3.metric("Market cap", _fmt(m["market_cap"], money=True, cur=cur))
    c4.metric("Sell-side view", (m["recommendation"] or "—").replace("_", " ").title())
    if m["sector"]:
        st.caption(f"Sector: {m['sector']} · Industry: {m['industry']}")
    if m["target_mean_price"]:
        st.caption(
            f"Street mean target: {cur} {m['target_mean_price']:,.0f} "
            f"(n={int(m['analyst_count']) if m['analyst_count'] else '?'})"
        )
    st.markdown("#### Signals")
    fdf = pd.DataFrame(a["fundamental"]["signals"], columns=["Metric", "Note", "Points"])
    if not fdf.empty:
        st.dataframe(
            fdf, hide_index=True, use_container_width=True,
            column_config={"Points": st.column_config.NumberColumn(format="%+d")},
        )

# --- Ownership: FII/DII (India) or institutional holders (US) ---------
with tab_own:
    if a.get("market") == "IN":
        with st.spinner("Fetching shareholding pattern from BSE…"):
            trend = _fii_dii(a["ticker"], 8)
        if not trend.available or trend.quarters.empty:
            st.info(
                "No BSE shareholding-pattern data found for this symbol — it may "
                "not be BSE-listed under this name, or the quarterly filing "
                "hasn't been published yet."
            )
        else:
            df = trend.quarters
            latest, prev = df.iloc[-1], df.iloc[-2] if len(df) > 1 else None

            k1, k2, k3, k4 = st.columns(4)
            k1.metric("FII / FPI holding", f"{latest['fii']:.2f}%",
                      f"{latest['fii']-prev['fii']:+.2f} pp QoQ" if prev is not None else None)
            k2.metric("DII holding", f"{latest['dii']:.2f}%",
                      f"{latest['dii']-prev['dii']:+.2f} pp QoQ" if prev is not None else None)
            k3.metric("Promoter holding", f"{latest['promoter']:.2f}%",
                      f"{latest['promoter']-prev['promoter']:+.2f} pp QoQ" if prev is not None else None)
            k4.metric("Public (non-institutional)", f"{latest['non_institutional']:.2f}%",
                      f"{latest['non_institutional']-prev['non_institutional']:+.2f} pp QoQ" if prev is not None else None)
            st.caption(f"Quarter ending {latest['quarter']} · BSE scrip code {trend.scripcode}")

            fig = go.Figure()
            for col, label, color in (
                ("promoter", "Promoter", "#9c27b0"),
                ("dii", "DII (domestic institutions)", "#2196f3"),
                ("fii", "FII/FPI (foreign)", "#ff9800"),
                ("government", "Government", "#607d8b"),
                ("non_institutional", "Public / retail / other", "#90a4ae"),
            ):
                fig.add_trace(go.Bar(x=df["quarter"], y=df[col], name=label, marker_color=color))
            fig.update_layout(
                barmode="stack", height=420, margin=dict(l=10, r=10, t=30, b=10),
                yaxis_title="% of shares held", legend=dict(orientation="h", y=1.12),
                title="Shareholding pattern by quarter",
            )
            st.plotly_chart(fig, use_container_width=True)

            show = df[["quarter", "promoter", "dii", "fii", "government", "non_institutional"]].copy()
            show.columns = ["Quarter", "Promoter %", "DII %", "FII %", "Govt %", "Non-institutional %"]
            st.dataframe(
                show.iloc[::-1], hide_index=True, use_container_width=True,
                column_config={c: st.column_config.NumberColumn(format="%.2f") for c in show.columns[1:]},
            )
            st.caption(
                "Source: BSE quarterly shareholding-pattern filings (bseindia.com), "
                "the regulatory disclosure every listed company must make each "
                "quarter. FII/FPI = 'Institutions (Foreign)'; DII = 'Institutions "
                "(Domestic)' (mutual funds, insurers, banks, AIFs, pension funds)."
            )
    else:
        with st.spinner("Fetching institutional ownership from Yahoo Finance…"):
            own = _us_ownership(a["ticker"])
        if not own.available:
            st.info("No institutional-ownership data found for this symbol.")
        else:
            k1, k2, k3 = st.columns(3)
            k1.metric("Institutional ownership", f"{own.pct_institutions:.1f}%" if own.pct_institutions is not None else "—")
            k2.metric("Insider ownership", f"{own.pct_insiders:.1f}%" if own.pct_insiders is not None else "—")
            k3.metric("# institutional holders", f"{own.holder_count:,}" if own.holder_count else "—")

            if not own.top_institutions.empty:
                t = own.top_institutions.copy()
                cols = [c for c in ["Holder", "Date Reported", "pctHeld", "Shares", "Value"] if c in t.columns]
                t = t[cols].rename(columns={"pctHeld": "% held"})
                fig = go.Figure(go.Bar(
                    x=t["% held"][:15][::-1], y=t["Holder"][:15][::-1], orientation="h",
                    marker_color="#2196f3",
                ))
                fig.update_layout(height=420, margin=dict(l=10, r=120, t=30, b=10),
                                  xaxis_title="% held", title="Top institutional holders")
                st.plotly_chart(fig, use_container_width=True)
                st.dataframe(
                    t, hide_index=True, use_container_width=True,
                    column_config={
                        "% held": st.column_config.NumberColumn(format="%.2f%%"),
                        "Shares": st.column_config.NumberColumn(format="%d"),
                        "Value": st.column_config.NumberColumn(format="$%d"),
                    },
                )
            st.caption(
                "US equities don't have an FII/DII split — this is Yahoo Finance's "
                "institutional & insider ownership (13F-derived), the closest "
                "available analog: total % of shares held by institutions, plus "
                "the largest individual institutional holders."
            )

# --- News --------------------------------------------------------
with tab_news:
    if not a["news"]["available"]:
        st.info("No recent headlines returned for this symbol.")
    for h in a["news"]["headlines"]:
        icon = {"positive": "🟢", "negative": "🔴", "neutral": "⚪"}[h["sentiment"]]
        title = f"{icon} {h['title']}"
        if h.get("link"):
            st.markdown(f"[{title}]({h['link']})  \n<small>{h.get('publisher','')}</small>",
                        unsafe_allow_html=True)
        else:
            st.markdown(title)
    st.caption("Headline tone is a keyword heuristic — treat as a rough tilt only.")
