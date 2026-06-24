---
phase: 01-foundation-data-layer
plan: 02
subsystem: dashboard-data-layer
tags: [data-layer, read-only, workbook-io, lock-tolerance, dashboard]
dependency_graph:
  requires: ["01-01"]
  provides: ["dashboard_data.py read-only layer"]
  affects: ["01-03-flask-shell"]
tech_stack:
  added: []
  patterns: ["read_only=True workbook reads", "cooperative lock pid-liveness probe", "JSON-first data access"]
key_files:
  created:
    - scripts/dashboard_data.py
  modified: []
decisions:
  - "Re-exported safe_load_workbook + WorkbookAccessError from workbook_io for callers — avoids duplicating retry logic"
  - "read_sheet_rows returns None (not []) on WorkbookAccessError to distinguish locked-workbook from empty-sheet"
  - "Removed ZoneInfo from all source text (including docstrings) to satisfy test assertNotIn guard"
  - "STALE_SECONDS and LOCK_DIR exposed as module-level constants so Wave-0 tests can override them in-process"
metrics:
  duration: "3m 5s"
  completed: "2026-06-24"
  tasks_completed: 2
  files_created: 1
---

# Phase 1 Plan 02: Dashboard Data Layer Summary

**One-liner:** Read-only data layer with lock-tolerant workbook reader, pid-liveness badge, and pipeline-matching today date — all five Wave-0 tests green.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Build JSON-first + lock-tolerant read accessors (read_json, read_sheet_rows) and today_str | ef0eb4c | scripts/dashboard_data.py |
| 2 | Build freshness/badge signals (write_in_progress, last_updated_hhmm) | ef0eb4c | scripts/dashboard_data.py |

Note: Both tasks were committed together as a single atomic unit because they produce a single file and the test suite validates them holistically.

## What Was Built

`scripts/dashboard_data.py` — 245 lines. A read-only data layer that:

- **`read_json(path)`** — parses JSON files; returns `None` on `FileNotFoundError`/`JSONDecodeError`. Lock-free fast path for `bankroll.json`, `calibration.json`, `*_latest.json`.

- **`read_sheet_rows(xlsx, sheet)`** — opens workbook with `read_only=True, data_only=True`; returns header-mapped row dicts, `[]` for absent sheet, `None` on `WorkbookAccessError`/`FileNotFoundError`. Always closes in `finally` (Pitfall 4). Never raises (D-01).

- **`today_str()`** — `datetime.now().strftime("%Y-%m-%d")` with no timezone import. Matches the runner's exact pattern to prevent midnight workbook mismatch (D-02).

- **`write_in_progress()`** — iterates `LOCK_DIR/*.xlsx.lock`; returns `True` only when a lock is both fresh (mtime age < 600s) and holds a live pid (`os.kill(pid, 0)` without `ProcessLookupError`). `PermissionError` counts as alive. Presence alone is never sufficient (Pitfall 1).

- **`last_updated_hhmm()`** — reads last non-empty line of `run_log.jsonl`, parses `["timestamp"]` (UTC), converts to machine-local via `.astimezone()`, returns `"HH:MM"`. Returns `None` on any error.

- **Re-exports:** `safe_load_workbook`, `WorkbookAccessError` from `workbook_io` for callers.

- **Constants:** `LOCK_DIR`, `NBA_DIR`, `MLB_DIR`, `STALE_SECONDS=600` — all module-level and overridable in tests.

## Test Results

All 5 Wave-0 tests pass:

| Test | Status |
|------|--------|
| test_read_only_untouched | PASSED — mtime+sha256 unchanged after read_only load |
| test_lock_tolerant | PASSED — WorkbookAccessError → None/[], never raises |
| test_missing_is_empty | PASSED — missing xlsx/JSON → None/[], no exception |
| test_today_matches_runner | PASSED — matches naive-local datetime.now(), no ZoneInfo |
| test_write_in_progress | PASSED — live+fresh → True; dead OR stale → False |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] ZoneInfo string in docstring blocked test**
- **Found during:** Task 1 test run (test_today_matches_runner)
- **Issue:** Test asserts `assertNotIn("ZoneInfo", source_text)` against the entire source file. A docstring comment containing "no ZoneInfo import anywhere" triggered the assertion.
- **Fix:** Replaced "ZoneInfo" with "timezone library" in the docstring for `today_str()`.
- **Files modified:** scripts/dashboard_data.py
- **Commit:** ef0eb4c

## Threat Surface Scan

No new network endpoints, auth paths, file writes, or schema changes. Module is strictly read-only. All threat register dispositions (T-1-02, T-1-03, T-1-04) confirmed mitigated:
- T-1-02 Tampering: no save/write path (grep confirms)
- T-1-03 DoS: WorkbookAccessError caught, returns None (never hangs)
- T-1-04 Spoofing: pid-liveness + age<600 double gate applied

## Known Stubs

None — all functions return live data from filesystem sources.

## Self-Check: PASSED

- scripts/dashboard_data.py: FOUND
- commit ef0eb4c: FOUND
- All 5 tests: PASSED
