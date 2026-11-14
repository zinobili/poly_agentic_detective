"""Fixtures shared by the lead-lag study tests."""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def analysis_written(tmp_path_factory) -> tuple[Path, dict, dict]:
    """Every pair's phase-1 job on synthetic panels, assembled and written once per session
    (about 40 s): (clean dir, docs by pair id, summary)."""
    import analysis_synth as synth
    from poly_actor.studies.leadlag.analysis import run

    clean = tmp_path_factory.mktemp("clean")
    docs, summary = run.assemble(synth.all_jobs())
    run.write_all(docs, summary, clean)
    return clean, docs, summary
