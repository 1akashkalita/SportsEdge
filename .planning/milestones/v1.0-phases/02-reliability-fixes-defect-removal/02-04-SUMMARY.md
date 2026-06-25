---
phase: 02-reliability-fixes-defect-removal
plan: "04"
subsystem: regression-tests
tags: [fix, test, broken-pipe, circuit-breaker, regression, D-09, D-10, WR-03, FIX-01, FIX-02]
dependency_graph:
  requires: [02-01]
  provides: [FIX-01-regression-proof, FIX-02-regression-proof, hardened-repro-harness]
  affects: [scripts/repro_broken_pipe.py, scripts/test_fix01_broken_pipe.py, scripts/test_fix02_telegram_circuit_breaker.py]
tech_stack:
  added: []
  patterns: [nonce-fence-log-isolation, importlib-module-load, subprocess-sentinel-close, unittest-mock-patch]
key_files:
  created:
    - scripts/test_fix01_broken_pipe.py
    - scripts/test_fix02_telegram_circuit_breaker.py
  modified:
    - scripts/repro_broken_pipe.py
decisions:
  - "Used nonce-fence approach for log isolation: generate uuid4().hex per run, write fence line to run_log.txt before spawning subprocess, scan only content after fence position — eliminates byte-offset race without requiring a runner log-path env var override"
  - "Reduced repro _WAIT_TIMEOUT from 240s to 120s: post-fix runner exits quickly (safe_print absorbs EPIPE, except block never fires; no Telegram retry or Obsidian fanout)"
  - "FIX-02 test uses importlib-load pattern + patch.object(requests, 'post') rather than subprocess: cleaner for circuit-breaker assertions which need direct access to runner._telegram_breaker state"
metrics:
  duration: "~10 minutes"
  completed: "2026-06-20"
  tasks_completed: 3
  files_changed: 3
---

# Phase 02 Plan 04: FIX-01/FIX-02 Regression Tests + Hardened Repro Harness Summary

One-liner: Nonce-isolated repro harness + two executable regression tests lock in the safe_print and Telegram circuit-breaker fixes with deterministic pass/fail proof.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Harden repro_broken_pipe.py (WR-03, D-09) | ac4a7f3 | scripts/repro_broken_pipe.py |
| 2 | FIX-01 regression test — pipe-close exits 0 (D-10) | f84265f | scripts/test_fix01_broken_pipe.py |
| 3 | FIX-02 regression test — circuit-breaker bounded (D-10) | cd6fca4 | scripts/test_fix02_telegram_circuit_breaker.py |

## What Was Built

### Task 1: Hardened repro_broken_pipe.py (WR-03 / D-09)

The existing repro harness used a racy byte-offset snapshot (`RUN_LOG.stat().st_size`) to scope
its log scan — a concurrent process writing to the log between the snapshot and subprocess start
would cause false signal counts. The harness also used `f.seek(before_size)` to skip earlier
content, which is the exact race described in WR-03.

**Changes made:**

1. **Nonce-fence isolation (WR-03)**: Generates `uuid.uuid4().hex` per run. Writes a fence line
   `[repro-fence] nonce=<hex>` into `run_log.txt` before spawning. After the subprocess exits,
   `count_nonce_signals()` finds the fence by text search (not byte offset) and counts signal
   lines only after it. No `f.seek()` call remains in the file.

2. **INFRA_FAILURE sentinel (-1)**: `count_nonce_signals()` returns `-1` (not `0`) when the
   log is unreadable or the fence is missing. Callers check this sentinel so a permissions error
   or cleared log is not misread as "zero broken-pipe signals" (IN-04 fix).

3. **Post-fix pass/fail inversion (D-09)**: The script now treats `returncode == 0` and
   `nonce_signals == 0` as **PASS** (exit 0, "fix confirmed"). The old pre-fix "reproduced"
   path (`returncode == 1, signals > 0`) now exits 2 as **FAIL** (regression detected).

4. **Reduced wait timeout**: `_WAIT_TIMEOUT` reduced from 240s to 120s. The post-fix runner
   exits almost immediately after `safe_print()` absorbs the EPIPE — no Telegram retry loop
   or Obsidian fanout fires in the except block.

**Log isolation approach used:** Nonce-fence (not temp-file), because the runner has no
log-path env var override and writes unconditionally to `RUN_LOG`. The nonce fence line serves
as a deterministic search anchor rather than a byte position.

**Verification result:** `python3 repro_broken_pipe.py` exits 0 with:
```
PASS: fix confirmed — runner exited 0 with no broken-pipe signals. safe_print() absorbed the pipe-close as expected. (returncode=0, nonce_signals=0)
```

