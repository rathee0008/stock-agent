"""Run every Streamlit page headless against synthetic market data (no network).

    python tests/smoke_pages.py            # all pages
    python tests/smoke_pages.py Portfolio  # name filter
"""

import glob
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.pop("ANTHROPIC_API_KEY", None)
os.environ["STOCK_AGENT_CACHE"] = "/tmp/stock_agent_smoke_cache"

from tests import fake_market  # noqa: E402

fake_market.install()

from streamlit.testing.v1 import AppTest  # noqa: E402

pages = [str(ROOT / "app.py")] + sorted(glob.glob(str(ROOT / "pages" / "*.py")))
flt = sys.argv[1].lower() if len(sys.argv) > 1 else ""
failed = 0
for p in pages:
    name = Path(p).name
    if flt and flt not in name.lower():
        continue
    t0 = time.time()
    at = AppTest.from_file(p, default_timeout=180)
    if name == "app.py":
        at.query_params["s"], at.query_params["m"] = "RELIANCE", "IN"
    at.run()
    exc = [e.value for e in at.exception]
    errs = [e.value for e in at.error]
    status = "OK " if not exc else "FAIL"
    failed += bool(exc)
    print(f"{status} {name:42s} {time.time() - t0:5.1f}s  exceptions={len(exc)} st.error={len(errs)}")
    for e in exc[:3]:
        print("     !!", str(e)[:400])
    for e in errs[:2]:
        print("     err:", str(e)[:200])
sys.exit(1 if failed else 0)
