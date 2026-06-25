---
phase: 02-reliability-fixes-defect-removal
plan: "05"
subsystem: ops-harness
tags: [fix-03, d-08, run-all, ci-seed, harness, live-run]
dependency_graph:
  requires: [02-01, 02-02]
  provides: [FIX-03-proof, CI-01-seed, CI-02-seed]
  affects: [scripts/run_all_tasks.py]
tech_stack:
  added: []
  patterns: [subprocess.Popen, Path(__file__).resolve(), per-task-timeout, JSON_RESULT-assertion]
key_files:
  created:
    - scripts/run_all_tasks.py
  modified: []
decisions:
  - "SKIP (exit 0 + JSON_RESULT) counts as PASS — matches documented runner contract"
  - "Per-task timeout set to 600s matching runner's max subprocess budget; harness self-bounds without external timeout binary"
  - "gtimeout not available on this macOS; ran directly without outer timeout since harness has internal 600s per-task limit"
metrics:
  duration_minutes: 25
  completed_date: "2026-06-20"
  tasks_completed: 1
  files_created: 1
---

# Phase 02 Plan 05: FIX-03 Run-All Harness Summary

**One-liner:** FIX-03 clean-pass harness invoking all 11 runner tasks sequentially via subprocess with per-task timeout and JSON_RESULT assertion — live run confirmed all 11 passed.

## What Was Built

Created `scripts/run_all_tasks.py`, the D-08 FIX-03 clean-pass harness. It:

- Defines `ALL_TASKS` as the exact 11 task names from `run_task()`'s mapping in `sports_system_runner.py`
- Spawns each task via `subprocess.Popen([sys.executable, "-u", str(RUNNER), "--task", task], stdout=PIPE, stderr=PIPE, cwd=SCRIPTS_DIR)`
- Enforces a 600s per-task timeout (matches runner's max subprocess budget); on `TimeoutExpired`, kills and records FAIL
- Pass criterion: `returncode == 0` AND `"JSON_RESULT=" in stdout`; a defensive SKIP (exit 0 + JSON_RESULT) counts as PASS per the documented runner contract
- On failure, prints stderr excerpt (truncated to 300 chars, no env/secret echo)
- Exits 0 if all pass, 1 if any fail
- Uses only portable paths via `Path(__file__).resolve().parent`; no hardcoded absolute paths
- Documents the non-trading-window operational requirement in the module docstring

## Live Run Results (FIX-03 Proof)

Run executed: 2026-06-20T22:06:09Z — 2026-06-20T22:29:58Z (approx 24 minutes)

| Task | Status | Notes |
|------|--------|-------|
| nba_daily_picks | OK | NBA offseason — defensive SKIP in JSON_RESULT, exit 0 |
| mlb_daily_picks | OK | MLB in-season live fetch + workbook write |
| nba_prop_monitor | OK | Fast SKIP (NBA offseason) |
| mlb_prop_monitor | OK | Live API fetch, completed successfully |
| nba_injury_monitor | OK | SKIP (NBA offseason) |
| mlb_injury_monitor | OK | Live ESPN + API fetch |
| nba_clv_tracker | OK | SKIP (NBA offseason) |
| mlb_clv_tracker | OK | Live Odds-API.io fetch |
| game_completion_monitor | OK | Completed |
| check_results | OK | Live ESPN gamelog check (longest task, ~10 min) |
| verify | OK | System verification |

Final output: `All 11 tasks passed.`
Harness exit code: 0

**FIX-03 success criterion 3 is satisfied:** all 11 runner tasks complete a clean end-to-end invocation without uncaught exceptions.

## Static Verification

```
python3 -c "import run_all_tasks as m; assert len(m.ALL_TASKS)==11; assert set(m.ALL_TASKS)=={...}; print('OK 11 tasks')"
OK 11 tasks
OK no hardcoded paths
```

## Decisions Made

- **SKIP counts as PASS:** The runner contract documents that missing games/workbooks become explicit SKIP states (status SKIP in JSON_RESULT, exit 0), not exceptions. The harness treats exit-0-with-JSON_RESULT as PASS regardless of the status field. This is the correct behavior per the architecture.
- **No external timeout binary:** `timeout` and `gtimeout` are not available on this macOS. The harness's internal 600s per-task `subprocess.communicate(timeout=...)` self-bounds the worst case (11 x 600s = 110 min). No external wrapper is needed.
- **Phase-5 CI seed:** This script is designed to be reused as CI-01/CI-02 in Phase 5 with minimal adaptation (add pytest wrapper or invoke from CI shell script).

## Deviations from Plan

None — plan executed exactly as written. The `timeout 3600 python3 run_all_tasks.py` outer wrapper in the plan's verify step was adapted to run directly (`python3 run_all_tasks.py`) since neither `timeout` nor `gtimeout` is installed on this macOS, as directed by the `ENVIRONMENT GOTCHA` constraint. Internal per-task timeout (600s) was already present in the harness.

## Known Stubs

None.

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes introduced. The harness only re-runs existing tasks via the same subprocess pattern cron uses.

## Self-Check: PASSED

- `scripts/run_all_tasks.py` exists: FOUND
- Commit c0a47f8 exists: FOUND
- Live run exit 0 with "All 11 tasks passed.": CONFIRMED
- No hardcoded `/Users` path in script: CONFIRMED (`grep -c 'Path("/Users' scripts/run_all_tasks.py` returns 0)
- ALL_TASKS length == 11: CONFIRMED (static import check passed)
