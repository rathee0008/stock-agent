"""Terminal-style Streamlit dashboard for the stock analysis agent.

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
from agent import theme as T  # noqa: E402
from agent import tradingview as _tv  # noqa: E402
from agent.analyze import analyze_stock  # noqa: E402
from agent.data import fetch_live  # noqa: E402
from agent.llm import synthesize  # noqa: E402

st.set_page_config(
    page_title="TERMINAL · Stock Analysis Agent",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)
T.inject()
T.register_plotly()
C = T.C

# --------------------------------------------------------------------------
# Sidebar — the command rail
# --------------------------------------------------------------------------
st.sidebar.markdown(
    '<div class="sb-brand">STOCK<span>·</span>AGENT</div>'
    '<div class="sb-tag">NSE / BSE / US EQUITIES</div>',
    unsafe_allow_html=True,
)

T.sidebar_head("Instrument")
market_choice = st.sidebar.radio(
    "Market", ["IN · NSE/BSE", "US · NYSE/NASDAQ"], horizontal=True,
    label_visibility="collapsed",
)
market = "US" if market_choice.startswith("US") else "IN"

if market == "IN":
    ticker = st.sidebar.text_input(
        "Symbol", value="RELIANCE",
        help="Plain NSE symbol, e.g. RELIANCE, TCS, INFY, HDFCBANK, TATASTEEL, MARUTI. "
        "Use SYMBOL.BO for BSE, ^NSEI for the Nifty 50.",
    ).strip().upper()
else:
    ticker = st.sidebar.text_input(
        "Symbol", value="AAPL",
        help="Plain US symbol, e.g. AAPL, MSFT, TSLA, NVDA, AMZN. "
        "Use ^GSPC for the S&P 500, ^IXIC for the Nasdaq Composite.",
    ).strip().upper()

period = st.sidebar.select_slider(
    "History", options=["6mo", "1y", "2y", "5y"], value="2y"
)

T.sidebar_head("Blend weights")
w_tech = st.sidebar.slider("Technical", 0.0, 1.0, 0.45, 0.05)
w_fund = st.sidebar.slider("Fundamental", 0.0, 1.0, 0.40, 0.05)
w_news = st.sidebar.slider("News", 0.0, 1.0, 0.15, 0.05)

_wsum = w_tech + w_fund + w_news
st.sidebar.markdown(
    f'<div style="font-family:{T.MONO};font-size:.66rem;color:{C["faint"]};'
    f'letter-spacing:.06em">Σ {_wsum:.2f} · normalised at runtime</div>',
    unsafe_allow_html=True,
)

use_llm = st.sidebar.checkbox(
    "Claude synthesis",
    value=bool(os.environ.get("ANTHROPIC_API_KEY")),
    help="Needs ANTHROPIC_API_KEY in your environment or .env file.",
)
if use_llm and not os.environ.get("ANTHROPIC_API_KEY"):
    st.sidebar.warning("No ANTHROPIC_API_KEY — falling back to the rule-based summary.")

run = st.sidebar.button("▸ Run analysis", type="primary", use_container_width=True)

T.sidebar_head("Live feed")
live_interval = st.sidebar.selectbox("Candle interval", ["1m", "5m", "15m", "30m", "60m"], index=1)
live_period = st.sidebar.selectbox("Session window", ["1d", "5d"], index=0)
live_auto = st.sidebar.checkbox("Auto-refresh", value=True)
live_every = st.sidebar.select_slider(
    "Refresh every", options=[15, 30, 60, 120, 300], value=60,
    format_func=lambda s: f"{s}s",
)

st.sidebar.markdown(
    f'<div style="margin-top:1.4rem;padding-top:.7rem;border-top:1px solid {C["line"]};'
    f'font-size:.65rem;color:{C["faint"]};line-height:1.55">'
    "RESEARCH &amp; EDUCATION ONLY · NOT INVESTMENT ADVICE · DATA MAY BE DELAYED "
    "· DO YOUR OWN DUE DILIGENCE</div>",
    unsafe_allow_html=True,
)


# --------------------------------------------------------------------------
# Data helpers (unchanged logic)
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


# --------------------------------------------------------------------------
# Charts
# --------------------------------------------------------------------------
def _price_chart(frame: pd.DataFrame, ind: dict) -> go.Figure:
    df = frame.tail(260)
    fig = make_subplots(
        rows=3, cols=1, shared_xaxes=True, row_heights=[0.62, 0.18, 0.20],
        vertical_spacing=0.035,
        subplot_titles=("PRICE · SMA 20/50/200 · BOLLINGER", "VOLUME", "RSI (14)"),
    )
    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"], low=df["Low"],
            close=df["Close"], name="OHLC",
            increasing_line_color=C["up"], decreasing_line_color=C["down"],
            increasing_fillcolor=C["up"], decreasing_fillcolor=C["down"],
            line=dict(width=1),
        ),
        row=1, col=1,
    )
    for col, color in (("SMA20", C["amber"]), ("SMA50", C["blue"]), ("SMA200", C["violet"])):
        if col in df:
            fig.add_trace(
                go.Scatter(x=df.index, y=df[col], name=col,
                           line=dict(width=1.1, color=color)),
                row=1, col=1,
            )
    if "BB_UP" in df:
        fig.add_trace(go.Scatter(x=df.index, y=df["BB_UP"], name="BB up",
                                 line=dict(width=1, dash="dot", color=C["faint"])), row=1, col=1)
        fig.add_trace(go.Scatter(x=df.index, y=df["BB_LOW"], name="BB low",
                                 line=dict(width=1, dash="dot", color=C["faint"]),
                                 fill="tonexty", fillcolor="rgba(124,135,152,0.06)"), row=1, col=1)
    for level, label, color in (
        (ind.get("support"), "SUPPORT", C["up"]),
        (ind.get("resistance"), "RESISTANCE", C["down"]),
    ):
        if level:
            fig.add_hline(y=level, line=dict(color=color, width=1, dash="dash"),
                          annotation_text=label, annotation_position="top left",
                          annotation_font=dict(size=9, color=color, family=T.MONO),
                          row=1, col=1)

    fig.add_trace(go.Bar(x=df.index, y=df["Volume"], name="Volume",
                         marker_color=C["line_hi"]), row=2, col=1)
    if "RSI" in df:
        fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], name="RSI",
                                 line=dict(color=C["cyan"], width=1.1)), row=3, col=1)
        fig.add_hline(y=70, line=dict(color=C["down"], width=1, dash="dot"), row=3, col=1)
        fig.add_hline(y=30, line=dict(color=C["up"], width=1, dash="dot"), row=3, col=1)

    fig.update_layout(height=720, margin=dict(l=8, r=8, t=54, b=8),
                      xaxis_rangeslider_visible=False, showlegend=True,
                      legend=dict(orientation="h", y=1.085, x=0, yanchor="bottom"))
    for ann in fig.layout.annotations:
        ann.font = dict(size=9.5, color=C["faint"], family=T.MONO)
    return T.style_axes(fig)


def _live_chart(q, cur: str, market: str = "IN") -> go.Figure:
    df = q.bars.copy()
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.78, 0.22],
        vertical_spacing=0.035,
    )
    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"], low=df["Low"],
            close=df["Close"], name=q.interval,
            increasing_line_color=C["up"], decreasing_line_color=C["down"],
            increasing_fillcolor=C["up"], decreasing_fillcolor=C["down"],
            line=dict(width=1),
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
                       line=dict(color=C["amber"], width=1.3)),
            row=1, col=1,
        )

    if q.prev_close:
        fig.add_hline(y=q.prev_close, line=dict(color=C["faint"], width=1, dash="dash"),
                      annotation_text="PREV CLOSE", annotation_position="top left",
                      annotation_font=dict(size=9, color=C["faint"], family=T.MONO),
                      row=1, col=1)
    if q.price:
        fig.add_hline(y=q.price, line=dict(color=C["blue"], width=1),
                      annotation_text=f"{q.price:,.2f}", annotation_position="bottom left",
                      annotation_font=dict(size=9.5, color=C["blue"], family=T.MONO),
                      row=1, col=1)

    up = df["Close"] >= df["Open"]
    fig.add_trace(
        go.Bar(x=df.index, y=df["Volume"], name="Volume",
               marker_color=up.map({True: C["up"], False: C["down"]}), opacity=.55),
        row=2, col=1,
    )

    # Hide non-trading gaps (nights / weekends) so candles sit flush.
    hour_gap = [16, 9.5] if market == "US" else [15.6, 9.25]
    fig.update_xaxes(rangebreaks=[dict(bounds=["sat", "mon"]),
                                  dict(bounds=hour_gap, pattern="hour")])
    fig.update_layout(
        height=560, margin=dict(l=8, r=8, t=8, b=8),
        xaxis_rangeslider_visible=False, showlegend=True,
        legend=dict(orientation="h", y=1.05, x=0), bargap=0,
    )
    fig.update_yaxes(title_text=cur, title_font=dict(size=10, color=C["faint"]), row=1, col=1)
    return T.style_axes(fig)


# --------------------------------------------------------------------------
# Empty state
# --------------------------------------------------------------------------
if not run and "last" not in st.session_state:
    st.markdown(
        f"""
