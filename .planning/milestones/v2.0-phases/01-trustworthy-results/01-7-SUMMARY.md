---
phase: 01-trustworthy-results
plan: 7
subsystem: grading
tags: [bankroll, pnl, prop-grading, tdd, gap-closure]
dependency_graph:
  requires: [BANKROLL-01, D-09]
  provides: [BANKROLL-01 enforced in grader, GAP-4 closed]
  affects: [scripts/sports_system_runner.py grade_game_in_workbook, Results sheet PnL column]
tech_stack:
  added: []
  patterns: [TDD RED/GREEN, stdlib unittest via importlib, temp-workbook fixture]
key_files:
  created:
    - scripts/test_prop_pnl_slip_terms.py
  modified:
    - scripts/sports_system_runner.py
decisions:
  - "BANKROLL-01: PROP and single-pick SPREAD/TOTAL rows write PnL=0; Result carries accuracy signal only; real money PnL belongs to Slip History (grade_slips)"
  - "odds_profit / pnl_for_result left unchanged — still used by parlay/slip grading path"
  - "Parlay loop (grade_game_in_workbook:6051) untouched — parlays are staked bets with real money PnL"
metrics:
  duration: 5m
  completed: 2026-06-23
  tasks: 2
  files_changed: 2
---

# Phase 01 Plan 7: Prop PnL = 0 / Slip-Terms-Only Accounting Summary

Severs standalone money PnL from individual PROP and single-pick SPREAD/TOTAL rows in `grade_game_in_workbook`. A per-prop PnL was conceptually wrong post-P3: DFS requires multi-leg slips, so no money is staked on a single prop. WIN/LOSS Result carries the accuracy signal; bankroll is computed only from Slip History Net PnL (D-09 / BANKROLL-01).

## What Was Built

- **Task 1 (RED):** `scripts/test_prop_pnl_slip_terms.py` — 7 stdlib unittest tests proving the per-prop money PnL bug (WIN prop returns +0.909, LOSS prop returns -1.0). Tests FAILED before the fix.
- **Task 2 (GREEN):** Three `pnl = 0.0` substitutions in `grade_game_in_workbook` with BANKROLL-01/D-09 inline comments:
  - Line 5900 (SPREAD lane): `pnl = odds_profit(...)` → `pnl = 0.0`
  - Line 5903 (TOTAL lane): `pnl = odds_profit(...)` → `pnl = 0.0`
  - Line 5967 (PROP lane): `pnl = odds_profit(result, units, None)` → `pnl = 0.0`
- Parlay loop (line 6051) unchanged — parlays/slips keep real money PnL.
- `odds_profit` / `pnl_for_result` unchanged — still used by slip-grading path.
- `sync_slip_bankroll` confirmed: sources bankroll only from Slip History "Net PnL" (D-09 intact).

## TDD Gate Compliance

- RED gate: `test(01-7)` commit `183e809` — failing tests proven (WIN prop PnL=+0.909, LOSS prop PnL=-1.0)
- GREEN gate: `feat(01-7)` commit `ee87b53` — all 7 tests pass

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| Task 1 (RED) | 183e809 | test(01-7): RED — failing test proving prop/single-pick PnL is nonzero (BANKROLL-01) |
| Task 2 (GREEN) | ee87b53 | feat(01-7): GREEN — PROP and single-pick SPREAD/TOTAL rows write PnL=0 (BANKROLL-01) |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Parlay test fixture missing Odds-API scores structure**
- **Found during:** Task 2 GREEN phase
- **Issue:** The test's `_GAME` dict used `home_score`/`away_score` keys but `final_scores()` reads `game["scores"]` (Odds-API list of `{name, score}` dicts). The SPREAD row graded as PENDING → parlay abstained → `assertIsNotNone(result_val)` failed.
- **Fix:** Added `"scores": [{"name": "Yankees", "score": "5"}, {"name": "Red Sox", "score": "3"}]` to `_GAME` fixture in the test file.
- **Files modified:** scripts/test_prop_pnl_slip_terms.py
- **Commit:** ee87b53 (bundled with GREEN fix)

## Verification

- `python3 -m pytest test_prop_pnl_slip_terms.py -x -q` → 7 passed
- `grep` confirms 3 × `pnl = 0.0` with BANKROLL-01/D-09 comments in grade_game_in_workbook
- `grep "odds_profit(result, units, None)"` → only 1 occurrence remaining (line 6051, parlay loop — correct)
- `sync_slip_bankroll` reads bankroll from `_SHH.index("Net PnL")` (D-09 intact, no code change)

## Known Stubs

None. All prop PnL assignments are wired to 0.0 unconditionally (not placeholder logic).

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes introduced. The grading change is value-only (PnL field assignment); schema is unchanged.

## Self-Check: PASSED

- scripts/test_prop_pnl_slip_terms.py: EXISTS ✓
- scripts/sports_system_runner.py: MODIFIED ✓ (3 pnl=0.0 changes confirmed)
- Commits: 183e809 (RED test), ee87b53 (GREEN fix) ✓
- 7 tests pass ✓
