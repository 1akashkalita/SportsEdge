---
phase: 04-observability
plan: 01
subsystem: observability
tags: [obs-01, jsonl, structured-logging, tdd]
dependency_graph:
  requires: []
  provides: [run_log.jsonl, append_run_record, RUN_LOG_JSONL]
  affects: [scripts/sports_system_runner.py]
tech_stack:
  added: []
  patterns: [append-only JSONL file write, defensive try/except around side-effects, sys.argv patch in unittest]
key_files:
  created:
    - scripts/test_run_log_jsonl.py
  modified:
    - scripts/sports_system_runner.py
decisions:
  - RUN_LOG_JSONL constant placed directly below RUN_LOG at line ~59 (D-01 sibling pattern)
  - append_run_record() uses open("a") not write_text() to preserve append-only JSONL semantics
  - Tracking vars (_run_status/_run_error/_run_exit_code) initialized before try block to avoid referencing out-of-scope `e` in finally
  - BrokenPipeError early-return leaves status as "ok" default (represents completed task whose pipe closed after success)
  - Test uses patch("sys.argv") not runner.main(args) because main() takes 0 positional args via argparse
  - Sport derivation: args.task.startswith(("nba_", "mlb_")) guard prevents "game"/"check" being treated as sport prefixes
metrics:
  duration_seconds: 235
  completed_date: "2026-06-21"
  tasks_completed: 3
  files_modified: 2
---

# Phase 04 Plan 01: OBS-01 Structured JSONL Run Log Summary

**One-liner:** Append-only JSONL run log (`run_log.jsonl`) with 7-field Core+ record (task, status, duration_s, error, timestamp, exit_code, sport) emitted from `main()`'s `finally` block using defensive `append_run_record()` helper.

## What Was Built

Implemented OBS-01: every `sports_system_runner.py` invocation now emits one structured JSON record to `data/pnl/logs/run_log.jsonl`, giving the operator after-the-fact visibility into every run without parsing the free-form `run_log.txt`.

### Components Added

**`RUN_LOG_JSONL` constant** (`scripts/sports_system_runner.py` ~line 59):
```python
RUN_LOG_JSONL = LOG_DIR / "run_log.jsonl"
```
Placed directly below `RUN_LOG` as a sibling constant. `RUN_LOG` and `log()` are untouched.

**`append_run_record(record: dict[str, Any]) -> None`** (~line 323):
- Opens `RUN_LOG_JSONL` with `.open("a")` (append-only — never overwrites)
- Writes `json.dumps(record, sort_keys=True) + "\n"`
- Entire body wrapped in `try/except Exception: pass` (defensive — never crashes a task)

**Tracking variables** in `main()` (initialized after `_task_result`):
```python
_run_status: str = "ok"
_run_error: str | None = None
_run_exit_code: int = 0
```

**Per-branch status assignment:**
- Success path: leaves defaults (`"ok"`, `None`, `0`)
- `except TaskTimeoutError`: sets `_run_status = "timeout"`, `_run_exit_code = 1`
- `except Exception`: sets `_run_status = "error"`, `_run_error = str(e)`, `_run_exit_code = 1`
- `BrokenPipeError` early-return: leaves defaults (completed task, pipe closed after success)

**Record emit in `finally` block** (after `log(f"[{args.task}] completed in ...")`, before Obsidian sync):
```python
append_run_record({
    "task": args.task,
    "status": _run_status,
    "duration_s": round(elapsed, 1),
    "error": _run_error,
    "timestamp": now_iso(),
    "exit_code": _run_exit_code,
    "sport": args.task.split("_")[0] if args.task.startswith(("nba_", "mlb_")) else None,
})
```

**`test_run_log_jsonl.py`** — 11 tests covering:
- `append_run_record` round-trip, append-only semantics, defensive no-raise on unwritable path
- Core+ record shape for ok/error/timeout outcomes (all 7 keys present, correct values)
- Sport derivation: `nba_prop_monitor` → `"nba"`, `mlb_daily_picks` → `"mlb"`, `check_results`/`verify`/`game_completion_monitor` → `None`

## JSONL Record Contract (fixed for OBS-02/OBS-03 consumers)

```json
{
  "duration_s": 12.3,
  "error": null,
  "exit_code": 0,
  "sport": "nba",
  "status": "ok",
  "task": "nba_daily_picks",
  "timestamp": "2026-06-21T08:12:00+00:00"
}
```

**Field casing:** all lowercase snake_case.
**`sort_keys=True`** in `json.dumps` — keys are always alphabetical on disk.
**`status` values:** `"ok"` | `"error"` | `"timeout"`.
**`sport` derivation rule:** `task.split("_")[0]` when `task.startswith(("nba_", "mlb_"))`, else `None`. Tasks `game_completion_monitor`, `check_results`, `verify` → `None`.
**`duration_s`:** `round(elapsed, 1)` — one decimal float.
**`error`:** `str(e)` on exception, `None` on success/timeout (timeout has no `str(e)`, only the budget info in the timeout JSON_RESULT).
**`timestamp`:** `now_iso()` → UTC ISO 8601 with seconds precision.
**File location:** `data/pnl/logs/run_log.jsonl` (beside `run_log.txt`).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed main() argument passing in test**
- **Found during:** Task 3 (GREEN verification)
- **Issue:** `runner.main(["--task", task])` raised `TypeError: main() takes 0 positional arguments but 1 was given` — `main()` uses `argparse` which reads `sys.argv` directly, not a passed argument list.
- **Fix:** Changed test `_run_main_stub` and `_emit_record_for_task` to `patch("sys.argv", [...])` before calling `runner.main()` with no arguments.
- **Files modified:** `scripts/test_run_log_jsonl.py`
- **Commit:** 4783528

## Security Notes (Threat Model T-04-01)

Per T-04-01: only `str(e)` is serialized to the `error` field — the same truncatable string already sent in the `❌ SPORTS TASK FAILED` Telegram alert. `traceback.format_exc()` continues to go only to `run_log.txt` (existing behavior). No env vars, secrets, or full stack traces are written to `run_log.jsonl`.

## Self-Check

### Created files exist

- `scripts/test_run_log_jsonl.py` - exists (created)

### Commits exist

- `7ee21c4` - test(04-01): add failing OBS-01 regression test (RED)
- `96f9c28` - feat(04-01): add RUN_LOG_JSONL constant and append_run_record() helper
- `4783528` - feat(04-01): emit Core+ JSONL record per invocation from main() finally (GREEN)

## Self-Check: PASSED

All files present. All commits verified. 11/11 OBS-01 tests pass. No new failures in regression tests.
