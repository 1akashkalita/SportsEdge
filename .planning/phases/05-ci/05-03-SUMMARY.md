---
phase: 05-ci
plan: "03"
subsystem: testing
tags: [pytest, fault-injection, ci, regression-proof, slip-payouts]

# Dependency graph
requires:
  - phase: 05-ci plan 01
    provides: run_ci_gate.py gate that this proof drives RED then GREEN

provides:
  - "Criterion-3 deliberate-regression proof: repro_ci_regression.py proves the CI gate catches a real regression"
  - "RES-04 fault-injection-by-construction harness with tri-state exit codes and guaranteed revert"

affects: []

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fault-injection-by-construction: harness injects one-line fault, drives gate RED, reverts unconditionally via finally, drives gate GREEN — cannot pass by accident"
    - "Tri-state exit codes: 0=PASS, 1=INFRA-FAIL, 2=REGRESSION-NOT-CAUGHT"
    - "Guaranteed revert: finally block restores original bytes and verifies byte-identity before post-revert gate run"

key-files:
  created:
    - scripts/repro_ci_regression.py
  modified: []

key-decisions:
  - "Target: slip_payouts._clean_slip_type() line 37 — well-tested (6 power-slip assertions in test_slip_payouts.py which is NOT in DENYLIST); one-line fault (return 'FAULT_INJECTED') breaks all power payout lookups"
  - "Timeout set to 3600s (60 min) after empirically measuring fault-injected run at 1687.49s (28:07) and 1925.01s (32:05) across two runs — 28 min headroom above worst observed"
  - "In-place source edit (not monkeypatch) chosen for fault injection to guarantee the gate subprocess sees the mutation without interpreter-level bypasses"

patterns-established:
  - "Criterion-3 proof pattern: inject fault → gate RED → revert → gate GREEN; by-construction so it cannot pass without gate surfacing the regression"

requirements-completed: [CI-01]

# Metrics
duration: 57min
completed: 2026-06-21
---

# Phase 5 Plan 03: Criterion-3 Deliberate-Regression Fault-Injection Proof Summary

**Fault-injection harness (repro_ci_regression.py) proves CI gate catches a deliberate regression in slip_payouts._clean_slip_type: gate exits 1 (RED, 6 failures) on fault, exits 0 (GREEN, 276 passed) after revert**

## Performance

- **Duration:** 57 min (gate runs: RED 28:07, GREEN 27:36)
- **Started:** 2026-06-21T18:21:00Z
- **Completed:** 2026-06-21T19:17:07Z
- **Tasks:** 1
- **Files modified:** 1

## Accomplishments

- Created `scripts/repro_ci_regression.py` — a fault-injection-by-construction harness with RES-04 rigor that CANNOT pass without the gate catching the regression
- RED gate confirmed: fault (`return "FAULT_INJECTED"`) injected into `slip_payouts._clean_slip_type()` caused 6 failures in `test_slip_payouts.py` (all power-slip payout assertions failed with `MANUAL REVIEW != GRADED`); gate exited 1 in 1687.49s (28:07)
- Revert confirmed byte-identical: `finally` block restored original bytes; `git diff` shows no residual change to `slip_payouts.py`
- GREEN gate confirmed: after revert, gate exited 0 in 1656.61s (27:36) — 276 passed, 2 subtests passed
- ROADMAP success criterion 3 satisfied: deliberate regression in a tested code path causes CI gate to fail and surface the failure

## Task Commits

1. **Task 1: Criterion-3 deliberate-regression fault-injection harness** - `af87585` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `scripts/repro_ci_regression.py` - Fault-injection harness: injects `return "FAULT_INJECTED"` into `slip_payouts._clean_slip_type()`, drives `run_ci_gate.py` RED then GREEN, guarantees revert via `finally`, tri-state exit codes (0=PASS/1=INFRA-FAIL/2=REGRESSION-NOT-CAUGHT)

