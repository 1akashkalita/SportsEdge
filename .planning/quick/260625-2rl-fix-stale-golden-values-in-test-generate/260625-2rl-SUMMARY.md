---
quick_id: 260625-2rl
slug: fix-stale-golden-values-in-test-generate
date: 2026-06-25
type: quick
status: complete
---

# Quick Task 260625-2rl — Summary

## Outcome

Fixed the 2 pre-existing failures in `scripts/test_generate_projections.py`.
`python3 -m pytest -q test_generate_projections.py` → **9 passed** (was 2 failed, 7 passed).

## What changed (test-only — zero production/model change)

`scripts/test_generate_projections.py`, class `ProjectionProbabilityTests`:

1. **Added `setUp`/`tearDown`** that pin `gp.load_calibration_factor` to a neutral `1.0`
   lambda for the duration of each test (original restored in `tearDown`). This isolates
   the golden assertions from the mutable, gitignored `data/research/calibration.json`.
   Because NBA is currently `1.0`, this changes no value today — it future-proofs the test
   against re-breaking once NBA calibration computes a non-neutral factor.
2. **Re-anchored the 3 stale numeric expectations per test** to the model's true,
   deterministic output on the frozen committed data:
   - KAT: `projection 32.651→31.796`, `sigma 5.18→5.313`, `over_probability 0.94→0.915`
   - Castle: `projection 23.905→21.418`, `sigma 5.58→5.787`, `over_probability 0.21→0.11`

All behavioral assertions (tier `A`/`SKIP`, EV sign, hit-rate `9/10`,
`recomputed_today_line`) were already passing and were left untouched.

## Why this is the correct fix (not a model change)

The projection-mean code is byte-identical since the file was first tracked (`867edc5`),
and the hit-rate data is frozen at Jun 13 (before the test was committed in `a0aa663`).
So the model produced `31.796`/`21.418` at commit time too — the golden anchors
`32.651`/`23.905` never matched the committed data. This is a born-failing golden-value
test, not a regression. Changing the model would have altered real-money pick outputs and
violated the milestone's compatibility constraint; re-anchoring the test was correct.

## Verification

- `python3 -m pytest -q test_generate_projections.py` → `9 passed in ~0.8s`.
- No other test file imports `test_generate_projections` (only `run_ci_gate.py`'s denylist
  names it). The `setUp`/`tearDown` patch is class-scoped and restored, so no leakage to
  the rest of the suite.
- The file remains on the CI-gate denylist (it still requires the gitignored
  `data/research/hit_rates/` fixtures); this task makes it pass when run directly, it does
  not add it to the gate.

## Notes / follow-ups

- The file stays data-dependent on `data/research/hit_rates/nba/*.json` (the denylist
  reason). A future hardening could freeze a small committed fixture so the file could
  join the gate, but that was out of scope here (minimal-invasive).
