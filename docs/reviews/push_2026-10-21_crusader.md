# Crusader review: push 2026-10-21 (5199235, feab900, e3b24a0)

**Verdict: SHIP WITH FIXES** (no blockers, 0 majors, 3 minors)

Scores: design 5, readability 5, types 5, errors 5, tests 4, config 5, security 5, perf 5, consistency 5, docs 4.

## Minor
1. `pyproject.toml:27` pins `streamlit>=1.40`, but `src/poly_actor/dashboard/app.py:243` now uses `st.context.theme`, which is newer (about 1.46). Raise the floor to the version that introduced it (installed: 1.65).
2. `src/poly_actor/dashboard/style.py:33` formats CSS with `%`. Any future literal `%` in the CSS (e.g. `width:100%`) raises at runtime. Use `str.replace` tokens, or add a comment. The test checks `"%(" not in css`, which is good.
3. `tests/test_dashboard_app.py:164` tests only `page_css`, not the `main()` wiring to `st.context.theme`. The existing AppTest tests cover that path indirectly. Acceptable.

## README check
- Image paths, LICENSE, docs/findings.md, preregistration.md, handoff/milestone2_backlog.md, .claude/agents, scripts/check.sh and build_pairs.py all exist.
- Commands match code: `refresh --workers/--dry-run`, `ingest run`, `align run`, `analysis run --workers`, `analysis report`.
- Claims match code: Gamma 0.5 s sleep, 100 per page, 120-call budget; yfinance 180-day chunks, 729-day cap, `auto_adjust=False`; SHA-256 manifest; Retry-After handling.
- The `.venv/Scripts/streamlit.exe` path exists.
- Untracked `.claude/launch.json` is not in the diff.
- The PNGs are 20-200 KB, which is fine.

## Good
- The CSS extraction is a clean pure function, parametrised and tested.
- The README diagrams are accurate to the module layout.
- The tests that ran passed (13 in test_dashboard_app.py) and ruff is clean.
- I did not wait for a full `scripts/check.sh` run to finish; it exceeded the timeout.
