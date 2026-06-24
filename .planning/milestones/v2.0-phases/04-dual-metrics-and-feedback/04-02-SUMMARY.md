---
phase: 04-dual-metrics-and-feedback
plan: 02
subsystem: metrics-report
tags: [metrics, roi, hit-rate, aggregation, telegram, obsidian, tdd]
dependency_graph:
  requires: []
  provides: [scripts/metrics_report.py, scripts/test_metrics_report.py]
  affects: [scripts/sports_system_runner.py via Plan 03 weekly_metrics task]
tech_stack:
  added: []
  patterns: [per-sport-workbook-aggregation, wow-arrow, read-only-module, tdd-red-green]
key_files:
  created:
    - scripts/metrics_report.py
    - scripts/test_metrics_report.py
  modified: []
decisions:
  - "D-04/D-05: Slip ROI = Σ Net PnL / Σ Stake over staked (stake > 0) slips only; zero-stake slips counted separately in zero_stake field"
  - "D-06: Sport attribution via per-sport workbook iteration (nba_*.xlsx / mlb_*.xlsx); any future cross-sport slip → MIXED bucket"
  - "D-03: wow_arrow uses 0.005 threshold; returns ↑/→/↓ — no improving/stagnant verdict line emitted"
  - "Pitfall 3 resolution: GRADED Slip Result rows included in ROI (Net PnL counted) but excluded from wins/losses/pushes counts"
  - "No sports_system_runner import — uses local PROP_ACCURACY_HEADERS constant to avoid circular dependency"
metrics:
  duration: ~15 min
  completed_date: "2026-06-23"
  tasks_completed: 2
  files_created: 2
  tests_added: 32
  tests_passing: 32
---

# Phase 4 Plan 2: Metrics Report Module Summary

**One-liner:** Pure read-only `metrics_report.py` module providing staked-only slip ROI (Σ Net PnL / Σ Stake) and prop hit-rate aggregation by ISO-week × sport with ↑/→/↓ WoW arrows, Telegram digest, and Obsidian markdown rendering — no verdict line, no workbook writes, no runner import.

## What Was Built

### `scripts/metrics_report.py` (526 lines)

A pure read-only aggregation and string-formatting module implementing METRICS-01 (D-03/D-04/D-05/D-06):

**`aggregate_slip_roi_by_week_sport(inception=INCEPTION_DATE)`**
- Iterates `data/nba/nba_*.xlsx` and `data/mlb/mlb_*.xlsx` Slip History sheets (D-06 per-sport bucketing)
- Staked slips only (stake > 0) feed ROI; zero-stake slips counted separately as `zero_stake` (D-04)
- Rows with `Needs Payout Reconciliation` truthy are excluded entirely (T-04-06)
- ROI = `total_pnl / total_stake`; `None` when `total_stake == 0`
- `GRADED` Slip Result rows: Net PnL included in ROI but not in wins/losses counts (Pitfall 3 resolution)
- Uses `safe_load_workbook(read_only=True, data_only=True)` for concurrent-access safety (T-04-06)

**`read_prop_hit_rate_by_week_sport(master_path, _wb_override)`**
- Reads existing `Prop Accuracy` sheet from `master_pnl.xlsx` (reuses `refresh_prop_accuracy` output)
- Column lookup by header name (safe against additive migrations)
- Returns `{}` (SKIP) when sheet is absent

**`wow_arrow(current, prev, threshold=0.005)`**
- Returns `"↑"` / `"→"` / `"↓"` — `"→"` when either argument is `None` (D-03)

**`build_weekly_report(roi_agg, prop_rates)`**
- Merges both aggregations, computes WoW deltas + arrows for ROI and hit-rate per sport
- Sorted by (iso_week, sport); no verdict line (D-03)

**`format_telegram_digest(report)`**
- Compact multi-line message: header with latest ISO-week, per-sport line with ROI% arrow + Hits% arrow + staked count, zero-stake informational line (D-01/D-03/D-04)

