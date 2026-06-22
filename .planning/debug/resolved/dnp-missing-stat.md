---
slug: dnp-missing-stat
status: resolved
trigger: "Phase 1 disposition table grades DNP/missing-stat props inconsistently: combo stats default missing components to 0 (grade), single stats return None (MANUAL REVIEW). Regressed a settled row (2026-06-08 Miles McBride Points 4.5 LOSS -> MANUAL REVIEW)."
created: 2026-06-22
updated: 2026-06-22
goal: find_and_fix
---

# Debug Session: dnp-missing-stat

## Symptoms
- **Expected:** A player's combo stat (PRA, H+R+RBI) and its component single stats grade CONSISTENTLY. A previously-settled bet is never changed by a re-grade.
- **Actual:** Re-grading June 8 changed 1 of 147 settled rows: `2026-06-08 PROP:Miles McBride Points 4.5` LOSS -> MANUAL REVIEW. His `Pts+Rebs+Asts 6.5` graded LOSS ("actual 0.0") but `Points 4.5` and `3-PT Made 0.5` became MANUAL REVIEW ("No final stat line found").
- **Errors:** "No final stat line found for Miles McBride Points".
- **Timeline:** Introduced by Phase 1 plan 01-3 (stat_value_for_prop disposition-table rewrite). Found 2026-06-22 during backfill verification.
- **Reproduction:** `game_completion_monitor(date="2026-06-08", reconciliation=True)` then inspect the McBride rows; or unit-test stat_value_for_prop with a player row that has some keys present and the target key absent.

## Current Focus
- hypothesis (confirmed in code): in `scripts/sports_system_runner.py` `stat_value_for_prop` (def ~L4322), DIRECT single-stat lookups return `(None,"manual",0.0)` when the stat KEY is missing from the resolved player row (via `_direct(value)` returning _MANUAL on None), while DERIVED/combo stats sum components with `or 0` defaults — so for the SAME resolved player whose row lacks a key, the combo grades (missing->0) but the single abstains. Inconsistent.
- recommended fix (CONFIRM first): make DIRECT and DERIVED consistent on missing keys — resolve to the row's value when the KEY is present (including a genuine 0); abstain (None) when the key is ABSENT; a combo returns None if ANY component key is absent (do NOT default to 0). DNP (player row entirely absent) abstains consistently for both. Do not flip any decided bet; missing/ambiguous abstains, never fabricates 0-as-LOSS or a wrong WIN.
- in scope if cheap: (a) Nick Martinez Hits Allowed 5.5 — pitcher stat looked up in batting namespace; (b) Masataka Yoshida H+R+RBI — accent name match / verify absence from box.
- next_action: confirm the exact combo `or 0` default sites + the DIRECT None path in stat_value_for_prop, then implement the consistent missing-key policy.

## Constraints (HARD — real-money grader)
- Python 3.14, run from scripts/ with python3; stdlib unittest, targeted files only (NOT the ~34-min full suite; baseline "2 failed, 202 passed").
- Additive-only schema; do NOT change gate logic or pick verdicts; do NOT revert the value-aware TERMINAL_RESULTS guard.
- Missing/ambiguous must ABSTAIN (MANUAL REVIEW); never fabricate a grade.

## Verification required after fix
- New regression test: a player row with the target key absent grades combo and single CONSISTENTLY (both abstain, or both grade — per the chosen policy).
- Re-grade June 8 (`game_completion_monitor(date="2026-06-08", reconciliation=True)`).
- Re-run settled-row flip check vs `data/pnl/_backfill_safety/terminal_snapshot_pre.json` — MUST be 0 flips (the McBride row should now resolve consistently, not regress).
- Confirm bankroll P/L recomputed from Pick History == bankroll.json.
- Targeted Phase-1 tests (test_stat_value_for_prop.py, test_provenance_plumbing.py) still pass.

## Key code
- `scripts/sports_system_runner.py`: stat_value_for_prop ~L4322 (the `_direct`/`_derived` helpers + combo `or 0` sums), grade_prop ~L4598, espn_player_stats_by_event ~L5318 (batting/pitching namespaces).
- Spec: docs/superpowers/specs/2026-06-21-trustworthy-results-design.md

## Eliminated
(none yet)

## Resolution
root_cause: In `stat_value_for_prop`, NBA PRA/combo stats used `or 0.0` fallbacks so an absent key silently became 0 and graded LOSS; the `_direct` single-stat path used `or` chaining which treated a genuine 0 value as falsy and fell through to None → MANUAL REVIEW. Same player row, inconsistent outcomes.
fix: Introduced `_flat_get(*keys)` sentinel helper inside the NBA branch that distinguishes key-absent (returns None) from key-present-but-zero (returns 0.0). PRA/combo combos now guard each component with `if X is None: return _MANUAL` so absent key → combo abstains. Direct single lookups use `_flat_get` so genuine 0 grades correctly.
verification: 112/112 test_stat_value_for_prop tests pass (includes 9 new regression tests); 32/32 test_provenance_plumbing tests pass; McBride Points 4.5 re-grades as LOSS (actual 0.0, src=api, conf=1.0); McBride Pts+Rebs+Asts 6.5 re-grades as LOSS (actual 0.0) — consistent; 0 flips in 147 terminal pre-snapshot rows; bankroll.json 7.892 == master_pnl Pick History sum 7.892.
files_changed: [scripts/sports_system_runner.py, scripts/test_stat_value_for_prop.py]