### Task 2: test_fix01_broken_pipe.py (D-10 / FIX-01)

A `unittest.TestCase` that deterministically proves a completed task survives a stdout pipe-close
without a spurious TASK FAILED alert.

**Mechanism:**
- Spawns runner with `--task verify` under `-u` (unbuffered stdout) via `subprocess.Popen`
- Background reader thread closes `proc.stdout` when it detects `"verification complete"` sentinel
- The next `safe_print("JSON_RESULT=...")` at main():5593 receives EPIPE, absorbs it, runner exits 0

**Assertions (both must pass):**
- `returncode == 0`: pipe-close on completed task is not an error (pre-fix: exited 1)
- `nonce_signals == 0`: no broken-pipe log evidence for this run (pre-fix: ERROR task= / TRACEBACK)

**Pre-fix behavior (would make test FAIL):** bare `print("JSON_RESULT=...")` raised `BrokenPipeError`
into `main()`'s `except` block → called `send_telegram("TASK FAILED")` → exited 1.

**Bounded wait:** `_WAIT_TIMEOUT=90s`; stalled runner fails the test, not hangs it.

**Result:** `python3 test_fix01_broken_pipe.py` exits 0. `python3 -m pytest test_fix01_broken_pipe.py`
reports 1 passed.

### Task 3: test_fix02_telegram_circuit_breaker.py (D-10 / FIX-02)

A `unittest.TestCase` with 3 tests proving the Telegram circuit-breaker (Plan-01 D-02/D-03) is
bounded, short-circuits when tripped, and logs the suppressed-count line.

**Load pattern:** `importlib.util.spec_from_file_location` + `exec_module(runner)` — direct module
access to `runner._telegram_breaker` and `runner.send_telegram`.

**setUp:** Sets dummy `TELEGRAM_BOT_TOKEN=x` / `TELEGRAM_HOME_CHANNEL=y` (real creds never read
or transmitted — `requests.post` is mocked); resets `_telegram_breaker` to clean state.

**Tests:**
1. `test_breaker_trips_after_n_failures`: 5 `ConnectionError` calls via `patch.object(requests, "post")`
   → asserts `_telegram_breaker["tripped"] is True` and total elapsed `< 30s`. Proves the 10s timeout
   + N=3 breaker bounds the stall that previously ran for hours.
2. `test_breaker_tripped_suppresses_immediately`: pre-sets `tripped=True`, asserts `send_telegram()`
   returns `False` in `< 0.2s` — no network attempt, no sleep.
3. `test_suppressed_count_logged`: monkeypatches `runner.log` to capture lines, forces breaker trip,
   asserts at least one captured line contains `"alerts suppressed"` or `"unreachable"` (the D-03
   log line: `"Telegram circuit-breaker tripped — alerts suppressed — Telegram unreachable ..."`).

**Pre-fix behavior (would make tests FAIL):** No `_telegram_breaker` attribute → `AttributeError`
on setUp; retry loop used `timeout=30` with no breaker so N calls would take N×65s.

**Result:** `python3 test_fix02_telegram_circuit_breaker.py` exits 0, 3 tests OK. `python3 -m pytest`
reports 3 passed.

## Deviations from Plan

None. Plan executed exactly as written.

## Known Stubs

None. All test assertions are wired to real runner behavior, not placeholders.

## Threat Flags

No new network endpoints, auth paths, file access patterns, or schema changes introduced.
All network calls in tests are mocked. Threat mitigations applied:

| Applied | File | Description |
|---------|------|-------------|
| T-02-09 mitigated | test_fix02_telegram_circuit_breaker.py | Dummy TOKEN/CHANNEL env vars; real creds never read (requests.post mocked) |
| T-02-10 mitigated | repro_broken_pipe.py | Nonce scan surfaces only matched fence section; no arbitrary log contents leaked |
| T-02-11 mitigated | repro_broken_pipe.py | Nonce-fence approach; harness no longer writes synthetic failure evidence into shared log |

## Self-Check: PASSED

Files created/modified:
- scripts/repro_broken_pipe.py: FOUND
- scripts/test_fix01_broken_pipe.py: FOUND
- scripts/test_fix02_telegram_circuit_breaker.py: FOUND

Commits:
- ac4a7f3: FOUND (fix(02-04): harden repro_broken_pipe.py)
- f84265f: FOUND (test(02-04): add FIX-01 regression test)
- cd6fca4: FOUND (test(02-04): add FIX-02 regression test)
