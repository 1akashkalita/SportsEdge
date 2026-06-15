---
phase: 01-diagnosis
plan: 02
subsystem: diagnosis/timing-evidence
tags: [timing, diagnosis, run-log-mining, telegram-retry, ranked-contributors]
dependency_graph:
  requires:
    - .planning/phases/01-diagnosis/01-RESEARCH.md
    - data/pnl/logs/run_log.txt
  provides:
    - .planning/phases/01-diagnosis/01-TIMING-EVIDENCE.md
  affects:
    - .planning/phases/01-diagnosis/01-03-PLAN.md (DIAGNOSIS.md timeout section)
tech_stack:
  added: []
  patterns: [run-log-mining, external-timing-measurement]
key_files:
  created:
    - .planning/phases/01-diagnosis/01-TIMING-EVIDENCE.md
  modified: []
decisions:
  - send_telegram() retry loop (30s×2 per failing call) named as dominant timeout contributor with run-log evidence — not subprocess timeout ceiling
  - Lead #2 (stacked subprocess timeouts, 1500s theoretical ceiling) RULED OUT: largest daily_picks observed is 7,697s, exceeding the ceiling by 5x via lock contention, confirming it is NOT the operative cause
  - D-11 decision recorded: no throwaway instrumentation added — coarse numbers from run-log mining isolate the offender
metrics:
  duration: "~90 minutes (log mining + 6 timed runs)"
  completed: "2026-06-15"
  completed_tasks: 2
  total_tasks: 2
---

# Phase 1 Plan 02: Timing Sweep Evidence Summary

