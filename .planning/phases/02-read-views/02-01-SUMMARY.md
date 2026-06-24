---
phase: 02-read-views
plan: 01
subsystem: dashboard-data-layer
tags: [view-accessors, read-only, tdd, dashboard]
dependency_graph:
  requires: [01-03]
  provides: [get_today_board, get_all_slips, get_history_data, PNL_DIR]
  affects: [scripts/dashboard_data.py, scripts/test_dashboard_views.py]
tech_stack:
  added: []
  patterns: [lock-tolerant-read, ev-coercion, iso-week-aggregation, two-tier-why-paired]
key_files:
  created: [scripts/test_dashboard_views.py]
  modified: [scripts/dashboard_data.py]
decisions:
  - "Missing-workbook-vs-locked: file-existence check in get_today_board before calling read_sheet_rows; only set locked=True when an existing file is unreadable (not when today's file hasn't been created yet by the pipeline)"
  - "test_locked_state fixture creates a real empty workbook before patching read_sheet_rows so the file-existence guard passes and the patch fires correctly"
  - "ISO-week aggregation duplicated inline in get_history_data (not imported from metrics_report.py — RESEARCH anti-pattern)"
  - "Tier-2 why_paired derived from Slip ID category segment is the normal path; Tier-1 Correlated Parlays lookup falls through on no-match without raising (Pitfall 7)"
metrics:
  duration_minutes: 45
  completed_date: "2026-06-24"
  tasks_completed: 2
  files_modified: 2
---

# Phase 02 Plan 01: View Accessor Foundation Summary

Three read-only view accessors that shape Today, Slips, and History page data added to `scripts/dashboard_data.py`, with a Wave-0 unit test file `scripts/test_dashboard_views.py` that pins their contract. These accessors are the data foundation every Phase 2 route and template renders against.

## What Was Built

### `scripts/dashboard_data.py` — three new accessors + PNL_DIR constant

**`PNL_DIR: Path = DATA / "pnl"`** added to the path-constants block (after `RUN_LOG_JSONL`). Required by `get_all_slips` and `get_history_data`.

**`get_today_board(date)`** — VIEW-01 contract:
- Reads `Picks` (Status==APPROVED, date-filtered) and `Skipped Picks` from both `NBA_DIR/nba_{today}.xlsx` and `MLB_DIR/mlb_{today}.xlsx`
- Sets `status_label = "✓ Approved"` on approved rows; `status_label = "Skip: GATE-NAME"` on skipped rows (splits `Gate Failed` on ` — `)
- Adds `ev_float` (float or None) to every row; `prob_float` to skipped rows; handles `"unavailable"` and None gracefully
- File-existence check before calling `read_sheet_rows`; sets `locked=True` only when an existing file is unreadable
- Returns `{"approved": [...], "skipped": [...], "date": str, "locked": bool}`

**`get_all_slips()`** — VIEW-02 contract:
- Reads `Slip History` from `PNL_DIR/master_pnl.xlsx` exclusively (88-slip superset)
- Adds `legs_list` (split on `"; "`) and `why_paired` to each slip
- Two-tier `why_paired`: Tier-1 = Correlated Parlays sheet join on Slip ID (no-match falls through silently); Tier-2 = `_WHY_PAIRED` dict keyed on Slip ID category segment
- Sorted date descending
- Returns `{"slips": [...], "locked": bool}`

**`get_history_data()`** — VIEW-03 contract:
- Reads `Pick History` and `Bankroll Chart Data` from `PNL_DIR/master_pnl.xlsx`
- Aggregates W/L/push, hit_pct, roi_pct, n overall + by_sport (NBA/MLB) + by_tier (A/B/C/UNKNOWN)
- `Confidence Tier = None` rows coerced to UNKNOWN (not hidden)
- `chart_daily`: labels + bankroll + roi in row order from Bankroll Chart Data
- `chart_weekly`: ISO-week aggregation using `date.fromisoformat(d).isocalendar()`, last row per week wins
- Returns full dict with `overall`, `by_sport`, `by_tier`, `chart_daily`, `chart_weekly`, `locked`

