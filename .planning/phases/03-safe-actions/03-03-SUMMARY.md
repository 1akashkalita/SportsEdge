---
phase: 03-safe-actions
plan: 03
subsystem: dashboard-action-layer
tags: [flask, fcntl, subprocess, threading, dashboard, safe-actions, lock-probe]

# Dependency graph
requires:
  - phase: 03-safe-actions-01
    provides: test_dashboard_actions.py RED scaffold (TestRefreshAction, TestStatusEndpoint tests)
  - phase: 03-safe-actions-02
    provides: dashboard_writes.mark_placed, add_note; dashboard_data.last_run_record
provides:
  - scripts/dashboard.py: _runner_is_locked probe, ALLOWED_TASKS whitelist, /action/refresh async spawn route, /api/status JSON endpoint, /action/mark-placed and /action/add-note POST routes
affects:
  - 03-04 (human-UAT: all 9 test_dashboard_actions.py tests GREEN; /action/refresh, /action/mark-placed, /action/add-note wired for template forms)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - fcntl.LOCK_EX|LOCK_NB non-blocking probe mirrors runner's LOCK_EX acquisition in read-only form
    - threading.Thread(daemon=True) + subprocess.Popen(stdout=DEVNULL, stderr=DEVNULL) fire-and-forget async spawn (never communicate)
    - ALLOWED_TASKS frozenset whitelist checked BEFORE any subprocess.Popen (task injection mitigation T-03-05)
    - POST->redirect->render (D-06): all POST routes flash result and redirect to url_for target; no inline confirm
    - try/except Exception around write helpers: flash "Save failed: {exc}" on any error

key-files:
  created: []
  modified:
    - scripts/dashboard.py

key-decisions:
  - "Both tasks implemented in one file edit and commit — dashboard.py is the sole file; splitting would have required an artificial mid-file partial save. Noted as minor deviation from strict per-task commits."
  - "_runner_is_locked() opens RUNNER_LOCK_FILE with mode 'r' (not 'w') to avoid truncating the runner's lock file — critical correctness requirement"
  - "action_refresh() uses _runner_is_locked() as the lock check, not dashboard_data.write_in_progress() (which probes per-workbook locks, not the runner process lock — Pitfall 1)"
  - "Async spawn uses threading.Thread(daemon=True) + Popen(DEVNULL) with no communicate() call — ensures Flask worker returns immediately (D-02) and pipe-buffer deadlock is impossible (Pitfall 3, T-03-08)"

patterns-established:
  - "Pattern: _runner_is_locked probe for lock-aware async spawn (mirrors runner fcntl.LOCK_EX in non-blocking form)"
  - "Pattern: ALLOWED_TASKS frozenset whitelist enforced at route entry before any subprocess (task injection guard)"
  - "Pattern: POST routes flash then redirect; write helpers called inside try/except with flash on failure"

requirements-completed: [ACTION-01, ACTION-02, ACTION-03]

# Metrics
duration: 12min
completed: 2026-06-24
---

# Phase 03 Plan 03: Flask Action Routes Summary

**Lock-aware async /action/refresh route with ALLOWED_TASKS whitelist + /api/status JSON endpoint + mark-placed/add-note POST routes wired to Plan-02 write helpers; all 9 test_dashboard_actions.py tests GREEN**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-24T10:05:00Z
- **Completed:** 2026-06-24T10:17:00Z
- **Tasks:** 2 (implemented together in one file edit)
- **Files modified:** 1

## Accomplishments

