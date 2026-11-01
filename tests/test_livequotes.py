import pandas as pd

from agent import livequotes as LV, ui


def _frame():
    # Prev closes: A = 100, B = 200
    return pd.DataFrame({"Symbol": ["A", "B"], "Price": [110.0, 190.0], "Change %": [10.0, -5.0]})


def test_apply_live_recomputes_change_against_same_prev_close():
    out = LV.apply_live(_frame(), {"A": 120.0})
    assert out.loc[0, "Price"] == 120.0
    assert abs(out.loc[0, "Change %"] - 20.0) < 1e-9
    assert out.loc[1, "Price"] == 190.0 and out.loc[1, "Change %"] == -5.0  # no live price: untouched


def test_apply_live_keeps_order_and_does_not_mutate_input():
    f = _frame()
    out = LV.apply_live(f, {"B": 210.0})
    assert list(out["Symbol"]) == ["A", "B"]
    assert f.loc[1, "Price"] == 190.0


def test_ticks_zero_on_first_sight_then_signed():
    assert LV.ticks({}, {"A": 10.0}) == {"A": 0.0}
    assert LV.ticks({"A": 10.0, "B": 5.0}, {"A": 11.0, "B": 4.0}) == {"A": 1.0, "B": -1.0}


def test_flash_cls_alternates_so_repeat_ticks_replay():
    assert ui.flash_cls(0.0) == "" and ui.flash_cls(None) == ""
    assert ui.flash_cls(1.0, 0) == "fua" and ui.flash_cls(1.0, 1) == "fub"
    assert ui.flash_cls(-1.0, 0) == "fda" and ui.flash_cls(-1.0, 1) == "fdb"
