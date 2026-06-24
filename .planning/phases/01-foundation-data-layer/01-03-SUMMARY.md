---
phase: 01-foundation-data-layer
plan: 03
subsystem: ui
tags: [flask, jinja2, pico-css, dashboard, python]

requires:
  - phase: 01-foundation-data-layer/01-02
    provides: "dashboard_data.write_in_progress() and last_updated_hhmm() read-layer signals"
provides:
  - "scripts/dashboard.py — Flask app (app, HOST) with loopback-only launch and index route"
  - "scripts/templates/base.html — dark Pico.css shell, nav with deferred stub tabs, badge/last-updated slots"
  - "scripts/templates/index.html — Phase-1 landing extending base.html"
  - "DASH-01 and DASH-03 satisfied; all three test_dashboard tests green"
affects: [02-read-views, 03-safe-actions]

tech-stack:
  added: [Flask 3.1.3, Jinja2 3.1.6, Pico.css v2 CDN]
  patterns:
    - "HOST = '127.0.0.1' module constant encodes DASH-03 loopback security boundary"
    - "Fresh-per-request render_template with no long-lived cache (D-03)"
    - "threading.Timer(1.0) deferred browser auto-open after server ready (D-04)"
    - "OSError Errno 48/98 fail-fast with --port hint instead of silent 0.0.0.0 fallback"

key-files:
  created:
    - scripts/dashboard.py
    - scripts/templates/base.html
    - scripts/templates/index.html
  modified: []

key-decisions:
  - "PORT CONFLICT POLICY: fail-fast with clear error + --port hint; never fall back to 0.0.0.0 (would violate DASH-03)"
  - "use_reloader=False and debug=False to prevent Werkzeug reloader child double-opening the browser (Pitfall 5)"
  - "Jinja2 autoescape left at default ON; no | safe filter used anywhere in templates (T-1-05 XSS mitigation)"

patterns-established:
  - "Loopback bind: HOST constant used in app.run(host=HOST) — single source of truth, grep-assertable"
  - "Template freshness: write_in_progress + last_updated passed fresh per request, no cache"
  - "Deferred stub tabs: aria-disabled + hash href marks TAB-01/02/03 as reserved without building them"

requirements-completed: [DASH-01, DASH-03]

duration: 2min
completed: 2026-06-24
---

# Phase 1 Plan 03: Dashboard Flask Shell Summary

**Dark Pico.css Flask shell bound to 127.0.0.1:8787 with auto-open browser, freshness badge from the read layer, and inert stub tabs reserving Calibration/Line-changes/Live for future milestones.**

## Performance

- **Duration:** ~2 min
- **Started:** 2026-06-24T04:45:57Z
- **Completed:** 2026-06-24T04:47:41Z
- **Tasks:** 2
- **Files modified:** 3 (all created)

## Accomplishments

- Flask app shell with `HOST = "127.0.0.1"` and `app = Flask(__name__)` exposed at module level (test_loopback_only and test_route_index both green).
- Index route reads `write_in_progress()` and `last_updated_hhmm()` from `dashboard_data` fresh on every request and passes them to `render_template` (D-01/D-02/D-03).
- Dark Pico.css shell (`data-theme="dark"`) with dense-table CSS, nav links for Today/Slips/History, inert stub tabs for Calibration/Line-changes/Live (TAB-01/02/03 deferred), and reserved `{% block scripts %}` for Phase-2 Chart.js — all in one CDN-linked `base.html`.

## Task Commits

1. **Task 1: Dark Pico.css shell templates** — `3b0de49` (feat)
2. **Task 2: Flask app + index route + loopback launch** — `1c6065b` (feat)

## Files Created/Modified

- `scripts/dashboard.py` (116 lines) — Flask `app`, `HOST = "127.0.0.1"`, index route, `_port()`, `main()` with argparse + webbrowser auto-open
- `scripts/templates/base.html` (75 lines) — Pico.css dark shell, nav, badge/last-updated slots, deferred stub tabs, content + scripts blocks
- `scripts/templates/index.html` (11 lines) — extends base.html with Phase-1 placeholder content

## Decisions Made

- **Port-conflict policy:** fail-fast on OSError Errno 48/98 with a message naming the port and the `--port` / `DASHBOARD_PORT` override. Never silently fall back to `0.0.0.0` (would violate DASH-03). Predictable URL is essential for a solo local tool.
- **`use_reloader=False`, `debug=False`:** Prevents Werkzeug reloader child from double-binding the port and double-launching the browser (Pitfall 5 from RESEARCH).
- **No `| safe` filter** in any template: Jinja2 autoescape stays ON to prevent stored-XSS from workbook string fields (T-1-05).

## Deviations from Plan

None — plan executed exactly as written. All acceptance criteria met on the first attempt.

## Issues Encountered

None.

## User Setup Required

None — no external service configuration required. `python3 dashboard.py` runs from `scripts/` with no additional setup.

## Next Phase Readiness

- Phase 2 (Read Views) can inherit `base.html`'s `{% block content %}` and `{% block scripts %}` blocks for Today/Slips/History data tables and the bankroll Chart.js chart.
- `dashboard_data.read_json`, `read_sheet_rows`, and `today_str` are available for Phase-2 view functions to consume.
- The three inert stub tabs (Calibration/Line-changes/Live) reserve space in the nav for milestones M2–M4 without blocking Phase 2.

## Self-Check

- [x] `scripts/dashboard.py` exists (116 lines, > 50 min)
- [x] `scripts/templates/base.html` exists (75 lines, > 30 min), contains `data-theme`, Pico CDN link, `write_in_progress`, `last_updated`, `{% block content %}`, `{% block scripts %}`, Calibration/Line-changes/Live stubs — no `| safe` filter
- [x] `scripts/templates/index.html` exists, extends base.html
- [x] Commits `3b0de49` and `1c6065b` confirmed in git log
- [x] `cd scripts && python3 -m unittest test_dashboard` → 3 passed, 0 failed

---
*Phase: 01-foundation-data-layer*
*Completed: 2026-06-24*
