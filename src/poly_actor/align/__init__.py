"""Step 4: align Polymarket signals and stock bars into one hourly UTC panel per pair.

Pure functions live in `prices`, `grid`, `events`, `signals`, `evaluate`, `stocks` and
`panel`; `cli` is the thin I/O wrapper (`python -m poly_actor.align run|report`).
Outputs are derived data under data/clean/ and can be rebuilt at any time.
"""
