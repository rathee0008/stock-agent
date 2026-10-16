"""Compare two stocks side by side: scores, valuation, returns, risk and a rebased price chart."""

import sys
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import cache, theme as T, ui, universe  # noqa: E402
from agent.analyze import analyze_stock  # noqa: E402

ui.setup("Compare", "⚖️")
C = T.C
IN_SET = set(universe.IN)

ui.sidebar_brand()
T.sidebar_head("Stocks")
_cmp = st.session_state.pop("cmp", None)  # two symbols sent from the Top 20 page
a_raw = st.sidebar.text_input("First symbol", value=_cmp[0] if _cmp else st.query_params.get("a", "TCS")).strip().upper()
b_raw = st.sidebar.text_input("Second symbol", value=_cmp[1] if _cmp else st.query_params.get("b", "INFY")).strip().upper()
unknown_as = st.sidebar.radio("Unknown symbols are", ["US", "India (NSE)"], horizontal=True)
T.sidebar_head("Blend weights")
w = (st.sidebar.slider("Technical", 0.0, 1.0, 0.45, 0.05), st.sidebar.slider("Fundamental", 0.0, 1.0, 0.40, 0.05),
     st.sidebar.slider("News", 0.0, 1.0, 0.15, 0.05))
if st.sidebar.button("Refresh", use_container_width=True):
    st.cache_data.clear()


def _mk(tok: str) -> tuple[str, str]:
    if tok.endswith((".NS", ".BO")) or tok in IN_SET or (unknown_as.startswith("India") and "." not in tok):
        return tok, "IN"
    return tok, "US"


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _a(sym: str, mkt: str, weights: tuple, b: int):
    return analyze_stock(sym, weights={"technical": weights[0], "fundamental": weights[1], "news": weights[2]},
                         period="2y", market=mkt)


ui.hero("Compare stocks", "Two stocks, one screen: composite call, scores, valuation, returns, volatility and how closely "
        "they move together.", pills=[("Delayed data", "amber"), ("Not advice", "flat")])
if not a_raw or not b_raw:
    ui.empty_note("<b>Enter two symbols</b> in the left rail.")
    ui.footer()
    st.stop()
try:
    st.query_params["a"], st.query_params["b"] = a_raw, b_raw
except Exception:  # noqa: BLE001
    pass

res = {}
with st.spinner("Analysing both…"):
    for raw in (a_raw, b_raw):
        sym, mkt = _mk(raw)
        try:
            res[raw] = _a(sym, mkt, w, cache.bucket(mkt))
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not analyse {raw}: {exc}")
if len(res) < 2:
    ui.footer()
    st.stop()

A, B = res[a_raw], res[b_raw]


def _ret(a: dict, days: int):
    c = a["history"]["Close"].dropna()
    return (float(c.iloc[-1]) / float(c.iloc[-1 - days]) - 1) * 100 if len(c) > days else None


def _f(v, fmt="{:.1f}"):
    return fmt.format(v) if v is not None and pd.notna(v) else "—"


def _row(label, fa, fb, higher_better=None, fmt="{:.1f}"):
    """(label, a, b, winner) — winner is 'a'/'b'/None."""
    win = None
    if higher_better is not None and fa is not None and fb is not None and pd.notna(fa) and pd.notna(fb) and fa != fb:
        win = "a" if (fa > fb) == higher_better else "b"
    return label, _f(fa, fmt), _f(fb, fmt), win


mA, mB = A["fundamental"]["metrics"], B["fundamental"]["metrics"]
iA, iB = A["technical"]["indicators"], B["technical"]["indicators"]
pos = lambda a, i: ((a["price"] - i["week52_low"]) / max(i["week52_high"] - i["week52_low"], 1e-9) * 100  # noqa: E731
                    if i.get("week52_high") and i.get("week52_low") else None)
