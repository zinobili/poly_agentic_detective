"""Regenerate config/pairs.yaml from cached Gamma API dumps.

Step 2 (pick pairs) tooling for milestone 1. This script is the single
source of truth for how `config/pairs.yaml` was built: every market slug,
CLOB token id, volume and date in the yaml traces back to a JSON file in
`data/scratch/step2/` written by this script.

Usage (from repo root):
    python scripts/build_pairs.py              # build only, fully offline from cache
    python scripts/build_pairs.py --refetch     # refresh the whole cache, then build
    python scripts/build_pairs.py --fetch-slugs SLUG [SLUG ...]  # fetch just these events

`--refetch` re-pulls everything from the live Gamma API
(https://gamma-api.polymarket.com): polite (0.5s sleep between calls,
exponential backoff retry on 429/5xx), and paginates every tag-based event
listing to exhaustion (`offset` steps of 100 until a short/empty page comes
back) -- the step-2 validator flagged that un-paginated listings silently
truncated at the API's page-size default (50 or 100), which caused several
real meetings/months to be missed in the first draft. Without `--refetch`,
the script only reads what's already cached in `data/scratch/step2/` (fully
offline, safe to re-run); a cache miss RAISES `CacheMiss` instead of silently
touching the network (use `--fetch-slugs` for a targeted fetch).

`data/scratch/step2/` (not `data/raw/`) is used deliberately: these are
step-2 research/discovery dumps, not the project's immutable ingestion
store. `data/raw/` is reserved for the production `ingest/` modules built in
step 3 (see CLAUDE.md's "Raw data is immutable" rule) and this script must
never write there.

Important data-quality notes baked into this script (see docs/step2_pairs.md
and docs/preregistration.md for the full writeup):
  - Gamma event `endDate` is NOT the announcement/release time for either
    the Fed or CPI series -- it is set some hours (sometimes most of a day)
    *before* the actual 2pm ET FOMC statement / 8:30am ET BLS release. Roll
    timing for both series uses hardcoded tables of the official FOMC / BLS
    dates (ET -> UTC through zoneinfo, DST-correct), not `endDate` and not the
    `closed` flag (which reflects current state and is a look-ahead risk).
    Every hardcoded time is cross-checked against the earliest market
    `closedTime` in the cache; a mismatch aborts the build.
  - Signals are spliced from *changes*, never from level differences taken
    across two different underlying events (see `splice_rule` in the
    emitted yaml).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from poly_actor.pairs_build.emit import build_pairs_yaml
from poly_actor.pairs_build.gamma import GammaClient, refetch_all

REPO_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = REPO_ROOT / "data" / "scratch" / "step2"
CONFIG_OUT = REPO_ROOT / "config" / "pairs.yaml"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--refetch",
        action="store_true",
        help="re-pull EVERYTHING from the live Gamma API, then build",
    )
    parser.add_argument(
        "--fetch-slugs",
        nargs="+",
        default=[],
        metavar="SLUG",
        help="fetch only these event slugs from Gamma (cache miss or refresh), then build",
    )
    args = parser.parse_args(argv)
    gamma = GammaClient(CACHE_DIR, refetch=args.refetch, fetch_slugs=set(args.fetch_slugs))
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Offline by default: a cache miss raises CacheMiss instead of touching the network.
    if gamma.refetch:
        print("--refetch: bypassing cache, re-pulling everything", file=sys.stderr)
        refetch_all(gamma)
    build_pairs_yaml(gamma, CONFIG_OUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
