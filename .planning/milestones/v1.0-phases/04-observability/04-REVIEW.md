---
phase: 04-observability
reviewed: 2026-06-21T09:00:00Z
depth: standard
files_reviewed: 5
files_reviewed_list:
  - scripts/health_check.py
  - scripts/sports_system_runner.py
  - scripts/test_health_check.py
  - scripts/test_repeated_failure_streak.py
  - scripts/test_run_log_jsonl.py
findings:
  critical: 0
  warning: 5
  info: 4
  total: 9
status: issues_found
---

# Phase 4: Code Review Report

**Reviewed:** 2026-06-21T09:00:00Z
**Depth:** standard
**Files Reviewed:** 5
**Status:** issues_found

## Summary

Phase 04 adds three observability features to the Hermes cron system: OBS-01 (a structured JSONL run-log emitted from `main()`'s `finally` block), OBS-02 (a standalone read-only `health_check.py`), and OBS-03 (a 🔁 REPEATED FAILURE Telegram alert driven by a trailing-failure-streak helper). The core defensive posture is sound: `append_run_record`, `trailing_failure_streak`, the OBS-01 finally block, and `send_telegram` are all wrapped so observability code cannot crash a task; `health_check.py` takes no fcntl lock and reads the JSONL read-only with corrupt-line skipping; the `JSON_RESULT={...}` stdout contract is untouched; cadence keys are currently aligned with `TASK_TIMEOUTS`; and all 55 new tests pass.

No BLOCKER-class defects were found — nothing here causes incorrect betting behavior, crashes a cron task, or leaks a secret with certainty. However, there are real defects worth fixing before this ships: an explicit phase constraint (truncate error strings / no traceback) is not honored on the write path or in the Telegram alerts; a security test asserts nothing; a regression test pollutes the real production log and lock; the JSONL log grows unbounded with no rotation; and the recorded `status` ignores task-level result status. Details below.

## Warnings

### WR-01: Untruncated `str(e)` written to JSONL and Telegram — violates the "truncate error strings, no traceback/tokens" phase constraint

**File:** `scripts/sports_system_runner.py:5807`, `5813-5814`, `5819`, `5840-5847`
**Issue:** The phase constraint states "no secrets may be logged (error strings must be truncated, no traceback/cookies/tokens)." The runner writes the **full, untruncated** `str(e)` in three new/adjacent places:
- the JSONL `error` field (`_run_error = str(e)` at line 5819, persisted verbatim at line 5843),
- the new 🔁 REPEATED FAILURE Telegram alert (`Last error: {e}` at line 5814),
- (pre-existing, but the 🔁 alert replicates it) the ❌ alert at line 5807.

Truncation is only applied *downstream* in `health_check.classify_tasks` (`last_error_raw[:_MAX_ERROR_LEN]`, line 210-214). The on-disk JSONL record and the outbound Telegram message are not capped. While the runner's own `RuntimeError` messages are clean (`exit={returncode}`), `e` can be any exception object — including third-party `requests`/`urllib`/`openpyxl` errors whose message may embed a full URL, header, or path. The constraint is about the *write* path, and the write path does not truncate.
**Fix:** Truncate at the source before persisting/sending, mirroring `_MAX_ERROR_LEN`:
```python
def _safe_err(e: Exception, limit: int = 200) -> str:
    s = str(e).replace("\n", " ")          # collapse multi-line tracebacks
    return s[:limit] + "…" if len(s) > limit else s
...
_run_error = _safe_err(e)
send_telegram(f"🔁 REPEATED FAILURE: {args.task} failed {_obs03_streak} times in a row\nLast error: {_run_error}")
```

### WR-02: `test_no_traceback_in_alert` asserts nothing about tracebacks — false security assurance

**File:** `scripts/test_health_check.py:372-384`
**Issue:** This test is named and documented to verify T-04-02-02 ("Alert text must never include a full traceback"), and it injects an error string that literally contains `"Traceback (most recent call last):..."`. But the only assertion is `self.assertIn("🩺", alert)` — it never checks that the traceback text is absent from `alert`. The rest is comments. Because `classify_tasks` truncates by **length only** (no newline stripping, no traceback filtering), a multi-line error shorter than 200 chars *would* pass its traceback fragment straight into the Telegram message — and this test would still pass. The security guarantee it claims to enforce is unverified.
**Fix:** Add a real assertion, and make the source strip newlines/traceback markers:
```python
self.assertNotIn("Traceback (most recent", alert)
self.assertNotIn("\n  File \"", alert)
```
Pair with the WR-01 source fix (collapse newlines / cap length on the write path).

### WR-03: `test_repeated_failure_streak.py` drives the real `main()` against production state (real lock, real log, real Obsidian sync)

**File:** `scripts/test_repeated_failure_streak.py:235-256` (`_run_main_with_error`)
**Issue:** Unlike `test_run_log_jsonl.py` (which patches `fcntl.flock`, `task_workbook_locks`, `dispatch_alerts`, and `obsidian_sync`), this helper calls the real `runner.main()` while patching only `send_telegram`, `run_task`, and `RUN_LOG_JSONL`. As a result the test:
- acquires the **real** exclusive `LOCK_FILE` (`data/pnl/logs/sports_system_runner.lock`) — can block or be blocked by a live cron run,
- appends to the **real** operational log `data/pnl/logs/run_log.txt` (verified: the test run added `[verify] completed in 0.0s` lines to the live 6.2 MB log),
- runs the **real** `obsidian_sync` subprocess in `main()`'s `finally` against the operator's iCloud vault.

On a real-money machine that also runs Hermes cron, a test polluting the operational log and contending for the runner lock is a genuine isolation defect.
**Fix:** Patch the same surface `test_run_log_jsonl.py` does:
```python
with (
    patch("sys.argv", ["sports_system_runner.py", "--task", task]),
    patch.object(_fcntl, "flock", lambda *a, **k: None),
    patch.object(runner, "task_workbook_locks", _fake_task_locks),
    patch.object(runner, "obsidian_sync", lambda *a, **k: None),
    patch.object(runner, "LOCK_FILE", Path(self.tmpdir.name) / "test.lock"),
    patch.object(runner, "RUN_LOG", Path(self.tmpdir.name) / "run_log.txt"),
):
    return runner.main()
```

### WR-04: `run_log.jsonl` grows unbounded — no rotation/truncation, and every run re-reads the whole file

**File:** `scripts/sports_system_runner.py:323-332` (`append_run_record`), `363-400` (`trailing_failure_streak`); `scripts/health_check.py:132-157` (`read_run_log`)
**Issue:** `append_run_record` is append-only with no cap, rotation, or pruning. On a cron system firing ~11 tasks at intraday cadence, the JSONL grows indefinitely (the sibling `run_log.txt` is already 6.2 MB). Both `trailing_failure_streak` (line 376 `read_text().splitlines()`) and `read_run_log` (line 142 `read_text()`) read the **entire** file on every invocation. This is a correctness/reliability concern for a long-running unattended system, not just performance: an ever-growing file makes the failure-path read in `trailing_failure_streak` progressively slower exactly when the system is already failing, and risks the read tripping the task budget over months/years of uptime.
**Fix:** Cap the file (keep the last N lines) on append, or read only the tail. Minimal version:
```python
MAX_JSONL_LINES = 5000
def append_run_record(record):
    try:
        ensure_dirs()
        with RUN_LOG_JSONL.open("a") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
        # opportunistic trim
        lines = RUN_LOG_JSONL.read_text(errors="ignore").splitlines()
        if len(lines) > MAX_JSONL_LINES * 2:
            RUN_LOG_JSONL.write_text("\n".join(lines[-MAX_JSONL_LINES:]) + "\n")
    except Exception:
        pass
```

### WR-05: JSONL `status`/`exit_code` reflect only uncaught-exception flow, not the task's returned `result["status"]`

**File:** `scripts/sports_system_runner.py:5749-5751`, `5769-5772`, `5840-5847`
**Issue:** `_run_status` is initialized to `"ok"` and only changed in the `except` branches. When `run_task` returns a degraded/failed result dict **without raising** (status values `"failed"`, `"missing_script"`, or `"error"` exist in the codebase — e.g. `run_build_hit_rate_db` returns `{"status": "failed"}`), the JSONL records `status: "ok"`, `exit_code: 0`, and `health_check` classifies the task HEALTHY. For a system whose entire purpose is detecting silent failures, a task that returns a non-ok result without raising would be invisible to the health check. (Note: per the architecture, intentional SKIP states are *supposed* to map to success, so this is partly by design — but the record makes no attempt to distinguish a deliberate SKIP from a degraded `result["status"]`.)
**Fix:** When no exception occurred, derive status from the result when present:
```python
# in the success path, after _task_result = result
if isinstance(result, dict) and result.get("status") in {"error", "failed", "timeout"}:
    _run_status = "error"
    _run_exit_code = 1
    _run_error = _safe_err_str(result.get("error") or result.get("stderr") or result["status"])
```

## Info

### IN-01: Unused `import sys` in health_check.py

**File:** `scripts/health_check.py:20`
**Issue:** `import sys` is never referenced (`raise SystemExit(main())` uses the builtin, not `sys.exit`). Dead import.
**Fix:** Remove line 20.

### IN-02: Encoding-handling asymmetry between the two JSONL readers

**File:** `scripts/sports_system_runner.py:376` vs `scripts/health_check.py:142`
**Issue:** `health_check.read_run_log` reads with `errors="ignore"` (tolerates a truncated multi-byte char from a concurrent append), but `trailing_failure_streak` uses plain `read_text()`. A bad UTF-8 byte would raise `UnicodeDecodeError`, caught by the outer `except Exception: return 0` — degrading the *entire* streak to 0 and silently suppressing the 🔁 alert, rather than skipping just the one bad line.
**Fix:** Use `RUN_LOG_JSONL.read_text(encoding="utf-8", errors="ignore")` at line 376 to match the health-check reader and preserve the trailing count.

### IN-03: `test_threshold_env_override` does not exercise the actual constant

**File:** `scripts/test_health_check.py` (n/a) / `scripts/test_repeated_failure_streak.py:154-166`
**Issue:** The test sets `REPEATED_FAILURE_THRESHOLD` in `os.environ` then recomputes `int(runner.env_value(...) or "2")` inline. It never asserts anything about `runner.REPEATED_FAILURE_THRESHOLD`, which is an **import-time** constant (line 357-360) that cannot change after import. The test gives the impression env override is verified end-to-end when it only re-runs the parse expression. (Acceptable for a fresh-import-per-cron process, but the test is misleading.)
**Fix:** Either document that the threshold is import-time-only, or refactor it into a small function (`def _repeated_failure_threshold() -> int`) called at use sites and assert against that.

### IN-04: Append happens after the exclusive lock is released — possible concurrent-append interleaving

**File:** `scripts/sports_system_runner.py:5836-5848` (finally) vs `5761-5766` (lock block)
**Issue:** `append_run_record` runs in `main()`'s `finally`, which executes *after* the `with LOCK_FILE.open("w")` block has exited and released the `fcntl.LOCK_EX`. Two cron invocations overlapping at task boundaries could append concurrently. POSIX `O_APPEND` is atomic only for writes under `PIPE_BUF`; a long record could interleave. The downstream readers skip corrupt lines, so this degrades gracefully, but the JSONL write is not actually serialized by the runner lock the way one might assume.
**Fix:** No action strictly required given the corrupt-line-skipping readers; if stronger guarantees are wanted, move the JSONL append inside the lock block, or keep each record well under 4 KB (a truncation fix per WR-01 helps here too).

---

_Reviewed: 2026-06-21T09:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
