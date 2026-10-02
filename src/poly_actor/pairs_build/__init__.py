"""Builds config/pairs.yaml from cached Polymarket Gamma dumps (step 2 tooling).

CLI wrapper: scripts/build_pairs.py. Modules: gamma (cached, polite Gamma client), slugs
(ground-truth slug tables), calendars (official FOMC / BLS dates), fed, recession, btc, cpi
(one builder per pair), emit (assemble and write the yaml), consts, util.
"""
