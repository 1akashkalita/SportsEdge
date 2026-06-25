---
phase: 02-reliability-fixes-defect-removal
plan: "02"
subsystem: orchestrator
tags: [dead-code-removal, defect, duplicate-defs, DEF-01]
dependency_graph:
  requires: ["02-01"]
  provides: ["single-canonical-injury-monitor", "single-canonical-clv-tracker", "DEF-01-regression-test"]
  affects: ["scripts/sports_system_runner.py"]
tech_stack:
  added: []
  patterns: ["ast-static-analysis", "importlib-module-load", "inspect-getsource"]
key_files:
  modified:
    - scripts/sports_system_runner.py
  created:
    - scripts/test_def01_no_duplicate_defs.py
decisions:
  - "Use record_morning_clv_row and weekly_clv_summary as distinguishing markers for active clv_tracker (PATTERNS.md marker 'resolve_odds_api_io_league' was incorrect — that function is not called directly inside clv_tracker)"
metrics:
  duration_minutes: 15
  tasks_completed: 2
  files_changed: 2
  completed_date: "2026-06-20"
---

# Phase 02 Plan 02: DEF-01 Duplicate Definition Removal Summary

**One-liner:** Deleted the two dead duplicate function stubs (injury_monitor at line 3624, clv_tracker at line 3665), leaving exactly one active superset definition of each in sports_system_runner.py, with a 5-assertion AST regression test to prevent reintroduction.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Re-confirm earlier defs are strict subsets, then remove them (DEF-01) | 9bf598e | scripts/sports_system_runner.py (-60 lines) |
| 2 | Add DEF-01 behavior-confirmation test and confirm existing suite passes | 2f01063 | scripts/test_def01_no_duplicate_defs.py (new) |

## Diff Confirmation (DEF-01 Safety Step)

Before deletion, both dead definitions were read in full and compared against the active superset definitions:

**Dead `injury_monitor` (former lines 3624-3662, 38 lines):**
- Reads only the cached "Injury Baseline" sheet via `injuries.cell(r, 5/6).value`
- No ESPN call, no `espn_injury_rows`, no `calculate_injury_impact`, no `find_injury_baseline_row`
- Returns a minimal dict with `players_checked` and `status_changes` only
- **Finding: strict subset of the active superset def. No unique logic.**

**Active `injury_monitor` (now at line 5003):**
- Calls `espn_injury_rows`, `espn_injury_news_flags`, `enrich_picks_with_espn_odds`
- Calls `calculate_injury_impact`, `find_injury_baseline_row`, `affected_items_for_player`, `set_affected_statuses`, `extract_current_pp_line`
- Returns richer dict including `raw_espn_injury_first5`, `espn_odds_pulled`, `injury_baseline_row_count`, `game_list`, `espn_api_status`
- **This is the implementation Python already used (last-definition wins). Kept unchanged.**

**Dead `clv_tracker` (former lines 3665-3681, 17 lines):**
- Called `odds_api(sport)` and `append_unique` only
- Wrote a basic 10-column game row per game, no CLV value calculation
- Returned minimal dict with `games`, `rows_added`, `credits_remaining`
- **Finding: strict subset of the active superset def. No unique logic.**

**Active `clv_tracker` (now at line 5397):**
- Also calls `odds_api(sport)` (same starting point), plus additionally:
- Calls `run_fetch_dfs_props` and `first_class_dfs_props_latest` for DFS closing lines
- Calls `record_morning_clv_row` to backfill morning CLV rows from the Picks sheet
- Calls `calculate_clv_value`, `clv_status`, `clv_preview_row` for CLV scoring
- Calls `weekly_clv_summary`, `sync_master_clv_fields`, `obsidian_create_weekly_recap`
- Sends a weekly Telegram CLV report on Mondays
- Returns richer dict with CLV metrics, preview rows, weekly summary, and backfill count
- **This is the implementation Python already used. Kept unchanged.**

**Conclusion: Both earlier definitions are confirmed strict subsets. Neither held unique logic. Deletion proceeds.**

## PATTERNS.md Marker Correction (Deviation Noted)

The PATTERNS.md document stated the active `clv_tracker` uses `resolve_odds_api_io_league` as its distinguishing marker. This is incorrect — `resolve_odds_api_io_league` is called inside `odds_scores()` and `build_hit_rate_db.py`, not directly inside `clv_tracker`. The actual distinguishing markers between the dead stub and the active def are `record_morning_clv_row` and `weekly_clv_summary`. The regression test was written with the correct markers.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] PATTERNS.md marker 'resolve_odds_api_io_league' not present in clv_tracker body**
- **Found during:** Task 2 (test execution)
- **Issue:** The DEF-01 test initially used `resolve_odds_api_io_league` as the distinguishing marker for the active `clv_tracker`, as documented in PATTERNS.md. Running the test revealed this marker is not present in the clv_tracker body — it is called inside `odds_scores()`, not `clv_tracker`.
- **Fix:** Replaced the test assertion with the correct markers: `record_morning_clv_row` (morning CLV backfill) and `weekly_clv_summary` (weekly reporting) — both present in the active def, both absent from the 17-line dead stub.
- **Files modified:** scripts/test_def01_no_duplicate_defs.py
- **Impact:** None on the deletion itself. The dead clv_tracker was still confirmed as a strict subset by direct inspection. The test now uses accurate markers.

## Acceptance Criteria Verification

| Criterion | Result |
|-----------|--------|
| AST check: `injury_monitor= 1 clv_tracker= 1` exits 0 | PASS |
| `grep -c 'def injury_monitor'` returns 1 | PASS (confirmed: 1) |
| `grep -c 'def clv_tracker'` returns 1 | PASS (confirmed: 1) |
| Surviving `injury_monitor` references `espn_injury_rows` (count >= 1) | PASS (count: 2) |
| Surviving `clv_tracker` references `resolve_odds_api_io_league` | N/A — see deviation; correct marker `record_morning_clv_row` confirmed present |
| `python3 -c "import sports_system_runner"` exits 0 | PASS |
| SUMMARY records diff outcome confirming no unique logic in earlier defs | PASS (this document) |
| DEF-01 test exits 0 with OK summary | PASS (5/5 tests pass) |
| Full targeted test suite (62 tests) passes with no new failures | PASS |

## Test Baseline Record

- New test: `test_def01_no_duplicate_defs.py` — 5 tests, all PASS
- Targeted regression run (test_dynamic_gate8.py + test_slip_payouts.py + test_odds_api_io_client.py): **62 tests, 0 failures**
- Known pre-existing failures (out of scope, NOT fixed): `test_generate_projections.py::test_castle_points_assists_case_has_negative_ev` and `test_generate_projections.py::test_kat_pra_case_uses_projection_line_sigma_not_hit_rate` — stale projection-math expectations pre-dating Phase 2

## Known Stubs

None. This plan is a pure dead-code removal with no stubs introduced.

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes. The only changes are: deletion of dead Python function bodies and addition of a static-analysis test file.

## Self-Check: PASSED

- `scripts/sports_system_runner.py` exists and was modified (60 lines deleted): confirmed
- `scripts/test_def01_no_duplicate_defs.py` exists and was created: confirmed
- Commit `9bf598e` exists: confirmed
- Commit `2f01063` exists: confirmed
- Module imports cleanly after deletion: confirmed
- AST reports exactly one def each: confirmed
