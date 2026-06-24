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
expected: Open /slips in a browser with a real master_pnl.xlsx containing ~88 slips and measure page load time. Page should load in under 5 seconds. CURRENT BEHAVIOR: the slips route performs O(N slips × 2 workbook opens) with a 1s sleep per open via `wait_for_stable_file` — measured at 184 seconds with a live workbook (test_slips_200). Renders correctly but unusable at scale. Operator must decide: (a) fix CR-01 before phase is accepted, or (b) accept current behavior with a tracked follow-up.
result: [pending]

## Summary

total: 4
passed: 0
issues: 0
pending: 4
skipped: 0
blocked: 0

## Gaps
