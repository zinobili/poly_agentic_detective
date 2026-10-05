"""Last-observation-at-or-before lookups (the only resampling rule used in alignment).

The as-of takes the FRESHEST usable observation across all fidelities (A25). An observation
stamped at `t` is usable at instant `x` only if `t <= x` (strict no-look-ahead), with ONE bounded
exception (A22, amended by A25): a fidelity-60 point stamped up to `tolerance_s` seconds AFTER a
whole-hour instant counts for that hour (the CLOB stamps its hourly samples a few seconds late).
No other fidelity and no other instant (e.g. the :30 session-bar ends) gets the tolerance.
Tolerance 0 = fully strict. Observations older than `max_age_s` are refused (no forward-fill
across long gaps). Instants and stamps are epoch seconds (UTC, int64).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from poly_actor.align.consts import CLIP_HI, CLIP_LO, HOUR_S, TOLERANCE_FIDELITY


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
    records with no rows contribute nothing: an absent observation is "no data", never a price.
    Only fidelity-60 rows are eligible for the tolerance; spot or other series never are."""

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
        tol_frame = frame[frame["fidelity"] == TOLERANCE_FIDELITY]
        self._tol_series: dict[str, tuple[np.ndarray, np.ndarray]] = {
            str(k): (g["t"].to_numpy(dtype="int64"), g["p"].to_numpy(dtype="float64"))
            for k, g in tol_frame.groupby("key", sort=False)
        }

    def has(self, key: str) -> bool:
        return key in self._series

    def asof(self, key: str, instants: np.ndarray) -> Quotes:
        """Freshest observation stamped at or before the instant (any fidelity), or a fidelity-60
        point up to `tolerance_s` after a whole-hour instant; within the age cap."""
        n = len(instants)
        series = self._series.get(key)
        if series is None or n == 0:
            return Quotes(np.full(n, np.nan), np.full(n, np.nan), np.zeros(n, dtype=bool))
        t, p = series
        none = np.iinfo(np.int64).min
        idx = np.searchsorted(t, instants, side="right") - 1
        safe = np.where(idx >= 0, idx, 0)
        stamp = np.where(idx >= 0, t[safe], none)
        value = p[safe]
        tol = self._tol_series.get(key)
        if tol is not None and self.tolerance_s > 0:
            tol_t, tol_p = tol
            reach = instants + np.where(instants % HOUR_S == 0, self.tolerance_s, 0)
            j = np.searchsorted(tol_t, reach, side="right") - 1
            js = np.where(j >= 0, j, 0)
            tol_stamp = np.where(j >= 0, tol_t[js], none)
            better = tol_stamp > stamp
            stamp = np.where(better, tol_stamp, stamp)
            value = np.where(better, tol_p[js], value)
        found = stamp != none
        age = np.where(found, instants - stamp, np.iinfo(np.int64).max)
        valid = found & (age <= self.max_age_s)
        raw = np.where(valid, value, np.nan)
        clipped = valid & ((raw < CLIP_LO) | (raw > CLIP_HI)) if self.clip else np.zeros(n, bool)
        out = np.clip(raw, CLIP_LO, CLIP_HI) if self.clip else raw
        return Quotes(out, np.where(valid, age, np.nan).astype("float64"), clipped)
