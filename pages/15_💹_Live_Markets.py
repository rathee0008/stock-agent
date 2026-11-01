"""Live markets: stock indices, Bitcoin and other major coins, crude oil, gold, silver, US dollar index, USD/INR and US Treasury
yields on one page, auto-refreshing, with a sparkline and tick-by-tick flash on every instrument.

Data is Yahoo Finance (agent/livemarkets.py). Crypto, FX and futures stream close to real time; NSE/BSE and
some index feeds are ~15 minutes delayed. Each card shows the timestamp of its own last bar, so "live" is
never assumed: a closed market shows CLOSED and its last close.
"""

import html as _html
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import livemarkets as LM, livequotes as LV, theme as T, ticker, ui  # noqa: E402

ui.setup("Live Markets", "💹")
C = T.C
IST = ZoneInfo("Asia/Kolkata")

ui.sidebar_brand()
T.sidebar_head("Live")
live_on = st.sidebar.toggle("Auto-refresh", value=True)
refresh = st.sidebar.select_slider("Refresh every (seconds)", options=[5, 10, 15, 30, 60], value=10)
groups = st.sidebar.multiselect("Sections", LM.GROUPS, default=LM.GROUPS)
rank_live_only = st.sidebar.toggle("Rank live feeds only", value=True,
                                   help="Leave out closed markets so the ranking only shows what is moving now.")
