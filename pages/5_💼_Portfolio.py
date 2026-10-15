"""Portfolio: P&L, FIFO lots, realised gains and Indian tax estimate, risk (correlation, beta, VaR) and position sizing."""

import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import cache, portfolio as PF, screener, sectors, technical as _tech, theme as T, ui, universe  # noqa: E402

ui.setup("Portfolio", "💼")
C = T.C

DEFAULT = "BUY RELIANCE 10 2400 2024-03-04\nBUY TCS 5 3300 2025-02-10\nSELL TCS 2 4100 2026-06-15\nBUY AAPL 8 180 2025-01-20\nNVDA 4 110"

ui.sidebar_brand()
T.sidebar_head("Transactions")
saved = st.query_params.get("p", "").replace(";", "\n") or DEFAULT
raw = st.sidebar.text_area("One per line", value=saved, height=190,
                           help="BUY RELIANCE 10 2400 2024-03-04 · SELL RELIANCE 4 2900 2025-08-11 · or the short form "
                                "RELIANCE 10 2400 (an undated buy). Dates enable realised P&L and tax. "
                                "Indian large-caps get .NS automatically.")
unknown_as = st.sidebar.radio("Unknown symbols are", ["US", "India (NSE)"], horizontal=True)
T.sidebar_head("Alerts")
a_loss = st.sidebar.slider("Flag if down more than (%) from cost", 5, 50, 15)
a_rsi = st.sidebar.slider("Flag RSI above", 60, 90, 75)
T.sidebar_head("Tax (India, editable)")
t_st = st.sidebar.number_input("STCG rate %", 0.0, 40.0, 20.0, 0.5)
t_lt = st.sidebar.number_input("LTCG rate %", 0.0, 40.0, 12.5, 0.5)
t_ex = st.sidebar.number_input("LTCG yearly exemption ₹", 0.0, 1_000_000.0, 125_000.0, 5_000.0)
fy0 = PF.current_fy_start()
fy_pick = st.sidebar.selectbox("Financial year", [fy0, fy0 - 1, fy0 - 2], format_func=lambda y: f"FY {y}-{str(y + 1)[2:]}")
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


txns, bad_lines = PF.parse_transactions(raw, _resolve)
open_lots, realised, warns = PF.fifo(txns)
holdings = PF.positions(open_lots)
try:
    st.query_params["p"] = ";".join(l.strip() for l in raw.splitlines() if l.strip())
except Exception:  # noqa: BLE001
    pass


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _closes(symbols: tuple[str, ...], b: int) -> tuple[pd.DataFrame, dict]:
    hist = screener.batch_history(list(symbols) + ["^NSEI", "^GSPC"], period="2y", min_rows=20)
    closes = pd.DataFrame({s: d["Close"] for s, d in hist.items()}).sort_index()
    rsi = {}
    for s in symbols:
        d = hist.get(s)
        if d is not None and len(d) >= 60:
            try:
                rsi[s] = _tech.analyze(d).indicators
            except Exception:  # noqa: BLE001
                pass
    return closes, rsi


ui.hero(
    "My Portfolio",
    "Value, profit and loss by lot, realised gains with an Indian tax estimate, risk (correlation, beta, value-at-risk) "
    "and position sizing. Indian and US holdings are totalled separately (no currency conversion). The list is stored "
    "in the page URL, so bookmark it.",
    pills=[("Delayed data", "amber"), ("Not advice · not tax advice", "flat")],
)

if bad_lines:
    st.warning("Could not read: " + " | ".join(bad_lines))
for w_ in warns:
    st.warning(w_)
if not txns:
    ui.empty_note("<b>No transactions yet.</b> Add lines like <b>BUY RELIANCE 10 2400 2024-03-04</b> in the left rail.")
    ui.footer()
    st.stop()

with st.spinner("Fetching prices…"):
    closes, inds = _closes(tuple(sorted(set(holdings) | {r.symbol for r in realised})), cache.bucket("IN", 2))

if not holdings and not realised:
    ui.empty_note("<b>Nothing to show.</b> Every position was sold or no valid lines were found.")
    ui.footer()
    st.stop()

