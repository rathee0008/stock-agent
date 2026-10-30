"""Index charts: live TradingView charts for Indian (NIFTY & co.) and US (NASDAQ & co.) indices,
with a full indicator picker and a buy/sell/neutral technical gauge."""

import sys
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import theme as T, tradingview as tv, ui  # noqa: E402

ui.setup("Index Charts", "📈")

# label -> TradingView symbol
INDIA = {
    "NIFTY 50": "NSE:NIFTY",
    "BANK NIFTY": "NSE:BANKNIFTY",
    "FIN NIFTY": "NSE:CNXFINANCE",
    "NIFTY IT": "NSE:CNXIT",
    "NIFTY MIDCAP 100": "NSE:CNXMIDCAP",
    "SENSEX": "BSE:SENSEX",
    "INDIA VIX": "NSE:INDIAVIX",
}
US = {
    "NASDAQ Composite": "NASDAQ:IXIC",
    "NASDAQ 100": "NASDAQ:NDX",
    "QQQ (NASDAQ-100 ETF)": "NASDAQ:QQQ",
    "NASDAQ 100 E-mini futures": "CME_MINI:NQ1!",
    "S&P 500": "SP:SPX",
    "Dow Jones": "DJ:DJI",
    "VIX": "CBOE:VIX",
}
# label -> (chart interval, gauge interval)
TIMEFRAMES = {
    "1 min": ("1", "1m"), "5 min": ("5", "5m"), "15 min": ("15", "15m"),
    "1 hour": ("60", "1h"), "4 hour": ("240", "4h"),
    "Daily": ("D", "1D"), "Weekly": ("W", "1W"), "Monthly": ("M", "1M"),
}

ui.sidebar_brand()
T.sidebar_head("Chart")
tf = st.sidebar.selectbox("Timeframe", list(TIMEFRAMES), index=5)
theme = st.sidebar.radio("Theme", ["dark", "light"], horizontal=True)
height = st.sidebar.slider("Chart height (px)", 450, 900, 680, step=10)

T.sidebar_head("Indicators")
preset = st.sidebar.radio("Preset", ["Essentials", "All indicators", "Custom"], horizontal=True,
                          help="Essentials: SMA, EMA, Bollinger, RSI, MACD, Volume. "
                               "All indicators loads every study listed below (crowded, but complete).")
if preset == "Essentials":
    chosen = tv.DEFAULT_STUDY_NAMES
elif preset == "All indicators":
    chosen = tv.all_study_names()
else:
    chosen = []
    for group, items in tv.STUDY_CATALOG.items():
        chosen += st.sidebar.multiselect(
            group, list(items),
            default=[n for n in items if n in tv.DEFAULT_STUDY_NAMES], key=f"studies_{group}")
if st.sidebar.button("Reload charts", use_container_width=True):
    st.rerun()

ui.hero(
    "Index Charts",
    "Live TradingView charts for the NIFTY and NASDAQ families with a full indicator set, "
    "plus a technical-analysis gauge that summarises oscillators and moving averages.",
    pills=[("LIVE", "up"), ("NSE / BSE", "flat"), ("NASDAQ", "flat")],
)


def section(options: dict[str, str], key: str, market_note: str) -> None:
    label = st.radio("Index", list(options), horizontal=True, key=f"idx_{key}")
    symbol = options[label]
    interval, gauge_interval = TIMEFRAMES[tf]

    components.html(
        tv.widget_html(symbol, theme=theme, height=height, interval=interval,
                       studies=tv.study_ids(chosen)),
        height=height + 10, scrolling=False,
    )

    left, right = st.columns([2, 1])
    with left:
        st.caption(
            f"{label} · {symbol} · {tf}. {len(chosen)} indicator(s) loaded. Add or remove more from the "
            "chart's own Indicators button; draw, compare symbols and change timeframe in the widget. "
            f"{market_note} A blank chart usually means an ad/privacy blocker is cutting off TradingView."
        )
        st.link_button(f"Open {label} on TradingView ↗",
                       f"https://www.tradingview.com/chart/?symbol={symbol}")
    with right:
        components.html(tv.technical_gauge_html(symbol, gauge_interval, theme), height=460, scrolling=False)


india_tab, us_tab = st.tabs(["🇮🇳 India · NIFTY", "🇺🇸 US · NASDAQ"])
with india_tab:
    section(INDIA, "in", "NSE session is 9:15 to 15:30 IST, Monday to Friday.")
with us_tab:
    section(US, "us", "US cash session is 9:30 to 16:00 ET; futures trade nearly around the clock.")

ui.footer()
