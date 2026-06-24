---
phase: 2
slug: read-views
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-24
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Source: `02-RESEARCH.md` → Validation Architecture (live-verified test map).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `unittest` (stdlib) base class; discovery via `python3 -m pytest` (pytest 9.0.3 installed) |
| **Config file** | none — tests self-load via `sys.path` + bare sibling imports (project convention); run from `scripts/` |
| **Quick run command** | `cd scripts && python3 -m pytest test_dashboard.py test_dashboard_data.py -x` |
| **Full suite command** | `cd scripts && python3 -m pytest test_dashboard.py test_dashboard_data.py test_dashboard_views.py -x` |
| **Estimated runtime** | quick: ~seconds · phase-gate full suite: ~34 min (use targeted files during the phase; full `pytest` only at the phase gate) |

---

## Sampling Rate

- **After every task commit:** Run `cd scripts && python3 -m pytest test_dashboard.py test_dashboard_data.py -x`
- **After every plan wave:** Run `cd scripts && python3 -m pytest test_dashboard.py test_dashboard_data.py test_dashboard_views.py -x`
- **Before `/gsd:verify-work`:** Full suite green — baseline is **"2 failed, 202 passed"** (the 2 known projection failures per project memory; anything beyond those two is a regression). Phase 2's new `test_dashboard_views.py` must be fully green.
- **Max feedback latency:** ~10 seconds (quick run)

---

## Per-Task Verification Map

> Keyed by requirement; task IDs bound to PLAN task IDs by the planner. All Phase 2 tests live in the new `scripts/test_dashboard_views.py` (Wave-0 stub — does not exist yet).