<div style="border:1px solid {C['line']};border-left:3px solid {C['amber']};
            background:linear-gradient(180deg,{C['panel']} 0%,{C['bg']} 100%);
            border-radius:3px;padding:2.2rem 2rem;margin-top:1rem">
  <div style="font-family:{T.MONO};font-size:.66rem;letter-spacing:.24em;
              color:{C['amber']};font-weight:700">STOCK ANALYSIS AGENT</div>
  <div style="font-size:1.9rem;font-weight:700;color:{C['text']};
              margin:.5rem 0 .2rem;letter-spacing:-.01em">Terminal standing by</div>
  <div style="color:{C['dim']};font-size:.9rem;max-width:62ch;line-height:1.6">
    Choose a market and symbol in the left rail, then hit
    <b style="color:{C['amber']}">Run analysis</b>. The agent pulls price history,
    scores technicals and fundamentals, reads recent headlines, and blends the
    three into one composite call.
  </div>
  <div style="display:flex;gap:.6rem;flex-wrap:wrap;margin-top:1.4rem">
    {"".join(
        f'<div style="border:1px solid {C["line"]};background:{C["panel"]};'
        f'border-radius:3px;padding:.55rem .8rem;min-width:150px">'
        f'<div style="font-family:{T.MONO};font-size:.6rem;letter-spacing:.14em;'
        f'color:{C["faint"]};font-weight:600">{k}</div>'
        f'<div style="color:{C["dim"]};font-size:.76rem;margin-top:.25rem">{v}</div></div>'
        for k, v in [
            ("LIVE", "Intraday candles, VWAP, volume"),
            ("BRIEFING", "Composite score + rationale"),
            ("CHART", "Daily OHLC, SMA, Bollinger, RSI"),
            ("OWNERSHIP", "FII/DII (IN) · 13F (US)"),
            ("NEWS", "Headline tone tilt"),
        ]
    )}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
    st.stop()

