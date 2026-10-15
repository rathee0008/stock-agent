"""One place to read settings: Streamlit secrets first, then environment / .env.

Works outside Streamlit too (CLI, GitHub Actions) because every lookup is wrapped:
a missing secrets file or a non-Streamlit process simply falls through to os.environ.
"""

from __future__ import annotations

import os

try:  # optional: load a local .env when python-dotenv is installed
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # noqa: BLE001
    pass


def get(key: str, default: str | None = None) -> str | None:
    """Return ``key`` from st.secrets, else os.environ, else ``default``."""
    try:
        import streamlit as st

        if key in st.secrets:
            val = st.secrets[key]
            if val not in (None, ""):
                return str(val)
    except Exception:  # noqa: BLE001 - no secrets file / not running under Streamlit
        pass
    val = os.environ.get(key)
    return val if val not in (None, "") else default


def has(key: str) -> bool:
    return get(key) is not None
