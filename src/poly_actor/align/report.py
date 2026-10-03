"""Panel summary: sizes and data-quality flag rates per pair (pure; no analysis of returns)."""

from __future__ import annotations

import pandas as pd

from poly_actor.align.consts import BEFORE_USABLE, EDGE_MASS, NO_EVENT, OK, START_UNAVAILABLE


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _age_quantiles(panel: pd.DataFrame) -> dict[str, float | None]:
    """Median and 90th percentile of the Polymarket observation age (seconds) on the rows the
    lead-lag tests use (`both_trading`). Negative ages come from the A22 tolerance only."""
    age = panel.loc[panel["both_trading"], "pm_obs_age_s"].dropna()
    if age.empty:
        return {"median": None, "p90": None, "n": 0}
    return {"median": float(age.median()), "p90": float(age.quantile(0.9)), "n": int(len(age))}


def summarize(panel: pd.DataFrame) -> dict:
    """Counts and rates from one pair's panel.

    Rates use stated denominators: `signal_level_valid_rate` is over rows with an active event
    past its first usable hour; the BTC PAV rate is over hours where both ladders were evaluated;
    the CPI clip rate is over hours where the derived bucket had complete quotes."""
    n = len(panel)
    reason = panel["signal_reason"]
    in_scope = ~reason.isin([NO_EVENT, BEFORE_USABLE])
    session = panel["is_session_bar"]
    out: dict = {
        "rows": n,
        "first_ts_end": str(panel["ts_end"].min()),
        "last_ts_end": str(panel["ts_end"].max()),
        "session_bar_rows": int(session.sum()),
        "both_trading_rows": int(panel["both_trading"].sum()),
        "both_trading_share_of_session_rows": _rate(
            int(panel["both_trading"].sum()), int(session.sum())
        ),
        "rows_with_active_event_and_usable": int(in_scope.sum()),
        "signal_level_valid_rate": _rate(
            int((in_scope & panel["signal_level"].notna()).sum()), int(in_scope.sum())
        ),
        "signal_change_valid_rate": _rate(
            int((in_scope & panel["signal_change"].notna()).sum()), int(in_scope.sum())
        ),
        "signal_reason_counts": {k: int(v) for k, v in reason.value_counts().items()},
        "roll_hour_rows": int(panel["roll_hour"].sum()),
        "event_hour_rows": int(panel["event_hour"].sum()),
        "outage_mask_rows": int(panel["outage_mask"].sum()),
        "short_day_rows": int(panel["short_day"].sum()),
        "clipped_p_gt1_rows": int(panel["clipped_p_gt1"].sum()),
        "median_pm_obs_age_s": None
        if panel["pm_obs_age_s"].isna().all()
        else float(panel["pm_obs_age_s"].median()),
        "pm_obs_age_s_both_trading": _age_quantiles(panel),
        "pm_used_tolerance_share": _rate(
            int((panel["pm_used_tolerance"] & panel["signal_level"].notna()).sum()),
            int(panel["signal_level"].notna().sum()),
        ),
        "overnight_rows": int(panel["is_session_open"].sum()),
        "overnight_pm_change_valid_rows": int(panel["pm_overnight_change"].notna().sum()),
        "ret_nan_rate_on_session_rows": {
            c: _rate(int(panel.loc[session, c].isna().sum()), int(session.sum()))
            for c in panel.columns
            if c.startswith("ret_") and not c.endswith("-USD")
        },
    }
    if "pav_pooled" in panel:
        out.update(_btc_stats(panel, in_scope))
    if "cpi_clip_binding" in panel:
        out.update(_cpi_stats(panel))
    return out


def _btc_stats(panel: pd.DataFrame, in_scope: pd.Series) -> dict:
    """BTC ladder: dropped hours, PAV pooling rate and partial-window use.

    Dropped = in scope (active event past first usable) with no valid level. PAV and partial
    rates are over hours where both ladders had at least one strike."""
    evaluated = (panel["n_up"] > 0) & (panel["n_dip"] > 0)
    dropped = in_scope & panel["signal_level"].isna()
    return {
        "btc_hours_evaluated": int(evaluated.sum()),
        "btc_dropped_hours_in_scope": int(dropped.sum()),
        "btc_dropped_rate_in_scope": _rate(int(dropped.sum()), int(in_scope.sum())),
        "btc_pav_pooling_rate": _rate(
            int(panel.loc[evaluated, "pav_pooled"].sum()), int(evaluated.sum())
        ),
        "btc_hours_with_partial_strikes_rate": _rate(
            int((evaluated & (panel["n_partial"] > 0)).sum()), int(evaluated.sum())
        ),
    }


def _cpi_stats(panel: pd.DataFrame) -> dict:
    """CPI: how often max(0, sum(plus) - sum(minus)) binds, over hours where the derived
    bucket had complete quotes (valid, or dropped only for edge mass)."""
    scoped = panel["cpi_has_derived"] & panel["signal_reason"].isin(
        [OK, EDGE_MASS, START_UNAVAILABLE]
    )
    return {
        "cpi_edge_strict_ok_share_of_valid_levels": _rate(
            int((panel["edge_mass_strict_ok"] & panel["signal_level"].notna()).sum()),
            int(panel["signal_level"].notna().sum()),
        ),
        "cpi_hours_with_derived_bucket": int(scoped.sum()),
        "cpi_clip_binding_rate": _rate(
            int(panel.loc[scoped, "cpi_clip_binding"].sum()), int(scoped.sum())
        ),
    }


def format_report(summaries: dict[str, dict]) -> str:
    """Plain-text report, one block per pair."""
    lines: list[str] = []
    for pair_id, s in summaries.items():
        lines.append(f"== {pair_id}")
        for key, value in s.items():
            lines.append(f"   {key}: {value}")
    return "\n".join(lines)
