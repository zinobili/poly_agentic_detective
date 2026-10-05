"""Last-observation-at-or-before lookups (the only resampling rule used in alignment).

The as-of takes the FRESHEST usable observation across all fidelities (A25). An observation
stamped at `t` is usable at instant `x` only if `t <= x`, at every fidelity, with no exceptions
(the A22 sampling tolerance was retired by A26). Observations older than `max_age_s` are refused
(no forward-fill across long gaps). Instants and stamps are epoch seconds (UTC, int64).
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
    age_s: instant minus observation stamp (always >= 0), NaN where unavailable.
    clipped: True where the raw value was outside [0, 1] and had to be clipped."""

    p: np.ndarray
    age_s: np.ndarray
    clipped: np.ndarray


class PriceBook:
    """Per-key (token or ticker) sorted observations with as-of lookup.

    `obs` columns: key, t (epoch seconds, UTC), p, and optionally fidelity. When the same
    (key, t) appears at several fidelities the finest (lowest) fidelity wins. Fidelity-1 probe
    records with no rows contribute nothing: an absent observation is "no data", never a price.
    """

    def __init__(self, obs: pd.DataFrame, max_age_s: int, clip: bool = True):
        self.max_age_s = max_age_s
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
        """Freshest observation stamped at or before the instant (any fidelity), within the cap."""
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
        found = stamp != none
        age = np.where(found, instants - stamp, np.iinfo(np.int64).max)
        valid = found & (age <= self.max_age_s)
        raw = np.where(valid, value, np.nan)
        clipped = valid & ((raw < CLIP_LO) | (raw > CLIP_HI)) if self.clip else np.zeros(n, bool)
        out = np.clip(raw, CLIP_LO, CLIP_HI) if self.clip else raw
        return Quotes(out, np.where(valid, age, np.nan).astype("float64"), clipped)
