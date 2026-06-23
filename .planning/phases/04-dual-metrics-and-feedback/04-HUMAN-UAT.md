---
status: partial
phase: 04-dual-metrics-and-feedback
source: [04-VERIFICATION.md]
started: 2026-06-23T07:45:27Z
updated: 2026-06-23T07:45:27Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Live weekly_metrics task delivery
expected: Running `cd scripts && python3 sports_system_runner.py --task weekly_metrics` with real credentials creates a Telegram message and an Obsidian note, each showing slip ROI and prop hit-rate broken down by ISO-week × sport (NBA / MLB) with WoW arrows. Task exits without error and stays under the 660s budget.
result: [pending]

### 2. calibration.json reflects real graded data
expected: After the first real run, `data/research/calibration.json` contains per-sport factors derived from graded PROP outcomes (or a correct "gate not met" reason when data is still sparse, e.g. <30 outcomes). Factors stay within [0.85, 1.20] and move at most ±0.05 from the prior cycle.
result: [pending]

### 3. Operator adds Monday cron entry
expected: A weekly cron entry is added to `~/.hermes` (outside the repo by design, D-02):
`0 8 * * MON cd <scripts_dir> && /usr/local/bin/python3 sports_system_runner.py --task weekly_metrics`
result: [pending]

## Summary

total: 3
passed: 0
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