- Added `_runner_is_locked()` private helper: opens `RUNNER_LOCK_FILE` with `"r"` (non-truncating), probes with `fcntl.LOCK_EX | fcntl.LOCK_NB`; on success releases and returns `False`; on `BlockingIOError` returns `True`; on `FileNotFoundError`/`OSError` returns `False`.
- Added module constants `PYTHON3`, `SCRIPTS_DIR`, `RUNNER_LOCK_FILE`, and `ALLOWED_TASKS` (frozenset of D-01 curated five tasks).
- Added `POST /action/refresh`: whitelist-checked, lock-probed, async fire-and-forget spawn via `threading.Thread(daemon=True)` + `subprocess.Popen(DEVNULL/DEVNULL)`. Never calls `communicate()`. Returns 302 on all paths (ACTION-01, success criteria 1 & 2).
- Added `GET /api/status`: returns `{locked, write_in_progress, last_updated, last_run}` JSON using existing `dashboard_data` signals + new `last_run_record(task)` from Plan 02 (ACTION-01d).
- Added `POST /action/mark-placed`: reads `date`/`slip_id`/`placed` from form; empty-field short-circuit; calls `dashboard_writes.mark_placed()` in try/except; flashes success/failure; redirects to `url_for("slips")` (ACTION-02).
- Added `POST /action/add-note`: same pattern; calls `dashboard_writes.add_note()`; redirects to `url_for("slips")` (ACTION-03).
- All 9 `test_dashboard_actions.py` tests GREEN; 23 existing dashboard tests pass (no regression).

## Task Commits

1. **Task 1 + Task 2: Add routes to dashboard.py** - `23bfcec` (feat)

**Plan metadata:** (docs commit follows)

## Files Created/Modified

- `scripts/dashboard.py` — Added imports (`fcntl`, `subprocess`, `Path`, `dashboard_writes`, extended Flask imports); added `PYTHON3`/`SCRIPTS_DIR`/`RUNNER_LOCK_FILE`/`ALLOWED_TASKS` constants; added `_runner_is_locked()` helper; added `/action/refresh`, `/api/status`, `/action/mark-placed`, `/action/add-note` routes.

## Decisions Made

- Both tasks implemented in a single commit: both routes live in `dashboard.py` and were written in one pass to avoid an artificial partial save of the same file between tasks.
- `_runner_is_locked()` opens the lock file with mode `"r"` (read-only) so the existing lock file is never truncated — the runner's `fcntl.LOCK_EX` hold would be broken if the file were opened for writing.
- Refresh lock check is `_runner_is_locked()`, not `write_in_progress()` — `write_in_progress()` probes per-workbook lock files, not the runner process lock (Pitfall 1 avoidance).
- `write_in_progress()` appears only in `_freshness_context()` (for nav badge) and `api_status()` (as an informational field) — it is not the refresh gate.

## Deviations from Plan

### Minor Deviation

**1. [Minor] Tasks 1 and 2 committed together**
- **Found during:** Task 1 implementation
- **Rationale:** Both tasks modify only `dashboard.py`. Writing one part, committing, then writing the remaining routes in the same file would require re-reading and re-editing an already-modified file mid-task. The combined commit still provides atomic traceability for all route additions.
- **Impact:** None on correctness or test results. All 9 tests GREEN. Verification criteria for both tasks fully met.

## Issues Encountered

- The plan's verify command `! grep -q "communicate(" dashboard.py` would have matched a comment containing `communicate()`. Changed the comment to not include the literal string `communicate(` so the anti-pattern grep works cleanly.

## Known Stubs

None — all routes are fully wired to their Plan-02 write helpers and data layer.

## Threat Surface Scan

No new network endpoints beyond those in the plan's `<threat_model>`. The four routes are local-only (bound to `127.0.0.1`). Security mitigations from the threat register are implemented:
- T-03-05: ALLOWED_TASKS whitelist enforced before any Popen
- T-03-06: date/slip_id passed only to helpers, never interpolated into filesystem paths
- T-03-07: _runner_is_locked() probe refuses concurrent spawn
- T-03-08: subprocess.DEVNULL on both streams, no communicate()

## Self-Check: PASSED

- `scripts/dashboard.py` — FOUND (modified)
- Commit `23bfcec` — FOUND (git log confirmed)
- `ALLOWED_TASKS` in dashboard.py — CONFIRMED
- `subprocess.DEVNULL` in dashboard.py — CONFIRMED
- No `communicate(` in code — CONFIRMED (only in comment with different phrasing)
- `_runner_is_locked()` is the refresh lock check — CONFIRMED (line 167)
- `write_in_progress()` only in _freshness_context + api_status — CONFIRMED
- All 9 test_dashboard_actions.py tests GREEN — CONFIRMED
- All 23 existing dashboard tests GREEN — CONFIRMED

---
*Phase: 03-safe-actions*
*Completed: 2026-06-24*
