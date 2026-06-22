---
phase: 01-trustworthy-results
plan: 2
subsystem: grading
tags: [name-matching, espn-api, mlb, nba, namespacing, hit-types, tdd]

# Dependency graph
requires:
  - "01-1 (ESPN fixtures and oracle ledger — mlb_summary.json, nba_summary.json, stat_corpus.json)"
provides:
  - "_canonical_name(name) -> str — grading-local NFKD accent fold + punct/suffix normalizer"
  - "name_match(prop_name, boxscore_keys) -> str | None — 4-tier resolution with abstain policy"
  - "espn_player_stats_by_event — batting/pitching namespace split for MLB + per-player _hit_counts from plays[]"
  - "scripts/test_name_match.py — 24 offline unit tests for name matching"
  - "scripts/test_espn_namespacing.py — 19 fixture-backed tests for namespace split and NBA regression"
affects:
  - "01-3 (stat_value_for_prop disposition table consumes name_match + batting/pitching namespaces)"
  - "01-4 (espn_player_stats_by_event now returns namespaced dict)"

# Tech tracking
tech-stack:
  added:
    - "unicodedata (stdlib) — NFKD normalization for accent folding in _canonical_name"
  patterns:
    - "TDD red-green per task: failing test committed before implementation"
    - "Abstain-on-ambiguity: name_match returns None rather than guessing when 2+ keys match"
    - "Namespace sub-dict pattern: MLB groups keyed by group_data.get('type') into batting/pitching sub-dicts"
    - "Plays-derived hit counts: _hit_counts attached to batting sub-dict from gamepackageJSON.plays[].type.type"

key-files:
  created:
    - scripts/test_name_match.py
    - scripts/test_espn_namespacing.py
  modified:
    - scripts/sports_system_runner.py

key-decisions:
  - "Group identity for MLB uses group_data.get('type') in ('batting','pitching') — the 'name' field is None for both MLB and NBA in confirmed fixtures"
  - "NBA single-group path (type==None) keeps byte-identical flat key output — no batting/pitching sub-dicts; all existing alias_pairs and FG/3PT/FT split-on-'-' logic preserved verbatim"
  - "Hit-type counts stored as batting._hit_counts dict keyed by plays type.type values: 'single','double','triple','home-run' — atBats top-level key is absent from fixture (oracle RECLASSIFY #8)"
  - "name_match Tier 3 (initial bridge) abstains when 0 OR 2+ keys match — strictly no-guess"
  - "name_match Tier 4 (last-name-unique) also abstains on 0 or 2+ matches"
  - "normalize_player_name:3483 left byte-identical (used in non-grading pp_lookup:3520; widening blast radius prohibited)"
  - "Batter->player-name cross-reference via athlete.id -> name map built during boxscore scan, then joined to plays[] participants with type=='batter'"

# Metrics
duration: ~25min
completed: 2026-06-22
---

# Phase 1 Plan 2: Layer-1 Matching Primitives Summary

**_canonical_name + name_match (4-tier, abstain on ambiguity) and espn_player_stats_by_event MLB batting/pitching namespace split with per-player hit-type counts from plays[], with NBA output byte-identical to pre-change**

## Performance

- **Duration:** ~25 min
- **Completed:** 2026-06-22
- **Tasks:** 2 (TDD: test → impl per task)
- **Files modified/created:** 3

## Accomplishments

- Added `_canonical_name(name: Any) -> str` to `sports_system_runner.py` at line 3494: NFKD accent fold + punct-to-space + suffix drop (jr/sr/ii/iii/iv) + whitespace collapse. Grading-local; does not touch `normalize_player_name`.
- Added `name_match(prop_name, boxscore_keys, game_roster=None) -> str | None` at line 3525: 4-tier resolution (exact → canonical → initial-bridge → last-name-unique) with strict abstain-on-ambiguity policy (returns None rather than guessing when 2+ keys qualify at Tiers 3–4). The J. Williams / {jalen williams, jaylin williams} case returns None by design.
- Modified `espn_player_stats_by_event` to replace the flat `stats.setdefault(name.lower(), {})` write (which clobbered shared MLB labels) with:
  - MLB groups (type="batting" or "pitching"): each player row now has `row["batting"]` and/or `row["pitching"]` sub-dicts, eliminating the Will Vest / shared-label clobber (hits, runs, walks, strikeouts, homeRuns, pitches all isolated per group)
  - NBA groups (type=None): flat key output preserved verbatim — same FG/3PT/FT split-on-"-" logic, same alias_pairs, same key names/values (byte-identical confirmed by test fixture)
  - Per-player `_hit_counts` dict ({"single": N, "double": N, "triple": N, "home-run": N}) attached to `row["batting"]` derived from `gamepackageJSON.plays[].type.type` matched by batter `athlete.id` — no scrape needed for Total Bases / Singles derivation

