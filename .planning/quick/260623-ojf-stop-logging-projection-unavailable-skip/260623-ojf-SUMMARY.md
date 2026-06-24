---
phase: quick-260623-ojf
plan: 01
subsystem: skipped-picks-write-filter
tags: [filter, skipped-picks, projection-unavailable, cleanup, tdd]
dependency_graph:
  requires: [quick-260623-lzi]
  provides: [write-side-projection-unavailable-filter, cleanup-script]
  affects: [scripts/sports_system_runner.py, scripts/cleanup_projection_unavailable_skips.py]
tech_stack:
  added: []
  patterns: [reason-prefix-constant, single-source-literal, bottom-up-row-delete, atomic-save-backup]
key_files:
  created:
    - scripts/test_skipped_picks_projection_filter.py
    - scripts/cleanup_projection_unavailable_skips.py
  modified:
    - scripts/sports_system_runner.py
decisions:
  - Match on reason-string prefix ("projection unavailable") not on gate name — other GATE-1 skips with different reasons remain written
  - Define PROJECTION_UNAVAILABLE_REASON_PREFIX and is_projection_unavailable_skip() once in runner; cleanup imports them (no duplicated literal)
  - Explicit GATE8_VETTED_MARKERS guard in cleanup (belt-and-suspenders; predicate already won't match those reasons)
  - Save only when >=1 row removed to keep cleanup idempotent with no spurious backups
metrics:
  duration: "~10 min"
  completed: "2026-06-23"
  tasks: 2
  files: 3
---

# Quick Task 260623-ojf: Stop Logging Projection-Unavailable Skips

**One-liner:** Write-side filter + reason-prefix constant + idempotent cleanup script eliminating the ~88% MLB Skipped-Picks bloat (stat-coverage gap) while preserving GATE-8 cap rows for build_slips.

## What Was Built

### Task 1: Shared predicate + write-side filter + regression test (TDD)

**RED commit:** `d843f34` — failing test (ImportError on missing constant)
**GREEN commit:** `50566e6` — constant + helper + filter guard

Added to `scripts/sports_system_runner.py` at module level (~line 296, after SKIPPED_PICK_HEADERS):

- `PROJECTION_UNAVAILABLE_REASON_PREFIX: str = "projection unavailable"` — single source of truth for the reason string prefix
- `is_projection_unavailable_skip(skip: dict) -> bool` — matches on reason prefix; returns False defensively for missing/None reason

Inserted before the Skipped Picks append loop (~line 3333):
```python
if is_projection_unavailable_skip(skipped):
    continue
```

Test file `scripts/test_skipped_picks_projection_filter.py` — 7 tests covering:
- Test a: canonical GATE-1 "projection unavailable; ..." reason → True (suppressed)
- Test b: GATE 8 — CONCENTRATION CAP → False; GATE 8 — DYNAMIC EXPOSURE CAP → False (both kept)
- Test c: GATE 1 with reason "prop model edge 0.3 < 0.5" → False (kept)
- Test d: filter loop regression — mixed list of 3 skip dicts, exactly 2 pass through
- Defensive: missing/None reason → False
- Smoke: prefix constant value is "projection unavailable"

All 7 tests pass. `test_dynamic_gate8.py` (21 tests) also passes — gate/source-boundary invariants untouched.

### Task 2: Idempotent cleanup script

**Commit:** `9c317d0`

`scripts/cleanup_projection_unavailable_skips.py`:
- Imports shared predicate from runner (no duplicated literal)
- Imports `GATE8_VETTED_MARKERS` from `build_slips` for explicit safety guard
- Discovers all `data/{nba,mlb}/*.xlsx` (skips `*.tmp.*`); resolves column indices by header name (schema-safe)
- Deletes matched rows bottom-up; saves via `workbook_io.safe_save_workbook` (atomic swap + timestamped backup)
- Skip-saves on 0 removed → idempotent, no spurious backups
- Prints per-file before/after counts and grand total

## Verification Results

```
7 passed in 0.97s   (test_skipped_picks_projection_filter.py)
21 passed in 0.65s  (test_dynamic_gate8.py)
parse-ok             (cleanup_projection_unavailable_skips.py)
```

## Deviations from Plan

None — plan executed exactly as written. TDD RED → GREEN commit sequence followed.

## Checkpoint: CLEARED — cleanup executed against live workbooks (operator pre-approved)

Operator pre-approved "Clean today + backfill" before execution. Cleanup ran successfully against all live workbooks:

- **33 workbooks scanned; 14,463 projection-unavailable rows removed.**
- `data/mlb/mlb_2026-06-23.xlsx`: **1487 → 168** Skipped-Picks rows.
- **All 144 GATE 8 — CONCENTRATION CAP rows preserved** in 06-23 (build_slips vetted universe intact); 11 other GATE 1 rows + GATE 2/3/6 rows also preserved.
- Per-file timestamped backups written under `data/backups/workbooks/2026-06-23/` (atomic-swap save path).
- Post-cleanup read-only audit: **0 projection-unavailable rows remain across all 33 workbooks** → idempotency guaranteed (a re-run removes 0).

### Root-cause correction (supersedes 260623-lzi's flag)

The prior task (260623-lzi) flagged this as a "runaway Skipped-Picks append (Pick Ref=MLB ×1487)" caused by reruns not clearing / a `fastloop_trader.py`. **That hypothesis was wrong.** Evidence: all 1,487 rows shared one `Logged At` timestamp (single run, not accumulation), the 1,457 distinct `Pick` values are genuinely different candidates (not one row duplicated), `fastloop_trader.py` does not exist, and `clear_today_rows` works correctly. The real cause is a **stat-coverage gap**: the projection model covers ~9 core stats while the DFS board offers ~30+ markets (singles, doubles, stolen bases, batter strikeouts, fantasy score, 1st-inning markets…). ~88% of MLB candidates are unprojectable → fail GATE 1 → every one was logged. Verified: 0 of 1,319 rows recoverable via `projection_lookup` (not a join bug). This is chronic since June 9, not a regression.

## Known Stubs

None.

## Threat Flags

None. No new network endpoints, auth paths, or schema changes introduced.

## Self-Check: PASSED

- `scripts/test_skipped_picks_projection_filter.py` exists and passes (7/7)
- `scripts/cleanup_projection_unavailable_skips.py` exists and parse-ok
- `scripts/sports_system_runner.py` modified (constant + helper + continue guard)
- Commits d843f34, 50566e6, 9c317d0 present in git log
