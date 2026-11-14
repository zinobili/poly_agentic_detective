"""Circular-shift placebo helper shared by every study."""

from __future__ import annotations

import numpy as np


def admissible_shifts(n: int, min_shift: int) -> np.ndarray:
    """Every circular shift j of a length-n series with min(j, n - j) >= min_shift.

    Keeping shifts away from 0 (and from n) stops a placebo series from still overlapping the
    real one through autocorrelation."""
    j = np.arange(1, n)
    return j[np.minimum(j, n - j) >= min_shift]
