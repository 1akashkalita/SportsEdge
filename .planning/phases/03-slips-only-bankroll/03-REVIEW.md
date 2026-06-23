---
phase: 03-slips-only-bankroll
reviewed: 2026-06-22T00:00:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - scripts/stake_sizing.py
  - scripts/sports_system_runner.py
  - scripts/test_stake_sizing.py
  - scripts/test_slip_bankroll.py
  - scripts/test_dynamic_gate8.py
findings:
  critical: 1
  warning: 6
  info: 3
  total: 10
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-06-22T00:00:00Z
**Depth:** standard (scoped to phase-3 diff vs `bc7a52f^`)
**Files Reviewed:** 5
**Status:** issues_found

## Summary

Phase 3 removes the Gate-8 global exposure caps, severs the prop->bankroll coupling, and introduces a slip-sourced bankroll ledger (`sync_slip_bankroll`), a one-time chronological re-stake (`rebuild_slip_bankroll`), a pure staking helper (`stake_sizing.py`), and a Prop Accuracy summary sheet. All 35 phase-3 tests pass and the staking math, EV gate, tier boundaries, idempotent upsert, and stale-row wipe all behave correctly against real data sampled from `data/research/slips/`.

The single most serious problem is a **wiring gap**: the new `sync_slip_bankroll` — the function whose entire purpose is to keep `bankroll.json`/Daily Log/Bankroll Chart Data updated from Slip History on the forward path — is never called by any task or pipeline. After the prop coupling was cut, the daily `grade_slips` path no longer updates the bankroll at all; only the manual `rebuild_bankroll` task does. This defeats the phase's core value ("bankroll sourced from Slip History") for everyday runs and is a data-correctness / operability blocker.

Several secondary issues degrade reporting fidelity and idempotency robustness without being immediately catastrophic. The gate-logic / pick-verdict surface is clean: the only selection change is the sanctioned global-cap removal; concentration caps, correlation caps, and `evaluate_no_bet_gates` are untouched, and the gate8 tests confirm no `DYNAMIC EXPOSURE CAP` skip rows are emitted.

## Critical Issues

### CR-01: `sync_slip_bankroll` is never invoked — forward daily path no longer updates the bankroll

**File:** `scripts/sports_system_runner.py:5113` (definition); only caller is tests
**Issue:**
The prop->bankroll coupling was severed in `sync_master_and_bankroll` (lines 5089-5094: no more `remove_rows_for_date`, no `BANKROLL.write_text`, no Bankroll Chart Data append). The replacement, `sync_slip_bankroll`, is defined but has **zero production callers**:

- `grade_slips_for_date` (in `grade_slips.py`) writes Slip History rows and saves the workbook but never calls `sync_slip_bankroll`.
- The `grade_slips` runner task (`run_task` mapping) calls `grade_slips_for_date` only.
- `sync_master_and_bankroll` (the post-grading sync at line 5961 and the `check_results`/`verify` path at line 6077) now intentionally does NOT touch the bankroll.
- The only function that rebuilds the slip bankroll, `rebuild_slip_bankroll`, runs solely from the manual one-time `rebuild_bankroll` task and is explicitly "NOT added to cron schedule" (line 7155).

Net effect: on every scheduled run, `bankroll.json`, the Daily Log Running Bankroll, and Bankroll Chart Data go **stale** until an operator manually runs `rebuild_bankroll`. The phase's stated core value — a bankroll continuously sourced from Slip History — is not realized on the automated path. For a real-money system this is a silent data-staleness defect.

**Fix:** Wire `sync_slip_bankroll(date)` into the grading path so the slip bankroll advances on schedule. Either call it at the end of `grade_slips_for_date` (after the master Slip History save) or in the `grade_slips` task lambda, e.g.:
```python
"grade_slips": lambda: _grade_slips_then_sync(today_str()),
# where:
def _grade_slips_then_sync(date: str) -> dict[str, Any]:
    summary = __import__("grade_slips").grade_slips_for_date(date)
    summary["slip_bankroll"] = sync_slip_bankroll(date)
    return summary
```
If the intent is for the forward sync to land in a later wave, document that explicitly and gate the milestone so the bankroll is not silently frozen between manual rebuilds.

## Warnings

### WR-01: `sync_slip_bankroll` upsert/grouping uses inconsistent date normalization (idempotency hazard)

