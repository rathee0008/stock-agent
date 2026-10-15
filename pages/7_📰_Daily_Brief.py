"""Auto-generated pre-market / post-market brief that covers your watchlist and portfolio."""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import alerts, briefing, cache, config, theme as T, ui, universe  # noqa: E402

ui.setup("Daily Brief", "📰")
ui.sidebar_brand()
T.sidebar_head("Brief")
mkt = st.sidebar.radio("Market", ["India", "United States"], label_visibility="collapsed")
M = "IN" if mkt == "India" else "US"
kind = st.sidebar.radio("Type", ["Auto", "Pre-market", "Post-market"], horizontal=True)
kind_v = briefing.session_kind(M) if kind == "Auto" else ("pre" if kind.startswith("Pre") else "post")
use_llm = st.sidebar.checkbox("Claude-written", value=bool(config.get("ANTHROPIC_API_KEY")))
T.sidebar_head("Cover")
default_w = st.query_params.get("w", "RELIANCE, TCS" if M == "IN" else "AAPL, NVDA")
wl_raw = st.sidebar.text_area("Watchlist (comma-separated)", value=default_w, height=80)
pf_raw = st.sidebar.text_area("Holdings (SYMBOL qty cost per line)", value=st.query_params.get("p", "").replace(";", "\n"), height=90)
if st.sidebar.button("Refresh", use_container_width=True):
    st.cache_data.clear()

IN_SET = set(universe.IN)


def _res(tok: str) -> str:
    t = tok.strip().upper()
    if not t or "." in t or t.startswith("^"):
        return t
    return f"{t}.NS" if t in IN_SET else t


watch = [s for s in (_res(t) for t in wl_raw.replace("\n", ",").split(",")) if s]
watch = [s for s in watch if s.endswith(".NS") == (M == "IN")][:15]
holdings = {}
for line in pf_raw.splitlines():
    p = line.replace(",", " ").split()
    try:
        holdings[_res(p[0])] = (float(p[1]), float(p[2]))
    except (IndexError, ValueError):
        continue
holdings = {k: v for k, v in holdings.items() if k.endswith(".NS") == (M == "IN")}


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _brief(m, kind_, w, h, llm, b):
    ctx = briefing.build_context(m, watch=list(w), holdings=dict(h) or None)
    return briefing.generate(ctx, kind_, use_llm=llm)


ui.hero("Daily Brief",
        "A short market note built from live index moves, sector rotation, top movers and deal headlines, "
        "plus your own watchlist and holdings.",
        pills=[("Pre-market" if kind_v == "pre" else "Post-market", "amber"), ("Not advice", "flat")])
with st.spinner("Building the brief…"):
    text, src = _brief(M, kind_v, tuple(watch), tuple(sorted(holdings.items())), use_llm, cache.bucket(M, 3))
st.markdown(text)
st.caption("Written by " + ("Claude" if src == "claude" else "a rule-based template (no API key, or the call failed)"))

st.divider()
ch = alerts.channels_configured()
c1, c2 = st.columns(2)
with c1:
    if st.button("Send this brief now", disabled=not any(ch.values())):
        res = alerts.deliver(f"{M} {kind_v}-market brief", text)
        st.success("Sent: " + ", ".join(k for k, v in res.items() if v) if any(res.values()) else "Could not send; see System status.")
with c2:
    st.caption("Telegram: " + ("✓ configured" if ch["telegram"] else "not set") + " · Email: "
               + ("✓ configured" if ch["email"] else "not set")
               + ". Scheduled delivery runs from GitHub Actions (see README → Alerts).")
ui.footer()
