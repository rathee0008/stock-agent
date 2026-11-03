"""Sector heatmap: which parts of the India and US large-cap universes are moving today."""

import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import cache, flows, heatmetrics as H, liveheat, screener, sectors, theme as T, ui  # noqa: E402

ui.setup("Sector Heatmap", "🗺️")
C = T.C

# ---------------------------------------------------------------- sidebar
ui.sidebar_brand()
T.sidebar_head("View")
span = st.sidebar.selectbox("Change over", list(H.SPANS), index=0)
size_mode = st.sidebar.radio("Tile size", list(H.SIZE_MODES), horizontal=True,
                             help="Equal: every stock the same size (shows breadth). Market cap: bigger companies get "
                                  "bigger tiles (shows what moves the index). Traded value: price x average volume, "
                                  "i.e. where the money actually trades.")
back = st.sidebar.slider("Replay: sessions back", 0, 60, 0,
                         help="Step the map back in time: 0 = latest close, 5 = how it looked a week ago. "
                              "Ignored in Live mode.")
T.sidebar_head("Colours")
pal_name = st.sidebar.selectbox("Palette", list(H.PALETTES))
_default_scale = {"1 day": "±3%", "1 week": "±5%"}.get(span, "±10%")
scale_choice = st.sidebar.selectbox(
    "Colour scale", list(H.SCALES), index=H.SCALES.index(_default_scale), key=f"scale_{span}",
    help="A fixed scale means the same colour always means the same move, across days and markets. "
         "Auto stretches the scale to today's 90th-percentile move.")
UP, DN = H.PALETTES[pal_name]
T.sidebar_head("Data")
if st.sidebar.button("Refresh", use_container_width=True):
    st.cache_data.clear()


@st.cache_data(ttl=45, show_spinner=False)
def _live(market: str, tick: int) -> dict:
    """Intraday last price vs previous close. ``tick`` makes the cache expire with the refresh interval."""
    return screener.live_prices(list(sectors.sector_map(market)))


@st.cache_data(ttl=12 * 3600, show_spinner=False)
def _mcaps(market: str) -> dict:
    """Market caps barely move intraday, so they are fetched rarely and cached for half a day."""
    return screener.market_caps(list(sectors.sector_map(market)))


def _apply_live(df: pd.DataFrame, market: str, tick: int) -> pd.DataFrame:
    """Overwrite price / 1-day change with live values; returns df unchanged if the feed is empty."""
    lp = _live(market, tick)
    if not lp:
        return df
    inv = {ui.short_sym(k): k for k in sectors.sector_map(market)}
    df = df.copy()
    for i, r in df.iterrows():
        k = inv.get(r["Symbol"])
        if k in lp:
            px_, prev = lp[k]
            df.at[i, "Price"] = px_
            df.at[i, "1D %"] = (px_ / prev - 1) * 100
    return df


def _base_price(c: pd.Series, lookback: int | None) -> float | None:
    """Close the window is measured from: N sessions back, or the last close of the prior year for YTD."""
    if lookback is None:
        prior = c[c.index.year < c.index[-1].year]
        return float(prior.iloc[-1]) if len(prior) else float(c.iloc[0])
    return float(c.iloc[-1 - lookback]) if len(c) > lookback else None


