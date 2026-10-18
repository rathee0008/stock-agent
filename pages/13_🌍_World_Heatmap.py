"""World markets heatmap: headline index of ~36 exchanges as a world map or a treemap, auto-refreshing."""

import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
import yfinance as yf

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import theme as T, ui  # noqa: E402

ui.setup("World Heatmap", "🌍")
C = T.C

ui.sidebar_brand()
T.sidebar_head("View")
view = st.sidebar.radio("Chart", ["World map", "Treemap"], horizontal=True)
T.sidebar_head("Live")
refresh = st.sidebar.select_slider("Auto-refresh (seconds)", options=[15, 30, 60, 120, 300], value=60)
limit = st.sidebar.select_slider("Colour scale ±%", options=[1, 2, 3, 5], value=3)

# country, ISO-3, exchange, index name, Yahoo symbol, region, approx. market cap (US$ trillion)
# Market caps are rounded approximations used ONLY to size treemap tiles.
MARKETS = [
    ("United States", "USA", "NYSE/Nasdaq", "S&P 500", "^GSPC", "Americas", 62),
    ("Canada", "CAN", "TSX", "S&P/TSX", "^GSPTSE", "Americas", 3.3),
    ("Mexico", "MEX", "BMV", "IPC", "^MXX", "Americas", 0.5),
    ("Brazil", "BRA", "B3", "Bovespa", "^BVSP", "Americas", 1.0),
    ("Argentina", "ARG", "BCBA", "Merval", "^MERV", "Americas", 0.1),
    ("Chile", "CHL", "Santiago", "IPSA", "^IPSA", "Americas", 0.2),
    ("United Kingdom", "GBR", "LSE", "FTSE 100", "^FTSE", "Europe", 3.2),
    ("Germany", "DEU", "Xetra", "DAX", "^GDAXI", "Europe", 2.4),
    ("France", "FRA", "Euronext Paris", "CAC 40", "^FCHI", "Europe", 3.2),
    ("Italy", "ITA", "Borsa Italiana", "FTSE MIB", "FTSEMIB.MI", "Europe", 0.9),
    ("Spain", "ESP", "BME", "IBEX 35", "^IBEX", "Europe", 0.9),
    ("Netherlands", "NLD", "Euronext Amsterdam", "AEX", "^AEX", "Europe", 1.2),
    ("Belgium", "BEL", "Euronext Brussels", "BEL 20", "^BFX", "Europe", 0.4),
    ("Switzerland", "CHE", "SIX", "SMI", "^SSMI", "Europe", 1.9),
    ("Sweden", "SWE", "Nasdaq Stockholm", "OMXS30", "^OMX", "Europe", 1.0),
    ("Denmark", "DNK", "Nasdaq Copenhagen", "OMXC25", "^OMXC25", "Europe", 0.7),
    ("Austria", "AUT", "Wiener Börse", "ATX", "^ATX", "Europe", 0.15),
    ("Poland", "POL", "GPW", "WIG20", "WIG20.WA", "Europe", 0.2),
    ("Turkey", "TUR", "Borsa Istanbul", "BIST 100", "XU100.IS", "Europe", 0.3),
    ("Israel", "ISR", "TASE", "TA-125", "^TA125.TA", "Middle East & Africa", 0.3),
    ("Saudi Arabia", "SAU", "Tadawul", "TASI", "^TASI.SR", "Middle East & Africa", 2.6),
    ("South Africa", "ZAF", "JSE", "FTSE/JSE All Share", "^J203.JO", "Middle East & Africa", 1.0),
    ("Egypt", "EGY", "EGX", "EGX 30", "^CASE30", "Middle East & Africa", 0.05),
    ("India", "IND", "NSE", "NIFTY 50", "^NSEI", "Asia-Pacific", 5.0),
    ("China", "CHN", "Shanghai SE", "SSE Composite", "000001.SS", "Asia-Pacific", 9.0),
    ("Hong Kong", "HKG", "HKEX", "Hang Seng", "^HSI", "Asia-Pacific", 4.5),
    ("Japan", "JPN", "Tokyo SE", "Nikkei 225", "^N225", "Asia-Pacific", 6.0),
    ("South Korea", "KOR", "KRX", "KOSPI", "^KS11", "Asia-Pacific", 2.0),
    ("Taiwan", "TWN", "TWSE", "TAIEX", "^TWII", "Asia-Pacific", 2.0),
    ("Singapore", "SGP", "SGX", "STI", "^STI", "Asia-Pacific", 0.6),
    ("Malaysia", "MYS", "Bursa Malaysia", "KLCI", "^KLSE", "Asia-Pacific", 0.4),
    ("Indonesia", "IDN", "IDX", "Jakarta Composite", "^JKSE", "Asia-Pacific", 0.8),
    ("Thailand", "THA", "SET", "SET Index", "^SET.BK", "Asia-Pacific", 0.5),
    ("Philippines", "PHL", "PSE", "PSEi", "PSEI.PS", "Asia-Pacific", 0.25),
    ("Pakistan", "PAK", "PSX", "KSE-100", "^KSE", "Asia-Pacific", 0.05),
    ("Australia", "AUS", "ASX", "S&P/ASX 200", "^AXJO", "Asia-Pacific", 1.8),
    ("New Zealand", "NZL", "NZX", "NZX 50", "^NZ50", "Asia-Pacific", 0.2),
]
COLS = ["country", "iso3", "exchange", "index", "symbol", "region", "mcap"]
META = pd.DataFrame(MARKETS, columns=COLS)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_prices() -> pd.DataFrame:
    """Latest price and % change vs previous close for every index."""
    raw = yf.download(
        list(META["symbol"]),
        period="7d",
        interval="1d",
        group_by="ticker",
        threads=True,
        progress=False,
        auto_adjust=False,
    )
    rows = []
    for sym in META["symbol"]:
        try:
            closes = raw[sym]["Close"].dropna()
            if len(closes) < 2:
                continue
            last, prev = float(closes.iloc[-1]), float(closes.iloc[-2])
            rows.append(
                {
                    "symbol": sym,
                    "price": last,
                    "pct": (last / prev - 1) * 100,
                    "asof": closes.index[-1].strftime("%d %b"),
                }
            )
        except Exception:
            continue  # symbol missing / delisted on Yahoo — skipped, listed below
    prices = pd.DataFrame(rows, columns=["symbol", "price", "pct", "asof"])
    return META.merge(prices, on="symbol", how="left")



