"""Last-observation-at-or-before lookups (the only resampling rule used in alignment).

An observation stamped at time `t` is usable at instant `x` only if `t <= x + tolerance_s`
(tolerance 0 = strict no-look-ahead; the Polymarket book uses the A22 stamp tolerance, a bounded
documented deviation), and only if `x - t <= max_age_s` (no forward-fill across long gaps).
Instants and stamps are epoch seconds (UTC, int64).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from poly_actor.align.consts import CLIP_HI, CLIP_LO


@dataclass(frozen=True)
class Quotes:
    """Result of an as-of lookup, aligned with the requested instants.

    p: value (clipped to [0, 1] when the book clips), NaN where unavailable.
    age_s: instant minus observation stamp, NaN where unavailable. Negative when the
        observation was stamped after the instant (only possible through the tolerance).
    clipped: True where the raw value was outside [0, 1] and had to be clipped."""

    p: np.ndarray
    age_s: np.ndarray
    clipped: np.ndarray

    @property
    def used_tolerance(self) -> np.ndarray:
        """True where the observation used was stamped after the instant."""
        return np.nan_to_num(self.age_s, nan=0.0) < 0


class PriceBook:
    """Per-key (token or ticker) sorted observations with as-of lookup.

    `obs` columns: key, t (epoch seconds, UTC), p, and optionally fidelity. When the same
    (key, t) appears at several fidelities the finest (lowest) fidelity wins. Fidelity-1 probe
    records with no rows contribute nothing: an absent observation is "no data", never a price."""

    def __init__(self, obs: pd.DataFrame, max_age_s: int, clip: bool = True, tolerance_s: int = 0):
        self.max_age_s = max_age_s
        self.tolerance_s = tolerance_s
        self.clip = clip
        frame = obs.copy()
        if "fidelity" not in frame:
            frame["fidelity"] = 0
        frame = frame.dropna(subset=["p"]).sort_values(["key", "t", "fidelity"], kind="stable")
        frame = frame.drop_duplicates(subset=["key", "t"], keep="first")
        self._series: dict[str, tuple[np.ndarray, np.ndarray]] = {
            str(k): (g["t"].to_numpy(dtype="int64"), g["p"].to_numpy(dtype="float64"))
            for k, g in frame.groupby("key", sort=False)
        }

    def has(self, key: str) -> bool:
        return key in self._series

    def asof(self, key: str, instants: np.ndarray) -> Quotes:
        """Latest observation stamped at or before instant + tolerance, within the age cap."""
        n = len(instants)
        series = self._series.get(key)
        if series is None or n == 0:
            return Quotes(np.full(n, np.nan), np.full(n, np.nan), np.zeros(n, dtype=bool))
        t, p = series
        idx = np.searchsorted(t, instants + self.tolerance_s, side="right") - 1
        found = idx >= 0
        safe = np.where(found, idx, 0)
        age = np.where(found, instants - t[safe], np.iinfo(np.int64).max)
        valid = found & (age <= self.max_age_s)
        raw = np.where(valid, p[safe], np.nan)
        clipped = valid & ((raw < CLIP_LO) | (raw > CLIP_HI)) if self.clip else np.zeros(n, bool)
        value = np.clip(raw, CLIP_LO, CLIP_HI) if self.clip else raw
        return Quotes(value, np.where(valid, age, np.nan).astype("float64"), clipped)
