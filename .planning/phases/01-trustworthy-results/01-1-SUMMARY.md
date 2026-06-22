---
phase: 01-trustworthy-results
plan: 1
subsystem: testing
tags: [espn-api, testdata, fixtures, oracle, mlb, nba, json]

# Dependency graph
requires: []
provides:
  - "scripts/testdata/espn_summary/mlb_summary.json — real ESPN MLB boxscore with Will Vest two-way player (batting+pitching) and 573-entry plays array"
  - "scripts/testdata/espn_summary/nba_summary.json — real ESPN NBA Finals boxscore with single-group stats per team"
  - "scripts/testdata/stat_corpus.json — 94 stat strings (59 NBA + 35 MLB) from live Props sheets"
  - "scripts/testdata/README.md — oracle ledger confirming exact ESPN key strings with 8 RECLASSIFY flags"
affects:
  - "01-trustworthy-results"
  - "plan 01-2 (name_match tests use corpus)"
  - "plan 01-3 (disposition table built against confirmed keys)"
  - "plan 01-4 (espn_player_stats_by_event namespace split validated against fixtures)"

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "testdata-first oracle pattern: capture real API fixtures before writing disposition logic so key mismatches surface as test failures, not silent MANUAL REVIEWs in production"

key-files:
  created:
    - scripts/testdata/espn_summary/mlb_summary.json
    - scripts/testdata/espn_summary/nba_summary.json
    - scripts/testdata/stat_corpus.json
    - scripts/testdata/README.md

key-decisions:
  - "MLB fixture: game 401815839 (Detroit Tigers vs Chicago White Sox, 2026-06-21) — selected because Will Vest appears in BOTH batting and pitching statistics groups (the two-way/shared-label collision the namespace split must fix)"
  - "NBA fixture: game 401859966 (Knicks vs Spurs NBA Finals Game 3, 2026-06-10) — single statistics group per team, group type/name fields are None"
  - "Group identity uses group_data.get('type') not get('name') — 'name' field is None for both sports in these fixtures; 'type' is 'batting'/'pitching' for MLB and None for NBA"
  - "atBats top-level key is ABSENT from gamepackageJSON — Total Bases / Singles / Doubles derivation must use gamepackageJSON.plays[].type.type values, not an atBats array"
  - "offensiveRebounds/defensiveRebounds are camelCase in fixture keys; runner lowercases them to offensiverebounds/defensiverebounds — disposition table must use the lowercased forms"
  - "fullInnings.partInnings is a SINGLE dotted key (not two separate keys) with string value like '6.2' where .1=1/3 out and .2=2/3 out (not decimals)"
  - "pitches key exists in BOTH batting and pitching groups with different meanings — namespace split required before Pitches Thrown can resolve correctly"

patterns-established:
  - "Test oracle pattern: confirm ESPN key strings from real fixtures before implementing disposition table — any RECLASSIFY in README.md must be incorporated into plan 01-3 implementation"
  - "Stat corpus sourced from live workbooks (Props + Player Props sheets), not assumed — ensures corpus covers all real stat variants the grading path will encounter"

requirements-completed: [RESULTS-02, RESULTS-03]

# Metrics
duration: 11min
completed: 2026-06-22
---

# Phase 1 Plan 1: ESPN Fixtures and Stat Corpus Summary

**Real ESPN summary fixtures captured (MLB two-way player + NBA Finals), stat corpus enumerated from live Props sheets, and 8 RECLASSIFY corrections to the spec's assumed key strings recorded in the oracle ledger before any disposition logic is written**

## Performance

- **Duration:** 11 min
- **Started:** 2026-06-22T07:05:27Z
- **Completed:** 2026-06-22T07:16:04Z
- **Tasks:** 2
- **Files created:** 4

## Accomplishments

- Captured real ESPN CDN summary JSON for MLB game 401815839 (Detroit Tigers vs White Sox, 2026-06-21), which contains Will Vest in both the batting group and pitching group — confirming the shared-label collision that Component 4's namespace split must fix, with 573 plays entries confirming the `plays` array is the correct source for hit-type derivation
- Captured real ESPN CDN summary JSON for NBA Finals game 401859966 (Knicks vs Spurs Game 3, 2026-06-10) with a single statistics group per team and no type/name field on the group object
- Built `stat_corpus.json` (94 entries: 59 NBA + 35 MLB) from all available live Props and Player Props sheets in `data/nba/*.xlsx` and `data/mlb/*.xlsx`, including Total Bases, Singles, Pitching Outs, Hitter/Pitcher Fantasy Score, and all NOT-DERIVABLE specials
- Produced `README.md` oracle ledger with 8 RECLASSIFY corrections that plan 01-3 must incorporate before implementing the disposition table

## Task Commits

1. **Task 1: Capture the two ESPN summary fixtures** - `26cb86c` (feat)
2. **Task 2: Enumerate the stat corpus and record the confirmed key strings** - `92e581c` (feat)

**Plan metadata:** (in final commit below)