**File:** `scripts/sports_system_runner.py:5293-5294, 5316-5317` (rebuild) and `grade_slips.py:396` (`write_slip_history_rows`)
**Issue:**
The rebuild collects/compares Slip History dates with `str(raw_date or "")[:10]` (10-char slice), but `write_slip_history_rows` matches existing rows for upsert with the full `str(cell_date or "") == str(date)` (no slice). Today every Slip History date cell is a bare `"YYYY-MM-DD"` string (verified against `data/pnl/master_pnl.xlsx`), so the two agree and upsert is idempotent. But if any Date cell ever holds a timestamp (`"2026-06-08T..."`) or a `datetime`, the rebuild would group it under the 10-char key while `write_slip_history_rows` fails the equality test and **appends a duplicate row instead of overwriting** — silently double-counting that slip's Net PnL into the bankroll.
**Fix:** Normalize both sides identically. In `write_slip_history_rows`, compare `str(cell_date or "")[:10] == str(date)[:10]`, and/or have the rebuild pass already-normalized dates. Add a regression test with a timestamp-valued Date cell.

### WR-02: Re-stake silently zeroes a genuinely-won slip when its `slips_<date>.json` signal is missing

**File:** `scripts/sports_system_runner.py:5337-5341, 5375-5381` (rebuild loop)
**Issue:**
For each Slip History row, `prob`/`ev` come only from `slip_signals[slip_id]`. When the date has no `slips_<date>.json` file, or the slip_id isn't present in the JSON, both fall back to `0` → `confidence_stake` returns `0` → `calculate_slip_payout(stake_units=0)` yields `gross=0`, `net=0`. A real, graded, winning slip therefore contributes **$0** to the bankroll with no warning. This is the documented D-13/Pitfall-2 "no signal -> no bet" behavior, but in a real-money rebuild it means a single missing/renamed JSON file silently understates the bankroll.
**Fix:** Track and surface a `slips_missing_signal` count in the return payload and log a warning when a non-reconciliation Slip History row has no matching JSON signal, so a missing file is visible rather than silently swallowed.

### WR-03: Rebuild rewrites `Contains Demon`/`Contains Goblin` audit columns to `False` for special-line slips

**File:** `scripts/sports_system_runner.py:5371-5387` (synthetic `legs_from_signals` -> `write_slip_history_rows` -> `slip_history_row`)
**Issue:**
`slip_history_row` (`slip_payouts.py:201-203`) recomputes `Contains Demon`/`Contains Goblin`/`Special Line Count` from the legs list it is handed. The rebuild builds `legs_from_signals` from the slip JSON legs, which carry no `line_type`/`odds_type` field (verified across all 15 `slips_*.json`), and pads with empty `{...}` dicts when the count differs. So after a rebuild, these audit columns are forced to `False`/`0` even for slips that originally recorded a demon/goblin. The payout *math* is unaffected (the rebuild reads `contains_demon`/`contains_goblin` from the sheet and passes them to `calculate_slip_payout` at lines 5350-5351), but the sheet's special-line audit trail is corrupted. Current data has no demon/goblin slips, so impact is presently nil; it is a latent data-fidelity defect.
**Fix:** Preserve the original `Contains Demon`/`Contains Goblin`/`Special Line Count` cells (read them from the sheet and write them back) instead of letting `slip_history_row` recompute from synthetic legs, or carry `line_type` through the synthetic legs.

### WR-04: Obsidian bankroll file mixes prop-era `day_pnl` with slip-era `current`/`roi`

