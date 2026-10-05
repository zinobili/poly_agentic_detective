"""Shared builders for the dashboard tests (no Streamlit import)."""

from __future__ import annotations

from poly_actor.dashboard.contract import CheckRow, PairResults, XCorr

LAGS = tuple(range(-12, 13))


def xcorr(ticker: str = "TLT", band: float = 0.1, **bars: float) -> XCorr:
    """XCorr over lags -12..12; ``bars`` maps 'm3'/'p2' (lag -3/+2) to an r value, rest 0."""
    r = {lag: 0.0 for lag in LAGS}
    for key, value in bars.items():
        r[int(key[1:]) * (-1 if key[0] == "m" else 1)] = value
    return XCorr(ticker, LAGS, tuple(r[lag] for lag in LAGS), band)


def results(pair_id: str = "fed_decision", **slots) -> PairResults:
    return PairResults(pair_id=pair_id, **slots)


def granger_row(status: str = "Passed") -> CheckRow:
    return CheckRow(
        name="Granger",
        status=status,
        plain="Odds help predict prices beyond their own past",
        technical="Granger causality, BH-adjusted p = 0.012",
    )
