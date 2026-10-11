"""Portfolio tracker: P&L, allocation and alert flags for your own holdings."""

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import screener, sectors, technical as _tech, theme as T, ui, universe  # noqa: E402

ui.setup("Portfolio", "💼")
C = T.C

DEFAULT = "RELIANCE 10 2400\nTCS 5 3300\nAAPL 8 180\nNVDA 4 110"

ui.sidebar_brand()
T.sidebar_head("Holdings")
saved = st.query_params.get("p", "").replace(";", "\n") or DEFAULT
raw = st.sidebar.text_area("One per line: SYMBOL quantity average-cost", value=saved, height=170,
                           help="Example: RELIANCE 10 2400. Indian large-caps get .NS automatically; "
                                "use SYMBOL.BO for BSE. Costs are in the stock's own currency.")
unknown_as = st.sidebar.radio("Unknown symbols are", ["US", "India (NSE)"], horizontal=True)
T.sidebar_head("Alerts")
a_loss = st.sidebar.slider("Flag if down more than (%) from cost", 5, 50, 15)
a_rsi = st.sidebar.slider("Flag RSI above", 60, 90, 75)
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


holdings: dict[str, tuple[float, float]] = {}
bad_lines: list[str] = []
for line in raw.splitlines():
    parts = line.replace(",", " ").split()
    if not parts:
        continue
    try:
        sym, qty, cost = _resolve(parts[0]), float(parts[1]), float(parts[2])
        if qty <= 0 or cost <= 0:
            raise ValueError
        q0, c0 = holdings.get(sym, (0.0, 0.0))
        holdings[sym] = (q0 + qty, (q0 * c0 + qty * cost) / (q0 + qty))
    except (IndexError, ValueError):
        bad_lines.append(line.strip())
try:
    st.query_params["p"] = ";".join(
        f"{s.replace('.NS', '')} {q:g} {c:g}" for s, (q, c) in holdings.items())
except Exception:  # noqa: BLE001
    pass


@st.cache_data(ttl=300, show_spinner=False)
def _prices(symbols: tuple[str, ...]) -> pd.DataFrame:
    hist = screener.batch_history(list(symbols), period="1y", min_rows=20)
    rows = []
    for s in symbols:
        df = hist.get(s)
        if df is None or len(df) < 2:
            continue
        c = df["Close"].dropna()
        rsi = None
        if len(df) >= 60:
            try:
                rsi = _tech.analyze(df).indicators.get("rsi")
            except Exception:  # noqa: BLE001
                pass
        rows.append({"Symbol": s, "Price": float(c.iloc[-1]), "Prev": float(c.iloc[-2]), "RSI": rsi})
    return pd.DataFrame(rows)


ui.hero(
    "My Portfolio",
    "Enter what you hold and see value, profit and loss, allocation and risk flags. Indian and US holdings are "
    "totalled separately (no currency conversion). The list is stored in the page URL, so bookmark it.",
    pills=[("Delayed data", "amber"), ("Not advice", "flat")],
)

if bad_lines:
    st.warning("Could not read: " + " | ".join(bad_lines) + ". Use the format SYMBOL quantity cost.")
if not holdings:
    ui.empty_note("<b>No holdings yet.</b> Add lines like <b>RELIANCE 10 2400</b> in the left rail.")
    ui.footer()
    st.stop()

with st.spinner("Fetching prices…"):
    px_df = _prices(tuple(holdings))

if px_df.empty:
    ui.empty_note("<b>No prices returned.</b> Check the symbols or try Refresh in a minute.")
    ui.footer()
    st.stop()

smap = {**sectors.sector_map("IN"), **sectors.sector_map("US")}
rows = []
for _, r in px_df.iterrows():
    q, c = holdings[r["Symbol"]]
    cur = "INR" if r["Symbol"].endswith((".NS", ".BO")) else "USD"
    val, inv = q * r["Price"], q * c
    rows.append({
        "Symbol": r["Symbol"], "Cur": cur, "Qty": q, "Avg cost": c, "Price": r["Price"],
        "Invested": inv, "Value": val, "P&L": val - inv, "P&L %": (val / inv - 1) * 100,
        "Day %": (r["Price"] / r["Prev"] - 1) * 100, "Day P&L": q * (r["Price"] - r["Prev"]),
        "RSI": r["RSI"], "Sector": smap.get(r["Symbol"], "Other"),
    })
pf = pd.DataFrame(rows)
missing = [s for s in holdings if s not in set(pf["Symbol"])]

