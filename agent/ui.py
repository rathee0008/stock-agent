"""Pro-terminal UI components shared by every page.

Builds on agent.theme (palette, KPI tiles, meters, plotly template) and
adds the page-level pieces: hero header, market strip, mover tables, pick
cards, news/deal feed and insider table. Everything renders as one HTML string
per component (no blank lines, so Streamlit's markdown never turns it into a
code block).
"""

from __future__ import annotations

import html as _html
import re

import pandas as pd
import streamlit as st

from . import theme as T

C = T.C

_CSS = """
<style>
/* ---------- hero ---------- */
.hero{display:flex;justify-content:space-between;align-items:flex-end;gap:1rem;flex-wrap:wrap;
padding:1.15rem 1.3rem;margin-bottom:.9rem;border:1px solid var(--line);border-left:3px solid var(--amber);
border-radius:3px;background:radial-gradient(900px 220px at 0% 0%,rgba(255,159,28,.11),transparent 62%),linear-gradient(180deg,#12151B,var(--panel));}
.hero .kick{font-family:var(--mono);font-size:.62rem;letter-spacing:.26em;color:var(--amber);font-weight:700;text-transform:uppercase}
.hero .ttl{font-size:1.75rem;font-weight:700;margin:.3rem 0 .25rem;color:var(--text);letter-spacing:-.015em;line-height:1.15}
.hero .sub{color:var(--dim);font-size:.84rem;max-width:72ch;line-height:1.55}
.hero .pills{display:flex;gap:.45rem;flex-wrap:wrap;align-items:center}

/* ---------- market strip ---------- */
.mstrip{display:flex;overflow-x:auto;border:1px solid var(--line);border-radius:3px;background:var(--panel);margin-bottom:.85rem}
.mcell{flex:1 0 auto;min-width:128px;padding:.5rem .85rem;border-right:1px solid var(--line)}
.mcell:last-child{border-right:0}
.mcell .n{font-size:.58rem;letter-spacing:.14em;color:var(--faint);font-weight:700;text-transform:uppercase;white-space:nowrap}
.mcell .p{font-family:var(--mono);font-size:.95rem;font-weight:600;color:var(--text);margin-top:.12rem;font-variant-numeric:tabular-nums}
.mcell .c{font-family:var(--mono);font-size:.7rem;font-weight:700}

/* ---------- data tables ---------- */
.ttw{border:1px solid var(--line);border-radius:3px;background:var(--panel);overflow-x:auto}
table.tt{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:.78rem;font-variant-numeric:tabular-nums}
table.tt th{font-size:.58rem;letter-spacing:.14em;text-transform:uppercase;color:var(--faint);font-weight:700;
text-align:right;padding:.5rem .7rem;border-bottom:1px solid var(--line-hi);white-space:nowrap;background:#0E1014}
table.tt td{padding:.45rem .7rem;border-bottom:1px solid var(--line);text-align:right;color:var(--text);white-space:nowrap}
table.tt th:first-child,table.tt td:first-child{text-align:left}
table.tt tr:last-child td{border-bottom:0}
table.tt tr:hover td{background:var(--panel-hi)}
table.tt .chg{font-weight:700}
table.tt .bar{display:inline-block;height:4px;border-radius:2px;vertical-align:middle;margin-right:.45rem;opacity:.9}
table.tt .rk{color:var(--faint);margin-right:.6rem;font-size:.68rem}
table.tt .dim{color:var(--dim)}
table.tt .wrap{white-space:normal;text-align:left;min-width:220px}
.tt-title{display:flex;align-items:center;gap:.55rem;margin:.2rem 0 .45rem;font-size:.7rem;letter-spacing:.16em;
text-transform:uppercase;font-weight:700;color:var(--dim)}
.tt-title i{width:8px;height:8px;border-radius:50%;display:inline-block}

/* ---------- pick cards ---------- */
.pgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:.75rem}
.pcard{background:var(--panel);border:1px solid var(--line);border-radius:3px;padding:.85rem .95rem;
transition:border-color .15s ease,transform .15s ease;position:relative;overflow:hidden}
.pcard:hover{border-color:var(--amber-dim);transform:translateY(-1px)}
.pcard:before{content:"";position:absolute;left:0;top:0;bottom:0;width:2px;background:var(--accent,var(--line-hi))}
.pcard .top{display:flex;align-items:center;gap:.65rem}
.pcard .rank{font-family:var(--mono);font-size:.68rem;font-weight:700;color:#0A0B0D;background:var(--amber);
border-radius:2px;padding:.12rem .42rem}
.pcard .psym{font-family:var(--mono);font-weight:700;font-size:1.02rem;color:var(--text);letter-spacing:.03em}
.pcard .pname{color:var(--dim);font-size:.72rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:22ch}
.pcard .pscore{margin-left:auto;text-align:right;line-height:1}
.pcard .pscore .v{font-family:var(--mono);font-size:1.4rem;font-weight:700}
.pcard .pscore .l{font-size:.52rem;letter-spacing:.16em;color:var(--faint);font-weight:700;margin-top:.15rem}
.pcard .meta{display:flex;gap:.45rem;align-items:center;margin:.5rem 0 .1rem;flex-wrap:wrap}
.pcard .px{display:flex;gap:.8rem;align-items:baseline;margin:.45rem 0 .6rem;font-family:var(--mono);font-variant-numeric:tabular-nums}
.pcard .px .big{font-size:1.1rem;font-weight:600;color:var(--text)}
.pcard .px .s{font-size:.72rem;font-weight:600}
.pcard .mini3{display:grid;grid-template-columns:repeat(3,1fr);gap:.7rem}
.mini .l{display:flex;justify-content:space-between;font-size:.54rem;letter-spacing:.12em;color:var(--faint);
text-transform:uppercase;font-weight:700;margin-bottom:.25rem}
.mini .l b{font-family:var(--mono);letter-spacing:0}
.mini .t{height:4px;background:var(--line);border-radius:2px;position:relative}
.mini .t:after{content:"";position:absolute;left:50%;top:-2px;width:1px;height:8px;background:var(--line-hi)}
.mini .f{position:absolute;top:0;height:4px;border-radius:2px}
.pcard .why{margin-top:.7rem;border-top:1px solid var(--line);padding-top:.55rem;color:var(--dim);font-size:.73rem;line-height:1.55}
.pcard .why b{color:var(--text);font-weight:600}
.chip{display:inline-block;font-family:var(--mono);font-size:.6rem;letter-spacing:.08em;text-transform:uppercase;
padding:.1rem .4rem;border-radius:2px;border:1px solid var(--line-hi);color:var(--dim);white-space:nowrap}

/* ---------- feeds ---------- */
.feed{border:1px solid var(--line);border-radius:3px;background:var(--panel)}
.feed .row{display:flex;gap:.75rem;align-items:flex-start;padding:.6rem .85rem;border-bottom:1px solid var(--line)}
.feed .row:last-child{border-bottom:0}
.feed .row:hover{background:var(--panel-hi)}
.feed .tm{font-family:var(--mono);font-size:.64rem;color:var(--faint);min-width:6.6rem;padding-top:.15rem;white-space:nowrap}
.feed a{color:var(--text);text-decoration:none;font-size:.84rem;line-height:1.45}
.feed a:hover{color:var(--amber)}
.feed .src{font-family:var(--mono);font-size:.6rem;color:var(--faint);text-transform:uppercase;letter-spacing:.08em;margin-top:.15rem}
.feed-scroll{max-height:430px;overflow-y:auto}

/* ---------- misc ---------- */
.footbar{margin-top:2.2rem;padding-top:.8rem;border-top:1px solid var(--line);font-family:var(--mono);font-size:.62rem;
letter-spacing:.08em;color:var(--faint);text-transform:uppercase;line-height:1.7}
.empty{border:1px dashed var(--line-hi);border-radius:3px;padding:1.1rem 1.2rem;color:var(--dim);font-size:.82rem;background:rgba(255,255,255,.01)}
.empty b{color:var(--text)}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a{border-radius:2px;font-size:.78rem}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a span,section[data-testid="stSidebar"] label,section[data-testid="stSidebar"] label p,section[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p,section[data-testid="stSidebar"] [data-testid="stRadio"] p{color:#c9d1d9!important}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] span{color:#ffb020!important}
section[data-testid="stSidebar"] [data-testid="stThumbValue"]{color:#ffb020!important}
section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"]{background:var(--panel-hi);border-left:2px solid var(--amber)}
[data-testid="stRadio"] label p{font-size:.78rem}
@media (max-width:760px){.hero .ttl{font-size:1.35rem}.pgrid{grid-template-columns:1fr}.mcell{min-width:112px}}
</style>
"""


