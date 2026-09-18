"""Terminal-style visual layer for the Streamlit dashboard.

Everything cosmetic lives here: the palette, the injected stylesheet, a shared
Plotly template, and small render helpers (KPI tiles, score meters, status
pills, section rules) that the app uses instead of raw ``st.metric``.

The look is deliberately dense and monospaced — a trading-desk terminal rather
than a consumer app: near-black canvas, hairline panel borders, amber accent,
tabular figures, uppercase letter-spaced labels.
"""

from __future__ import annotations

import html as _html

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------
C = {
    "bg": "#0A0B0D",        # page canvas
    "panel": "#101216",     # cards, tiles
    "panel_hi": "#161920",  # hover / raised
    "line": "#1F2430",      # hairline borders
    "line_hi": "#2A313F",
    "text": "#D5DBE3",      # primary text
    "dim": "#7C8798",       # secondary text
    "faint": "#4E5768",     # labels, axis
    "amber": "#FF9F1C",     # accent / brand
    "amber_dim": "#8A5A14",
    "up": "#0ECB81",        # bullish
    "down": "#F6465D",      # bearish
    "flat": "#7C8798",
    "blue": "#4C8DFF",
    "violet": "#9D7BFF",
    "cyan": "#2FD4D4",
}

MONO = "'JetBrains Mono', 'IBM Plex Mono', 'SF Mono', Menlo, Consolas, monospace"


def tone_color(tone: str) -> str:
    return {"up": C["up"], "down": C["down"], "flat": C["flat"],
            "amber": C["amber"], "dim": C["dim"]}.get(tone, C["text"])


def sign_tone(value: float | None) -> str:
    """Bullish / bearish / neutral tone from a signed number."""
    if value is None:
        return "flat"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------
_CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Inter:wght@400;500;600;700&display=swap');

:root {{
  --bg:{C['bg']}; --panel:{C['panel']}; --panel-hi:{C['panel_hi']};
  --line:{C['line']}; --line-hi:{C['line_hi']}; --text:{C['text']};
  --dim:{C['dim']}; --faint:{C['faint']}; --amber:{C['amber']};
  --up:{C['up']}; --down:{C['down']};
  --mono:{MONO};
}}

html, body, [class*="st-"], .stApp {{
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}}
.stApp {{ background: var(--bg); }}

/* kill Streamlit's default top padding — the terminal bar sits flush */
.block-container {{ padding-top: 1.1rem !important; padding-bottom: 3rem !important;
                    max-width: 1500px; }}
#MainMenu, footer {{ visibility: hidden; }}
header[data-testid="stHeader"] {{ background: transparent; height: 0; }}

/* numbers everywhere are tabular mono */
.mono, [data-testid="stMetricValue"], .stDataFrame, code {{
  font-family: var(--mono); font-variant-numeric: tabular-nums;
}}

