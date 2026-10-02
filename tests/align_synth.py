"""Synthetic inputs for the alignment tests (no network, no raw data)."""

from __future__ import annotations

import numpy as np
import pandas as pd

from poly_actor.align.events import Event
from poly_actor.align.grid import bar_table, build_row_grid
from poly_actor.ingest.common import to_epoch


def ep(iso: str) -> int:
    return to_epoch(iso)


def obs(key: str, times: list[int], values: list[float], fidelity: int = 60) -> pd.DataFrame:
    return pd.DataFrame({"key": key, "fidelity": fidelity, "t": times, "p": values})


def hourly_obs(key: str, start_s: int, end_s: int, value, offset_s: int = 5) -> pd.DataFrame:
    """One observation per hour stamped `offset_s` after the hour (like CLOB fid=60)."""
    times = list(range(start_s + offset_s, end_s, 3600))
    return obs(key, times, [value(t) for t in times])


def bars_for(ticker: str, sessions: pd.DataFrame, open_fn, close_fn) -> pd.DataFrame:
    """Start-stamped raw-style bars for every expected bar of `sessions`."""
    table = bar_table(sessions)
    starts = table["start_s"].to_numpy()
    return pd.DataFrame(
        {
            "ticker": ticker,
            "ts": pd.to_datetime(starts, unit="s", utc=True),
            "open": [open_fn(s) for s in starts],
            "close": [close_fn(s) for s in starts],
            "ohlc_all_nan": False,
        }
    )


def rows_for(start_iso: str, end_iso: str, sessions: pd.DataFrame) -> pd.DataFrame:
    return build_row_grid(ep(start_iso), ep(end_iso), sessions)


def token_event(
    event_id: str, token: str, use_from: str, use_until: str, first_usable: str | None = None
) -> Event:
    return Event(
        event_id, ep(use_from), ep(use_until), ep(first_usable or use_from), ep(use_until) - 3600,
        token=token,
    )  # fmt: skip


def values(frame: pd.DataFrame, column: str) -> np.ndarray:
    return frame[column].to_numpy(dtype="float64")
