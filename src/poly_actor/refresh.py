"""One command refreshes everything: ingest -> align -> analysis run -> findings report.

    python -m poly_actor.refresh [--workers N] [--dry-run]

Each stage is the existing CLI, called in this process with the arguments printed. The first
stage that fails (non-zero exit or an exception) stops the refresh: later stages do not run,
the message names the failed stage, and the exit code is non-zero. `--dry-run` prints the
stages in order and runs nothing: no network, no writes (the stage modules are not even
imported).
"""

from __future__ import annotations

import argparse
import importlib
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

DEFAULT_WORKERS = 4


@dataclass(frozen=True)
class Stage:
    name: str
    package: str  # what a user types after `python -m`
    entry: str  # module whose `main(argv) -> int` runs the stage
    argv: tuple[str, ...]

    @property
    def command(self) -> str:
        return " ".join(("python -m", self.package, *self.argv))


def stages(workers: int = DEFAULT_WORKERS) -> tuple[Stage, ...]:
    w = ("--workers", str(workers))
    return (
        Stage("ingest", "poly_actor.ingest", "poly_actor.ingest.cli", ("run", *w)),
        Stage("align", "poly_actor.align", "poly_actor.align.cli", ("run",)),
        Stage("analysis", "poly_actor.analysis", "poly_actor.analysis.run", ("run", *w)),
        Stage("report", "poly_actor.analysis", "poly_actor.analysis.run", ("report",)),
    )


def run_stage(stage: Stage) -> int:
    """Run one stage's CLI; its exit code, or 1 if it raised."""
    try:
        main = importlib.import_module(stage.entry).main
        code = main(list(stage.argv))
    except SystemExit as exc:  # argparse errors and explicit exits
        code = exc.code if isinstance(exc.code, int) else 1
    except Exception:
        log.exception("stage %r raised", stage.name)
        return 1
    return int(code or 0)


def refresh(
    workers: int = DEFAULT_WORKERS,
    dry_run: bool = False,
    runner: Callable[[Stage], int] = run_stage,
    say: Callable[[str], None] = print,
) -> int:
    plan = stages(workers)
    for i, stage in enumerate(plan, 1):
        say(f"[{i}/{len(plan)}] {stage.name}: {stage.command}")
        if dry_run:
            continue
        code = runner(stage)
        if code != 0:
            say(
                f"refresh FAILED at stage {i} ({stage.name}) with exit code {code}; "
                "later stages were not run"
            )
            return code
    say("dry run: nothing was run, fetched or written" if dry_run else "refresh done")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="poly_actor.refresh", description=__doc__)
    parser.add_argument(
        "--workers", type=int, default=DEFAULT_WORKERS, help="parallel workers (ingest, analysis)"
    )
    parser.add_argument("--dry-run", action="store_true", help="print the stages; run nothing")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    return refresh(args.workers, args.dry_run)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