def inject_extra() -> None:
    """Inject the component stylesheet (after theme.inject)."""
    st.markdown(_CSS, unsafe_allow_html=True)


def setup(title: str, icon: str = "📊") -> None:
    """First call on every page: page config + theme + component CSS."""
    st.set_page_config(page_title=title, page_icon=icon, layout="wide",
                       initial_sidebar_state="expanded")
    T.inject()
    T.register_plotly()
    inject_extra()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _e(v) -> str:
    return _html.escape("" if v is None else str(v))


def _ok(v) -> bool:
    return v is not None and not (isinstance(v, float) and pd.isna(v)) and v is not pd.NA


def short_sym(s) -> str:
    return re.sub(r"\.(NS|BO)$", "", str(s))


def _px(v, nd: int = 2) -> str:
    return f"{float(v):,.{nd}f}" if _ok(v) else "—"


def _pct(v, nd: int = 2) -> str:
    return f"{float(v):+.{nd}f}%" if _ok(v) else "—"


def sidebar_brand(tag: str = "NSE / BSE / US EQUITIES") -> None:
    st.sidebar.markdown(
        f'<div class="sb-brand">STOCK<span>·</span>AGENT</div><div class="sb-tag">{_e(tag)}</div>',
        unsafe_allow_html=True,
    )