if run:
    try:
        with st.spinner(f"Fetching and scoring {ticker}…"):
            st.session_state["last"] = _run(ticker, (w_tech, w_fund, w_news), period, market)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not analyze '{ticker}': {exc}")
        st.stop()

a = st.session_state["last"]
sig = a["signal"]
cur = a["currency"]

# --------------------------------------------------------------------------
# Terminal status bar
# --------------------------------------------------------------------------
_day_tone = T.sign_tone(a["day_change_pct"])
T.status_bar(
    symbol=a["ticker"],
    name=a["name"],
    price=f"{cur} {a['price']:,.2f}",
    change=f"{a['day_change_pct']:+.2f}%",
    tone=_day_tone,
    cells=[
        ("MKT", "NSE/BSE" if a.get("market") == "IN" else "US"),
        ("WINDOW", period),
        ("FETCHED", a["fetched_at"][:16].replace("T", " ") + "Z"),
    ],
)

# --- Signal summary row -------------------------------------------------
s1, s2, s3, s4 = st.columns([1.15, 1, 1, 1])
_sig_tone = T.sign_tone(sig["score"])
T.kpi(s1, "Composite call", sig["label"].upper(),
      f"score {sig['score']:+.0f} · confidence {sig['confidence_pct']}%", _sig_tone, small=True)