@st.cache_data(ttl=3 * 3600, show_spinner=False)
def _fiidii(b: int) -> pd.DataFrame:
    """FII / DII cash-market net flows (NSE, provisional). Empty when NSE refuses the host."""
    return flows.fii_dii()


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _hist(market: str, b: int) -> dict:
    """One year of daily bars for the whole universe, shared by the map, rotation table and RRG."""
    return screener.batch_history(list(sectors.sector_map(market)), period="1y", min_rows=30)


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _load(market: str, span_name: str, b: int, back: int = 0) -> pd.DataFrame:
    """``b`` is a market-hours-aware cache bucket (short while open, long when closed).
    ``back`` replays the map that many sessions ago."""
    crypto = market == "CRYPTO"
    lookback = (H.SPANS_CRYPTO if crypto else H.SPANS)[span_name]
    smap = sectors.sector_map(market)
    hist = _hist(market, b)
    caps = _mcaps(market)
    rows = []
    for s, df in hist.items():
        if back:
            df = df.iloc[:-back]
            if len(df) < 30:
                continue
        c = df["Close"].dropna()
        base = _base_price(c, lookback)
        if base is None or len(c) < 2:
            continue
        last = float(c.iloc[-1])
        vol = df["Volume"].dropna() if "Volume" in df else pd.Series(dtype=float)
        vol_x = None
        value = None
        if len(vol) > 21:
            avg = float(vol.iloc[-21:-1].mean())
            vol_x = float(vol.iloc[-1]) / avg if avg > 0 else None
            value = avg if crypto else last * avg   # Yahoo's crypto volume is already in US$
        yr = c.tail(365 if crypto else 252)
        hi, lo = float(yr.max()), float(yr.min())
        pos = (last - lo) / (hi - lo) * 100 if hi > lo else None
        near_hi, near_lo = last >= hi * (1 - H.NEAR_52W), last <= lo * (1 + H.NEAR_52W)
        rows.append({
            "Symbol": ui.short_sym(s), "Y": s, "Sector": smap[s], "Price": last,
            "Change %": (last / base - 1) * 100, "1D %": (last / float(c.iloc[-2]) - 1) * 100,
            "Trend": [float(x) for x in c.tail(30)],
            "MCap": caps.get(s), "MCapTxt": H.fmt_cap(caps.get(s), "₹" if market == "IN" else "$"),
            "Value": value, "VolX": vol_x, "Pos52": pos, "Flags": H.flags(vol_x, pos, near_hi, near_lo),
            "AsOf": c.index[-1].strftime("%d %b %Y"),
        })
    return pd.DataFrame(rows)


def _static_map(df: pd.DataFrame, mkt: str, lim: float, height: int, wts: list[float],
                dim_below: float, hl: set[str]) -> go.Figure:
    """Plotly treemap built node by node so colours, flags, tooltips and outlines are all ours."""
    ids, labels, parents, values, colors, text, hover, line_c, line_w = [], [], [], [], [], [], [], [], []
    w_of = dict(zip(df["Symbol"], wts))
    sec_mean = df.groupby("Sector")["Change %"].mean()
    ids.append("ALL"); labels.append(mkt); parents.append(""); values.append(sum(wts))
    colors.append("#0A0B0D"); text.append(""); hover.append(""); line_c.append("#0A0B0D"); line_w.append(0)
    for sec, g in df.groupby("Sector"):
        ids.append(f"S:{sec}"); labels.append(f"{sec.upper()}  {sec_mean[sec]:+.2f}%"); parents.append("ALL")
        values.append(sum(w_of[x] for x in g["Symbol"]))
        colors.append("#121418"); text.append(""); hover.append(""); line_c.append("#0A0B0D"); line_w.append(1)
        for _, r in g.iterrows():
            pct = float(r["Change %"])
            ids.append(f"L:{r['Symbol']}"); parents.append(f"S:{sec}")
            labels.append(f"{r['Symbol']} {r['Flags']}".strip()); values.append(w_of[r["Symbol"]])
            colors.append(H.tile_color(pct, lim, UP, DN, dim=dim_below > 0 and abs(pct) < dim_below))
            text.append(f"{pct:+.1f}%")
            bits = [f"<b>{r['Symbol']}</b> · {sec}", f"{span}: <b>{pct:+.2f}%</b>   today: {r['1D %']:+.2f}%",
                    f"Price {H.fmt_price(r['Price'])}   Market cap {r['MCapTxt']}"]
            if pd.notna(r["VolX"]):
                bits.append(f"Volume {r['VolX']:.1f}× 20-day average" + ("  ⚡ spike" if r["VolX"] >= H.VOL_SPIKE else ""))
            if pd.notna(r["Pos52"]):
                bits.append(f"52-week range position {r['Pos52']:.0f}%")
            hover.append("<br>".join(bits))
            hi_ = r["Symbol"] in hl
            line_c.append("#FFFFFF" if hi_ else "#0A0B0D"); line_w.append(3 if hi_ else 1)
    fig = go.Figure(go.Treemap(
        ids=ids, labels=labels, parents=parents, values=values, branchvalues="total", text=text,
        texttemplate="%{label}<br>%{text}", hovertext=hover, hovertemplate="%{hovertext}<extra></extra>",
        marker=dict(colors=colors, line=dict(color=line_c, width=line_w)), textfont=dict(family="monospace", size=13),
        tiling=dict(pad=2), pathbar=dict(visible=False), sort=False,
    ))
    fig.update_layout(height=height, margin=dict(l=0, r=0, t=0, b=0))
    return fig