rows = [
    _row("Composite score", A["signal"]["score"], B["signal"]["score"], True, "{:+.0f}"),
    _row("Technical score", A["technical"]["score"], B["technical"]["score"], True, "{:+.0f}"),
    _row("Fundamental score", A["fundamental"]["score"], B["fundamental"]["score"], True, "{:+.0f}"),
    _row("News tone", A["news"]["score"], B["news"]["score"], True, "{:+.0f}"),
    _row("P/E (lower is cheaper)", mA.get("pe"), mB.get("pe"), False),
    _row("P/B", mA.get("pb"), mB.get("pb"), False),
    _row("ROE %", (mA.get("roe") or 0) * 100 if mA.get("roe") is not None else None,
         (mB.get("roe") or 0) * 100 if mB.get("roe") is not None else None, True),
    _row("Net margin %", (mA.get("profit_margin") or 0) * 100 if mA.get("profit_margin") is not None else None,
         (mB.get("profit_margin") or 0) * 100 if mB.get("profit_margin") is not None else None, True),
    _row("Debt / equity (lower is safer)", mA.get("debt_to_equity"), mB.get("debt_to_equity"), False, "{:.2f}"),
    _row("Revenue growth %", (mA.get("revenue_growth") or 0) * 100 if mA.get("revenue_growth") is not None else None,
         (mB.get("revenue_growth") or 0) * 100 if mB.get("revenue_growth") is not None else None, True),
    _row("1-month return %", _ret(A, 21), _ret(B, 21), True),
    _row("3-month return %", _ret(A, 63), _ret(B, 63), True),
    _row("1-year return %", _ret(A, 252), _ret(B, 252), True),
    _row("RSI", iA.get("rsi"), iB.get("rsi"), None, "{:.0f}"),
    _row("Volatility: ATR % of price (lower is calmer)", iA.get("atr_pct"), iB.get("atr_pct"), False, "{:.2f}"),
    _row("Position in 52-week range %", pos(A, iA), pos(B, iB), None, "{:.0f}"),
]
wa = sum(1 for r in rows if r[3] == "a")
wb = sum(1 for r in rows if r[3] == "b")

c1, c2, c3 = st.columns([1, 1, 1])
for col, a in ((c1, A), (c2, B)):
    T.kpi(col, a["name"][:28], a["signal"]["label"].upper(),
          f"{a['ticker']} · {a['currency']} {a['price']:,.2f} ({a['day_change_pct']:+.2f}%) · confidence {a['signal']['confidence_pct']}%",
          T.sign_tone(a["signal"]["score"]), small=True)
ca = pd.concat([A["history"]["Close"].pct_change(), B["history"]["Close"].pct_change()], axis=1, join="inner").dropna().tail(252)
corr = float(ca.iloc[:, 0].corr(ca.iloc[:, 1])) if len(ca) > 60 else None
T.kpi(c3, "Correlation (1y)", _f(corr, "{:.2f}"), "1 = move together, 0 = independent",
      "amber" if corr is not None and corr > 0.7 else "flat")
st.markdown("<div style='height:.7rem'></div>", unsafe_allow_html=True)

# rebased chart
fig = go.Figure()
common = pd.concat([A["history"]["Close"].rename("a"), B["history"]["Close"].rename("b")], axis=1, join="inner").dropna()
if len(common) > 5:
    for key, nm, col in (("a", a_raw, C["amber"]), ("b", b_raw, C["blue"])):
        fig.add_trace(go.Scatter(x=common.index, y=common[key] / common[key].iloc[0] * 100, name=nm,
                                 line=dict(color=col, width=2)))
    fig.update_layout(height=360, margin=dict(l=8, r=8, t=8, b=8), yaxis_title="Rebased to 100",
                      yaxis_title_font=dict(size=10, color=C["faint"]), legend=dict(orientation="h", y=1.08, x=0))
    st.plotly_chart(T.style_axes(fig), use_container_width=True)
if A["currency"] != B["currency"]:
    st.caption("The two stocks trade in different currencies; the chart is rebased, so only the % path is comparable.")

trs = []
for label, fa, fb, win in rows:
    ga = f' style="color:{C["up"]};font-weight:700"' if win == "a" else ""
    gb = f' style="color:{C["up"]};font-weight:700"' if win == "b" else ""
    trs.append(f"<tr><td>{ui._e(label)}</td><td{ga}>{fa}</td><td{gb}>{fb}</td></tr>")
st.markdown(f'<div class="ttw"><table class="tt"><thead><tr><th>Metric</th><th>{ui._e(a_raw)}</th><th>{ui._e(b_raw)}</th></tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table></div>', unsafe_allow_html=True)
st.caption(f"Green = better on that metric. Tally: {a_raw} {wa} · {b_raw} {wb}. A tally is not a verdict: "
           "check that the stocks are comparable (sector, size, growth stage) before reading anything into it.")

for a in (A, B):
    if a["signal"].get("conflict_note"):
        st.warning(f"{a['ticker']}: {a['signal']['conflict_note']}")
with st.expander("Top drivers behind each call"):
    d1, d2 = st.columns(2)
    for col, a in ((d1, A), (d2, B)):
        with col:
            st.markdown(f"**{a['ticker']}**")
            ui.drivers_panel(a["signal"].get("drivers", []), top=6)
ui.footer()
