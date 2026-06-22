---
phase: 01-trustworthy-results
plan: 3
subsystem: grading
tags: [stat-value, provenance, disposition-table, false-positive-fix, tdd, mlb, nba]

# Dependency graph
requires:
  - "01-2 (name_match + espn_player_stats_by_event batting/pitching namespace split + _hit_counts)"
provides:
  - "stat_value_for_prop(player_stats, player, stat) -> tuple[float|None, str, float] — explicit 3-tuple disposition table"
  - "grade_prop(row, player_stats, game_final) -> tuple[str, float|None, str, str, float] — 5-tuple with provenance"
  - "RESULT_HEADERS += [\"Result Source\", \"Result Confidence\"] — additive schema migration"
  - "result_record_from_source — record[\"Result Source\"] / record[\"Result Confidence\"] from extra dict"
  - "grade_game_in_workbook call sites — provenance threaded through every Results row (prop/spread/total/parlay/VOID)"
  - "scripts/test_stat_value_for_prop.py — 103 offline tests: corpus dispositions, false-positive regressions, derived MLB stats"
  - "scripts/test_provenance_plumbing.py — 32 offline tests: 5-tuple shape, pending branches, api/1.0 for spread/total/parlay/VOID"
affects:
  - "01-4 (parlay/guard — builds on grade_prop 5-tuple and extra-dict provenance keys)"
  - "01-5 (Layer-2 scraped fallback — extends grade_game_in_workbook prop call site with resolve_missing_stat wiring)"

# Tech tracking
tech-stack:
  added:
    - "_innings_to_outs_grading() — helper mirroring build_hit_rate_db.py innings_to_outs for grading path"
    - "_canon_stat() — stat canonicalizer (lowercase, collapse +/spaces) for disposition table lookup"
  patterns:
    - "Explicit DIRECT/DERIVED/NOT-DERIVABLE disposition table — no substring fallback"
    - "MLB batting/pitching namespace selection — group tag from stat name (Hitter*/Pitcher*/*Allowed)"
    - "TDD red-green per task: failing test committed before implementation"
    - "Provenance end-to-end: stat_value_for_prop → grade_prop → result_record_from_source → RESULT_HEADERS"

key-files:
  created:
    - scripts/test_stat_value_for_prop.py
    - scripts/test_provenance_plumbing.py
  modified:
    - scripts/sports_system_runner.py

key-decisions:
  - "FG Attempted, FT Attempted, 3-PT Attempted, 3s Attempted, Two Pointers Attempted marked NOT-DERIVABLE: the runner's split-on-hyphen logic at espn_player_stats_by_event stores only the MADE count from 'X-Y' strings; attempted count is discarded and cannot be reconstructed from the flat dict"
  - "Total Bases / Singles / Doubles / Triples derived from batting._hit_counts (plays[].type.type) per plan 01-2 — atBats top-level key absent from fixture (oracle RECLASSIFY #8)"
  - "Pitching Outs parsing: stored float 6.2 → int(6)*3 + int('2') = 20, NOT float division (not 6.2/10)"
  - "MLB stat group selection: 'Hitter Strikeouts'/'Batter Strikeouts' → batting['strikeouts']; 'Pitcher Strikeouts' → pitching['strikeouts']; bare 'Strikeouts' defaults to batting"
  - "Unrecognised stat returns (None, 'manual', 0.0) — no fall-through to substring match"
  - "NOT-DERIVABLE set is explicit: (Combo) props, inning-scoped (1st Inning Runs Allowed etc.), Fantasy Score variants, Stolen Bases, Plate Appearances, period-scoped (1H/1Q), first-N-minutes"

# Metrics
duration: ~10min
completed: 2026-06-22
---

# Phase 1 Plan 3: Disposition Table + Provenance Plumbing Summary

**Explicit DIRECT/DERIVED/NOT-DERIVABLE disposition table for stat_value_for_prop (3-tuple) and end-to-end provenance (Result Source / Result Confidence) on every Results row**

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-06-22
- **Tasks:** 2 (TDD: test → impl per task)
- **Files modified/created:** 3

## Accomplishments

### Task 1 — stat_value_for_prop rewrite

