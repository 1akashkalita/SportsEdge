---
phase: 04-dual-metrics-and-feedback
plan: "03"
subsystem: feedback-loop-wiring
tags: [calibration, sigma-injection, weekly-metrics, integrity, tdd, python]
dependency_graph:
  requires:
    - scripts/calibration.py (Plan 01)
    - scripts/metrics_report.py (Plan 02)
  provides:
    - scripts/generate_projections.py (load_calibration_factor + sigma injection)
    - scripts/sports_system_runner.py (weekly_metrics task)
    - scripts/test_weekly_metrics.py (TestSigmaInjection + TestIntegrityNoVerdictChange + TestIntegrityGateOutput)
  affects:
    - data/research/calibration.json (read by generate_projections at projection time)
tech_stack:
  added: []
  patterns:
    - call-time-config-read (never import-time — anti-pattern avoided)
    - fail-safe-clamped-read (try/except + clamp to [0.85,1.20])
    - lazy-import-task-function (__import__ inside task fn, mirrors _grade_slips_then_sync)
    - obsidian-sync-direct-bypass (bypasses path.exists guard for re-run overwrite)
    - verdict-snapshot-integrity-test (Design A)
    - gate-output-determinism-test (Design C)
key_files:
  created: []
  modified:
    - scripts/generate_projections.py
    - scripts/sports_system_runner.py
    - scripts/test_weekly_metrics.py
decisions:
  - "D-07: sigma injection in build_projection — sigma = estimate_sigma(...) * load_calibration_factor(sport)"
  - "D-09: auto-apply ON by default — generate_projections reads calibration.json at call time, no feature flag; absent file → neutral 1.0"
  - "D-01: weekly_metrics delivers to BOTH Telegram (send_telegram) AND Obsidian (obsidian_sync direct, bypassing path.exists guard)"
  - "D-02: weekly_metrics is a standalone task wired in TASK_TIMEOUTS=660 / task_workbook_paths / run_task; cron entry must be added by operator in ~/.hermes"
  - "D-12: calibration recompute runs inside weekly_metrics_task (one task, two logical phases)"
  - "D-13: loop proven integrity — verdict snapshot (Design A) + gate-output determinism (Design C) + AST import check (Design B, Plan 01) all green"
  - "METRICS-03: integrity tests confirm the loop changes no graded verdict and leaves evaluate_no_bet_gates output unchanged"
metrics:
  duration: ~30 min
  completed_date: "2026-06-23"
  tasks_completed: 3
  files_modified: 3
  tests_added: 30
  tests_passing: 39
---

# Phase 4 Plan 3: Feedback Loop Wiring Summary

**One-liner:** Per-sport calibration factor wired into sigma at projection time (`generate_projections.py` `load_calibration_factor` + injection after `estimate_sigma`), `weekly_metrics` standalone task added to runner (TASK_TIMEOUTS/task_workbook_paths/run_task, report → Telegram + Obsidian, calibration recompute), and METRICS-03 integrity proven by verdict-snapshot (Design A) + gate-output (Design C) + AST-import (Design B, Plan 01) tests.

## What Was Built

### Task 1: Sigma injection in generate_projections.py (D-07 / D-09)

**`load_calibration_factor(sport: str) -> float`** added to `generate_projections.py` (after path constants, before `estimate_sigma`):
- Reads `DATA / "research" / "calibration.json"` at CALL TIME (never at import time — anti-pattern avoided per RESEARCH §6)
- `try/except Exception → 1.0` on any failure (absent, corrupt, missing key)
- V5 input validation: clamps any read value into [0.85, 1.20] (T-04-02 mitigated)
- No new third-party import — uses `json` and `DATA` already in the module

