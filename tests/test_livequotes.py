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


def test_rank_moves_up_down_new_and_first_poll():
    assert LV.rank_moves([], ["A", "B"]) == {}
    assert LV.rank_moves(["A", "B", "C"], ["A", "B", "C"]) == {}
    assert LV.rank_moves(["A", "B", "C"], ["C", "A", "D"]) == {"C": 2, "A": -1, "D": "new"}


def test_ticker_html_is_safe_and_drops_unpriced_rows():
    from agent import ticker

    rows = [{"symbol": "A</script>", "label": 'X"<b>', "price": 1.5, "prev": 1.0, "move": 50.0},
            {"symbol": "B", "label": "B", "price": float("nan"), "prev": None, "move": None}]
    h = ticker.build_html(rows)
    assert h.count("</script>") == 1          # the one closing our own script, none smuggled in via data
    assert '"s": "B"' not in h and '"s":"B"' not in h


def test_tile_driver_is_static_and_covers_binance_crypto():
    from agent import livemarkets as LM, ticker

    h = ticker.tile_driver_html()
    assert h == ticker.tile_driver_html()                       # no per-poll data => iframe/socket stay alive
    assert all(f'"{y}": "{b}"' in h for y, b in ticker.BINANCE_STREAMS.items())   # "@trade" is appended in the JS
    assert set(ticker.BINANCE_STREAMS) <= {i.symbol for i in LM.INSTRUMENTS}


def test_crypto_sector_map_and_display_helpers():
    from agent import heatmetrics as H, sectors

    m = sectors.sector_map("CRYPTO")
    assert m["BTC-USD"] == "Bitcoin & store of value" and all(k.endswith("-USD") for k in m)
    assert len(set(m)) == len(m) and len(set(m.values())) >= 4 and "UNI7083-USD" in m
    assert ui.short_sym("BTC-USD") == "BTC" and ui.short_sym("UNI7083-USD") == "UNI" and ui.short_sym("RELIANCE.NS") == "RELIANCE" and ui.short_sym("BRK-B") == "BRK-B"
    assert set(H.SPANS_CRYPTO) == set(H.SPANS)                       # same selector labels for every market
    assert H.fmt_price(77802.0) == "77,802.00" and H.fmt_price(1.2507) == "1.25" and H.fmt_price(0.000012) == "0.00001200" and H.fmt_price(0.5) == "0.5000"


def test_crypto_market_never_closes_for_cache_ttl():
    from agent import cache

    assert cache.state("CRYPTO") == "REGULAR" and cache.ttl_for("CRYPTO") == cache.OPEN_TTL


def test_us_market_state_uses_new_york_time_with_dst(monkeypatch):
    import datetime as dt
    from zoneinfo import ZoneInfo

    from agent import data

    ny = ZoneInfo("America/New_York")
    # 10:00 ET on a summer Monday (EDT, UTC-4) and a winter Monday (EST, UTC-5) must both be REGULAR
    for d in (dt.datetime(2026, 7, 6, 10, 0, tzinfo=ny), dt.datetime(2026, 12, 7, 10, 0, tzinfo=ny)):
        monkeypatch.setattr(data, "_us_now", lambda d=d: d)
        assert data._us_market_state() == "REGULAR"
    monkeypatch.setattr(data, "_us_now", lambda: dt.datetime(2026, 7, 6, 8, 0, tzinfo=ny))
    assert data._us_market_state() == "PRE"


def test_ticker_js_has_cleanup_and_stale_price_guard():
    from agent import ticker

    for h in (ticker.build_html([{"symbol": "BTC-USD", "label": "BTC", "price": 1.0, "prev": 1.0, "move": 0.0}]),
              ticker.tile_driver_html()):
        assert "pagehide" in h
    assert "tape_prev2" in ticker.build_html([{"symbol": "A", "label": "A", "price": 1.0, "prev": 1.0, "move": 0.0}])
