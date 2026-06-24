---
phase: 02-read-views
plan: 02
subsystem: dashboard-routes-and-views
tags: [flask-routes, jinja-templates, view-layer, tdd, dashboard, VIEW-01, VIEW-02]
dependency_graph:
  requires: [02-01]
  provides: [index-route, slips-route, history-route, _freshness_context, index.html, slips.html]
  affects: [scripts/dashboard.py, scripts/templates/index.html, scripts/templates/slips.html, scripts/test_dashboard_views.py]
tech_stack:
  added: []
  patterns: [freshness-context-helper, client-side-sort-filter, expandable-rows, date-grouping-namespace-loop, ev-descending-default-sort]
key_files:
  created: [scripts/templates/slips.html]
  modified: [scripts/dashboard.py, scripts/templates/index.html, scripts/test_dashboard_views.py]
decisions:
  - "_freshness_context() helper added before the routes to DRY the write_in_progress + last_updated context pair required by all base.html nav badges (Pitfall 9 guard)"
  - "Client-side vanilla JS for sort/filter (per RESEARCH Open Question 2 — dataset is small, no build toolchain)"
  - "textContent used for triangle marker rotation in toggleSlip (not innerHTML) to avoid any innerHTML risk even with static string values"
  - "skipped rows use row['What Edge Would Have Been'] for Edge and row.prob_float for Model Prob (set by the accessor), matching the Skipped Picks column contract"
  - "Jinja namespace loop (ns = namespace(current_date=None)) used for date-group headings in slips.html — required for Jinja2 scope rules"
  - "history.html route defined here (Plan 02) per plan spec so dashboard.py has a single owner; template ships in Plan 03"
metrics:
  duration_minutes: 25
  completed_date: "2026-06-24"
  tasks_completed: 3
  files_modified: 4
---

# Phase 02 Plan 02: Routes + Views (VIEW-01, VIEW-02) Summary

Three GET routes wired in `dashboard.py` behind a shared `_freshness_context()` helper, delivering the Today master table (`index.html`) and the Slips grouped-expandable list (`slips.html`). VIEW-01 and VIEW-02 are complete. The `/history` route is defined here but its template ships in Plan 03.

## What Was Built

### `scripts/dashboard.py` — `_freshness_context` helper + three routes

**`_freshness_context() -> dict[str, object]`** added before the route block:
- Returns `{"write_in_progress": ..., "last_updated": ...}` from `dashboard_data`
- Called with `**_freshness_context()` by every route handler
- Eliminates repeated freshness calls and prevents `UndefinedError` on `{% if write_in_progress %}` in `base.html` (Pitfall 9)

**`index()` route** (replaced existing stub):
- Calls `dashboard_data.get_today_board()`
- Renders `index.html` with `board=board, **_freshness_context()`

**`slips()` route** (new, `/slips`):
- Calls `dashboard_data.get_all_slips()`
- Renders `slips.html` with `data=data, **_freshness_context()`

**`history()` route** (new, `/history`):
- Calls `dashboard_data.get_history_data()`
- Renders `history.html` with `data=data, **_freshness_context()`
- Template ships in Plan 03; route defined here so `dashboard.py` has a single owner

`HOST = "127.0.0.1"` unchanged (DASH-03 preserved).

### `scripts/templates/index.html` — Today master table (VIEW-01)

Replaced the Phase-1 placeholder stub body while keeping `{% extends "base.html" %}`:

- **Filter bar**: three `<select>` elements (Platform, Sport, Status) populated from `data-*` attributes via JS on load; `onchange="applyFilters()"` triggers row show/hide
- **`<table id="today-table">`**: sortable column headers (`onclick="sortTable(col)"`); columns: Status, Sport, Platform, Pick, EV, Model Prob, Edge, Confidence (D-03)
- **Approved rows**: loop over `board.approved`; `data-platform`, `data-sport`, `data-status="approved"`, `data-ev` attributes; EV rendered as `%.1f%%` of `ev_float * 100` or `—`; Model Prob as `%.0f%%`
- **Skipped rows**: loop over `board.skipped`; `class="skipped-row"` (opacity 0.55); Status cell shows `row.status_label` (e.g. `"Skip: MINIMUM EDGE"`)
- **Empty state**: `"No evaluated picks for {{ board.date }} — the pipeline may not have run yet."`
- **Locked guard**: `"Data is updating…"` badge when `board.locked`
- **`_populateFilters()`**: runs on `DOMContentLoaded`, reads all `data-platform` / `data-sport` values from rows and fills the filter `<select>` options dynamically
- **`applyFilters()`**: sets `display:none` on filter-mismatch rows
- **`sortTable(col)`**: sorts tbody rows by `data-ev` (numeric, NaN sinks), `data-prob`, `data-edge`, or text attributes; toggles direction on re-click
- **Default sort**: `sortTable('ev')` on `DOMContentLoaded` → EV descending (D-03)
- **XSS**: no `| safe` filter on any workbook-sourced value (T-02-01 — confirmed by `grep -c "| safe" == 0`)

### `scripts/templates/slips.html` — Slips page (VIEW-02)

New file extending `base.html`:

