"""Per-pair analysis cores (pure: grids and tables in, plain dicts out) and the `Facts` the
verdict rules read. `run.py` does the I/O; the synthetic tests call these directly, so both
go through the same code.

Phase 1 computes every primary (and its p-value); phase 2 applies BH over the three
inferential primaries (A12 family, A27 rule 6); phase 3 turns each core into `Facts`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from poly_actor.analysis import cpi as cpi_mod
from poly_actor.analysis import placebo, primary
from poly_actor.analysis.sample import SessionGrid
from poly_actor.analysis.verdict import Facts

MIN_ROWS = 500  # A27 rule 7.2 / M8 (Fed, BTC)
MIN_SESSIONS = 60
XLU_PLACEBO_P = 0.10  # XLU passes if two-sided p > 0.10 (A27 rule 3)
FED_PLACEBO_P = 0.10  # shift permutation p < 0.10 (A27 rule 11)
CPI_PLACEBO_PCTL = 0.10


def sufficiency(n: int, sessions: int) -> tuple[bool, str]:
    ok = n >= MIN_ROWS and sessions >= MIN_SESSIONS
    return ok, f"{n} usable rows in {sessions} sessions (minimum {MIN_ROWS} and {MIN_SESSIONS})"


# ---------------------------------------------------------------- Fed


@dataclass
class FedCore:
    reg: primary.RegOut
    placebo: dict
    robustness: dict | None
    xcorr: dict[str, placebo.XcorrResult]
    secondary: dict[str, primary.RegOut]

    @property
    def p_one(self) -> float:
        return self.reg.tests["sum"].p_one


def fed_core(
    grid: SessionGrid,
    grid_age900: SessionGrid | None = None,
    event_sessions: set | None = None,
    xcorr_tickers: tuple[str, ...] = ("TLT",),
    secondary: tuple[str, ...] = (),
) -> FedCore:
    _, reg = primary.fed_regression(grid, "TLT")
    plc = placebo.shift_placebo(grid, grid.returns["TLT"], primary.FED_LAGS)
    rob = (
        primary.fed_robustness(grid, grid_age900, event_sessions or set())
        if grid_age900 is not None
        else None
    )
    xc = {t: placebo.xcorr_with_band(grid, grid.returns[t]) for t in xcorr_tickers}
    sec = {}
    for t in secondary:
        y = grid.returns[t] if t in grid.returns else _spread(grid, t)
        sec[t] = primary.fed_regression(_with_returns(grid, t, y), t)[1]
    return FedCore(reg, plc, rob, xc, sec)


def _spread(grid: SessionGrid, name: str) -> np.ndarray:
    a, b = name.split("-")
    return grid.returns[a] - grid.returns[b]


def _with_returns(grid: SessionGrid, name: str, y: np.ndarray) -> SessionGrid:
    from dataclasses import replace

    return replace(grid, returns={**grid.returns, name: y})


def fed_facts(core: FedCore, bh_reject: bool, bh_q: float) -> Facts:
    t = core.reg.tests["sum"]
    ok, note = sufficiency(core.reg.n, core.reg.n_sessions)
    plc_p = core.placebo["permutation_p"]
    return Facts(
        pair="fed",
        sufficient=ok,
        sufficiency_note=note,
        placebo_pass=plc_p < FED_PLACEBO_P,
        placebo_note=f"session-shift permutation p = {plc_p:.3f} (needs < {FED_PLACEBO_P})",
        p_one=t.p_one,
        p_two=t.p_two,
        estimate_h1_sign=t.estimate > 0,
        bh_reject=bh_reject,
        bh_q=bh_q,
        upper_r=t.r_upper,
        lower_r=t.r_lower,
        lead_p=core.reg.tests["lead"].p_one,
        robust_hold=core.robustness["all_hold"] if core.robustness else None,
    )


# ---------------------------------------------------------------- BTC


@dataclass
class BtcCore:
    reg: primary.RegOut  # with the spot control
    reg_nocontrol: primary.RegOut
    xlu: primary.RegOut
    placebo_shift: dict
    robustness: dict | None
    xcorr_raw: dict[str, placebo.XcorrResult]
    xcorr_resid: dict[str, placebo.XcorrResult]
    exploratory: dict[str, primary.RegOut]

    @property
    def p_one(self) -> float:
        return self.reg.tests["lag1"].p_one


def btc_core(
    grid: SessionGrid,
    controls: np.ndarray,
    grid_age900: SessionGrid | None = None,
    xcorr_tickers: tuple[str, ...] = ("IBIT",),
    exploratory: tuple[str, ...] = (),
) -> BtcCore:
    _, reg = primary.btc_regression(grid, controls, "IBIT")
    _, reg_nc = primary.btc_regression(grid, controls, "IBIT", with_control=False)
    xlu = primary.btc_regression(grid, controls, "XLU")[1] if "XLU" in grid.returns else None
    plc = placebo.shift_placebo(grid, grid.returns["IBIT"], primary.BTC_LAGS, controls)
    rob = primary.btc_robustness(grid, grid_age900, controls) if grid_age900 is not None else None
    raw = {t: placebo.xcorr_with_band(grid, grid.returns[t]) for t in xcorr_tickers}
    resid = {
        t: placebo.xcorr_with_band(grid, primary.residualise(grid.returns[t], controls))
        for t in xcorr_tickers
    }
    exp = {t: primary.btc_regression(grid, controls, t)[1] for t in exploratory}
    if exploratory:
        exp["IBIT_lags1to3"] = primary.btc_regression(grid, controls, "IBIT", pm_lags=(1, 2, 3))[1]
    return BtcCore(reg, reg_nc, xlu, plc, rob, raw, resid, exp)


def btc_facts(core: BtcCore, bh_reject: bool, bh_q: float) -> Facts:
    t = core.reg.tests["lag1"]
    ok, note = sufficiency(core.reg.n, core.reg.n_sessions)
    xlu_p = core.xlu.tests["lag1"].p_two if core.xlu else None
    return Facts(
        pair="btc",
        sufficient=ok,
        sufficiency_note=note,
        placebo_pass=None if xlu_p is None else xlu_p > XLU_PLACEBO_P,
        placebo_note=f"control stock XLU two-sided p = {xlu_p:.3f} (needs > {XLU_PLACEBO_P})"
        if xlu_p is not None
        else "",
        p_one=t.p_one,
        p_two=t.p_two,
        estimate_h1_sign=t.estimate > 0,
        bh_reject=bh_reject,
        bh_q=bh_q,
        upper_r=t.r_upper,
        lower_r=t.r_lower,
        nocontrol_p=core.reg_nocontrol.tests["lag1"].p_one,
        robust_hold=core.robustness["all_hold"] if core.robustness else None,
    )


# ---------------------------------------------------------------- CPI


@dataclass
class CpiCore:
    n_usable: int
    validation: cpi_mod.Validation
    test: cpi_mod.SpearmanOut | None
    close_proxy: cpi_mod.SpearmanOut | None
    robust_r2: cpi_mod.SpearmanOut | None
    placebo: dict | None

    @property
    def p_one(self) -> float | None:
        return self.test.p_one if self.test else None


def cpi_core(
    proxy: np.ndarray,
    gap: np.ndarray,
    close_proxy: np.ndarray,
    validation: cpi_mod.Validation,
    placebo_proxy: np.ndarray | None = None,
    placebo_gap: np.ndarray | None = None,
) -> CpiCore:
    """`proxy`, `gap`, `close_proxy` are per usable release (NaN rows already removed for
    proxy/gap; close_proxy may hold NaN)."""
    n = len(proxy)
    test = cpi_mod.spearman_test(proxy, gap) if n >= 3 else None
    ok = ~np.isnan(close_proxy)
    close = cpi_mod.spearman_test(close_proxy[ok], gap[ok]) if ok.sum() >= 3 else None
    r2 = cpi_mod.spearman_test(*cpi_mod.drop_largest(proxy, gap)) if n >= 4 else None
    plc = None
    if test is not None and placebo_proxy is not None and len(placebo_proxy) >= n:
        rhos = cpi_mod.placebo_rhos(placebo_proxy, placebo_gap, n)
        p10 = float(np.quantile(rhos, CPI_PLACEBO_PCTL))
        plc = {
            "n_candidates": int(len(placebo_proxy)),
            "n_sets": int(len(rhos)),
            "p10_of_placebo_rho": p10,
            "release_rho": test.rho,
            "passes": bool(test.rho < p10),
            "share_below_release_rho": float(np.mean(rhos <= test.rho)),
        }
    return CpiCore(n, validation, test, close, r2, plc)


def cpi_facts(core: CpiCore, bh_reject: bool, bh_q: float | None) -> Facts:
    ok = core.n_usable >= cpi_mod.MIN_USABLE
    note = f"{core.n_usable} usable releases (minimum {cpi_mod.MIN_USABLE})"
    t = core.test
    r2_holds = bool(core.robust_r2 and core.robust_r2.rho < 0 and core.robust_r2.p_one < 0.10)
    close_ok = bool(core.close_proxy and core.close_proxy.rho < 0 and core.close_proxy.p_one < 0.10)
    return Facts(
        pair="cpi",
        sufficient=ok,
        sufficiency_note=note,
        validation_ok=core.validation.passed,
        placebo_pass=None if core.placebo is None else core.placebo["passes"],
        placebo_note="the release correlation is not below the 10th percentile of random dates",
        p_one=t.p_one if t else None,
        p_two=t.p_two if t else None,
        estimate_h1_sign=bool(t and t.rho < 0),
        bh_reject=bh_reject,
        bh_q=bh_q,
        upper_r=t.upper_r if t else None,
        lower_r=t.lower_r if t else None,
        close_proxy_ok=close_ok,
        robust_hold=r2_holds,  # R1 and R3 do not apply to a one-row-per-release test
    )
