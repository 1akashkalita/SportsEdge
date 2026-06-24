---
phase: 01-trustworthy-results
plan: 8
subsystem: testing
tags: [python, unittest, pytest, openpyxl, espn-api, fixture, idempotency]

# Dependency graph
requires:
  - phase: 01-trustworthy-results
    provides: Layer-1 stat grading (stat_value_for_prop, parse_prop_ref, espn_player_stats_by_event)
provides:
  - Pinned pre-backfill June 8 MANUAL REVIEW snapshot fixture (35 denominator + 2 DNP rows)
  - Idempotent RESULTS-07 gate test (measures against fixed snapshot, not live workbook)
  - test_snapshot_fixture_integrity: fixture integrity assertion (counts, DNP flags, parseable refs)
affects: [01-trustworthy-results, gap-closure]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fixture-pinned idempotent gate test: pin pre-backfill snapshot as fixed denominator so test is stable after grading runs"
    - "ESPN network skip guard: skipTest on unreachable ESPN (network condition, not gate regression)"
    - "DNP exclusion pattern: mark dnp_void:true in fixture; exclude from denominator + numerator"

key-files:
  created:
    - scripts/testdata/june8_manual_review_snapshot.json
  modified:
    - scripts/test_june8_dryrun_gate.py

key-decisions:
  - "Snapshot reconstructed from data/backups/workbooks/2026-06-22/mlb_2026-06-08.xlsx.012123.xlsx (earliest backup, pre-backfill) — not fabricated"
  - "DNP rows (Nick Martinez, Masataka Yoshida) marked dnp_void:true and excluded from denominator (never Layer-1-recoverable)"
  - "_read_june8_manual_review_rows retained in test file as reference-only comment, not called by any test"
  - "ESPN calls kept in gate (deterministic for historical date); skipTest on network failure instead of fail"

patterns-established:
  - "Snapshot pattern: pre-backfill fixture pins the denominator; test never reads live workbook state"

requirements-completed: [RESULTS-07]

# Metrics
duration: 3min
completed: 2026-06-23
---

# Phase 01 Plan 8: Idempotent RESULTS-07 Gate (GAP 3 Closure) Summary

**RESULTS-07 gate made idempotent via pre-backfill snapshot fixture (35/35=100% resolution rate, stable across runs independent of workbook state)**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-06-23T21:15:19Z
- **Completed:** 2026-06-23T21:19:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Reconstructed the exact pre-backfill June 8 non-Fantasy MANUAL REVIEW set (37 rows) from the earliest backup (2026-06-22 012123) — all real Pick Refs, none fabricated
- Marked Nick Martinez and Masataka Yoshida as `dnp_void:true` (both DNP June 8, played June 9, graded VOID in UAT)
- Rewired test gate to use fixed snapshot denominator (35 rows, excluding 2 DNP) — decoupled from live workbook state
- Gate now measures 35/35=100% resolution rate and is idempotent (consecutive green runs verified)
- Added `test_snapshot_fixture_integrity` asserting 37 total rows / 35 denominator / 2 DNP / all PROP refs parseable

## Task Commits

Each task was committed atomically:

1. **Task 1: Pin pre-backfill snapshot fixture** - `bbcf424` (test)
2. **Task 2: Rewire gate to fixed snapshot denominator** - `6311421` (feat)

**Plan metadata:** (included in final docs commit)

## Files Created/Modified

- `scripts/testdata/june8_manual_review_snapshot.json` - 37-row pre-backfill fixture; 35 denominator rows, 2 DNP marked `dnp_void:true`; reconstructed from `data/backups/workbooks/2026-06-22/mlb_2026-06-08.xlsx.012123.xlsx`
- `scripts/test_june8_dryrun_gate.py` - Rewired to use `_load_snapshot_denominator()` instead of `_read_june8_manual_review_rows()`; added `test_snapshot_fixture_integrity`; ESPN network skip guard added

## Decisions Made

- Snapshot source: `mlb_2026-06-08.xlsx.012123.xlsx` (2026-06-22, 01:21:23 UTC) is the earliest available backup — confirms pre-backfill state with 83 MANUAL REVIEW rows (37 non-Fantasy + 46 Fantasy)
- DNP exclusion: Nick Martinez (Hits Allowed) and Masataka Yoshida (Hits+Runs+RBIs) are marked `dnp_void:true`; they appear in the snapshot for completeness but are excluded from the denominator
- Kept `_read_june8_manual_review_rows` in the file as reference-only (not called by any test) to preserve historical context
- ESPN calls are deterministic for a past date; kept live for actual stat verification; skipTest on network failure

## Deviations from Plan

None — plan executed exactly as written. The snapshot reconstruction was successful from the earliest backup without any fabrication. All 37 pre-backfill non-Fantasy rows were recoverable.

## Issues Encountered

None. The earliest backup (2026-06-22 012123) contained all 83 MANUAL REVIEW rows from before the backfill, giving us the exact 37-row non-Fantasy set documented in UAT.

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes introduced. Test-only change.

## Self-Check

- [x] `scripts/testdata/june8_manual_review_snapshot.json` exists
- [x] `scripts/test_june8_dryrun_gate.py` modified
- [x] Commit `bbcf424` exists (snapshot fixture)
- [x] Commit `6311421` exists (gate rewire)
- [x] Two consecutive green runs: IDEMPOTENT confirmed

## Self-Check: PASSED

## Next Phase Readiness

- GAP 3 closed: `test_june8_dryrun_gate.py` is green and idempotent
- RESULTS-07 requirement complete and verified
- Phase 01-trustworthy-results gap closure complete

---
*Phase: 01-trustworthy-results*
*Completed: 2026-06-23*
