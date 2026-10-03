"""Splicing across rolls and the mandatory no-look-ahead properties of the signal."""

import numpy as np
import pandas as pd
import pytest

from align_synth import ep, hourly_obs, obs, rows_for, token_event
from poly_actor.align.evaluate import evaluate_recession
from poly_actor.align.grid import load_sessions
from poly_actor.align.prices import PriceBook
from poly_actor.align.splice import spliced_signal

HOUR = 3600
SAT = "2025-01-11T00:00:00Z"  # a weekend: every row is a whole UTC hour
MON = "2025-01-13T00:00:00Z"


def weekend_rows() -> pd.DataFrame:
    sessions = load_sessions(ep(SAT), ep(MON))
    return rows_for(SAT, MON, sessions)


def book_of(*frames: pd.DataFrame) -> PriceBook:
    return PriceBook(pd.concat(frames), 3 * HOUR, clip=True)


def stepped(key: str, base: str, first: float, step: float) -> pd.DataFrame:
    """Observations stamped base+5s, +1h+5s, ... with value first + step*k."""
    start = ep(base)
    times = list(range(start + 5, start + 48 * HOUR, HOUR))
    return obs(key, times, [first + step * k for k in range(len(times))])


def run(events, book, rows):
    return spliced_signal(
        events,
        evaluate_recession,
        book,
        book,
        rows["start_s"].to_numpy(),
        rows["end_s"].to_numpy(),
    )


def test_change_inside_one_event_is_the_difference_of_its_own_levels():
    rows = weekend_rows()
    events = [token_event("A", "a", "2025-01-11T00:00:00Z", "2025-01-13T00:00:00Z")]
    out = run(events, book_of(stepped("a", SAT, 0.10, 0.005)), rows)
    changes = out["signal_change"].dropna().to_numpy()
    assert changes == pytest.approx(np.full(len(changes), 0.005))


def test_levels_of_two_events_are_never_differenced_across_a_roll():
    rows = weekend_rows()
    roll = "2025-01-12T12:00:00Z"
    events = [
        token_event("A", "a", SAT, roll),
        token_event("B", "b", roll, MON, first_usable="2025-01-10T00:00:00Z"),
    ]
    book = book_of(stepped("a", SAT, 0.10, 0.005), stepped("b", SAT, 0.40, 0.01))
    out = run(events, book, rows)
    after = out[out["event_id"] == "B"]
    assert after["signal_change"].dropna().to_numpy() == pytest.approx(0.01)
    assert out["signal_change"].abs().max() < 0.02  # a 0.3 level jump would show here


def test_row_ending_at_the_roll_is_the_old_event_and_the_next_row_is_flagged():
    rows = weekend_rows()
    roll = "2025-01-12T12:00:00Z"
    events = [token_event("A", "a", SAT, roll), token_event("B", "b", roll, MON, SAT)]
    book = book_of(stepped("a", SAT, 0.1, 0.005), stepped("b", SAT, 0.4, 0.01))
    out = run(events, book, rows)
    flagged = rows.loc[out["roll_hour"].to_numpy(), ["start_s", "end_s"]]
    assert flagged["start_s"].tolist() == [ep(roll)]
    ending_at_roll = out[rows["end_s"].to_numpy() == ep(roll)].iloc[0]
    assert not ending_at_roll["roll_hour"] and ending_at_roll["event_id"] == "A"
    assert ending_at_roll["signal_change"] == pytest.approx(0.005)  # old event's last full hour
    starting = out[rows["start_s"].to_numpy() == ep(roll)].iloc[0]
    assert starting["roll_hour"] and starting["event_id"] == "B"


