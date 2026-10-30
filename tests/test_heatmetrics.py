import pandas as pd

from agent import heatmetrics as H
from agent import liveheat


def _df():
    return pd.DataFrame({
        "Symbol": ["A", "B", "C", "D"], "Sector": ["X", "X", "Y", "Y"], "Price": [10.0, 20.0, 30.0, 40.0],
        "Change %": [1.0, -2.0, 3.0, -4.0], "MCap": [1000.0, 10.0, None, 500.0],
        "Value": [5.0, 5.0, 5.0, 5.0],
    })


def test_weights_equal_and_fallback():
    df = _df()
    assert H.weights(df, "Equal") == [1.0] * 4
    assert H.weights(df.drop(columns=["MCap"]), "Market cap") == [1.0] * 4   # no data -> equal
    assert H.weights(df.assign(MCap=None), "Market cap") == [1.0] * 4


def test_weights_cap_floor_and_missing():
    w = H.weights(_df(), "Market cap")
    med = 500.0                              # median of the known caps
    assert w[0] == 1000.0 and w[3] == 500.0
    assert w[2] == med                       # missing -> median
    assert w[1] == med * 0.25                # tiny cap floored to 25% of the median


def test_scale_limit():
    s = pd.Series([0.5, -1.0, 8.0])
    assert H.scale_limit(s, "±5%") == 5.0
    assert H.scale_limit(s, "Auto") >= 2.0


def test_flags():
    assert H.flags(2.5, 99, True, False) == "⚡▲"
    assert H.flags(1.0, 1, False, True) == "▼"
    assert H.flags(None, None, False, False) == ""
    assert H.flags(float("nan"), None, False, False) == ""


def test_tile_color_symmetry_and_dim():
    up, dn = H.PALETTES["Green / red"]
    assert H.tile_color(0, 3, up, dn) == "rgb(27,30,36)"
    assert H.tile_color(3, 3, up, dn) == "rgb(25,210,122)"
    assert H.tile_color(-9, 3, up, dn) == "rgb(255,59,78)"       # saturates at the limit
    assert H.tile_color(3, 3, up, dn, dim=True) != H.tile_color(3, 3, up, dn)


def test_rel_strength_and_parse():
    assert H.rel_strength(pd.Series({"X": 1.5}), 0.5)["X"] == 1.0
    assert H.parse_tickers("reliance, tcs.ns,\nAAPL ,") == {"RELIANCE", "TCS", "AAPL"}
    assert H.fmt_cap(2.9e12, "$") == "$2.9T" and H.fmt_cap(None, "$") == "—"


def test_cap_weighted_layout_gives_bigger_tile():
    df = _df()
    tiles = [t for t in liveheat.layout(df, [100.0, 1.0, 1.0, 1.0]) if t["sym"]]
    area = {t["sym"]: t["w"] * t["h"] for t in tiles}
    assert area["A"] > 5 * area["B"]


def test_build_html_payload():
    df = _df().assign(MCapTxt="$1T", VolX=2.5, Pos52=90.0, Flags="⚡", Change1D=1.0, Y=["A", "B", "C", "D"],
                      Trend=[[1.0, 2.0]] * 4)
    html = liveheat.build_html(df, None, 3.0, weights=[4, 1, 1, 1], highlight={"A"}, min_move=1.0, size_label="Market cap")
    assert '"hl": ["A"]' in html and '"minMove": 1.0' in html and '"mc": "$1T"' in html
