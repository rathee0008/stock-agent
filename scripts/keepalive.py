#!/usr/bin/env python3
"""Open the Streamlit app in a headless browser so Community Cloud treats it as active."""

import os
import sys

from playwright.sync_api import sync_playwright

url = os.environ.get("APP_URL") or "https://rathee0008-stock-agent.streamlit.app"

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    try:
        page.get_by_role("button", name="Yes, get this app back up!").click(timeout=8_000)
        print("App was asleep: pressed the wake-up button.")
        page.wait_for_timeout(45_000)
    except Exception:  # noqa: BLE001 - button absent means the app is already awake
        page.wait_for_timeout(15_000)
    body = page.inner_text("body")[:200].replace("\n", " ")
    print("Loaded:", page.title(), "|", body)
    browser.close()
sys.exit(0)
