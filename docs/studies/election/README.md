# Study 2: the partisan beta of AI (`election`)

**Question.** Did AI stocks move with the odds that Democrats take Congress, beyond the broad
market, and did each stock's pre-election sensitivity say which names would reprice on election
night (2026 US midterm)?
**Status.** Done (2026-11-14). **Answer.** [`findings.md`](findings.md), generated from the results.

| Piece | Where |
|---|---|
| Frozen plan and amendments A1–A3 | [`preregistration.md`](preregistration.md) |
| Signals, universe and rationale | [`config/election/election.yaml`](../../../config/election/election.yaml) |
| Code | `src/poly_actor/studies/election/` |
| Published results bundle | `reports/election/` (tracked; derived aggregates only) |
| Step hand-offs and reviews | [`handoff/`](handoff/), [`reviews/`](reviews/) |
| Screenshots | [`images/`](images/) |

```bash
streamlit run src/poly_actor/studies/election/app.py        # reads reports/election/
python -m poly_actor.studies.election report                # bundle -> findings.md
python -m poly_actor.studies.election ingest --workers 4    # rebuild from scratch: then
python -m poly_actor.studies.election panel                 #   panel, analyse, publish
```
