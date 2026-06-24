---
phase: 02-read-views
verified: 2026-06-24T00:00:00Z
status: human_needed
score: 5/5 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Open http://127.0.0.1:8787/ in a browser after running `cd scripts && python3 dashboard.py`"
    expected: "Today table renders with Status, Sport, Platform, Pick, EV, Model Prob, Edge, Confidence columns; EV column sorts descending by default; Platform/Sport/Status filter dropdowns populate and filter rows; approved picks are visually distinct from dimmed skipped rows (opacity 0.55)"
    why_human: "client-side JS sort/filter/populate cannot be exercised by Flask test_client(); visual distinction of skipped rows requires browser rendering"
  - test: "Click a slip summary row on /slips in a browser"
    expected: "Detail expands revealing the legs list and 'Why paired:' text; clicking again collapses it; triangle marker rotates"
    why_human: "JavaScript toggleSlip() DOM behavior requires a real browser; test_client() only confirms 200 + page renders"
  - test: "Open /history in a browser and verify the bankroll chart"
    expected: "A Chart.js line chart renders with bankroll data; the Daily and Weekly toggle buttons swap the dataset without error; the UNKNOWN / pre-v2.0 tier row appears in the tier breakdown table"
    why_human: "Chart.js CDN script execution and canvas rendering require a real browser; the toggle event listener wiring is not exercised by test_client()"
  - test: "Open /slips in a browser with a real master_pnl.xlsx containing 88 slips and measure page load time"
    expected: "Page loads in under 5 seconds"
    why_human: "CR-01 (code review blocker): the slips route performs O(N slips x 2 workbook opens) with a 1s sleep per open via wait_for_stable_file. With 88 slips this is ~176 sequential sleeps = ~3 minutes. The route renders CORRECTLY but is effectively unusable at scale. Confirmed: test_dashboard_views.py::TestRoutes::test_slips_200 took 184 seconds with a live workbook. Human must decide: (a) fix CR-01 before phase is considered done, or (b) accept current behavior with a follow-up issue."
---

# Phase 2: Read Views Verification Report

