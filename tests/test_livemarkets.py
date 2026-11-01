from datetime import datetime, timezone

import pandas as pd
import pytest

from agent import livemarkets as LM

NOW = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
PRICE = LM.Instrument("US", "TEST", "TST")
YIELD = LM.Instrument("Rates", "10Y", "^TNX", "yield", 3)


def _daily(vals, end="2026-11-01"):
    return pd.Series(vals, index=pd.bdate_range(end=end, periods=len(vals)))


def _intra(vals, start, tz="UTC"):
    return pd.Series(vals, index=pd.date_range(start, periods=len(vals), freq="min", tz=tz))


def test_previous_close_is_prior_session_not_today():
    daily = _daily([100.0, 101.0, 102.0], end="2026-11-02")  # last daily row = today's partial bar
    intra = _intra([102.0, 103.0, 104.0], "2026-11-02 09:50")  # last bar 09:52, "now" is 10:00
    row = LM.build_row(PRICE, daily, intra, NOW)
    assert row["price"] == 104.0
    assert row["prev"] == 101.0
    assert row["move"] == pytest.approx((104 / 101 - 1) * 100)
    assert row["live"] is True


def test_closed_market_flagged_stale():
    daily = _daily([100.0, 101.0], end="2026-10-29")
    intra = _intra([101.5, 101.8], "2026-10-30 09:00")
    row = LM.build_row(PRICE, daily, intra, NOW)
    assert row["live"] is False
    assert row["age_min"] > LM.LIVE_MAX_AGE_MIN


def test_yield_move_in_basis_points():
    daily = _daily([4.10, 4.20], end="2026-10-30")
    intra = _intra([4.25, 4.30], "2026-11-02 09:00")
    row = LM.build_row(YIELD, daily, intra, NOW)
    assert row["unit"] == "bps"
    assert row["move"] == pytest.approx(10.0)  # 4.30 - 4.20 = 0.10 pp = 10 bps


def test_yield_quoted_times_ten_is_rescaled():
    daily = _daily([41.0, 42.0], end="2026-10-30")
    intra = _intra([42.5, 43.0], "2026-11-02 09:00")
    row = LM.build_row(YIELD, daily, intra, NOW)
    assert row["price"] == pytest.approx(4.30)
    assert row["move"] == pytest.approx(10.0)


def test_daily_only_fallback_and_empty():
    row = LM.build_row(PRICE, _daily([100.0, 110.0]), pd.Series(dtype=float), NOW)
    assert row["price"] == 110.0 and row["move"] == pytest.approx(10.0)
    assert LM.build_row(PRICE, None, None, NOW) is None


def test_every_group_has_instruments():
    groups = {i.group for i in LM.INSTRUMENTS}
    assert set(LM.GROUPS) == groups
    assert len({i.symbol for i in LM.INSTRUMENTS}) == len(LM.INSTRUMENTS)
