---
phase: 03-slips-only-bankroll
plan: "02"
subsystem: pick-generation
tags: [gate8, exposure-cap, bankroll, D-07]
dependency_graph:
  requires: []
  provides: [gate8-global-cap-removed, picks-uncapped-by-daily-exposure]
  affects: [scripts/sports_system_runner.py, scripts/test_dynamic_gate8.py]
tech_stack:
  added: []
  patterns: [cap-removal, return-dict-null-sentinel]
key_files:
  created: []
  modified:
    - scripts/sports_system_runner.py
    - scripts/test_dynamic_gate8.py
decisions:
  - "D-07 implemented: DAILY_EXPOSURE_CAP and BASE/STRONG/EXCEPTIONAL/ABSOLUTE_DAILY_CAP removed; daily_cap/dynamic_daily_cap return keys set to None as null sentinels"
  - "Concentration caps (GATE 8 — CONCENTRATION CAP) preserved verbatim per D-07 fence and A1 open question conservative default"
  - "board_quality_from_eligible retained for logging/classification (Normal/Strong/Exceptional) but no longer drives any pick gating"
  - "Correlated-parlay can_add simplified to check only CORRELATION_GROUP_CAP (exposure + dynamic_cap check removed)"
  - "test_higher_ev_approved_first_and_all_pass_without_cap: intent updated — all eligible picks now flow through since no global cap; previous assertion ('Player 1 not in keys') was testing cap-exclusion behavior, not EV priority"
metrics:
  duration_minutes: 8
  completed_date: "2026-06-23T02:54:47Z"
  tasks_completed: 2
  files_changed: 2
---

# Phase 03 Plan 02: Remove Gate-8 Global Exposure Caps (D-07) Summary

Gate-8 global daily exposure cap removed from the pick-generation path; DAILY_EXPOSURE_CAP and tier constants deleted; concentration caps and the full no-bet gate gauntlet preserved intact; test suite updated and green at 21/21.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Remove Gate-8 global exposure caps from the pick-generation path | babeda3 | scripts/sports_system_runner.py |
| 2 | Update test_dynamic_gate8.py for post-removal regression | 433bdfc | scripts/test_dynamic_gate8.py |

## What Was Built

### Task 1 — sports_system_runner.py (cap removal)

Removed the entire global Gate-8 daily exposure budget from the pick-generation path per D-07:

**Constants deleted:**
- `DAILY_EXPOSURE_CAP = 10.0` (line 91)
- `BASE_DAILY_CAP = 10.0`, `STRONG_DAILY_CAP = 12.0`, `EXCEPTIONAL_DAILY_CAP = 15.0`, `ABSOLUTE_DAILY_CAP = 15.0` (lines 2543-2546)

**allocate_eligible_candidates changes:**
- `daily_cap: float | None = None` parameter removed from signature
- `dynamic_cap` computation deleted
- Dynamic-cap skip block (`GATE 8 — DYNAMIC EXPOSURE CAP`, `would_have_played=True`, `blocked_dynamic += 1`, `continue`) deleted
- `blocked_dynamic` variable deleted
- Return dict: `daily_cap` and `dynamic_daily_cap` set to `None`; `picks_blocked_by_dynamic_cap` set to `0`

**board_quality_from_eligible changes:**
- `cap` variable and `BASE/STRONG/EXCEPTIONAL/ABSOLUTE_DAILY_CAP` references removed
- Board quality classification (Normal/Strong/Exceptional) retained for logging purposes — no longer drives any gating
- Return dict simplified: `cap` key removed

**generate_picks changes:**
- `daily_cap: float = DAILY_EXPOSURE_CAP` parameter removed from signature
- `daily_cap=DAILY_EXPOSURE_CAP` argument removed from call site (~line 3326)
- `allocate_eligible_candidates` called without `daily_cap` kwarg
- Correlated-parlay `can_add` check simplified: removed `exposure + 0.5 <= dynamic_cap` and `exposure + 0.5 <= ABSOLUTE_DAILY_CAP` conditions; only `current_corr + 0.5 <= CORRELATION_GROUP_CAP` remains
- Return dict: `daily_cap` and `dynamic_daily_cap` set to `None`; `picks_blocked_by_dynamic_cap` to `0`
- Log line updated: removed `dynamic_cap=` and `blocked_dynamic=` fields

**Preserved verbatim:**
- `GATE 8 — CONCENTRATION CAP` block in `allocate_eligible_candidates` (per-sport, per-player, per-game, per-corr, MAX_SAME_PLAYER_PROPS checks)
- `PER_PLAYER_CAP`, `PER_GAME_CAP`, `PER_SPORT_CAP`, `CORRELATION_GROUP_CAP`, `MAX_SAME_PLAYER_PROPS` constants
- `evaluate_no_bet_gates` (G1-G7, G9, G12, MLB sub-gates) — unchanged
- `global_daily_exposure()` — still called for informational starting_exposure

### Task 2 — test_dynamic_gate8.py (regression update)