**One-liner:** `send_telegram()` 30s retry loop named as dominant cron-timeout contributor (observed max 24,923s on clv_tracker); stacked subprocess timeouts (Lead #2, 1,500s ceiling) ruled out with run-log evidence from 791+ completions.

## What Was Built

Produced `.planning/phases/01-diagnosis/01-TIMING-EVIDENCE.md` — the DIAG-02 timing evidence artifact for the DIAGNOSIS.md timeout section (Plan 03).

**Task 1 (mining):** Extracted per-task duration profiles from 18,626 run-log lines spanning 2026-06-08 through 2026-06-15 (791+ task completions across all 11 runner tasks). Built a complete duration table (min/p25/median/p75/max) per task, correlated extreme durations with their co-occurring network/Telegram stall lines.

**Task 2 (timed runs + ranked table):** Executed representative timed invocations for the heavy path tasks using `time python3 sports_system_runner.py --task <task>` from `scripts/`. Assembled the D-10 ranked-contributors table with 5 entries. Recorded the D-11 instrumentation decision (not needed — coarse numbers sufficient).

## Dominant Timeout Contributor (DIAG-02 Answer)

**`send_telegram()` retry loop** — 30s HTTP timeout × 2 retries per failing call site, multiple call sites per task run (one per `log()` call that fires an alert, plus per-move fanout in `dispatch_alerts`).

- Max observed: **24,923s** (`mlb_clv_tracker`, 2026-06-12) — entire duration caused by Telegram/DNS failure
- Causes today's still-elevated runs (1,128s `mlb_daily_picks`, 832s `nba_prop_monitor`) during the active network outage
- Under normal network conditions, the same tasks run in 44s (mlb_daily_picks median) and 31s (nba_prop_monitor median)

## Lead #2 Disposition: RULED OUT

**Stacked subprocess timeout totals are RULED OUT as the primary timeout cause.**

- Theoretical ceiling: `fetch_dfs_props` 300s + `build_hit_rate_db` 600s + `generate_projections` 600s = **1,500s**
- Largest observed `daily_picks` duration: **7,697s** — exceeds ceiling by 5× confirming it cannot be from subprocess timeouts
- Subprocess stages complete in seconds under normal conditions: hit_rate_db ~19s (290 players), generate_projections ~2s, fetch_dfs_props ~3s
- The 1,500s ceiling has never been reached in 791+ completions

## Ranked Contributors (D-10 Table)

| Rank | Contributor | Max overhead | Root cause |
|------|-------------|-------------|------------|
| 1 | `send_telegram()` retry loop | 24,923s | Network/DNS outage; 30s timeout × 2 retries per call |
| 2 | `obsidian_sync` per `log()` call | Minutes compounding | 60s subprocess per log line × N log lines |
| 3 | Workbook lock contention | Hours (in combination with #1) | Lock holder stalled → queue behind it |
| 4 | Bare `print()` in `run_fetch_dfs_props` | Rare | Pipe already closed; unprotected print |
| 5 | Stacked subprocess timeouts | 1,500s (theoretical) | Never reached in 791+ completions |

## D-11 Instrumentation Decision

No throwaway per-stage instrumentation was added. The run-log provides complete subprocess timing already (e.g., `build_hit_rate_db — start/complete` pairs showing 19s for 290 players). The extreme durations (hours) are far outside the subprocess range (seconds), making the offender clear without code instrumentation. The only source code change in Phase 1 is the Plan 01 traceback hook — nothing from Plan 02 touched source.

## Evidence Artifact Location

`.planning/phases/01-diagnosis/01-TIMING-EVIDENCE.md` — contains:
- `## Run-Log Duration Profile` — per-task table (all 11 tasks, 5 duration percentiles)
- `## Slow-Run Warning Corroboration` — 206 slow-run warnings catalogued
- `## Extreme-Duration / Network-Stall Correlation` — 3 cases with verbatim run-log excerpts
- `## Lead #2 Disposition` — RULED OUT with the 7,697s vs 1,500s ceiling comparison
- `## Representative Timed Runs` — 6 timed runs with wall-clock + runner `completed in` agreement
- `## Ranked Contributors` — D-10 5-column schema table (Rank | Contributor | Max | Occurs when | Fix)
- `## D-11 Instrumentation Decision` — explicit no-instrumentation decision
- `## Timing Caveat` — python3 3.14 ALPHA stated; cron budget marked [ASSUMED]

## Deviations from Plan

None — plan executed exactly as written. The coarse external numbers isolated the dominant offender (D-11 confirmed), so no throwaway instrumentation was needed. Representative timed runs were collected for: `verify`, `nba_daily_picks`, `nba_injury_monitor`, `mlb_prop_monitor`, `mlb_daily_picks`, and `nba_prop_monitor` — all six tasks matched or exceeded the plan minimum of three (nba_daily_picks + mlb_daily_picks + mlb_prop_monitor).

## Threat Surface Scan

No new network endpoints, auth paths, file access patterns, or schema changes introduced. This plan is read-only log mining plus new documentation file creation. No threat flags.

## Known Stubs

None — the artifact is complete evidence, not a placeholder.

## Self-Check

- [x] `.planning/phases/01-diagnosis/01-TIMING-EVIDENCE.md` exists (200 lines, > 40 minimum)
- [x] `## Run-Log Duration Profile` section present with nba_daily_picks, mlb_daily_picks, mlb_prop_monitor
- [x] `## Lead #2 Disposition` present with RULED OUT, 1,500s ceiling, 7,697s observed max
- [x] Verbatim run-log excerpt with timestamp in `## Extreme-Duration / Network-Stall Correlation`
- [x] `grep -E 'TELEGRAM_BOT_TOKEN|PRIZEPICKS_COOKIE|ODDS_API_IO_KEY'` returns nothing
- [x] `## Representative Timed Runs` present with nba_daily_picks, mlb_daily_picks, mlb_prop_monitor
- [x] `## Ranked Contributors` with D-10 schema and send_telegram ranked #1
- [x] `## D-11 Instrumentation Decision` present
- [x] `## Timing Caveat` with "alpha" and "ASSUMED"
- [x] Test suite (subset: slip_payouts, special_line_value, prop_correlation) passes — 45 passed in 0.17s
- [x] No source code changes from this plan (only docs created)
