---
phase: 04-dual-metrics-and-feedback
reviewed: 2026-06-23T00:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - scripts/calibration.py
  - scripts/metrics_report.py
  - scripts/generate_projections.py
  - scripts/sports_system_runner.py
  - scripts/test_metrics_report.py
  - scripts/test_weekly_metrics.py
findings:
  critical: 0
  warning: 3
  info: 4
  total: 7
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-06-23T00:00:00Z
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Phase 4 adds two new standalone modules (`calibration.py`, `metrics_report.py`), a `load_calibration_factor` + sigma-injection hook in `generate_projections.build_projection`, and a `weekly_metrics` runner task. I reviewed both new modules fully and the Phase-4 diff (`91956d3^..HEAD`) for the two large pre-existing files.

**Integrity verdict (the load-bearing concern for a real-money system): PASS.** The additive-only and METRICS-03 guarantees hold up under adversarial scrutiny:

- `calibration.py` is structurally isolated — no import of `sports_system_runner`, `evaluate_no_bet_gates`, or grading code (verified by AST tests AND by direct reading). It reads `master_pnl.xlsx` in `read_only=True` mode and writes only `calibration.json`. I confirmed empirically that running `compute_and_update_calibration` against a seeded Pick History leaves every `Result` value byte-identical (no verdict mutation).
- The calibration factor is applied at projection time (sigma widening), strictly upstream of the gate gauntlet. `evaluate_no_bet_gates` never reads `calibration.json` or `load_calibration_factor`. Gate output is therefore invariant to calibration state.
- The `weekly_metrics` task is correctly wired into `TASK_TIMEOUTS` (660s, under the 720s Hermes hard-kill), acquires the cooperative `master_pnl.xlsx` lock, runs under the global `fcntl.LOCK_EX`, and degrades to no-op on Telegram/Obsidian/aggregation/calibration failure (every external call is wrapped). No secrets are hardcoded; `calibration.json` writes are atomic (`.json.tmp` + `os.replace`).
- The Phase-4 targeted tests pass (71 passed, 3 skipped).

The defects below are correctness/quality issues in the new calibration math and resource hygiene — none breach the integrity contract or alter pick verdicts, so none are BLOCKER. The most consequential is WR-01 (the calibration gate/denominator population mismatch), which can bias the per-sport factor when prop rows lack a Model Over Probability value.

## Warnings

### WR-01: Calibration gate and empirical hit-rate use a different population than `model_implied`

**File:** `scripts/calibration.py:68-98` (gate at line 72; empirical at line 81; model_implied at line 93)
**Issue:** The function docstring (line 56) states `n_gate: minimum MOP-backed outcomes required before factor moves`, but the implementation gates on `n_outcomes = wins + losses` (line 72), not `n_with_mop = len(mop_values)`. Worse, `empirical` (line 81) is computed over *all* WIN/LOSS rows, while `model_implied` (line 93) is computed over *only* the MOP-backed subset. When not every graded PROP row carries a `Model Over Probability` (which is not guaranteed — the upsert at `sports_system_runner.py:4826` only populates MOP `or` from source, and it can be `None`), the two populations diverge and `raw_ratio = model_implied / empirical` becomes a biased estimate that still moves the real-money sigma factor.

Demonstrated: with `wins=15, losses=15` (gate passes on `n_outcomes=30`) but only 3 MOP values `[0.9,0.9,0.9]`, `empirical=0.5` (over 30) vs `model_implied=0.9` (over 3) → `raw_ratio=1.8` → `new_factor=1.05`. The factor moved on a 3-sample model estimate while claiming a 30-sample gate.

**Fix:** Gate on (and compute `empirical` over) the same MOP-backed population. Either restrict the win/loss tally to rows that also have a parseable MOP, or gate on `n_with_mop`:
```python
n_eff = n_with_mop  # the population model_implied is actually computed over
if n_eff < n_gate:
    return prev_factor, {"reason": f"gate not met: n={n_eff} < {n_gate}", ...}
# and compute empirical over the SAME MOP-backed rows, not all wins+losses
```
Track wins/losses only for rows where MOP is present, so `empirical` and `model_implied` share a denominator.

### WR-02: `compute_and_update_calibration` docstring claims idempotence it does not have

**File:** `scripts/calibration.py:288` (docstring) vs `:103-106` (stepping logic)
**Issue:** The docstring asserts "Running twice on unchanged data is idempotent (factors converge to the same value)." This is false for the as-written stepping logic. With identical data the factor advances by up to `MAX_STEP` (0.05) on *every* invocation until it reaches the clamped target. Demonstrated: identical MLB data produced `1.00 → 1.05` (cycle 1) → `1.10` (cycle 2), and would continue to `1.20`. Since `weekly_metrics` is a cron job, an operator re-running it (or a retry) the same week double-steps the factor without new data — directly affecting next week's projection probabilities. The "idempotent" claim is not just a doc error; it implies a safety property that does not exist.
**Fix:** Either (a) make the cycle idempotent by recomputing toward the target from a stored *baseline* rather than from the last `prev_factor` each run, or (b) correct the docstring to "factors step toward the clamped target by at most MAX_STEP per invocation; re-running advances the factor again" and ensure the cron schedule guarantees exactly one run per data window. Given this is a real-money feedback loop, prefer (a) or add a guard that skips re-stepping when the underlying graded-row count has not changed since the last audit entry.

