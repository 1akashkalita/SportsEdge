---
phase: 03-resilience
plan: "01"
subsystem: orchestrator
tags: [resilience, subprocess-retry, timeout, broken-pipe, sigalrm]
dependency_graph:
  requires: []
  provides: [RES-01, RES-02, RES-03]
  affects: [scripts/sports_system_runner.py]
tech_stack:
  added: [signal (stdlib — import signal added to runner)]
  patterns:
    - _subprocess_run_with_retry: Popen-based retry helper with 1 re-run on hard failure
    - TASK_TIMEOUTS: per-task wall-clock budget dict (all values < 120s)
    - TaskTimeoutError: custom exception raised by SIGALRM handler
    - _sigalrm_handler: kills in-flight subprocess then raises TaskTimeoutError
    - _task_result sentinel: distinguishes post-completion BrokenPipeError from real failures
key_files:
  modified:
    - scripts/sports_system_runner.py
decisions:
  - RES-01 uses subprocess.Popen (not subprocess.run) so _sigalrm_handler can kill the in-flight child via _current_subprocess
  - Retry loop does NOT catch TaskTimeoutError — SIGALRM always wins over the retry
  - Exit-0 results (including empty board) are never retried per D-02
  - _task_result is a local variable set OUTSIDE the with task_workbook_locks block so run_task() exceptions leave it None
  - except TaskTimeoutError placed BEFORE except Exception per Pitfall 6
  - signal.alarm(0) is the first statement in finally — unconditional cancel per Pitfall 2/3
  - No OS-level SIGPIPE handler added (D-09)
  - stdout/stderr buffering: Popen with capture_output=True buffers in Popen.stdout/stderr pipes; read() called after proc.wait(); text kwarg handled by decoding if needed
metrics:
  duration_seconds: 259
  completed_date: "2026-06-21"
  tasks_completed: 3
  files_modified: 1
---

# Phase 3 Plan 01: RES-01 + RES-02 + RES-03 Resilience Hardening Summary

**One-liner:** SIGALRM per-task timeout (budgets 60-90s), subprocess retry-on-hard-failure, and BrokenPipeError reclassification added to sports_system_runner.py main() with zero gate-logic or schema changes.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | RES-01 subprocess retry helper + 3 stage call sites | 14defe0 | scripts/sports_system_runner.py |
| 2 | RES-02 _task_result sentinel + BrokenPipeError reclassification | 6e6c177 | scripts/sports_system_runner.py |
| 3 | RES-03 SIGALRM timeout + TASK_TIMEOUTS + orphan-killing handler | 6e6c177 | scripts/sports_system_runner.py |

Note: Tasks 2 and 3 were committed together (both touch the same main() try/except/finally region per plan instructions — "do both in sequence within this plan; do not leave main() half-patched between tasks").

## What Was Built

### RES-01: Subprocess Retry Helper

Added `_subprocess_run_with_retry(cmd, *, timeout, backoff=5, context, **kwargs)` as a module-private helper. Key properties:

- Uses `subprocess.Popen` (not `subprocess.run`) so the live child is tracked in `_current_subprocess` and can be killed by `_sigalrm_handler` on timeout
- Sets `_current_subprocess = proc` before `proc.wait(timeout=timeout)`, clears it in `finally`
- Retries exactly once (D-03) on: non-zero exit code OR `subprocess.TimeoutExpired`
- Exit 0 (including empty board) returns immediately — never retried (D-02)
- `TaskTimeoutError` from SIGALRM is NOT caught — unwinds past retry loop so alarm wins
- Returns `subprocess.CompletedProcess` with same `.returncode`/`.stdout`/`.stderr` fields callers expect
- Text mode handling: decodes bytes if text kwarg is set

All three call sites routed through the helper:
- `run_fetch_dfs_props` (timeout=300, context=`fetch_dfs_props {sport}`)
- `run_build_hit_rate_db` (timeout=600, context=`hit-rate build {sport}`)
- `run_generate_projections` (timeout=600, context=`projection generation {sport}`)

### RES-02: BrokenPipeError Reclassification

Added `_task_result: dict[str, Any] | None = None` as a local before the `try` in `main()`. After the `with task_workbook_locks` block exits (not inside it), `_task_result = result` is set.

In `except Exception as e:`: if `_task_result is not None and isinstance(e, BrokenPipeError)`, logs `WARNING: BrokenPipeError after task completion — cron pipe closed; task data persisted` and returns 0. All other exceptions (including BrokenPipeError during run_task) still fire `❌ SPORTS TASK FAILED` and return 1.

### RES-03: SIGALRM Per-Task Timeout