Deleted the substring fallback loop at the old `:4064-4066` (`if s == key or s in key or key in s: return value`) — the false-positive root cause — and replaced with an explicit disposition table:

**NBA DIRECT (→ "api", 1.0):** Points, Rebounds, Assists, Steals, Blocked Shots, Turnovers, Personal Fouls, Offensive Rebounds (`offensiverebounds` key — DISTINCT from total rebounds), Defensive Rebounds (`defensiverebounds` key — DISTINCT from total rebounds).

**NBA DERIVED (→ "api", 0.8):** Blks+Stls (blocks+steals), 3-PT Made (via "3-pt made" alias), FG Made (from `fieldgoalsmade-fieldgoalsattempted` split[0]), FT Made (from `freethrowsmade-freethrowsattempted` split[0]), Two Pointers Made (FG made - 3PT made), all PRA/Pts+Rebs/Pts+Asts/Rebs+Asts combos.

**NBA NOT-DERIVABLE (→ None, "manual", 0.0):** Fantasy Score/Points, Dunks, Double-Double, all period-scoped (1H/1Q), first-N-minutes variants, FG/FT/3PT attempted (attempted count discarded), Two Pointers Attempted, (Combo) two-player props, First FG/3PT Attempt, First to 10+, High Scorer variants, 3+ Points Scored Each Quarter.

**MLB DIRECT (batting group → "api", 1.0):** Hits, Runs, RBIs, Home Runs, Walks/Batter Walks, Hitter Strikeouts/Batter Strikeouts (from batting namespace). **MLB DIRECT (pitching group → "api", 1.0):** Hits Allowed, Earned Runs Allowed, Walks Allowed, Pitcher Strikeouts, Pitches Thrown.

**MLB DERIVED (→ "api", 0.8):** Total Bases (1×single + 2×double + 3×triple + 4×HR from `_hit_counts`), Singles/Doubles/Triples (from `_hit_counts`), Pitching Outs (int(whole)×3 + int(frac[:1]) from `fullinnings.partinnings`), Hits+Runs+RBIs (sum of batting sub-dict keys).

**MLB NOT-DERIVABLE (→ None, "manual", 0.0):** 1st Inning/Inn. variants (Runs Allowed, Walks, Hits, Strikeouts, Pitch Count, Batters Faced), 1-3 Inn. Runs Allowed, Hitter/Pitcher Fantasy Score, Fantasy Points, Pitcher Strikeouts (Combo), Stolen Bases, Plate Appearances.

Added `_innings_to_outs_grading()` helper mirroring `build_hit_rate_db.py:165` and `_canon_stat()` canonicalizer.

### Task 2 — grade_prop 5-tuple + provenance end-to-end

- `grade_prop` signature changed to `-> tuple[str, float|None, str, str, float]` (result, actual, note, source, confidence). All PENDING branches return `("manual", 0.0)`. WIN/LOSS/PUSH carry source/confidence from `stat_value_for_prop`.
- `RESULT_HEADERS` appended `["Result Source", "Result Confidence"]` after `+ MARKET_CONTEXT_FIELDS`. Migration is automatic via `ensure_ws_columns`/`result_headers`; flows to master_pnl Pick History.
- `result_record_from_source` gains `record["Result Source"] = extra.get("Result Source")` and `record["Result Confidence"] = extra.get("Result Confidence")`.
- `grade_game_in_workbook` prop call site: unpacks 5-tuple from `grade_prop`; passes `Result Source`/`Result Confidence` in existing `extra` dict. VOID prop row writes `api/1.0`.
- Spread/total/VOID (picks loop): `extra={"Result Source": "api", "Result Confidence": 1.0}`.
- Parlay: `extra[...] = {"Result Source": "api", "Result Confidence": 1.0}`.

## Task Commits

1. **Task 1 RED — test_stat_value_for_prop.py (failing):** `eb5c1b3`
2. **Task 1 GREEN — stat_value_for_prop disposition table:** `4daccac`
3. **Task 2 RED — test_provenance_plumbing.py (failing):** `25ce807`
4. **Task 2 GREEN — grade_prop 5-tuple + provenance plumbing:** `87ba8b8`

