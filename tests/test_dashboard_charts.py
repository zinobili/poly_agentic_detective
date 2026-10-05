"""Figure builders: no dual axis, line breaks across gaps, values match the panel."""

from pathlib import Path

import numpy as np
import pandas as pd

from dashboard_helpers import xcorr
from poly_actor.dashboard import charts
from poly_actor.dashboard.contract import EventStudy
from poly_actor.dashboard.load import load_panel

PANEL = load_panel(Path(__file__).parent / "fixtures" / "dashboard_clean", "fed_decision")


def _utc(ts) -> pd.Timestamp:
    return pd.Timestamp(ts).tz_convert("UTC").tz_localize(None)


def test_chart3_is_two_stacked_panels_without_secondary_axis():
    fig = charts.raw_data_figure(PANEL, "fed_decision", "TLT")
    assert len(fig.data) == 2
    assert fig.data[0].yaxis == "y" and fig.data[1].yaxis == "y2"
    assert fig.layout.yaxis2.overlaying is None
    assert fig.layout.xaxis.matches == "x2"  # shared timeline
    assert fig.layout.xaxis2.title.text == "Time (UTC)"
    assert fig.layout.yaxis.domain[0] > fig.layout.yaxis2.domain[1]  # signal on top


def _trace_at(trace, ts) -> float:
    x = pd.to_datetime(pd.Series(trace.x))
    return float(np.asarray(trace.y)[x == _utc(ts)][0])


def test_chart3_values_match_the_panel_at_three_timestamps():
    fig = charts.raw_data_figure(PANEL, "fed_decision", "SPY")
    bars = PANEL[PANEL["is_session_bar"] & PANEL["ret_SPY"].notna()].reset_index(drop=True)
    running, index_at = 0.0, {}
    for _, row in bars.iterrows():
        gap = row["overnight_gap_SPY"]
        running += row["ret_SPY"] + (0.0 if np.isnan(gap) else gap)
        index_at[row["ts_end"]] = 100.0 * np.exp(running)
    for ts in (bars["ts_end"].iloc[0], bars["ts_end"].iloc[17], bars["ts_end"].iloc[-1]):
        row = PANEL[PANEL["ts_end"] == ts].iloc[0]
        assert _trace_at(fig.data[0], ts) == row["signal_level"] / 100.0  # bp -> pts
        assert abs(_trace_at(fig.data[1], ts) - index_at[ts]) < 1e-9


def test_signal_units_per_pair():
    s = pd.DataFrame({"ts_end": pd.to_datetime(["2025-01-01"], utc=True), "signal_level": [0.25]})
    assert charts.signal_series(s, "us_recession")["y"].iloc[0] == 25.0
    s["signal_level"] = [np.log(90_000.0)]
    assert abs(charts.signal_series(s, "bitcoin_monthly_ladder")["y"].iloc[0] - 90.0) < 1e-9


def test_gap_over_six_hours_breaks_the_line():
    x = pd.Series(pd.to_datetime(["2025-03-14 20:00", "2025-03-14 21:00", "2025-03-17 14:30"]))
    out = charts.break_gaps(x, pd.Series([1.0, 2.0, 3.0]))
    assert out["y"].isna().sum() == 1
    nan_x = out.loc[out["y"].isna(), "x"].iloc[0]
    assert pd.Timestamp("2025-03-14 21:00") < nan_x < pd.Timestamp("2025-03-17 14:30")


def test_gap_of_exactly_six_hours_is_not_broken():
    x = pd.Series(pd.to_datetime(["2025-03-14 10:00", "2025-03-14 16:00"]))
    assert charts.break_gaps(x, pd.Series([1.0, 2.0]))["y"].isna().sum() == 0


def test_chart3_has_breaks_over_the_weekend_in_real_panel():
    fig = charts.raw_data_figure(PANEL, "fed_decision", "TLT")
    stock_y = np.asarray(fig.data[1].y, dtype=float)
    assert np.isnan(stock_y).sum() >= 4  # nights and the weekend inside the fixture week


def test_xcorr_figure_colours_bars_by_noise_zone():
    xc = xcorr("TLT", band=0.1, p2=0.2)
    fig = charts.xcorr_figure(xc)
    colours = list(fig.data[0].marker.color)
    assert colours.count(charts.POLY_COLOR) == 1 and colours[xc.lags.index(2)] == charts.POLY_COLOR
    assert "positive: odds moved first" in fig.layout.xaxis.title.text


def test_event_study_figure_has_band_and_mean():
    es = EventStudy("TLT", (0, 1), (0.1, 0.2), (0.0, 0.1), (0.2, 0.3), ())
    fig = charts.event_study_figure(es)
    assert [t.name for t in fig.data] == [None, "Plausible range", "Average move"]
    assert fig.layout.yaxis.title.text == "TLT move (%)"