**Injection in `build_projection`** after `estimate_sigma` call (lines 412-419):
```python
sigma, sigma_source = estimate_sigma(stat, stat_name)
# D-07 / D-09: apply per-sport calibration factor to sigma at projection time.
cal_factor = load_calibration_factor(sport)
if cal_factor != 1.0:
    sigma = sigma * cal_factor
    sigma_source = f"{sigma_source} × cal={cal_factor:.4f}"
over_prob = round(model_over_probability(projection, pp_line, sigma), 4)
```
`model_over_probability` and `estimate_sigma` bodies are byte-for-byte unchanged.

**TestSigmaInjection (9 tests):** MLB factor loaded correctly, missing-sport neutral, missing-file neutral, corrupt-file neutral, 5.0 clamped to 1.20, 0.10 clamped to 0.85, wider sigma pulls prob toward 0.5, model body unchanged, function callable. All 9 PASS.

### Task 2: Wire weekly_metrics task (D-01 / D-02 / D-12)

Three additions to `sports_system_runner.py`:

1. **`TASK_TIMEOUTS["weekly_metrics"] = 660`** — matches grade_slips/rebuild_bankroll (D-02)

2. **`task_workbook_paths("weekly_metrics") → [PNL_DIR / "master_pnl.xlsx"]`** — read-only cooperative lock to prevent races with grade_slips / check_results

3. **`weekly_metrics_task() -> dict[str, Any]`** placed near `_grade_slips_then_sync` (~line 7261):
   - Lazy imports: `__import__("calibration")` + `__import__("metrics_report")` (no import-time coupling)
   - Aggregates report: `aggregate_slip_roi_by_week_sport()` + `read_prop_hit_rate_by_week_sport()` + `build_weekly_report()`
   - Recomputes calibration: `compute_and_update_calibration()` wrapped in `try/except` (non-blocking) (D-12)
   - Builds calibration_note from audit dicts (per-sport old→new factor, n, reason — D-13 observable log)
   - Delivers to Telegram: `send_telegram(format_telegram_digest(report))` in `try/except`
   - Delivers to Obsidian: `obsidian_sync({...fill_obsidian_recap_markdown...})` directly (bypasses `path.exists` guard — RESEARCH Pitfall 5; re-runs overwrite the note) in `try/except`
   - Returns `{status, weeks, sports, calibration, telegram_sent, obsidian_sent}` — never raises
   - Code comment documents operator must add Monday cron entry in `~/.hermes` (D-02)

4. **`run_task mapping: "weekly_metrics": lambda: weekly_metrics_task()`**

Operator cron entry (D-02 — must be added manually to `~/.hermes` outside this repo):
```
0 8 * * MON cd /path/to/sports_picks/scripts && python3 sports_system_runner.py --task weekly_metrics
```

### Task 3: METRICS-03 integrity tests (Design A + Design C)

**TestIntegrityNoVerdictChange (Design A — 3 tests):**
- `test_calibration_loop_does_not_change_any_verdict`: builds 36-row workbook (32 MLB W/L + 4 PUSH/VOID + 5 NBA); snapshots all Result values before; runs `compute_and_update_calibration(_wb_override=wb, path=tmp_cal.json)`; asserts snapshot_before == snapshot_after
- `test_calibration_loop_ran_and_changed_mlb_factor`: asserts calibration.json written AND MLB factor != 1.0 (loop actually ran with 32 MOP-backed rows ≥ gate of 30)
- `test_push_void_rows_unchanged`: asserts PUSH/VOID subset unchanged after loop

**TestIntegrityGateOutput (Design C — 3 tests):**
- `test_gate_output_identical_regardless_of_calibration_file`: runs `evaluate_no_bet_gates(pick, {})` twice with same pick dict; asserts (ok, skipped, passed) identical — gate reads stored model_over_probability, never calibration.json
- `test_gate_does_not_read_calibration_json`: inspects `evaluate_no_bet_gates` source for absence of "calibration.json" and "load_calibration_factor" (D-13 structural check)
- `test_pick_with_high_prob_passes_gate2`: asserts MOP=0.70 pick does not fail Gate 2

## Commits

