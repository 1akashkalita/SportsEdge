---
phase: 03-resilience
plan: "02"
subsystem: tests
tags: [resilience, subprocess-retry, timeout, sigalrm, regression-test, fault-injection]
dependency_graph:
  requires: [03-01]
  provides: [RES-01-test, RES-03-test, RES-04]
  affects: [scripts/test_res01_subprocess_retry.py, scripts/test_res03_task_timeout.py]
tech_stack:
  added: []
  patterns:
    - importlib-runner-load: load runner via importlib.util for in-process monkeypatching
    - fake-popen-call-count: _FakePopen stub with .wait()/.returncode/.stdout/.stderr/.kill()
    - subprocess-shim-isolation: generated temp child shim avoids in-process SIGALRM bleed
    - nonce-fence-log-scan: uuid fence in run_log.txt isolates post-fence signal counts
key_files:
  created:
    - scripts/test_res01_subprocess_retry.py
    - scripts/test_res03_task_timeout.py
decisions:
  - RES-01 patch target is subprocess.Popen (not subprocess.run) — the helper constructs Popen
  - RES-03 tested via generated child shim (Pitfall 3 — SIGALRM is process-wide)
  - Healthy shim uses default 60s verify budget (not 3s) because verify does workbook I/O (~7s)
  - Timeout assertions check for "TIMEOUT task=" log prefix and JSON "status":"timeout" since Telegram payload is not captured in subprocess stdout
metrics:
  duration_seconds: 900
  completed_date: "2026-06-21"
  tasks_completed: 2
  files_modified: 2
---

# Phase 3 Plan 02: RES-01 + RES-03 Regression Tests Summary

**One-liner:** Fault-injection regression tests for subprocess-retry (Popen patch + call-count) and SIGALRM timeout (generated child shim) proving both behaviors are green against the Plan-01 runner and would fail against pre-fix code.

## Tasks Completed

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | test_res01_subprocess_retry.py — RES-01 fault injection | a8fce60 | scripts/test_res01_subprocess_retry.py |
| 2 | test_res03_task_timeout.py — RES-03 subprocess-isolated shim | 8d32e41 | scripts/test_res03_task_timeout.py |

## What Was Built

### RES-01 Test: `test_res01_subprocess_retry.py`

Plain `unittest.TestCase` (`class TestRes01SubprocessRetry`). Loads the runner via `importlib` and patches `subprocess.Popen` (the symbol `_subprocess_run_with_retry` constructs — NOT `subprocess.run`) using a `_FakePopen` stub that exposes exactly what the helper reads: `.wait(timeout=...)`, `.returncode`, `.stdout`/`.stderr` (both `io.StringIO("")` for text-mode), and `.kill()`. Patches `time.sleep` in `setUp` so the 5-second backoff does not stall the suite.

Three test methods:

1. **`test_subprocess_retry_on_nonzero_exit`** — first Popen exits 1, second exits 0; asserts `call_count == 2`. FAILS pre-Plan-01 (helper does not exist; `subprocess.run` is called instead; Popen patch records 0 constructions).
2. **`test_no_retry_on_clean_exit`** — every Popen exits 0; asserts `call_count == 1` (D-02: empty board is not retried).
3. **`test_after_one_retry_fails_propagates`** — both Popen calls exit 1; asserts `assertRaises(Exception)` (stage raises after exhausting re-run).

Total runtime: < 2 seconds.

### RES-03 Test: `test_res03_task_timeout.py`

Plain `unittest.TestCase` (`class TestRes03TaskTimeout`). Uses the subprocess-shim pattern (Pitfall 3: SIGALRM is process-wide and cannot be tested in-process). The test writes a tiny temp `.py` shim to `tempfile.mkstemp()`, registers cleanup via `addCleanup`, and spawns it via `subprocess.Popen([sys.executable, shim_path, "--task", "verify"])`.

Two shim variants:

- **Hang shim** (`_write_hang_shim`): rebinds `r.verify = lambda: time.sleep(9999)` and sets `r.TASK_TIMEOUTS["verify"] = 3`. Since `run_task` builds its dispatch mapping at call-time (`mapping = {"verify": verify}`) and `verify` is looked up from the module namespace, the rebind takes effect. `main()` arms `signal.alarm(3)` → SIGALRM fires at 3s → `_sigalrm_handler` raises `TaskTimeoutError` → `main()` logs `TIMEOUT task=verify` and returns 1.
- **Healthy shim** (`_write_healthy_shim`): uses real `verify` with the default 60s budget (workbook I/O takes ~7s — a 3s budget would cause a spurious timeout).