## Key Implementation Details for Plans 01-4 and 01-5

### grade_prop 5-tuple call site shape (plan 01-4 / 01-5 consumption)

```python
result, actual, note, res_src, res_conf = grade_prop(row, player_stats, True)
# → ("WIN"|"LOSS"|"PUSH"|"PENDING", float|None, str, "api"|"manual", float)
```

### extra dict keys for provenance (plan 01-5 scraped path)

When `resolve_missing_stat` returns `("scraped", 0.5)`, the plan 01-5 wiring should:
```python
res_src, res_conf = "scraped", 0.5
extra["Result Source"] = res_src
extra["Result Confidence"] = res_conf
```

Plan 01-5 does NOT call `grade_prop` again — it replaces `res_src`/`res_conf` on the already-unpacked variables before calling `result_record_from_source`.

### The MANUAL REVIEW escalation path (unchanged, now carries provenance)

```python
if result == "PENDING" and "No final stat line" in note:
    result = "MANUAL REVIEW"
    res_src, res_conf = "manual", 0.0
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test assertion contradiction in test_provenance_plumbing.py**
- **Found during:** Task 2 GREEN first run
- **Issue:** `test_loss_under_exact_name_direct_stat_api_1_0` asserted LOSS then immediately asserted WIN (copied comment error from a confused test stub)
- **Fix:** Renamed test to `test_win_under_exact_name_direct_stat_api_1_0` and fixed the single correct assertion (Points UNDER 35.5 with actual=30 → WIN since 30 < 35.5)
- **Files modified:** scripts/test_provenance_plumbing.py
- **Commit:** within Task 2 GREEN commit

**2. [Rule 1 - Bug] FG Attempted / 3-PT Attempted / FT Attempted / 3s Attempted marked NOT-DERIVABLE (spec said DERIVED)**
- **Found during:** Task 1 implementation — analyzing the runner's existing `split-on-"-"` logic
- **Issue:** `espn_player_stats_by_event` at `:5520-5521` splits "X-Y" strings for FG/3PT/FT keys and stores only the MADE count (split[0]); the ATTEMPTED count (split[1]) is discarded. The flat dict `fieldgoalsmade-fieldgoalsattempted: 12.0` is the MADE count, not a tuple.
- **Fix:** Classified FG Attempted, FT Attempted, 3-PT Attempted, 3s Attempted, Two Pointers Attempted as NOT-DERIVABLE. Two Pointers Made (FG made - 3PT made) remains DERIVED since both made counts are available.
- **Files modified:** scripts/test_stat_value_for_prop.py (test expectations), scripts/sports_system_runner.py (disposition table)
- **Impact:** Conservative: these stats continue to produce MANUAL REVIEW (same as before). No false-positive risk. Correctly prevents returning the MADE count when ATTEMPTED is requested.

## Known Stubs

None — all grading paths resolve to a value or explicitly return NOT-DERIVABLE with manual/0.0. No placeholder values.

## Threat Flags

None — no new network endpoints, no new auth paths, no new file access patterns introduced. The RESULT_HEADERS addition is additive and schema-migrated; it cannot corrupt existing workbooks.

## Self-Check

- `scripts/sports_system_runner.py` — FOUND (modified: stat_value_for_prop, grade_prop, RESULT_HEADERS, result_record_from_source, grade_game_in_workbook call sites)
- `scripts/test_stat_value_for_prop.py` — FOUND (103 tests, 0 failures)
- `scripts/test_provenance_plumbing.py` — FOUND (32 tests, 0 failures)
- Substring fallback deleted: `grep "s == key or s in key"` returns empty (CONFIRMED)
- `RESULT_HEADERS` contains "Result Source" and "Result Confidence" at line 278 (CONFIRMED)
- Commit eb5c1b3 (RED test_stat_value_for_prop): FOUND
- Commit 4daccac (GREEN disposition table): FOUND
- Commit 25ce807 (RED test_provenance_plumbing): FOUND
- Commit 87ba8b8 (GREEN 5-tuple + provenance): FOUND

## Self-Check: PASSED

---
*Phase: 01-trustworthy-results*
*Completed: 2026-06-22*
