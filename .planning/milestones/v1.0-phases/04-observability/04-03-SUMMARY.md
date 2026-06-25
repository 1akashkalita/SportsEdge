---
phase: 04-observability
plan: 03
subsystem: observability
tags: [obs-03, streak-alert, repeated-failure, tdd]
dependency_graph:
  requires: [04-01]
  provides: [REPEATED_FAILURE_THRESHOLD, trailing_failure_streak, repeated-failure-alert]
  affects: [scripts/sports_system_runner.py]
tech_stack:
  added: []
  patterns: [JSONL tail-read with defensive parse, additive Telegram alert after existing alerts, env_value int constant]
key_files:
  created:
    - scripts/test_repeated_failure_streak.py
  modified:
    - scripts/sports_system_runner.py
decisions:
  - "Env var name: REPEATED_FAILURE_THRESHOLD (int, default 2, fallback on malformed)"
  - "REPEATED_FAILURE_THRESHOLD placed after env_value() definition (~line 354) to avoid forward-reference"
  - "trailing_failure_streak placed as sibling to append_run_record; returns prior count only (D-09 timing)"
  - "Streak walks backward through task-filtered records, stops at first status==ok, skips unknown statuses"
  - "Exact 🔁 alert wording: '🔁 REPEATED FAILURE: {task} failed {streak} times in a row\\nLast error: {e}'"
  - "Timeout branch uses 'budget {N}s exceeded (timeout)' as the last-error descriptor"
metrics:
  duration_seconds: 191
  completed_date: "2026-06-21"
  tasks_completed: 3
  files_modified: 2
---

# Phase 04 Plan 03: OBS-03 Repeated Failure Streak Alert Summary

**One-liner:** Configurable `REPEATED_FAILURE_THRESHOLD` (env-driven, default 2) with `trailing_failure_streak()` reading `run_log.jsonl` tail, firing a distinct `🔁 REPEATED FAILURE` Telegram alert additively in both `except` branches of `main()` once consecutive failures reach the threshold.

## What Was Built

Implemented OBS-03: when the same task fails (error or timeout) N or more times in a row, a distinct `🔁 REPEATED FAILURE` alert fires in addition to the per-occurrence `❌ SPORTS TASK FAILED` / `⏱ TASK TIMED OUT` alerts. The streak is derived solely from `run_log.jsonl` (the OBS-01 record), with no separate counter or state file.

### Components Added

**`REPEATED_FAILURE_THRESHOLD` constant** (`scripts/sports_system_runner.py` ~line 354):
```python
try:
    REPEATED_FAILURE_THRESHOLD: int = max(1, int(env_value("REPEATED_FAILURE_THRESHOLD") or "2"))
except Exception:
    REPEATED_FAILURE_THRESHOLD = 2
```
Placed after `env_value()` definition to avoid forward-reference. Reads `REPEATED_FAILURE_THRESHOLD` env var; malformed/empty value falls back to 2 without raising.

**`trailing_failure_streak(task: str) -> int`** (~line 364):
- Opens `RUN_LOG_JSONL` read-only
- Skips blank/corrupt JSONL lines (defensive `json.loads` per line in `try/except`)
- Filters to records for the given `task`
- Walks backward counting records with `status in {"error", "timeout"}`, stopping at the first `status == "ok"` (D-08 reset — includes no-games SKIP which returns `ok`)
- Returns PRIOR failure count only (current record not yet on disk — D-09 timing)
- Entire body wrapped in `try/except Exception: return 0` — never raises on the failure path

**🔁 alert in `except TaskTimeoutError` branch** (after `⏱ TASK TIMED OUT` send):
```python
_obs03_streak = trailing_failure_streak(args.task) + 1
if _obs03_streak >= REPEATED_FAILURE_THRESHOLD:
    send_telegram(
        f"🔁 REPEATED FAILURE: {args.task} failed {_obs03_streak} times in a row\n"
        f"Last error: budget {budget}s exceeded (timeout)"
    )
```

