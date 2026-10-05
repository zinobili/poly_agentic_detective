"""Flag-rate summary on small hand-made panels."""

import numpy as np
import pandas as pd
import pytest

from poly_actor.align.report import format_report, summarize


def base_panel(reasons: list[str]) -> pd.DataFrame:
    n = len(reasons)
    levels = [1.0 if r in ("ok", "start_unavailable") else np.nan for r in reasons]
    return pd.DataFrame(
        {
            "ts_end": pd.date_range("2025-01-01", periods=n, freq="h", tz="UTC"),
            "is_session_bar": [True] * n,
            "is_session_open": [False] * n,
            "both_trading": [r == "ok" for r in reasons],
            "signal_reason": reasons,
            "signal_level": levels,
            "signal_change": [0.1 if r == "ok" else np.nan for r in reasons],
            "roll_hour": [False] * n,
            "event_hour": [False] * n,
            "outage_mask": [False] * n,
            "short_day": [False] * n,
            "clipped_p_gt1": [False] * n,
            "pm_obs_age_s": [3600.0] * n,
            "pm_overnight_change": [np.nan] * n,
            "ret_TLT": [0.0] * n,
        }
    )


def test_rates_use_in_scope_rows_as_denominator():
    panel = base_panel(["ok", "ok", "missing_quote", "no_active_event", "before_first_usable"])
    out = summarize(panel)
    assert out["rows_with_active_event_and_usable"] == 3
    assert out["signal_level_valid_rate"] == pytest.approx(2 / 3, abs=1e-6)
    assert out["both_trading_rows"] == 2 and out["median_pm_obs_age_s"] == 3600.0


def test_start_unavailable_rows_keep_a_valid_level_but_no_change():
    out = summarize(base_panel(["ok", "start_unavailable"]))
    assert out["signal_level_valid_rate"] == 1.0
    assert out["signal_change_valid_rate"] == 0.5


def test_btc_stats_report_drops_pav_and_partial_rates():
    panel = base_panel(["ok", "not_bracketed", "ok", "no_rungs"])
    panel["pav_pooled"] = [True, False, False, False]
    panel["n_up"], panel["n_dip"] = [3, 3, 3, 0], [3, 3, 3, 3]
    panel["n_partial"] = [1, 0, 0, 0]
    out = summarize(panel)
    assert out["btc_hours_evaluated"] == 3
    assert out["btc_dropped_hours_in_scope"] == 2
    assert out["btc_pav_pooling_rate"] == pytest.approx(1 / 3, abs=1e-6)
    assert out["btc_hours_with_partial_strikes_rate"] == pytest.approx(1 / 3, abs=1e-6)


def test_cpi_clip_rate_counts_edge_dropped_hours_with_complete_quotes():
    panel = base_panel(["ok", "edge_mass_gt_max", "missing_quote", "ok"])
    panel["cpi_has_derived"] = [True, True, True, False]
    panel["cpi_clip_binding"] = [True, False, False, False]
    panel["edge_mass_strict_ok"] = [True, False, False, True]
    out = summarize(panel)
    assert out["cpi_hours_with_derived_bucket"] == 2
    assert out["cpi_clip_binding_rate"] == 0.5


def test_empty_denominators_give_none_not_an_error():
    out = summarize(base_panel(["no_active_event"]))
    assert out["signal_level_valid_rate"] is None


def test_format_report_has_one_block_per_pair():
    text = format_report({"a": {"rows": 1}, "b": {"rows": 2}})
    assert "== a" in text and "== b" in text and "rows: 2" in text
