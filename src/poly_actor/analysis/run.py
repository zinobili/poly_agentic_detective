"""CLI: python -m poly_actor.analysis run [--workers N] | counts | report

`run` writes data/clean/results/<pair_id>.json (dashboard contract) and results/summary.json
(BH tables, plus the code commit that produced them). Phase 1 runs one job per pair (in
parallel with --workers); phase 2 applies BH over the three inferential primaries (A12, A27
rule 6) and, separately, over the exploratory family; phase 3 computes verdicts and writes.

`counts` prints sample sizes from flags and data presence only (no return values are read
into any statistic); it is safe before the analysis settings are final.

`report` renders docs/findings.md from the results files (`findings.py`); no statistics.
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from collections.abc import Callable, Mapping
from concurrent.futures import Future, ProcessPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from poly_actor.align import pipeline
from poly_actor.analysis import cpi as cpi_mod
from poly_actor.analysis import (
    findings,
    inputs,
    models,
    primary,
    results,
    runners,
    sample,
    studies,
    verdict,
)
from poly_actor.analysis.verdict import BH_Q
from poly_actor.config import CLEAN_DIR, ROOT
from poly_actor.dashboard.contract import ResultsDoc
from poly_actor.dashboard.load import load_pair_specs

log = logging.getLogger(__name__)

PRIMARY_ORDER = ("fed_decision", "bitcoin_monthly_ladder", "us_cpi_inflation")
# Exploratory tests that use the misaligned spot control (prereg A29 item 3 and its addendum).
A29_EXPLORATORY = (
    "btc_COIN_lag1",
    "btc_MSTR_lag1",
    "btc_IBIT_lag2",
    "btc_IBIT_lag3",
    "btc_overnight_IBIT_spot_control",
)


@dataclass
class Job:
    """Phase-1 output of one pair: the core, its chart-2 studies and extras."""

    pair_id: str
    core: object | None = None
    studies: dict = field(default_factory=dict)
    extra: dict = field(default_factory=dict)
    exploratory: dict[str, float] = field(default_factory=dict)  # name -> two-sided p
    exploratory_notes: dict[str, str] = field(default_factory=dict)  # name -> caveat
    doc: ResultsDoc | None = None  # pair 4 is complete after phase 1


# ---------------------------------------------------------------- helpers


def session_values(panel: pd.DataFrame, grid: sample.SessionGrid, col: str) -> np.ndarray:
    """Per-session value of a column read on the session's opening row (e.g. a gap)."""
    opens = panel[panel["is_session_open"].astype(bool)].set_index("session")[col]
    return pd.Series(grid.sessions).map(opens).to_numpy(dtype="float64")


def flagged_cells(panel: pd.DataFrame, grid: sample.SessionGrid, col: str) -> list[tuple[int, int]]:
    """(session, position) of session bars where a boolean column is set."""
    bars = panel[panel["is_session_bar"].astype(bool)].sort_values("ts_end")
    ts = ((bars["ts_end"] - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)).to_numpy()
    want = set(ts[bars[col].astype(bool).to_numpy()])
    s_idx, p_idx = np.nonzero(grid.exists)
    return [
        (int(s), int(p)) for s, p in zip(s_idx, p_idx, strict=True) if grid.ts_end[s, p] in want
    ]


def session_index(grid: sample.SessionGrid, days: set[date]) -> list[int]:
    return [i for i, d in enumerate(grid.sessions) if d in days]


# ---------------------------------------------------------------- phase 1 jobs