def test_roll_inside_a_window_uses_the_new_events_own_change_and_flags_it():
    rows = weekend_rows()
    roll = "2025-01-12T12:30:00Z"  # inside the (12:00, 13:00] row
    events = [token_event("A", "a", SAT, roll), token_event("B", "b", roll, MON, SAT)]
    book = book_of(stepped("a", SAT, 0.1, 0.005), stepped("b", SAT, 0.4, 0.01))
    out = run(events, book, rows)
    row = out[rows["end_s"].to_numpy() == ep("2025-01-12T13:00:00Z")].iloc[0]
    assert row["roll_hour"] and row["event_id"] == "B"
    assert row["signal_change"] == pytest.approx(0.01)


def test_new_event_without_a_start_level_gives_nan_change_not_a_cross_event_difference():
    rows = weekend_rows()
    roll = "2025-01-12T12:00:00Z"
    events = [
        token_event("A", "a", SAT, roll),
        token_event("B", "b", roll, MON, first_usable="2025-01-12T12:30:00Z"),
    ]
    book = book_of(stepped("a", SAT, 0.1, 0.005), stepped("b", SAT, 0.4, 0.01))
    out = run(events, book, rows)
    window = out[rows["start_s"].to_numpy() == ep(roll)].iloc[0]
    assert np.isnan(window["signal_change"])
    assert window["signal_reason"] == "start_unavailable"


def test_hours_without_an_active_event_have_no_signal():
    rows = weekend_rows()
    events = [token_event("A", "a", "2025-01-12T00:00:00Z", MON, SAT)]
    out = run(events, book_of(stepped("a", SAT, 0.1, 0.005)), rows)
    before = out[rows["end_s"].to_numpy() < ep("2025-01-12T00:00:00Z")]
    assert (before["signal_reason"] == "no_active_event").all()
    assert before["signal_level"].isna().all() and before["event_id"].isna().all()


def test_event_hour_flags_the_window_containing_the_official_time():
    rows = weekend_rows()
    events = [token_event("A", "a", SAT, MON)]  # event_time = use_until - 1h = 23:00Z Sunday
    out = run(events, book_of(stepped("a", SAT, 0.1, 0.005)), rows)
    hit = rows.loc[out["event_hour"].to_numpy(), "end_s"].tolist()
    assert hit == [ep("2025-01-12T23:00:00Z")]


def test_no_forward_fill_across_a_long_gap():
    rows = weekend_rows()
    events = [token_event("A", "a", SAT, MON)]
    frame = hourly_obs("a", ep(SAT), ep("2025-01-11T12:00:00Z"), lambda t: 0.3)
    out = run(events, book_of(frame), rows)
    late = out[
        (rows["end_s"].to_numpy() > ep("2025-01-11T16:00:00Z"))
        & (rows["end_s"].to_numpy() < ep(MON))
    ]
    assert late["signal_level"].isna().all()
    assert (late["signal_reason"] == "missing_quote").all()


def test_future_observations_cannot_change_any_earlier_row():
    """Mandatory no-look-ahead check: rows ending at or before T are identical whether the
    observations after T are the real ones, garbage, or missing."""
    rows = weekend_rows()
    events = [token_event("A", "a", SAT, MON)]
    rng = np.random.default_rng(7)
    base = hourly_obs("a", ep(SAT), ep(MON), lambda t: float(rng.uniform(0.1, 0.9)))
    cut = ep("2025-01-12T06:00:00Z")
    garbage = base.copy()
    garbage.loc[garbage["t"] > cut, "p"] = 0.999
    truncated = base[base["t"] <= cut]
    results = [run(events, book_of(f), rows) for f in (base, garbage, truncated)]
    keep = rows["end_s"].to_numpy() <= cut
    for other in results[1:]:
        for col in ("signal_level", "signal_change"):
            np.testing.assert_array_equal(
                results[0].loc[keep, col].to_numpy(), other.loc[keep, col].to_numpy()
            )
    assert not np.array_equal(
        results[0]["signal_level"].to_numpy(), results[1]["signal_level"].to_numpy()
    )  # the garbage is visible after the cut, so the comparison above is not vacuous
