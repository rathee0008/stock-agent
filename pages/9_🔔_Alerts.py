"""Build alert rules, preview which would fire now, send a test, and export alerts.json."""

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import alerts, theme as T, ui  # noqa: E402

ui.setup("Alerts", "🔔")
ui.sidebar_brand()

cfg = alerts.load_config()
ch = alerts.channels_configured()
ui.hero("Alerts",
        "Rules for price levels, big moves, RSI, volume spikes and composite-call flips. They are checked on a schedule "
        "by GitHub Actions and sent to Telegram or email, so they fire even when this page is closed.",
        pills=[("Telegram ✓" if ch["telegram"] else "Telegram not set", "up" if ch["telegram"] else "flat"),
               ("Email ✓" if ch["email"] else "Email not set", "up" if ch["email"] else "flat")])

T.rule("Rules")
df = pd.DataFrame(cfg.get("rules", []) or [{"symbol": "", "market": "IN", "type": "price_above", "value": None, "note": ""}])
for c, d in (("symbol", ""), ("market", "IN"), ("type", "price_above"), ("value", None), ("note", "")):
    if c not in df:
        df[c] = d
edited = st.data_editor(
    df[["symbol", "market", "type", "value", "note"]], num_rows="dynamic", use_container_width=True, hide_index=True,
    column_config={
        "market": st.column_config.SelectboxColumn("market", options=["IN", "US"], required=True),
        "type": st.column_config.SelectboxColumn("type", options=alerts.RULE_TYPES, required=True),
        "value": st.column_config.NumberColumn("value", help="Not needed for composite_flip"),
    },
)
rules = []
for _, r in edited.dropna(subset=["symbol"]).iterrows():
    if str(r["symbol"]).strip():
        try:
            rules.append(alerts.Rule.from_dict({k: (None if pd.isna(v) else v) for k, v in r.items()}))
        except Exception:  # noqa: BLE001
            pass

c1, c2, c3 = st.columns(3)
with c1:
    if st.button("Preview: what would fire now", disabled=not rules):
        with st.spinner("Evaluating…"):
            snaps = alerts.snapshots_for(rules)
            events, _ = alerts.evaluate(rules, snaps, {"fired": {}, "labels": {}})
        if events:
            st.code(alerts.format_events(events))
        else:
            st.info(f"None of the {len(rules)} rules is firing right now ({len(snaps)} symbols checked). "
                    "Composite-flip rules need a previous state, so they only fire on the schedule.")
with c2:
    if st.button("Send a test message", disabled=not any(ch.values())):
        res = alerts.deliver("Stock Agent test", "If you can read this, alerts are wired up.")
        st.success("Delivered via " + ", ".join(k for k, v in res.items() if v)) if any(res.values()) else st.error("Delivery failed; see System status.")
with c3:
    new_cfg = {**cfg, "rules": [dict(symbol=r.symbol, market=r.market, type=r.type, value=r.value, note=r.note) for r in rules]}
    st.download_button("Download alerts.json", json.dumps(new_cfg, indent=2), "alerts.json", "application/json")

st.caption("Streamlit Cloud cannot keep files between restarts, so rules are saved by committing `alerts.json` to the "
           "repo: download it here, replace the file in GitHub, and the next scheduled run uses it.")

T.rule("Setup (one time)")
st.markdown("""
1. **Telegram:** message `@BotFather` → `/newbot` → copy the token. Send your bot any message, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` to read your `chat.id`.
2. In GitHub → *Settings → Secrets and variables → Actions*, add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
   (and optionally `ANTHROPIC_API_KEY`, `SMTP_HOST`, `SMTP_USER`, `SMTP_PASSWORD`, `ALERT_EMAIL_TO`).
3. Run the workflow once from *Actions → Alerts and daily brief → Run workflow → mode: test*.
4. For the same channels on this page, add the same keys to the app's *Secrets* (Manage app → Settings → Secrets).
""")
ui.footer()
