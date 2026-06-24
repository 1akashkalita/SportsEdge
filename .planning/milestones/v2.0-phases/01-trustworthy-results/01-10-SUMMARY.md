---
phase: 01-trustworthy-results
plan: 10
subsystem: grading
tags: [python, fantasy-score, prizepicks, underdog, mlb, grading, provenance]

# Dependency graph
requires:
  - phase: 01-trustworthy-results
    plan: 3
    provides: stat_value_for_prop disposition table, _hit_counts batting namespace, _innings_to_outs_grading
  - phase: 01-trustworthy-results
    plan: 9
    provides: Layer-2 firecrawl scrape lane (SB/Win from play-by-play)

provides:
  - MLB Hitter Fantasy Score derivation: single*3+double*5+triple*8+HR*10+R*2+RBI*2+BB*2+HBP*2+SB*(PP5/UD4)
  - MLB Pitcher Fantasy Score derivation: outs*1+K*3+ER*(-3)+Win*(PP6/UD5)+QS*(PP4/UD5) where QS=outs>=18 AND ER<=3
  - Platform recovery: _prop_platform() reads Platform field then Reasoning text (PrizePicks vs Underdog)
  - Money-safe disagreement-abstain: platform unknown + SB/Win/QS makes PP vs UD grades differ -> MANUAL REVIEW
  - Missing-component-abstain: outs or hit-type counts unavailable -> MANUAL REVIEW (never guess)

affects:
  - verify_results (Layer-2 scrape provides SB/Win into bat/pit dicts)
  - check_results (calls grade_prop which now passes source_row to stat_value_for_prop)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Fantasy score derivation: arithmetic over locked scoring tables with platform-specific SB/Win/QS weights"
    - "Grade-comparison disambiguation: when platform is unknown and scores differ, compare grades vs line to abstain-or-grade"
    - "source_row optional parameter threads prop metadata into stat resolution without breaking existing callers"

key-files:
  created:
    - scripts/test_fantasy_score.py
  modified:
    - scripts/sports_system_runner.py
    - scripts/test_stat_value_for_prop.py

key-decisions:
  - "Do the grade-comparison disambiguation inside stat_value_for_prop using source_row['Line']; no separate line parameter needed"
  - "When platform unknown and scores equal (no divergent component or scores coincidentally agree): grade with the common score"
  - "Win (pitcher decision) treated as confirmed-0 when absent from box (same as SB); QS derived purely arithmetically from outs+ER"
  - "source_row parameter named to avoid collision with existing local 'row' variable (player_stats.get(matched_key))"
  - "test_stat_value_for_prop.py updated: old NOT-DERIVABLE assertions for MLB fantasy score replaced to reflect derivable behavior"

patterns-established:
  - "Locked scoring table: operator-supplied values encoded as numeric literals with GAP/RESULTS citation comments"
  - "Money-safe abstain over grade: missing data or grade disagreement returns (None, 'manual', 0.0) consistently"

requirements-completed: [RESULTS-02, RESULTS-07]

# Metrics
duration: 25min
completed: 2026-06-23
---

# Phase 01 Plan 10: Fantasy Score Derivation Summary

**MLB Hitter/Pitcher Fantasy Score now derives actual values from box-score components with PP/UD platform disambiguation and money-safe abstain rules (GAP 2 closed)**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-06-23T21:35:00Z
- **Completed:** 2026-06-23T22:00:00Z
- **Tasks:** 2 (TDD: RED + GREEN)
- **Files modified:** 3

## Accomplishments

- Encoded locked PP/UD scoring tables: hitter (single 3 / double 5 / triple 8 / HR 10 / R 2 / RBI 2 / BB 2 / HBP 2 / SB PP5|UD4) and pitcher (out 1 / K 3 / ER -3 / Win PP6|UD5 / QS PP4|UD5 where QS=outs>=18 AND ER<=3)
- Platform recovery via `_prop_platform()`: inspects Platform field then Reasoning text ("PrizePicks baseline" → prizepicks, "Underdog value" → underdog, else unknown)
- Money-safe disagreement-abstain: when platform is unknown AND divergent component (SB/Win/QS) makes PP and UD grades differ vs the line → MANUAL REVIEW
- Missing-component-abstain: when outs data or hit-type counts are absent → MANUAL REVIEW (never assume 0)
- `stat_value_for_prop` extended with optional `source_row` parameter; `grade_prop` now passes `source_row=row` so platform is recovered at grading time
- 27 pinning tests in `test_fantasy_score.py`; 144 existing regression tests pass unmodified behavior

## Task Commits

1. **Task 1: RED — failing tests pinning PP/UD tables, grading, platform, both abstain rules** - `0479d96` (test)
2. **Task 2: GREEN — fantasy-score derivation + platform disambiguation wired into stat_value_for_prop** - `d143657` (feat)