**File:** `scripts/sports_system_runner.py:5106-5109` (`sync_master_and_bankroll`)
**Issue:**
After severing, `current`, `roi`, and `bankroll` are read from the slip-sourced `bankroll.json`, but `day_pnl` (line 5106) and `flat` are still computed from **Pick History prop rows**. `obsidian_update_bankroll_files(date, bankroll, flat, current, roi, day_pnl)` (line 5109) and the two `obsidian_update_results_section` calls therefore publish a prop-derived daily PnL alongside a slip-derived running bankroll. The "Day PnL" shown in Obsidian will not reconcile with the change in the bankroll figure on the same note — a confusing/contradictory operator report on a real-money dashboard.
**Fix:** Source the Obsidian `day_pnl` from the slip bankroll (e.g., have `sync_slip_bankroll` return the day's slip net and pass it through), or clearly label the prop figure as prop-accuracy-only and the bankroll figure as slip-only so they are not read as a single ledger.

### WR-05: `sync_slip_bankroll` always reports `roi_percentage_current = 0` (Units Bet never populated)

**File:** `scripts/sports_system_runner.py:5180-5181, 5159` (and appended Daily Log row at 5160)
**Issue:**
ROI is `round((total_profit / total_units) * 100, 2) if total_units else 0`. The Daily Log rows appended by `sync_slip_bankroll` put `None` in the Units Bet column (index 5): `wb["Daily Log"].append([date, "SLIPS", None, None, None, None, day_pnl, "", ...])`. Summing that column yields `total_units == 0`, so ROI is permanently `0`. Meanwhile `rebuild_slip_bankroll` computes ROI as `((current-100)/100)*100`. The two bankroll writers thus disagree on the ROI definition, and `sync_slip_bankroll`'s ROI is meaningless. (Compounded by CR-01, `sync_slip_bankroll` doesn't run today — but if/when it is wired in, ROI will be wrong.)
**Fix:** Either populate Units Bet with the day's total slip stake so the units-based ROI is real, or align `sync_slip_bankroll` ROI to the `rebuild_slip_bankroll` profit-on-starting-bankroll definition. Pick one definition and use it in both writers.

### WR-06: `refresh_performance_breakdown(wb, bankroll, [])` zeroes the Performance Breakdown sheet on every slip sync

**File:** `scripts/sports_system_runner.py:5217-5218` (`sync_slip_bankroll`)
**Issue:**
`refresh_performance_breakdown` clears and rewrites the whole sheet from `graded_rows`. `sync_slip_bankroll` passes `[]`, so Wins/Losses/Pushes/Graded Picks/Units Bet/Net PNL are all written as `0` (only Current Bankroll / ROI come from `bankroll`). Any prop-era performance data previously on that sheet is wiped to zeros each sync. The comment calls this "slip-aware (graded_rows=[] because slip grading is tracked separately)", but the visible result is a Performance Breakdown that reports zero wins/losses forever. Not a schema change, but a data-overwrite that misrepresents real performance.
**Fix:** Compute the slip W/L/P/units/PnL from Slip History and pass them to `refresh_performance_breakdown`, or skip the call entirely from `sync_slip_bankroll` and keep Prop Accuracy as the dedicated prop scoreboard.

## Info

### IN-01: `slip_history_row` rewrites `Graded At` to "now" on every rebuild

**File:** `scripts/slip_payouts.py:205-213` via `scripts/sports_system_runner.py:5383` (`write_slip_history_rows`)
**Issue:** The upsert overwrites `Graded At` with `now_utc_iso()` each time. The financial columns (Stake Units / Gross Return / Net PnL) remain stable so bankroll idempotency holds, but the original grading timestamp is lost on every rebuild, weakening the audit trail.
**Fix:** Preserve the existing `Graded At` cell on upsert when the financial result is unchanged.

### IN-02: Slips that newly flip to MANUAL REVIEW during re-derivation are counted in `slips_restaked`, not `slips_skipped`

**File:** `scripts/sports_system_runner.py:5395-5405` (`rebuild_slip_bankroll`)
**Issue:** `slips_skipped` only counts rows whose *original sheet* `Needs Payout Reconciliation` is truthy. A slip that was GRADED but, after re-derivation (e.g. power slip with special line lacking an actual multiplier, or missing config), now returns `needs_payout_reconciliation=True` is still counted in `slips_restaked` while contributing `0` to the bankroll. The return-payload counts are therefore mildly misleading for reconciliation diagnostics.
**Fix:** After computing `payout`, increment a separate `slips_flipped_to_review` counter when `payout.get("needs_payout_reconciliation")` is truthy, and exclude those from `slips_restaked`.

### IN-03: `stake_sizing.confidence_stake` `start_of_day_bankroll` is unvalidated

**File:** `scripts/stake_sizing.py:25-66`
**Issue:** A negative `start_of_day_bankroll` (possible after a deep drawdown) would produce a negative stake; the function only guards the probability/EV inputs. Low risk given the rebuild floors bankroll arithmetic, but a defensive `max(0.0, ...)` on the returned stake (or an early guard) would make the helper robust in isolation.
**Fix:** Clamp the returned stake to `>= 0.0`, or document that callers must pass a non-negative bankroll.

---

_Reviewed: 2026-06-22T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