Added:
- `TASK_TIMEOUTS: dict[str, int]` — 11 task budgets, all ≤ 90s (< 120s Hermes hard-kill window)
- `TaskTimeoutError(Exception)` — custom exception class raised by the handler
- `_sigalrm_handler(signum, frame)` — kills `_current_subprocess` if active, then raises `TaskTimeoutError`

In `main()`:
- `budget = TASK_TIMEOUTS.get(args.task, 60)` computed before try/locks
- `old_handler = signal.signal(signal.SIGALRM, _sigalrm_handler)` + `signal.alarm(budget)` armed BEFORE `with LOCK_FILE.open(...)` (Pitfall 2 — also catches hangs during lock acquisition)
- `except TaskTimeoutError` placed BEFORE `except Exception` (Pitfall 6)
- On timeout: logs `TIMEOUT task=...`, sends `⏱ TASK TIMED OUT: {task}\nBudget: {budget}s exceeded`, emits JSON_RESULT with status=timeout, returns 1
- `finally`: `signal.alarm(0)` + `signal.signal(signal.SIGALRM, old_handler)` as FIRST two statements (always cancel, Pitfall 2/3)

## Verification Results

All automated checks from the plan passed:

```
RES-01 symbols OK
RES-01 wired into all 3 stages (>=4 refs: 1 def + 3 calls)
import OK
RES-03 OK {'nba_daily_picks': 90, 'mlb_daily_picks': 90, ...all <= 90...}
```

Regression suite:
```
test_fix01_broken_pipe.py::TestFix01BrokenPipe::test_no_spurious_task_failed_after_pipe_close PASSED
test_fix02_telegram_circuit_breaker.py — 3 PASSED
test_def01_no_duplicate_defs.py — 5 PASSED
test_def02_path_resolution.py — 5 PASSED
14 passed in 57.03s
```

Additional spot checks:
- `grep -c 'SIGPIPE' sports_system_runner.py` → 0 (D-09 confirmed)
- `grep -c 'def evaluate_no_bet_gates' sports_system_runner.py` → 1 (gate logic unchanged)
- `grep -c 'JSON_RESULT=' sports_system_runner.py` → 4 (all print sites preserved)
- All TASK_TIMEOUTS values < 120 and ≤ 90
- `except TaskTimeoutError` at line 5688 BEFORE `except Exception` at line 5696

## Deviations from Plan

### Auto-adjustments (no deviation protocol required)

**1. Tasks 2 and 3 committed together** — the plan explicitly states "This task edits the SAME main() region as Task 3 — do both in sequence within this plan; do not leave main() half-patched between tasks." Both changes are in a single coherent edit of main()'s try/except/finally. Committed as a single "feat(03-01): RES-02 + RES-03" commit rather than two separate commits to avoid a half-patched intermediate state.

**2. `import signal` added in Task 1 commit** — the plan assigns adding `import signal` to Task 3's read_first, but since TASK_TIMEOUTS, TaskTimeoutError, _sigalrm_handler, and _current_subprocess needed to be added as module-level state (referenced by the Task 1 helper body via `_current_subprocess`), all module-level additions were grouped in Task 1's commit. This is the natural grouping — `_current_subprocess` is used by both the Task 1 helper and the Task 3 handler.

**3. Text-mode stdout/stderr handling in `_subprocess_run_with_retry`** — the plan's pattern template (PATTERNS.md lines 376-378) reads `proc.stdout.read()` returning bytes, but the callers use `text=True` + `capture_output=True` which means Popen opens stdout/stderr in text mode and `read()` returns str. Added a guard: `if kwargs.get("text"): stdout = stdout if isinstance(stdout, str) else stdout.decode(...)` to handle both modes cleanly. This is a Rule 2 (missing null/type handling) auto-fix.

## Known Stubs

None. All new functionality is fully wired. The retry helper, timeout machinery, and reclassification guard are all live in the production code path.

## Threat Surface Scan

No new trust boundaries introduced. The changes are confined to:
- A module-private helper that wraps existing subprocess invocations
- The existing `main()` try/except/finally block

Threat mitigations T-03-01 through T-03-05 from the plan's threat model are implemented as designed:
- T-03-01 (retry amplification): bounded by 1 re-run + 5s backoff + task budget
- T-03-02 (orphaned subprocess): `_sigalrm_handler` kills + waits before raising
- T-03-03 (suppressing genuine failures): `_task_result` set only after run_task() returns successfully, outside the locks block
- T-03-05 (stale .lock/.tmp): SIGALRM raises through `with` blocks (their `__exit__` releases); `safe_save_workbook` finally unlinks orphaned .tmp

## Self-Check: PASSED

- `scripts/sports_system_runner.py` exists and imports clean
- Commit 14defe0 exists (RES-01)
- Commit 6e6c177 exists (RES-02 + RES-03)
- All acceptance criteria verified via grep and python3 -c assertions above