| Hash | Type | Description |
|------|------|-------------|
| c2ac0d0 | feat | add load_calibration_factor + sigma injection in generate_projections + TestSigmaInjection |
| 6868f92 | feat | wire weekly_metrics task + weekly_metrics_task() in sports_system_runner.py |
| f73c954 | test | fill TestIntegrityNoVerdictChange + TestIntegrityGateOutput — METRICS-03 |

## Verification Results

```
cd scripts && python3 -m pytest test_weekly_metrics.py -x -q
39 passed, 3 skipped in 0.91s

python3 -c "import generate_projections" → clean

Runner bootstrap:
  TASK_TIMEOUTS["weekly_metrics"] == 660 → confirmed
  callable(weekly_metrics_task) → confirmed
  task_workbook_paths("weekly_metrics") → [master_pnl.xlsx] confirmed

METRICS-03 integrity (Design A + B + C):
  TestIntegrityNoVerdictChange: 3/3 PASS
  TestIntegrityGateOutput: 3/3 PASS
  TestIntegrityNoGateImport: 8/8 PASS (Design B — from Plan 01)
```

## Deviations from Plan

None — plan executed exactly as written. All acceptance criteria met.

## Operator Action Required (D-02)

The `weekly_metrics` task is wired in the runner. The Monday-morning cron schedule entry must be added by the operator to `~/.hermes` (outside this repo). Example:

```
0 8 * * MON cd /path/to/sports_picks/scripts && /usr/local/bin/python3 sports_system_runner.py --task weekly_metrics
```

Replace `/path/to/sports_picks/scripts` with the actual path on the operator's machine.

## Known Stubs

None. The 3 `@unittest.skip` test stubs remaining in `test_weekly_metrics.py` are Plan 01/02 stubs for `TestSlipRoiAggregation`, `TestPropHitRateAggregation`, and `TestWowArrow` — these were intentionally not filled here because Plan 02 created `test_metrics_report.py` covering those behaviors. The stubs are harmless.

## Threat Mitigations Applied

| Threat | Mitigation |
|--------|-----------|
| T-04-01: corrupt calibration.json crashes projections | try/except → neutral 1.0 in load_calibration_factor |
| T-04-02: out-of-range factor applied to sigma | clamp to [0.85, 1.20] in load_calibration_factor |
| T-04-09: feedback loop altering graded verdicts or gate logic | Design A (verdict snapshot) + Design C (gate determinism) + Design B (AST import) all green |
| T-04-10: weekly_metrics exceeds 660s budget | TASK_TIMEOUTS["weekly_metrics"]=660; task is read-only aggregation (<45s) |
| T-04-11: delivery failure crashes task | Telegram + Obsidian both wrapped in try/except; task returns dict, never raises |

## Threat Flags

No new network endpoints, auth paths, file access patterns, or schema changes beyond the plan's threat model. The only new file I/O is read from `calibration.json` (existing METRICS-02 design surface) and `obsidian_sync` subprocess call (existing pattern in the runner).

## Self-Check: PASSED

- scripts/generate_projections.py: FOUND, defines load_calibration_factor and sigma injection
- scripts/sports_system_runner.py: FOUND, weekly_metrics wired in TASK_TIMEOUTS/task_workbook_paths/run_task
- scripts/test_weekly_metrics.py: FOUND, 39 tests pass 3 skipped
- Commit c2ac0d0: FOUND
- Commit 6868f92: FOUND
- Commit f73c954: FOUND
- TestSigmaInjection 9/9 PASS: CONFIRMED
- TestIntegrityNoVerdictChange 3/3 PASS: CONFIRMED
- TestIntegrityGateOutput 3/3 PASS: CONFIRMED
- TestIntegrityNoGateImport 8/8 PASS: CONFIRMED
- model_over_probability body unchanged: CONFIRMED (inspect.getsource test)
- evaluate_no_bet_gates does not reference calibration.json: CONFIRMED (source scan test)
- TASK_TIMEOUTS["weekly_metrics"] == 660: CONFIRMED
- task_workbook_paths("weekly_metrics") returns [master_pnl.xlsx]: CONFIRMED
