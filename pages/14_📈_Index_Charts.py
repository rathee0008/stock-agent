"""Index charts: NIFTY (India) and NASDAQ (US) with a full indicator set.

NSE symbols are blocked in TradingView's free embed, so NSE indices default to the built-in chart
(Yahoo data, indicators computed in agent/indexchart.py). SENSEX and the US indices use TradingView.
"""

import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import indexchart as IC, theme as T, tradingview as tv, ui  # noqa: E402

ui.setup("Index Charts", "📈")
C = T.C

# label -> (TradingView symbol, Yahoo symbol, TradingView embed allowed?)
INDIA = {
    "NIFTY 50": ("NSE:NIFTY", "^NSEI", False),
    "BANK NIFTY": ("NSE:BANKNIFTY", "^NSEBANK", False),
    "FIN NIFTY": ("NSE:CNXFINANCE", "NIFTY_FIN_SERVICE.NS", False),
    "NIFTY IT": ("NSE:CNXIT", "^CNXIT", False),
    "NIFTY MIDCAP 100": ("NSE:CNXMIDCAP", "NIFTY_MIDCAP_100.NS", False),
    "SENSEX": ("BSE:SENSEX", "^BSESN", True),
    "INDIA VIX": ("NSE:INDIAVIX", "^INDIAVIX", False),
}
US = {
    "NASDAQ Composite": ("NASDAQ:IXIC", "^IXIC", True),
    "NASDAQ 100": ("NASDAQ:NDX", "^NDX", True),
    "QQQ (NASDAQ-100 ETF)": ("NASDAQ:QQQ", "QQQ", True),
    "NASDAQ 100 E-mini futures": ("CME_MINI:NQ1!", "NQ=F", True),
    "S&P 500": ("SP:SPX", "^GSPC", True),
    "Dow Jones": ("DJ:DJI", "^DJI", True),
    "VIX": ("CBOE:VIX", "^VIX", True),
}
# label -> (TradingView chart interval, gauge interval)
TIMEFRAMES = {
    "1 min": ("1", "1m"), "5 min": ("5", "5m"), "15 min": ("15", "15m"),
    "1 hour": ("60", "1h"), "4 hour": ("240", "4h"),
    "Daily": ("D", "1D"), "Weekly": ("W", "1W"), "Monthly": ("M", "1M"),
}
BUILTIN = {"1 min", "5 min", "15 min", "1 hour", "Daily", "Weekly", "Monthly"}

ui.sidebar_brand()
T.sidebar_head("Chart")
tf = st.sidebar.selectbox("Timeframe", list(TIMEFRAMES), index=5)
theme = st.sidebar.radio("Theme (TradingView)", ["dark", "light"], horizontal=True)
height = st.sidebar.slider("Chart height (px)", 450, 950, 720, step=10)
refresh = st.sidebar.select_slider("Built-in chart refresh (s)", options=[15, 30, 60, 120, 300], value=60)

T.sidebar_head("Indicators")
preset = st.sidebar.radio("Preset", ["Essentials", "All indicators", "Custom"], horizontal=True,
                          help="Essentials: SMA, EMA, Bollinger, Volume, RSI, MACD. All indicators loads every "
                               "study (crowded, but complete). Custom lets you pick.")
if preset == "Essentials":
    tv_chosen, ic_chosen = tv.DEFAULT_STUDY_NAMES, IC.DEFAULT_INDICATORS
elif preset == "All indicators":
    tv_chosen, ic_chosen = tv.all_study_names(), IC.ALL_INDICATORS
else:
    ic_chosen = st.sidebar.multiselect("Built-in chart", IC.ALL_INDICATORS, default=IC.DEFAULT_INDICATORS)
    tv_chosen = []
    for group, items in tv.STUDY_CATALOG.items():
        tv_chosen += st.sidebar.multiselect(
            f"TradingView · {group}", list(items),
            default=[n for n in items if n in tv.DEFAULT_STUDY_NAMES], key=f"studies_{group}")
