---
phase: 02-read-views
plan: 03
subsystem: dashboard-history-view
tags: [jinja-templates, view-layer, chart-js, tdd, dashboard, VIEW-03]
dependency_graph:
  requires: [02-01, 02-02]
  provides: [history.html, VIEW-03]
  affects: [scripts/templates/history.html]
tech_stack:
  added: [Chart.js 4.5.1 via CDN SRI-pinned]
  patterns: [sri-cdn-script, tojson-chart-serialization, tier-breakdown-table, daily-weekly-toggle]
key_files:
  created: [scripts/templates/history.html]
  modified: []
decisions:
  - "Chart.js CDN pinned to v4.5.1 with verified SHA-384 SRI hash and crossorigin=anonymous (T-02-05; RESEARCH Pitfall 11 locked spec)"
  - "UNKNOWN tier row always rendered, labeled 'UNKNOWN / pre-v2.0' to surface pre-confidence-tier historical picks (Pitfall 5, D-09)"
  - "Chart canvas wrapped in Jinja guard so empty-data state shows 'No chart data yet.' without a JS error (spanGaps:false, no canvas rendered)"
  - "tojson filter used for all four chart series (dailyLabels, dailyBankroll, weeklyLabels, weeklyBankroll) — zero | safe filters on any workbook value (T-02-01)"
metrics:
  duration_minutes: 8
  completed_date: "2026-06-24"
  tasks_completed: 1
  files_modified: 1
---

# Phase 02 Plan 03: History View (VIEW-03) Summary

`scripts/templates/history.html` ships the History page extending `base.html`, rendering the W/L overall + per-sport record table, the A/B/C/UNKNOWN confidence-tier breakdown, and the bankroll/ROI Chart.js line chart with daily/weekly toggle — all from the `get_history_data()` accessor delivered in Plan 01. This completes VIEW-03 and turns the previously-RED `test_history_200` smoke test GREEN.

## What Was Built

### `scripts/templates/history.html` — History page (VIEW-03)

New file extending `base.html`:

- **Locked guard**: `{% if data.locked %}` → "Data is updating…" warning in orange (D-01).

- **Overall + per-sport W/L table**: single `<table>` with rows for Overall, NBA, MLB. Reads `data.overall` and `data.by_sport["NBA"]` / `data.by_sport["MLB"]`. Hit % and ROI % rendered as `%.1f%%` of their fraction values; `—` when None.

- **Confidence tier breakdown table** (D-09): loops the fixed tier order `['A', 'B', 'C', 'UNKNOWN']`, each row reading `data.by_tier[tier]`. UNKNOWN tier rendered as "UNKNOWN / pre-v2.0" with a sub-heading note explaining pre-v2.0 picks. Never hidden (Pitfall 5). Shows W-L, Hit %, ROI %, n.

- **Bankroll chart section** (D-08): toggle buttons `id="toggle-daily"` and `id="toggle-weekly"` above a `<canvas id="bankroll-chart">`. Canvas is wrapped in `{% if data.chart_daily.labels %}` guard — shows "No chart data yet." when empty, preventing Chart.js initialization on a missing canvas element.

- **`{% block scripts %}`** — two script elements:
  1. Chart.js CDN `<script>` with pinned `chart.js@4.5.1` URL, `integrity="sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ"`, `crossorigin="anonymous"` (T-02-05, RESEARCH Pitfall 11).
  2. Initialization script: four `const` variables via `| tojson` filter (Pitfall 8 — None→null, special chars handled). Chart defaults to daily series. Toggle listeners swap `chart.data.labels` + `chart.data.datasets[0].data` and call `chart.update()`. Init block is also wrapped in `{% if data.chart_daily.labels %}` so it is not emitted when chart data is absent.

- **XSS mitigation (T-02-01)**: Jinja2 autoescaping active throughout. All `{{ }}` expressions are auto-escaped. `| tojson` used for JS serialization (not `| safe`). Grep confirms: `grep -c "| safe" scripts/templates/history.html` == 0.

## Verification Results

```
cd scripts && python3 -m pytest test_dashboard_views.py::TestRoutes::test_history_200 -x -q
1 passed in 3.10s
```

```
cd scripts && python3 -m pytest test_dashboard_views.py test_dashboard.py test_dashboard_data.py -x -q
22 passed in 226.80s
```

Acceptance criteria confirmed:
- `grep -c "bankroll-chart" scripts/templates/history.html` == 2
- `grep -c "sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ" scripts/templates/history.html` == 1
- `grep -c "chart.js@4.5.1" scripts/templates/history.html` == 1
- `grep -c "crossorigin" scripts/templates/history.html` == 1
- `grep -c "by_tier" scripts/templates/history.html` == 1
- `grep -c "UNKNOWN" scripts/templates/history.html` == 4
- `grep -c "tojson" scripts/templates/history.html` == 5
- `grep -c "| safe" scripts/templates/history.html` == 0

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None. The History page fully wires all four data paths from `get_history_data()`:
- `data.overall` → Overall row
- `data.by_sport` → NBA/MLB rows
- `data.by_tier` → A/B/C/UNKNOWN rows
- `data.chart_daily` / `data.chart_weekly` → Chart.js line chart

## Threat Flags

None. Mitigations from the threat register implemented:

- **T-02-05** (CDN tampering): `integrity="sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ"` + `crossorigin="anonymous"` — browser will refuse a tampered CDN file. Hash confirmed by grep == 1.
- **T-02-01** (workbook content → XSS): Jinja2 autoescaping on all `{{ }}` expressions; `| tojson` for chart series; zero `| safe` filters (confirmed by grep).
- **T-02-03** (information disclosure): `/history` is GET-only, no user input, `HOST=127.0.0.1` unchanged.
- **T-02-SC** (package installs): No new Python packages. Chart.js is CDN-loaded only.

## Self-Check: PASSED

Files created:
- `scripts/templates/history.html` — FOUND (150 lines)

Commit:
- `7a3b78d` — feat(02-03): build History page template with W/L tables and Chart.js bankroll chart — FOUND