def fed_job(panel: pd.DataFrame, days: Mapping[str, set[date]]) -> Job:
    grid = sample.build_grid(panel, "fed_decision")
    grid900 = sample.build_grid(panel, "fed_decision", sample.ROBUST_PM_AGE_S)
    core = runners.fed_core(
        grid,
        grid900,
        days["fomc"] | days["cpi"],
        xcorr_tickers=("TLT", "SPY", "XLF"),
        secondary=("SPY", "XLF-SPY"),
    )
    decisions = flagged_cells(panel, grid, "event_hour")
    fomc_idx = {s for s, _ in decisions}
    pool = [(s, 4) for s in range(grid.n_sessions) if s not in fomc_idx and grid.exists[s, 4]]
    st = {}
    for t in ("TLT", "SPY", "XLF"):
        gaps = session_values(panel, grid, f"overnight_gap_{t}")
        out = studies.bar_study(
            grid,
            grid.returns[t],
            gaps,
            decisions,
            pool,
            studies.FED_SIGN_MIN,
            studies.FED_WINDOW,
            fold=False,
        )
        st[t] = out
    night = primary.overnight_test(primary.overnight_frame(panel, "TLT", -1.0), 1e4)
    exploratory = {
        "fed_SPY_sum": core.secondary["SPY"].tests["sum"].p_two,
        "fed_XLF-SPY_sum": core.secondary["XLF-SPY"].tests["sum"].p_two,
        "fed_overnight_TLT": night["p_two"],
    }
    extra = {"n_events": len(decisions), "overnight_TLT": night}
    return Job("fed_decision", core, st, extra, exploratory)


def btc_job(panel: pd.DataFrame, spot_at: Callable[[np.ndarray], np.ndarray]) -> Job:
    pid = "bitcoin_monthly_ladder"
    grid = sample.build_grid(panel, pid)
    grid900 = sample.build_grid(panel, pid, sample.ROBUST_PM_AGE_S)
    controls = primary.spot_controls(grid, spot_at)
    tickers = ("IBIT", "COIN", "MSTR", "XLU")
    core = runners.btc_core(grid, controls, grid900, tickers, exploratory=("COIN", "MSTR"))
    bar0s = studies.btc_events(grid)
    event_sessions = {s for s, _ in bar0s}
    cells, where = studies.flat_index(grid)
    pool = [
        cells[where[(s, p)] + 1]
        for s, p in zip(*np.nonzero(grid.row_ok), strict=True)
        if s not in event_sessions and where[(s, p)] + 1 < len(cells)
    ]
    spot_gap = _spot_gap(panel, grid, spot_at)
    st = {}
    for t in tickers:
        y = primary.residualise(grid.returns[t], controls)
        gaps = _residual_gap(session_values(panel, grid, f"overnight_gap_{t}"), spot_gap)
        out = studies.bar_study(grid, y, gaps, bar0s, pool, 0.0, studies.BTC_WINDOW, fold=True)
        st[t] = out
    frame = primary.overnight_frame(panel, "IBIT", 1.0)
    gap_by_session = dict(zip(grid.sessions, spot_gap, strict=True))
    ctrl = frame["session"].map(gap_by_session).to_numpy(dtype="float64")
    night = primary.overnight_test(frame, 100.0)
    night_c = primary.overnight_test(frame, 100.0, control=ctrl)
    exp = core.exploratory
    exploratory = {
        "btc_COIN_lag1": exp["COIN"].tests["lag1"].p_two,
        "btc_MSTR_lag1": exp["MSTR"].tests["lag1"].p_two,
        "btc_IBIT_lag2": exp["IBIT_lags1to3"].tests["lag2"].p_two,
        "btc_IBIT_lag3": exp["IBIT_lags1to3"].tests["lag3"].p_two,
        "btc_IBIT_no_control": core.reg_nocontrol.tests["lag1"].p_two,
        "btc_overnight_IBIT": night["p_two"],
        "btc_overnight_IBIT_spot_control": night_c["p_two"],
    }
    extra = {
        "n_events": len(bar0s),
        "overnight_IBIT": night,
        "overnight_IBIT_spot_control": night_c,
    }
    # Prereg A29 item 3: these use the same misaligned spot control as the primary.
    notes = {n: verdict.A29_NOTE for n in A29_EXPLORATORY}
    return Job(pid, core, st, extra, exploratory, notes)