smap = {**sectors.sector_map("IN"), **sectors.sector_map("US")}
rows = []
prices: dict[str, float] = {}
for sym, (q, c) in holdings.items():
    if sym not in closes or closes[sym].dropna().shape[0] < 2:
        continue
    cl = closes[sym].dropna()
    price, prev = float(cl.iloc[-1]), float(cl.iloc[-2])
    prices[sym] = price
    cur = "INR" if PF.is_indian(sym) else "USD"
    val, inv = q * price, q * c
    rows.append({"Symbol": sym, "Cur": cur, "Qty": q, "Avg cost": c, "Price": price, "Invested": inv, "Value": val,
                 "P&L": val - inv, "P&L %": (val / inv - 1) * 100, "Day %": (price / prev - 1) * 100,
                 "Day P&L": q * (price - prev), "RSI": (inds.get(sym) or {}).get("rsi"), "Sector": smap.get(sym, "Other")})
pf = pd.DataFrame(rows)
missing = [s for s in holdings if s not in prices]
SYM = {"INR": "₹", "USD": "$"}

tab_pos, tab_risk, tab_tax, tab_size = st.tabs(["POSITIONS", "RISK", "REALISED P&L · TAX", "POSITION SIZING"])

# =============================================================== positions
with tab_pos:
    if pf.empty:
        ui.empty_note("<b>No prices returned for open positions.</b> Try Refresh in a minute.")
    else:
        for cur in ("INR", "USD"):
            sub = pf[pf["Cur"] == cur]
            if sub.empty:
                continue
            inv, val, dayp = sub["Invested"].sum(), sub["Value"].sum(), sub["Day P&L"].sum()
            real = sum(x.pnl for x in realised if (PF.is_indian(x.symbol)) == (cur == "INR"))
            k = st.columns(5)
            s = SYM[cur]
            T.kpi(k[0], f"{cur} value", f"{s}{val:,.0f}", f"invested {s}{inv:,.0f}", "flat")
            T.kpi(k[1], "Unrealised P&L", f"{s}{val - inv:+,.0f}", f"{(val / inv - 1) * 100:+.2f}%", T.sign_tone(val - inv))
            T.kpi(k[2], "Realised P&L", f"{s}{real:+,.0f}", "all sold lots", T.sign_tone(real))
            T.kpi(k[3], "Today", f"{s}{dayp:+,.0f}", f"{dayp / max(val - dayp, 1e-9) * 100:+.2f}%", T.sign_tone(dayp))
            T.kpi(k[4], "Holdings", f"{len(sub)}", "open positions", "flat")
            st.markdown("<div style='height:.6rem'></div>", unsafe_allow_html=True)

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
        for n_ in PF.lots_turning_long_term(open_lots, prices, 45):
            flags.append(("amber", f"{ui.short_sym(n_['Symbol'])}: {n_['Qty']:g} shares turn long-term in {n_['Days to long-term']} days "
                                   f"(unrealised gain ₹{n_['Unrealised gain']:,.0f}); selling earlier is taxed at the higher short-term rate"))
        if flags:
            T.rule("Alerts")
            st.markdown("".join(f'<div style="margin:.25rem 0">{T.pill("FLAG", t)} &nbsp;{ui._e(m)}</div>' for t, m in flags),
                        unsafe_allow_html=True)
        else:
            T.note("<b>No alerts.</b> No position is past your loss or RSI limits, and none dominates the portfolio.")

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

        with st.expander("Open lots (FIFO)"):
            lots = pd.DataFrame([{"Symbol": l.symbol, "Qty": l.qty, "Cost": l.cost, "Bought": l.date,
                                  "Days held": (pd.Timestamp.today().date() - l.date).days if l.date else None} for l in open_lots])
            st.dataframe(lots, use_container_width=True, hide_index=True)