def _legend(lim: float) -> None:
    ramp = f"linear-gradient(90deg,{H.tile_color(-lim, lim, UP, DN)},{H.tile_color(0, lim, UP, DN)},{H.tile_color(lim, lim, UP, DN)})"
    st.markdown(
        f'<div style="display:flex;align-items:center;gap:8px;font-size:12px;color:#9aa0aa;flex-wrap:wrap">'
        f'<span>−{lim:g}%</span><div style="width:200px;height:8px;border-radius:4px;background:{ramp}"></div>'
        f'<span>+{lim:g}%</span><span style="margin-left:10px">colour saturates at ±{lim:g}% · ⚡ volume ≥ 2× its 20-day '
        f'average · ▲ / ▼ within 2% of the 52-week high / low · white outline = your highlighted tickers</span></div>',
        unsafe_allow_html=True)


ui.hero(
    "Sector Heatmap",
    "Large-cap stocks (and major crypto coins) grouped by sector or category. Colour = move over the chosen window; tile size = equal, market cap or traded "
    "value (sidebar). Use it to see where money is rotating.",
    pills=[("Delayed data", "amber"), (size_mode, "flat"), ("Live mode available", "flat")],
)


def _view(mkt: str, live: bool) -> None:
    _M = {"India": "IN", "United States": "US", "Crypto": "CRYPTO"}[mkt]
    crypto = _M == "CRYPTO"
    unit = "coins" if crypto else "stocks"
    with st.spinner("Loading prices…"):
        df = _load(_M, span, cache.bucket(_M, 3), 0 if live else back)
        if live:
            df = _apply_live(df, _M, int(time.time() // 60))
            df["Change %"] = df["1D %"]   # live mode is always "today vs previous close"

    if df.empty:
        ui.empty_note("<b>No prices returned.</b> Yahoo may be rate-limiting. Try Refresh in a minute.")
        return
    df = df.assign(Change1D=df["1D %"])

    with st.expander("Display options", expanded=False):
        o1, o2, o3 = st.columns(3)
        all_secs = sorted(df["Sector"].unique())
        pick_secs = o1.multiselect("Sectors shown", all_secs, default=all_secs)
        dim_below = o2.slider("Dim moves smaller than (%)", 0.0, 3.0, 0.0, 0.25,
                              help="Fades tiles whose move is below this size so the real movers stand out.")
        hl_text = o3.text_input("Highlight tickers", value=st.session_state.get("wl_last", ""),
                                help="Comma-separated. Prefilled from your Watchlist if you opened it this session.")
        f1, f2, f3, f4 = st.columns([1.3, 1, 1, 1])
        f_mode = f1.selectbox("Quick filter", list(H.FILTER_MODES))
        f_top = f2.selectbox("Size tier", ["All", "Top 20 by market cap", "Top 50 by market cap"],
                             help="Keeps only the largest companies, so the map shows what moves the index.")
        f_search = f3.text_input("Search ticker", help="Substring match, e.g. 'BANK' or 'TA'.")
        f_only = f4.checkbox("Only my highlighted tickers", help="Show just the tickers in the highlight box (e.g. your watchlist).")
        h_choice = st.radio("Map height", ["Compact", "Standard", "Tall"], index=1, horizontal=True)
    height = {"Compact": 460, "Standard": 560, "Tall": 760}[h_choice]
    hl = H.parse_tickers(hl_text)
    if pick_secs:
        df = df[df["Sector"].isin(pick_secs)].reset_index(drop=True)
    df = H.apply_filters(df, f_mode, {"All": None, "Top 20 by market cap": 20, "Top 50 by market cap": 50}[f_top],
                         f_search, hl if (f_only and hl) else None)
    if df.empty:
        ui.empty_note("<b>Nothing to show.</b> No sectors selected, or the filters in Display options match no "
                      f"{unit}.")
        return

    mkt_avg = float(df["Change %"].mean())
    sec = df.groupby("Sector")["Change %"].agg(["mean", "count"]).sort_values("mean", ascending=False)
    sec["up"] = df.assign(_u=df["Change %"] > 0).groupby("Sector")["_u"].sum().reindex(sec.index).astype(int)
    sec["rs"] = H.rel_strength(sec["mean"], mkt_avg)
    best, worst = sec.index[0], sec.index[-1]
    win = "today" if live else span
    k = st.columns(4)
    T.kpi(k[0], "Leading sector", str(best), f"{sec.loc[best, 'mean']:+.2f}% avg", "up", small=True)
    T.kpi(k[1], "Lagging sector", str(worst), f"{sec.loc[worst, 'mean']:+.2f}% avg", "down", small=True)
    T.kpi(k[2], "Advancers / decliners", f"{int((df['Change %'] > 0).sum())} / {int((df['Change %'] < 0).sum())}",
          f"of {len(df)} {unit}", "flat")
    T.kpi(k[3], "Market average", f"{mkt_avg:+.2f}%", win, T.sign_tone(mkt_avg))
    st.markdown("<div style='height:.4rem'></div>", unsafe_allow_html=True)

    gain, lose = H.top_movers(df, 5)
    if len(gain) or len(lose):
        def _chips(frame: pd.DataFrame, tone: str) -> str:
            col = T.tone_color(tone)
            return "".join(
                f'<span style="display:inline-block;margin:2px 6px 2px 0;padding:2px 8px;border-radius:10px;'
                f'background:#14171c;border:1px solid #23272f;font:12px monospace;color:{col}">'
                f'{ui._e(r["Symbol"])} {r["Change %"]:+.1f}%</span>' for _, r in frame.iterrows())
        st.markdown(f'<div style="font-size:12px;color:#9aa0aa">Top gainers {_chips(gain, "up")}'
                    f'&nbsp;&nbsp;Top losers {_chips(lose, "down")}</div>', unsafe_allow_html=True)
        st.markdown("<div style='height:.3rem'></div>", unsafe_allow_html=True)

    if _M == "IN":
        fd = _fiidii(cache.bucket("IN", 5))
        if fd.empty:
            st.caption("FII / DII flows: unavailable right now (NSE blocks some hosts).")
        else:
            def _flow_chip(r: pd.Series) -> str:
                col = T.tone_color(T.sign_tone(r["Net (Cr)"]))
                return (f'<span style="display:inline-block;margin:2px 6px 2px 0;padding:2px 8px;border-radius:10px;'
                        f'background:#14171c;border:1px solid #23272f;font:12px monospace;color:{col}">'
                        f'{ui._e(str(r["Category"]).split()[0])} net ₹{r["Net (Cr)"]:+,.0f} Cr</span>')
            st.markdown('<div style="font-size:12px;color:#9aa0aa">FII / DII cash market, '
                        f'{ui._e(str(fd["Date"].iloc[0]))} '
                        + "".join(_flow_chip(r) for _, r in fd.iterrows())
                        + ' <span style="color:#6b7280">provisional, market-wide (NSE does not split flows by sector)</span></div>',
                        unsafe_allow_html=True)
        st.markdown("<div style='height:.3rem'></div>", unsafe_allow_html=True)

    if crypto:
        st.caption("Crypto trades 24/7, so there is no closing bell: “today” is the move since the previous UTC-day "
                   "close, and week/month windows count calendar days. Traded value is Yahoo's 24-hour US$ volume. "
                   "Coins Yahoo does not return simply do not appear.")
    asof = (f"Prices as of {datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%d %b %Y, %H:%M')} IST (live, exchange-delayed where Yahoo says so)"
            if live else f"Data as of {'last close' if not back else f'{back} sessions back'}, {df['AsOf'].iloc[0]}")
    st.caption(f"{asof} · window: {win} · tile size: {size_mode}"
               + (" · market caps are cached for 12h" if size_mode == "Market cap" else ""))

    lim = H.scale_limit(df["Change %"], scale_choice)
    wts = H.weights(df, size_mode)
    if size_mode != "Equal" and len(set(round(w, 6) for w in wts)) == 1:
        st.info(f"{size_mode} data was unavailable from Yahoo right now, so tiles are equal-sized.")
    _legend(lim)

    if live:
        n_sec, max_n = int(df["Sector"].nunique()), int(df.groupby("Sector").size().max())
        components.html(
            liveheat.build_html(df, None, lim, height, "Prices stream from Yahoo; they are exchange-delayed where Yahoo says so.",
                                weights=wts, palette=(UP, DN), highlight=hl, min_move=dim_below, size_label=size_mode, crypto=crypto),
            height=height + 80 + 36 * n_sec + 110 + 36 * max_n + 150)
    else:
        st.plotly_chart(_static_map(df, mkt, lim, height, wts, dim_below, hl), use_container_width=True,
                        config={"displaylogo": False})

    if not live:  # in live mode the ranking is part of the streaming block above
        ui.table_title("Sector ranking", "flat")
        rows = []
        mx = max(float(sec["mean"].abs().max()), 0.01)
        for name, r in sec.iterrows():
            col = T.tone_color(T.sign_tone(r["mean"]))
            rs_col = T.tone_color(T.sign_tone(r["rs"]))
            w = min(60, abs(float(r["mean"])) / mx * 60)
            rows.append(
                f'<tr><td><b>{ui._e(name)}</b></td><td class="dim">{int(r["count"])}</td>'
                f'<td class="dim">{int(r["up"])}↑ {int(r["count"] - r["up"])}↓</td>'
                f'<td class="chg" style="color:{col}"><span class="bar" style="width:{w:.0f}px;background:{col}"></span>'
                f'{ui._pct(r["mean"])}</td>'
                f'<td class="chg" style="color:{rs_col}">{r["rs"]:+.2f} pts</td></tr>'
            )
        st.markdown(
            '<div class="ttw"><table class="tt"><thead><tr><th>Sector</th><th>Stocks</th><th>Up / down</th>'
            '<th>Avg change</th><th>vs market</th></tr></thead>'
            "<tbody>" + "".join(rows) + "</tbody></table></div>",
            unsafe_allow_html=True,
        )
        st.caption("“vs market” is the sector's average minus the all-stock average, in percentage points: "
                   "positive means the sector is outperforming the rest of this universe.")

        T.rule("Sector rotation: momentum across windows")
        spans_cmp = [x for x in ("1 day", "1 week", "1 month", "3 months") if x in H.SPANS]
        by_span = {}
        for sp_name in spans_cmp:
            d_ = _load(_M, sp_name, cache.bucket(_M, 3), back)
            if len(d_) and pick_secs:
                d_ = d_[d_["Sector"].isin(pick_secs)]
            by_span[sp_name] = d_
        mm = H.momentum_matrix(by_span)
        if len(mm):
            lim_m = max(2.0, float(mm[spans_cmp].abs().stack().quantile(0.9)))
            shown = mm.reset_index().rename(columns={"index": "Sector"})
            if "Sector" not in shown.columns:
                shown = shown.rename(columns={shown.columns[0]: "Sector"})
            sty = shown.style.format({c: "{:+.2f}%" for c in spans_cmp}).background_gradient(
                cmap="RdYlGn", subset=spans_cmp, vmin=-lim_m, vmax=lim_m)
            st.dataframe(sty, use_container_width=True, hide_index=True)
            st.caption("Average move per sector over each window. “Accelerating” = the short window is beating the "
                       "longer one while positive (money flowing in now); “Fading” = a longer-term winner that is "
                       "losing steam; “Weak” = down in the short window.")

        st.download_button("Download this view as CSV",
                           df.drop(columns=["Trend", "Y", "Flags", "MCapTxt", "Change1D"], errors="ignore")
                             .to_csv(index=False).encode("utf-8"),
                           file_name=f"sector_heatmap_{_M}_{span.replace(' ', '')}.csv", mime="text/csv")

        T.rule("Relative rotation graph (RRG)")
        smap_ = sectors.sector_map(_M)
        hist_ = _hist(_M, cache.bucket(_M, 3))
        closes_ = pd.DataFrame({k: (v["Close"].iloc[:-back] if back else v["Close"]) for k, v in hist_.items()
                                if k in smap_}).sort_index()
        if pick_secs:
            closes_ = closes_[[k for k in closes_.columns if smap_[k] in pick_secs]]
        rr = H.rrg(closes_, smap_)
        if rr:
            qcol = {"Leading": "#19D27A", "Weakening": "#FFC247", "Lagging": "#FF3B4E", "Improving": "#3B9DFF"}
            fig = go.Figure()
            for name, d in rr.items():
                last = d.iloc[-1]
                fig.add_trace(go.Scatter(x=d["ratio"], y=d["momentum"], mode="lines+markers", name=name,
                                         line=dict(color=qcol[last["Quadrant"]], width=1.5),
                                         marker=dict(size=[4] * (len(d) - 1) + [11], color=qcol[last["Quadrant"]]),
                                         hovertemplate=name + "<br>strength %{x:.1f} · momentum %{y:.1f}<extra></extra>",
                                         showlegend=False))
                fig.add_annotation(x=last["ratio"], y=last["momentum"], text=name, showarrow=False, yshift=14,
                                   font=dict(size=10, color=qcol[last["Quadrant"]]))
            fig.add_vline(x=100, line_color="#444", line_width=1)
            fig.add_hline(y=100, line_color="#444", line_width=1)
            for txt, xa, ya, xan, yan in (("LEADING", "right", "top", 1, 1), ("WEAKENING", "right", "bottom", 1, 0),
                                          ("LAGGING", "left", "bottom", 0, 0), ("IMPROVING", "left", "top", 0, 1)):
                fig.add_annotation(xref="paper", yref="paper", x=xan, y=yan, text=txt, showarrow=False,
                                   xanchor=xa, yanchor=ya, font=dict(size=11, color="#555"))
            fig.update_layout(height=460, margin=dict(l=8, r=8, t=8, b=8), xaxis_title="Relative strength vs market (100 = in line)",
                              yaxis_title="Momentum (100 = flat)")
            st.plotly_chart(T.style_axes(fig), use_container_width=True, config={"displaylogo": False})
            st.caption("Each sector's equal-weighted index vs the all-stock average. Right = outperforming, up = "
                       "improving. Sectors normally circle clockwise: Improving → Leading → Weakening → Lagging. "
                       "The big dot is today, the tail is the last 5 sessions.")
        else:
            st.caption("Not enough price history to draw the rotation graph for this selection.")

        T.rule("Drill into a sector")
        pick = st.selectbox("Sector", list(sec.index), label_visibility="collapsed")
        sub = df[df["Sector"] == pick].sort_values("Change %", ascending=False)
        c1, c2 = st.columns([1, 1])
        with c1:
            fig = go.Figure(go.Bar(x=sub["Change %"], y=sub["Symbol"], orientation="h",
                                   marker_color=[UP if v >= 0 else DN for v in sub["Change %"]],
                                   hovertemplate="%{y}: %{x:+.2f}%<extra></extra>"))
            fig.update_layout(height=max(260, 28 * len(sub) + 60), margin=dict(l=8, r=8, t=8, b=8),
                              yaxis=dict(autorange="reversed"), xaxis_title=f"Change over {span}",
                              xaxis_title_font=dict(size=10, color=C["faint"]))
            st.plotly_chart(T.style_axes(fig), use_container_width=True)
        with c2:
            st.dataframe(
                sub[["Symbol", "Price", "Change %", "1D %", "VolX", "Pos52", "Trend"]],
                use_container_width=True, hide_index=True,
                column_config={
                    "Price": st.column_config.NumberColumn(format="%.6g" if crypto else "%.2f"),
                    "Change %": st.column_config.NumberColumn(format="%+.2f"),
                    "1D %": st.column_config.NumberColumn(format="%+.2f"),
                    "VolX": st.column_config.NumberColumn("Volume ×avg", format="%.1f×"),
                    "Pos52": st.column_config.ProgressColumn("52-wk range", min_value=0, max_value=100, format="%.0f%%"),
                    "Trend": st.column_config.LineChartColumn("30-day trend"),
                },
            )
            if not crypto:  # the Analyze page covers listed stocks only
                who = st.selectbox("Open a stock in Analyze", list(sub["Symbol"]), key=f"open_{_M}_{pick}")
                st.markdown(f"[Open {who} in Analyze →](/?s={who}&m={_M})")
    else:
        st.caption("Live ticks stream straight to your browser (no page refresh). The summary cards above are a "
                   "snapshot from when you switched Live on; the map's own header updates tick by tick. "
                   "Live mode shows today's change vs the previous close and ignores the window selector. "
                   "Click a tile to jump to that sector's drill-down; hover for details; Pause freezes the map. "
                   "Tiles stay still while the exchange is closed.")


c_m, c_l = st.columns([2, 1])
with c_m:
    mkt = st.radio("Market", ["India", "United States", "Crypto"], horizontal=True, label_visibility="collapsed")
with c_l:
    live = st.toggle("Live", value=False, help="Stream live price ticks into the map (today vs previous close).")
_view(mkt, live)
ui.footer()