T.meter(s2, "Technical", a["technical"]["score"])
T.meter(s3, "Fundamental", a["fundamental"]["score"])
T.meter(s4, "News tone", a["news"]["score"])

T.note(
    "<b>NOT INVESTMENT ADVICE.</b> Automated, rule-based analysis on delayed data "
    "for research and education. The projection below is a volatility band derived "
    "from realised vol — not a forecast."
)

# --------------------------------------------------------------------------
# Tabs
# --------------------------------------------------------------------------
own_tab_label = "FII/DII" if a.get("market") == "IN" else "OWNERSHIP"
tab_live, tab_brief, tab_chart, tab_tech, tab_fund, tab_own, tab_news, tab_tv = st.tabs(
    ["LIVE", "BRIEFING", "CHART", "TECHNICAL", "FUNDAMENTAL", own_tab_label, "NEWS", "TRADINGVIEW"]
)

_MKT = {
    "REGULAR": ("MARKET OPEN", "up"), "PRE": ("PRE-OPEN", "amber"),
    "PREPRE": ("PRE-OPEN", "amber"), "POST": ("POST-MARKET", "amber"),
    "POSTPOST": ("CLOSED", "down"), "CLOSED": ("CLOSED", "down"),
}


def _render_live() -> None:
    interval = st.session_state.get("_li", live_interval)
    period_ = st.session_state.get("_lp", live_period)
    bucket = int(dt.datetime.now().timestamp() // max(15, live_every)) if live_auto else 0
    try:
        q = _live(a["ticker"], interval, period_, bucket, a.get("market", "IN"))
    except Exception as exc:  # noqa: BLE001
        st.error(f"Live data unavailable: {exc}")
        return

    if a.get("market") == "US":
        tz, tz_label = dt.timezone(dt.timedelta(hours=-5)), "ET"
    else:
        tz, tz_label = dt.timezone(dt.timedelta(hours=5, minutes=30)), "IST"

    state_txt, state_tone = _MKT.get(q.market_state.upper(), (q.market_state.upper(), "flat"))
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:.8rem;margin:.2rem 0 .7rem">'
        f'{T.pill(state_txt, state_tone)}'
        f'<span style="font-family:{T.MONO};font-size:.68rem;color:{C["faint"]};'
        f'letter-spacing:.08em">{interval} CANDLES · UPDATED '
        f"{q.fetched_at.astimezone(tz):%H:%M:%S} {tz_label}"
        f'{f" · AUTO {live_every}S" if live_auto else " · AUTO OFF"}</span></div>',
        unsafe_allow_html=True,
    )

    m = st.columns(5)
    T.kpi(m[0], f"Last ({q.currency})", f"{q.price:,.2f}",
          f"{q.change:+,.2f}  {q.change_pct:+.2f}%", T.sign_tone(q.change))
    T.kpi(m[1], "Open", _fmt(q.day_open))
    T.kpi(m[2], "High", _fmt(q.day_high), tone="up")
    T.kpi(m[3], "Low", _fmt(q.day_low), tone="down")
    T.kpi(m[4], "Volume", f"{q.day_volume:,.0f}" if q.day_volume else "—")

    if q.bars is None or q.bars.empty:
        st.info("No intraday bars returned (market may be closed and Yahoo has "
                "not published the last session yet). Try the 5d window.")
        return
    st.markdown("<div style='height:.6rem'></div>", unsafe_allow_html=True)
    st.plotly_chart(_live_chart(q, q.currency, a.get("market", "IN")),
                    use_container_width=True, key=f"live-{a['ticker']}")
    st.caption("VWAP resets each session · delayed ~15 min · not a trading feed")