### `scripts/test_dashboard_views.py` — Wave-0 unit tests

**`TestTodayBoard`** (4 tests):
- `test_approved_picks`: date-filtered approved row returns with `status_label="✓ Approved"`
- `test_skipped_picks_gate_label`: `"GATE 1 — MINIMUM EDGE"` → `status_label="Skip: MINIMUM EDGE"`
- `test_locked_state`: real workbook file + patched `read_sheet_rows=None` → `locked=True`, no raise
- `test_ev_coercion`: `EV="unavailable"` → `ev_float=None`

**`TestSlipsAccessor`** (3 tests):
- `test_slips_sorted`: 3 slips across 3 dates → date-descending order
- `test_legs_parsed`: `"A; B; C"` → `legs_list=["A","B","C"]`
- `test_why_paired_derived`: `correlated_upside` → starts "Correlated upside"; unknown category → "Independent legs"

**`TestHistoryAccessor`** (4 tests):
- `test_tier_breakdown`: all 4 tiers have W/L/hit_pct/roi_pct/n keys; A-tier W=1/L=1
- `test_none_tier_as_unknown`: 2 None-tier rows → UNKNOWN.n=2; A/B/C.n=0
- `test_chart_daily`: 3 rows → 3 labels/bankroll points of equal length
- `test_chart_weekly`: Jun 8+11 (same W24) + Jun 15 (W25) → 2 labels; W24 bankroll=103.0 (last wins)

## Verification Results

```
cd scripts && python3 -m pytest test_dashboard_views.py test_dashboard.py test_dashboard_data.py -q
19 passed in 35 seconds
```

- All 11 Wave-0 accessor tests: GREEN
- Phase 1 suite (8 tests): GREEN — no regression
- `grep -c zoneinfo scripts/dashboard_data.py` == 0
- `python3 -c "import dashboard_data; b=dashboard_data.get_today_board(); assert set(['approved','skipped','date','locked']) <= set(b)"` exits 0

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] test_locked_state fixture needed workbook file for file-existence guard**
- **Found during:** Task 2 GREEN phase
- **Issue:** `get_today_board` skips non-existent workbook files (empty state, not locked). The original `test_locked_state` patched `read_sheet_rows` globally without creating a workbook file, so the file-existence guard caused the test to skip rather than call the patched function.
- **Fix:** Updated `test_locked_state` to create a real (empty) workbook file in a temp dir and override `NBA_DIR`/`MLB_DIR` before patching `read_sheet_rows`. This correctly simulates a present-but-locked workbook (D-01 mid-write lock scenario).
- **Files modified:** `scripts/test_dashboard_views.py`
- **Commit:** 3888494

**2. [Rule 1 - Bug] Docstring contained "zoneinfo" string triggering test_today_matches_runner**
- **Found during:** Task 2 verification
- **Issue:** `get_history_data` docstring comment "Do NOT import zoneinfo" contained the literal string "zoneinfo", which the `test_today_matches_runner` source-text grep detected as a false violation.
- **Fix:** Replaced docstring line with "Uses stdlib datetime.date only — no timezone library."
- **Files modified:** `scripts/dashboard_data.py`
- **Commit:** 3888494

## Known Stubs

None. All three accessors are fully wired to real workbook data paths and return the documented dict shapes.

## Threat Flags

None. All threat model mitigations implemented:
- **T-02-01** (path traversal): workbook paths hardcoded as `DATA/"nba"/f"nba_{today}.xlsx"` where `today` comes from `today_str()` — no request input.
- **T-02-02** (locked workbook DoS): all paths call only `read_sheet_rows`; `None` return → `locked=True` with `[]` fallback — never raise, never hang.

## Self-Check: PASSED

Files created/modified:
- `scripts/dashboard_data.py` — FOUND (modified, 4 new definitions confirmed by grep)
- `scripts/test_dashboard_views.py` — FOUND (551 lines, 11 tests collectible)

Commits:
- `81e1c07` — test(02-01): Wave-0 RED test scaffold — FOUND
- `3888494` — feat(02-01): three view accessors + PNL_DIR — FOUND
