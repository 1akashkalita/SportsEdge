---
phase: 02-slip-reconstruction-and-grading
verified: 2026-06-24T00:00:00Z
status: passed
score: 4/4 success criteria verified
re_verification:
  previous_status: none
  note: "Initial verification — Phase 2 had SUMMARYs 02-1..02-3 but no VERIFICATION.md and no UAT."
requirements_disposition:
  - id: SLIPS-01
    status: Complete
    evidence: "build_slips.py (692 lines) wired into daily flow via cron (HERMES_SPORTS_BUILD_SLIPS 08:20) + ensure_slip_defs subprocess."
  - id: SLIPS-02
    status: Complete
    evidence: "grade_slips.grade_leg/grade_slip + Slip History populated (88 rows, all financial cols filled for 66 GRADED rows)."
  - id: SLIPS-03
    status: "FLIP Pending -> Complete"
    evidence: "master_pnl Slip History: 88 rows / 12 distinct dates 2026-06-08..2026-06-21, ZERO duplicate (Date,Slip ID) keys. Idempotent upsert proven by re-execution."
  - id: SLIPS-04
    status: Complete
    evidence: "Slip History and Pick History/Prop Accuracy are separate sheets; 0 of 279 Pick History rows carry a Slip ID."
gaps: []
human_verification: []
---

# Phase 2: Slip Reconstruction and Grading — Verification Report

**Phase Goal:** The Slip History sheet is populated — the model's recommended slips are reconstructed per day, graded against trustworthy results from Phase 1, and backfilled across June 8–21 as a verifiable backtest.
**Verified:** 2026-06-24
**Status:** passed (4/4 success criteria)
**Re-verification:** No — initial verification (no prior VERIFICATION.md, no UAT existed for this phase).

## Goal Achievement

### Observable Truths (the 4 Success Criteria)

| # | Truth (Success Criterion) | Status | Evidence |
|---|---------------------------|--------|----------|
| 1 | Running the daily picks flow produces slip records in Slip History (legs, slip result, payout multiplier, gross return, net PnL) — sheet not empty after a daily run | ✓ VERIFIED | `master_pnl.xlsx` "Slip History" holds **88 data rows**. All 66 GRADED rows have non-null Net PnL and Gross Return; the 23-column `SLIP_HISTORY_HEADERS` includes Legs, Slip Result, Standard/Estimated/Actual Payout Multiplier, Gross Return, Net PnL. Production path: cron `build_slips.py --date today` (08:20) builds slip defs; the runner `grade_slips` task → `_grade_slips_then_sync` → `grade_slips_for_date` grades + upserts. `daily_picks` itself only calls `ensure_slip_history_sheet` (sheet provisioning), consistent with the subprocess-isolation architecture — slip production is the dedicated `grade_slips` task, not inline in `daily_picks`. See "Wiring note" below. |
| 2 | Each slip's grade derives from trustworthy P1 results: all-WIN→WIN, any-LOSS→LOSS; slip success and individual-prop success stored as distinct metrics; any unresolved leg→PENDING (not LOSS) | ✓ VERIFIED | `grade_leg` (grade_slips.py:182) reuses P1 `stat_value_for_prop` unchanged; on `None` it returns `LEG_PENDING` (line 216-222) — NEVER LOSS. `grade_slip` passes raw leg statuses (incl. PENDING/PUSH) to `calculate_slip_payout`, whose ambiguous-leg branch (slip_payouts.py:90-105) forces `MANUAL REVIEW` + `needs_payout_reconciliation=True`, `net_pnl=None`. Power slips: `winning_legs != total_legs` → `net = -stake` (any LOSS → slip loss, line 132-135). Data confirms: 22/22 MANUAL REVIEW rows have Net PnL=None and Needs Payout Reconciliation=True (PENDING-not-LOSS holds in real data). Distinct metrics: Winning Legs / Losing Legs / Push-Void-DNP Legs / Slip Result columns are per-slip and separate from prop tracking. |
| 3 | **SLIPS-03** — June 8–21 backfill completes without duplicate rows; re-running a date already having slip records is idempotent | ✓ VERIFIED | Data: 88 rows / **12 distinct dates** spanning 2026-06-08..2026-06-21, **0 duplicate (Date, Slip ID) keys** (programmatic Counter check). Per-day workbooks hold 82 rows (the 6-row delta is mixed-sport slips routed to master only, grade_slips.py:600-627). Off-days June 9/15 legitimately absent. Code: `write_slip_history_rows` (grade_slips.py:360-470) scans existing rows for matching `(Date, Slip ID)` with `[:10]` date normalization (line 412-417) and **overwrites in place** when found, else appends. `slip_id_for` (line 248) is `SHA1(date|category|sorted-leg-identities)[:8]` — stable across re-runs, distinct for different leg sets. **Proven by re-execution:** writing 8 graded slips twice produced 7 data rows both times (rows_written=8 each, data rows 7→7; one pair dedups across categories), IDEMPOTENT=True. |
| 4 | Operator can distinguish slip ROI from prop win-rate at a glance (separate tracking, not interleaved) | ✓ VERIFIED | Physically separate sheets in `master_pnl.xlsx`: **Slip History** (slip ROI: Net PnL, Gross Return, payout multipliers) vs **Pick History** (prop-level Result/Units/PnL) vs **Prop Accuracy** (Week / Sport / Total Props / Wins / Losses / Hit Rate — at-a-glance model accuracy). Non-interleaving confirmed in data: **0 of 279 Pick History prop rows carry a Slip ID**; `pick_history_rows_count_for_bankroll` (slip_payouts.py:173) explicitly excludes any Slip-ID-bearing row from bankroll PnL. `test_slip_rows_not_in_results` asserts Results sheet untouched by slip writes. |

