"""Hourly primary tests of A27 (rules 2-3), their robustness runs (rule 10), the shift
placebo (rule 11) and the exploratory overnight test (rule 14). Pure functions.

Units. Returns are log returns. Fed effects are TLT bp per 1 bp of Δdovishness (beta * 1e4).
BTC effects are IBIT bp per 1% change in the ladder level (beta * 100).
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from poly_actor.analysis import models
from poly_actor.analysis.sample import Design, SessionGrid, build_design

FED_LAGS = (0, 1, 2)
BTC_LAGS = (1,)
SPOT_LAGS = (0, 1, 2, 3)
ROBUST_DROP_SHARE = 0.01  # R2: drop the top 1% of |ΔPM| rows
ROBUST_P = 0.10  # a robustness run "holds" if the sign is unchanged and one-sided p < 0.10
HOUR_S = 3600


@dataclass(frozen=True)
class TestOut:
    """A one-sided test of w'beta > 0 (sign already aligned with H1), effect in reader units."""

    estimate: float
    ci_low: float
    ci_high: float
    se: float
    t: float
    df: int
    p_one: float  # H1 direction
    p_two: float
    r_upper: float  # one-sided 95% upper bound, partial-correlation units
    r_lower: float  # one-sided 95% lower bound, partial-correlation units

    def as_dict(self) -> dict:
        return {k: _clean(v) for k, v in self.__dict__.items()}


def _clean(v):
    if isinstance(v, float | np.floating):
        return float(v) if math.isfinite(v) else None
    if isinstance(v, np.integer):
        return int(v)
    return v


def to_test(lt: models.LinTest, scale: float) -> TestOut:
    return TestOut(
        lt.estimate * scale,
        lt.ci_low * scale,
        lt.ci_high * scale,
        lt.se * scale,
        lt.t,
        lt.df,
        lt.p_upper,
        lt.p_two,
        models.bound_r(lt, upper=True),
        models.bound_r(lt, upper=False),
    )


@dataclass(frozen=True)
class RegOut:
    n: int
    n_sessions: int
    hac_lag: int
    tests: dict[str, TestOut]
    robustness: dict[str, dict] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "n": self.n,
            "n_sessions": self.n_sessions,
            "hac_lag": self.hac_lag,
            "tests": {k: v.as_dict() for k, v in self.tests.items()},
            "robustness": self.robustness,
        }


def _fit(d: Design, cov: str = "hac") -> models.OlsFit:
    return models.ols(d.X, d.y, cov=cov, groups=d.session)


def _test(d: Design, fit: models.OlsFit, terms: tuple[str, ...], scale: float) -> TestOut:
    return to_test(models.lin_test(fit, models.weights(d.names, terms)), scale)


def drop_top_share(d: Design, pm_cols: list[int], share: float = ROBUST_DROP_SHARE) -> Design:
    """R2: drop the ceil(share * n) rows with the largest max |ΔPM| over their PM regressors."""
    size = np.abs(d.X[:, pm_cols]).max(axis=1)
    n_drop = math.ceil(share * len(size))
    keep = np.ones(len(size), dtype=bool)
    keep[np.argsort(-size, kind="stable")[:n_drop]] = False
    return Design(d.y[keep], d.X[keep], d.session[keep], d.cells[keep], d.names)


def holds(test: TestOut, sign: float = 1.0) -> bool:
    """Sign unchanged and one-sided p < 0.10 (A27 rule 10)."""
    return bool(np.sign(test.estimate) == sign and test.p_one < ROBUST_P)


def keep_sessions(d: Design, sessions: np.ndarray, drop: set) -> Design:
    keep = np.array([sessions[s] not in drop for s in d.session], dtype=bool)
    return Design(d.y[keep], d.X[keep], d.session[keep], d.cells[keep], d.names)


# ---------------------------------------------------------------- Fed (rule 2)


