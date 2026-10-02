"""Panel assembly on synthetic data: end-stamped returns, overnight gaps, flags, no look-ahead."""

import numpy as np
import pandas as pd
import pytest

from align_synth import bars_for, ep, hourly_obs, obs, rows_for, token_event
from poly_actor.align.evaluate import evaluate_recession
from poly_actor.align.grid import bar_table, load_sessions, restamp_bars
from poly_actor.align.panel import PairInputs, build_panel, outage_mask, overnight_pm_change
from poly_actor.align.prices import PriceBook

HOUR = 3600
START, END = "2025-01-13T00:00:00Z", "2025-01-17T00:00:00Z"  # Mon..Thu, EST, no holidays
TUE_OPEN = ep("2025-01-14T14:30:00Z")


def open_price(start_s: int) -> float:
    return 100.0 + (start_s - ep(START)) / HOUR * 0.01  # distinct per bar


def close_price(start_s: int) -> float:
    return open_price(start_s) + 0.5


def make_inputs(
    pm_end: str = END, short_days: frozenset = frozenset(), spot: pd.DataFrame | None = None
) -> PairInputs:
    sessions = load_sessions(ep(START), ep(END))
    table = bar_table(sessions)
    raw = bars_for("TLT", sessions, open_price, close_price)
    stamped, _ = restamp_bars(raw, table)
    rows = rows_for(START, END, sessions)
    pm = hourly_obs("m", ep(START), ep(pm_end), lambda t: 0.2 + 0.0001 * ((t - ep(START)) // HOUR))
    spot_obs = spot if spot is not None else obs("BTC-USD", [], [])
    return PairInputs(
        pair_id="synthetic",
        tickers=["TLT", "BTC-USD"],
        events=[token_event("E", "m", START, END, START)],
        evaluator=evaluate_recession,
        pm_book=PriceBook(pm, 3 * HOUR),
        spot_book=PriceBook(spot_obs, 3 * HOUR, clip=False),
        rows=rows,
        sessions=sessions,
        bars={"TLT": stamped},
        short_days=set(short_days),
    )


def row_ending(panel: pd.DataFrame, iso: str) -> pd.Series:
    return panel[panel["ts_end"] == pd.Timestamp(iso)].iloc[0]


def test_bar_return_is_stamped_at_the_bar_end():
    panel = build_panel(make_inputs())
    start = ep("2025-01-14T14:30:00Z")  # the 09:30 ET bar
    expected = np.log(close_price(start) / open_price(start))
    assert row_ending(panel, "2025-01-14T15:30:00Z")["ret_TLT"] == pytest.approx(expected)
    # the same bar must NOT appear on the row ending at its start time
    assert np.isnan(row_ending(panel, "2025-01-14T14:30:00Z")["ret_TLT"])


def test_returns_are_nan_outside_session_bars():
    panel = build_panel(make_inputs())
    assert panel.loc[~panel["is_session_bar"], "ret_TLT"].isna().all()
    assert panel.loc[panel["is_session_bar"], "ret_TLT"].notna().all()


def test_both_trading_needs_a_session_bar_and_a_valid_signal_change():
    panel = build_panel(make_inputs())
    assert row_ending(panel, "2025-01-14T16:30:00Z")["both_trading"]
    assert not row_ending(panel, "2025-01-14T08:00:00Z")["both_trading"]  # overnight


def test_both_trading_is_false_when_the_signal_goes_stale():
    panel = build_panel(make_inputs(pm_end="2025-01-14T12:00:00Z"))
    assert not row_ending(panel, "2025-01-15T16:30:00Z")["both_trading"]
    assert row_ending(panel, "2025-01-15T16:30:00Z")["signal_reason"] == "missing_quote"


def test_opening_gap_and_overnight_pm_change_sit_on_the_first_bar_row():
    panel = build_panel(make_inputs())
    open_row = row_ending(panel, "2025-01-15T15:30:00Z")  # Wed's first bar
    prev_close = close_price(ep("2025-01-14T20:30:00Z"))  # Tue's last bar
    wed_open = open_price(ep("2025-01-15T14:30:00Z"))
    assert open_row["is_session_open"]
    assert open_row["overnight_gap_TLT"] == pytest.approx(np.log(wed_open / prev_close))
    between = panel[(panel["ts_end"] > pd.Timestamp("2025-01-14T21:00:00Z"))]
    between = between[between["ts_end"] <= pd.Timestamp("2025-01-15T14:30:00Z")]
    assert open_row["pm_overnight_change"] == pytest.approx(between["signal_change"].sum())
    assert open_row["pm_overnight_n_missing"] == 0
    assert panel.loc[~panel["is_session_open"], "overnight_gap_TLT"].isna().all()


def test_no_overnight_gap_for_the_first_session_in_the_panel():
    panel = build_panel(make_inputs())
    first_open = panel[panel["is_session_open"]].iloc[0]
    assert np.isnan(first_open["pm_overnight_change"])


def test_overnight_change_is_nan_when_any_hour_in_between_is_missing():
    is_bar = np.array([True, False, False, True])
    is_open = np.array([False, False, False, True])
    total, missing = overnight_pm_change(is_bar, is_open, np.array([0.0, 0.1, np.nan, 0.0]))
    assert np.isnan(total[3]) and missing[3] == 1
    total, missing = overnight_pm_change(is_bar, is_open, np.array([0.0, 0.1, 0.2, 0.0]))
    assert total[3] == pytest.approx(0.3) and missing[3] == 0


def test_short_day_flag_marks_only_that_session():
    flagged = pd.Timestamp("2025-01-15").date()
    panel = build_panel(make_inputs(short_days=frozenset({flagged})))
    assert panel.loc[panel["short_day"], "session"].eq(flagged).all()
    assert panel["short_day"].sum() == 7


def test_outage_mask_covers_the_known_upstream_outage_window():
    start = np.array([ep("2025-10-29T08:00:00Z"), ep("2025-10-29T13:00:00Z")])
    end = np.array([ep("2025-10-29T09:00:00Z"), ep("2025-10-29T14:00:00Z")])
    assert outage_mask(start, end).tolist() == [False, True]  # (08,09] ends at the outage start
    before = outage_mask(
        np.array([ep("2025-10-29T14:00:00Z")]), np.array([ep("2025-10-29T15:00:00Z")])
    )
    assert before.tolist() == [False]


def test_btc_spot_return_uses_only_closes_known_at_each_end():
    bars_start = list(range(ep(START), ep(END), HOUR))
    closes = [100.0 + i for i in range(len(bars_start))]
    # spot bars are start-stamped; their close is known one hour later
    spot = obs("BTC-USD", [s + HOUR for s in bars_start], closes)
    panel = build_panel(make_inputs(spot=spot))
    row = row_ending(panel, "2025-01-15T10:00:00Z")
    k = (ep("2025-01-15T10:00:00Z") - ep(START)) // HOUR  # bar index ending at 10:00
    assert row["ret_BTC-USD"] == pytest.approx(np.log(closes[k - 1] / closes[k - 2]))
    # at a :30 stamp the latest known close is the one from the previous full hour
    half = row_ending(panel, "2025-01-15T15:30:00Z")
    k2 = (ep("2025-01-15T15:30:00Z") - ep(START)) // HOUR
    assert half["ret_BTC-USD"] == pytest.approx(np.log(closes[k2 - 1] / closes[k2 - 2]))


def test_future_pm_and_bar_data_cannot_change_earlier_rows():
    full = make_inputs()
    cut = ep("2025-01-15T12:00:00Z")
    tampered = make_inputs()
    pm = hourly_obs(
        "m",
        ep(START),
        ep(END),
        lambda t: 0.2 + 0.0001 * ((t - ep(START)) // HOUR) if t <= cut else 0.9,
    )
    tampered = PairInputs(**{**tampered.__dict__, "pm_book": PriceBook(pm, 3 * HOUR)})
    bars = tampered.bars["TLT"].copy()
    bars.loc[bars["start_s"] > cut, ["open", "close"]] = 1.0
    tampered = PairInputs(**{**tampered.__dict__, "bars": {"TLT": bars}})
    a, b = build_panel(full), build_panel(tampered)
    keep = a["ts_end"] <= pd.Timestamp("2025-01-15T12:00:00Z")
    for col in ("ret_TLT", "signal_level", "overnight_gap_TLT"):
        np.testing.assert_array_equal(a.loc[keep, col].to_numpy(), b.loc[keep, col].to_numpy())
    assert not np.array_equal(a["ret_TLT"].to_numpy(), b["ret_TLT"].to_numpy(), equal_nan=True)


def test_panel_records_the_observation_stamp_age_and_tolerance_flag():
    tol = 53
    inp = make_inputs()
    pm = hourly_obs("m", ep(START), ep(END), lambda t: 0.3, offset_s=40)  # stamped 40 s after
    inp = PairInputs(**{**inp.__dict__, "pm_book": PriceBook(pm, 3 * HOUR, tolerance_s=tol)})
    panel = build_panel(inp)
    row = row_ending(panel, "2025-01-15T03:00:00Z")
    assert row["pm_used_tolerance"] and row["pm_obs_age_s"] == -40
    assert row["pm_obs_ts"] == pd.Timestamp("2025-01-15T03:00:40Z")
    strict = PairInputs(**{**inp.__dict__, "pm_book": PriceBook(pm, 3 * HOUR)})
    srow = row_ending(build_panel(strict), "2025-01-15T03:00:00Z")
    assert not srow["pm_used_tolerance"] and srow["pm_obs_age_s"] == 3600 - 40
