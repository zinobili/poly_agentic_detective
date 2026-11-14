# Study 1: Polymarket odds vs related stocks (`leadlag`)

**Question.** Do Polymarket odds lead, lag, or move with related stocks?
**Status.** Done (2026-10-08). **Answer.** [`findings.md`](findings.md), generated from the results.

| Piece | Where |
|---|---|
| Plan and frozen tests | [`plan.md`](plan.md), [`preregistration.md`](preregistration.md) |
| Pairs and their rationale | [`config/leadlag/pairs.yaml`](../../../config/leadlag/pairs.yaml), built by `scripts/build_pairs.py`; notes in [`step2_pairs.md`](step2_pairs.md) |
| Data notes | [`step1_data_check.md`](step1_data_check.md), [`step3_ingestion.md`](step3_ingestion.md) |
| Code | `src/poly_actor/studies/leadlag/` (`ingest`, `pairs_build`, `align`, `analysis`, `dashboard`, `refresh`) |
| Step hand-offs and reviews | [`handoff/`](handoff/), [`reviews/`](reviews/) |
| Dashboard design | [`design/dashboard_ux.md`](design/dashboard_ux.md) |

```bash
python -m poly_actor.studies.leadlag.refresh --workers 4   # ingest -> align -> analysis -> report
streamlit run src/poly_actor/studies/leadlag/dashboard/app.py
```

Data for this study sits at the top of `data/raw/` and `data/clean/` (it predates the per-study
data folders).