Updated 5 tests, added 2 new tests, removed 0 tests:

**Tests replaced (dynamic-cap value assertions → absence-of-skip assertions):**
- `test_normal_board_stays_10u` → `test_normal_board_no_dynamic_cap_skip` (asserts `dynamic_daily_cap is None`, no DYNAMIC EXPOSURE CAP skips)
- `test_strong_board_increases_to_12u` → `test_strong_board_no_dynamic_cap_skip`
- `test_exceptional_board_increases_to_15u` → `test_exceptional_board_no_dynamic_cap_skip`
- `test_no_board_can_exceed_15u` → `test_no_dynamic_cap_skip_rows_after_removal` (12-candidate board, asserts zero dynamic-cap skip rows)
- `test_higher_ev_cross_sport_replaces_lower_ev_under_cap` → `test_higher_ev_approved_first_and_all_pass_without_cap` (all 4 picks now approved; assertion inverted because the cap exclusion behavior it relied on is gone)

**New tests added:**
- `test_no_dynamic_cap_skip_rows_after_removal` (proves no dynamic-cap skips on large board)
- `test_concentration_caps_still_block_overexposure` (proves D-07 preserved concentration caps)

**Unchanged (kept identical):**
- `allocate()` helper signature (removed now-deleted `daily_cap=None` kwarg)
- `test_concentration_fields_are_explicitly_named_and_split_by_pool_vs_final`
- `test_correlated_picks_alone_cannot_trigger_exceptional`
- `test_per_player_cap_blocks_overexposure`
- `test_per_game_cap_blocks_overexposure`
- `test_order_independent_for_nba_first_vs_mlb_first`
- `PropDataSourceBoundaryTests` class (8 tests — fully unaffected by D-07)
- `MLBNormalizationGateTests` class (2 tests — unaffected)

## Verification Results

```
python3 -m pytest test_dynamic_gate8.py -x    → 21 passed in 0.64s
grep -c 'DAILY_EXPOSURE_CAP' sports_system_runner.py  → 0
grep -c 'GATE 8 — DYNAMIC EXPOSURE CAP' sports_system_runner.py  → 0
grep -c 'GATE 8 — CONCENTRATION CAP' sports_system_runner.py  → 1
python3 -c "import ast; ast.parse(open('sports_system_runner.py').read())"  → OK
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_higher_ev_cross_sport_replaces_lower_ev_under_cap needed intent update**
- **Found during:** Task 2
- **Issue:** This test's assertion (`"Player 1 Over 11.5 Points" not in keys`) was specifically testing that the lowest-EV pick was *excluded* once the daily cap was hit. With the cap removed, all 4 picks pass, making the assertion wrong but the *behavior* correct — this was cap-exclusion behavior, not an EV-priority invariant.
- **Fix:** Updated test name and assertion to reflect the new correct behavior: all eligible picks are approved; verified `picks_blocked_by_dynamic_cap == 0`.
- **Files modified:** scripts/test_dynamic_gate8.py
- **Commit:** 433bdfc

## Key Notes (from plan output spec)

### (a) build_slips._collect_gate8 dynamic-cap half is now a no-op

`build_slips.py`'s `_collect_gate8()` uses `GATE8_VETTED_MARKERS = ("GATE 8 — DYNAMIC EXPOSURE CAP", "GATE 8 — CONCENTRATION CAP")`. After this plan:
- No picks will ever be skipped with `"GATE 8 — DYNAMIC EXPOSURE CAP"` — that label is no longer emitted
- The `"GATE 8 — CONCENTRATION CAP"` half still fires for concentration-blocked picks, which continue to populate the vetted slip universe
- **No code change was made to `build_slips.py`** — it degrades gracefully as documented

### (b) Concentration-cap preservation (A1 open question)

D-07/CONTEXT.md is silent on whether the concentration caps (PER_PLAYER_CAP, PER_GAME_CAP, PER_SPORT_CAP, CORRELATION_GROUP_CAP) should also be removed. This plan preserved them by default per the conservative A1 open question resolution. If the operator wants them removed, that is a separate scope decision requiring a new plan. The concentration caps currently limit picks to ~6u per player, ~6u per game, ~10u per sport, ~5u per correlation group — they are not exposure caps but concentration diversification controls.

## Known Stubs

None — no stub patterns introduced.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced. The threat T-03-03 (accidental removal of a non-exposure gate) was mitigated by: grep assertions confirming `GATE 8 — CONCENTRATION CAP` survives, `evaluate_no_bet_gates` unchanged at 2 references, and `test_concentration_caps_still_block_overexposure` passing.

## Self-Check: PASSED

- scripts/sports_system_runner.py: modified, `DAILY_EXPOSURE_CAP` count = 0, `GATE 8 — CONCENTRATION CAP` count = 1, parses OK
- scripts/test_dynamic_gate8.py: modified, 21/21 tests pass
- Commit babeda3 exists: feat(03-02) cap removal
- Commit 433bdfc exists: test(03-02) test update
