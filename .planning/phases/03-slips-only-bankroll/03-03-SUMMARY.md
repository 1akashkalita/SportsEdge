---
phase: 03-slips-only-bankroll
plan: "03"
subsystem: bankroll-ledger
tags: [bankroll, slip-sourced, prop-accuracy, D-09, D-10, D-13, BANKROLL-01, BANKROLL-04]
dependency_graph:
  requires: [03-01, 03-02]
  provides: [sync_slip_bankroll, prop-coupling-severed, Prop-Accuracy-sheet, refresh_prop_accuracy]
  affects: [scripts/sports_system_runner.py, scripts/test_slip_bankroll.py]
tech_stack:
  added: []
  patterns: [slip-sourced-bankroll, additive-sheet-migration, TDD-red-green, inspect-ast-assertion]
key_files:
  created:
    - scripts/test_slip_bankroll.py
  modified:
    - scripts/sports_system_runner.py
decisions:
  - "D-09 implemented: prop->bankroll coupling severed in sync_master_and_bankroll; bankroll.json, Daily Log Running Bankroll, and Bankroll Chart Data now written only by sync_slip_bankroll"
  - "D-13 implemented: Needs Payout Reconciliation == True rows excluded from bankroll sum in sync_slip_bankroll (treats both bool True and string 'TRUE'/'True' as excluded)"
  - "D-10 implemented: PROP_ACCURACY_HEADERS added; Prop Accuracy sheet added via master_pnl_workbook() additive expected dict; refresh_prop_accuracy reads Pick History only"
  - "sync_master_and_bankroll preserved for Pick History upsert + Obsidian results; reads bankroll.json for current values to pass to Obsidian but does not update it"
  - "test_prop_flip_leaves_bankroll_unchanged uses AST inspection of sync_master_and_bankroll source to verify no wb['Bankroll Chart Data'].append() calls exist (comments ignored)"
  - "sync_slip_bankroll accepts _wb_override/_master_override/_bankroll_override for in-memory testing without live workbook access"
metrics:
  duration_minutes: 20
  completed_date: "2026-06-23"
  tasks_completed: 2
  files_changed: 2
---

# Phase 3 Plan 3: Slip-Sourced Bankroll + Prop Accuracy Summary

**One-liner:** slip-sourced bankroll ledger via sync_slip_bankroll with D-13 reconciliation exclusion, prop coupling severed in sync_master_and_bankroll, and additive Prop Accuracy sheet with per-week hit-rate writer.

## What Was Built

### Task 1: sync_slip_bankroll + severed prop coupling (GREEN after RED)

**`sync_slip_bankroll(date, dry_run=False)`** added to `sports_system_runner.py`:
- Sources bankroll from master Slip History sheet (not Pick History)
- D-13: excludes rows where `Needs Payout Reconciliation` is truthy (`True` bool or string `"TRUE"/"True"`)
- Rebuilds Daily Log and Bankroll Chart Data idempotently via `remove_rows_for_date` + re-append
- Sums all Daily Log Day PnL to compute `current = starting + total_profit`
- Writes workbook atomically via `save_workbook_atomic` BEFORE writing `bankroll.json` (T-03-08)
- `dry_run=True` returns computed values without any writes (for in-memory test fixtures)

**`sync_master_and_bankroll` severed (D-09 / BANKROLL-01):**
- Removed: `remove_rows_for_date` on Daily Log / Bankroll Chart Data
- Removed: Daily Log bankroll rebuild, `total_profit` / `current=starting+profit` computation
- Removed: `bankroll.json` write via `BANKROLL.write_text`
- Removed: `Bankroll Chart Data` append
- Removed: `refresh_performance_breakdown` call
- Retained: Pick History upsert loop + Obsidian results/bankroll file updates (reads bankroll.json for current values but does not mutate it)

### Task 2: Prop Accuracy sheet + test suite (GREEN after RED)

**`PROP_ACCURACY_HEADERS`** constant added after `RESULT_HEADERS`:
```python
PROP_ACCURACY_HEADERS = ["Week", "Sport", "Total Props", "Wins", "Losses", "Pushes", "Hit Rate", "Updated At"]
```