## Files Created/Modified

- `/Users/akashkalita/sports_picks/scripts/test_fantasy_score.py` - 27 TDD tests (hitter/pitcher exact weights, over-style grading, platform recovery, disagreement-abstain, missing-component-abstain, NBA not-regressed)
- `/Users/akashkalita/sports_picks/scripts/sports_system_runner.py` - Added `_prop_platform()`, `_hitter_fantasy_score()`, `_pitcher_fantasy_score()`, `_fantasy_grade_direction()`; extended `stat_value_for_prop` with `source_row` param and fantasy-score routing; updated `grade_prop` to pass `source_row=row`; removed MLB fantasy from `_NOT_DERIVABLE`
- `/Users/akashkalita/sports_picks/scripts/test_stat_value_for_prop.py` - Updated 3 assertions that pinned old NOT-DERIVABLE behavior for MLB fantasy score; annotated with GAP 2 context

## Decisions Made

- **Grade-comparison in stat_value_for_prop**: The line for disambiguation comes from `source_row["Line"]` when available. This keeps all the logic in one place without splitting the abstain decision across two functions.
- **Win treated as confirmed-0 when absent**: Pitcher Win is not in the standard ESPN summary box. When `pitcher_win` key is absent, Win defaults to 0 (same behavior as SB in hitter). When present (from Layer-2 scrape), it is used.
- **QS is purely arithmetic**: outs >= 18 AND earnedruns <= 3. No external data needed.
- **Coincidentally-equal PP/UD scores grade**: When platform is unknown but scores happen to be equal (no SB, or SB=0), the disambiguation is trivial — both formulas agree on all lines.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Naming conflict] Used `source_row` instead of `row` as parameter name**
- **Found during:** Task 2 (GREEN implementation)
- **Issue:** `stat_value_for_prop` already uses local variable `row` for `player_stats.get(matched_key)`; adding a `row=` parameter would shadow it
- **Fix:** Parameter named `source_row`; test file updated via sed to use `source_row=row` consistently
- **Files modified:** scripts/sports_system_runner.py, scripts/test_fantasy_score.py
- **Committed in:** d143657 (Task 2 commit)

**2. [Rule 1 - Outdated test] Updated test_stat_value_for_prop.py old NOT-DERIVABLE assertions**
- **Found during:** Task 2 GREEN verification
- **Issue:** Two tests pinned "Hitter/Pitcher Fantasy Score is NOT-DERIVABLE" — now intentionally derivable
- **Fix:** Updated `test_hitter_fantasy_score_not_derivable` → `test_hitter_fantasy_score_now_derivable` (asserts 17.0); updated `test_pitcher_fantasy_score_not_derivable` → `test_pitcher_fantasy_score_ambiguous_abstains` (asserts None when no line provided and QS diverges); removed both from `NOT_DERIVABLE_MLB` corpus set
- **Files modified:** scripts/test_stat_value_for_prop.py
- **Committed in:** d143657 (Task 2 commit)

---

**Total deviations:** 2 auto-fixed (2x Rule 1 — naming conflict and outdated test)
**Impact on plan:** Both auto-fixes necessary for correctness. No scope creep.

## Issues Encountered

None — plan executed cleanly once the naming collision was identified and resolved.

## Known Stubs

None. The 46-row June 8 Fantasy Score residue was resolved manually in UAT (01-UAT.md Test 4); this plan encodes the formula so future runs grade automatically. Future rows with a known platform (PrizePicks/Underdog in Reasoning) and available components will grade in-process.

## Threat Flags

No new network endpoints, auth paths, or schema changes introduced. The `source_row` parameter is read-only metadata threading.

T-01-G2-01 (platform spoofing): Mitigated — "unknown" when ambiguous; disagreement abstain pinned by 5 disagreement tests.
T-01-G2-02 (partial box total): Mitigated — abstain when required component absent, pinned by 3 missing-component tests.
T-01-G2-03 (wrong-platform grade): Mitigated — exact table when platform known; agreement-grade when platform unknown and grades agree.

## Self-Check: PASSED

Files created:
- scripts/test_fantasy_score.py — FOUND
- .planning/phases/01-trustworthy-results/01-10-SUMMARY.md — this file

Commits:
- 0479d96 (RED test) — FOUND
- d143657 (GREEN implementation) — FOUND

## Next Phase Readiness

- GAP 2 (Fantasy Score encoding) is closed. The 46-row June 8 residue class will now grade automatically on future runs when the platform is known from the source prop.
- Remaining GAPs from 01-UAT: GAP 1 (DNP → VOID), GAP 3 (gate test idempotency), GAP 4 (prop PnL = 0) — not in scope for this plan.
- Phase 01 plan 10 is the final plan in the gap-closure wave.

---
*Phase: 01-trustworthy-results*
*Completed: 2026-06-23*
