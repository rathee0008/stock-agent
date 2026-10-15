"""Chat with the agent: 'Why is Reliance rated Hold?' answered from the app's own numbers."""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent import chat, config, theme as T, ui  # noqa: E402

ui.setup("Ask", "💬")
ui.sidebar_brand()
T.sidebar_head("Context")
inc_watch = st.sidebar.checkbox("Include my watchlist", value=True)
if st.sidebar.button("Clear chat", use_container_width=True):
    st.session_state.pop("chat", None)

ui.hero("Ask the agent",
        "Ask about any stock or the market. Answers use the same scores, drivers and headlines as the Analyze page, "
        "so you can check every number.",
        pills=[("Claude" if config.get("ANTHROPIC_API_KEY") else "Rule-based (no API key)", "amber"), ("Not advice", "flat")])

hist = st.session_state.setdefault("chat", [])
if not hist:
    st.caption("Try: “Why is RELIANCE rated Hold?” · “Compare TCS and INFY” · “Is NVDA overbought?”")
for m in hist:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

q = st.chat_input("Ask about a stock…")
if q:
    hist.append({"role": "user", "content": q})
    with st.chat_message("user"):
        st.markdown(q)
    with st.chat_message("assistant"):
        with st.spinner("Checking the data…"):
            extra = {"watchlist": st.query_params.get("w", "")} if inc_watch else None
            text, src = chat.answer(q, hist[:-1], extra)
        st.markdown(text)
        st.caption("Claude" if src == "claude" else "rule-based answer")
    hist.append({"role": "assistant", "content": text})
ui.footer()
