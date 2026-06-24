---
phase: 01-foundation-data-layer
plan: 01
subsystem: dashboard-tests
tags: [dashboard, flask, testing, tdd, red-phase]
dependency_graph:
  requires: []
  provides: [test_dashboard.py, test_dashboard_data.py]
  affects: [phase-01-plan-02, phase-01-plan-03]
tech_stack:
  added: []
  patterns: [unittest-bootstrap, Flask-test-client, werkzeug-make-server, TemporaryDirectory-fixture, monkeypatch-module-constant]
key_files:
  created:
    - scripts/test_dashboard.py
    - scripts/test_dashboard_data.py
  modified: []
decisions:
  - "Used werkzeug.serving.make_server for the live-bind Flask test rather than app.test_client() so test_flask_serves proves an actual TCP 127.0.0.1 bind+self-GET (not just WSGI in-process)"
  - "Monkeypatched dashboard_data.safe_load_workbook via unittest.mock.patch.object for test_lock_tolerant — avoids creating an actually-locked file and is deterministic across environments"
  - "Used dead_pid=99999999 for the dead-process sub-case in test_write_in_progress — guaranteed non-existent on macOS (max pid ~99999); avoids timing races with PID reuse"
  - "test_write_in_progress covers three sub-cases in one test method: live+fresh (True), dead pid (False), live+stale mtime (False) — mirrors the three conditions in workbook_io stale_seconds=600"
metrics:
  duration: 2m 32s
  completed: "2026-06-24"
  tasks_completed: 2
  files_created: 2
---

# Phase 1 Plan 1: Wave-0 Test Scaffolds (DASH-01/02/03 + DASH-04/D-01/D-02) Summary

Wave-0 RED-phase test scaffolds for the localhost dashboard: Flask gating invariant proves D-06's tech choice live on Python 3.14.0a2, and five behavioral tests are RED against the real module/attribute names plans 02 and 03 will create.

## What Was Built

**`scripts/test_dashboard.py`** — Three test methods covering DASH-01/02/03:
- `test_flask_serves` (DASH-02): Uses `werkzeug.serving.make_server` to bind a minimal Flask app on `127.0.0.1` at an ephemeral port, issues a self-GET via `urllib.request`, and asserts HTTP 200 with a non-empty body. Uses `importlib.metadata.version("flask")` (not `flask.__version__`, removed in Flask 3.2). **PASSES NOW** on Python 3.14.0a2 — the D-06 gating invariant is proven.
- `test_route_index` (DASH-01): Imports `dashboard` and calls `dashboard.app.test_client().get("/")`. **RED** — `ModuleNotFoundError` on `dashboard` until plan 03.
- `test_loopback_only` (DASH-03): Asserts `dashboard.HOST == "127.0.0.1"` and that the host binds to `127.0.0.1` via a probe socket. **RED** — `ModuleNotFoundError` on `dashboard` until plan 03.

**`scripts/test_dashboard_data.py`** — Five test methods covering DASH-04 + D-01/D-02:
- `test_read_only_untouched` (DASH-04): Synthetic workbook in `TemporaryDirectory`; captures `st_mtime` + `sha256` before; calls `dashboard_data.read_sheet_rows`; asserts both values unchanged. **RED** — `ModuleNotFoundError` on `dashboard_data` at module import time.
- `test_lock_tolerant` (DASH-04/D-01): Monkeypatches `dashboard_data.safe_load_workbook` to raise `WorkbookAccessError`; asserts `read_sheet_rows` returns `None`/`[]` without raising. **RED** — `ModuleNotFoundError`.
- `test_missing_is_empty` (DASH-04): Calls `read_sheet_rows` and `read_json` on non-existent paths; asserts empty/`None` return with no exception. **RED** — `ModuleNotFoundError`.
- `test_today_matches_runner` (D-02): Asserts `dashboard_data.today_str()` equals `datetime.now().strftime("%Y-%m-%d")` AND verifies the source has no `zoneinfo`/`ZoneInfo` import (Pitfall 2 guard). **RED** — `ModuleNotFoundError`.
- `test_write_in_progress` (D-01): Three sub-cases in a `TemporaryDirectory`-based lock dir: live pid + fresh mtime → `True`; dead pid (99999999) + fresh mtime → `False`; live pid + stale mtime (>600s) → `False`. Mirrors the `{"pid","path","acquired_at"}` JSON shape and `stale_seconds=600` from `workbook_io.py:90`. **RED** — `ModuleNotFoundError`.

## Verification Results

```
# Gating invariant — must PASS:
cd scripts && python3 test_dashboard.py -k flask_serves
→ Ran 1 test in 0.756s: OK  (exit 0)

# RED tests in test_dashboard.py — must FAIL with ImportError:
cd scripts && python3 test_dashboard.py
→ Ran 3 tests, FAILED (errors=2): route_index, loopback_only both ModuleNotFoundError on 'dashboard'

# RED file-level fail in test_dashboard_data.py — must FAIL at import:
cd scripts && python3 test_dashboard_data.py
→ ModuleNotFoundError: No module named 'dashboard_data'
```

All three verification conditions from the plan satisfied.

## Decisions Made

1. `werkzeug.serving.make_server` for live bind (rather than `app.test_client()` for `test_flask_serves`) — proves an actual TCP `127.0.0.1` bind + OS-level GET, not just WSGI in-process routing. The stronger check catches a serve-time regression that an in-process test client would miss.
2. `unittest.mock.patch.object` on `dashboard_data.safe_load_workbook` for `test_lock_tolerant` — deterministic, no OS-level file locking needed, runs fast and reliably on any machine.
3. `dead_pid=99999999` for the dead-process sub-case — guaranteed non-existent on macOS (system max ~99999); avoids timing races with PID reuse that could cause a false `True`.
4. Three sub-cases in `test_write_in_progress` cover the full decision matrix: live+fresh → True, dead+fresh → False, live+stale → False. All use the same lock JSON shape and `stale_seconds=600` from `workbook_io.py`.

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — this plan creates test files only; no module-level stubs or placeholders exist.

## Threat Flags

None — both files are test-only; no new network endpoints, auth paths, file access patterns, or schema changes were introduced.

## Self-Check: PASSED

Files created:
- FOUND: /Users/akashkalita/sports_picks/scripts/test_dashboard.py
- FOUND: /Users/akashkalita/sports_picks/scripts/test_dashboard_data.py

Commits:
- FOUND: 321e983 (test_dashboard.py)
- FOUND: a2ed6f9 (test_dashboard_data.py)