def hero(title: str, subtitle: str = "", pills: list[tuple[str, str]] | None = None,
         kicker: str = "STOCK·AGENT") -> None:
    pills_html = "".join(T.pill(t, tone) for t, tone in (pills or []))
    st.markdown(
        f'<div class="hero"><div><div class="kick">{_e(kicker)}</div>'
        f'<div class="ttl">{_e(title)}</div><div class="sub">{_e(subtitle)}</div></div>'
        f'<div class="pills">{pills_html}</div></div>',
        unsafe_allow_html=True,
    )


def market_strip(quotes: list[dict]) -> None:
    """Index / macro strip. quotes: [{name, price, chg_pct}]; hides itself if empty."""
    cells = []
    for q in quotes or []:
        ch = q.get("chg_pct")
        col = T.tone_color(T.sign_tone(ch))
        arrow = "▲" if (ch or 0) > 0 else "▼" if (ch or 0) < 0 else "•"
        cells.append(
            f'<div class="mcell"><div class="n">{_e(q["name"])}</div>'
            f'<div class="p">{_px(q.get("price"))}</div>'
            f'<div class="c" style="color:{col}">{arrow} {_pct(ch)}</div></div>'
        )
    if cells:
        st.markdown(f'<div class="mstrip">{"".join(cells)}</div>', unsafe_allow_html=True)


def table_title(text: str, tone: str = "flat") -> None:
    st.markdown(
        f'<div class="tt-title"><i style="background:{T.tone_color(tone)}"></i>{_e(text)}</div>',
        unsafe_allow_html=True,
    )


