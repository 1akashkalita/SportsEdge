---
phase: 03-safe-actions
plan: "04"
subsystem: ui
tags: [flask, jinja2, html, javascript, setInterval, flash-messages, forms]

# Dependency graph
requires:
  - phase: 03-safe-actions/03-03
    provides: "Lock-aware async /action/refresh + /api/status + /action/mark-placed + /action/add-note routes"
provides:
  - "Flash banner block in base.html (get_flashed_messages with categories: success/error/warning)"
  - "Per-slip Mark Placed toggle form + Add Note inline form in slips.html"
  - "Persisted Placed / Placed At / Operator Note state display per slip row"
  - "Refresh widget (curated 5-task dropdown + confirm prompt) posting to /action/refresh"
  - "Status-poll JS (setInterval 5000ms) updating in-page badge from /api/status after refresh"
  - "Human-verified live round-trips: mark-placed/add-note persistence, refresh subprocess, concurrent-run refusal, no workbook corruption"
affects: [future-dashboard-features, v3.0-close]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "POST-redirect-render with flask.flash for all action outcomes"
    - "Jinja2 autoescaping enforced (no safe filter on workbook-derived data or note text)"
    - "Light vanilla-JS setInterval poller for async task status — no build toolchain"
    - "Confirm-gate (browser confirm()) on destructive/expensive action only (refresh); inline forms apply without confirm"

key-files:
  created: []
  modified:
    - scripts/templates/base.html
    - scripts/templates/slips.html

key-decisions:
  - "Refresh is the ONLY action that requires a confirm prompt (D-05); mark-placed and add-note apply inline"
  - "XSS rule from Phase 2 preserved: all workbook-derived data and operator note text use Jinja2 autoescaping (no safe filter)"
  - "Status poller uses setInterval(5000) with /api/status?task=<t>; active only on this page after a refresh is triggered"
  - "ALLOWED_TASKS dropdown is the five curated tasks (D-01): nba_daily_picks, mlb_daily_picks, check_results, nba_prop_monitor, mlb_prop_monitor"

patterns-established:
  - "Flash block pattern: {% with messages = get_flashed_messages(with_categories=true) %} loop in base.html; color by category (success=green, error=red, warning=amber)"
  - "Slip action forms carry hidden date + slip_id inputs; toggled placed value derived from current state"

requirements-completed: [ACTION-01, ACTION-02, ACTION-03]

# Metrics
duration: "~15 min (Task 1 automated; Task 2 human-verify approved by operator)"
completed: 2026-06-24
---

# Phase 3 Plan 04: UI — Flash Banner, Slip Action Forms, Refresh Widget Summary

**Flash banner (base.html) + per-slip Mark Placed / Add Note forms + Refresh widget with /api/status poll (slips.html), operator-verified for live subprocess and persistence round-trips**

## Performance

- **Duration:** ~15 min (Task 1 code; Task 2 human checkpoint)
- **Started:** 2026-06-24
- **Completed:** 2026-06-24
- **Tasks:** 2 (1 auto, 1 human-verify — both complete)
- **Files modified:** 2

## Accomplishments

- Added flash message block to `base.html` immediately inside `<main>`, rendering `get_flashed_messages(with_categories=true)` with color-coded banners (success/error/warning) and Jinja2 autoescaping.
- Wired per-slip Mark Placed toggle and Add Note inline forms in `slips.html`; each carries hidden `date`/`slip_id` inputs and POSTs to `/action/mark-placed` and `/action/add-note` respectively; current persisted `Placed`, `Placed At`, and `Operator Note` values render on the detail row.
- Added Refresh widget (curated 5-task dropdown + `onsubmit confirm()`) and status-poll JS (`setInterval(5000)` against `/api/status?task=<t>`) in the `{% block scripts %}` section of `slips.html`.
- Operator confirmed all six live round-trips: mark-placed/add-note persist and toggle correctly, grading Notes column untouched, refresh subprocess fires and logs, concurrent run refused with flash, no workbook corruption.

## Task Commits

Each task was committed atomically:

1. **Task 1: Flash banner + slip action forms + refresh widget + status-poll JS** — `d9d6ce3` (feat)
2. **Task 2: Human-verify checkpoint** — Approved by operator (no code commit; live verification only)

**Plan metadata:** (committed below as docs commit)

## Files Created/Modified

- `scripts/templates/base.html` — Flash message block added inside `<main>`, above `{% block content %}`
- `scripts/templates/slips.html` — Mark Placed toggle form, Add Note inline form, Placed/Note state display, Refresh widget, status-poll JS

## Decisions Made

- Refresh is the only action behind a `confirm()` prompt per D-05; mark-placed and add-note apply immediately inline.
- Jinja2 autoescaping is preserved for all workbook-derived data and the operator note field (XSS rule from Phase 2; no `safe` filter used anywhere on those values).
- Status poller is activated on this page only after a refresh is triggered, polling `/api/status?task=<t>` every 5 seconds.

## Deviations from Plan

None — plan executed exactly as written.

## Issues Encountered

None. Task 1 automated tests passed on first run (`test_dashboard_views.py`, `test_dashboard.py`). Task 2 human checkpoint was approved by the operator with the message "it's working well."

## Human Verification Record

**Task 2 — Live round-trips (checkpoint:human-verify)** — APPROVED by operator 2026-06-24.

Operator confirmed all six checks:
1. Mark Placed toggle: flash appears, Placed state + Placed At timestamp persist after reload; toggling back clears them.
2. Add Note: flash appears, Operator Note persists after reload; grading Notes/payout/Net PnL unchanged.
3. Refresh widget: confirm() prompt appears on click; success flash shown; `data/pnl/logs/run_log.jsonl` has a fresh `check_results` record; status badge reflects completion.
4. Concurrent-run refusal: a second refresh during an in-progress run is refused with "run already in progress" flash and no second subprocess starts.
5. No workbook corruption: Slips and History pages load and show correct data after all actions.

## User Setup Required

None — no external service configuration required.

## Next Phase Readiness

Phase 3 (Safe Actions) is complete. All four plans executed and verified:
- 03-01: RED test scaffold (9 ACTION tests)
- 03-02: Write layer (mark_placed + add_note + last_run_record)
- 03-03: Flask routes (/action/refresh, /api/status, /action/mark-placed, /action/add-note)
- 03-04: UI (flash banner, action forms, refresh widget, human-verified)

The dashboard milestone (v3.0) is complete. All requirements ACTION-01 through ACTION-04 satisfied. No blockers for next milestone (M2 Model Accuracy & Calibration).

---
*Phase: 03-safe-actions*
*Completed: 2026-06-24*
