---
phase: 04-dual-metrics-and-feedback
type: fix
warnings_addressed: [WR-01, WR-02]
files_modified:
  - scripts/calibration.py
  - scripts/test_weekly_metrics.py
commits:
  red: 2cc74dc
  green: eb6efcf
date: 2026-06-23
---

# Phase 4 WR-01 / WR-02 Fix Summary

One-liner: Fixed calibration population mismatch (WR-01) and non-idempotent
stepping (WR-02) in calibration.py using TDD RED/GREEN commits.

## WR-01 — Population mismatch between gate/empirical and model_implied

**Root cause:** `read_graded_outcomes_for_sport` incremented wins/losses for
every graded WIN/LOSS row, but only appended to `mop_values` for rows with a
parseable MOP. This caused `empirical = wins/(wins+losses)` (over all N rows) to
diverge from `model_implied = mean(mop_values)` (over only the MOP-backed subset),
making `raw_ratio` a biased estimate. Additionally `compute_calibration_target`
gated on `n_outcomes` (total rows) not `n_with_mop` (MOP-backed rows), so the
gate could pass on 30 total rows while only 3 carried MOP.

**Fix — `read_graded_outcomes_for_sport`:**
- Moved win/loss increment inside the MOP-parse success block. After the fix,
  `wins + losses == len(mop_values) == n_with_mop` always.
- Added `n_total_graded` counter (every WIN/LOSS PROP row regardless of MOP)
  returned for informational audit use. It does NOT affect gating.

**Fix — `compute_calibration_target`:**
- Gate now fires on `n_with_mop` (not `n_outcomes`).
- `empirical` is computed over `n_with_mop` — same denominator as `model_implied`.
- `n_total_graded` propagated through to audit dict (optional kwarg, default 0
  for backward compatibility with direct callers).
- Docstrings updated to state MOP-backed population requirement explicitly.

**Safety properties preserved:** bounded-step (MAX_STEP=0.05), clamp
[CLAMP_LO, CLAMP_HI], gate (N_GATE=30) — all unchanged.

## WR-02 — Non-idempotent stepping on unchanged data

**Root cause:** `compute_and_update_calibration` stepped the factor by up to
MAX_STEP on every invocation. Re-running the weekly_metrics cron the same week
(e.g. a retry) would double-step the factor even though no new graded data arrived.
The docstring claimed idempotence that did not exist.

**Fix — data-fingerprint guard:**
- `write_calibration_json`: accepts optional `fingerprints` dict and persists it
  under a `"fingerprints"` key in calibration.json alongside factors and audit.
  `load_calibration_factor` reads only `"factors"` — fully backward-compatible.
- `_load_last_fingerprint`: new private helper reads `(wins, losses, n_with_mop)`
  for a sport from the persisted fingerprints block.
- `compute_and_update_calibration`: before stepping, compares freshly read
  `(wins, losses, n_with_mop)` against the last persisted fingerprint. If identical
  ("no new graded data since last calibration"), keeps existing factor unchanged.
  If fingerprint differs, steps as before. Docstring corrected.

**Idempotence guarantee:** re-running on unchanged data leaves the factor and the
calibration.json `"factors"` block byte-identical (except `"updated_at"` timestamp
and a new audit entry with reason "no new graded data since last calibration").

## TDD gate compliance

| Gate | Commit | Test class |
|------|--------|-----------|
| RED  | 2cc74dc | TestCalibrationGateNotMet.test_wr01_* (2 tests), TestIdempotentStepping (2 tests) |
| GREEN | eb6efcf | All 4 RED tests now pass; 0 pre-existing tests broken |

## Existing test updates

No existing tests encoded the buggy behaviour (all existing TestCalibrationGateNotMet
and TestCalibrationFormula tests pass wins/losses equal to len(mop_values), so they
remained valid with the corrected semantics). No test modifications were required
beyond adding the new RED tests.

## Final verification counts

- `test_weekly_metrics.py`: **43 passed, 3 skipped** (46 total)
- `test_metrics_report.py`: **32 passed** (32 total)
- `python3 -c "import calibration, generate_projections"`: clean import

## Files changed

- `scripts/calibration.py` — production fix (WR-01 + WR-02)
- `scripts/test_weekly_metrics.py` — 4 new RED tests (now passing GREEN)

No other files were touched.