**`master_pnl_workbook()` additive migration:** `"Prop Accuracy": PROP_ACCURACY_HEADERS` added to `expected` dict — no existing sheet/column renamed or dropped.

**`refresh_prop_accuracy(wb)`** clears + rewrites Prop Accuracy sheet from Pick History prop rows:
- Groups by ISO week (`YYYY-WNN`) + sport
- Hit Rate = wins/(wins+losses), PUSH excluded from denominator, divide-by-zero → 0
- Never writes to Pick History or Results (D-10)

**`test_slip_bankroll.py`** (3 tests, all green):
- `test_pending_slip_excluded`: D-13 — PENDING/MANUAL REVIEW slip contributes 0 to bankroll sum
- `test_prop_flip_leaves_bankroll_unchanged`: BANKROLL-01 — AST inspection confirms no `wb["Bankroll Chart Data"].append()` in prop path; dry_run bankroll invariant to prop result changes
- `test_prop_accuracy_additive`: BANKROLL-04 — Prop Accuracy sheet created, Pick History headers unchanged after `refresh_prop_accuracy`

## Verification Results

```
cd scripts && python3 -m pytest test_slip_bankroll.py -x
3 passed in 0.98s

cd scripts && python3 -m pytest test_stake_sizing.py test_slip_bankroll.py test_dynamic_gate8.py -x
31 passed in 0.79s

grep -c 'def sync_slip_bankroll' scripts/sports_system_runner.py  → 1
grep -c 'def refresh_prop_accuracy' scripts/sports_system_runner.py  → 1
grep -c 'PROP_ACCURACY_HEADERS' scripts/sports_system_runner.py  → 4
python3 -c "import ast; ast.parse(open('scripts/sports_system_runner.py').read())"  → OK
```

## Deviations from Plan

**1. [Rule 1 - Bug] AST inspection instead of string search for Bankroll Chart Data check**
- **Found during:** Task 2 test implementation
- **Issue:** `sync_master_and_bankroll` has "Bankroll Chart Data" in _comments_ explaining the severing (to document what was removed). A naive `assertNotIn("Bankroll Chart Data", src)` would fail on the comment text.
- **Fix:** Updated `test_prop_flip_leaves_bankroll_unchanged` to use Python's `ast` module to walk the function AST and check for actual `wb["Bankroll Chart Data"].append()` call nodes rather than checking the raw source text.
- **Files modified:** `scripts/test_slip_bankroll.py`
- **Commit:** 1a518e2

## Threat Mitigations Applied

| Threat ID | Status | Evidence |
|-----------|--------|---------|
| T-03-05 | Mitigated | `test_pending_slip_excluded` proves PENDING slips contribute 0 |
| T-03-06 | Mitigated | `test_prop_flip_leaves_bankroll_unchanged` proves bankroll invariant to prop changes |
| T-03-07 | Mitigated | `test_prop_accuracy_additive` proves Pick History headers unchanged |
| T-03-08 | Mitigated | `save_workbook_atomic` called before `bankroll_path.write_text` in sync_slip_bankroll |

## TDD Gate Compliance

RED gate: commit `1fb892b` — `test(03-03): add failing tests for sync_slip_bankroll + Prop Accuracy (RED)`
GREEN gate: commit `1a518e2` — `feat(03-03): sync_slip_bankroll + sever prop coupling + Prop Accuracy sheet (GREEN)`

## Self-Check: PASSED

- `scripts/sports_system_runner.py` exists and parses: FOUND
- `scripts/test_slip_bankroll.py` exists: FOUND
- RED commit 1fb892b exists: FOUND
- GREEN commit 1a518e2 exists: FOUND
- `def sync_slip_bankroll` count == 1: FOUND
- `def refresh_prop_accuracy` count == 1: FOUND
- `PROP_ACCURACY_HEADERS` count >= 2: FOUND (4 occurrences)
- `Needs Payout Reconciliation` inside sync_slip_bankroll: FOUND
- `sync_master_and_bankroll` has no `BANKROLL.write_text`: CONFIRMED
- All 31 wave regression tests pass: CONFIRMED