# =============================================================== risk
with tab_risk:
    st.caption("Risk is computed per currency block because INR and USD values are not converted. Beta is against the "
               "Nifty 50 for Indian holdings and the S&P 500 for US ones, using up to 2 years of daily returns.")
    for cur, bench in (("INR", "^NSEI"), ("USD", "^GSPC")):
        sub = pf[pf["Cur"] == cur] if not pf.empty else pd.DataFrame()
        if sub.empty:
            continue
        T.rule(f"{cur} holdings")
        syms = [s for s in sub["Symbol"] if s in closes]
        wts = {r["Symbol"]: r["Value"] for _, r in sub.iterrows() if r["Symbol"] in closes}
        total = sum(wts.values())
        port = PF.portfolio_returns(closes, wts)
        stats = PF.var_cvar(port, 0.95, 1)
        stats10 = PF.var_cvar(port, 0.95, 10)
        bret = closes[bench].pct_change() if bench in closes else pd.Series(dtype=float)
        pbeta = PF.beta(port, bret) if len(bret) else None
        shares = pd.Series(wts) / total
        k = st.columns(5)
        T.kpi(k[0], "1-day VaR (95%)", f"{SYM[cur]}{stats.get('hist_var', 0) * total:,.0f}" if stats else "—",
              f"{stats.get('hist_var', 0) * 100:.2f}% of value · historical" if stats else "need 60+ days", "down")
        T.kpi(k[1], "10-day VaR (95%)", f"{SYM[cur]}{stats10.get('hist_var', 0) * total:,.0f}" if stats10 else "—", "√time scaling", "down")
        T.kpi(k[2], "Expected shortfall", f"{SYM[cur]}{stats.get('cvar', 0) * total:,.0f}" if stats else "—", "avg loss on the worst 5% days", "down")
        T.kpi(k[3], "Portfolio beta", f"{pbeta:.2f}" if pbeta is not None else "—", "vs " + ("Nifty 50" if cur == "INR" else "S&P 500"), "amber")
        eff_n = 1 / PF.hhi(shares) if len(shares) else 0
        T.kpi(k[4], "Effective holdings", f"{eff_n:.1f}", f"of {len(shares)} (1 = all in one stock)", "flat")
        st.markdown("<div style='height:.6rem'></div>", unsafe_allow_html=True)

        c1, c2 = st.columns(2)
        with c1:
            corr = PF.correlation(closes[syms])
            if corr.empty:
                st.info("Need at least two holdings with 60+ days of prices for a correlation matrix.")
            else:
                corr.index = [ui.short_sym(s) for s in corr.index]
                corr.columns = [ui.short_sym(s) for s in corr.columns]
                fig = px.imshow(corr, zmin=-1, zmax=1, text_auto=".2f", aspect="auto",
                                color_continuous_scale=[(0, C["blue"]), (0.5, "#1B1E24"), (1, C["down"])])
                fig.update_layout(height=340, margin=dict(l=8, r=8, t=28, b=8), coloraxis_showscale=False,
                                  title=dict(text="Correlation of daily returns (red = move together)", font=dict(size=12, color=C["dim"])))
                st.plotly_chart(fig, use_container_width=True)
        with c2:
            rc = PF.risk_contributions(closes, wts)
            if rc.empty:
                st.info("Not enough history for risk contributions.")
            else:
                fig = go.Figure(go.Bar(x=rc.values * 100, y=[ui.short_sym(s) for s in rc.index], orientation="h",
                                       marker_color=C["amber"], hovertemplate="%{y}: %{x:.0f}% of risk<extra></extra>"))
                fig.update_layout(height=340, margin=dict(l=8, r=8, t=28, b=8), yaxis=dict(autorange="reversed"),
                                  title=dict(text="Share of portfolio risk (variance) by holding", font=dict(size=12, color=C["dim"])))
                st.plotly_chart(T.style_axes(fig), use_container_width=True)
        bt = []
        for s in syms:
            b_ = PF.beta(closes[s].pct_change(), bret) if len(bret) else None
            bt.append(f"{ui.short_sym(s)} {b_:.2f}" if b_ is not None else f"{ui.short_sym(s)} —")
        st.caption("Beta by holding: " + " · ".join(bt))
        sc = PF.sector_concentration(wts, smap)
        if len(sc):
            warn = [f"{k_} {v * 100:.0f}%" for k_, v in sc.items() if v >= 0.40]
            if warn:
                st.warning("Sector concentration: " + ", ".join(warn) + " of this block sits in one sector.")
    st.caption("VaR here is historical simulation: the 1-day loss that was exceeded on 5% of past days. It is not a "
               "worst case; real losses can be larger, especially in crashes.")

