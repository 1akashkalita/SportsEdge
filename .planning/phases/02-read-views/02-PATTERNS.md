# Phase 2: Read Views - Pattern Map

**Mapped:** 2026-06-24
**Files analyzed:** 5 files to create or modify
**Analogs found:** 5 / 5 — all Phase 2 files have close analogs in the repo (primarily Phase 1's own files)

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `scripts/dashboard_data.py` (MODIFY — add 3 accessors) | service (read layer) | file-I/O, transform | `scripts/dashboard_data.py` itself (`read_sheet_rows`, `read_json`) | exact — new accessors are view-shaped wrappers over the same primitives |
| `scripts/dashboard.py` (MODIFY — add 3 routes + `_freshness_context`) | controller | request-response | `scripts/dashboard.py` existing `index()` route (lines 51–64) | exact — same Flask route + `render_template` shape, same freshness context pattern |
| `scripts/templates/today.html` (CREATE — replace index.html stub) | component (view) | request-response | `scripts/templates/index.html` (lines 1–11) + `scripts/templates/base.html` | exact — same `{% extends "base.html" %}` + `{% block content %}` pattern; index.html is today.html's direct predecessor |
| `scripts/templates/slips.html` (CREATE) | component (view) | request-response | `scripts/templates/base.html` shell; expandable-row pattern is new but within base.html | role-match — same extends/block pattern; JS expand mechanism is net-new within the shell |
| `scripts/templates/history.html` (CREATE) | component (view) | request-response | `scripts/templates/base.html` shell; `{% block scripts %}` CDN slot (line 72) | role-match — same extends/block pattern; Chart.js CDN block is the only net-new element |
| `scripts/test_dashboard_views.py` (CREATE) | test | file-I/O + request-response | `scripts/test_dashboard_data.py` (in-memory workbook fixtures, `_make_picks_wb`) + `scripts/test_dashboard.py` (`app.test_client()` route smokes) | exact |

---

## Pattern Assignments

### `scripts/dashboard_data.py` — three new view accessors (MODIFY)

**Analog:** `scripts/dashboard_data.py` — the existing `read_sheet_rows` and `read_json` functions are the only primitives these accessors call. Every new accessor must mirror the same lock-tolerant, never-raise contract.

**Existing imports block** (lines 16–26) — add nothing new; all needed stdlib is already imported:
```python
# dashboard_data.py lines 16–26 (already present — do not duplicate)
from __future__ import annotations
import json
import os
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from workbook_io import WorkbookAccessError, safe_load_workbook  # noqa: F401
```

**Existing path constants** (lines 32–38) — the three new accessors consume `NBA_DIR`, `MLB_DIR`, and `DATA`; note `PNL_DIR` does NOT exist yet and must be added:
```python
# dashboard_data.py lines 32–38 (already present)
HOME: Path = Path.home()
ROOT: Path = HOME / "sports_picks"
DATA: Path = ROOT / "data"
NBA_DIR: Path = DATA / "nba"
MLB_DIR: Path = DATA / "mlb"
LOCK_DIR: Path = ROOT / "locks"
RUN_LOG_JSONL: Path = DATA / "pnl" / "logs" / "run_log.jsonl"
# ADD BELOW — PNL_DIR needed by get_all_slips and get_history_data:
# PNL_DIR: Path = DATA / "pnl"
```

**Core lock-tolerant read pattern** (lines 87–144) — every new accessor calls `read_sheet_rows` and handles `None` the same way. This is the pattern to replicate at the accessor level:
```python
# dashboard_data.py lines 107–137 — the exact guard/fallback pattern
wb = None
try:
    wb = safe_load_workbook(Path(xlsx), read_only=True, data_only=True)
    if sheet not in wb.sheetnames:
        return []
    ws = wb[sheet]
    rows_iter = ws.iter_rows(values_only=True)
    try:
        headers = next(rows_iter)
    except StopIteration:
        return []
    if headers is None:
        return []
    result: list[dict[str, Any]] = []
    for row in rows_iter:
        if row is None:
            continue
        result.append(dict(zip(headers, row)))
    return result
except (WorkbookAccessError, FileNotFoundError, OSError, zipfile.BadZipFile):
    return None        # ← None means "locked" → serve last-known-good (D-01)
finally:
    if wb is not None and hasattr(wb, "close"):
        try:
            wb.close()
        except Exception:
            pass
```

**How new accessors use `read_sheet_rows`** — the function already returns `None` for locked workbooks. Accessors propagate `locked=True` in the returned dict without re-reading:
```python
# Pattern for get_today_board() and all three new accessors:
def get_today_board(date: str | None = None) -> dict[str, list[dict[str, Any]]]:
    today = date or today_str()
    locked = False

    nba_path = NBA_DIR / f"nba_{today}.xlsx"
    picks_nba = read_sheet_rows(nba_path, "Picks")
    if picks_nba is None:
        locked = True
        picks_nba = []

    # ... same for mlb_path, "Skipped Picks" ...

    return {"approved": [...], "skipped": [...], "date": today, "locked": locked}
```

**EV coercion pattern** (Pitfall 2 from RESEARCH.md) — apply in `get_today_board` when building each skipped row dict:
```python
# In the accessor — not in the template or route
ev_raw = row.get("EV")
ev_float: float | None = None
try:
    if ev_raw not in (None, "", "unavailable"):
        ev_float = float(ev_raw)
except (ValueError, TypeError):
    pass
row["ev_float"] = ev_float

# Same pattern for "Probability" field in Skipped Picks
```

**Status label computation** (D-04) — done in the accessor, not the template:
```python
# Approved picks (from Picks sheet)
row["status_label"] = "✓ Approved"

# Skipped picks (from Skipped Picks sheet)
gate_raw = row.get("Gate Failed") or ""
# Gate Failed format: "GATE N — HUMAN GATE NAME"
# Strip the numeric prefix, keep the human name
if " — " in gate_raw:
    gate_name = gate_raw.split(" — ", 1)[1]
else:
    gate_name = gate_raw
row["status_label"] = f"Skip: {gate_name}"
```

**ISO-week aggregation for `get_history_data`** (D-08 weekly chart toggle, RESEARCH Pattern):
```python
# In get_history_data() — aggregate Bankroll Chart Data by ISO week
from datetime import date as date_cls  # stdlib only, no new deps

weekly: dict[str, dict] = {}
for row in chart_rows:
    d_str = str(row.get("Date") or "")
    try:
        iso = date_cls.fromisoformat(d_str).isocalendar()
        week_key = f"{iso.year}-W{iso.week:02d}"  # "2026-W24" format per metrics_report convention
    except (ValueError, TypeError):
        continue
    weekly[week_key] = row   # last row in the week wins (overwrite = last point)

labels_w = sorted(weekly.keys())
bankroll_w = [weekly[k].get("Bankroll") for k in labels_w]
```

**Legs list split for `get_all_slips`** (Pitfall 4):
```python
# In get_all_slips() accessor — split legs string before returning
slip["legs_list"] = [
    leg for leg in str(slip.get("Legs") or "").split("; ")
    if leg.strip()
]
```

**"Why paired" derivation** (D-07 two-tier, Tier-2 is the normal path):
```python
# Tier-2 derived mapping (hardcoded in accessor) — Tier-1 join first, fall through on no-match
_WHY_PAIRED = {
    "correlated_upside": "Correlated upside pair — same team, high-confidence",
    "diversified":       "Diversified portfolio — avoids same-player overlap",
    "highest_ev":        "Highest EV combination — top expected value legs",
    "safest_2_leg":      "Safest 2-leg — highest model probability, positive EV",
    "safest_3_leg":      "Safest 3-leg — three high-probability independent legs",
    "kat_based":         "KAT anchor stack — correlated same-player props allowed",
}

def _derive_why_paired(slip_id: str) -> str:
    parts = str(slip_id or "").split(":")
    category = parts[1] if len(parts) >= 2 else ""
    return _WHY_PAIRED.get(category, "Independent legs / no correlation flagged")
```

**Column contract references** (never use `data/nxls_schema.txt` — use these constants):
- `PICKS_HEADERS` — `sports_system_runner.py:277–283` (confirmed: includes `Model Over Probability`, `EV`, `Edge`, `Confidence`, `Platform`, `Player/Team`, `Selection`, `Status`, `Injury Flag`)
- `SKIPPED_PICK_HEADERS` — `sports_system_runner.py:295` (confirmed: `Gate Failed`, `Reason`, `What Edge Would Have Been`, `Probability`, `EV`, `Platform`, `Pick`, `Player/Team`, `Pick Type`, `Line`)
- `PARLAY_HEADERS` — `sports_system_runner.py:294` (confirmed: `Reasoning`, `Correlation Group`, `Slip ID`)
- `SLIP_HISTORY_HEADERS` — `slip_payouts.py:18–24` (confirmed: `Slip ID`, `Date`, `Platform`, `Slip Type`, `Number of Legs`, `Legs`, `Slip Result`, `Standard Payout Multiplier`, `Net PnL`, `Gross Return`, `Winning Legs`, `Losing Legs`, `Contains Demon`, `Contains Goblin`, `Notes`)

---

### `scripts/dashboard.py` — three new routes + `_freshness_context` helper (MODIFY)

**Analog:** `scripts/dashboard.py` — the existing `index()` route (lines 51–64) is the exact pattern for all three new routes.

**Existing route pattern to copy** (lines 51–64):
```python
# dashboard.py lines 51–64 — copy this shape for /slips and /history
@app.route("/")
def index() -> str:
    """Render the Phase-1 shell with live freshness signals (D-01/D-02/D-03).

    Freshness context is computed fresh on every request (D-03 — no long-lived
    cache). Values come from the Phase-1 read layer (dashboard_data):
        write_in_progress — drives the "updating…" badge (D-01)
        last_updated      — HH:MM label from the last pipeline run (D-02)
    """
    return render_template(
        "index.html",
        write_in_progress=dashboard_data.write_in_progress(),
        last_updated=dashboard_data.last_updated_hhmm(),
    )
```

**`_freshness_context` helper to add** (open question 2 from RESEARCH.md — use this DRY pattern):
```python
# Add to dashboard.py before the routes — eliminates repeated freshness calls
def _freshness_context() -> dict[str, object]:
    """Return freshness context vars required by base.html nav (D-01/D-02).

    Called by every route handler. Passing these to render_template is mandatory
    for all templates that extend base.html — omitting them causes an
    UndefinedError on the {% if write_in_progress %} check (Pitfall 9).
    """
    return {
        "write_in_progress": dashboard_data.write_in_progress(),
        "last_updated": dashboard_data.last_updated_hhmm(),
    }
```

**Three new routes — shape mirrors existing `index()`**:
```python
@app.route("/")
def index() -> str:
    board = dashboard_data.get_today_board()
    return render_template("index.html", board=board, **_freshness_context())

@app.route("/slips")
def slips() -> str:
    data = dashboard_data.get_all_slips()
    return render_template("slips.html", data=data, **_freshness_context())

@app.route("/history")
def history() -> str:
    data = dashboard_data.get_history_data()
    return render_template("history.html", data=data, **_freshness_context())
```

**Import block** (lines 14–22) — add `dashboard_data` accessor calls; no new imports needed. The `render_template` import already exists:
```python
# dashboard.py lines 14–22 (already present — no new imports required for Phase 2)
from __future__ import annotations
import argparse
import os
import threading
import webbrowser
import dashboard_data
from flask import Flask, render_template
```

**Security constraint** (lines 27, 96) — `HOST = "127.0.0.1"` never changes. All new routes are GET-only with no user input, so no new attack surface. Jinja autoescaping is on by default — never use `| safe` on workbook data.

---

### `scripts/templates/today.html` (CREATE — replaces the index.html stub)

**Analog:** `scripts/templates/index.html` (lines 1–11) and `scripts/templates/base.html`.

**Base extends pattern** (index.html lines 1–11) — copy exactly:
```html
{% extends "base.html" %}

{% block title %}Today — Hermes Sports Dashboard{% endblock %}

{% block content %}
<!-- Today board content here -->
{% endblock %}
```

**Nav active-link pattern** — add `class="nav-active"` to the `Today` anchor in `base.html`'s nav OR inject a `page` context var from the route. Simplest: pass `page="today"` from the route and check `{% if page == 'today' %}class="nav-active"{% endif %}` on the `<a href="/">Today</a>` tag in base.html. Alternatively, override with an inline CSS class in the template. Either approach is within discretion.

**Table structure** (D-03 dense sortable master table):
```html
<!-- In {% block content %} -->
<!-- Filter bar (client-side) — data-attributes drive the JS -->
<div style="display:flex; gap:0.5rem; margin-bottom:0.5rem;">
  <select id="filter-platform" onchange="applyFilters()"><option value="">All Platforms</option></select>
  <select id="filter-sport" onchange="applyFilters()"><option value="">All Sports</option></select>
  <select id="filter-status" onchange="applyFilters()">
    <option value="">All</option><option value="approved">Approved</option><option value="skipped">Skipped</option>
  </select>
</div>

<table id="today-table">
  <thead>
    <tr>
      <th onclick="sortTable('status')">Status</th>
      <th onclick="sortTable('sport')">Sport</th>
      <th onclick="sortTable('platform')">Platform</th>
      <th>Pick</th>
      <th onclick="sortTable('ev_float')">EV ▼</th>
      <th onclick="sortTable('prob')">Model Prob</th>
      <th onclick="sortTable('edge')">Edge</th>
      <th onclick="sortTable('confidence')">Confidence</th>
    </tr>
  </thead>
  <tbody>
    {% for row in board.approved %}
    <tr data-platform="{{ row.Platform | e }}"
        data-sport="{{ row.Sport | e }}"
        data-status="approved"
        data-ev="{{ row.ev_float if row.ev_float is not none else '' }}">
      <td>{{ row.status_label | e }}</td>
      <td>{{ row.Sport | e }}</td>
      <td>{{ row.Platform | e }}</td>
      <td>{{ row.Selection | e }}</td>
      <td>{{ "%.1f%%"|format(row.ev_float * 100) if row.ev_float is not none else "—" }}</td>
      <td>{{ "%.0f%%"|format(row["Model Over Probability"] * 100) if row["Model Over Probability"] else "—" }}</td>
      <td>{{ row.Edge | e }}</td>
      <td>{{ row.Confidence | e }}</td>
    </tr>
    {% endfor %}
    {% for row in board.skipped %}
    <tr class="skipped-row"
        data-platform="{{ row.Platform | e }}"
        data-sport="{{ row.Sport | e }}"
        data-status="skipped"
        data-ev="{{ row.ev_float if row.ev_float is not none else '' }}">
      <td>{{ row.status_label | e }}</td>
      <!-- remaining cells same pattern -->
    </tr>
    {% endfor %}
  </tbody>
</table>
```

**Skipped-row CSS** — add one rule inside `<style>` or inline in the template (base.html already has a `<style>` block at lines 9–37 to append to):
```css
.skipped-row { opacity: 0.55; }
```

**Empty state** (RESEARCH.md empty-state table):
```html
{% if not board.approved and not board.skipped %}
  <p>No evaluated picks for {{ board.date }} — the pipeline may not have run yet.</p>
{% endif %}
```

**Client-side sort/filter** — in `{% block scripts %}`:
```html
{% block scripts %}
<script>
// Sort: reads data-ev / data-prob / data-edge numeric attributes; toggles direction
// Filter: reads data-platform / data-sport / data-status; sets display:none when no match
// Default sort on load: EV descending (data-ev)
function applyFilters() { /* ~15 lines */ }
function sortTable(col) { /* ~20 lines */ }
document.addEventListener('DOMContentLoaded', function() { sortTable('ev'); });
</script>
{% endblock %}
```

**Jinja autoescaping rule:** All `{{ var }}` in templates is auto-escaped. Never use `| safe` on any workbook-originated string value.

---

### `scripts/templates/slips.html` (CREATE)

**Analog:** `scripts/templates/base.html` shell; expandable-row structure is net-new within the shell but follows the base pattern.

**Extends base** (same as all templates):
```html
{% extends "base.html" %}
{% block title %}Slips — Hermes Sports Dashboard{% endblock %}
{% block content %}
```

**Date-grouped expandable rows** (D-05/D-06 — grouped date descending, expand on click):
```html
{# Group slips by date in the template using a loop-and-check approach #}
{% set ns = namespace(current_date=None) %}
{% for slip in data.slips %}
  {% if slip.Date != ns.current_date %}
    {% set ns.current_date = slip.Date %}
    <h3>{{ slip.Date | e }}</h3>
  {% endif %}

  <!-- Summary row — compact, click to expand -->
  <table>
    <tbody>
      <tr class="slip-summary" onclick="toggleSlip(this)" style="cursor:pointer;">
        <td>{{ slip.Date | e }}</td>
        <td>{{ slip['Slip Result'] | e }}</td>
        <td>{{ slip['Slip Type'] | e }}</td>
        <td>{{ slip['Number of Legs'] }}</td>
        <td>{{ slip['Standard Payout Multiplier'] if slip['Standard Payout Multiplier'] else 'n/a' }}</td>
        <td>▶</td>
      </tr>
      <!-- Detail row — hidden by default -->
      <tr class="slip-detail" style="display:none;">
        <td colspan="6">
          <div>
            <strong>Legs:</strong>
            <ul>
              {% for leg in slip.legs_list %}
                <li>{{ leg | e }}</li>
              {% endfor %}
            </ul>
            <strong>Why paired:</strong> {{ slip.why_paired | e }}
            {% if slip['Net PnL'] is not none %}
              <br><strong>Net PnL:</strong> {{ slip['Net PnL'] }}u
            {% endif %}
          </div>
        </td>
      </tr>
    </tbody>
  </table>
{% else %}
  <p>No slips recorded yet.</p>
{% endfor %}
```

**Expand toggle JS** (in `{% block scripts %}`):
```html
{% block scripts %}
<script>
function toggleSlip(summaryRow) {
    var detailRow = summaryRow.nextElementSibling;
    if (detailRow && detailRow.classList.contains('slip-detail')) {
        detailRow.style.display = detailRow.style.display === 'none' ? '' : 'none';
    }
}
</script>
{% endblock %}
```

**Date filter** — a `<select>` of unique dates (populated in JS from data attributes) or server-rendered `<option>` values extracted by Jinja. Simplest server-rendered approach:
```html
{% set unique_dates = data.slips | map(attribute='Date') | unique | list %}
<select id="filter-date" onchange="filterSlips()">
  <option value="">All Dates</option>
  {% for d in unique_dates %}
    <option value="{{ d }}">{{ d }}</option>
  {% endfor %}
</select>
```

---

### `scripts/templates/history.html` (CREATE)

**Analog:** `scripts/templates/base.html` shell, specifically the `{% block scripts %}` slot (line 72) reserved for Chart.js.

**Extends base**:
```html
{% extends "base.html" %}
{% block title %}History — Hermes Sports Dashboard{% endblock %}
{% block content %}
```

**W/L summary tables** (D-09 — overall + per-sport + per-tier):
```html
<section>
  <h3>Overall</h3>
  <table>
    <thead><tr><th>W</th><th>L</th><th>Hit %</th><th>ROI %</th><th>n</th></tr></thead>
    <tbody>
      <tr>
        <td>{{ data.overall.W }}</td>
        <td>{{ data.overall.L }}</td>
        <td>{{ "%.1f%%"|format(data.overall.hit_pct * 100) if data.overall.hit_pct is not none else "—" }}</td>
        <td>{{ "%.1f%%"|format(data.overall.roi_pct * 100) if data.overall.roi_pct is not none else "—" }}</td>
        <td>{{ data.overall.n }}</td>
      </tr>
    </tbody>
  </table>
</section>

<section>
  <h3>Per Confidence Tier</h3>
  <table>
    <thead><tr><th>Tier</th><th>W-L</th><th>Hit %</th><th>ROI %</th><th>n</th></tr></thead>
    <tbody>
      {% for tier in ['A', 'B', 'C', 'UNKNOWN'] %}
        {% set t = data.by_tier[tier] %}
        <tr>
          <td>{{ tier }}</td>
          <td>{{ t.W }}-{{ t.L }}</td>
          <td>{{ "%.1f%%"|format(t.hit_pct * 100) if t.hit_pct is not none else "—" }}</td>
          <td>{{ "%.1f%%"|format(t.roi_pct * 100) if t.roi_pct is not none else "—" }}</td>
          <td>{{ t.n }}</td>
        </tr>
      {% endfor %}
    </tbody>
  </table>
</section>
```

**Chart.js in `{% block scripts %}`** (D-08 — daily default + weekly toggle):
```html
{% block scripts %}
<!-- Chart.js CDN — pinned to v4.5.1 with verified SRI hash (RESEARCH Pitfall 11) -->
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js"
        integrity="sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ"
        crossorigin="anonymous"></script>
<script>
  // Server serializes series as JSON — tojson handles None→null correctly (Pitfall 8)
  const dailyLabels   = {{ data.chart_daily.labels   | tojson }};
  const dailyBankroll = {{ data.chart_daily.bankroll  | tojson }};
  const weeklyLabels  = {{ data.chart_weekly.labels   | tojson }};
  const weeklyBankroll = {{ data.chart_weekly.bankroll | tojson }};

  const ctx = document.getElementById('bankroll-chart').getContext('2d');
  const chart = new Chart(ctx, {
      type: 'line',
      data: {
          labels: dailyLabels,
          datasets: [{ label: 'Bankroll', data: dailyBankroll, tension: 0.2 }]
      },
      options: { responsive: true, spanGaps: false }
  });

  // Toggle daily/weekly
  document.getElementById('toggle-weekly').addEventListener('click', function() {
      chart.data.labels = weeklyLabels;
      chart.data.datasets[0].data = weeklyBankroll;
      chart.update();
  });
  document.getElementById('toggle-daily').addEventListener('click', function() {
      chart.data.labels = dailyLabels;
      chart.data.datasets[0].data = dailyBankroll;
      chart.update();
  });
</script>
{% endblock %}
```

**Chart canvas + toggle buttons** (in `{% block content %}`):
```html
<section>
  <h3>Bankroll Over Time</h3>
  <button id="toggle-daily">Daily</button>
  <button id="toggle-weekly">Weekly</button>
  {% if data.chart_daily.labels %}
    <canvas id="bankroll-chart" style="max-height:300px;"></canvas>
  {% else %}
    <p>No chart data yet.</p>
  {% endif %}
</section>
```

**Empty state** — if `data.locked` is True and data is empty, show "Data is updating…" (the nav badge already shows this but explicit in-page text is the fallback).

---

### `scripts/test_dashboard_views.py` (CREATE)

**Analog A:** `scripts/test_dashboard_data.py` — provides the workbook fixture helper (`_make_picks_wb`, lines 48–56), the `sys.path` bootstrap (lines 31–33), the `TemporaryDirectory` + module-path-override pattern (lines 85–102 / 276–325), and `unittest.main()` (line 328–329).

**Analog B:** `scripts/test_dashboard.py` — provides the `app.test_client()` route smoke test shape (lines 87–103).

**Sys.path bootstrap** (test_dashboard_data.py lines 31–36) — copy exactly:
```python
#!/usr/bin/env python3
"""test_dashboard_views.py — VIEW-01/02/03 tests for Phase 2 view accessors and routes."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any

from openpyxl import Workbook

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import dashboard_data   # noqa: E402
import dashboard        # noqa: E402
```

**Workbook fixture helper pattern** (test_dashboard_data.py lines 48–56) — build synthetic sheets using the exact runner header constants:
```python
# Mirror _make_picks_wb but for each sheet needed by Phase 2 tests

def _make_picks_wb_with_data() -> Workbook:
    """Synthetic workbook with Picks and Skipped Picks sheets."""
    from scripts_constants import PICKS_HEADERS  # or inline the relevant subset
    wb = Workbook()
    ws = wb.active
    ws.title = "Picks"
    ws.append(["Date", "Sport", "Platform", "Selection", "Player/Team", "Pick Type",
               "Line", "Model Projection", "Edge", "Model Over Probability", "EV",
               "Confidence", "Status", "Injury Flag"])
    ws.append(["2026-06-24", "NBA", "PrizePicks", "LeBron James Over 25.5 Points",
               "LeBron James", "PROP", 25.5, 27.1, 1.5, 0.63, 0.12, "A", "APPROVED", None])

    ws2 = wb.create_sheet("Skipped Picks")
    ws2.append(["Date", "Sport", "Pick", "Gate Failed", "Reason", "What Edge Would Have Been",
                "Probability", "EV", "Pick Type", "Player/Team", "Line", "Platform"])
    ws2.append(["2026-06-24", "NBA", "LeBron James Under 8.5 Assists", "GATE 1 — MINIMUM EDGE",
                "Edge below threshold", 0.3, 0.48, "unavailable", "PROP", "LeBron James", 8.5, "PrizePicks"])
    return wb
```

**Module-path override pattern** (test_dashboard_data.py lines 94–101) — override `dashboard_data.NBA_DIR` and `MLB_DIR` to point at `TemporaryDirectory`:
```python
# In TestTodayBoard — same tmpdir + monkeypatch pattern
with tempfile.TemporaryDirectory() as tmpdir:
    wb = _make_picks_wb_with_data()
    xlsx_path = Path(tmpdir) / f"nba_{dashboard_data.today_str()}.xlsx"
    wb.save(xlsx_path)

    orig_nba = dashboard_data.NBA_DIR
    orig_mlb = dashboard_data.MLB_DIR
    try:
        dashboard_data.NBA_DIR = Path(tmpdir)
        dashboard_data.MLB_DIR = Path(tmpdir)  # empty — no MLB workbook in this test
        result = dashboard_data.get_today_board()
    finally:
        dashboard_data.NBA_DIR = orig_nba
        dashboard_data.MLB_DIR = orig_mlb
```

**Route smoke test pattern** (test_dashboard.py lines 87–103) — `app.test_client()` GET:
```python
class TestRoutes(unittest.TestCase):
    def setUp(self):
        self.client = dashboard.app.test_client()

    def test_index_200(self):
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"EV", resp.data)

    def test_slips_200(self):
        resp = self.client.get("/slips")
        self.assertEqual(resp.status_code, 200)

    def test_history_200(self):
        resp = self.client.get("/history")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"chart.js", resp.data.lower())
```

**`unittest.main()` footer** (test_dashboard_data.py lines 328–329) — always include:
```python
if __name__ == "__main__":
    unittest.main()
```

---

## Shared Patterns

### Lock-tolerant read / last-known-good (D-01)
**Source:** `scripts/dashboard_data.py` lines 107–144 (`read_sheet_rows` try/except/finally)
**Apply to:** ALL three new accessor functions in `dashboard_data.py`

Rules:
- Call `read_sheet_rows(path, sheet_name)` — never call `safe_load_workbook` directly from accessor bodies
- If `read_sheet_rows` returns `None` → set `locked=True`, use `[]` as the data fallback
- If `read_sheet_rows` returns `[]` → sheet absent or empty; not an error — serve empty state
- Include `locked: bool` in every accessor's returned dict so routes can pass it to templates

### Freshness context (D-01/D-02)
**Source:** `scripts/dashboard.py` lines 62–63 (existing `index()` call pattern)
**Apply to:** ALL three new route handlers in `dashboard.py`

Rule: every route extending `base.html` MUST pass `write_in_progress` and `last_updated` to `render_template` (Pitfall 9 from RESEARCH.md). Use `_freshness_context()` helper to avoid duplication.

### `today_str()` date semantics (D-02 / Pitfall 1 in RESEARCH.md)
**Source:** `scripts/dashboard_data.py` lines 51–57
**Apply to:** `get_today_board()` accessor; any other accessor that constructs a date-keyed workbook path

Rule: always call `dashboard_data.today_str()` — never `datetime.now(ZoneInfo(...))`. `test_today_matches_runner` is a standing regression guard; `dashboard_data.py` must never import `zoneinfo`.

### Portable paths (DEF-02)
**Source:** `scripts/dashboard_data.py` lines 32–38 (PATH constants anchored on `Path.home()`)
**Apply to:** `PNL_DIR` constant to add; `master_pnl.xlsx` path construction in `get_all_slips` and `get_history_data`

Rule: `PNL_DIR = DATA / "pnl"` — never hardcode `/Users/<name>/...`. `master_pnl.xlsx` path: `PNL_DIR / "master_pnl.xlsx"`.

### Test bootstrap (run from `scripts/`)
**Source:** `scripts/test_dashboard_data.py` lines 31–36 (sys.path insert) + line 328 (`unittest.main()`)
**Apply to:** `scripts/test_dashboard_views.py`

```python
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
```

### Jinja autoescaping (XSS prevention)
**Source:** Flask's default (`base.html` line 1 — `<!doctype html>` triggers Jinja2 HTML autoescaping)
**Apply to:** ALL new templates (`today.html`, `slips.html`, `history.html`)

Rule: `{{ var }}` is always HTML-escaped. Never use `{{ var | safe }}` on any workbook-sourced string (player names, selection text, reasoning strings). The `| tojson` filter in `{% block scripts %}` is the correct pattern for serializing Python data to JS variables — it handles Unicode, `None`, and special chars correctly.

### Runner header constants as schema (not `data/nxls_schema.txt`)
**Source:** `sports_system_runner.py:277–295`, `slip_payouts.py:18–24`
**Apply to:** ALL accessor functions that map columns from workbook rows

Verified column names to use (not stale schema doc):
- Picks sheet: `"Model Over Probability"`, `"EV"`, `"Edge"`, `"Confidence"`, `"Status"`, `"Platform"`, `"Player/Team"`, `"Selection"`, `"Injury Flag"` — all confirmed in `PICKS_HEADERS` (runner:277–283)
- Skipped Picks sheet: `"Gate Failed"`, `"Reason"`, `"What Edge Would Have Been"`, `"Probability"`, `"EV"`, `"Platform"`, `"Pick"` — all confirmed in `SKIPPED_PICK_HEADERS` (runner:295)
- Slip History sheet: `"Slip ID"`, `"Legs"`, `"Slip Result"`, `"Standard Payout Multiplier"`, `"Net PnL"`, `"Number of Legs"` — all confirmed in `SLIP_HISTORY_HEADERS` (slip_payouts:18–24)
- Correlated Parlays sheet: `"Reasoning"`, `"Correlation Group"`, `"Slip ID"` — confirmed in `PARLAY_HEADERS` (runner:294)

---

## No Analog Found

All Phase 2 files have analogs. Two sub-concerns within files have no in-repo precedent:

| Sub-concern | File | Reason | Use Instead |
|-------------|------|---------|-------------|
| ISO-week aggregation logic | `dashboard_data.py:get_history_data` | `metrics_report.py:aggregate_slip_roi_by_week_sport` reads per-sport workbooks in subprocess model — cannot import into dashboard | Duplicate the simple `date.fromisoformat(d).isocalendar()` aggregation inline (RESEARCH.md Pattern, anti-pattern: do NOT import `metrics_report`) |
| Chart.js CDN `<script>` block with SRI hash | `templates/history.html` | No CDN script loading exists anywhere in repo yet; `{% block scripts %}` slot was reserved but empty in Phase 1 | Use the verified `<script>` tag from RESEARCH.md Pitfall 11 (Chart.js v4.5.1, `sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ`) |

---

## Metadata

**Analog search scope:** `scripts/dashboard_data.py`, `scripts/dashboard.py`, `scripts/templates/base.html`, `scripts/templates/index.html`, `scripts/test_dashboard_data.py`, `scripts/test_dashboard.py`; runner constants at `scripts/sports_system_runner.py:277–295`; slip constants at `scripts/slip_payouts.py:18–24`
**Files scanned:** 8 source/template/test files read directly
**Pattern extraction date:** 2026-06-24