**Score:** 4/4 success criteria verified.

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scripts/grade_slips.py` | Leg grading + slip aggregation + idempotent upsert + backfill + CLI | ✓ VERIFIED | 872 lines; all Wave-1/2/3 exports present and wired (build_date_box_scores, grade_leg, slip_id_for, grade_slip, write_slip_history_rows, grade_slips_for_date, ensure_slip_defs, backfill_range, main). Imports cleanly. |
| `scripts/slip_payouts.py` | calculate_slip_payout, slip_history_row, ensure_slip_history_sheet, SLIP_HISTORY_HEADERS | ✓ VERIFIED | Ambiguous-leg → MANUAL REVIEW branch and GRADED net-PnL math present and correct; 23-column header schema. |
| `scripts/build_slips.py` | Slip construction from vetted picks (SLIPS-01) | ✓ VERIFIED | 692 lines; filter_to_vetted + build_slips + JSON output; wired via cron and ensure_slip_defs subprocess. |
| `scripts/sports_system_runner.py` | grade_slips runner task + timeout + lock paths | ✓ VERIFIED | `run_task["grade_slips"]` dispatch (line 7806), `TASK_TIMEOUTS["grade_slips"]=660` (line 134, within 720s cron ceiling), `task_workbook_paths` grade_slips branch locks nba+mlb per-day + master (line 7637). |
| `data/pnl/master_pnl.xlsx` "Slip History" | Backfilled slip ledger | ✓ VERIFIED | 88 rows / 12 dates / 0 dups (see criterion 3). |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|----|--------|---------|
| cron / runner | grade_slips_for_date | `run_task["grade_slips"]` → `_grade_slips_then_sync` | ✓ WIRED | runner line 7806/7665-7677 |
| grade_slip | calculate_slip_payout | raw leg_results passthrough | ✓ WIRED | grade_slips.py:322-330 (no pre-collapse) |
| grade_leg | P1 stat_value_for_prop | importlib reuse of runner | ✓ WIRED | grade_slips.py:44, 214 |
| write_slip_history_rows | Slip History sheet | (Date, Slip ID) upsert | ✓ WIRED | grade_slips.py:412-466; idempotency re-proven |
| backfill_range | build_slips.py | ensure_slip_defs subprocess | ✓ WIRED | grade_slips.py:653-702 (built June 11/12/13/14/16 per SUMMARY; defs present on disk) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Idempotent upsert (no dup on re-write) | re-ran `write_slip_history_rows` twice on June-21 defs | 7 data rows both writes; IDEMPOTENT=True | ✓ PASS |
| Backfill rows present & unique | Counter over master Slip History | 88 rows / 12 dates / 0 dup keys | ✓ PASS |
| GRADED financial cols populated | scan Net PnL / Gross Return | 66/66 non-null | ✓ PASS |
| PENDING-not-LOSS in real data | scan MANUAL REVIEW rows | 22/22 Net PnL=None, recon=True | ✓ PASS |
| Targeted test suite | `pytest test_slip_payouts.py test_grade_slips_legs.py test_grade_slips_aggregate.py test_grade_slips_backfill.py -q` | 53 passed, 1 failed (known stale) | ✓ PASS (see note) |

### Requirements Coverage

| Requirement | Description | Status | Evidence |
|-------------|-------------|--------|----------|
| SLIPS-01 | Reconstruct model slips per day from projections/correlations (build_slips.py wired) | ✓ SATISFIED | build_slips.py substantive; cron + ensure_slip_defs wiring |
| SLIPS-02 | Legs graded vs P1 results; Slip History populated (legs, result, multiplier, gross, net) | ✓ SATISFIED | grade_leg/grade_slip + 88 populated rows |
| SLIPS-03 | Slips backfilled across June 8–21 as a backtest | ✓ SATISFIED (was Pending) | 88 rows / 12 dates / 0 dups — see disposition below |
| SLIPS-04 | Slip success vs individual-prop success tracked separately | ✓ SATISFIED | Separate Slip History vs Pick History/Prop Accuracy; 0/279 prop rows carry Slip ID |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | No TBD/FIXME/XXX in grade_slips.py, slip_payouts.py, build_slips.py | ℹ️ Info | No unresolved debt markers in phase files |

### Known Test Failure (assessed, NOT a gap)

`test_grade_slips_legs::test_unrecognised_mlb_stat_returns_pending_not_loss` — **FAIL, expected and benign.**

- The test (written in Wave 1) asserts `"hits runs rbis"` (space-separated) abstains to `LEG_PENDING`.
- Wave 2 deliberately added `_normalize_stat` mapping `"hits runs rbis" → "hits+runs+rbis"` (the documented MUST-FIX) so combo legs *resolve* instead of abstaining — without it almost no real slip would grade.
- With the Freeman fixture (3H/2R/1RBI = 6) vs line 2.5 OVER, the correct grade is **WIN**, which is exactly what the code now returns.
- **The test encodes pre-normalization behavior and is stale; the live behavior is correct and intended.** It does NOT affect Criterion 2: the PENDING-not-LOSS money-safety guarantee is independently covered by passing tests `test_not_derivable_stat_returns_pending_not_loss` (fantasy score → PENDING), the absent-player abstain test, and aggregate `test_pending_leg_is_manual_review`. Recommend updating/removing the stale Wave-1 assertion (housekeeping; not a Phase-2 blocker).

### Wiring note — Criterion 1 phrasing

Criterion 1 says "Running the daily picks flow automatically produces slip records." In this codebase the slip pipeline is intentionally a *separate* stage from `daily_picks(sport)`: `build_slips.py` (cron 08:20) writes slip defs, and the runner `grade_slips` task grades + upserts to Slip History. `daily_picks` only provisions the sheet (`ensure_slip_history_sheet`). This matches the system's subprocess-isolation architecture (the orchestrator does not inline fetch/build/grade logic) and the SLIPS-01 wording ("build_slips.py wired into the flow"). The end-to-end "daily flow" therefore does populate Slip History — via the dedicated cron + grade_slips task, not via a single `daily_picks` call. This is a wording nuance, not a gap; the observable outcome (populated Slip History after the daily flow) is met.

### Gaps Summary

No goal-blocking gaps. All four success criteria are verified against actual code and the persisted `master_pnl.xlsx` data. The single test failure is a stale Wave-1 assertion contradicted by the intended Wave-2 normalization fix, with money-safety still covered by other passing tests.

### SLIPS-03 Disposition

**FLIP from Pending → Complete.** REQUIREMENTS.md currently marks SLIPS-03 Pending, but the codebase + data prove it is delivered: `master_pnl.xlsx` "Slip History" holds 88 rows across 12 distinct dates (2026-06-08..2026-06-21) with **zero duplicate (Date, Slip ID) keys**, the (Date, Slip ID) upsert is idempotent (re-proven by re-execution: identical re-write yields the same row count, no duplicates), and `backfill_range` builds missing defs via `ensure_slip_defs`. The Pending status is stale and should be updated to Complete in both the checkbox (line 21) and the traceability table (line 64).

---

_Verified: 2026-06-24_
_Verifier: Claude (gsd-verifier)_
