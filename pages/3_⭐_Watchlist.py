"""Personal watchlist: live price, momentum and technical score for your own tickers."""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import screener, technical as _tech, theme as T, ui, universe  # noqa: E402

ui.setup("Watchlist", "⭐")
C = T.C

DEFAULT = "RELIANCE, TCS, HDFCBANK, AAPL, NVDA, MSFT"

# ---------------------------------------------------------------- sidebar
ui.sidebar_brand()
T.sidebar_head("Your tickers")
saved = st.query_params.get("w", DEFAULT)
raw = st.sidebar.text_area("Comma-separated symbols", value=saved, height=120,
                           help="Indian large-caps are detected automatically. Use SYMBOL.NS / SYMBOL.BO "
                                "to force an exchange, or plain US tickers like AAPL.")
unknown_as = st.sidebar.radio("Unknown symbols are", ["US", "India (NSE)"], horizontal=True)
T.sidebar_head("Data")
if st.sidebar.button("Refresh", use_container_width=True):
    st.cache_data.clear()

IN_SET = set(universe.IN)


def _resolve(tok: str) -> str:
    t = tok.strip().upper()
    if not t or t.startswith("^") or "." in t:
        return t
    if t in IN_SET:
        return f"{t}.NS"
    return f"{t}.NS" if unknown_as.startswith("India") else t


syms: list[str] = []
for tok in raw.replace("\n", ",").split(","):
    s = _resolve(tok)
    if s and s not in syms:
        syms.append(s)
syms = syms[:30]
try:
    st.query_params["w"] = ", ".join(s.replace(".NS", "") if s.endswith(".NS") else s for s in syms)
except Exception:  # noqa: BLE001
    pass


@st.cache_data(ttl=300, show_spinner=False)
def _scan(symbols: tuple[str, ...]) -> pd.DataFrame:
    hist = screener.batch_history(list(symbols), period="1y", min_rows=20)
    rows = []
    for s in symbols:
        df = hist.get(s)
        if df is None or len(df) < 2:
            rows.append({"Symbol": s, "ok": False})
            continue
        close = df["Close"]
        last, prev = float(close.iloc[-1]), float(close.iloc[-2])
        row = {
            "Symbol": s, "ok": True, "Price": last, "Day %": (last / prev - 1) * 100,
            "1M %": (last / float(close.iloc[-22]) - 1) * 100 if len(close) > 22 else None,
            "3M %": (last / float(close.iloc[-64]) - 1) * 100 if len(close) > 64 else None,
            "52W pos %": (last - float(close.min())) / max(float(close.max() - close.min()), 1e-9) * 100,
            "Score": None, "RSI": None, "Trend": "—",
        }
        if len(df) >= 60:
            try:
                r = _tech.analyze(df)
                row["Score"], row["RSI"] = r.score, r.indicators.get("rsi")
                row["Trend"] = r.label
            except Exception:  # noqa: BLE001
                pass
        rows.append(row)
    return pd.DataFrame(rows)


ui.hero(
    "My Watchlist",
    "Track your own stocks in one place. The list lives in the page URL, so bookmark this page "
    "to keep it; edit symbols in the left rail.",
    pills=[("Delayed data", "amber"), ("Technical score only", "flat")],
)

if not syms:
    ui.empty_note("<b>Your watchlist is empty.</b> Add symbols in the left rail, e.g. RELIANCE, AAPL.")
    ui.footer()
    st.stop()

with st.spinner("Fetching quotes…"):
    df = _scan(tuple(syms))

ok = df[df["ok"]].copy()
missing = df[~df["ok"]]["Symbol"].tolist()
if ok.empty:
    ui.empty_note("<b>No quotes returned.</b> Check the symbols or try Refresh in a minute.")
    ui.footer()
    st.stop()

best = ok.loc[ok["Day %"].idxmax()]
worst = ok.loc[ok["Day %"].idxmin()]
k = st.columns(4)
T.kpi(k[0], "Tracked", f"{len(ok)}", f"of {len(syms)} symbols", "flat")
T.kpi(k[1], "Avg day move", f"{ok['Day %'].mean():+.2f}%", "equal-weighted", T.sign_tone(ok["Day %"].mean()))
T.kpi(k[2], "Best today", ui.short_sym(best["Symbol"]), f"{best['Day %']:+.2f}%", "up")
T.kpi(k[3], "Worst today", ui.short_sym(worst["Symbol"]), f"{worst['Day %']:+.2f}%", "down")
st.markdown("<div style='height:.8rem'></div>", unsafe_allow_html=True)

rows = []
for _, r in ok.sort_values("Day %", ascending=False).iterrows():
    cur = "₹" if r["Symbol"].endswith((".NS", ".BO")) else "$"
    sc = r["Score"]
    sc_html = "—"
    if ui._ok(sc):
        sc_html = f'<span style="color:{T.tone_color(T.sign_tone(sc))};font-weight:700">{float(sc):+.0f}</span>'

    def _c(v):
        return f'<span style="color:{T.tone_color(T.sign_tone(v))}">{ui._pct(v, 1)}</span>' if ui._ok(v) else "—"

    rsi_txt = f"{r['RSI']:.0f}" if ui._ok(r["RSI"]) else "—"
    rows.append(
        f'<tr><td><b>{ui._e(ui.short_sym(r["Symbol"]))}</b></td><td>{cur}{ui._px(r["Price"])}</td>'
        f'<td class="chg">{_c(r["Day %"])}</td><td>{_c(r["1M %"])}</td><td>{_c(r["3M %"])}</td>'
        f'<td>{rsi_txt}</td><td>{sc_html}</td>'
        f'<td class="dim">{ui._e(r["Trend"])}</td><td>{ui._px(r["52W pos %"], 0)}%</td></tr>'
    )
st.markdown(
    '<div class="ttw"><table class="tt"><thead><tr><th>Symbol</th><th>Price</th><th>Day</th><th>1M</th>'
    '<th>3M</th><th>RSI</th><th>Score</th><th>Trend</th><th>52W range</th></tr></thead><tbody>'
    + "".join(rows) + "</tbody></table></div>",
    unsafe_allow_html=True,
)
if missing:
    st.caption("No data for: " + ", ".join(ui.short_sym(m) for m in missing)
               + ". Check spelling or add .NS / .BO for Indian stocks.")
st.caption("Score = technical-only (trend, RSI, MACD, volume), −100…+100. Open the Analyze page for the full "
           "fundamental and news blend. 52W range: 0% = at the 52-week low, 100% = at the high.")
ui.footer()
