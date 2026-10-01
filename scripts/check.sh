#!/usr/bin/env bash
# One command for the standard checks. Used by builders, validators and the main agent.
# Usage: bash scripts/check.sh   (from the repo root; Git Bash on Windows)
set -u
cd "$(dirname "$0")/.."

PY=.venv/Scripts/python.exe; [ -x "$PY" ] || PY=.venv/bin/python; [ -x "$PY" ] || PY=python
RUFF=.venv/Scripts/ruff.exe; [ -x "$RUFF" ] || RUFF=.venv/bin/ruff; [ -x "$RUFF" ] || RUFF=ruff
fail=0
step() { printf '%-28s' "$1"; }

step "pytest (offline)";  out=$("$PY" -m pytest -p no:cacheprovider --color=no 2>&1); rc=$?
echo "$out" | grep -Eo '[0-9]+ (passed|failed|error)[^=]*' | tail -1; [ $rc -eq 0 ] || { fail=1; echo "$out" | tail -20; }

step "ruff check";        "$RUFF" check . -q && echo ok || fail=1
step "ruff format";       "$RUFF" format --check . -q && echo ok || fail=1

step "pairs.yaml rebuild"
if [ -d data/scratch/step2 ]; then
  "$PY" scripts/build_pairs.py >/dev/null 2>&1 \
    && git diff --quiet -- config/pairs.yaml && echo "reproducible" \
    || { echo "DIFFERS (or build failed)"; fail=1; }
else echo "skipped (no data/scratch/step2 cache)"; fi

step "ingest dry-run"
if [ -d data/raw/polymarket ]; then
  "$PY" -m poly_actor.ingest run --dry-run 2>&1 | grep -iE 'planned|calls' | tail -2 | tr '\n' ' '; echo
else echo "skipped (no data/raw)"; fi

[ $fail -eq 0 ] && echo "CHECK: PASS" || echo "CHECK: FAIL"
exit $fail
