---
phase: 02-slip-reconstruction-and-grading
plan: 1
subsystem: slip-grading
tags: [grading, box-score, offline-test, money-safety, espn]
dependency_graph:
  requires: [01-trustworthy-results]
  provides: [slip-leg-grading-core]
  affects: [02-2-slip-aggregation, 02-3-backfill]
tech_stack:
  added: []
  patterns: [importlib-reuse, offline-injection, abstain-sentinel]
key_files:
  created:
    - scripts/grade_slips.py
    - scripts/test_grade_slips_legs.py
  modified: []
decisions:
  - "LEG_PENDING = 'PENDING' chosen as abstain sentinel — matches P1 grade_prop's PENDING token so Wave 2 can treat unresolved legs uniformly"
  - "build_date_box_scores accepts injected player_stats_by_sport for offline use; online path merges all final-game box scores per sport"
  - "grade_leg reuses stat_value_for_prop unchanged; any None return → LEG_PENDING (never LOSS)"
  - "'hits runs rbis' (space-sep, actual slip leg stat_type) is NOT-DERIVABLE in P1 table — abstains correctly (Wave 2/3 will need mapping or manual reconciliation)"
metrics:
  duration_minutes: 15
  tasks_completed: 2
  files_changed: 2
  completed_date: "2026-06-22"
---

# Phase 02 Plan 1: Slip-Leg Grading Core Summary

**One-liner:** Date-wide ESPN box-score merge and per-leg WIN/LOSS/PUSH grader reusing P1 stat_value_for_prop, with LEG_PENDING abstain on unresolved stats.

## What Was Built

### `scripts/grade_slips.py`
Core slip-leg grading module exporting:

- `LEG_PENDING: str = "PENDING"` — abstain sentinel; the same token P1's `grade_prop` uses for unresolved props.
- `build_date_box_scores(date, player_stats_by_sport=None) -> dict[str, dict]` — returns injected fixture unchanged (offline path); otherwise iterates `espn_scoreboard_games_for_date` for NBA + MLB, keeps `status == "final"` games, calls `espn_player_stats_by_event` per event_id, and merges into `{"NBA": {...}, "MLB": {...}}`. First non-empty row wins when a player key appears in multiple games.
- `grade_leg(leg, box_scores) -> dict[str, str | float | None]` — selects per-sport stats via `leg["sport"]`; calls P1 `stat_value_for_prop`; if value is None → `{"result": LEG_PENDING, "actual": None, ...}`; otherwise computes WIN/LOSS/PUSH from actual vs line honoring OVER/UNDER side (mirrors `grade_prop` diff convention). Returns `{"result", "actual", "source", "confidence"}`.

No workbook writes; no side effects at import time. Importable from scripts/ via `python3`.

### `scripts/test_grade_slips_legs.py`
Offline unittest (12 tests, stdlib `unittest`). Fixture box scores:
- **MLB — Freddie Freeman** (batting: 3 hits / 2 runs / 1 RBI) with `batting`/`pitching` sub-dicts.
- **MLB — Shane Bieber** (pitching: 6 striker strikeouts / 90 pitches).
- **NBA — LeBron James** (flat: 30 pts / 10 reb / 5 ast).

Test cases:
| Case | Leg | Expected |
|------|-----|----------|
| OVER win (NBA) | LeBron 30 pts vs 25.5 OVER | WIN |
| OVER win (MLB) | Freeman 3 hits vs 1.5 OVER | WIN |
| OVER loss (NBA) | LeBron 5 ast vs 7.5 OVER | LOSS |
| OVER loss (MLB) | Bieber 6 K vs 6.5 OVER | LOSS |
| PUSH (NBA) | LeBron 10 reb vs 10.0 OVER | PUSH |
| PUSH (MLB) | Freeman 3 hits vs 3.0 OVER | PUSH |
| UNDER win | LeBron 5 ast vs 7.5 UNDER | WIN |
| UNDER loss | LeBron 30 pts vs 25.5 UNDER | LOSS |
| Absent player (abstain) | "ghost player" pts | LEG_PENDING — NOT LOSS |
| NOT-DERIVABLE stat (abstain) | LeBron "fantasy score" | LEG_PENDING — NOT LOSS |
| Unrecognised MLB stat (abstain) | Freeman "hits runs rbis" (space-sep) | LEG_PENDING — NOT LOSS |
| Injection path | build_date_box_scores(..., fixture) | returns fixture unchanged |

All 12 tests pass, fully offline, exits 0 in ~0.004s.

## Key Discovery

Real slip leg `stat_type = "hits runs rbis"` (space-separated, as emitted by `build_slips.py`) does NOT match the P1 disposition table entry `"hits+runs+rbis"` (plus-separated). The stat correctly abstains to LEG_PENDING. Wave 2/3 planning should either:
1. Map `"hits runs rbis"` to `"hits+runs+rbis"` in a stat normalization step before calling `grade_leg`, or
2. Accept that these legs are PENDING and require manual reconciliation.
This is NOT a bug in grade_slips.py — the abstain behavior is the correct money-safe outcome.

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 — grade_slips.py | 09b49a3 | feat(02-1): date-wide box-score merge + per-leg grader |
| 2 — test file | bf4d4d7 | test(02-1): offline unittest for grade_leg WIN/LOSS/PUSH/abstain cases |

## Deviations from Plan

None — plan executed exactly as written. The `build_date_box_scores` injection path, LEG_PENDING sentinel, `grade_leg` OVER/UNDER convention, and all test cases match the plan specification.

## Threat Model Compliance

| Threat | Mitigation Applied |
|--------|-------------------|
| T-02-01: fabricated verdict on unresolved leg | grade_leg returns LEG_PENDING (not LOSS) on any None from stat_value_for_prop; 3 abstain test cases explicitly assert result != "LOSS" |
| T-02-02: name spoofing | Reuses P1 name_match unchanged (abstains on ambiguity); no new matching logic introduced |
| T-02-03: network in tests | build_date_box_scores injection path; all 12 tests run fully offline |

## Self-Check: PASSED

- [x] `scripts/grade_slips.py` exists and imports cleanly
- [x] `scripts/test_grade_slips_legs.py` exists and exits 0
- [x] Commits 09b49a3 and bf4d4d7 verified in git log
- [x] No modifications to `sports_system_runner.py`
- [x] No workbook writes in `grade_slips.py`
