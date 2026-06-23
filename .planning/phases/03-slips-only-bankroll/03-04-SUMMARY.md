---
phase: 03-slips-only-bankroll
plan: 04
subsystem: bankroll
tags: [bankroll, slips, confidence-stake, rebuild, ledger, master-pnl, idempotent]

# Dependency graph
requires:
  - phase: 03-slips-only-bankroll
    provides: "03-01: confidence_stake() helper; 03-03: sync_slip_bankroll, grade_slips, write_slip_history_rows, Prop Accuracy"
provides:
  - "rebuild_slip_bankroll() chronological idempotent re-stake from 2026-06-08 with starting_bankroll=100"
  - "rebuild_bankroll runner task (660s budget, cooperative master_pnl.xlsx lock)"
  - "Live bankroll.json + Bankroll Chart Data + Daily Log rebased onto slips-only basis"
  - "Regression test: test_rebuild_wipes_stale_in_range_rows covering the wipe-scope defect"
affects: [04-dual-metrics-and-feedback]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Chronological idempotent ledger rebuild: wipe full inception-onward range then re-append, single save_workbook_atomic"
    - "Start-of-day snapshot staking: D-14 — all slips on the same day size off the same bankroll snapshot, day aggregate applied once at day close"
    - "Slip exclusion by reconciliation flag: D-13 — MANUAL REVIEW / Needs Payout Reconciliation slips skipped, never assigned fabricated Net PnL"

key-files:
  created: []
  modified:
    - scripts/sports_system_runner.py
    - scripts/test_slip_bankroll.py

key-decisions:
  - "Wipe scope must cover the FULL inception-onward date range (not just slip-dates) to avoid stale prop-era rows on non-slip days; changed from set(all_dates) wipe to scan-all-rows-by-date wipe (commit 539cbdf)"
  - "Live write gated behind blocking human-verify checkpoint with mandatory dry-run, backup confirmation, and second-run idempotency check before operator approval"
  - "Rebuild does NOT read JSON stake_units (may be None for 2026-06-08); always computes stake from combined_probability + combined_ev_score (Pitfall 2 mitigation)"
  - "Starting bankroll = 100.0; current_bankroll = 126.778 slips-only; prior prop-based ledger (110.619) is superseded"

patterns-established:
  - "Atomic ledger rebuild: open -> wipe -> re-append -> single save_workbook_atomic (no partial-write-on-crash)"

requirements-completed: [BANKROLL-03]

# Metrics
duration: ~90min
completed: 2026-06-22
---

# Phase 03 Plan 04: Slips-Only Bankroll Rebuild Summary

**Chronological idempotent bankroll rebase from 2026-06-08 with starting_bankroll=100; live ledger now reflects 126.778 slips-only (66 slips across 12 dates), replacing prior prop-based accounting**

## Performance

- **Duration:** ~90 min
- **Started:** 2026-06-22
- **Completed:** 2026-06-22
- **Tasks:** 3 (2 auto + 1 human-verify)
- **Files modified:** 2

## Accomplishments

- `rebuild_slip_bankroll(dry_run, inception)` implemented: chronological per-date re-stake loop from 2026-06-08, idempotent by (Date, Slip ID) via `write_slip_history_rows`, with D-13 exclusion and D-14 start-of-day snapshot semantics
- `rebuild_bankroll` wired as a dispatchable runner task with 660s budget and cooperative `master_pnl.xlsx` lock
- Live production rebuild executed and operator-approved: `bankroll.json` starting=100, current=126.778, series begins 2026-06-08, 22 MANUAL REVIEW slips excluded, backup written under `data/backups/workbooks/2026-06-22/`; second run confirmed idempotent (identical 126.778)
- Wipe-scope defect found and fixed during checkpoint verification: stale prop-era rows were left on non-slip in-range dates; fix (commit 539cbdf) now scans each sheet's Date column for all dates >= inception and removes them before re-appending; regression test `test_rebuild_wipes_stale_in_range_rows` added

## Task Commits

Each task was committed atomically:

1. **Task 1: rebuild_slip_bankroll() chronological idempotent re-stake + rebuild** — `c72ac95` (feat)
2. **Task 2: Wire rebuild_bankroll runner task with 660s timeout + workbook lock** — `421155f` (feat)
3. **Gap fix (Task 1, found during checkpoint verification):** Wipe full inception-onward range in rebuild_slip_bankroll (drop stale prop-era rows) — `539cbdf` (fix)

Task 3 (human-verify) was a real-money operator-approved live write; no separate commit was required — the live ledger state is the artifact.

## Files Created/Modified