with tab_live:
    st.session_state["_li"] = live_interval
    st.session_state["_lp"] = live_period
    if live_auto:
        st.fragment(_render_live, run_every=live_every)()
    else:
        _render_live()

# --- Briefing -----------------------------------------------------------
with tab_brief:
    with st.spinner("Writing synthesis…"):
        key = f"{a['ticker']}|{a['fetched_at']}|{round(a['signal']['score'])}|{use_llm}"
        text, source = _synth(key, a, use_llm)
    st.markdown(text)
    st.markdown(
        f'<div style="font-family:{T.MONO};font-size:.64rem;color:{C["faint"]};'
        f'letter-spacing:.08em;margin-top:.6rem">SOURCE: '
        + ("CLAUDE · " + os.environ.get("STOCK_AGENT_MODEL", "claude-sonnet-5").upper()
           if source == "claude" else "RULE-BASED TEMPLATE")
        + "</div>",
        unsafe_allow_html=True,
    )

    T.rule("Statistical range · volatility band, not a forecast")
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

    T.rule("How the score was built")
    for r in sig["rationale"]:
        st.markdown(r if r.startswith("•") else f"- {r}")

# --- Chart --------------------------------------------------------------
with tab_chart:
    st.plotly_chart(_price_chart(a["technical"]["frame"], a["technical"]["indicators"]),
                    use_container_width=True)

# --- Technical ----------------------------------------------------------
with tab_tech:
    ind = a["technical"]["indicators"]
    _rsi = ind["rsi"]
    _rsi_tone = "down" if (_rsi or 50) > 70 else "up" if (_rsi or 50) < 30 else "flat"
    r1 = st.columns(4)
    T.kpi(r1[0], "RSI (14)", _fmt(_rsi, nd=1),
          "overbought" if _rsi_tone == "down" else "oversold" if _rsi_tone == "up" else "neutral",
          _rsi_tone)
    T.kpi(r1[1], "ATR %", _fmt(ind["atr_pct"], nd=2))
    T.kpi(r1[2], "50-DMA", _fmt(ind["sma50"]))
    T.kpi(r1[3], "200-DMA", _fmt(ind["sma200"]))
    st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)
    r2 = st.columns(4)
    T.kpi(r2[0], "52W high", _fmt(ind["week52_high"]))
    T.kpi(r2[1], "52W low", _fmt(ind["week52_low"]))
    T.kpi(r2[2], "Support", _fmt(ind["support"]), tone="up")
    T.kpi(r2[3], "Resistance", _fmt(ind["resistance"]), tone="down")

    T.rule("Signal scorecard")
    tdf = pd.DataFrame(a["technical"]["signals"], columns=["Signal", "Note", "Points"])
    st.dataframe(
        tdf, hide_index=True, use_container_width=True,
        column_config={"Points": st.column_config.NumberColumn(format="%+d")},
    )

