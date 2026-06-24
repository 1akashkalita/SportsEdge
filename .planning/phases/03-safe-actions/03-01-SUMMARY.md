---
phase: 03-safe-actions
plan: 01
subsystem: testing
tags: [flask, openpyxl, unittest, dashboard, tdd-red-scaffold]

# Dependency graph
requires:
  - phase: 02-read-views
    provides: dashboard.py Flask app, dashboard_data.py read layer, Flask test_client patterns
  - phase: 01-foundation-data-layer
    provides: workbook_io atomic save, dashboard.py/dashboard_data.py shells
provides:
  - scripts/dashboard_writes.py stub module (mark_placed, add_note slips-only signatures, ACTION-04 hard line documented)
  - scripts/test_dashboard_actions.py RED scaffold with 9 ACTION-01..04 test node IDs
  - dashboard.app.secret_key wired (flash() prerequisite for D-06 inline banner)
affects:
  - 03-02 (write-helpers implementation turns TestMarkPlaced, TestAddNote, TestActionFourHardLine GREEN)
  - 03-03 (route implementation turns TestRefreshAction, TestStatusEndpoint GREEN)
  - 03-04 (human-UAT checkpoint builds on fully-GREEN suite)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - importlib runner-load idiom (spec_from_file_location, load_suppressed_edge_types stubbed) for test isolation
    - _make_slip_history_wb() synthetic workbook fixture using exact 23-column SLIP_HISTORY_HEADERS
    - _ensure_ws_columns inlined in dashboard_writes.py (never import from runner — Pitfall 6)
    - PNL_DIR anchored on Path.home() (never hardcoded username)
    - patch.object(dashboard_writes, "PNL_DIR", ...) for write-path test isolation

key-files:
  created:
    - scripts/dashboard_writes.py
    - scripts/test_dashboard_actions.py
  modified:
    - scripts/dashboard.py

key-decisions:
  - "dashboard_writes.py is slips-only for v1 (D-08 verdict: Picks Slip ID is null in live data; Date+Selection not guaranteed unique — pick key cannot be confirmed)"
  - "ensure_ws_columns inlined in dashboard_writes.py per Pitfall 6 — importing from runner loads 8000+ lines at dashboard startup"
  - "app.secret_key set via os.environ.get('DASHBOARD_SECRET_KEY') or os.urandom(16) — no hardcoded key, no persistent-session guarantee needed for localhost flash cookies"
  - "test_exposure_caps_unchanged passes at Wave 1 (static constant assertion); the 8 remaining tests are RED as required"

patterns-established:
  - "Pattern 1: RED-first test stubs — real assertions (not skipTest) so they go GREEN automatically when waves land implementations"
  - "Pattern 2: Write-path test isolation — patch.object(module, 'PNL_DIR', tmp_dir) avoids touching live master_pnl.xlsx"
  - "Pattern 3: Multi-sheet workbook fixture — non-Slip-History sheets populated to verify ACTION-04c write scope isolation"

requirements-completed: [ACTION-01, ACTION-02, ACTION-03, ACTION-04]

# Metrics
duration: 10min
completed: 2026-06-24
---

# Phase 03 Plan 01: Safe Actions Test Foundation Summary

**RED test scaffold for 9 ACTION-01..04 behaviors + dashboard_writes.py slips-only stub + Flask flash() wired via app.secret_key**

## Performance

- **Duration:** ~10 min
- **Started:** 2026-06-24T09:41:00Z
- **Completed:** 2026-06-24T09:51:32Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Created `scripts/dashboard_writes.py` stub with `mark_placed` and `add_note` signatures (slips-only scope per D-08 verdict, ACTION-04 hard line in module docstring, `_ensure_ws_columns` inlined, `PNL_DIR` anchored on `Path.home()`).
- Wired `app.secret_key = os.environ.get("DASHBOARD_SECRET_KEY") or os.urandom(16)` in `dashboard.py` (flash() prerequisite for D-06 inline banners in later waves).
- Created `scripts/test_dashboard_actions.py` with all 9 ACTION-01..04 test node IDs: 8 RED (routes/implementations not yet wired), 1 passing (`test_exposure_caps_unchanged` — correct static cap assertion per plan).

## Task Commits

Each task was committed atomically:

1. **Task 1: Create dashboard_writes.py stub + wire app.secret_key** - `d7ac621` (feat)
2. **Task 2: Write RED test scaffold test_dashboard_actions.py** - `e365074` (test)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `scripts/dashboard_writes.py` — Additive write helper stub; mark_placed/add_note with NotImplementedError bodies; inlined _ensure_ws_columns; PNL_DIR constant; ACTION-04 and slips-only documented in module docstring.
- `scripts/dashboard.py` — Added `app.secret_key = os.environ.get("DASHBOARD_SECRET_KEY") or os.urandom(16)` after Flask app creation (line 33).
- `scripts/test_dashboard_actions.py` — 9-test RED scaffold: TestRefreshAction (01a/b/c), TestStatusEndpoint (01d), TestMarkPlaced (02), TestAddNote (03), TestActionFourHardLine (04a/b/c). Uses importlib runner-load idiom, _make_slip_history_wb fixture, patch.object(dashboard_writes, "PNL_DIR") for isolation.

## Decisions Made

- Slips-only scope for `dashboard_writes.py` v1 confirmed per D-08 research verdict — Picks `Slip ID` is null in live data; `Date+Selection` not guaranteed unique. Pick-level notes deferred.
- `ensure_ws_columns` inlined in `dashboard_writes.py` (Pitfall 6) — importing from the runner loads 8,000+ lines at dashboard startup, violating the subprocess-isolation architectural constraint.
- `app.secret_key` uses env var with `os.urandom(16)` fallback — matches no-hardcoded-secrets rule in CLAUDE.md; ephemeral random key is sufficient for localhost flash-session cookies.
- `test_exposure_caps_unchanged` deliberately passes at Wave 1 — this is expected per the plan (static constant assertion). The plan's acceptance criteria require "all currently RED" only for the 8 behavioral tests.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. One minor adjustment: removed `DAILY_EXPOSURE_CAP` mention from a test docstring (grep check found it in a comment and acceptance criteria required no occurrences).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Wave 1 (Plan 03-01) complete: RED scaffold established, module stubs importable.
- Plan 03-02 can proceed: implement `mark_placed` and `add_note` bodies to turn TestMarkPlaced, TestAddNote, TestActionFourHardLine GREEN.
- Plan 03-03 can proceed after 03-02: implement `/action/refresh`, `/api/status`, `/action/mark-placed`, `/action/add-note` routes to turn TestRefreshAction and TestStatusEndpoint GREEN.
- Existing dashboard tests (23 tests in test_dashboard.py, test_dashboard_data.py, test_dashboard_views.py) all pass — no regressions from `app.secret_key` addition.

---
*Phase: 03-safe-actions*
*Completed: 2026-06-24*
