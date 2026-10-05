"""End-to-end on a tiny synthetic raw directory: idempotent output, raw untouched, CLI wiring."""

import hashlib
from pathlib import Path

import pandas as pd
import pytest

from align_synth import bars_for, ep, hourly_obs
from poly_actor.align import cli, pipeline
from poly_actor.align.grid import load_sessions

START, END = "2025-01-13T00:00:00Z", "2025-01-17T00:00:00Z"
TOKEN = "123456789"


def tiny_config() -> dict:
    return {
        "pairs": [
            {
                "id": "us_recession",
                "tickers": ["TLT"],
                "coverage": {"stock_window_start_utc": START},
                "roll_rule": {"roll_utc": "2025-01-15T00:00:00Z"},
                "markets": [
                    {
                        "period": "first",
                        "token_id_yes": TOKEN,
                        "start": START,
                        "end": "2025-01-20T00:00:00Z",
                        "closed_time": None,
                    },
                    {
                        "period": "second",
                        "token_id_yes": TOKEN,
                        "start": START,
                        "end": "2025-01-20T00:00:00Z",
                        "closed_time": None,
                    },
                ],
            }
        ]
    }


def write_raw(raw: Path) -> None:
    sessions = load_sessions(ep(START), ep(END))
    bars = bars_for("TLT", sessions, lambda s: 100.0 + (s % 7), lambda s: 100.5 + (s % 7))
    bars["high"], bars["low"], bars["volume"] = 1.0, 1.0, 1.0
    (raw / "stocks" / "TLT").mkdir(parents=True)
    bars.drop(columns="ticker").to_parquet(raw / "stocks" / "TLT" / "a.parquet", index=False)
    pm = hourly_obs(TOKEN, ep(START), ep(END), lambda t: 0.1 + 0.0001 * ((t - ep(START)) // 3600))
    pm["ts"] = pd.to_datetime(pm["t"], unit="s", utc=True)
    folder = raw / "polymarket" / TOKEN / "fid=60"
    folder.mkdir(parents=True)
    pm[["t", "ts", "p"]].to_parquet(folder / "a.parquet", index=False)


def tree_hash(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


@pytest.fixture
def raw_dir(tmp_path: Path) -> Path:
    raw = tmp_path / "raw"
    write_raw(raw)
    return raw


def test_run_twice_gives_identical_files_and_leaves_raw_untouched(raw_dir, tmp_path):
    clean = tmp_path / "clean"
    raw_before = tree_hash(raw_dir)
    con = pipeline.connect_raw(raw_dir)
    pipeline.run_pair(tiny_config(), "us_recession", con, clean)
    first = tree_hash(clean)
    pipeline.run_pair(tiny_config(), "us_recession", con, clean)
    assert tree_hash(clean) == first and list(first) == ["panel_us_recession.parquet"]
    assert tree_hash(raw_dir) == raw_before


def test_panel_covers_the_window_and_has_the_documented_columns(raw_dir, tmp_path):
    con = pipeline.connect_raw(raw_dir)
    panel, diag = pipeline.run_pair(tiny_config(), "us_recession", con, tmp_path / "clean")
    assert diag["unmatched_bars"] == 0
    for column in (
        "ts_end",
        "signal_level",
        "signal_change",
        "roll_hour",
        "both_trading",
        "ret_TLT",
    ):
        assert column in panel
    assert panel["ts_end"].dt.tz is not None and str(panel["ts_end"].dt.tz) == "UTC"
    assert panel["roll_hour"].sum() == 1
    assert panel["both_trading"].any()


def test_cli_rejects_an_unknown_pair(capsys):
    assert cli.main(["run", "--pairs", "nope"]) == 2
    assert "unknown pair" in capsys.readouterr().out


def test_cli_report_without_panels_explains_what_to_do(tmp_path, capsys):
    assert cli.main(["report", "--clean-dir", str(tmp_path)]) == 2
    assert "run" in capsys.readouterr().out


def test_cli_report_prints_the_summary_of_an_existing_panel(raw_dir, tmp_path, capsys):
    clean = tmp_path / "clean"
    pipeline.run_pair(tiny_config(), "us_recession", pipeline.connect_raw(raw_dir), clean)
    assert cli.main(["report", "--clean-dir", str(clean)]) == 0
    out = capsys.readouterr().out
    assert "== us_recession" in out and "both_trading_rows" in out


def test_strict_build_never_looks_ahead_and_tolerant_build_uses_the_constant(raw_dir, tmp_path):
    from poly_actor.align import consts

    con = pipeline.connect_raw(raw_dir)
    strict, sdiag = pipeline.run_pair(tiny_config(), "us_recession", con, tmp_path / "c", True)
    tolerant, tdiag = pipeline.run_pair(tiny_config(), "us_recession", con, tmp_path / "c")
    assert sdiag["pm_stamp_tolerance_s"] == 0 and not strict["pm_used_tolerance"].any()
    assert strict["pm_obs_age_s"].min() >= 0
    assert tdiag["pm_stamp_tolerance_s"] == consts.PM_STAMP_TOLERANCE_S == 53
    assert tolerant["pm_used_tolerance"].any() and tolerant["pm_obs_age_s"].min() == -5
    assert (tmp_path / "c" / "panel_us_recession_strict.parquet").exists()