def fed_regression(
    grid: SessionGrid,
    ticker: str = "TLT",
    drop_sessions: set | None = None,
) -> tuple[Design, RegOut]:
    """OLS of ret_ticker_t on Δdovishness at lags 0, 1, 2 with Newey-West HAC.

    Tests: `sum` = b0+b1+b2 (primary), `lead` = b1+b2 (rule 7.6 gatekeeping), `b0`."""
    d = build_design(grid, grid.returns[ticker], FED_LAGS)
    if drop_sessions:
        d = keep_sessions(d, grid.sessions, drop_sessions)
    fit = _fit(d)
    tests = {
        "sum": _test(d, fit, ("pm_lag0", "pm_lag1", "pm_lag2"), 1e4),
        "lead": _test(d, fit, ("pm_lag1", "pm_lag2"), 1e4),
        "b0": _test(d, fit, ("pm_lag0",), 1e4),
    }
    return d, RegOut(d.n_rows, d.n_sessions, models.nw_lag(d.n_rows), tests)


def fed_robustness(
    grid: SessionGrid, grid_age900: SessionGrid, event_sessions: set, ticker: str = "TLT"
) -> dict:
    """R1 session-clustered SE, R2 drop top 1% |ΔPM|, R3 drop CPI and FOMC sessions; the
    age-900 run is reported only."""
    d, base = fed_regression(grid, ticker)
    terms = ("pm_lag0", "pm_lag1", "pm_lag2")
    r1 = _test(d, _fit(d, "cluster"), terms, 1e4)
    d2 = drop_top_share(d, [1, 2, 3])
    r2 = _test(d2, _fit(d2), terms, 1e4)
    _, r3 = fed_regression(grid, ticker, drop_sessions=event_sessions)
    _, age = fed_regression(grid_age900, ticker)
    sign = float(np.sign(base.tests["sum"].estimate)) or 1.0
    out = {
        "R1_session_cluster": {**r1.as_dict(), "holds": holds(r1, sign)},
        "R2_drop_top1pct": {**r2.as_dict(), "holds": holds(r2, sign), "n": d2.n_rows},
        "R3_drop_event_sessions": {
            **r3.tests["sum"].as_dict(),
            "holds": holds(r3.tests["sum"], sign),
            "n": r3.n,
        },
        "age900_reported_only": {
            **age.tests["sum"].as_dict(),
            "n": age.n,
            "rows_changed": base.n - age.n,
            "fire_rate": (base.n - age.n) / base.n if base.n else None,
        },
    }
    out["all_hold"] = all(out[k]["holds"] for k in out if k.startswith("R"))
    return out


def spot_controls(grid: SessionGrid, spot_at: Callable[[np.ndarray], np.ndarray]) -> np.ndarray:
    """BTC-USD control lags in CLOCK time (A27 rule 3, M5), shape (S, P, 4).

    Lag k = log S(t - 60k min) - log S(t - 60(k+1) min), each S an as-of lookup (`spot_at`
    maps epoch seconds to the latest spot at or before them, NaN when too old). Session
    boundaries do not matter for the control."""
    ts = grid.ts_end.astype("float64")
    ts[~grid.exists] = np.nan
    levels = []
    for k in range(len(SPOT_LAGS) + 1):
        inst = ts - k * HOUR_S
        flat = inst.ravel()
        vals = np.full(flat.shape, np.nan)
        ok = ~np.isnan(flat)
        vals[ok] = spot_at(flat[ok].astype("int64"))
        levels.append(np.log(vals.reshape(ts.shape)))
    return np.stack([levels[k] - levels[k + 1] for k in range(len(SPOT_LAGS))], axis=2)


def btc_regression(
    grid: SessionGrid,
    controls: np.ndarray,
    ticker: str = "IBIT",
    with_control: bool = True,
    pm_lags: tuple[int, ...] = BTC_LAGS,
) -> tuple[Design, RegOut]:
    """OLS of ret_ticker_t on Δln(ladder)_{t-1} (+ spot lags 0-3). The no-control run uses the
    same rows as the control run, so the two coefficients are comparable."""
    y = grid.returns[ticker]
    d_ctrl = build_design(grid, y, pm_lags, controls, tuple(f"spot_lag{k}" for k in SPOT_LAGS))
    d = d_ctrl
    if not with_control:
        d = Design(
            d_ctrl.y,
            d_ctrl.X[:, : 1 + len(pm_lags)],
            d_ctrl.session,
            d_ctrl.cells,
            d_ctrl.names[: 1 + len(pm_lags)],
        )
    fit = _fit(d)
    tests = {f"lag{k}": _test(d, fit, (f"pm_lag{k}",), 100.0) for k in pm_lags}
    return d, RegOut(d.n_rows, d.n_sessions, models.nw_lag(d.n_rows), tests)


