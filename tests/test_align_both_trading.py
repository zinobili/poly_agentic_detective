"""`both_trading` must require a valid change and exclude the upstream-outage hours."""

import pandas as pd

from align_synth import ep, hourly_obs
from poly_actor.align import panel as panel_mod
from poly_actor.align.panel import PairInputs, build_panel
from poly_actor.align.prices import PriceBook
from test_align_panel import END, make_inputs, row_ending

HOUR = 3600


def test_row_with_a_level_but_no_start_level_is_not_both_trading():
    inp = make_inputs()
    pm = hourly_obs("m", ep("2025-01-14T15:00:00Z"), ep(END), lambda t: 0.3)  # first point 15:00:05
    inp = PairInputs(**{**inp.__dict__, "pm_book": PriceBook(pm, 3 * HOUR)})
    row = row_ending(build_panel(inp), "2025-01-14T15:30:00Z")  # the first bar of the day
    assert row["is_session_bar"] and pd.notna(row["signal_level"])
    assert pd.isna(row["signal_change"]) and not row["both_trading"]


def test_outage_rows_are_not_both_trading(monkeypatch):
    monkeypatch.setattr(
        panel_mod, "OUTAGE_WINDOWS_UTC", (("2025-01-15T14:00:00Z", "2025-01-15T17:00:00Z"),)
    )
    out = build_panel(make_inputs())
    row = row_ending(out, "2025-01-15T16:30:00Z")
    assert row["outage_mask"] and row["is_session_bar"] and not row["both_trading"]
    assert row_ending(out, "2025-01-15T19:30:00Z")["both_trading"]
