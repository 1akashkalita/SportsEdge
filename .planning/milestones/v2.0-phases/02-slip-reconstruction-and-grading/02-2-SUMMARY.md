---
phase: 02-slip-reconstruction-and-grading
plan: 2
subsystem: slip-grading
tags: [grading, payout, slip-history, idempotency, money-safety, stat-normalization]
dependency_graph:
  requires: [02-1-slip-leg-grading-core, 01-trustworthy-results]
  provides: [slip-aggregation, slip-history-upsert, grade-slips-for-date]
  affects: [02-3-backfill]
tech_stack:
  added: [hashlib-sha1-slip-id]
  patterns: [upsert-by-stable-id, raw-leg-results-passthrough, stat-normalization-map]
key_files:
  created:
    - scripts/test_grade_slips_aggregate.py
  modified:
    - scripts/grade_slips.py
decisions:
  - "slip_id_for uses SHA1(date|category|sorted leg keys) truncated to 8 hex chars — stable across re-runs, distinct for different leg sets, format '<date>:<category>:<8-char-hash>'"
  - "grade_slips_for_date signature: (date, *, dry_run=False, player_stats_by_sport=None) → returns summary dict with status/total_slips/win_count/loss_count/pending_count/rows_written/graded"
  - "Per-day vs master write split: single-sport slips go to both per-sport workbook AND master; mixed-sport slips go to master only"
  - "Idempotency via (Date, Slip ID) scan in write_slip_history_rows — if matching row found, overwrite in place; else append (mirrors P1 replace-by-ref pattern)"
  - "_normalize_stat() map added to grade_leg: translates space-separated DFS stat_type strings ('hits runs rbis', 'outs', 'points rebounds assists', etc.) to canonical forms before stat_value_for_prop dispatch"
  - "MUST-FIX applied: combo stat legs ('hits runs rbis', NBA PRA combos, 'outs') now resolve correctly instead of abstaining to PENDING — verified with test cases"
  - "Raw per-leg statuses (including LEG_PENDING/PUSH) passed directly to calculate_slip_payout; its ambiguous-leg branch forces MANUAL REVIEW + reconciliation — no pre-collapse"
metrics:
  duration_minutes: 12
  tasks_completed: 3
  files_changed: 2
  completed_date: "2026-06-22"
---

# Phase 02 Plan 2: Slip Aggregation, Payout, Idempotent Slip History Summary

**One-liner:** Slip-level payout aggregation using calculate_slip_payout with raw-status passthrough, SHA1-stable Slip IDs, and idempotent (Date, Slip ID) upsert into per-day + master Slip History sheets.

## What Was Built

### `scripts/grade_slips.py` (extended from Wave 1)

New exports:

- `_normalize_stat(stat) -> str` — Maps DFS space-separated combo stat_type strings to the canonical form `stat_value_for_prop` expects (e.g. `"hits runs rbis"` → `"hits+runs+rbis"`, `"outs"` → `"pitching outs"`, NBA PRA combos). Applied inside `grade_leg` before dispatch. This was the MUST-FIX from the Wave 1 discovery: without normalization, all combo legs abstained to PENDING and almost no slip graded.

- `slip_id_for(date, slip) -> str` — Deterministic stable ID: `SHA1(date|category|sorted leg identity strings)[:8]`, formatted as `"<date>:<category>:<8-char-hash>"`. Leg identity is `prop_id` if present, else `"<sport>:<player>:<stat>:<line>:<side>"`. Same slip + date always yields the same ID; different leg sets yield different IDs.

- `grade_slip(slip, box_scores, config=None) -> dict` — Grades each leg via `grade_leg`, collects raw `leg_results` (including `LEG_PENDING`/`PUSH`), then calls `calculate_slip_payout` with those raw statuses. The ambiguous-leg branch in `calculate_slip_payout` handles PENDING/PUSH by forcing `MANUAL REVIEW + needs_payout_reconciliation=True` — no pre-collapse, no fabricated verdict. Returns: `slip_id`, `category`, `platform`, `slip_type`, `stake_units`, `legs`, `payout` (full calculate_slip_payout dict), `leg_grades`.

- `write_slip_history_rows(ws, date, graded_slips) -> int` — Upserts each graded slip into a Slip History worksheet. Scans existing rows for matching `(Date, Slip ID)`; if found overwrites in place; if not found appends. Returns count of rows written. Uses `slip_payouts.slip_history_row` for row construction.

- `grade_slips_for_date(date, *, dry_run=False, player_stats_by_sport=None) -> dict` — Entry point. Loads `data/research/slips/slips_<date>.json`, flattens all categories (skips empty), builds box scores (offline injection path or ESPN network), grades every slip, and (unless dry_run) writes Slip History rows to: (1) the per-sport per-day workbook via `ensure_workbook` + `save_workbook_atomic`; (2) the master P&L workbook via `master_pnl_workbook()` + `save_workbook_atomic`. All writes confined to the "Slip History" sheet; Results / Pick History prop rows are never touched (SLIPS-04).