| Plan/Req | Wave | Requirement | Behavior | Test Type | Automated Command | File Exists | Status |
|----------|------|-------------|----------|-----------|-------------------|-------------|--------|
| VIEW-01 | 1 | VIEW-01 | `get_today_board()` returns approved picks from Picks sheet, date-filtered | unit | `python3 -m pytest test_dashboard_views.py::TestTodayBoard::test_approved_picks -x` | ❌ W0 | ⬜ pending |
| VIEW-01 | 1 | VIEW-01 | `get_today_board()` returns skipped picks with `status_label = "Skip: GATE-NAME"` | unit | `python3 -m pytest test_dashboard_views.py::TestTodayBoard::test_skipped_picks_gate_label -x` | ❌ W0 | ⬜ pending |
| VIEW-01 | 1 | VIEW-01 | `get_today_board()` returns `locked=True` when `read_sheet_rows` returns None (mid-write lock) | unit | `python3 -m pytest test_dashboard_views.py::TestTodayBoard::test_locked_state -x` | ❌ W0 | ⬜ pending |
| VIEW-01 | 1 | VIEW-01 | `ev_float` is None for skipped picks with EV="unavailable" (coercion safe) | unit | `python3 -m pytest test_dashboard_views.py::TestTodayBoard::test_ev_coercion -x` | ❌ W0 | ⬜ pending |
| VIEW-01 | 1 | VIEW-01 | `GET /` returns 200 and HTML contains the `EV` column header | route smoke | `python3 -m pytest test_dashboard_views.py::TestRoutes::test_index_200 -x` | ❌ W0 | ⬜ pending |
| VIEW-02 | 1 | VIEW-02 | `get_all_slips()` returns all slips from `master_pnl.xlsx`, sorted date-descending | unit | `python3 -m pytest test_dashboard_views.py::TestSlipsAccessor::test_slips_sorted -x` | ❌ W0 | ⬜ pending |
| VIEW-02 | 1 | VIEW-02 | `get_all_slips()` splits `Legs` string into `legs_list` | unit | `python3 -m pytest test_dashboard_views.py::TestSlipsAccessor::test_legs_parsed -x` | ❌ W0 | ⬜ pending |
| VIEW-02 | 1 | VIEW-02 | `get_all_slips()` populates two-tier `why_paired` (stored Reasoning/Group → derived fallback) | unit | `python3 -m pytest test_dashboard_views.py::TestSlipsAccessor::test_why_paired_derived -x` | ❌ W0 | ⬜ pending |
| VIEW-02 | 1 | VIEW-02 | `GET /slips` returns 200 and HTML contains at least one slip row | route smoke | `python3 -m pytest test_dashboard_views.py::TestRoutes::test_slips_200 -x` | ❌ W0 | ⬜ pending |
| VIEW-03 | 1 | VIEW-03 | `get_history_data()` returns per-tier breakdown (A/B/C/UNKNOWN: W-L, hit-rate, ROI, count) | unit | `python3 -m pytest test_dashboard_views.py::TestHistoryAccessor::test_tier_breakdown -x` | ❌ W0 | ⬜ pending |
| VIEW-03 | 1 | VIEW-03 | `Confidence Tier = None` is treated as `UNKNOWN` tier (not hidden) | unit | `python3 -m pytest test_dashboard_views.py::TestHistoryAccessor::test_none_tier_as_unknown -x` | ❌ W0 | ⬜ pending |
| VIEW-03 | 1 | VIEW-03 | `get_history_data()` returns `chart_daily` with correct labels + bankroll series | unit | `python3 -m pytest test_dashboard_views.py::TestHistoryAccessor::test_chart_daily -x` | ❌ W0 | ⬜ pending |
| VIEW-03 | 1 | VIEW-03 | `get_history_data()` aggregates `chart_weekly` by ISO week (last point per week) | unit | `python3 -m pytest test_dashboard_views.py::TestHistoryAccessor::test_chart_weekly -x` | ❌ W0 | ⬜ pending |
| VIEW-03 | 1 | VIEW-03 | `GET /history` returns 200 and HTML contains the Chart.js script tag | route smoke | `python3 -m pytest test_dashboard_views.py::TestRoutes::test_history_200 -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `scripts/test_dashboard_views.py` — new test file covering all VIEW-* requirements above, in the existing `unittest.TestCase` style:
  - `TestTodayBoard` — unit tests for `get_today_board()` using synthetic in-memory workbooks (pattern from `test_dashboard_data.py:_make_picks_wb`)
  - `TestSlipsAccessor` — unit tests for `get_all_slips()` using an in-memory `master_pnl`-shaped workbook
  - `TestHistoryAccessor` — unit tests for `get_history_data()` using an in-memory workbook (incl. None-tier and sparse-chart fixtures)
  - `TestRoutes` — route smoke tests via `dashboard.app.test_client()` for `/`, `/slips`, `/history`

*Existing `test_dashboard.py` + `test_dashboard_data.py` cover Phase 1 DASH-* requirements; Phase 2 adds `test_dashboard_views.py` to the same `scripts/` directory.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Chart.js renders the bankroll/ROI series in a real browser (CDN load + SRI) | VIEW-03 | CDN fetch + canvas render is not exercised by `test_client()`; needs a live browser | `cd scripts && python3 dashboard.py`, open `http://127.0.0.1:<port>/history`, confirm the bankroll line draws and the daily/weekly toggle switches series |
| Sortable headers + expandable slip rows behave (client-side JS) | VIEW-01, VIEW-02 | DOM interaction (click-to-sort, row expand) is not covered by route smoke tests | In the browser: click an EV header → rows reorder; click a slip summary row → legs + "why paired" expand |
| Skipped-row dimming + +EV color cue read correctly | VIEW-01 | Visual/aesthetic judgement | Confirm approved picks visually pop vs muted skip rows on `/` |

---

## Validation Sign-Off

- [x] All requirement rows have an `<automated>` verify (unit + route smoke) or are listed under Manual-Only with rationale
- [x] Sampling continuity: no 3 consecutive tasks without automated verify (every accessor + route has a unit/smoke test)
- [x] Wave 0 covers the one MISSING reference (`test_dashboard_views.py`)
- [x] No watch-mode flags (`-x` one-shot runs only)
- [x] Feedback latency < ~10s (quick run)
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending (bound to task IDs at plan creation)
