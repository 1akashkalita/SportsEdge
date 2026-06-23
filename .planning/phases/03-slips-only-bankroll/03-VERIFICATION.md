---
phase: 03-slips-only-bankroll
verified: 2026-06-22T04:30:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
---

# Phase 03: Slips-Only Bankroll Verification Report

**Phase Goal:** The bankroll ledger reflects only what was actually staked and returned on DFS slips — individual prop outcomes are removed from the bankroll and preserved as a separate model-accuracy signal.
**Verified:** 2026-06-22T04:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths (from ROADMAP Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | The current bankroll balance is computed exclusively from slip Net PnL; re-running the bankroll calculation with no new slips produces the same balance (individual prop W/L rows have no effect on the balance) | VERIFIED | `sync_master_and_bankroll` contains no `BANKROLL.write_text`, no `remove_rows_for_date` on Daily Log/BCD, no `current = starting` computation. All bankroll writes are in `sync_slip_bankroll` only. `test_prop_flip_leaves_bankroll_unchanged` passes. `sync_slip_bankroll('2026-06-21', dry_run=True)` returns 126.777; live `bankroll.json` shows 126.778 (0.001 rounding from the running vs single-date calculation — both derive solely from slip Net PnL). |
| 2 | Each slip's stake is sized by confidence score — a higher-confidence slip has a larger stake than a lower-confidence slip from the same day under the same bankroll | VERIFIED | `confidence_stake()` implements exact D-02..D-06 tiered rule; D-06 monotonicity proven by `test_monotonicity`. D-14 single start-of-day snapshot enforced in `rebuild_slip_bankroll`. `test_rebuild_restake_monotonic_same_day` passes. All 7 stake_sizing tests pass. |
| 3 | The bankroll history is rebased from 2026-06-08: the historical P&L chart reflects slip-based outcomes from inception, not prior prop-based accounting | VERIFIED | Live `data/pnl/master_pnl.xlsx` Bankroll Chart Data: 12 rows, first row `('2026-06-08', 91, -9, ...)`, last row `('2026-06-21', 126.778, 26.78, ...)`. Chronological, no duplicates, no prop-era rows. `bankroll.json`: `starting_bankroll=100.0`, `current_bankroll=126.778`, `last_graded_date='2026-06-21'`. REQUIREMENTS.md still shows `[ ] BANKROLL-03` (documentation not updated), but the live ledger satisfies the criterion. |
| 4 | Prop W/L outcomes remain readable as a model-accuracy signal in a separate report or sheet, not eliminated | VERIFIED | `Prop Accuracy` sheet present in `master_pnl.xlsx` with headers `['Week','Sport','Total Props','Wins','Losses','Pushes','Hit Rate','Updated At']` and 4 data rows. Pick History intact with 277 rows. `refresh_prop_accuracy` reads Pick History only, never writes it. `test_prop_accuracy_additive` passes. |

**Score:** 4/4 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scripts/stake_sizing.py` | `confidence_stake()` + `apply_confidence_stakes()` pure staking helpers | VERIFIED | Exists, 103 lines, no runner import, no side effects at import. All 9 D-rule behaviors confirmed at REPL. D-01 fence verified at AST level (slip_type/leg_count/category only in comments). |
| `scripts/test_stake_sizing.py` | Unit coverage for D-03/D-04/D-05/D-06 tiers, zero-floor, EV gate, monotonicity | VERIFIED | 7 tests, all pass. All 4 validation-named tests present: `test_confidence_stake_tiers`, `test_monotonicity`, `test_ev_gate`, `test_zero_floor`. |
| `scripts/sports_system_runner.py` (Gate-8 removal) | `DAILY_EXPOSURE_CAP` removed; `GATE 8 — DYNAMIC EXPOSURE CAP` removed; `GATE 8 — CONCENTRATION CAP` preserved | VERIFIED | `grep -c 'DAILY_EXPOSURE_CAP'` = 0. `grep -c 'GATE 8 — DYNAMIC EXPOSURE CAP'` = 0. `grep -c 'GATE 8 — CONCENTRATION CAP'` = 1. File parses cleanly. |
| `scripts/test_dynamic_gate8.py` | Post-removal regression: no dynamic-cap skip; concentration caps still block | VERIFIED | 21 tests pass. `test_no_dynamic_cap_skip_rows_after_removal` asserts no DYNAMIC EXPOSURE CAP skip rows. `test_concentration_caps_still_block_overexposure` confirms concentration caps fire. `PropDataSourceBoundaryTests` class unchanged and green. |
| `scripts/sports_system_runner.py` (sync_slip_bankroll) | `sync_slip_bankroll()` slip-sourced ledger; prop coupling severed; Prop Accuracy sheet | VERIFIED | `def sync_slip_bankroll` at line 5126. `Needs Payout Reconciliation` exclusion at line 5178. `sync_master_and_bankroll` contains only comment references to BCD — no writes. `PROP_ACCURACY_HEADERS` defined at line 299, referenced at lines 4862, 5303, 5307. `def refresh_prop_accuracy` at line 5293. |
| `scripts/test_slip_bankroll.py` | Unit coverage: PENDING exclusion, prop-flip-leaves-bankroll-unchanged, Prop Accuracy additive, rebuild idempotency, June-8 inception | VERIFIED | 13 tests, all pass. All 6 validation-named tests present and green. |
| `scripts/sports_system_runner.py` (rebuild_slip_bankroll) | `rebuild_slip_bankroll()` + `rebuild_bankroll` task wiring | VERIFIED | `def rebuild_slip_bankroll` at line 5356. `"rebuild_bankroll"` in TASK_TIMEOUTS (660s), task_workbook_paths, and run_task mapping — 3 wiring points confirmed. `task_workbook_paths('rebuild_bankroll')` resolves to `master_pnl.xlsx`. File parses. |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `grade_slips` task dispatch | `sync_slip_bankroll(date)` | `_grade_slips_then_sync(date)` | WIRED | CR-01 fix confirmed: `run_task["grade_slips"]` calls `_grade_slips_then_sync`, which calls `sync_slip_bankroll(date)` at line 7249. No `sync_slip_bankroll` call exists in `sync_master_and_bankroll` (only comment references). |
| `rebuild_slip_bankroll` | `confidence_stake` | `from stake_sizing import confidence_stake as _cs` | WIRED | Line 5393. Reads `combined_probability` + `combined_ev_score` from slip JSON (not `stake_units` — Pitfall 2 avoided). |
| `rebuild_slip_bankroll` | `write_slip_history_rows` | lazy `__import__("grade_slips")` | WIRED | Line 5396. Idempotent (Date, Slip ID) upsert confirmed in D-12. |
| `sync_slip_bankroll` | `Slip History` (not Pick History) | `_SHH.index("Needs Payout Reconciliation") + 1` | WIRED | Line 5161. Excludes reconciliation rows at line 5178. |
| `master_pnl_workbook()` | `Prop Accuracy` sheet | additive expected-dict entry | WIRED | Line 4862: `"Prop Accuracy": PROP_ACCURACY_HEADERS` in the expected dict. |

---

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `bankroll.json` | `current_bankroll` | Slip History Net PnL via `sync_slip_bankroll` | Yes — 126.778 (verified live) | FLOWING |
| `Bankroll Chart Data` | date/balance rows | `rebuild_slip_bankroll` chronological loop | Yes — 12 rows, 2026-06-08 to 2026-06-21 | FLOWING |
| `Prop Accuracy` sheet | hit-rate by week/sport | Pick History rows via `refresh_prop_accuracy` | Yes — 4 rows with real counts (e.g. 110 props, 52 wins) | FLOWING |
| `confidence_stake()` | stake amount | `combined_probability` + `combined_ev_score` | Yes — tiered math with no hardcoded data | FLOWING |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| confidence_stake EV gate fires first | `confidence_stake(0.80, 0.0, 100) == 0.0` | 0.0 | PASS |
| confidence_stake D-03 high tier | `confidence_stake(0.75, 1.0, 100) == 2.5` | 2.5 | PASS |
| confidence_stake D-04 zero-floor | `confidence_stake(0.57, 1.5, 100) == 0.0` | 0.0 | PASS |
| bankroll.json starting_bankroll == 100 | `json.loads(bankroll.json)['starting_bankroll']` | 100.0 | PASS |
| BCD first row is 2026-06-08 | Read BCD sheet row 2 | `('2026-06-08', 91, -9, ...)` | PASS |
| No DAILY_EXPOSURE_CAP references in runner | `grep -c 'DAILY_EXPOSURE_CAP' sports_system_runner.py` | 0 | PASS |
| CONCENTRATION CAP preserved | `grep -c 'GATE 8 — CONCENTRATION CAP' sports_system_runner.py` | 1 | PASS |
| sync_slip_bankroll dry_run matches live | `sync_slip_bankroll('2026-06-21', dry_run=True)['current']` | 126.777 vs live 126.778 | PASS (sub-cent rounding from single-date vs cumulative sum) |
| Wave regression | `pytest test_stake_sizing.py test_slip_bankroll.py test_dynamic_gate8.py` | 41 passed | PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| BANKROLL-01 | 03-03 | Bankroll computed strictly from slip Net PnL; props excluded | SATISFIED | `sync_master_and_bankroll` severed; `sync_slip_bankroll` is the only bankroll writer. `test_prop_flip_leaves_bankroll_unchanged` green. REQUIREMENTS.md: `[x]`. |
| BANKROLL-02 | 03-01, 03-02 | Each slip staked using confidence-scaled sizing | SATISFIED | `confidence_stake()` implements D-02..D-06 exactly. Gate-8 global cap removed (D-07). All stake-sizing tests green. REQUIREMENTS.md: `[x]`. |
| BANKROLL-03 | 03-04 | Bankroll history rebased from 2026-06-08 | SATISFIED (live state) | Live `bankroll.json` has `starting_bankroll=100`, `current_bankroll=126.778`, BCD starts 2026-06-08 (12 rows, chronological). `rebuild_slip_bankroll` implemented and `rebuild_bankroll` task wired. Human-verified production rebuild executed (backup present at `data/backups/workbooks/2026-06-22/master_pnl.xlsx.*`). NOTE: REQUIREMENTS.md still shows `[ ]` Pending — documentation not updated post-rebuild. This is a documentation gap only; the live ledger satisfies the criterion. |
| BANKROLL-04 | 03-03 | Prop-level W/L retained as model-accuracy signal, reported separately | SATISFIED | `Prop Accuracy` sheet in `master_pnl.xlsx` with 4 data rows. `refresh_prop_accuracy` reads Pick History only. Pick History has 277 rows (untouched). REQUIREMENTS.md: `[x]`. |

---

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| None in modified files | — | — | No debt markers (TBD/FIXME/XXX/TODO/HACK) found in `stake_sizing.py`, `test_stake_sizing.py`, `test_slip_bankroll.py`, or the modified sections of `sports_system_runner.py`. |

---

### Pre-existing Known Failure (Not a Phase 3 Gap)

`test_grade_slips_legs.py::TestGradeLegAbstain::test_unrecognised_mlb_stat_returns_pending_not_loss` fails (1 test). This is a Phase 1 grading-hardening concern (plan 01-06 is incomplete). Phase 3 did not touch `grade_leg()` or stat-disposition logic — only called `write_slip_history_rows` as a consumer. Pre-existing per `MEMORY.md` (clean baseline is "2 failed, 202 passed"). Do not count against Phase 3.

---

### Documentation Gap (Non-Blocking)

**REQUIREMENTS.md BANKROLL-03 not updated to `[x]`.** The live rebuild was executed and the ledger satisfies the BANKROLL-03 criterion, but `.planning/REQUIREMENTS.md` still shows `[ ] BANKROLL-03: Pending` and the traceability table shows `Pending`. This is a documentation-only gap — the code and live data are correct. The operator should update REQUIREMENTS.md to mark BANKROLL-03 complete.

---

### Human Verification Required

None. All success criteria are verifiable from the codebase and live data files without human observation of visual or real-time behavior.

---

## Gaps Summary

No gaps blocking goal achievement. All 4 roadmap success criteria are satisfied:

1. Bankroll is computed exclusively from slip Net PnL — prop writes severed, `test_prop_flip_leaves_bankroll_unchanged` green.
2. Confidence-scaled stake sizing implemented and proven monotonic.
3. Bankroll rebased from 2026-06-08 with starting_bankroll=100 — live ledger confirmed.
4. Prop W/L preserved in Pick History and summarized in additive Prop Accuracy sheet.

The only non-blocking items are: (a) REQUIREMENTS.md not updated to mark BANKROLL-03 complete, and (b) the pre-existing Phase 1 `test_grade_slips_legs` failure unrelated to Phase 3.

---

_Verified: 2026-06-22T04:30:00Z_
_Verifier: Claude (gsd-verifier)_
