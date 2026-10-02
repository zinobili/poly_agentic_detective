"""Stock-side features and event loading from the real config."""

import numpy as np
import pandas as pd
import pytest

from align_synth import ep
from poly_actor.align import events as ev
from poly_actor.align.grid import bar_table, load_sessions, restamp_bars
from poly_actor.align.pipeline import EVENT_BUILDERS, load_config
from poly_actor.align.stocks import bar_log_returns, session_gap_returns, short_day_sessions
from poly_actor.config import CONFIG_DIR


def two_session_bars(drop_last_of_first: bool = False, nan_first_bar_second: bool = False):
    sessions = load_sessions(ep("2025-01-14T00:00:00Z"), ep("2025-01-15T23:00:00Z"))
    sessions = sessions[
        sessions["session"].isin(
            [pd.Timestamp("2025-01-14").date(), pd.Timestamp("2025-01-15").date()]
        )
    ].reset_index(drop=True)
    table = bar_table(sessions)
    raw = pd.DataFrame(
        {
            "ticker": "TLT",
            "ts": pd.to_datetime(table["start_s"], unit="s", utc=True),
            "open": [100.0] * len(table),
            "close": [101.0] * len(table),
            "ohlc_all_nan": False,
        }
    )
    raw.loc[7:, ["open", "close"]] = [105.0, 106.0]  # second session
    if drop_last_of_first:
        raw = raw.drop(index=6)
    if nan_first_bar_second:
        raw.loc[7, ["open", "close", "ohlc_all_nan"]] = [np.nan, np.nan, True]
    stamped, _ = restamp_bars(raw, table)
    return stamped, sessions


def test_bar_return_is_log_close_over_open_and_nan_for_nan_bars():
    stamped, _ = two_session_bars(nan_first_bar_second=True)
    ret = bar_log_returns(stamped.sort_values("start_s").reset_index(drop=True))
    assert ret.iloc[0] == pytest.approx(np.log(101 / 100))
    assert np.isnan(ret.iloc[7])


def test_opening_gap_is_log_of_open_over_previous_close():
    stamped, sessions = two_session_bars()
    gaps = session_gap_returns(stamped, sessions).set_index("session")["gap_ret"]
    assert gaps[pd.Timestamp("2025-01-15").date()] == pytest.approx(np.log(105 / 101))
    assert np.isnan(gaps[pd.Timestamp("2025-01-14").date()])  # no previous session in the frame


def test_opening_gap_is_nan_when_the_previous_close_bar_is_missing():
    stamped, sessions = two_session_bars(drop_last_of_first=True)
    gaps = session_gap_returns(stamped, sessions).set_index("session")["gap_ret"]
    assert np.isnan(gaps[pd.Timestamp("2025-01-15").date()])


def test_opening_gap_is_nan_when_the_first_bar_is_all_nan():
    stamped, sessions = two_session_bars(nan_first_bar_second=True)
    gaps = session_gap_returns(stamped, sessions).set_index("session")["gap_ret"]
    assert np.isnan(gaps[pd.Timestamp("2025-01-15").date()])


def test_short_day_sessions_selects_xnys_rows_for_the_given_tickers_only():
    table = pd.DataFrame(
        {
            "ticker": ["TLT", "SPY", "BTC-USD"],
            "date": [pd.Timestamp("2025-01-14").date()] * 3,
            "kind": ["xnys_session", "xnys_session", "utc_day"],
        }
    )
    assert short_day_sessions(table, ["TLT"]) == {pd.Timestamp("2025-01-14").date()}
    assert short_day_sessions(table, ["BTC-USD"]) == set()


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config(CONFIG_DIR / "pairs.yaml")


@pytest.mark.parametrize("pair_id", sorted(EVENT_BUILDERS))
def test_real_config_events_are_sorted_non_overlapping_and_have_tokens(cfg, pair_id):
    pair = next(p for p in cfg["pairs"] if p["id"] == pair_id)
    events = EVENT_BUILDERS[pair_id](pair)
    assert len(events) >= 2
    starts = [e.use_from_s for e in events]
    assert starts == sorted(starts)
    assert all(a.use_until_s <= b.use_from_s for a, b in zip(events, events[1:], strict=False))
    assert all(e.first_usable_s < e.use_until_s for e in events)


def test_fed_roll_is_one_hour_after_the_decision(cfg):
    pair = next(p for p in cfg["pairs"] if p["id"] == "fed_decision")
    events = ev.fed_events(pair)
    assert all(e.use_until_s - e.event_time_s == 3600 for e in events)
    nov = events[0]  # 2024-11-07 14:00 ET (EST) = 19:00Z
    assert nov.event_time_s == ep("2024-11-07T19:00:00Z")


def test_active_index_uses_half_open_windows_and_minus_one_outside():
    a = ev.Event("A", 100, 200, 100, None)
    b = ev.Event("B", 200, 300, 200, None)
    got = ev.active_index([a, b], np.array([99, 100, 199, 200, 299, 300]))
    assert got.tolist() == [-1, 0, 0, 1, 1, -1]


def test_overlapping_events_are_rejected():
    a = ev.Event("A", 100, 250, 100, None)
    b = ev.Event("B", 200, 300, 200, None)
    with pytest.raises(ValueError, match="overlap"):
        ev._sorted_checked([a, b])
