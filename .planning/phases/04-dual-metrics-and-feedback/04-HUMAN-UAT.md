---
status: complete
phase: 04-dual-metrics-and-feedback
source: [04-VERIFICATION.md]
started: 2026-06-23T07:45:27Z
updated: 2026-06-23T08:06:00Z
---

## Current Test

[testing complete]

## Tests

### 1. Live weekly_metrics task delivery
expected: Running `cd scripts && python3 sports_system_runner.py --task weekly_metrics` with real credentials creates a Telegram message and an Obsidian note, each showing slip ROI and prop hit-rate broken down by ISO-week × sport (NBA / MLB) with WoW arrows. Task exits without error and stays under the 660s budget.
result: pass

### 2. calibration.json reflects real graded data
expected: After the first real run, `data/research/calibration.json` contains per-sport factors derived from graded PROP outcomes (or a correct "gate not met" reason when data is still sparse, e.g. <30 outcomes). Factors stay within [0.85, 1.20] and move at most ±0.05 from the prior cycle.
result: pass

### 3. Operator adds Monday cron entry
expected: A weekly cron entry is added (outside the repo by design, D-02) so weekly_metrics fires every Monday.
result: pass
note: Added to the system crontab as `# HERMES_SPORTS_WEEKLY_METRICS` — `0 8 * * 1 cd /Users/akashkalita/sports_picks/scripts && /usr/local/bin/python3 sports_system_runner.py --task weekly_metrics >> logs/hermes_sports_cron.log 2>> logs/hermes_sports_cron_errors.log` (added by assistant 2026-06-23; prior crontab backed up to ~/.hermes/crontab.backup.20260623_020554). Interpreter/import path validated.

## Summary

total: 3
passed: 3
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps
