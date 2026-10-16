"""Daily Lists: the saved results of every Screener preset and the Top 20, from the twice-daily job."""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import theme as T, ui  # noqa: E402
from agent.presets import PRESETS, slug  # noqa: E402

ui.setup("Daily Lists", "📅")
ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "data" / "screener"
LISTS = {"Top 20 (best overall)": "top20", **{n: slug(n) for n in PRESETS}}
_ORDER = {"morning": 0, "run": 1, "evening": 2}


def _runs() -> list[str]:
    """Saved run folders, newest first (date, then morning < evening)."""
    d = BASE / "history"
    if not d.exists():
        return []
    names = [p.name for p in d.iterdir() if p.is_dir() and (p / "_summary.md").exists()]
    return sorted(names, key=lambda n: (n.split("_")[0], _ORDER.get(n.split("_")[-1], 1)), reverse=True)


@st.cache_data(ttl=900, show_spinner=False)
def _read(run: str, key: str) -> pd.DataFrame:
    f = BASE / "history" / run / f"{key}.csv"
    return pd.read_csv(f) if f.exists() else pd.DataFrame()


ui.sidebar_brand()
runs = _runs()
T.sidebar_head("Saved run")
run = st.sidebar.selectbox("Run", runs, label_visibility="collapsed", disabled=not runs) if runs else None
T.sidebar_head("List")
choice = st.sidebar.selectbox("List", list(LISTS), label_visibility="collapsed")
if st.sidebar.button("Reload", use_container_width=True):
    st.cache_data.clear()

ui.hero("Daily Lists",
        "Results of all 12 Screener presets and the Top 20, saved automatically after each market session "
        "(about 8:30 AM and 4:30 PM IST). Browse any past run and see what entered or left a list.",
        pills=[("Saved snapshots", "amber"), ("Not advice", "flat")])

if not run:
    ui.empty_note("<b>No saved runs yet.</b> The twice-daily GitHub job writes them; run it once from the repo's Actions tab.")
    ui.footer()
    st.stop()

df = _read(run, LISTS[choice])
prev_run = runs[runs.index(run) + 1] if runs.index(run) + 1 < len(runs) else None
prev = _read(prev_run, LISTS[choice]) if prev_run else pd.DataFrame()

now = set(df["Symbol"]) if "Symbol" in df else set()
before = set(prev["Symbol"]) if "Symbol" in prev else set()
k = st.columns(4)
T.kpi(k[0], "Run", run.replace("_", " "), "IST date, session", "amber", small=True)
T.kpi(k[1], "Matches", f"{len(df)}", choice, "flat", small=True)
T.kpi(k[2], "New since previous", f"{len(now - before)}" if prev_run else "—", prev_run.replace("_", " ") if prev_run else "no earlier run", "up")
T.kpi(k[3], "Dropped", f"{len(before - now)}" if prev_run else "—", "left the list", "down")
st.markdown("<div style='height:.6rem'></div>", unsafe_allow_html=True)

if df.empty:
    ui.empty_note("<b>No stocks matched</b> this list in the selected run.")
else:
    view = df.copy()
    if prev_run:
        view.insert(0, "Change", ["NEW" if s not in before else "" for s in view["Symbol"]])
    view.index += 1
    st.dataframe(view, use_container_width=True, height=620,
                 column_config={"Score": st.column_config.ProgressColumn("Score", min_value=-100, max_value=100, format="%.1f"),
                                **{c: st.column_config.NumberColumn(c, format="%.1f") for c in
                                   ["Day %", "3M %", "P/E", "ROE %", "Rev growth %", "RSI", "Upside %", "Price"] if c in view}})
    st.download_button("Download this list (CSV)", df.to_csv(index=False).encode("utf-8"),
                       file_name=f"{run}_{LISTS[choice]}.csv", mime="text/csv")
    if prev_run and before - now:
        st.caption("Dropped since the previous run: " + ", ".join(sorted(s.replace(".NS", "") for s in before - now)))

T.rule("All lists in this run")
summary = (BASE / "history" / run / "_summary.md").read_text(encoding="utf-8")
rows = [[c.strip() for c in ln.strip().strip("|").split("|")] for ln in summary.splitlines() if ln.startswith("|")][2:]
st.dataframe(pd.DataFrame(rows, columns=["List", "Matches", "Top 5 by score"]), use_container_width=True, hide_index=True)
st.caption("Snapshots are rule-based screens on delayed public data, saved for research. Not investment advice.")
ui.footer()
