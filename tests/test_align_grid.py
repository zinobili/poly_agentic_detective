"""Bar re-stamping to bar end, early closes, DST days and the tiled row grid."""

import numpy as np
import pandas as pd

from align_synth import bars_for, ep, rows_for
from poly_actor.align.grid import bar_table, load_sessions, restamp_bars, session_bar_edges


def hhmm(seconds: int) -> str:
    return pd.Timestamp(seconds, unit="s", tz="UTC").strftime("%H:%M")


def edges_for(day: str) -> list[tuple[str, str]]:
    sessions = load_sessions(ep(f"{day}T00:00:00Z"), ep(f"{day}T23:59:00Z"))
    row = sessions[sessions["session"] == pd.Timestamp(day).date()].iloc[0]
    return [(hhmm(a), hhmm(b)) for a, b in session_bar_edges(row.open_s, row.close_s, row.early)]


def test_regular_winter_day_bars_end_on_the_half_hour_and_at_the_close():
    # 2025-01-15 is EST: 09:30 ET = 14:30Z, close 16:00 ET = 21:00Z
    assert edges_for("2025-01-15") == [
        ("14:30", "15:30"),
        ("15:30", "16:30"),
        ("16:30", "17:30"),
        ("17:30", "18:30"),
        ("18:30", "19:30"),
        ("19:30", "20:30"),
        ("20:30", "21:00"),
    ]


def test_summer_day_is_one_hour_earlier_in_utc():
    # 2025-07-15 is EDT: 09:30 ET = 13:30Z
    got = edges_for("2025-07-15")
    assert got[0] == ("13:30", "14:30") and got[-1] == ("19:30", "20:00")


def test_early_close_eleven_thirty_bar_runs_to_one_pm():
    # 2025-11-28 closes 13:00 ET = 18:00Z; Yahoo has no 12:30 bar
    assert edges_for("2025-11-28") == [
        ("14:30", "15:30"),
        ("15:30", "16:30"),
        ("16:30", "18:00"),
    ]


def test_dst_switch_week_uses_the_new_offset_from_monday():
    # US DST began Sunday 2025-03-09: Friday open 14:30Z, Monday open 13:30Z
    assert edges_for("2025-03-07")[0][0] == "14:30"
    assert edges_for("2025-03-10")[0][0] == "13:30"


def one_day(day: str) -> pd.DataFrame:
    sessions = load_sessions(ep(f"{day}T00:00:00Z"), ep(f"{day}T23:00:00Z"))
    return sessions[sessions["session"] == pd.Timestamp(day).date()]


def test_restamp_maps_start_to_end_and_flags_unexpected_starts():
    sessions = one_day("2025-01-15")
    table = bar_table(sessions)
    bars = bars_for("TLT", sessions, lambda s: 100.0, lambda s: 101.0)
    odd = bars.iloc[[0]].copy()
    odd["ts"] = odd["ts"] + pd.Timedelta(minutes=7)  # not an expected bar start
    stamped, unmatched = restamp_bars(pd.concat([bars, odd]), table)
    assert len(stamped) == 7 and len(unmatched) == 1
    ordered = stamped.sort_values("start_s")
    assert ordered.iloc[0]["end_s"] - ordered.iloc[0]["start_s"] == 3600
    assert ordered.iloc[-1]["end_s"] - ordered.iloc[-1]["start_s"] == 1800  # 15:30 -> 16:00 close


def test_restamp_of_no_bars_is_empty_not_an_error():
    sessions = one_day("2025-01-15")
    empty = bars_for("TLT", sessions, lambda s: 1.0, lambda s: 1.0).iloc[:0]
    stamped, unmatched = restamp_bars(empty, bar_table(sessions))
    assert stamped.empty and unmatched.empty


def test_row_grid_tiles_without_overlap_and_session_rows_are_the_bars():
    sessions = load_sessions(ep("2025-01-15T00:00:00Z"), ep("2025-01-17T00:00:00Z"))
    rows = rows_for("2025-01-15T00:00:00Z", "2025-01-17T00:00:00Z", sessions)
    assert (rows["start_s"].to_numpy()[1:] == rows["end_s"].to_numpy()[:-1]).all()
    day = rows[rows["session"] == pd.Timestamp("2025-01-15").date()]
    assert len(day) == 7 and day["is_session_bar"].all()
    assert day["is_session_open"].sum() == 1
    assert day[day["is_session_open"]].iloc[0]["start_s"] == ep("2025-01-15T14:30:00Z")


def test_stub_row_ends_at_the_session_open_and_is_not_a_session_bar():
    sessions = load_sessions(ep("2025-01-15T00:00:00Z"), ep("2025-01-16T00:00:00Z"))
    rows = rows_for("2025-01-15T00:00:00Z", "2025-01-16T00:00:00Z", sessions)
    stub = rows[rows["end_s"] == ep("2025-01-15T14:30:00Z")].iloc[0]
    assert stub["window_minutes"] == 30 and not stub["is_session_bar"]


def test_weekend_is_covered_by_whole_utc_hour_rows():
    sessions = load_sessions(ep("2025-01-10T00:00:00Z"), ep("2025-01-14T00:00:00Z"))
    rows = rows_for("2025-01-11T00:00:00Z", "2025-01-12T00:00:00Z", sessions)
    assert len(rows) == 24 and not rows["is_session_bar"].any()
    assert set(np.diff(rows["end_s"])) == {3600}
