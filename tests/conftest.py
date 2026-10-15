import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def make_ohlcv(n=600, seed=0, drift=0.0004, vol=0.015, start=100.0, end="2026-10-14"):
    rng = np.random.default_rng(seed)
    rets = rng.normal(drift, vol, n)
    close = start * np.exp(np.cumsum(rets))
    idx = pd.bdate_range(end=end, periods=n)
    hi = close * (1 + np.abs(rng.normal(0, 0.006, n)))
    lo = close * (1 - np.abs(rng.normal(0, 0.006, n)))
    opn = np.r_[close[0], close[:-1]]
    vol_ = rng.integers(8e5, 2e6, n).astype(float)
    return pd.DataFrame({"Open": opn, "High": hi, "Low": lo, "Close": close, "Volume": vol_}, index=idx)


@pytest.fixture
def ohlcv():
    return make_ohlcv()


@pytest.fixture
def universe_hist():
    return {f"S{i}.NS": make_ohlcv(seed=i, drift=0.0002 + 0.00005 * (i % 5)) for i in range(16)}