SYM = {"INR": "₹", "USD": "$"}
for cur in ("INR", "USD"):
    sub = pf[pf["Cur"] == cur]
    if sub.empty:
        continue
    inv, val, dayp = sub["Invested"].sum(), sub["Value"].sum(), sub["Day P&L"].sum()
    k = st.columns(4)
    s = SYM[cur]
    T.kpi(k[0], f"{cur} value", f"{s}{val:,.0f}", f"invested {s}{inv:,.0f}", "flat")
    T.kpi(k[1], "Total P&L", f"{s}{val - inv:+,.0f}", f"{(val / inv - 1) * 100:+.2f}%", T.sign_tone(val - inv))
    T.kpi(k[2], "Today", f"{s}{dayp:+,.0f}", f"{dayp / max(val - dayp, 1e-9) * 100:+.2f}%", T.sign_tone(dayp))
    T.kpi(k[3], "Holdings", f"{len(sub)}", "positions", "flat")
    st.markdown("<div style='height:.6rem'></div>", unsafe_allow_html=True)

# ---------------------------------------------------------------- alerts
flags = []
for _, r in pf.iterrows():
    n = ui.short_sym(r["Symbol"])
    if r["P&L %"] <= -a_loss:
        flags.append(("down", f"{n} is {r['P&L %']:.1f}% below your cost"))
    if ui._ok(r["RSI"]) and r["RSI"] >= a_rsi:
        flags.append(("amber", f"{n} RSI is {r['RSI']:.0f} (overbought)"))
for cur in ("INR", "USD"):
    sub = pf[pf["Cur"] == cur]
    if len(sub) > 1:
        top = sub.loc[sub["Value"].idxmax()]
        share = top["Value"] / sub["Value"].sum() * 100
        if share >= 40:
            flags.append(("amber", f"{ui.short_sym(top['Symbol'])} is {share:.0f}% of your {cur} portfolio (concentration)"))
if flags:
    T.rule("Alerts")
    st.markdown("".join(f'<div style="margin:.25rem 0">{T.pill("FLAG", t)} &nbsp;{ui._e(m)}</div>' for t, m in flags),
                unsafe_allow_html=True)
else:
    T.note("<b>No alerts.</b> No position is past your loss or RSI limits, and none dominates the portfolio.")

# ---------------------------------------------------------------- table
T.rule("Positions")
trs = []
for _, r in pf.sort_values("Value", ascending=False).iterrows():
    s = SYM[r["Cur"]]
    pc = T.tone_color(T.sign_tone(r["P&L"]))
    dc = T.tone_color(T.sign_tone(r["Day %"]))
    rsi_txt = f"{r['RSI']:.0f}" if ui._ok(r["RSI"]) else "—"
    trs.append(
        f'<tr><td><b>{ui._e(ui.short_sym(r["Symbol"]))}</b></td><td>{r["Qty"]:g}</td>'
        f'<td>{s}{r["Avg cost"]:,.2f}</td><td>{s}{r["Price"]:,.2f}</td><td>{s}{r["Value"]:,.0f}</td>'
        f'<td style="color:{pc};font-weight:700">{s}{r["P&L"]:+,.0f} ({r["P&L %"]:+.1f}%)</td>'
        f'<td style="color:{dc}">{r["Day %"]:+.2f}%</td><td>{rsi_txt}</td></tr>'
    )
st.markdown(
    '<div class="ttw"><table class="tt"><thead><tr><th>Symbol</th><th>Qty</th><th>Avg cost</th><th>Price</th>'
    "<th>Value</th><th>P&amp;L</th><th>Day</th><th>RSI</th></tr></thead><tbody>"
    + "".join(trs) + "</tbody></table></div>",
    unsafe_allow_html=True,
)
if missing:
    st.caption("No price for: " + ", ".join(ui.short_sym(m) for m in missing))

# ---------------------------------------------------------------- allocation
T.rule("Allocation")
cols = st.columns(2)
for col, cur in zip(cols, ("INR", "USD")):
    sub = pf[pf["Cur"] == cur]
    if sub.empty:
        continue
    with col:
        by = sub.groupby("Sector")["Value"].sum().sort_values(ascending=False)
        fig = go.Figure(go.Pie(labels=by.index, values=by.values, hole=0.58, textinfo="label+percent",
                               marker=dict(line=dict(color="#0A0B0D", width=2))))
        fig.update_layout(height=340, margin=dict(l=8, r=8, t=28, b=8), showlegend=False,
                          title=dict(text=f"{cur} by sector", font=dict(size=12, color=C["dim"])))
        st.plotly_chart(fig, use_container_width=True)
st.caption("Not investment advice. Alerts are shown on this page only; no emails or push messages are sent.")
ui.footer()