**🔁 alert in `except Exception as e` branch** (after `❌ SPORTS TASK FAILED` send):
```python
_obs03_streak = trailing_failure_streak(args.task) + 1
if _obs03_streak >= REPEATED_FAILURE_THRESHOLD:
    send_telegram(
        f"🔁 REPEATED FAILURE: {args.task} failed {_obs03_streak} times in a row\n"
        f"Last error: {e}"
    )
```

**`scripts/test_repeated_failure_streak.py`** — 17 tests covering:
- Streak counting: `ok,error,error→2`; `error,ok,error→1`; newest-ok→0; missing-file→0
- Task filtering: records for other tasks are ignored
- Timeout records count in streak
- D-08 reset: `ok` (including SKIP) clears to 0
- Corrupt/blank JSONL lines are skipped without raising
- `REPEATED_FAILURE_THRESHOLD` default is 2 (env-overridable)
- D-09 timing: prior-streak + 1 for current failure
- First failure (streak 1 < 2) fires only `❌`, no `🔁`
- Second consecutive failure fires BOTH `❌` and `🔁`
- `🔁` alert names task, count, and error string
- `❌` fires before `🔁` (order check)

## Configuration

| Env Var | Default | Effect |
|---------|---------|--------|
| `REPEATED_FAILURE_THRESHOLD` | `2` | Minimum consecutive failures before `🔁` alert fires |

## Exact 🔁 Alert Wording

**Exception path:**
```
🔁 REPEATED FAILURE: {task} failed {streak} times in a row
Last error: {str(e)}
```

**Timeout path:**
```
🔁 REPEATED FAILURE: {task} failed {streak} times in a row
Last error: budget {budget}s exceeded (timeout)
```

The `{streak}` count grows on each subsequent failure, so an ongoing outage keeps generating increasingly alarming counts.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] REPEATED_FAILURE_THRESHOLD placement moved after env_value()**
- **Found during:** Task 2 implementation
- **Issue:** The plan cited placing the constant beside `TASK_TIMEOUTS` (~line 112), but `env_value()` is defined at ~line 337 — placing the constant before it would cause a `NameError` at module load time.
- **Fix:** Placed `REPEATED_FAILURE_THRESHOLD` and `trailing_failure_streak` after `env_value()`, before `send_telegram()` — still logically grouped with the helper functions and accessible to `main()`.
- **Files modified:** `scripts/sports_system_runner.py`
- **Commit:** 816e531

## Security Notes (Threat Model)

- T-04-03-01 (Info Disclosure): `🔁` alert uses only `str(e)` (same truncated error string as the existing `❌` alert at line 5799). `traceback.format_exc()` continues to go only to `run_log.txt`. No env vars, secrets, or stack traces in the Telegram message.
- T-04-03-02 (DoS on failure path): `trailing_failure_streak` is wrapped to return 0 on any parse/IO error — a corrupt or unreadable `run_log.jsonl` can never raise inside the `except` branch and compound a normal failure.
- T-04-03-03 (Spoofing/Tampering of streak source): Accepted — local filesystem write access is same trust zone as all other `data/pnl/logs/` files.

## Self-Check

### Created files exist

- `scripts/test_repeated_failure_streak.py` — exists (created)

### Commits exist

- `456aed3` — test(04-03): add failing OBS-03 regression test (RED)
- `816e531` — feat(04-03): add REPEATED_FAILURE_THRESHOLD + trailing_failure_streak helper
- `0484c16` — feat(04-03): fire 🔁 REPEATED FAILURE alert in both failure branches (GREEN)

## Self-Check: PASSED

All files present. All commits verified. 17/17 OBS-03 tests pass. 82/82 spot-check tests (including OBS-01, slip_payouts, line_timing, dynamic_gate8) pass. No new failures beyond the known "2 failed" baseline.