- `scripts/sports_system_runner.py` — Added `rebuild_slip_bankroll()`, wired `rebuild_bankroll` task in `run_task`, `TASK_TIMEOUTS`, and `task_workbook_paths`
- `scripts/test_slip_bankroll.py` — Added `test_rebuild_idempotent`, `test_rebuild_starts_june8`, `test_rebuild_restake_monotonic_same_day`, `test_rebuild_wipes_stale_in_range_rows`

## Decisions Made

- Wipe scope changed from "slip-date-only" to "full inception-onward range": the initial implementation wiped only dates that had at least one graded slip, leaving stale prop-era rows on dates with no slips (e.g., 2026-06-09, 2026-06-15, 2026-06-22). Fixed before the live write was finalized.
- Rebuild reads `combined_probability` + `combined_ev_score` from slip JSON, never the JSON `stake_units` field (may be None for 2026-06-08).
- Payout multiplier is always re-derived from `calculate_slip_payout` using platform/slip_type/total_legs/winning_legs — never read back from the Slip History sheet column.
- Live write order: `save_workbook_atomic` first, then `BANKROLL.write_text(...)` — ensures a crash between the two leaves the workbook correct and bankroll.json slightly stale (recoverable on next run), not vice versa.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Wipe scope omitted non-slip in-range dates, leaving stale prop-era rows**

- **Found during:** Task 3 checkpoint verification (first live run)
- **Issue:** `rebuild_slip_bankroll` Step 3's wipe called `remove_rows_for_date(ws, date)` for dates in `all_dates` (the set of distinct slip dates). Dates within the 2026-06-08-onward range that had no graded slip — e.g., 2026-06-09, 2026-06-15, 2026-06-22 — were not wiped. Any pre-existing prop-era rows for those dates remained in Bankroll Chart Data and Daily Log, producing extra rows that violated BANKROLL-03 criterion #3 (no stale prop-era rows in the series). The bankroll value itself was never wrong (it sums only slip Net PnL); only the chart/log presentation was affected.
- **Fix:** Changed the wipe logic to scan every row in each sheet's Date column for dates >= inception, and delete matching rows regardless of whether that date had any slips. Produces a clean slate for the entire inception-onward window before re-appending.
- **Files modified:** `scripts/sports_system_runner.py`, `scripts/test_slip_bankroll.py` (added `test_rebuild_wipes_stale_in_range_rows`)
- **Verification:** Second live run confirmed 12 chart rows (one per slip date) with no extras; `test_rebuild_wipes_stale_in_range_rows` passes.
- **Committed in:** `539cbdf` (gap fix before operator approval)

---

**Total deviations:** 1 auto-fixed (Rule 1 bug)
**Impact on plan:** Fix was necessary to satisfy BANKROLL-03 criterion #3 (clean series from 2026-06-08). No scope creep. Bankroll math was correct throughout; only chart/log presentation required the fix.

## Issues Encountered

- The dry-run mode was essential: running `rebuild_slip_bankroll(dry_run=True)` before the live write allowed the operator to confirm the expected `current_bankroll` and detect the stale-row defect before any live write occurred. The atomic-save + backup pattern meant the live fix was low-risk.

## User Setup Required

None — the live write was a one-time operator-authorized run. No recurring cron schedule was added. `rebuild_bankroll` remains dispatchable via `--task rebuild_bankroll` for future one-off use.

## Next Phase Readiness

- Phase 04 (Dual Metrics and Feedback) can proceed: `bankroll.json` reflects slips-only from 2026-06-08, the Bankroll Chart Data series is clean and chronological, and Prop Accuracy sheet is populated separately for accuracy-signal use.
- The `confidence_stake` + `sync_slip_bankroll` + `rebuild_slip_bankroll` chain is fully tested; idempotency is proven on the live ledger.
- Known: Phase 04 will read the slip ROI and prop hit-rate from the now-correct ledger. No blockers from this plan.

---

*Phase: 03-slips-only-bankroll*
*Completed: 2026-06-22*

## Self-Check: PASSED

- Commits exist in git history: c72ac95, 421155f, 539cbdf — confirmed present
- Files modified: scripts/sports_system_runner.py, scripts/test_slip_bankroll.py — confirmed (per task commits and gap fix)
- Live rebuild artifacts: bankroll.json starting=100, current=126.778, series 2026-06-08 — confirmed by operator during Task 3 checkpoint
- Test suite: `cd scripts && python3 -m pytest test_stake_sizing.py test_slip_bankroll.py test_dynamic_gate8.py -x` — 35 passed (confirmed)
- BANKROLL-03 requirement satisfied: D-11 (idempotent rebuild), D-12 (in-place re-stake), D-14 (start-of-day snapshot), D-13 (MANUAL REVIEW excluded)