# --- Fundamental --------------------------------------------------------
with tab_fund:
    m = a["fundamental"]["metrics"]
    if not a["fundamental"]["available"]:
        st.info("Yahoo Finance returned no usable fundamental data for this symbol.")
    f1 = st.columns(4)
    T.kpi(f1[0], "P/E (TTM)", _fmt(m["pe"], nd=1))
    T.kpi(f1[1], "Forward P/E", _fmt(m["forward_pe"], nd=1))
    T.kpi(f1[2], "P/B", _fmt(m["pb"], nd=2))
    T.kpi(f1[3], "PEG", _fmt(m["peg"], nd=2))
    st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)
    f2 = st.columns(4)
    T.kpi(f2[0], "ROE", _fmt(m["roe"], pct=True))
    T.kpi(f2[1], "Net margin", _fmt(m["profit_margin"], pct=True))
    T.kpi(f2[2], "Debt / equity", _fmt(m["debt_to_equity"], nd=2))
    T.kpi(f2[3], "Revenue growth", _fmt(m["revenue_growth"], pct=True),
          tone=T.sign_tone(m["revenue_growth"]))
    st.markdown("<div style='height:.5rem'></div>", unsafe_allow_html=True)
    f3 = st.columns(4)
    T.kpi(f3[0], "Earnings growth", _fmt(m["earnings_growth"], pct=True),
          tone=T.sign_tone(m["earnings_growth"]))
    T.kpi(f3[1], "Dividend yield", _fmt(m["dividend_yield"], pct=True))
    T.kpi(f3[2], "Market cap", _fmt(m["market_cap"], money=True, cur=cur), small=True)
    T.kpi(f3[3], "Sell-side view",
          (m["recommendation"] or "—").replace("_", " ").upper(), small=True)

    _meta = []
    if m["sector"]:
        _meta.append(f"SECTOR {m['sector']} · INDUSTRY {m['industry']}")
    if m["target_mean_price"]:
        _meta.append(
            f"STREET MEAN TARGET {cur} {m['target_mean_price']:,.0f} "
            f"(n={int(m['analyst_count']) if m['analyst_count'] else '?'})"
        )
    if _meta:
        st.markdown(
            f'<div style="font-family:{T.MONO};font-size:.66rem;color:{C["faint"]};'
            f'letter-spacing:.07em;margin-top:.8rem">' + " &nbsp;|&nbsp; ".join(_meta)
            + "</div>", unsafe_allow_html=True,
        )

    fdf = pd.DataFrame(a["fundamental"]["signals"], columns=["Metric", "Note", "Points"])
    if not fdf.empty:
        T.rule("Signal scorecard")
        st.dataframe(
            fdf, hide_index=True, use_container_width=True,
            column_config={"Points": st.column_config.NumberColumn(format="%+d")},
        )

# --- Ownership ----------------------------------------------------------
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
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) > 1 else None

            def _qoq(col):
                if prev is None:
                    return None, "flat"
                d = latest[col] - prev[col]
                return f"{d:+.2f} pp QoQ", T.sign_tone(d)

            o = st.columns(4)
            for i, (col, label) in enumerate([
                ("fii", "FII / FPI holding"), ("dii", "DII holding"),
                ("promoter", "Promoter holding"), ("non_institutional", "Public / retail"),
            ]):
                sub, tone = _qoq(col)
                T.kpi(o[i], label, f"{latest[col]:.2f}%", sub, tone)

            st.markdown(
                f'<div style="font-family:{T.MONO};font-size:.66rem;color:{C["faint"]};'
                f'letter-spacing:.07em;margin-top:.7rem">QUARTER ENDING '
                f"{latest['quarter']} · BSE SCRIP {trend.scripcode}</div>",
                unsafe_allow_html=True,
            )

            T.rule("Shareholding pattern by quarter")
            fig = go.Figure()
            for col, label, color in (
                ("promoter", "Promoter", C["violet"]),
                ("dii", "DII (domestic)", C["blue"]),
                ("fii", "FII/FPI (foreign)", C["amber"]),
                ("government", "Government", C["faint"]),
                ("non_institutional", "Public / retail", C["line_hi"]),
            ):
                fig.add_trace(go.Bar(x=df["quarter"], y=df[col], name=label,
                                     marker_color=color, marker_line_width=0))
            fig.update_layout(
                barmode="stack", height=420, margin=dict(l=8, r=8, t=8, b=8),
                yaxis_title="% of shares held",
                yaxis_title_font=dict(size=10, color=C["faint"]),
                legend=dict(orientation="h", y=1.1, x=0), bargap=.35,
            )
            st.plotly_chart(T.style_axes(fig), use_container_width=True)

            show = df[["quarter", "promoter", "dii", "fii", "government",
                       "non_institutional"]].copy()
            show.columns = ["Quarter", "Promoter %", "DII %", "FII %", "Govt %",
                            "Non-institutional %"]
            st.dataframe(
                show.iloc[::-1], hide_index=True, use_container_width=True,
                column_config={c: st.column_config.NumberColumn(format="%.2f")
                               for c in show.columns[1:]},
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
            o = st.columns(3)
            T.kpi(o[0], "Institutional ownership",
                  f"{own.pct_institutions:.1f}%" if own.pct_institutions is not None else "—")
            T.kpi(o[1], "Insider ownership",
                  f"{own.pct_insiders:.1f}%" if own.pct_insiders is not None else "—")
            T.kpi(o[2], "Institutional holders",
                  f"{own.holder_count:,}" if own.holder_count else "—")

            if not own.top_institutions.empty:
                t = own.top_institutions.copy()
                cols = [c for c in ["Holder", "Date Reported", "pctHeld", "Shares", "Value"]
                        if c in t.columns]
                t = t[cols].rename(columns={"pctHeld": "% held"})
                T.rule("Top institutional holders")
                fig = go.Figure(go.Bar(
                    x=t["% held"][:15][::-1], y=t["Holder"][:15][::-1], orientation="h",
                    marker_color=C["amber"], marker_line_width=0,
                ))
                fig.update_layout(height=430, margin=dict(l=8, r=100, t=8, b=8),
                                  xaxis_title="% held",
                                  xaxis_title_font=dict(size=10, color=C["faint"]))
                st.plotly_chart(T.style_axes(fig), use_container_width=True)
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
                "available analog."
            )