- **Date filter**: server-rendered `<select>` of unique dates from `data.slips` via Jinja `map | unique`; `filterSlips()` JS hides/shows `.slip-table` and `.slip-date-heading` by `data-date` attribute
- **Date-grouped display** (D-05): `{% set ns = namespace(current_date=None) %}` loop emits `<h3>` date headings on date change; data is already Date-descending from the accessor
- **Summary row** (`class="slip-summary"`, `onclick="toggleSlip(this)"`): shows Date, Slip Result, Slip Type, Number of Legs, Standard Payout Multiplier (or `n/a`), triangle marker
- **Detail row** (`class="slip-detail"`, `display:none` by default): reveals legs (`ul` loop over `slip.legs_list`), "Why paired:" (`slip.why_paired`), Net PnL with color coding (D-06, D-07)
- **`toggleSlip(summaryRow)`**: toggles `detailRow.style.display`; rotates marker using `textContent` (not `innerHTML`)
- **Empty state**: Jinja `{% else %}` on the for-loop → `"No slips recorded yet."`
- **XSS**: no `| safe` filter on any workbook-sourced value (T-02-01 — confirmed by `grep -c "| safe" == 0`)

### `scripts/test_dashboard_views.py` — TestRoutes class appended

**`TestRoutes`** (3 tests) appended after existing 11 accessor tests:
- `setUp`: `self.client = dashboard.app.test_client()`
- `test_index_200`: GET `/` → 200 + `b"EV"` in body
- `test_slips_200`: GET `/slips` → 200
- `test_history_200`: GET `/history` → 200 + `b"chart.js"` in lowercased body (RED until Plan 03 ships history.html — acceptable Wave-2 state)

## Verification Results

```
python3 -m pytest test_dashboard_views.py::TestRoutes::test_index_200 test_dashboard_views.py::TestRoutes::test_slips_200 -x -q
2 passed in 188s
```

```
python3 -m pytest test_dashboard.py test_dashboard_data.py -x -q
8 passed in 8.24s  (Phase 1 suite — no regressions)
```

Acceptance criteria confirmed:
- `grep -n "def _freshness_context" scripts/dashboard.py` → line 51
- `grep -n "/slips\|/history" scripts/dashboard.py` → lines 79, 90
- `grep -n "127.0.0.1" scripts/dashboard.py` → present (DASH-03 intact)
- `grep -c "today-table" scripts/templates/index.html` → 2
- `grep -c "applyFilters" scripts/templates/index.html` → 4
- `grep -c "board.approved" scripts/templates/index.html` → 2
- `grep -c "board.skipped" scripts/templates/index.html` → 2
- `grep -c "skipped-row" scripts/templates/index.html` → 2
- `grep -c "| safe" scripts/templates/index.html` → 0
- `grep -c "slip-summary" scripts/templates/slips.html` → 1
- `grep -c "toggleSlip" scripts/templates/slips.html` → 2
- `grep -c "legs_list" scripts/templates/slips.html` → 2
- `grep -c "why_paired" scripts/templates/slips.html` → 1
- `grep -c "namespace" scripts/templates/slips.html` → 2
- `grep -c "| safe" scripts/templates/slips.html` → 0

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Security] Used textContent instead of innerHTML for triangle marker rotation**
- **Found during:** Task 3 implementation (triggered by security plugin warning)
- **Issue:** Initial implementation used `marker.innerHTML = '&#9660;'` to rotate the triangle marker in `toggleSlip`. While the string was a hardcoded HTML entity (not workbook data), using `innerHTML` is unnecessary when `textContent` achieves the same result.
- **Fix:** Changed to `marker.textContent = '▼'` / `marker.textContent = '►'` — eliminates any `innerHTML` usage in JS, fully consistent with T-02-01 spirit.
- **Files modified:** `scripts/templates/slips.html`
- **Commit:** 611b2b7

## Known Stubs

`test_history_200` in `TestRoutes` will remain RED until Plan 03 ships `history.html`. This is an accepted Wave-2 state documented in the plan (`test_history_200` behavior block: "RED if run before Plan 03 — acceptable").

The `/history` route is defined and functional; the template (`history.html`) is not yet created — accessing `/history` in a browser will return a 500 (TemplateNotFound) until Plan 03.

## Threat Flags

None. Mitigations from the threat register implemented:

- **T-02-01** (workbook content → HTML): Jinja autoescaping active; zero `| safe` filters on any workbook-sourced template variable (confirmed by grep). `textContent` used in JS instead of `innerHTML`.
- **T-02-03** (information disclosure): `HOST = "127.0.0.1"` unchanged. All routes GET-only with no user input to accessors.
- **T-02-04** (path traversal): `get_today_board()`, `get_all_slips()`, `get_history_data()` derive paths from `today_str()` and hardcoded constants — zero query params or user input reach these calls.
- **T-02-SC** (package installs): no new packages installed.

## Self-Check: PASSED

Files created/modified:
- `scripts/dashboard.py` — FOUND (modified: `_freshness_context` at line 51, `/slips` at line 79, `/history` at line 90 confirmed)
- `scripts/templates/index.html` — FOUND (modified: `today-table` id present, `board.approved` loop present)
- `scripts/templates/slips.html` — FOUND (created: `slip-summary`, `toggleSlip`, `legs_list`, `why_paired`, `namespace` all present)
- `scripts/test_dashboard_views.py` — FOUND (modified: `TestRoutes` class at end of file)

Commits:
- `4868b36` — test(02-02): add failing TestRoutes class to test_dashboard_views.py — FOUND
- `611b2b7` — feat(02-02): wire routes + _freshness_context; build Today and Slips views — FOUND