/* ---------------- terminal status bar ---------------- */
.term-bar {{
  display:flex; align-items:center; gap:0; flex-wrap:wrap;
  background: linear-gradient(90deg, #12151B 0%, var(--panel) 60%);
  border:1px solid var(--line); border-left:3px solid var(--amber);
  border-radius:3px; padding:.55rem .9rem; margin-bottom:.85rem;
}}
.term-bar .tb-sym {{
  font-family:var(--mono); font-weight:700; font-size:1.05rem; color:var(--text);
  letter-spacing:.06em;
}}
.term-bar .tb-name {{
  color:var(--dim); font-size:.78rem; margin-left:.7rem; letter-spacing:.02em;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis; max-width:30ch;
}}
.term-bar .tb-spacer {{ flex:1 1 auto; }}
.term-bar .tb-cell {{
  font-family:var(--mono); font-size:.76rem; color:var(--dim);
  padding:0 .85rem; border-left:1px solid var(--line); white-space:nowrap;
}}
.term-bar .tb-cell b {{ color:var(--text); font-weight:600; }}
.term-bar .tb-px {{ font-family:var(--mono); font-size:1.0rem; font-weight:700;
                    padding:0 .9rem; }}

/* ---------------- KPI tile ---------------- */
.kpi {{
  background:var(--panel); border:1px solid var(--line); border-radius:3px;
  padding:.6rem .75rem .65rem; height:100%; min-height:5.1rem;
  transition:border-color .15s ease, background .15s ease;
}}
.kpi:hover {{ border-color:var(--line-hi); background:var(--panel-hi); }}
.kpi .k-lab {{
  font-size:.62rem; letter-spacing:.14em; text-transform:uppercase;
  color:var(--faint); font-weight:600; margin-bottom:.3rem;
}}
.kpi .k-val {{
  font-family:var(--mono); font-variant-numeric:tabular-nums;
  font-size:1.28rem; font-weight:600; line-height:1.15; color:var(--text);
}}
.kpi .k-val.sm {{ font-size:1.05rem; }}
.kpi .k-sub {{ font-family:var(--mono); font-size:.7rem; margin-top:.22rem; }}

/* ---------------- score meter ---------------- */
.meter {{
  background:var(--panel); border:1px solid var(--line); border-radius:3px;
  padding:.6rem .8rem .7rem;
}}
.meter .m-top {{ display:flex; justify-content:space-between; align-items:baseline; }}
.meter .m-lab {{
  font-size:.62rem; letter-spacing:.14em; text-transform:uppercase;
  color:var(--faint); font-weight:600;
}}
.meter .m-val {{ font-family:var(--mono); font-size:1.15rem; font-weight:700; }}
.meter .m-track {{
  position:relative; height:6px; margin-top:.5rem; border-radius:2px;
  background:linear-gradient(90deg,
    rgba(246,70,93,.30) 0%, rgba(246,70,93,.12) 35%,
    rgba(124,135,152,.14) 50%,
    rgba(14,203,129,.12) 65%, rgba(14,203,129,.30) 100%);
}}
.meter .m-zero {{
  position:absolute; left:50%; top:-2px; width:1px; height:10px;
  background:var(--line-hi);
}}
.meter .m-fill {{ position:absolute; top:0; height:6px; border-radius:2px; }}
.meter .m-pin {{
  position:absolute; top:-3px; width:2px; height:12px; background:var(--text);
  box-shadow:0 0 6px rgba(255,255,255,.35);
}}
.meter .m-scale {{
  display:flex; justify-content:space-between; font-family:var(--mono);
  font-size:.58rem; color:var(--faint); margin-top:.25rem;
}}

/* ---------------- pills & rules ---------------- */
.pill {{
  display:inline-block; font-family:var(--mono); font-size:.66rem; font-weight:600;
  letter-spacing:.08em; text-transform:uppercase; padding:.16rem .5rem;
  border-radius:2px; border:1px solid currentColor;
}}
.rule {{
  display:flex; align-items:center; gap:.7rem; margin:1.5rem 0 .8rem;
}}
.rule .r-txt {{
  font-size:.68rem; letter-spacing:.18em; text-transform:uppercase;
  color:var(--dim); font-weight:700; white-space:nowrap;
}}
.rule .r-line {{ flex:1; height:1px; background:var(--line); }}

/* ---------------- notes ---------------- */
.note {{
  border:1px solid var(--line); border-left:2px solid var(--amber-dim,{C['amber_dim']});
  background:rgba(255,159,28,.04); border-radius:3px;
  padding:.55rem .8rem; font-size:.76rem; color:var(--dim); line-height:1.5;
}}
.note b {{ color:{C['amber']}; font-weight:600; }}

/* ---------------- tabs ---------------- */
.stTabs [data-baseweb="tab-list"] {{
  gap:0; border-bottom:1px solid var(--line); background:transparent;
}}
.stTabs [data-baseweb="tab"] {{
  height:36px; padding:0 .95rem; background:transparent; border-radius:0;
  font-size:.7rem; font-weight:600; letter-spacing:.11em; text-transform:uppercase;
  color:var(--faint);
}}
.stTabs [data-baseweb="tab"]:hover {{ color:var(--text); background:var(--panel); }}
.stTabs [aria-selected="true"] {{ color:var(--amber) !important; background:var(--panel); }}
.stTabs [data-baseweb="tab-highlight"] {{ background:var(--amber); height:2px; }}
.stTabs [data-baseweb="tab-border"] {{ display:none; }}

/* ---------------- sidebar ---------------- */
section[data-testid="stSidebar"] {{
  background:#0C0E12; border-right:1px solid var(--line);
}}
section[data-testid="stSidebar"] .block-container {{ padding-top:1rem; }}
section[data-testid="stSidebar"] label, section[data-testid="stSidebar"] .stMarkdown p {{
  font-size:.74rem;
}}
.sb-head {{
  font-size:.62rem; letter-spacing:.16em; text-transform:uppercase;
  color:var(--faint); font-weight:700; margin:1.1rem 0 .35rem;
  padding-bottom:.3rem; border-bottom:1px solid var(--line);
}}
.sb-brand {{
  font-family:var(--mono); font-size:1rem; font-weight:700; letter-spacing:.04em;
  color:var(--text);
}}
.sb-brand span {{ color:var(--amber); }}
.sb-tag {{ font-size:.65rem; color:var(--faint); letter-spacing:.06em;
          text-transform:uppercase; margin-top:.15rem; }}

/* buttons */
.stButton button {{
  border-radius:2px; font-size:.72rem; font-weight:700; letter-spacing:.14em;
  text-transform:uppercase; border:1px solid var(--amber); background:var(--amber);
  color:#0A0B0D;
}}
.stButton button:hover {{ background:#FFB347; border-color:#FFB347; color:#0A0B0D; }}

/* inputs */
.stTextInput input, .stSelectbox div[data-baseweb="select"] > div {{
  font-family:var(--mono); font-size:.8rem; border-radius:2px;
  background:var(--panel); border-color:var(--line);
}}

/* dataframes */
.stDataFrame {{ border:1px solid var(--line); border-radius:3px; font-size:.78rem; }}

/* plotly containers get the panel treatment */
[data-testid="stPlotlyChart"] {{
  border:1px solid var(--line); border-radius:3px; background:var(--panel);
  padding:.35rem;
}}

/* narrow viewports: keep figures on one line */
@media (max-width: 1000px) {{
  .kpi {{ padding:.5rem .55rem; min-height:4.5rem; }}
  .kpi .k-val {{ font-size:1.0rem; }}
  .kpi .k-val.sm {{ font-size:.88rem; }}
  .kpi .k-lab {{ font-size:.56rem; letter-spacing:.1em; }}
  .kpi .k-sub {{ font-size:.64rem; }}
  .meter .m-val {{ font-size:1rem; }}
  .term-bar .tb-cell {{ padding:0 .5rem; font-size:.68rem; }}
  .term-bar .tb-px {{ font-size:.9rem; padding:0 .5rem; }}
  .term-bar .tb-name {{ max-width:18ch; }}
  .stTabs [data-baseweb="tab"] {{ padding:0 .55rem; font-size:.64rem; }}
}}
.kpi .k-val {{ white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}

/* headline rows */
.hl {{
  display:flex; gap:.7rem; align-items:flex-start; padding:.55rem .1rem;
  border-bottom:1px solid var(--line);
}}
.hl .hl-dot {{ font-size:.6rem; line-height:1.5rem; }}
.hl a {{ color:var(--text); text-decoration:none; font-size:.86rem; line-height:1.45; }}
.hl a:hover {{ color:var(--amber); }}
.hl .hl-src {{ font-family:var(--mono); font-size:.64rem; color:var(--faint);
              text-transform:uppercase; letter-spacing:.08em; }}
</style>
"""


def inject() -> None:
    """Inject the stylesheet. Call once, right after ``set_page_config``."""
    st.markdown(_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Plotly template
# ---------------------------------------------------------------------------
def register_plotly() -> str:
    """Register and activate the terminal Plotly template. Returns its name."""
    tpl = go.layout.Template()
    tpl.layout = go.Layout(
        paper_bgcolor=C["panel"],
        plot_bgcolor=C["panel"],
        font=dict(family=MONO, size=11, color=C["dim"]),
        title=dict(font=dict(family=MONO, size=12, color=C["text"])),
        margin=dict(l=8, r=8, t=28, b=8),
        xaxis=dict(gridcolor=C["line"], zerolinecolor=C["line"],
                   linecolor=C["line"], tickfont=dict(size=10, color=C["faint"]),
                   showspikes=True, spikecolor=C["faint"], spikethickness=1,
                   spikemode="across", spikedash="dot"),
        yaxis=dict(gridcolor=C["line"], zerolinecolor=C["line"],
                   linecolor=C["line"], tickfont=dict(size=10, color=C["faint"]),
                   showspikes=True, spikecolor=C["faint"], spikethickness=1,
                   spikedash="dot"),
        legend=dict(font=dict(size=10, color=C["dim"]), bgcolor="rgba(0,0,0,0)"),
        hoverlabel=dict(font=dict(family=MONO, size=11), bgcolor=C["panel_hi"],
                        bordercolor=C["line_hi"]),
        colorway=[C["amber"], C["blue"], C["violet"], C["cyan"], C["up"], C["down"]],
    )
    pio.templates["terminal"] = tpl
    pio.templates.default = "terminal"
    return "terminal"


def style_axes(fig: go.Figure) -> go.Figure:
    """Apply the grid/axis treatment to every subplot of an existing figure."""
    fig.update_xaxes(gridcolor=C["line"], linecolor=C["line"],
                     tickfont=dict(size=10, color=C["faint"]), zeroline=False)
    fig.update_yaxes(gridcolor=C["line"], linecolor=C["line"],
                     tickfont=dict(size=10, color=C["faint"]), zeroline=False)
    return fig


# ---------------------------------------------------------------------------
# Render helpers
# ---------------------------------------------------------------------------
def _esc(v) -> str:
    return _html.escape(str(v))


def kpi(container, label: str, value, sub: str | None = None,
        tone: str = "flat", small: bool = False) -> None:
    """A single KPI tile. ``tone`` colours the sub-line (up/down/flat/amber)."""
    sub_html = (
        f'<div class="k-sub" style="color:{tone_color(tone)}">{_esc(sub)}</div>'
        if sub else ""
    )
    container.markdown(
        f'<div class="kpi"><div class="k-lab">{_esc(label)}</div>'
        f'<div class="k-val{" sm" if small else ""}">{_esc(value)}</div>'
        f"{sub_html}</div>",
        unsafe_allow_html=True,
    )


def kpi_row(labels_values, cols=None, container=st) -> None:
    """Render a row of tiles from ``[(label, value, sub, tone), ...]``."""
    cols = cols or container.columns(len(labels_values))
    for col, item in zip(cols, labels_values):
        label, value = item[0], item[1]
        sub = item[2] if len(item) > 2 else None
        tone = item[3] if len(item) > 3 else "flat"
        kpi(col, label, value, sub, tone)


def meter(container, label: str, score: float, lo: float = -100, hi: float = 100) -> None:
    """Horizontal -100..+100 score meter — the terminal answer to a gauge."""
    score = max(lo, min(hi, float(score)))
    pct = (score - lo) / (hi - lo) * 100          # 0..100 position
    colour = tone_color(sign_tone(score))
    left, width = (50, pct - 50) if score >= 0 else (pct, 50 - pct)
    container.markdown(
        f'<div class="meter">'
        f'<div class="m-top"><span class="m-lab">{_esc(label)}</span>'
        f'<span class="m-val" style="color:{colour}">{score:+.0f}</span></div>'
        f'<div class="m-track">'
        f'<div class="m-fill" style="left:{left}%;width:{max(width,0):.2f}%;'
        f'background:{colour};opacity:.85"></div>'
        f'<div class="m-zero"></div>'
        f'<div class="m-pin" style="left:calc({pct:.2f}% - 1px)"></div>'
        f'</div>'
        f'<div class="m-scale"><span>{lo:+.0f}</span><span>0</span>'
        f'<span>{hi:+.0f}</span></div></div>',
        unsafe_allow_html=True,
    )


def pill(text: str, tone: str = "flat") -> str:
    """Inline HTML pill — returns a string so it can be embedded in markdown."""
    return f'<span class="pill" style="color:{tone_color(tone)}">{_esc(text)}</span>'


def rule(text: str, container=st) -> None:
    """A labelled section divider."""
    container.markdown(
        f'<div class="rule"><span class="r-txt">{_esc(text)}</span>'
        f'<span class="r-line"></span></div>',
        unsafe_allow_html=True,
    )


def note(text_html: str, container=st) -> None:
    """A compact amber-keyed note box (accepts inline HTML)."""
    container.markdown(f'<div class="note">{text_html}</div>', unsafe_allow_html=True)


def sidebar_head(text: str) -> None:
    st.sidebar.markdown(f'<div class="sb-head">{_esc(text)}</div>',
                        unsafe_allow_html=True)


def status_bar(symbol: str, name: str, price: str, change: str, tone: str,
               cells: list[tuple[str, str]]) -> None:
    """The top terminal bar: symbol, name, last price, then labelled cells."""
    cell_html = "".join(
        f'<div class="tb-cell">{_esc(k)} <b>{_esc(v)}</b></div>' for k, v in cells
    )
    st.markdown(
        f'<div class="term-bar">'
        f'<span class="tb-sym">{_esc(symbol)}</span>'
        f'<span class="tb-name">{_esc(name)}</span>'
        f'<span class="tb-spacer"></span>'
        f'<span class="tb-px" style="color:{tone_color(tone)}">{_esc(price)}'
        f'<span style="font-size:.74rem;margin-left:.45rem">{_esc(change)}</span></span>'
        f"{cell_html}</div>",
        unsafe_allow_html=True,
    )