def _spot_gap(panel, grid, spot_at) -> np.ndarray:
    """log spot at each session open minus log spot at the previous session's close.

    Prereg A29 (addendum): the spot as-of at the 09:30 ET open is the 09:00 hourly close, so
    this control is about 30 min off the IBIT gap, like the primary's control. The tests that
    use it (`btc_overnight_IBIT_spot_control`, the BTC Chart 2 gaps) carry the A29 note."""
    opens = panel[panel["is_session_open"].astype(bool)].set_index("session")["ts_start"]
    open_s = pd.Series(grid.sessions).map(opens)
    open_s = ((open_s - pd.Timestamp(0, tz="UTC")) // pd.Timedelta(seconds=1)).to_numpy()
    last = np.where(grid.exists, grid.ts_end, -1).max(axis=1)
    prev_close = np.r_[-1, last[:-1]]
    ok = prev_close > 0
    out = np.full(grid.n_sessions, np.nan)
    out[ok] = np.log(spot_at(open_s[ok])) - np.log(spot_at(prev_close[ok]))
    return out


def _residual_gap(gap: np.ndarray, spot_gap: np.ndarray) -> np.ndarray:
    ok = ~np.isnan(gap) & ~np.isnan(spot_gap)
    out = np.full(gap.shape, np.nan)
    if ok.sum() > 2:
        X = np.column_stack([np.ones(ok.sum()), spot_gap[ok]])
        beta = np.linalg.lstsq(X, gap[ok], rcond=None)[0]
        out[ok] = gap[ok] - X @ beta
    return out


def cpi_job(panel: pd.DataFrame, tab: pd.DataFrame, placebo_tab: pd.DataFrame | None) -> Job:
    pid = "us_cpi_inflation"
    grid = sample.build_grid(panel, pid)
    gap = {t: session_values(panel, grid, f"overnight_gap_{t}") for t in ("TLT", "QQQ")}
    by_day = {d: i for i, d in enumerate(grid.sessions)}
    use = tab[tab["usable"]].copy()
    use["gap_TLT"] = [gap["TLT"][by_day[d]] if d in by_day else np.nan for d in use["session"]]
    use["gap_QQQ"] = [gap["QQQ"][by_day[d]] if d in by_day else np.nan for d in use["session"]]
    no_gap = int(use["gap_TLT"].isna().sum())
    use = use[use["gap_TLT"].notna()]
    validation = cpi_mod.validate(tab)
    plc_proxy = plc_gap = None
    if placebo_tab is not None and len(placebo_tab):
        pt = placebo_tab[placebo_tab["usable"]].copy()
        pt["gap"] = [gap["TLT"][by_day[d]] if d in by_day else np.nan for d in pt["session"]]
        pt = pt[pt["gap"].notna()]
        plc_proxy, plc_gap = pt["proxy"].to_numpy(), pt["gap"].to_numpy()
    core = runners.cpi_core(
        use["proxy"].to_numpy(),
        use["gap_TLT"].to_numpy(),
        use["close_proxy"].to_numpy(),
        validation,
        plc_proxy,
        plc_gap,
    )
    qqq = use[use["gap_QQQ"].notna()]
    qqq_test = cpi_mod.spearman_test(qqq["proxy"].to_numpy(), qqq["gap_QQQ"].to_numpy())
    rel_idx = session_index(grid, set(tab["session"]))
    pool_days = set(placebo_tab["session"]) if placebo_tab is not None else set()
    pool_idx = session_index(grid, pool_days)
    st = {
        t: studies.cpi_study(grid, grid.returns[t], gap[t], rel_idx, pool_idx)
        for t in ("TLT", "QQQ")
    }
    extra = {
        "releases": tab.drop(columns=[c for c in tab.columns if c.startswith("age")]).to_dict(
            "records"
        ),
        "usable_without_gap": no_gap,
        "qqq_exploratory": qqq_test.as_dict(),
    }
    return Job(pid, core, st, extra, {"cpi_QQQ_spearman": qqq_test.p_two})


def recession_job(panel: pd.DataFrame) -> Job:
    days = studies.recession_days(panel, studies.RECESSION_TICKERS)
    main = studies.recession_study(days, "dp")
    sens = studies.recession_study(days, "dlogit")
    return Job("us_recession", doc=results.recession_result(main, sens))


# ---------------------------------------------------------------- phases 2 and 3


def assemble(jobs: dict[str, Job]) -> tuple[dict[str, ResultsDoc], dict]:
    """BH over the primaries and the exploratory family, then verdicts and contract docs."""
    p_primary = []
    for pid in PRIMARY_ORDER:
        p = jobs[pid].core.p_one if pid in jobs and jobs[pid].core else None
        p_primary.append(1.0 if p is None else p)  # a primary that could not run enters as 1
    reject, adj = models.bh(p_primary, BH_Q)
    family = "the three primary tests (Fed, Bitcoin, inflation)"
    exp_names = [n for j in jobs.values() for n in j.exploratory]
    exp_notes = {n: t for j in jobs.values() for n, t in j.exploratory_notes.items()}
    exp_p = [j.exploratory[n] for j in jobs.values() for n in j.exploratory]
    exp_p = [1.0 if (p is None or not np.isfinite(p)) else p for p in exp_p]
    exp_rej, exp_adj = models.bh(exp_p, BH_Q) if exp_p else (np.array([]), np.array([]))
    summary = {
        "primary_family": [
            {"pair_id": pid, "p_one_sided": p, "bh_adjusted": float(a), "reject": bool(r)}
            for pid, p, a, r in zip(PRIMARY_ORDER, p_primary, adj, reject, strict=True)
        ],
        "exploratory_family": [
            {
                "test": n,
                "p_two_sided": p,
                "bh_adjusted": float(a),
                "reject": bool(r),
                **({"note": exp_notes[n]} if n in exp_notes else {}),
            }
            for n, p, a, r in zip(exp_names, exp_p, exp_adj, exp_rej, strict=True)
        ],
        "q": BH_Q,
    }
    builders = {
        "fed_decision": (runners.fed_facts, results.fed_result),
        "bitcoin_monthly_ladder": (runners.btc_facts, results.btc_result),
        "us_cpi_inflation": (runners.cpi_facts, results.cpi_result),
    }
    docs = {}
    for i, pid in enumerate(PRIMARY_ORDER):
        job = jobs.get(pid)
        if job is None or job.core is None:
            continue
        to_facts, to_doc = builders[pid]
        facts = to_facts(job.core, bool(reject[i]), float(adj[i]))
        docs[pid] = to_doc(job.core, facts, {"family": family}, job.studies, job.extra)
    for pid, job in jobs.items():
        if job.doc is not None:
            docs[pid] = job.doc
    return docs, summary


def write_all(docs: dict[str, ResultsDoc], summary: dict, clean_dir: Path) -> None:
    out = clean_dir / "results"
    for pid, doc in docs.items():
        results.write_json({"schema_version": results.SCHEMA_VERSION, **doc}, out / f"{pid}.json")
    results.write_json(summary, out / "summary.json")


# ---------------------------------------------------------------- loading (I/O) and CLI


def _job(pair_id: str, clean_dir: str) -> Job:
    """Load one pair's inputs and run its phase-1 job (runs in a worker process)."""
    cfg = pipeline.load_config()
    panel = inputs.load_panel(Path(clean_dir), pair_id)
    days = inputs.event_days(cfg)
    if pair_id == "fed_decision":
        return fed_job(panel, days)
    if pair_id == "bitcoin_monthly_ladder":
        return btc_job(panel, inputs.spot_lookup(inputs.pair_inputs(cfg, pair_id)))
    if pair_id == "us_cpi_inflation":
        inp = inputs.pair_inputs(cfg, pair_id)
        tab = inputs.cpi_release_table(cfg, inp)
        cal = inputs.calendar(inp)
        candidates = cpi_mod.placebo_candidates(cal.sessions, days["cpi"] | days["fomc"])
        in_data = set(sample.build_grid(panel, pair_id).sessions)
        candidates = [d for d in candidates if d in in_data]
        return cpi_job(panel, tab, inputs.cpi_placebo_table(inp, candidates))
    return recession_job(panel)


def _result_of(pair_id: str, future: Future[Job]) -> Job:
    """A worker's job, re-raising its error with the pair named."""
    try:
        return future.result()
    except Exception as exc:
        raise RuntimeError(f"analysis job for pair {pair_id!r} failed") from exc


def cmd_run(args: argparse.Namespace) -> int:
    """Run every pair, apply BH and the verdicts, write the results JSON."""
    pairs = (*PRIMARY_ORDER, "us_recession")
    if args.workers > 1:
        with ProcessPoolExecutor(max_workers=args.workers) as pool:
            futures = {p: pool.submit(_job, p, args.clean_dir) for p in pairs}
            jobs = {p: _result_of(p, f) for p, f in futures.items()}
    else:
        jobs = {p: _job(p, args.clean_dir) for p in pairs}
    docs, summary = assemble(jobs)
    summary["code_commit"] = code_version()
    write_all(docs, summary, Path(args.clean_dir))
    for pid, doc in docs.items():  # stdout on purpose: the CLI's result; logging is diagnostics
        print(f"{pid}: {doc['verdict']} ({doc['confidence']['level']})")
    return 0


def code_version() -> str:
    """Short commit of the checked-out code, with '-dirty' when src/ or config/ has uncommitted
    changes; 'unknown' without git."""

    def git(*cmd: str) -> str:
        out = subprocess.run(  # noqa: S603 (fixed argv, no shell)
            ["git", *cmd], cwd=ROOT, capture_output=True, text=True, check=True, timeout=30
        )
        return out.stdout.strip()

    try:
        sha = git("rev-parse", "--short", "HEAD")
        dirty = git("status", "--porcelain", "--", "src", "config")
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return f"{sha}-dirty" if dirty else sha


def cmd_report(args: argparse.Namespace) -> int:
    """Render docs/findings.md from the results files."""
    try:
        out = findings.write_report(Path(args.clean_dir), load_pair_specs(), Path(args.out))
    except FileNotFoundError as exc:
        print(f"report: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {out}")
    return 0


def cmd_counts(args: argparse.Namespace) -> int:
    """Sample sizes from flags and presence only."""
    clean = Path(args.clean_dir)
    for pid, ticker, lags in (
        ("fed_decision", "TLT", primary.FED_LAGS),
        ("bitcoin_monthly_ladder", "IBIT", primary.BTC_LAGS),
    ):
        grid = sample.build_grid(inputs.load_panel(clean, pid), pid)
        ok = sample.design_mask(grid, lags, grid.returns[ticker])
        print(f"{pid}: {int(ok.sum())} rows in {int(ok.any(axis=1).sum())} sessions")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="poly_actor.analysis", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run the step 6 analysis and write results JSON")
    run.add_argument("--workers", type=int, default=1, help="parallel pair jobs")
    run.add_argument("--clean-dir", default=str(CLEAN_DIR))
    run.set_defaults(func=cmd_run)
    cnt = sub.add_parser("counts", help="sample sizes from flags only")
    cnt.add_argument("--clean-dir", default=str(CLEAN_DIR))
    cnt.set_defaults(func=cmd_counts)
    rep = sub.add_parser("report", help="render docs/findings.md from the results JSON")
    rep.add_argument("--clean-dir", default=str(CLEAN_DIR))
    rep.add_argument("--out", default=str(findings.FINDINGS_PATH), help="markdown output path")
    rep.set_defaults(func=cmd_report)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