## Task Commits

1. **Task 1 RED — test_name_match.py (failing):** `25e4d28`
2. **Task 1 GREEN — _canonical_name + name_match implementation:** `8589d5f`
3. **Task 2 RED — test_espn_namespacing.py (failing):** `1363f9c`
4. **Task 2 GREEN — espn_player_stats_by_event namespace split + hit counts:** `2af9122`

## Key Implementation Details for Plan 01-3

### Group identity strings (critical for plan 01-3 consumption)

| Sport | group_data.get("type") value | Sub-dict key |
|-------|------------------------------|--------------|
| MLB batting group | `"batting"` | `row["batting"]` |
| MLB pitching group | `"pitching"` | `row["pitching"]` |
| NBA (single group) | `None` | flat dict (no sub-dict) |

### plays[] hit-type path (plan 01-3 Total Bases / Singles derivation)

- Array path: `data["gamepackageJSON"]["plays"]`
- Hit event filter: `play["type"]["type"] in {"single", "double", "triple", "home-run"}`
- Batter identification: `participant["type"] == "batter"` and `participant["athlete"]["id"]`
- Stored as: `row["batting"]["_hit_counts"]` = `{"single": N, "double": N, "triple": N, "home-run": N}`
- Note: `"home-run"` (with hyphen) is the ESPN play type string, NOT "homerun" or "hr"

### Confirmed fixture keys for plan 01-3 (from oracle ledger, preserved here for traceability)

**MLB batting keys** (post-lowercase): `hits-atbats`, `atbats`, `runs`, `hits`, `rbis`, `homeruns`, `walks`, `strikeouts`, `pitches`, `avg`, `onbasepct`, `slugavg`

**MLB pitching keys** (post-lowercase): `fullinnings.partinnings`, `hits`, `runs`, `earnedruns`, `walks`, `strikeouts`, `homeruns`, `pitches-strikes`, `era`, `pitches`

**Pitching Outs parsing**: value at `row["pitching"]["fullinnings.partinnings"]` is stored as a float (e.g. 1.0 for "1.0"). The raw string was "1.0" meaning 1 full inning + 0/3 outs. Plan 01-3's `innings_to_outs` must parse the stored float as: `int(val) * 3 + round((val % 1) * 10)` where .1 = 1/3 out and .2 = 2/3 out.

## Deviations from Plan

**1. [Rule 1 - Bug] Test value corrections for NBA pre-change snapshot**
- **Found during:** Task 2 RED (initial run)
- **Issue:** The pre-computed NBA expected values in the test had incorrect rebounds (7.0) and assists (6.0) for Wembanyama; the real fixture values are rebounds=13.0, assists=1.0
- **Fix:** Corrected expected values in test to match fixture (captured by running the pre-change logic against the actual NBA fixture JSON)
- **Files modified:** scripts/test_espn_namespacing.py (in the same RED commit phase before the GREEN impl)
- **Impact:** None to production; test oracle now correctly reflects fixture

**2. [Rule 1 - Bug] Test used `assertIs` for string identity (too strict)**
- **Found during:** Task 1 GREEN first run
- **Issue:** `assertIs(result, "giannis antetokounmpo")` fails because Python doesn't guarantee string object identity for runtime-constructed strings
- **Fix:** Changed to `assertEqual` (correct semantic — value equality is what matters)
- **Files modified:** scripts/test_name_match.py

## Known Stubs

None — this plan adds matching primitives only. No data-flow wiring to the grading path yet (that is plan 01-3).

## Threat Flags

None — no new network endpoints, no new auth paths, no new file access patterns introduced.

## Self-Check

- `scripts/sports_system_runner.py` — FOUND (modified, contains `def _canonical_name`, `def name_match`, updated `espn_player_stats_by_event`)
- `scripts/test_name_match.py` — FOUND (24 tests, 0 failures)
- `scripts/test_espn_namespacing.py` — FOUND (19 tests, 0 failures)
- `normalize_player_name:3483` byte-identical (grep confirmed)
- Commit 25e4d28 (RED test_name_match): FOUND
- Commit 8589d5f (GREEN _canonical_name + name_match): FOUND
- Commit 1363f9c (RED test_espn_namespacing): FOUND
- Commit 2af9122 (GREEN namespace split): FOUND

## Self-Check: PASSED

---
*Phase: 01-trustworthy-results*
*Completed: 2026-06-22*