if st.sidebar.button("Reload charts", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

ui.hero(
    "Index Charts",
    "NIFTY and NASDAQ charts with a full indicator set. NSE indices use the built-in chart because "
    "TradingView's free embed does not allow NSE symbols; SENSEX and the US indices use live TradingView.",
    pills=[("LIVE", "up"), ("NSE / BSE", "flat"), ("NASDAQ", "flat")],
)


@st.cache_data(ttl=30, show_spinner=False)
def bars_for(yahoo_symbol: str, timeframe: str, market: str):
    return IC.load_bars(yahoo_symbol, timeframe, market)


def builtin_chart(label: str, yahoo_symbol: str, market: str, indicators: list[str]) -> None:
    timeframe = tf if tf in BUILTIN else "1 hour"
    if timeframe != tf:
        st.caption("4-hour bars are not available in the built-in chart; showing 1 hour.")
    run_every = refresh if timeframe in IC.INTRADAY else None

    @st.fragment(run_every=run_every)
    def draw():
        try:
            df = bars_for(yahoo_symbol, timeframe, market)
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Could not load {label} ({yahoo_symbol}): {exc}")
            return
        last, prev = float(df["Close"].iloc[-1]), float(df["Close"].iloc[-2]) if len(df) > 1 else float(df["Close"].iloc[-1])
        chg = (last / prev - 1) * 100 if prev else 0.0
        tone = C["up"] if chg >= 0 else C["down"]
        st.markdown(
            f'<div style="font-family:var(--mono);margin:.2rem 0 .4rem">'
            f'<span style="font-size:1.35rem;font-weight:700">{last:,.2f}</span> '
            f'<span style="color:{tone};font-weight:700">{chg:+.2f}%</span> '
            f'<span style="color:{C["dim"]};font-size:.75rem">vs previous bar · last bar '
            f'{df.index[-1]:%d %b %H:%M} · Yahoo, ~15 min delayed · {timeframe}</span></div>',
            unsafe_allow_html=True)
        fig = IC.build_figure(df, indicators, title=f"{label} · {timeframe}", height=height)
        st.plotly_chart(fig, use_container_width=True, config={"displaylogo": False, "scrollZoom": True})

        rows = IC.readout(df)
        if rows:
            b, s, n = IC.summary(rows)
            st.markdown(
                f'<div style="font-family:var(--mono);font-size:.8rem;margin:.3rem 0">'
                f'<b>Indicator readout</b> &nbsp; <span style="color:{C["up"]}">{b} bullish</span> · '
                f'<span style="color:{C["down"]}">{s} bearish</span> · {n} neutral '
                f'<span style="color:{C["dim"]}">(rule-of-thumb reads of the latest bar, not advice)</span></div>',
                unsafe_allow_html=True)
            st.dataframe([{"Indicator": a, "Value": v, "Read": t} for a, v, t in rows],
                         hide_index=True, use_container_width=True)

    draw()


def tradingview_chart(label: str, symbol: str, blocked: bool, market_note: str) -> None:
    interval, gauge_interval = TIMEFRAMES[tf]
    if blocked:
        st.warning("TradingView's free embed refuses NSE symbols, so this will likely show 'only available on "
                   "TradingView'. Use the built-in chart, or open it on tradingview.com.")
    components.html(
        tv.widget_html(symbol, theme=theme, height=height, interval=interval, studies=tv.study_ids(tv_chosen)),
        height=height + 10, scrolling=False)
    left, right = st.columns([2, 1])
    with left:
        st.caption(f"{label} · {symbol} · {tf}. {len(tv_chosen)} indicator(s) loaded; add more, draw or compare "
                   f"from the chart's own toolbar. {market_note} A blank chart usually means an ad/privacy "
                   "blocker is cutting off TradingView.")
        st.link_button(f"Open {label} on TradingView ↗", f"https://www.tradingview.com/chart/?symbol={symbol}")
    with right:
        components.html(tv.technical_gauge_html(symbol, gauge_interval, theme), height=460, scrolling=False)


def section(options: dict, key: str, market: str, market_note: str) -> None:
    label = st.radio("Index", list(options), horizontal=True, key=f"idx_{key}")
    tv_symbol, yahoo_symbol, tv_ok = options[label]
    engines = ["Built-in chart", "TradingView"]
    engine = st.radio("Chart", engines, index=1 if tv_ok else 0, horizontal=True, key=f"eng_{key}_{label}",
                      help="Built-in: candles + indicators from Yahoo data (works for every index). "
                           "TradingView: live embedded chart with its own indicator toolbox.")
    if engine == "Built-in chart":
        builtin_chart(label, yahoo_symbol, market, ic_chosen)
        st.caption(market_note)
    else:
        tradingview_chart(label, tv_symbol, not tv_ok, market_note)


india_tab, us_tab = st.tabs(["🇮🇳 India · NIFTY", "🇺🇸 US · NASDAQ"])
with india_tab:
    section(INDIA, "in", "IN", "NSE session is 9:15 to 15:30 IST, Monday to Friday.")
with us_tab:
    section(US, "us", "US", "US cash session is 9:30 to 16:00 ET; futures trade nearly around the clock.")

ui.footer()