SCALE = lambda: [(0, C["down"]), (0.5, "#1B1E24"), (1, C["up"])]


def _style(fig, height):
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=0, b=0), paper_bgcolor="rgba(0,0,0,0)",
                      coloraxis_colorbar=dict(title="% chg", ticksuffix="%"))
    return fig


def world_map(df, lim):
    fig = px.choropleth(
        df, locations="iso3", color="pct", hover_name="country",
        hover_data={"iso3": False, "pct": ":+.2f", "exchange": True, "index": True, "price": ":,.2f", "asof": True},
        color_continuous_scale=SCALE(), range_color=(-lim, lim), color_continuous_midpoint=0,
        labels={"pct": "% change", "asof": "as of"},
    )
    fig.update_geos(showframe=False, showcoastlines=False, showcountries=True, countrycolor="#2a2f3a",
                    bgcolor="rgba(0,0,0,0)", landcolor="#161a22", projection_type="natural earth")
    return _style(fig, 560)


def treemap(df, lim):
    fig = px.treemap(
        df, path=[px.Constant("World"), "region", "country"], values="mcap", color="pct",
        color_continuous_scale=SCALE(), range_color=(-lim, lim), color_continuous_midpoint=0,
        custom_data=["index", "exchange", "pct", "price", "asof"],
    )
    fig.update_traces(
        texttemplate="<b>%{label}</b><br>%{customdata[0]}<br>%{customdata[2]:+.2f}%",
        hovertemplate="<b>%{label}</b><br>%{customdata[1]} · %{customdata[0]}<br>Level: %{customdata[3]:,.2f}"
                      "<br>Change: %{customdata[2]:+.2f}%<br>As of %{customdata[4]}<extra></extra>",
        marker=dict(line=dict(width=1, color="#0A0B0D")),
    )
    return _style(fig, 620)


ui.hero(
    "World Heatmap",
    "Headline index of each major stock exchange, coloured by today's move vs the previous close. "
    "Switch between a world map and a treemap in the left rail.",
    pills=[("Delayed data", "amber"), ("Auto-refresh", "flat")],
)


@st.fragment(run_every=refresh)
def live_panel():
    if refresh <= 30:
        fetch_prices.clear()
    data = fetch_prices()
    ok = data.dropna(subset=["pct"])
    missing = data[data["pct"].isna()]
    if ok.empty:
        ui.empty_note("<b>No prices returned.</b> Yahoo may be rate-limiting. It will retry on the next refresh.")
        return

    best, worst = ok.loc[ok["pct"].idxmax()], ok.loc[ok["pct"].idxmin()]
    k = st.columns(4)
    T.kpi(k[0], "Top mover", str(best["country"]), f"{best['pct']:+.2f}%", "up", small=True)
    T.kpi(k[1], "Weakest", str(worst["country"]), f"{worst['pct']:+.2f}%", "down", small=True)
    T.kpi(k[2], "Advancing / declining", f"{int((ok['pct'] > 0).sum())} / {int((ok['pct'] < 0).sum())}",
          f"of {len(ok)} markets", "flat")
    T.kpi(k[3], "Average move", f"{ok['pct'].mean():+.2f}%", "all markets", T.sign_tone(ok["pct"].mean()))
    st.markdown("<div style='height:.8rem'></div>", unsafe_allow_html=True)

    st.plotly_chart(world_map(ok, limit) if view == "World map" else treemap(ok, limit), use_container_width=True)

    st.caption(
        f"Updated {datetime.now(timezone.utc).strftime('%H:%M:%S')} UTC · refreshes every {refresh}s · Yahoo Finance, "
        "typically ~15 min delayed; closed markets show the last session's move. Treemap tile size uses rounded "
        "approximate market caps."
    )
    t = ok[["country", "exchange", "index", "price", "pct", "asof"]].sort_values("pct", ascending=False)
    st.dataframe(
        t.rename(columns={"pct": "% change", "asof": "as of"}), hide_index=True, use_container_width=True,
        column_config={"% change": st.column_config.NumberColumn(format="%+.2f"),
                       "price": st.column_config.NumberColumn(format="%.2f")},
    )
    if not missing.empty:
        with st.expander(f"{len(missing)} exchange(s) with no data right now"):
            st.write(", ".join(missing["country"] + " (" + missing["symbol"] + ")"))


live_panel()
ui.footer()