**Phase Goal:** The operator can see the whole board through three rendered pages — today's props/picks by platform & sport, all slips with why-they're-paired insight, and the running win/loss record with charts — all read-only over the Phase 1 data layer.
**Verified:** 2026-06-24T00:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1   | Today page shows today's props/picks grouped by platform and sport with player/stat/line, projection, edge, +EV, model probability, and confidence; operator can filter by platform/sport and sort by EV (VIEW-01) | ✓ VERIFIED | `index.html` renders `board.approved` and `board.skipped` rows; filter bar with Platform/Sport/Status selects; `sortTable('ev')` on DOMContentLoaded; `data-ev`, `data-prob`, `data-edge` attributes on rows; EV column header includes default-descending indicator |
| 2   | Slips page lists every slip with its status, payout, and legs (VIEW-02) | ✓ VERIFIED | `slips.html` loops `data.slips` sorted date-descending; summary row shows Slip Result, Slip Type, Number of Legs, Standard Payout Multiplier; detail row shows `slip.legs_list`; route returns 200 |
| 3   | Each slip shows a "why these legs are paired" insight — stored Correlated Parlays Reasoning/Correlation Group where present, and a derived rationale for general slips (VIEW-02) | ✓ VERIFIED | `get_all_slips()` calls `_lookup_correlated_parlays()` (Tier-1) then `_derive_why_paired()` (Tier-2 via `_WHY_PAIRED` dict); `slips.html` line 57 renders `slip.why_paired`; test `test_why_paired_derived` GREEN; why_paired is always populated (never empty) |
| 4   | History page shows win/loss overall and per sport, with a per-confidence-tier breakdown (VIEW-03) | ✓ VERIFIED | `history.html` renders `data.overall`, `data.by_sport['NBA']`/`['MLB']`; loops `['A','B','C','UNKNOWN']` from `data.by_tier`; UNKNOWN tier always rendered as "UNKNOWN / pre-v2.0"; `test_tier_breakdown` and `test_none_tier_as_unknown` GREEN |
| 5   | History page renders a bankroll/ROI time-series chart (Chart.js via CDN) from the persisted bankroll/master-P&L data (VIEW-03) | ✓ VERIFIED | `history.html` includes Chart.js CDN with pinned `chart.js@4.5.1` and SRI hash `sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ`; canvas `bankroll-chart` present; daily/weekly toggle buttons wired; `data.chart_daily` and `data.chart_weekly` serialized via `tojson`; `test_history_200` GREEN (body contains `chart.js`) |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `scripts/dashboard_data.py` | get_today_board, get_all_slips, get_history_data + PNL_DIR | ✓ VERIFIED | All four definitions confirmed at lines 41, 302, 389, 480; no zoneinfo import |
| `scripts/test_dashboard_views.py` | 14 tests across TestTodayBoard, TestSlipsAccessor, TestHistoryAccessor, TestRoutes | ✓ VERIFIED | 14 tests collected; all 14 PASS |
| `scripts/dashboard.py` | _freshness_context + /, /slips, /history routes | ✓ VERIFIED | `_freshness_context` at line 51; `/slips` at line 79; `/history` at line 90; `HOST="127.0.0.1"` intact |
| `scripts/templates/index.html` | Today master table (sortable, filterable, dimmed skips) | ✓ VERIFIED | `today-table` present (2x); `applyFilters` (4x); `board.approved` loop; `board.skipped` loop; `skipped-row` class; no `| safe` filter |
| `scripts/templates/slips.html` | Date-grouped expandable slip rows with why-paired detail | ✓ VERIFIED | `slip-summary` (1x); `toggleSlip` (2x); `legs_list` (2x); `why_paired` (1x); Jinja `namespace` (2x); no `| safe` filter |
| `scripts/templates/history.html` | W/L + per-tier tables + Chart.js bankroll/ROI chart | ✓ VERIFIED | `bankroll-chart` (2x); SRI hash present (1x); `chart.js@4.5.1` (1x); `crossorigin` (1x); `by_tier` (1x); `UNKNOWN` (4x); `tojson` (5x); no `| safe` filter |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `dashboard.py:index` | `dashboard_data.get_today_board` | Call at line 75; result passed to `render_template` as `board=` | ✓ WIRED | Confirmed by grep and direct code read |
| `dashboard.py:slips` | `dashboard_data.get_all_slips` | Call at line 86; result passed to `render_template` as `data=` | ✓ WIRED | Confirmed |
| `dashboard.py:history` | `dashboard_data.get_history_data` | Call at line 99; result passed to `render_template` as `data=` | ✓ WIRED | Confirmed |
| `templates/index.html` | `board.approved` + `board.skipped` | Jinja loops on lines 49 and 67 | ✓ WIRED | `board.approved` (2x), `board.skipped` (2x) |
| `templates/slips.html` | `data.slips` with `legs_list`, `why_paired` | Jinja loop line 27; detail row renders `slip.legs_list` and `slip.why_paired` | ✓ WIRED | Confirmed |
| `templates/history.html` | `data.by_tier['A','B','C','UNKNOWN']` | Jinja loop line 65 over fixed tier list | ✓ WIRED | UNKNOWN tier always rendered |
| `templates/history.html` | `data.chart_daily` / `data.chart_weekly` | `tojson` on lines 108-111; Chart.js init in scripts block | ✓ WIRED | Four series variables declared |
| `dashboard_data.get_all_slips` | `_lookup_correlated_parlays` + `_derive_why_paired` | Called lines 425-428 in the slip loop | ✓ WIRED (but O(N) I/O — see CR-01) | Renders correctly; performance defect is separate |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `get_today_board` | `approved`, `skipped` | `read_sheet_rows(wb_path, "Picks")` and `read_sheet_rows(wb_path, "Skipped Picks")` | Yes — reads live xlsx workbooks; live invocation returned `approved:0, skipped:0` (no pipeline run today, correct for a new day) | ✓ FLOWING |
| `get_all_slips` | `slips` | `read_sheet_rows(PNL_DIR/"master_pnl.xlsx", "Slip History")` | Yes — reads master_pnl.xlsx Slip History sheet | ✓ FLOWING |
| `get_history_data` | `by_tier`, `chart_daily` | `read_sheet_rows(master_path, "Pick History")` and `"Bankroll Chart Data"` | Yes — reads both sheets from master_pnl.xlsx | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| `get_today_board()` returns correct dict shape without raising | `python3 -c "import dashboard_data; b=dashboard_data.get_today_board(); assert set(['approved','skipped','date','locked']) <= set(b)"` | PASS — printed `PASS: 2026-06-24 locked: False approved: 0 skipped: 0` | ✓ PASS |
| All 14 view tests pass | `cd scripts && python3 -m pytest test_dashboard_views.py -x -q` | `14 passed in 218.01s` | ✓ PASS |
| `/slips` route returns 200 | `python3 -m pytest test_dashboard_views.py::TestRoutes::test_slips_200 -v` | `1 passed in 184.42s` — PASSES but takes 184 seconds due to CR-01 | ✓ PASS (correctness); WARNING (performance — see CR-01) |

### Probe Execution

