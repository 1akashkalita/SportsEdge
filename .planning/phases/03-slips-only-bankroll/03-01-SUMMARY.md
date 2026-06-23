---
phase: 03-slips-only-bankroll
plan: 01
subsystem: bankroll
tags: [stake-sizing, confidence-stake, bankroll, slip, dfs, pure-functions, unit-tests]

# Dependency graph
requires: []
provides:
  - "scripts/stake_sizing.py: confidence_stake() + apply_confidence_stakes() pure staking helpers"
  - "scripts/test_stake_sizing.py: unit tests covering D-03/D-04/D-05/D-06 tiers, EV gate, zero-floor, monotonicity"
affects:
  - "03-02 (forward daily bankroll path): imports confidence_stake from stake_sizing"
  - "03-03 (historical rebuild): imports apply_confidence_stakes from stake_sizing"
  - "03-04 (bankroll rebase): stake_sizing is the Wave-0 scaffold all later plans build on"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Stateless pure-math module (slip_payouts.py analog): no runner import, no side effects at import time"
    - "EV gate checked FIRST (D-05), then zero-floor (D-04), then tiers (D-03) — branch order is the contract"
    - "None-coercion via float(x or 0) in batch helper (T-03-02 mitigation)"
    - "Test structure: unittest.TestCase with _stake() helper + one test per D-NN behavior"

key-files:
  created:
    - scripts/stake_sizing.py
    - scripts/test_stake_sizing.py
  modified: []

key-decisions:
  - "D-01 fence: confidence_stake() accepts exactly 3 numeric params; never inspects slip category/slip_type/leg_count"
  - "D-05 EV gate before D-04 zero-floor: combined_ev_score <= 0 gates to zero before prob check"
  - "D-03 tiers: >=0.75->2.5%, >=0.65->1.5%, >=0.58->0.75% of start_of_day_bankroll; all lower boundaries inclusive"
  - "D-06 monotonicity holds by construction (tier ordering guarantees higher prob >= stake of lower prob)"

patterns-established:
  - "confidence_stake(combined_probability, combined_ev_score, start_of_day_bankroll) -> float"
  - "apply_confidence_stakes(slips, start_of_day_bankroll) -> list[dict[str, Any]] with stake_units set"

requirements-completed: [BANKROLL-02]

# Metrics
duration: 2min
completed: 2026-06-23
---

# Phase 3 Plan 01: Stake Sizing Module Summary

**Deterministic tiered-percentage staking helper (D-02..D-06): EV gate + probability tiers mapping slips to 0/0.75%/1.5%/2.5% of start-of-day bankroll**

## Performance

- **Duration:** 2 min
- **Started:** 2026-06-23T02:46:07Z
- **Completed:** 2026-06-23T02:48:12Z
- **Tasks:** 2 completed
- **Files modified:** 2 created

## Accomplishments

- Created `scripts/stake_sizing.py`: pure stateless module with `confidence_stake()` and `apply_confidence_stakes()`; no runner dependency, no import-time side effects
- Implemented exact D-02..D-06 staking rule: EV gate first (D-05), zero-floor (D-04), then 3 tiers at their inclusive lower boundaries (D-03); D-06 monotonicity guaranteed by construction
- Created `scripts/test_stake_sizing.py`: 7 unit tests including the 4 validation-named tests (test_confidence_stake_tiers, test_monotonicity, test_ev_gate, test_zero_floor); all green

## Task Commits

Each task was committed atomically:

1. **Task 1: Implement stake_sizing.py confidence_stake + apply_confidence_stakes** - `bc7a52f` (feat)
2. **Task 2: Write test_stake_sizing.py covering tiers, zero-floor, EV gate, monotonicity** - `93128c6` (test)

## Files Created/Modified

- `/Users/akashkalita/sports_picks/scripts/stake_sizing.py` - Pure stateless staking helper: `confidence_stake()` + `apply_confidence_stakes()`, no runner import, no side effects
- `/Users/akashkalita/sports_picks/scripts/test_stake_sizing.py` - 7 unit tests covering all D-NN behaviors; 4 validation-named tests match 03-VALIDATION.md requirements exactly

## Decisions Made

- Followed plan as specified; branch order (EV gate first, then zero-floor, then tiers) is the central correctness contract
- D-01 fence maintained: `confidence_stake()` takes only 3 numeric parameters, never inspects slip category, slip_type, or leg_count
- `apply_confidence_stakes()` coerces None signals to 0.0 via `float(x or 0)` (T-03-02 mitigation per threat model)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. Grep for "slip_type|leg_count|category" in stake_sizing.py returned only docstring comment lines (not function logic), confirming D-01 fence intact.

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. This plan is a pure stateless math module with no I/O.

## Known Stubs

None - `stake_sizing.py` is fully implemented; no hardcoded placeholders, no TODO/FIXME, no empty return values.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- `scripts/stake_sizing.py` is ready to import by 03-02, 03-03, and 03-04 plans
- `confidence_stake()` public API: `confidence_stake(combined_probability: float, combined_ev_score: float, start_of_day_bankroll: float) -> float`
- `apply_confidence_stakes()` public API: `apply_confidence_stakes(slips: list[dict[str, Any]], start_of_day_bankroll: float) -> list[dict[str, Any]]`
- Tests in `test_stake_sizing.py` cover BANKROLL-02 / D-03 / D-04 / D-05 / D-06 with explicit named test methods matching 03-VALIDATION.md contract

---
*Phase: 03-slips-only-bankroll*
*Completed: 2026-06-23*

## Self-Check: PASSED