## Files Created/Modified

- `scripts/testdata/espn_summary/mlb_summary.json` — Full ESPN CDN response for MLB game 401815839; contains `gamepackageJSON.boxscore.players` with batting+pitching groups and Will Vest in both; `gamepackageJSON.plays` with 573 entries including type.type values "single", "double", "home-run"
- `scripts/testdata/espn_summary/nba_summary.json` — Full ESPN CDN response for NBA Finals game 401859966; single statistics group per team (group type=None, name=None)
- `scripts/testdata/stat_corpus.json` — 94-entry NBA+MLB stat string union from live Props/Player Props sheets; verified contains "Total Bases"
- `scripts/testdata/README.md` — Oracle ledger: confirmed ESPN key strings, group identity mechanism, two-way player data, all RECLASSIFY flags for plan 01-3

## Decisions Made

- Game selection: chose 401815839 (DET vs CHW) over other 2026-06-21 games because Will Vest (pitcher used as batter in a National League park) is the only player found in BOTH a batting and pitching group across all recent MLB games checked
- Saved full CDN response (not just boxscore sub-object) so the fixture matches exactly what `espn_player_stats_by_event` receives at runtime via `espn_json()`
- Stat corpus sourced from live xlsx workbooks (openpyxl read-only), not hardcoded — ensures real production stat variants are captured
- RECLASSIFY flags recorded in README.md rather than correcting the spec itself, so plan 01-3 can diff against the spec and apply corrections cleanly

## Deviations from Plan

None — plan executed exactly as written. No source files under `scripts/*.py` were modified.

## RECLASSIFY Flags (Critical for Plan 01-3)

The following spec-assumed key strings differ from confirmed fixture keys:

| # | Spec assumed | Confirmed fixture key | After runner lowercase | Impact |
|---|-------------|----------------------|----------------------|--------|
| 1 | `offensiverebounds` | `offensiveRebounds` | `offensiverebounds` | OK — lowercase matches |
| 2 | `defensiverebounds` | `defensiveRebounds` | `defensiverebounds` | OK — lowercase matches |
| 3 | `fieldGoals[0/1]` (assumed) | `fieldGoalsMade-fieldGoalsAttempted` (single key, split on "-") | `fieldgoalsmade-fieldgoalsattempted` | Runner already splits; existing alias to "3-pt made" for 3PT |
| 4 | `threePoint[1]` (assumed) | `threePointFieldGoalsMade-threePointFieldGoalsAttempted` | `threepointfieldgoalsmade-threepointfieldgoalsattempted` | Runner already splits; existing alias |
| 5 | `earnedruns` | `earnedRuns` | `earnedruns` | OK — lowercase matches |
| 6 | `fullInnings` + `partInnings` (assumed separate) | `fullInnings.partInnings` (SINGLE key) | `fullinnings.partinnings` | **CORRECTION NEEDED** — single key, value is string "X.Y" |
| 7 | `pitches` (unique to pitching) | `pitches` in BOTH batting and pitching groups | collision | **NAMESPACE SPLIT REQUIRED** |
| 8 | `atBats` array (spec says plays/atBats) | `gamepackageJSON.atBats` ABSENT | use `plays` only | **CORRECTION NEEDED** — only plays[] available |

Plan 01-3 must implement Pitching Outs parsing as: `parse "X.Y" string from "fullinnings.partinnings" key` where `.1`=1/3 out and `.2`=2/3 out (not decimal fractions).

## Issues Encountered

- Initial search did not find two-way players because the code checked `group_data.get("name")` which is `None` for all MLB groups; fixed to check `group_data.get("type")` which correctly returns `"batting"` / `"pitching"` for MLB groups
- The NBA scoreboard returns empty game lists for dates after June 15 (NBA Finals ended); had to search earlier dates (June 8-10 for Finals games)

## Next Phase Readiness

- Plan 01-2 (name_match unit tests) can now use `stat_corpus.json` as its test oracle; no blockers
- Plan 01-3 (disposition table) must use README.md RECLASSIFY flags — in particular, `fullInnings.partInnings` is a single key and `gamepackageJSON.atBats` is absent (use `plays`)
- Plan 01-4 (ESPN namespace split) must validate against the MLB fixture's Will Vest rows and the NBA fixture's single-group output
- Zero edits to `sports_system_runner.py` confirmed — this plan is parallel-safe

## Self-Check: PASSED

- `scripts/testdata/espn_summary/mlb_summary.json`: FOUND (75,167 lines, Will Vest in batting+pitching confirmed)
- `scripts/testdata/espn_summary/nba_summary.json`: FOUND (49,186 lines, single group confirmed)
- `scripts/testdata/stat_corpus.json`: FOUND (100 lines, 94 entries, "Total Bases" present)
- `scripts/testdata/README.md`: FOUND (268 lines, 13,684 bytes)
- Commit 26cb86c: FOUND
- Commit 92e581c: FOUND

---
*Phase: 01-trustworthy-results*
*Completed: 2026-06-22*