Step 7c: SKIPPED — no `scripts/*/tests/probe-*.sh` files for this phase; dashboard is a Flask server, not a CLI/migration tool.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| VIEW-01 | 02-01-PLAN.md, 02-02-PLAN.md | Operator can view today's props/picks grouped by platform and sport with +EV, model probability, edge, confidence; platform/sport filtering; EV sorting | ✓ SATISFIED | `get_today_board()` returns full evaluated set; `index.html` renders all columns; filter bar + EV-descending sort wired; 4 tests GREEN |
| VIEW-02 | 02-01-PLAN.md, 02-02-PLAN.md | Operator can view all slips (status, payout, legs) with "why these legs are paired" insight | ✓ SATISFIED | `get_all_slips()` returns legs_list + why_paired (two-tier); `slips.html` renders expandable rows; route returns 200; 3 tests GREEN |
| VIEW-03 | 02-01-PLAN.md, 02-03-PLAN.md | Operator can view W/L history overall + per sport, bankroll/ROI chart, per-confidence-tier breakdown | ✓ SATISFIED | `get_history_data()` returns by_tier (A/B/C/UNKNOWN), chart_daily, chart_weekly; `history.html` renders all three sections with Chart.js CDN; 4 tests GREEN |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `scripts/dashboard_data.py` | 416-428, 442-473 | O(N) blocking workbook I/O per slip in `_lookup_correlated_parlays` — each slip triggers 2 workbook opens, each with 1s sleep | ⚠️ Warning (Code Review already flagged as BLOCKER CR-01) | Slips page takes ~3 minutes to load with 88 slips. Rendering is correct; page is unusable at production scale |
| `scripts/templates/index.html` | 54-55, 74 | Truthiness guards (`if row.Edge`) instead of `is not none` for numeric attributes — a legitimate `0.0` becomes blank, corrupting sort | ⚠️ Warning (Code Review WR-01/WR-02) | Zero-value edge/probability columns silently disappear in sort key while `<td>` shows them — sort key and display cell disagree |
| `scripts/templates/index.html` | 54 vs 73 | Approved rows use `row['Model Over Probability']` for `data-prob`; skipped rows use `row.prob_float` — different columns, different scales | ⚠️ Warning (Code Review WR-03) | Mixed-population sort on prob column produces misleading ordering |

No `TBD`, `FIXME`, or `XXX` markers found in any phase 2 modified files.

### Human Verification Required

#### 1. Today Table Visual and Interactivity Check

**Test:** Run `cd scripts && python3 dashboard.py`, open `http://127.0.0.1:8787/` in a browser on a day when the pipeline has run (picks exist in today's workbook).
**Expected:** Table renders with all columns (Status, Sport, Platform, Pick, EV, Model Prob, Edge, Confidence); EV column sorts descending by default; approved rows are visually distinct from dimmed (opacity 0.55) skipped rows; Platform and Sport filter dropdowns populate with actual values from the data; selecting a filter hides non-matching rows.
**Why human:** client-side JavaScript (`_populateFilters`, `applyFilters`, `sortTable`) and CSS (`.skipped-row` opacity) cannot be exercised by Flask `test_client()`.

#### 2. Slips Page Click-to-Expand Check

**Test:** Open `/slips` in a browser and click a slip summary row.
**Expected:** The detail panel expands revealing the legs list (`<ul>` of individual legs) and the "Why paired:" text; clicking again collapses it; the triangle marker rotates between ► and ▼.
**Why human:** `toggleSlip()` DOM manipulation requires a real browser; `test_client()` only checks that the route returns 200 and the HTML is served.

#### 3. History Page Chart Render Check

**Test:** Open `/history` in a browser. Verify the chart renders and the toggle buttons work.
**Expected:** A Chart.js line chart appears with bankroll data points; clicking "Weekly" swaps to ISO-week aggregated data; clicking "Daily" restores daily data; the UNKNOWN / pre-v2.0 row appears in the tier breakdown table with non-zero n if historical data exists.
**Why human:** Chart.js CDN script execution and canvas rendering require a real browser; toggle event listener wiring is not exercised by `test_client()`.

#### 4. Slips Page Performance Decision (CR-01)

**Test:** Open `/slips` in a browser with a live `master_pnl.xlsx` containing the 88-slip superset.
**Expected:** Page loads in under 5 seconds.
**Why human / decision needed:** Code Review CR-01 identified that `_lookup_correlated_parlays()` is called once per slip, and each call opens both per-sport workbooks via `read_sheet_rows` → `safe_load_workbook` → `wait_for_stable_file(delay=1.0s)`. With 88 slips this is ~176 sequential 1-second sleeps ≈ 3 minutes of blocking I/O. **This was directly measured during verification: `test_slips_200` took 184 seconds with a live workbook.** The route renders correctly (status 200, correct data) but is effectively unusable at production scale. The operator must decide: (a) fix CR-01 before accepting the phase as done, or (b) accept the current rendering correctness and treat CR-01 as a follow-up performance defect.

### Gaps Summary

All five roadmap success criteria are verified in the codebase. Three templates render correctly. All 14 tests pass. The phase goal is observably achieved.

**Status is `human_needed` (not `passed`) for two reasons:**

1. Visual/interactive behaviors (client-side sort, filter, expand, chart render) cannot be verified programmatically and require browser testing.

2. CR-01 (O(N) blocking I/O on the slips route) was measured during verification at 184 seconds for the test_slips_200 route. The page renders correctly but is a usability blocker at production scale. This was flagged as a BLOCKER by the code review. The human must decide whether to fix it before accepting the phase or accept it as a known defect.

---

_Verified: 2026-06-24T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