### WR-03: Persistent `status: "partial"` in `weekly_metrics` is invisible to the failure-streak observability

**File:** `scripts/sports_system_runner.py:7309, 7331` (sets `result["status"] = "partial"`) and `:7412, 7481, 7505` (observability only escalates on exception)
**Issue:** `weekly_metrics_task` intentionally never raises — aggregation or calibration failures set `result["status"] = "partial"` and the task still exits 0. The observability layer (`_run_status`) only flips to `error`/`timeout` on an actual exception, and the `🔁 REPEATED FAILURE` streak (`trailing_failure_streak`) is computed from those. Consequently, a calibration phase that fails *every* week (e.g., `master_pnl.xlsx` schema drift, a corrupt `calibration.json`, or a persistent read error) is recorded as `ok` with exit 0 and never triggers a repeated-failure alert. The operator — whose stated goal is to stop babysitting the automation — would get a green run while the feedback loop is silently dead. The calibration note even degrades to "*Calibration recompute failed this cycle — see run log.*", buried in Obsidian.
**Fix:** Surface persistent partial status. Minimal option: when `result["status"] == "partial"`, send a distinct low-noise Telegram/Obsidian flag (not the full failure alert) so a recurring degradation is visible. Better: record `partial` into the JSONL run-outcome sink so `trailing_failure_streak` can count consecutive partials and escalate after N, mirroring the existing OBS-03 pattern.

## Info

### IN-01: `INCEPTION_DATE = "2026-06-08"` is duplicated across three modules

**File:** `scripts/calibration.py:26`, `scripts/metrics_report.py:42`, `scripts/sports_system_runner.py:5364`
**Issue:** The inception date is a magic constant copy-pasted into three files. If the operator ever re-baselines (e.g., after the grading pipeline thaws), three independent edits are required and they can silently drift, corrupting which rows feed ROI, hit-rate, and calibration.
**Fix:** Define it once (e.g., in a small shared constants module or re-export from `slip_payouts`/`workbook_io`, which the new modules already import) and reference it, since the new modules deliberately avoid importing the runner.

### IN-02: Read-only workbooks are never closed in the aggregation loops

**File:** `scripts/metrics_report.py:132` (per-workbook loop), `:220`, `scripts/calibration.py:158`
**Issue:** `aggregate_slip_roi_by_week_sport` opens every dated per-sport workbook (`safe_load_workbook(..., read_only=True)`) inside a loop and never calls `wb.close()`. Confirmed each read-only load holds one open fd until GC. There are 33 dated workbooks today and the set grows daily across a season. On this machine the soft fd limit is 1,048,576, so there is no operational risk *here*, but it is a leak and fragile if the system is ever run where `ulimit -n` is the macOS default (256).
**Fix:** Close each read-only workbook after use:
```python
try:
    wb = safe_load_workbook(wb_path, read_only=True, data_only=True)
except Exception:
    continue
try:
    ...  # iterate Slip History
finally:
    wb.close()
```

### IN-03: Short-row length guard conflates "unreadable row" with valid rows

**File:** `scripts/metrics_report.py:142`
**Issue:** `if not row_vals or len(row_vals) < max(date_idx, stake_idx, net_pnl_idx, result_idx, recon_idx) + 1: continue` skips any row whose tuple is shorter than the recon column index. The intent (skip malformed short rows) is reasonable, but the threshold is keyed to `recon_idx` (col 21) even though `SLIP_HISTORY_HEADERS` has 23 columns — so the guard's meaning is non-obvious and depends on openpyxl padding behaviour. With openpyxl 3.1.5, read-only `iter_rows` pads to the sheet's `max_column` (23, set by the header), so valid rows are not dropped today; but a future openpyxl that trims trailing empties could silently drop legitimate slips whose last populated cell is at/before `Net PnL`.
**Fix:** Make the guard explicit and version-robust by normalizing row length first, e.g. `row_vals = tuple(row_vals) + (None,) * (len(SLIP_HISTORY_HEADERS) - len(row_vals))` (or index with a helper that returns `None` past the end), rather than dropping the whole row.

### IN-04: `model_implied` averages raw MOP across mixed OVER/UNDER selections without orientation

**File:** `scripts/calibration.py:93`
**Issue:** `model_implied = sum(mop_values) / len(mop_values)` averages the stored `Model Over Probability` for every graded PROP row regardless of whether the actual pick was an OVER or an UNDER selection. `empirical = wins/(wins+losses)` is the hit rate of the *picks*. For an UNDER pick, the model's pick-implied probability is `1 - MOP`, not `MOP`. If the prop universe mixes OVER and UNDER selections, the comparison of `model_implied` (over-oriented) against `empirical` (pick-oriented) is apples-to-oranges and biases the calibration ratio. This may be acceptable if Phase-4 scope is OVER-only props, but the code does not assert or document that assumption.
**Fix:** If both directions exist, orient each MOP to the pick: use `MOP` for OVER selections and `1 - MOP` for UNDER selections before averaging. At minimum, document the OVER-only assumption in `read_graded_outcomes_for_sport` and filter to OVER picks so the comparison is well-defined.

---

_Reviewed: 2026-06-23T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
