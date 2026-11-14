"""Amendment A1: after a token's close time its price is its last traded price (flag `resolved`);
before the close the freshness cap is unchanged. Hand-off step 9 examples."""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from poly_actor.core.ingest.common import to_epoch
from poly_actor.studies.election import panel

HOUR = 3600
CLOSE_MKT = to_epoch("2026-11-04T10:53:59Z")  # Gamma closedTime of p_sen
LAST_TRADE = to_epoch("2026-11-04T10:54:00Z")


def pts(*stamps, fid=10):
    return pd.DataFrame({"t": [s for s, _ in stamps], "p": [p for _, p in stamps], "fidelity": fid})


def sess(*rows):
    return pd.DataFrame(rows, columns=["session", "open_s", "close_s", "early"])


def _book(max_age, fid=None, closes=None):
    d = pts((to_epoch("2026-11-03T20:59:20Z"), 0.745), (LAST_TRADE, 0.9995), fid=fid or 10)
    return panel.build_book({"p_sen": d}, max_age, fid, closes=closes)


def test_session_after_close_takes_last_traded_price_and_is_flagged():
    c3, c4 = to_epoch("2026-11-03T21:00:00Z"), to_epoch("2026-11-04T21:00:00Z")
    s = sess((date(2026, 11, 3), c3 - 23400, c3, False), (date(2026, 11, 4), c4 - 23400, c4, False))
    out = panel.build_odds_daily(_book(6 * HOUR, closes={"p_sen": CLOSE_MKT}), ["p_sen"], s)
    assert out["p"].tolist() == [0.745, 0.9995]
    assert out["resolved"].tolist() == [False, True]
    assert out["dp"].iloc[1] == pytest.approx(0.2545)
    assert out["age_s"].iloc[1] == c4 - LAST_TRADE  # honest age, ~10 h


def test_without_the_rule_the_same_session_is_missing():
    c4 = to_epoch("2026-11-04T21:00:00Z")
    out = panel.build_odds_daily(
        _book(6 * HOUR), ["p_sen"], sess((date(2026, 11, 4), c4 - 23400, c4, False))
    )
    assert np.isnan(out["p"].iloc[0]) and not out["resolved"].iloc[0]


def test_session_before_close_keeps_the_6h_cap():
    # a reading 7 h old at a close BEFORE the market close stays missing even with the rule on
    c = to_epoch("2026-10-30T20:00:00Z")
    b = panel.build_book(
        {"p_sen": pts((c - 7 * HOUR, 0.70))}, 6 * HOUR, closes={"p_sen": CLOSE_MKT}
    )
    out = panel.build_odds_daily(b, ["p_sen"], sess((date(2026, 10, 30), c - 23400, c, False)))
    assert np.isnan(out["p"].iloc[0]) and not out["resolved"].iloc[0]


def test_resolved_price_never_uses_a_point_after_the_instant():
    # instant after the close but before the last trade: last trade is not visible yet
    b = _book(6 * HOUR, closes={"p_sen": CLOSE_MKT})
    q = b.asof("p_sen", np.array([CLOSE_MKT + 0, LAST_TRADE + 1]))
    assert q.p.tolist() == [0.745, 0.9995]


def test_open_market_close_none_is_never_resolved():
    b = _book(6 * HOUR, closes={"p_sen": None})
    assert not b.resolved("p_sen", np.array([LAST_TRADE + 10 * HOUR])).any()
    assert np.isnan(b.asof("p_sen", np.array([LAST_TRADE + 10 * HOUR])).p[0])


def test_hourly_bars_after_close_have_dp_zero():
    s = sess(
        (
            date(2026, 11, 4),
            to_epoch("2026-11-04T14:30:00Z"),
            to_epoch("2026-11-04T21:00:00Z"),
            False,
        )
    )
    out = panel.build_odds_hourly(_book(1800, closes={"p_sen": CLOSE_MKT}), ["p_sen"], s)
    assert out["resolved"].all() and (out["p"] == 0.9995).all()
    assert (out["dp"].dropna() == 0).all() and out["dp"].notna().sum() == len(out) - 1


def test_night_bars_after_close_dp_zero_and_flagged(cfg_night):
    fut, cfg = cfg_night
    b = panel.build_book(
        {"p_sen": pts((LAST_TRADE - 300, 0.98), (LAST_TRADE, 0.9995), fid=1)},
        600,
        fid=1,
        closes={"p_sen": CLOSE_MKT},
    )
    out = panel.build_night(fut, b, ["p_sen"], cfg)
    late = out[out["bar_end_ts"] >= pd.Timestamp("2026-11-04T11:10:00Z")]
    assert len(late) and late["res_p_sen"].all() and (late["p_sen"] == 0.9995).all()
    assert (late["dp_sen"].dropna() == 0).all()


@pytest.fixture
def cfg_night():
    from poly_actor.studies.election.config import load_config

    cfg = load_config()
    start = pd.date_range("2026-11-04T10:30:00Z", "2026-11-04T11:30:00Z", freq="5min")
    bars = pd.DataFrame({"ts": start, "open": 100.0, "close": 100.5})
    return {"NQ=F": bars}, cfg
