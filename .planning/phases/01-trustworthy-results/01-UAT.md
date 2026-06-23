---
status: complete
phase: 01-trustworthy-results
source: [01-1-SUMMARY.md, 01-2-SUMMARY.md, 01-3-SUMMARY.md, 01-4-SUMMARY.md, 01-5-SUMMARY.md, 01-6-PLAN.md]
started: 2026-06-23T00:00:00Z
updated: 2026-06-23T13:40:00Z
---

## Current Test

[testing complete — RESULTS-07 verified; June 8 MLB backlog fully resolved; 3 fixes captured as gaps]

## Tests

### 1. RESULTS-07 — June 8 dry-run gate ≥80% + backfill ran
expected: June 8 backfilled to 96 terminal MLB grades; remaining MANUAL REVIEW = 46 Fantasy-Score residue + 2 genuinely-unresolvable; historical resolution 35/37 = 94.6% ≥ 80% (gate cleared).
result: pass
note: |
  Confirmed via direct workbook inspection. The 2 "genuinely-unresolvable" non-Fantasy
  stragglers were RESOLVED via web box-score lookup (CBS + ESPN): both were DNP on June 8
  — Nick Martinez pitched June 9, Masataka Yoshida played June 9, neither appeared June 8.
  Graded VOID (no action), Result Source=scraped, Confidence=1.0. June 8 non-Fantasy
  backlog is therefore fully resolved; remaining MANUAL REVIEW = 46 Fantasy-Score rows
  (separately resolved — see Test 4).

### 2. Gate test honesty — test_june8_dryrun_gate.py is misleadingly red
expected: The automated RESULTS-07 gate test currently FAILS (reports 0/2) because it re-runs Layer-1 against rows that are STILL MANUAL REVIEW after the backfill (the residue) instead of the original ~37-row denominator — so a passed requirement reads red and pollutes the test baseline. This is a "passed work reads red" defect worth fixing (make the gate idempotent / fixture-pin the pre-backfill snapshot, or recognize it as a one-shot historical gate).
result: issue
reported: "Non-idempotent gate test reads red despite RESULTS-07 passing — pollutes the test baseline."
severity: minor

### 3. June 8–21 backfill coverage
expected: June 8 is fully backfilled; June 9–21 workbooks carry only a few rows each (MLB 0–4/date, NBA mostly empty) with near-zero MANUAL REVIEW — i.e. sparse data for those dates, not a missed backfill (no hidden recoverable backlog).
result: pass

### 4. Fantasy-Score residue (46 June 8 rows) — resolved via PrizePicks formula + box scores
expected: The 46 Fantasy-Score MANUAL REVIEW rows (Hitter/Pitcher Fantasy Score, PrizePicks) are resolved by computing the actual PrizePicks fantasy score from June 8 box scores and grading over-style (WIN if score>line, LOSS if <, PUSH if =, VOID if DNP). Formula now known (operator-supplied); platform confirmed PrizePicks; grading direction matches the system's verified over-rule (35/35 prop rows consistent).
result: pass
note: |
  All 46 resolved: 27 WIN, 19 LOSS, 0 remaining. PrizePicks fantasy scores computed in code
  (singles 3 / 2B 5 / 3B 8 / HR 10 / R·2 / RBI·2 / BB·2 / HBP·2 / SB·5; pitcher out·1 / K·3 /
  ER·−3 / W·6 / QS·4), graded over-style vs line. Box-score stats pulled from TWO independent
  sources per game (ESPN + CBS/Baseball-Reference) and reconciled; 45/46 agreed exactly. The
  one cross-source disagreement (Spencer Arrighetti ER 2 vs 3) was WIN either way (score 34–37
  vs 28.5 line). No DNPs. June 8 MLB Results is now 100% terminal: 71 WIN / 70 LOSS / 1 PUSH /
  2 VOID, 0 MANUAL REVIEW. Backups saved under data/backups/workbooks/2026-06-23/.

## Summary

total: 4
passed: 3
issues: 1
pending: 0
skipped: 0

## Gaps

- truth: "DNP props resolve to VOID, not MANUAL REVIEW"
  status: failed
  reason: "Grading parks did-not-play props in MANUAL REVIEW ('no final stat line found') instead of detecting the DNP and grading VOID. Surfaced by Nick Martinez (pitched June 9) and Masataka Yoshida (played June 9) — both DNP June 8, manually resolved to VOID this session."
  severity: minor
  fix: "Layer-2: when stat_value_for_prop returns None, confirm whether the player appeared in the game (box score / lineup); if DNP -> grade VOID (no action) instead of MANUAL REVIEW. Squarely in the firecrawl-fallback's lane (verify_results.py / resolve_missing_stat)."
  test: 1
  artifacts: [scripts/verify_results.py, scripts/sports_system_runner.py]
  missing: [DNP detection -> VOID]

- truth: "PrizePicks/Underdog Fantasy Score props grade automatically"
  status: failed
  reason: "The Fantasy Score scoring formula was unencoded (the 46-row June 8 residue class). Operator supplied the PrizePicks + Underdog MLB scoring tables this session; the 46 rows were resolved manually by computing PrizePicks fantasy scores from box scores."
  severity: major
  fix: "Encode the PrizePicks + Underdog MLB hitter/pitcher fantasy-score formulas into the grader so Hitter/Pitcher Fantasy Score props derive an actual value (singles 3 / double 5 / triple 8 / HR 10 / R 2 / RBI 2 / BB 2 / HBP 2 / SB PP5 UD4; pitcher out 1 / K 3 / ER -3 / W PP6 UD5 / QS PP4 UD5). Requires platform disambiguation (rows currently tagged generic 'DFS' — recover PrizePicks vs Underdog from the source prop reasoning)."
  test: 4
  artifacts: [scripts/sports_system_runner.py, scripts/verify_results.py]
  missing: [fantasy-score formula encoding, platform disambiguation]

- truth: "RESULTS-07 gate test reflects reality (green when the gate passed)"
  status: failed
  reason: "test_june8_dryrun_gate.py re-runs Layer-1 against rows STILL in MANUAL REVIEW after the backfill (the residue) and reports 0/2, reading red despite RESULTS-07 passing at 94.6%. Pollutes the test baseline (1 of the 4 'pre-existing' failures)."
  severity: minor
  fix: "Make the gate idempotent: pin a pre-backfill fixture snapshot of the June 8 MANUAL REVIEW rows and measure Layer-1 against that fixed denominator, OR convert to a one-shot historical assertion. Should also account for DNP->VOID rows being excluded from the denominator."
  test: 2
  artifacts: [scripts/test_june8_dryrun_gate.py]
  missing: [idempotent gate measurement]
