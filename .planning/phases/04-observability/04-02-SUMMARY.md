---
phase: 04-observability
plan: 02
subsystem: observability
tags: [obs-02, health-check, heartbeat, read-only, standalone]
dependency_graph:
  requires: [04-01]
  provides: [health_check.py, OBS-02, TASK_CADENCE_SECONDS]
  affects: []
tech_stack:
  added: []
  patterns: [standalone-script-with-env_value, urllib-telegram, read-only-JSONL-reader, classify-then-snapshot dual-output]
key_files:
  created:
    - scripts/health_check.py
    - scripts/test_health_check.py
  modified: []
decisions:
  - "TASK_CADENCE_SECONDS uses 26h for daily tasks (90-min grace buffer) and 2h for hourly monitors"
  - "Exit code convention: 0 = all healthy, 1 = any overdue or last-failed"
  - "Alert flag: --alert (opt-in); without --alert, snapshot-only (no Telegram) — safe for interactive runs"
  - "Error truncation limit: 200 chars + ellipsis in alert text (T-04-02-02 compliance)"
  - "Most-recent record wins: last record in JSONL order for a given task determines its classification"
metrics:
  duration_seconds: 420
  completed_date: "2026-06-21"
  tasks_completed: 2
  files_modified: 2
---

# Phase 04 Plan 02: OBS-02 Health Check Summary

**One-liner:** Standalone read-only `health_check.py` classifies all 11 tasks as HEALTHY / OVERDUE / LAST-FAILED by reading `run_log.jsonl`, prints a per-task snapshot to stdout, and fires a `🩺` Telegram alert (with `--alert`) when any task is overdue or last-failed.

## What Was Built

Implemented OBS-02: a self-contained `scripts/health_check.py` that gives the operator an on-demand system-health snapshot (or scheduled heartbeat) without acquiring the runner's exclusive file lock (D-04).

### Components Added

**`scripts/health_check.py`** — standalone read-only script:
- Shebang `#!/usr/bin/env python3`, docstring, `from __future__ import annotations`, stdlib-only imports (`urllib.request` — no `requests` dep), mirroring `send_slips_telegram.py`
- Path constants: `HOME`, `ROOT`, `HERMES_ENV`, `TELEGRAM_API`, `LOG_DIR`, `RUN_LOG_JSONL`
- `env_value(key)` — verbatim copy from `send_slips_telegram.py` (self-contained; no runner import)
- `now_iso()` — own UTC ISO timestamp (no runner import)
- `send_telegram(message)` — urllib-based, degrades to no-op (returns 2) when creds absent
- **`TASK_CADENCE_SECONDS: dict[str, int]`** — all 11 keys from `TASK_TIMEOUTS`, values = max staleness:
  - Daily tasks (`nba_daily_picks`, `mlb_daily_picks`, `nba_clv_tracker`, `mlb_clv_tracker`, `check_results`, `verify`): **93600s (26h)** — 24h schedule with 2h grace buffer
  - Hourly monitors (`nba_prop_monitor`, `mlb_prop_monitor`, `nba_injury_monitor`, `mlb_injury_monitor`, `game_completion_monitor`): **7200s (2h)** — 1h schedule with 1h grace buffer
- `read_run_log(path)` — opens `run_log.jsonl` read-only, iterates `.splitlines()`, `json.loads()` per line inside `try/except`, skips blank/corrupt lines (T-04-02-01)
- `classify_tasks(records, cadence, reference_time)` — per-task classification:
  - `HEALTHY`: last record within cadence and `status == "ok"`
  - `OVERDUE`: no record ever seen OR age > cadence
  - `LAST-FAILED`: last record within cadence but `status in {"error", "timeout"}`
- `format_snapshot(task_status)` — human-readable multi-line stdout output
- `build_alert_text(task_status)` — `🩺 HEALTH CHECK: N problem(s)` with truncated last-error strings (T-04-02-02: no traceback, no secrets)
- `main() -> int` — argparse with `--alert` and `--jsonl` flags; always prints snapshot; fires Telegram only on `--alert` + problems
- `raise SystemExit(main())` pattern (D-06 dual output honored)

**Exit-code convention:** `0` = all tasks HEALTHY; `1` = at least one OVERDUE or LAST-FAILED.

**`scripts/test_health_check.py`** — 27 tests across 5 test classes:
- `TestReadRunLog` (5 tests): missing file, valid records, blank lines, corrupt/partial lines, non-dict JSON
- `TestClassifyTasks` (9 tests): HEALTHY (1), OVERDUE stale (2), OVERDUE never-seen (3), LAST-FAILED error (4a), LAST-FAILED timeout (4b), most-recent-wins, error truncation, boundary edge case
- `TestMainExitCode` (5 tests): exit 0 healthy, exit 1 overdue, exit 1 last-failed, Telegram called with overdue+--alert, Telegram silent healthy, Telegram silent without --alert
- `TestFormatSnapshot` (2 tests): task names in snapshot, header line
- `TestBuildAlertText` (3 tests): empty on healthy, emoji on problems, no traceback content

All tests use `tempfile` + `unittest.mock.patch`; no real `run_log.jsonl` or Telegram calls.

## Key Design Choices

| Decision | Value | Rationale |
|----------|-------|-----------|
| Daily cadence | 93600s (26h) | 24h schedule + 2h grace for typical daily picks window |
| Monitor cadence | 7200s (2h) | ~1h typical cron run + 1h grace before alert |
| Alert flag | `--alert` (opt-in, default off) | Safe for interactive runs; `--alert` activates heartbeat Telegram |
| Exit code | 0 = healthy, 1 = problems | Standard shell convention; compatible with cron `MAILTO` on non-zero |
| Error truncation | 200 chars | Prevents info-disclosure (T-04-02-02); matches runner's existing alert hygiene |

## Threat Model Mitigations

| Threat | Mitigation Applied |
|--------|-------------------|
| T-04-02-01: Corrupt/partial JSONL line (no lock, concurrent write) | Every `json.loads()` call inside `try/except`; blank lines and non-dict JSON both silently skipped |
| T-04-02-02: Info-disclosure via Telegram alert | `last_error` truncated to 200 chars + `…`; no `traceback.format_exc()`, no env/secret values in alert text |
| T-04-02-03: stdout snapshot (low risk) | Accepted — operator-facing terminal output only |

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — `health_check.py` reads real `run_log.jsonl` and sends real Telegram alerts when configured.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes beyond what the plan's threat model already covers.

## Self-Check

### Created files exist

- `scripts/health_check.py` - exists (created, 382 lines)
- `scripts/test_health_check.py` - exists (created, 388 lines)

### Commits exist

- `aa57923` - feat(04-02): implement OBS-02 standalone read-only health_check.py
- `4183d48` - feat(04-02): add OBS-02 regression test suite (test_health_check.py)

## Self-Check: PASSED

All files present. All commits verified. 27/27 OBS-02 tests pass. 11/11 OBS-01 tests pass. No new failures.