# --- News ---------------------------------------------------------------
with tab_news:
    if not a["news"]["available"]:
        st.info("No recent headlines returned for this symbol.")
    _dot = {"positive": C["up"], "negative": C["down"], "neutral": C["faint"]}
    rows = []
    for h in a["news"]["headlines"]:
        colour = _dot[h["sentiment"]]
        title = h["title"].replace("<", "&lt;")
        link = h.get("link")
        title_html = (f'<a href="{link}" target="_blank">{title}</a>'
                      if link else f'<span style="color:{C["text"]}">{title}</span>')
        rows.append(
            f'<div class="hl"><span class="hl-dot" style="color:{colour}">●</span>'
            f'<div>{title_html}<div class="hl-src">{h.get("publisher","")}</div></div></div>'
        )
    st.markdown("".join(rows), unsafe_allow_html=True)
    st.caption("Headline tone is a keyword heuristic — treat as a rough tilt only.")

# --- TradingView --------------------------------------------------------
with tab_tv:
    tv_symbol = _tv.tv_symbol(a["ticker"], a.get("market", "IN"))
    st.markdown(
        f'<div style="font-family:{T.MONO};font-size:.68rem;color:{C["faint"]};'
        f'letter-spacing:.09em;margin-bottom:.5rem">SYMBOL '
        f'<b style="color:{C["amber"]}">{tv_symbol}</b></div>',
        unsafe_allow_html=True,
    )
    if a.get("market") == "IN":
        # NSE/BSE data is not licensed for TradingView's free embeddable widget —
        # it always answers "This symbol is only available on TradingView".
        T.note(
            "<b>NSE/BSE is not available in the embeddable widget.</b> TradingView "
            "does not license Indian-exchange data to the free embed for any site, "
            "so the chart would render empty here. Use the LIVE and CHART tabs for "
            "Indian symbols, or open the full chart on TradingView:"
        )
        st.link_button(f"Open {tv_symbol} on TradingView.com ↗",
                       f"https://www.tradingview.com/chart/?symbol={tv_symbol}")
    else:
        tv_theme = st.radio("Theme", ["dark", "light"], horizontal=True,
                            label_visibility="collapsed")
        components.html(
            _tv.widget_html(tv_symbol, theme=tv_theme, height=650),
            height=660, scrolling=False,
        )
        st.caption(
            "RSI, MACD, Bollinger Bands, SMA and volume are preloaded; use the "
            "widget's own toolbar to add studies, change timeframe, or draw. "
            "A blank chart here usually means an ad/privacy blocker is cutting "
            "TradingView's data socket."
        )