if st.sidebar.button("Refresh now", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.markdown(
    f"""<style>
.lm-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(205px,1fr));gap:.55rem;margin-bottom:1.1rem}}
.lm-card{{border:1px solid var(--line);border-top:2px solid var(--line-hi);border-radius:3px;background:var(--panel);
padding:.6rem .75rem .5rem;position:relative}}
.lm-card.up{{border-top-color:{C["up"]}}}.lm-card.down{{border-top-color:{C["down"]}}}
.lm-top{{display:flex;justify-content:space-between;align-items:center;gap:.4rem}}
.lm-name{{font-size:.6rem;letter-spacing:.13em;color:var(--faint);font-weight:700;text-transform:uppercase;white-space:nowrap}}
.lm-st{{font-family:var(--mono);font-size:.55rem;letter-spacing:.08em;font-weight:700;color:{C["dim"]}}}
.lm-st.live{{color:{C["up"]}}}
.lm-px{{font-family:var(--mono);font-size:1.3rem;font-weight:700;color:var(--text);margin:.2rem 0 .05rem;
font-variant-numeric:tabular-nums;letter-spacing:-.01em}}
.lm-chg{{font-family:var(--mono);font-size:.74rem;font-weight:700;font-variant-numeric:tabular-nums}}
.lm-spark{{display:block;width:100%;height:30px;margin:.3rem 0 .15rem}}
.lm-foot{{font-family:var(--mono);font-size:.58rem;color:var(--faint);letter-spacing:.04em;white-space:nowrap;
overflow:hidden;text-overflow:ellipsis}}
.lm-card.flash-up{{animation:lmup 1.1s ease-out}}.lm-card.flash-down{{animation:lmdn 1.1s ease-out}}
@keyframes lmup{{0%{{background:rgba(14,203,129,.28)}}100%{{background:var(--panel)}}}}
@keyframes lmdn{{0%{{background:rgba(246,70,93,.28)}}100%{{background:var(--panel)}}}}
</style>""",
    unsafe_allow_html=True,
)


@st.cache_data(ttl=5, show_spinner=False)
def snapshot() -> pd.DataFrame:
    return LM.fetch_snapshot()


def _e(v) -> str:
    return _html.escape(str(v))


def _num(v: float, dp: int) -> str:
    return f"{v:,.{dp}f}"


def _signed(v: float | None, dp: int, suffix: str = "") -> str:
    return "n/a" if v is None or pd.isna(v) else f"{v:+,.{dp}f}{suffix}"


def _spark(values: list[float], colour: str) -> str:
    if len(values) < 2:
        return '<svg class="lm-spark" viewBox="0 0 120 30"></svg>'
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    pts = " ".join(f"{i * 120 / (len(values) - 1):.1f},{28 - (v - lo) / span * 26:.1f}" for i, v in enumerate(values))
    return (f'<svg class="lm-spark" viewBox="0 0 120 30" preserveAspectRatio="none">'
            f'<polyline points="{pts}" fill="none" stroke="{colour}" stroke-width="1.4" '
            f'vector-effect="non-scaling-stroke"/></svg>')


def _flip(key: str) -> int:
    """Counter that alternates the flash animation name so back-to-back ticks replay."""
    st.session_state[key] = st.session_state.get(key, 0) + 1
    return st.session_state[key]


def _ranking(df: pd.DataFrame) -> None:
    """One leaderboard across every selected section, sorted by live % move, with rank-change badges."""
    pool = df[(df["group"].isin(groups)) & (df["kind"] == "price") & df["move"].notna()]
    note = ""
    if rank_live_only:
        live_rows = pool[pool["live"]]
        if live_rows.empty and not pool.empty:
            note = "No feed is live right now, so every instrument is ranked on its last close."
        else:
            pool = live_rows
    if pool.empty:
        ui.empty_note("<b>Nothing to rank yet.</b> No instrument in the selected sections has a move to rank.")
        return
    pool = pool.sort_values("move", ascending=False).reset_index(drop=True)
    syms = list(pool["symbol"])
    moves = LV.rank_moves(st.session_state.get("lm_rank_prev", []), syms)
    st.session_state["lm_rank_prev"] = syms
    flip = _flip("lm_rank_flip")
    mx = max(float(pool["move"].abs().max()), 0.01)
    rows = []
    for i, (_, r) in enumerate(pool.iterrows(), 1):
        mv = float(r["move"])
        col = T.tone_color(T.sign_tone(mv))
        rm = moves.get(r["symbol"])
        rfl = ui.flash_cls(1 if rm == "new" else rm, flip)
        fl = ui.flash_cls(r["tick"], flip)
        st_txt = '<span style="color:var(--up,#0ecb81)">● LIVE</span>' if r["live"] else "○ CLOSED"
        rows.append(
            f'<tr><td class="{rfl}"><span class="rk">{i:02d}</span>{ui._rank_badge(rm)}<b>{_e(r["label"])}</b></td>'
            f'<td class="dim">{_e(r["group"])}</td><td class="{fl}">{_num(r["price"], r["dp"])}</td>'
            f'<td class="chg {fl}" style="color:{col}"><span class="bar" style="width:{abs(mv) / mx * 46:.0f}px;'
            f'background:{col}"></span>{_signed(mv, 2, "%")}</td><td class="dim">{st_txt}</td></tr>')
    ui.table_title(f"Live ranking · {len(pool)} instruments by % move", "amber")
    st.markdown('<div class="ttw"><table class="tt"><thead><tr><th>Instrument</th><th>Section</th><th>Price</th>'
                '<th>Move</th><th>Feed</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>",
                unsafe_allow_html=True)
    st.caption((note + " " if note else "") + "Ranked by % move vs previous close. ▲/▼ shows places gained or lost "
               "since the last refresh. Treasury yields move in basis points, so they are not ranked against % moves.")


def _card(r: pd.Series, tick: float) -> str:
    move = r["move"]
    tone = T.sign_tone(None if pd.isna(move) else float(move))
    colour = T.tone_color(tone)
    arrow = "▲" if tone == "up" else "▼" if tone == "down" else "•"
    unit_dp = 2 if r["unit"] == "%" else 1
    chg_txt = f'{arrow} {_signed(r["chg"], r["dp"])} ({_signed(move, unit_dp, "%" if r["unit"] == "%" else " bps")})'
    flash = " flash-up" if tick > 0 else " flash-down" if tick < 0 else ""
    when = r["asof"].astimezone(IST)
    status = ('<span class="lm-st live">● LIVE</span>' if r["live"]
              else '<span class="lm-st">○ CLOSED</span>')
    foot = f'{_e(r["symbol"])} · {when:%d %b %H:%M} IST'
    prev_attr = "" if pd.isna(r["prev"]) else f'{float(r["prev"]):.10g}'
    spark_attr = _e(json.dumps([round(float(v), 6) for v in r["spark"]]))
    return (f'<div class="lm-card {tone}{flash}" data-sym="{_e(r["symbol"])}" data-prev="{prev_attr}" '
            f'data-dp="{int(r["dp"])}" data-spark="{spark_attr}" title="Last bar {when:%d %b %Y %H:%M:%S} IST · prev close '
            f'{_e(_num(r["prev"], r["dp"]) if pd.notna(r["prev"]) else "n/a")}">'
            f'<div class="lm-top"><span class="lm-name">{_e(r["label"])}</span>{status}</div>'
            f'<div class="lm-px">{_num(r["price"], r["dp"])}</div>'
            f'<div class="lm-chg" style="color:{colour}">{chg_txt}</div>'
            f'{_spark(r["spark"], colour)}<div class="lm-foot">{foot}</div></div>')


ui.hero(
    "Live Markets",
    "Indian, US and world indices, Bitcoin and other major coins, crude oil, gold, silver, the US dollar index, USD/INR and US "
    "Treasury yields on one page. A live ranking orders every instrument by its move, and each card flashes green or red when the price ticks.",
    pills=[("LIVE" if live_on else "PAUSED", "up" if live_on else "flat"),
           ("Yahoo Finance", "amber"), ("Times in IST", "flat")],
)


ticker.render_tile_driver()  # streams real crypto trades into the cards between polls, no rerun needed


@st.fragment(run_every=refresh if live_on else None)
def live_panel() -> None:
    try:
        df = snapshot()
    except Exception as exc:  # noqa: BLE001
        ui.empty_note(f"<b>Could not load prices.</b> {_e(exc)}. It will retry on the next refresh.")
        return
    if df.empty:
        ui.empty_note("<b>No prices returned.</b> Yahoo may be rate-limiting. It will retry on the next refresh.")
        return

    prev_px = st.session_state.get("lm_prev", {})
    df = df.assign(tick=[(p - prev_px[s]) if s in prev_px else 0.0 for s, p in zip(df["symbol"], df["price"])])
    st.session_state["lm_prev"] = dict(zip(df["symbol"], df["price"]))

    ticker.render(df[df["group"].isin(groups)].to_dict("records"))

    moved = df.dropna(subset=["move"])
    up, down = int((moved["move"] > 0).sum()), int((moved["move"] < 0).sum())
    T.kpi_row([
        ("Last refresh", datetime.now(IST).strftime("%H:%M:%S"), "IST", "amber"),
        ("Feeds live", f'{int(df["live"].sum())} / {len(df)}', "last bar under 20 min old", "flat"),
        ("Rising", str(up), "vs previous close", "up"),
        ("Falling", str(down), "vs previous close", "down"),
    ])

    _ranking(df)

    for group in LM.GROUPS:
        if group not in groups:
            continue
        part = df[df["group"] == group]
        if part.empty:
            continue
        ui.table_title(group.upper(), "amber")
        cards = "".join(_card(r, r["tick"]) for _, r in part.iterrows())
        st.markdown(f'<div class="lm-grid">{cards}</div>', unsafe_allow_html=True)

    missing = [x.label for x in LM.INSTRUMENTS if x.symbol not in set(df["symbol"]) and x.group in groups]
    if missing:
        st.caption("No data returned for: " + ", ".join(missing) + ". They will reappear when Yahoo responds.")

    with st.expander("Exact values table"):
        table = pd.DataFrame({
            "Instrument": df["label"],
            "Symbol": df["symbol"],
            "Price": [_num(p, d) for p, d in zip(df["price"], df["dp"])],
            "Prev close": [_num(p, d) if pd.notna(p) else "n/a" for p, d in zip(df["prev"], df["dp"])],
            "Change": [_signed(c, d) for c, d in zip(df["chg"], df["dp"])],
            "Move": [_signed(m, 2 if u == "%" else 1, "%" if u == "%" else " bps") for m, u in zip(df["move"], df["unit"])],
            "Last bar (IST)": [t.astimezone(IST).strftime("%d %b %H:%M:%S") for t in df["asof"]],
            "Age (min)": df["age_min"].round(1),
            "Status": ["LIVE" if x else "CLOSED" for x in df["live"]],
        })
        st.dataframe(table, hide_index=True, use_container_width=True)


live_panel()
st.caption(
    "Source: Yahoo Finance. Bitcoin, FX and futures (gold, silver, crude) stream close to real time; NSE/BSE and "
    "several index feeds run about 15 minutes behind. Treasury yields move in basis points (1 bp = 0.01 "
    "percentage point). Gold, silver and crude are front-month futures. A CLOSED card shows the last close."
)
ui.footer()