def movers_table(df: pd.DataFrame) -> None:
    if df is None or df.empty:
        st.markdown('<div class="empty">No data returned.</div>', unsafe_allow_html=True)
        return
    mx = max(float(df["Change %"].abs().max()), 0.01)
    rows = []
    for i, (_, r) in enumerate(df.iterrows(), 1):
        ch = r["Change %"]
        col = T.tone_color(T.sign_tone(ch))
        w = min(46, abs(float(ch)) / mx * 46) if _ok(ch) else 0
        vv = r.get("Vol vs 5d avg")
        vcol = C["amber"] if _ok(vv) and float(vv) >= 1.5 else C["dim"]
        vtxt = f"{float(vv):.1f}x" if _ok(vv) else "—"
        rows.append(
            f'<tr><td><span class="rk">{i:02d}</span><b>{_e(short_sym(r["Symbol"]))}</b></td>'
            f'<td>{_px(r["Price"])}</td>'
            f'<td class="chg" style="color:{col}"><span class="bar" style="width:{w:.0f}px;background:{col}"></span>{_pct(ch)}</td>'
            f'<td style="color:{vcol}">{vtxt}</td></tr>'
        )
    st.markdown(
        '<div class="ttw"><table class="tt"><thead><tr><th>Symbol</th><th>Price</th>'
        '<th>Change</th><th>Vol × avg</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>",
        unsafe_allow_html=True,
    )


def _mini(label: str, score) -> str:
    s = 0.0 if not _ok(score) else max(-100.0, min(100.0, float(score)))
    col = T.tone_color(T.sign_tone(s))
    pct = (s + 100) / 2
    left, width = (50, pct - 50) if s >= 0 else (pct, 50 - pct)
    return (
        f'<div class="mini"><div class="l"><span>{_e(label)}</span><b style="color:{col}">{s:+.0f}</b></div>'
        f'<div class="t"><div class="f" style="left:{left}%;width:{width:.1f}%;background:{col}"></div></div></div>'
    )


def pick_cards(df: pd.DataFrame) -> None:
    """Card grid for ranked picks. Expects the screener.rank() columns."""
    if df is None or df.empty:
        st.markdown('<div class="empty">No stocks passed the screen.</div>', unsafe_allow_html=True)
        return
    cards = []
    for rank, (_, r) in enumerate(df.iterrows(), 1):
        sc = r.get("Score")
        tone = T.sign_tone(sc if _ok(sc) else 0)
        col = T.tone_color(tone)
        day = r.get("Day %")
        dcol = T.tone_color(T.sign_tone(day if _ok(day) else 0))
        mk = r.get("Market", "")
        cur = "₹" if mk == "IN" else "$"
        name = r.get("Name")
        name = "" if (not _ok(name) or str(name) == str(r["Symbol"])) else str(name)
        chips = [f'<span class="chip">{_e(mk)}</span>']
        sector = r.get("Sector")
        if _ok(sector) and str(sector) not in ("—", ""):
            chips.append(f'<span class="chip">{_e(sector)}</span>')
        ana = r.get("Analyst")
        if _ok(ana) and str(ana) not in ("—", "none", ""):
            chips.append(f'<span class="chip">{_e(str(ana).replace("_", " "))}</span>')
        stats = []
        m3 = r.get("3M %")
        if _ok(m3):
            stats.append(f'3M <b style="color:{T.tone_color(T.sign_tone(m3))}">{_pct(m3, 1)}</b>')
        rsi = r.get("RSI")
        if _ok(rsi):
            stats.append(f"RSI <b>{float(rsi):.0f}</b>")
        up = r.get("Upside %")
        if _ok(up):
            stats.append(f'Target <b style="color:{T.tone_color(T.sign_tone(up))}">{_pct(up, 1)}</b>')
        pe = r.get("P/E")
        if _ok(pe):
            stats.append(f"P/E <b>{float(pe):.1f}</b>")
        why = str(r.get("Why") or "").strip(" ·")
        why_html = "<br>".join(_e(p.strip()) for p in why.split(" · ") if p.strip())
        cards.append(
            f'<div class="pcard" style="--accent:{col}">'
            f'<div class="top"><span class="rank">#{rank}</span>'
            f'<div><div class="psym">{_e(short_sym(r["Symbol"]))}</div><div class="pname">{_e(name)}</div></div>'
            f'<div class="pscore"><div class="v" style="color:{col}">{float(sc):+.1f}</div><div class="l">SCORE</div></div></div>'
            f'<div class="meta">{"".join(chips)}</div>'
            f'<div class="px"><span class="big">{cur}{_px(r.get("Price"))}</span>'
            f'<span class="s" style="color:{dcol}">{_pct(day)}</span>'
            f'<span class="s dim" style="color:var(--dim);font-weight:500">{" · ".join(stats)}</span></div>'
            f'<div class="mini3">{_mini("Technical", r.get("Technical"))}{_mini("Fundamental", r.get("Fundamental"))}{_mini("News", r.get("News"))}</div>'
            + (f'<div class="why">{why_html}</div>' if why_html else "")
            + "</div>"
        )
    st.markdown(f'<div class="pgrid">{"".join(cards)}</div>', unsafe_allow_html=True)