`_WAIT_TIMEOUT = _SHIM_BUDGET + 30 = 33s`. Total runtime: ~30s (dominated by the healthy task's real verify run).

Two test methods:

1. **`test_timeout_fires_on_hung_task`** — spawns hang shim; asserts: proc exits within `_WAIT_TIMEOUT`, `returncode == 1`, `"TIMEOUT task="` or `'"status": "timeout"'` in combined stdout/stderr, `"TASK FAILED"` absent. FAILS pre-Plan-01 (no `signal.alarm()` → child hangs → `proc.wait(timeout=33)` raises `TimeoutExpired` → `self.fail()`).
2. **`test_healthy_task_cancels_alarm`** — spawns healthy shim; asserts exit 0, no timeout signal, no `TASK FAILED`.

## Verification Results

```
test_res01_subprocess_retry.py::TestRes01SubprocessRetry::test_after_one_retry_fails_propagates PASSED
test_res01_subprocess_retry.py::TestRes01SubprocessRetry::test_no_retry_on_clean_exit PASSED
test_res01_subprocess_retry.py::TestRes01SubprocessRetry::test_subprocess_retry_on_nonzero_exit PASSED
test_res03_task_timeout.py::TestRes03TaskTimeout::test_healthy_task_cancels_alarm PASSED
test_res03_task_timeout.py::TestRes03TaskTimeout::test_timeout_fires_on_hung_task PASSED
5 passed in 30.42s
```

No new baseline failures introduced (pre-existing baseline: "2 failed, 202 passed").

## D-11 Fail-Before/Pass-After Confirmation

**RES-01:** Confirmed red against pre-Plan-01 code by construction — `_subprocess_run_with_retry` does not exist in the pre-fix runner. `run_fetch_dfs_props` calls `subprocess.run` directly, so patching `subprocess.Popen` records 0 constructions. `test_subprocess_retry_on_nonzero_exit` expects `call_count == 2` → assertion fails → test is RED.

**RES-03:** Confirmed red against pre-Plan-01 code by construction — no `TASK_TIMEOUTS` dict and no `signal.alarm()` call exist. The hang shim's `time.sleep(9999)` never completes. `proc.wait(timeout=33)` raises `subprocess.TimeoutExpired`. The test catches it, calls `self.fail()` → test is RED.

## Deviations from Plan

### Auto-adjusted (Rule 1 — behavior correction)

**1. Healthy shim uses default 60s verify budget, not 3s** — the plan states "real verify finishes well under 3s" but the actual `verify` function does workbook I/O (ensure_workbook + safe_load_workbook for NBA + MLB) which takes ~7s. Using `_SHIM_BUDGET = 3` for the healthy shim caused a spurious SIGALRM on first iteration. Fixed by leaving the healthy shim at the default 60s budget. The hang shim still uses `_SHIM_BUDGET = 3` for fast test execution. The `_WAIT_TIMEOUT = _SHIM_BUDGET + 30 = 33s` specification is preserved as the harness wait limit.

**2. Timeout detection asserts `"TIMEOUT task="` (log prefix) and `'"status": "timeout"'` (JSON stdout), not `"TIMED OUT"` (Telegram payload)** — the runner's `log()` call writes `"TIMEOUT task=verify"` to stdout and run_log.txt. The Telegram message `"⏱ TASK TIMED OUT"` is sent to Telegram and is not visible in subprocess stdout/stderr. The test asserts on what IS observable (the log prefix and JSON status) rather than the Telegram payload. The plan's acceptance criteria says "post-fence output contains TIMED OUT" — this was inaccurate because `log()` output is what appears in stdout, not the Telegram string. Adjusted to match the actual runner output.

## Known Stubs

None. Both test files are fully implemented and green.

## Threat Surface Scan

No new trust boundaries introduced. The tests:
- Read `run_log.txt` with a nonce fence (T-03-T1 mitigated: only post-fence content scanned; no fake ERROR/TASK FAILED markers written)
- Use `self.skipTest()` for infra failures (T-03-T2 mitigated: fence-write and shim-write failures produce SKIP, not false RED)
- Clean up temp shims via `addCleanup` and kill orphaned child processes in `TimeoutExpired` branch (T-03-T3 mitigated)

## Self-Check: PASSED

- `scripts/test_res01_subprocess_retry.py` exists: FOUND
- `scripts/test_res03_task_timeout.py` exists: FOUND
- Commit a8fce60 exists (RES-01 test): FOUND
- Commit 8d32e41 exists (RES-03 test): FOUND
- Both tests pass: 5 passed in 30.42s