**`fill_obsidian_recap_markdown(report, calibration_note="")`**
- Overview table + By Sport table (all weeks × sports with ROI/hit-rate/WoW arrows) + Adjustments-for-Next-Week heading (D-01/D-03)
- `calibration_note` parameter accepts the Plan 03 calibration audit string

### `scripts/test_metrics_report.py` (501 lines)

32 tests across 6 test classes covering all METRICS-01 behaviors:

| Class | Tests | Coverage |
|-------|-------|----------|
| `TestSlipRoiAggregation` | 5 | ROI formula, W/L counting, recon exclusion, GRADED handling, no-runner-import check |
| `TestZeroStakeSeparation` | 3 | Zero-stake count separation, None stake handling, ROI=None when stake=0 |
| `TestPropHitRateAggregation` | 4 | 2-row fixture, multiple sports, missing sheet → empty, case normalization |
| `TestWowArrow` | 10 | All arrow directions, threshold boundaries, None handling |
| `TestFormatTelegramDigest` | 5 | ISO-week present, ROI+Hits rendered, arrow chars present, no verdict text, zero-stake line |
| `TestFillObsidianMarkdown` | 5 | By Sport section, NBA+MLB rows, Adjustments heading, calibration_note injection, no verdict text |

## Deviations from Plan

None — plan executed exactly as written. All acceptance criteria from both tasks met.

## Threat Mitigations Applied

| Threat | Mitigation |
|--------|-----------|
| T-04-06: Half-written workbook during concurrent daily run | `safe_load_workbook` (retry-on-stale) with `read_only=True, data_only=True`; malformed rows SKIPped |
| T-04-08: 30 workbook opens | Read-only, small files; confirmed well under 660s budget |

## Acceptance Criteria Verification

- Two staked MLB slips (stake=1.0 net=+2.0; stake=1.0 net=-1.0) + one zero-stake: ROI==0.5; zero_stake==1; total_stake==2.0. **VERIFIED (TestZeroStakeSeparation.test_zero_stake_separation)**
- Needs Payout Reconciliation truthy → excluded from all counts. **VERIFIED (TestSlipRoiAggregation.test_recon_flagged_rows_excluded_entirely)**
- GRADED row: Net PnL in ROI; not in wins/losses. **VERIFIED (TestSlipRoiAggregation.test_graded_row_included_in_roi_not_win_loss)**
- `python3 -c "import metrics_report"` imports cleanly with no sports_system_runner import. **VERIFIED (test + runtime check)**
- wow_arrow(0.52, 0.47)=="↑"; wow_arrow(0.47, 0.52)=="↓"; wow_arrow(0.50, 0.50)=="→"; wow_arrow(0.5, None)=="→". **VERIFIED (TestWowArrow)**
- read_prop_hit_rate_by_week_sport 2-row fixture → {("2026-W25","MLB"):0.55, ("2026-W26","MLB"):0.60}. **VERIFIED (TestPropHitRateAggregation.test_reads_two_row_fixture)**
- format_telegram_digest: latest ISO-week, ROI+Hits with arrow, zero-stake count, no "improving"/"stagnant". **VERIFIED (TestFormatTelegramDigest)**
- fill_obsidian_recap_markdown: By Sport section, NBA+MLB rows, Adjustments heading. **VERIFIED (TestFillObsidianMarkdown)**

## Operator Note

The `weekly_metrics` runner task (Plan 03) will call `format_telegram_digest` and `fill_obsidian_recap_markdown` with the strings produced here, then deliver them via `send_telegram` / `obsidian_sync`. No cron entry is added in this plan — it will be wired in Plan 03 and the operator must add a Monday-morning cron entry to `~/.hermes` (per D-02).

## Self-Check: PASSED

- `scripts/metrics_report.py`: FOUND
- `scripts/test_metrics_report.py`: FOUND
- Commit d88a5e7 (test RED phase): FOUND
- Commit d2fa6da (feat GREEN phase implementation): FOUND
- 32/32 tests passing: VERIFIED