# =============================================================== tax
with tab_tax:
    rates = PF.IndiaTax(stcg_rate=t_st / 100, ltcg_rate=t_lt / 100, ltcg_exempt=t_ex)
    ts = PF.tax_summary(realised, fy_pick, rates)
    if not realised:
        ui.empty_note("<b>No sales recorded.</b> Add lines like <b>SELL TCS 2 4100 2026-06-15</b> to see realised P&amp;L and a tax estimate.")
    else:
        k = st.columns(4)
        T.kpi(k[0], ts.fy + " short-term", f"₹{ts.stcg:+,.0f}", f"taxed at {t_st:g}%", T.sign_tone(ts.stcg))
        T.kpi(k[1], "Long-term", f"₹{ts.ltcg:+,.0f}", f"₹{ts.ltcg_taxable:,.0f} taxable after exemption", T.sign_tone(ts.ltcg))
        T.kpi(k[2], "Estimated tax", f"₹{ts.tax:,.0f}", "incl. 4% cess, no surcharge", "amber")
        T.kpi(k[3], "Foreign (US) gains", f"${ts.foreign_gain:+,.0f}", "not taxed here", "flat")
        st.markdown("<div style='height:.6rem'></div>", unsafe_allow_html=True)
        if ts.rows:
            df = pd.DataFrame(ts.rows)
            st.dataframe(df.style.format({"Qty": "{:g}", "P&L": "{:+,.0f}"}), use_container_width=True, hide_index=True)
        else:
            st.info(f"No sales dated inside {ts.fy}.")
        if ts.undated:
            st.warning(f"{ts.undated} sale(s) skipped because a buy or sell date is missing.")
        st.download_button("Download realised trades (CSV)", pd.DataFrame(ts.rows).to_csv(index=False).encode() if ts.rows else b"",
                           "realised_trades.csv", "text/csv", disabled=not ts.rows)
    st.caption("Estimate for Indian-listed equity with STT paid, using the rates in the sidebar (defaults: 20% short-term, "
               "12.5% long-term above ₹1.25 lakh, long-term = held more than 12 months, 4% cess). It ignores surcharge, "
               "brokerage, loss carry-forward from earlier years, bonus/split adjustments and grandfathering. Foreign shares "
               "follow different rules (slab rate, 24-month long-term). This is not tax advice: check with a CA.")

# =============================================================== sizing
with tab_size:
    st.caption("How many shares can you buy so that hitting your stop loses only a set % of capital?")
    c = st.columns(4)
    cap = c[0].number_input("Capital", 1000.0, 1e9, 500_000.0, 10_000.0)
    risk = c[1].number_input("Risk per trade %", 0.1, 10.0, 1.0, 0.25)
    mult = c[2].number_input("Stop = ATR ×", 0.5, 6.0, 2.0, 0.5)
    maxp = c[3].number_input("Max position % of capital", 5.0, 100.0, 25.0, 5.0)
    s1, s2 = st.columns([2, 1])
    default_sym = ui.short_sym(pf.iloc[0]["Symbol"]) if not pf.empty else "RELIANCE"
    sym_in = s1.text_input("Symbol", value=default_sym)
    side = s2.radio("Side", ["LONG", "SHORT"], horizontal=True)
    if sym_in:
        tsym = _resolve(sym_in)
        try:
            cl, ind = _closes((tsym,), cache.bucket("IN", 2))
            d = cl[tsym].dropna()
            atr = (ind.get(tsym) or {}).get("atr")
            entry = st.number_input("Entry price", 0.01, 1e9, float(d.iloc[-1]) if len(d) else 100.0)
            if atr is None:
                atr = st.number_input("ATR (could not compute)", 0.01, 1e9, entry * 0.02)
            z = PF.position_size(cap, risk, entry, float(atr), mult, maxp, side)
            if z is None or z.qty == 0:
                st.info("Stop distance or capital leaves no whole share. Lower the ATR multiple or raise capital.")
            else:
                cur_s = "₹" if PF.is_indian(tsym) else "$"
                k = st.columns(5)
                T.kpi(k[0], "Buy quantity", f"{z.qty:,}", "shares", "up")
                T.kpi(k[1], "Position value", f"{cur_s}{z.position_value:,.0f}", f"{z.pct_of_capital:.1f}% of capital", "flat")
                T.kpi(k[2], "Stop loss", f"{cur_s}{z.stop:,.2f}", f"{mult:g}× ATR ({atr:,.2f})", "down")
                T.kpi(k[3], "Risk if stopped", f"{cur_s}{z.risk_amount:,.0f}", f"{z.risk_amount / cap * 100:.2f}% of capital", "amber")
                T.kpi(k[4], "Reward at 2R", f"{cur_s}{z.qty * z.risk_per_share * 2:,.0f}", f"target {cur_s}{entry + 2 * z.risk_per_share * (1 if side == 'LONG' else -1):,.2f}", "up")
                if z.capped:
                    st.warning(f"Capped by the {maxp:g}% max-position rule: the risk budget would allow more shares.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Could not size {sym_in}: {exc}")
    st.caption("ATR-based sizing is a risk-management tool, not a signal. Gaps, slippage and illiquid stocks can make real "
               "losses exceed the planned stop.")
ui.footer()
