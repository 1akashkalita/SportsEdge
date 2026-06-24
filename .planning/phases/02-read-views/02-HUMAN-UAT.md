---
status: partial
phase: 02-read-views
source: [02-VERIFICATION.md]
started: 2026-06-24T00:00:00Z
updated: 2026-06-24T00:00:00Z
---

## Current Test

[awaiting human testing]

## Tests

### 1. Today page renders and sorts/filters
expected: Open http://127.0.0.1:8787/ in a browser after running `cd scripts && python3 dashboard.py`. Today table renders with Status, Sport, Platform, Pick, EV, Model Prob, Edge, Confidence columns; EV column sorts descending by default; Platform/Sport/Status filter dropdowns populate and filter rows; approved picks are visually distinct from dimmed skipped rows (opacity 0.55).
result: [pending]

### 2. Slips click-to-expand
expected: Click a slip summary row on /slips in a browser. Detail expands revealing the legs list and "Why paired:" text; clicking again collapses it; triangle marker rotates.
result: [pending]

### 3. History chart + tier breakdown
expected: Open /history in a browser. A Chart.js line chart renders with bankroll data; the Daily and Weekly toggle buttons swap the dataset without error; the UNKNOWN / pre-v2.0 tier row appears in the tier breakdown table.
result: [pending]

### 4. CR-01 decision — /slips load time at scale (BLOCKING)
expected: Open /slips in a browser with a real master_pnl.xlsx containing ~88 slips and measure page load time. Page should load in under 5 seconds.
result: RESOLVED — operator chose "Fix CR-01 now". get_all_slips() now builds a Correlated Parlays index once per distinct slip date (was O(N slips × 2 workbook opens)), and the read-only index fan-out passes delay=0.0 to skip the 1s settle sleep. Measured: test_slips_200 dropped from 184s → 1.86s. Regression test `test_correlated_parlays_read_once_per_date` pins the once-per-date contract.

## Summary

total: 4
passed: 1
issues: 0
pending: 3
skipped: 0
blocked: 0

## Gaps