def btc_robustness(grid: SessionGrid, grid_age900: SessionGrid, controls: np.ndarray) -> dict:
    d, base = btc_regression(grid, controls)
    r1 = _test(d, _fit(d, "cluster"), ("pm_lag1",), 100.0)
    d2 = drop_top_share(d, [1])
    r2 = _test(d2, _fit(d2), ("pm_lag1",), 100.0)
    _, age = btc_regression(grid_age900, controls)
    sign = float(np.sign(base.tests["lag1"].estimate)) or 1.0
    out = {
        "R1_session_cluster": {**r1.as_dict(), "holds": holds(r1, sign)},
        "R2_drop_top1pct": {**r2.as_dict(), "holds": holds(r2, sign), "n": d2.n_rows},
        "R3_drop_event_sessions": {"holds": True, "note": "Fed only (A27 rule 10)"},
        "age900_reported_only": {
            **age.tests["lag1"].as_dict(),
            "n": age.n,
            "rows_changed": base.n - age.n,
            "fire_rate": (base.n - age.n) / base.n if base.n else None,
        },
    }
    out["all_hold"] = bool(out["R1_session_cluster"]["holds"] and out["R2_drop_top1pct"]["holds"])
    return out


def residualise(y: np.ndarray, controls: np.ndarray) -> np.ndarray:
    """Return y minus its OLS fit on the controls (cells with y and all controls present)."""
    ok = ~np.isnan(y) & ~np.isnan(controls).any(axis=2)
    X = np.column_stack([np.ones(ok.sum()), controls[ok]])
    beta = np.linalg.lstsq(X, y[ok], rcond=None)[0]
    out = np.full(y.shape, np.nan)
    out[ok] = y[ok] - X @ beta
    return out


# ---------------------------------------------------------------- overnight (rule 14)


def overnight_frame(panel: pd.DataFrame, ticker: str, sign: float) -> pd.DataFrame:
    """One row per session open: gap, PM overnight change (sign applied), weekend flag."""
    rows = panel[panel["is_session_open"].astype(bool)].sort_values("ts_end")
    day = pd.to_datetime(pd.Series(rows["session"].to_numpy()))
    nights = day.diff().dt.days.to_numpy()  # NaN for the first session
    return pd.DataFrame(
        {
            "session": rows["session"].to_numpy(),
            "ts_open": rows["ts_start"].to_numpy(),
            "gap": rows[f"overnight_gap_{ticker}"].to_numpy(dtype="float64"),
            "dpm": sign * rows["pm_overnight_change"].to_numpy(dtype="float64"),
            "n_missing": rows["pm_overnight_n_missing"].to_numpy(),
            "weekend": (nights > 1).astype(float),
        }
    )


def overnight_test(frame: pd.DataFrame, scale: float, control: np.ndarray | None = None) -> dict:
    """OLS gap ~ dpm + weekend + dpm*weekend (+ spot gap control), HC1. Exploratory: the
    coefficient on dpm reads as 'moves with', never 'first'."""
    ok = (frame["n_missing"] == 0) & frame["gap"].notna() & frame["dpm"].notna()
    cols = [frame["dpm"], frame["weekend"], frame["dpm"] * frame["weekend"]]
    names = ("const", "dpm", "weekend", "dpm_x_weekend")
    if control is not None:
        ok &= ~np.isnan(control)
        cols.append(pd.Series(control, index=frame.index))
        names = (*names, "spot_gap")
    sel = frame[ok]
    X = np.column_stack([np.ones(len(sel))] + [c[ok].to_numpy(dtype="float64") for c in cols])
    fit = models.ols(X, sel["gap"].to_numpy(dtype="float64"), cov="hc1")
    lt = models.lin_test(fit, models.weights(names, ("dpm",)))
    return {
        "n": int(len(sel)),
        "n_weekend": int(sel["weekend"].sum()),
        **to_test(lt, scale).as_dict(),
    }