## Decisions Made

- **Target function selection:** `slip_payouts._clean_slip_type()` line 37 (`return "power"`) chosen because it is exercised by 6 power-slip payout tests in `test_slip_payouts.py` (NOT in DENYLIST), giving unambiguous RED signal with no pre-existing failures in that file
- **Timeout calibration to 3600s:** First run timed out at 660s; second run timed out at 1800s (fault-injected pytest took 1925.01s due to verbose failure output); third run with 3600s succeeded — empirical measurement essential for fault-injected runs which take longer than clean runs
- **In-place source mutation:** Chose direct byte-level file mutation (save original bytes, write faulted text, revert in finally) rather than monkeypatching, to ensure the gate subprocess (`run_ci_gate.py`) sees the mutation without any interpreter-level bypass

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Increased _GATE_TIMEOUT from 660s to 1800s after first INFRA FAIL**
- **Found during:** Task 1 first verification run
- **Issue:** Both gate runs timed out at 660s; the clean gate run takes ~1705s alone
- **Fix:** Changed `_GATE_TIMEOUT = 660.0` to `_GATE_TIMEOUT = 1800.0`
- **Files modified:** scripts/repro_ci_regression.py
- **Committed in:** af87585 (same commit — iterative refinement during verification)

**2. [Rule 3 - Blocking] Increased _GATE_TIMEOUT from 1800s to 3600s after second INFRA FAIL**
- **Found during:** Task 1 second verification run
- **Issue:** Fault-injected pytest run took 1925.01s (32:05), exceeding 1800s timeout; failure output generation adds ~3.7 min vs clean run
- **Fix:** Changed `_GATE_TIMEOUT = 1800.0` to `_GATE_TIMEOUT = 3600.0`; updated docstring with observed timing data (TIMING NOTE section)
- **Files modified:** scripts/repro_ci_regression.py
- **Committed in:** af87585 (same commit — final file version)

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking: timeout calibration requiring 3 verification runs)
**Impact on plan:** Required 3 verification runs totaling ~2h wall time; the harness logic was correct from the start — only timeout value needed empirical calibration. No scope creep.

## Issues Encountered

- Timeout calibration required empirical measurement across 3 runs: 660s → 1800s → 3600s. The fault-injected pytest run with 6 verbose failure reports consistently takes longer than the clean run (observed range: 1687s-1925s vs clean 1656s-1705s). The 3600s timeout provides adequate headroom.

## Criterion-3 Evidence

| Metric | Value |
|--------|-------|
| Fault injected | `slip_payouts._clean_slip_type()` line 37: `return "power"` → `return "FAULT_INJECTED"` |
| RED gate exit code | 1 (non-zero — regression surfaced) |
| RED gate test results | 6 failed, 270 passed, 2 subtests passed in 1687.49s (0:28:07) |
| Revert method | `finally` block, original bytes restored unconditionally |
| Revert confirmation | byte-identical verified by re-read comparison |
| GREEN gate exit code | 0 (clean) |
| GREEN gate test results | 276 passed, 2 subtests passed in 1656.61s (0:27:36) |
| Residual slip_payouts.py change | None — `git diff --stat` shows no change |
| Harness exit code | 0 (PASS) |

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 5 (CI) is now **complete**: all 3 plans delivered (run_ci_gate.py gate, pre-push git hook, criterion-3 regression proof)
- ROADMAP success criteria 1, 2, 3 all satisfied
- The full milestone (Hermes Sports Automation — Stability Hardening) is complete

---

## Self-Check: PASSED

- `scripts/repro_ci_regression.py` exists: FOUND
- Commit `af87585` exists: FOUND
- `slip_payouts.py` clean (no fault): CONFIRMED (`return "power"` at line 37, no git diff)
- Harness exit code: 0 (PASS)
- RED gate exit: 1, GREEN gate exit: 0

---
*Phase: 05-ci*
*Completed: 2026-06-21*
