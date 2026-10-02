"""Offline tests for the ingest CLI: run/report wiring, exit codes, dry-run, worker passthrough.

`RAW_DIR` and the scratch dir are redirected to tmp_path; the run functions are replaced by
recording fakes (or, for dry-run, the real ones, which must not fetch or write)."""

from __future__ import annotations

import pandas as pd
import pytest

from poly_actor.ingest import cli, polymarket, stocks, targets
from poly_actor.ingest.common import write_parquet_once


@pytest.fixture
def env(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    monkeypatch.setattr(cli, "RAW_DIR", raw)
    monkeypatch.setattr(cli, "SCRATCH", tmp_path / "scratch")
    return raw


@pytest.fixture
def fakes(monkeypatch):
    calls: dict[str, list] = {"pm": [], "st": []}

    def fake_pm(specs, **kw):
        calls["pm"].append((specs, kw))
        return polymarket.RunStats(calls=2, rows=5)

    def fake_st(tickers, wstart, **kw):
        calls["st"].append((tickers, kw))
        return stocks.StockStats(calls=1, rows=3)

    monkeypatch.setattr(polymarket, "run_polymarket", fake_pm)
    monkeypatch.setattr(stocks, "run_stocks", fake_st)
    return calls


ASOF = "2026-10-01T12:00:00Z"


def test_unknown_pair_exits_2(env, fakes, capsys):
    assert cli.main(["run", "--pairs", "nope", "--asof", ASOF]) == 2
    assert "unknown pair" in capsys.readouterr().out
    assert fakes == {"pm": [], "st": []}


def test_naive_asof_exits_2(env, fakes, capsys):
    assert cli.main(["run", "--asof", "2026-10-01T12:00:00"]) == 2
    assert "tz-aware" in capsys.readouterr().out
    assert fakes == {"pm": [], "st": []}


def test_held_lock_exits_3(env, fakes, capsys):
    env.mkdir(parents=True)
    (env / ".ingest.lock").write_text("pid=1\n")
    assert cli.main(["run", "--asof", ASOF]) == 3
    assert "another ingest run" in capsys.readouterr().out
    assert fakes["pm"] == []
    assert (env / ".ingest.lock").exists()  # the other run's lock is left alone


def test_dry_run_makes_no_calls_and_no_writes(env, tmp_path, capsys):
    # real run functions: with dry_run they must neither fetch (network is blocked) nor write
    assert cli.main(["run", "--dry-run", "--asof", ASOF, "--workers", "2"]) == 0
    out = capsys.readouterr().out
    assert "DRY RUN" in out and "TOTAL planned calls" in out and "2 workers" in out
    assert not env.exists()
    assert not (tmp_path / "scratch").exists()


def test_dry_run_takes_no_lock(env, fakes):
    env.mkdir(parents=True)
    (env / ".ingest.lock").write_text("pid=1\n")
    assert cli.main(["run", "--dry-run", "--asof", ASOF]) == 0
    assert all(kw["dry_run"] for _, kw in fakes["pm"] + fakes["st"])


def test_workers_passed_to_polymarket_only(env, fakes):
    assert cli.main(["run", "--asof", ASOF, "--workers", "7"]) == 0
    assert fakes["pm"], "polymarket run expected"
    assert all(kw["workers"] == 7 for _, kw in fakes["pm"])
    assert all("workers" not in kw for _, kw in fakes["st"])


def test_only_stocks_skips_polymarket_and_backfill(env, fakes):
    assert cli.main(["run", "--asof", ASOF, "--only", "stocks"]) == 0
    assert fakes["pm"] == [] and len(fakes["st"]) == 1
    assert fakes["st"][0][1]["pause"] >= 0.5  # stocks pause floor


def test_no_backfill_runs_polymarket_once(env, fakes):
    assert cli.main(["run", "--asof", ASOF, "--only", "polymarket", "--no-backfill"]) == 0
    assert len(fakes["pm"]) == 1 and fakes["st"] == []


def test_failures_exit_1_and_are_listed(env, monkeypatch, capsys):
    def failing(specs, **kw):
        return polymarket.RunStats(failures=[{"token_id": "tok1", "error": "boom"}])

    monkeypatch.setattr(polymarket, "run_polymarket", failing)
    assert cli.main(["run", "--asof", ASOF, "--only", "polymarket", "--no-backfill"]) == 1
    assert "failed: tok1 boom" in capsys.readouterr().out


def test_report_counts_rows_per_pair(env, capsys):
    cfg = cli._load_cfg()
    specs = targets.build_token_specs(cfg, 2_000_000_000)
    sp = next(s for s in specs if s.fidelity == 60)
    t0 = 1_760_000_000
    df = pd.DataFrame({"t": [t0, t0 + 3600], "p": [0.4, 0.5]})
    df.insert(1, "ts", pd.to_datetime(df["t"], unit="s", utc=True))
    assert write_parquet_once(df, polymarket.raw_path(env, sp.token_id, 60, t0, t0 + 7200))
    assert cli.main(["report"]) == 0
    out = capsys.readouterr().out
    assert "pair, fidelity, tokens_with_data, rows, first_ts, last_ts" in out
    assert f"{sorted(sp.pairs)[0]}, 60, 1, 2, " in out
    assert "ticker, rows, nan_rows, first_ts, last_ts" in out
    assert "manifest statuses: {}" in out