def feed(df: pd.DataFrame, time_col: str = "Published", title_col: str = "Headline",
         src_col: str = "Source", link_col: str = "Link", empty: str = "No headlines found.") -> None:
    if df is None or df.empty:
        st.markdown(f'<div class="empty">{_e(empty)}</div>', unsafe_allow_html=True)
        return
    rows = []
    for _, r in df.iterrows():
        t = r[time_col]
        ts = t.strftime("%d %b · %H:%M") if hasattr(t, "strftime") else str(t)
        title = _e(r[title_col])
        link = r.get(link_col)
        link_html = (f'<a href="{_e(link)}" target="_blank" rel="noopener">{title}</a>'
                     if _ok(link) and link else f"<span>{title}</span>")
        rows.append(
            f'<div class="row"><div class="tm">{_e(ts)} UTC</div>'
            f'<div>{link_html}<div class="src">{_e(r.get(src_col, ""))}</div></div></div>'
        )
    st.markdown(f'<div class="feed feed-scroll">{"".join(rows)}</div>', unsafe_allow_html=True)


def insider_table(df: pd.DataFrame, empty: str = "No transactions in this window.") -> None:
    if df is None or df.empty:
        st.markdown(f'<div class="empty">{_e(empty)}</div>', unsafe_allow_html=True)
        return
    rows = []
    for _, r in df.iterrows():
        buy = str(r.get("Type")) == "BUY"
        col = C["up"] if buy else C["down"]
        val = r.get("Value $")
        vtxt = "$" + f"{float(val):,.0f}" if _ok(val) else "—"
        sh = r.get("Shares")
        rows.append(
            f'<tr><td><b>{_e(r["Symbol"])}</b></td>'
            f'<td class="wrap">{_e(r.get("Insider"))}<br><span class="dim">{_e(r.get("Role"))}</span></td>'
            f'<td>{T.pill(str(r.get("Type")), "up" if buy else "down")}</td>'
            f'<td>{f"{float(sh):,.0f}" if _ok(sh) else "—"}</td>'
            f'<td style="color:{col};font-weight:700">{vtxt}</td><td class="dim">{_e(r.get("Date"))}</td></tr>'
        )
    st.markdown(
        '<div class="ttw feed-scroll"><table class="tt"><thead><tr><th>Ticker</th><th>Insider</th><th>Side</th>'
        '<th>Shares</th><th>Value</th><th>Date</th></tr></thead><tbody>' + "".join(rows) + "</tbody></table></div>",
        unsafe_allow_html=True,
    )


def empty_note(text: str) -> None:
    st.markdown(f'<div class="empty">{text}</div>', unsafe_allow_html=True)


def footer(text: str = "Research & education only · Not investment advice · Data delayed · Do your own due diligence") -> None:
    st.markdown(f'<div class="footbar">{_e(text)}</div>', unsafe_allow_html=True)
