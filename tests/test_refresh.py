"""Step 7: the one-command refresh (rules-as-examples rows 6 and 7 of docs/handoff/step7.md)."""

from __future__ import annotations

import sys

import pytest

from poly_actor import refresh

ORDER = ["ingest", "align", "analysis", "report"]


def test_dry_run_prints_four_stages_in_order_and_runs_nothing(monkeypatch, capsys, tmp_path):
    """Row 6: exit 0, the stages in order, no stage module imported or run."""
    monkeypatch.chdir(tmp_path)

    def boom(stage):
        raise AssertionError(f"dry run ran {stage.name}")

    monkeypatch.setattr(refresh, "run_stage", boom)
    for mod in ("poly_actor.ingest.cli", "poly_actor.align.cli"):
        monkeypatch.delitem(sys.modules, mod, raising=False)
    assert refresh.main(["--dry-run"]) == 0
    out = capsys.readouterr().out.splitlines()
    stage_lines = [ln for ln in out if ln.startswith("[")]
    assert [ln.split("] ")[1].split(":")[0] for ln in stage_lines] == ORDER
    assert stage_lines[0].endswith("python -m poly_actor.ingest run --workers 4")
    assert stage_lines[3].endswith("python -m poly_actor.analysis report")
    assert "nothing was run" in out[-1]
    assert "poly_actor.ingest.cli" not in sys.modules  # not even imported
    assert list(tmp_path.iterdir()) == []  # no files written


def test_failed_stage_stops_the_refresh_and_is_named(capsys):
    """Row 7: stage 2 (align) fails -> non-zero exit, stages 3-4 not run, message names it."""
    ran = []

    def runner(stage):
        ran.append(stage.name)
        return 1 if stage.name == "align" else 0

    code = refresh.refresh(dry_run=False, runner=runner)
    assert code != 0
    assert ran == ["ingest", "align"]
    assert "FAILED at stage 2 (align)" in capsys.readouterr().out


def test_a_stage_that_raises_counts_as_failed(monkeypatch, capsys):
    import poly_actor.align.cli as align_cli

    def broken(argv):
        raise RuntimeError("panel build broke")

    monkeypatch.setattr(align_cli, "main", broken)
    stage = refresh.stages()[1]
    assert stage.name == "align"
    assert refresh.run_stage(stage) == 1


def test_argparse_exit_inside_a_stage_is_a_failure(monkeypatch):
    import poly_actor.align.cli as align_cli

    def bad_args(argv):
        raise SystemExit(2)

    monkeypatch.setattr(align_cli, "main", bad_args)
    assert refresh.run_stage(refresh.stages()[1]) == 2


def test_all_stages_succeed():
    ran = []
    assert refresh.refresh(runner=lambda s: ran.append(s.name) or 0, say=lambda _: None) == 0
    assert ran == ORDER


@pytest.mark.parametrize("workers", [1, 8])
def test_workers_reach_ingest_and_analysis(workers):
    argv = {s.name: s.argv for s in refresh.stages(workers)}
    assert argv["ingest"] == ("run", "--workers", str(workers))
    assert argv["analysis"] == ("run", "--workers", str(workers))
    assert argv["align"] == ("run",) and argv["report"] == ("report",)