### `scripts/test_grade_slips_aggregate.py`

Offline unittest (13 tests, stdlib `unittest`, exits 0 in ~0.015s).

| Test | Coverage |
|------|----------|
| `test_power_both_win` | 2-leg power all-WIN → GRADED, 3.0x, +2u, reconcile=False |
| `test_power_one_loss` | 2-leg power + LOSS → GRADED, 0x, -1u, reconcile=False |
| `test_pending_leg_is_manual_review` | Absent player → MANUAL REVIEW, net=None, reconcile=True |
| `test_leg_grades_include_pending_token` | LEG_PENDING in leg_grades for absent leg |
| `test_flex_2_of_3` | 3-leg flex 2-of-3 WIN → 1.0x, net 0.0 |
| `test_stable_across_reruns` | slip_id_for is deterministic |
| `test_distinct_for_different_legs` | Different legs → different ID |
| `test_distinct_for_different_dates` | Different date → different ID |
| `test_format_contains_date_and_category` | ID format validation |
| `test_second_write_no_duplicate` | write_slip_history_rows idempotency (upsert, not append) |
| `test_slip_rows_not_in_results` | SLIPS-04: Slip History only, Results untouched |
| `test_hits_runs_rbis_resolves` | 'hits runs rbis' normalizes → WIN for Freeman 6 vs 5.0 |
| `test_hits_runs_rbis_loss` | 'hits runs rbis' normalizes → LOSS for Freeman 6 vs 7.0 |

## Stat Normalization Map

| DFS stat_type | Canonical form (stat_value_for_prop) | Sport |
|---------------|--------------------------------------|-------|
| `hits runs rbis` | `hits+runs+rbis` | MLB |
| `hits + runs + rbis` | `hits+runs+rbis` | MLB |
| `outs` | `pitching outs` | MLB |
| `points rebounds assists` | `pts+rebs+asts` | NBA |
| `points rebounds` | `pts+rebs` | NBA |
| `points assists` | `pts+asts` | NBA |
| `rebounds assists` | `rebs+asts` | NBA |
| `pts rebs asts` | `pts+rebs+asts` | NBA |

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1+2 — grade_slips.py | 3469864 | feat(02-2): slip aggregation, payout, stable Slip ID (grade_slip, slip_id_for) |
| 3 — test file | dd43438 | test(02-2): offline unittest — power WIN/LOSS, PENDING-not-LOSS, idempotent upsert, prop separation |

## Deviations from Plan

### Auto-applied MUST-FIX — Stat normalization in grade_leg

**Found during:** Task 1 implementation (confirmed from 02-1-SUMMARY discovery)

**Issue:** All combo stat legs (`"hits runs rbis"`, `"points rebounds assists"`, `"outs"`) in slip definitions abstained to PENDING because `stat_value_for_prop` uses plus-separated canonical forms while `build_slips.py` emits space-separated strings. Without normalization, almost no real-world slips (which heavily use H+R+RBI combos) would grade at all.

**Fix:** Added `_normalize_stat()` mapping table and applied it in `grade_leg` before calling `stat_value_for_prop`. Added `TestStatNormalization` tests to confirm resolution.

**Files modified:** `scripts/grade_slips.py`

**Commits:** 3469864 (included in Task 1 commit)

## Threat Model Compliance

| Threat | Mitigation Applied |
|--------|-------------------|
| T-02-04: fabricated slip result from partial leg set | Raw per-leg statuses (incl. LEG_PENDING) passed to calculate_slip_payout; its ambiguous branch forces MANUAL REVIEW; test_pending_leg_is_manual_review explicitly asserts NOT WIN / NOT LOSS |
| T-02-05: duplicate Slip History rows on re-run | Stable slip_id_for + (Date, Slip ID) scan in write_slip_history_rows; test_second_write_no_duplicate asserts data row count unchanged |
| T-02-06: slip metrics bleeding into prop tracking | Writes confined to Slip History sheet only; test_slip_rows_not_in_results asserts Results sheet untouched |
| T-02-07: non-atomic master_pnl write | All writes via save_workbook_atomic (temp-swap + backup) |

## Known Stubs

None — all core slip grading functions are wired to real implementations. The `kat_based` category is empty in today's slip data and is correctly skipped (not a stub).

## Self-Check: PASSED

- [x] `scripts/grade_slips.py` exists and imports cleanly with all 4 new exports callable
- [x] `scripts/test_grade_slips_aggregate.py` exists and exits 0 (13 tests, ~0.015s)
- [x] Commits 3469864 and dd43438 verified in git log
- [x] Stat normalization applied in grade_leg (combo legs resolve, not abstain)
- [x] No modifications to `sports_system_runner.py` or prop grading logic
- [x] Writes confined to Slip History sheet via save_workbook_atomic
