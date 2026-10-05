"""Pre-registered signal formulas (pure, vectorised). Input rows are instants; NaN = no quote.

Reasons are strings (see `consts`): "ok" when the level is valid, else why it was dropped.
"""

from __future__ import annotations

import numpy as np

from poly_actor.align.consts import (
    CPI_EDGE_MASS_MAX,
    EDGE_MASS,
    FED_OTHER_MASS_MAX,
    MISSING_BUCKET,
    OK,
    OTHER_MASS,
    ZERO_MASS,
)


def _reason(*conditions_and_labels: tuple[np.ndarray, str]) -> np.ndarray:
    """First matching label per row, "ok" otherwise (later pairs have lower priority)."""
    n = len(conditions_and_labels[0][0])
    out = np.full(n, OK, dtype=object)
    for cond, label in reversed(conditions_and_labels):
        out[cond] = label
    return out


def fed_expected_change(
    p: np.ndarray, deltas: np.ndarray, other: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """sum(p_i * delta_i) / sum(p_i) over named buckets. p: (n, k) clipped probabilities.

    `other` is the catch-all "another level" bucket price (n,) or None; it is excluded from
    the mean and used only as `other_mass`: hours with other_mass > 0.25 are dropped.
    A bucket without a quote makes the hour invalid (never filled with 0).
    Returns (level_bp, other_mass, reason)."""
    missing = np.isnan(p).any(axis=1)
    mass = np.nansum(p, axis=1)
    other_mass = np.full(len(p), np.nan) if other is None else other
    other_missing = np.zeros(len(p), dtype=bool) if other is None else np.isnan(other)
    with np.errstate(invalid="ignore", divide="ignore"):
        level = np.where(mass > 0, np.nansum(p * deltas, axis=1) / mass, np.nan)
    reason = _reason(
        (missing | other_missing, MISSING_BUCKET),
        (mass == 0, ZERO_MASS),
        (other_mass > FED_OTHER_MASS_MAX, OTHER_MASS),
    )
    return np.where(reason == OK, level, np.nan), other_mass, reason


def derived_bucket(plus: np.ndarray, minus: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Derived CPI bucket p = max(0, sum(plus) - sum(minus)); plus/minus are (n, m) arrays.

    Returns (p, clip_binding) where clip_binding is True when sum(plus) < sum(minus)."""
    diff = plus.sum(axis=1) - minus.sum(axis=1)
    return np.maximum(0.0, diff), diff < 0


def cpi_implied(
    p: np.ndarray, centers: np.ndarray, is_edge: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """sum(p_i * c_i) / sum(p_i) over merged buckets; hours with edge_mass > 0.25 are dropped (A23).

    p: (n, k); edge_mass = (p of edge buckets) / sum(p). Returns (level, edge_mass, reason)."""
    missing = np.isnan(p).any(axis=1)
    mass = np.nansum(p, axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        edge_mass = np.where(mass > 0, np.nansum(p[:, is_edge], axis=1) / mass, np.nan)
        level = np.where(mass > 0, np.nansum(p * centers, axis=1) / mass, np.nan)
    reason = _reason(
        (missing, MISSING_BUCKET),
        (mass == 0, ZERO_MASS),
        (edge_mass > CPI_EDGE_MASS_MAX, EDGE_MASS),
    )
    return np.where(reason == OK, level, np.nan), edge_mass, reason


def log_ladder_level(k_up: np.ndarray, k_dn: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """ln(ladder_level) = (ln K_up* + ln K_dn*) / 2 and half_width = (ln K_up* - ln K_dn*) / 2,
    where ladder_level = exp(ln(ladder_level)) is the pre-registered level. Vectorised; NaN in,
    NaN out."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return (np.log(k_up) + np.log(k_dn)) / 2, (np.log(k_up) - np.log(k_dn)) / 2


def skew(k_up: np.ndarray, k_dn: np.ndarray, spot: np.ndarray) -> np.ndarray:
    """skew = ln K_up* + ln K_dn* - 2 ln S_t (positive: upside rung further from spot)."""
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.log(k_up) + np.log(k_dn) - 2 * np.log(spot)
