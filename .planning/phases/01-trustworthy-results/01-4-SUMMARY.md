---
phase: 01-trustworthy-results
plan: 4
subsystem: grading
tags: [money-safety, backfill, terminal-guard, parlay, side-parser, tdd]

# Dependency graph
requires:
  - "01-3 (grade_prop 5-tuple + provenance + stat_value_for_prop disposition table)"
provides:
  - "TERMINAL_RESULTS = frozenset({'WIN','LOSS','PUSH','VOID'}) — module constant"
  - "existing_result_map(results_ws, date, sport_label) -> dict[str, str] returning {ref: result_str}"
  - "grade_game_in_workbook three loop guards EVOLVED to value-aware TERMINAL_RESULTS (casing-robust)"
  - "Parlay full-leg-set merge: aggregates WIN+LOSS+PUSH from persisted Results; ABSTAINS on incomplete leg set"
  - "_KNOWN_PROP_STATS tuple — disposition-table stat strings for ref parsing"
  - "parse_prop_ref(ref) -> (player, stat, line) — multi-word stat segmentation from PROP: ref"
  - "grade_prop _side_unrecoverable abstain policy — never guesses Over/Under on real money"
  - "scripts/test_backfill_regrade.py — 26 TDD tests: TERMINAL_RESULTS, existing_result_map, guard normalization, MANUAL REVIEW overwrite, casing-variant skip, no dup rows, no double-count"
  - "scripts/test_parlay_leg_backfill.py — 2 TDD tests: parlay resolves from full persisted leg set; abstains on incomplete"
  - "scripts/test_side_parser.py — 13 TDD tests: multi-word stat segmentation; abstain-to-MANUAL-REVIEW on unrecoverable side"
affects:
  - "01-5 (Layer-2 scraped fallback — extends grade_game_in_workbook prop call site using parse_prop_ref for backfill rows)"
  - "01-6 (backfill execution — relies on this reconciliation path being money-safe)"

# Tech tracking
tech-stack:
  added:
    - "TERMINAL_RESULTS frozenset — guards all three grade_game_in_workbook loops against settled-bet re-grade"
    - "existing_result_map() — {ref: result_str} mirror of existing_result_refs (adds Result column read)"
    - "_KNOWN_PROP_STATS tuple — sourced from stat_value_for_prop disposition table; powers parse_prop_ref"
    - "parse_prop_ref() — multi-word-aware PROP: ref segmentation (longest stat match from known list)"
    - "grade_prop _side_unrecoverable abstain branch — returns PENDING rather than guessing Over/Under"
    - "Parlay leg merge: declared_leg_refs (from Legs column) + persisted terminal results + this-run graded"
  patterns:
    - "EVOLVED guard (not reverted): existing_result_refs replaced with existing_result_map + TERMINAL_RESULTS"
    - "Abstain-on-ambiguity: unrecoverable side → PENDING (MANUAL REVIEW escalation), never a terminal guess"
    - "Full-leg-set completeness: parlay checks ALL declared legs are terminal before computing verdict"
    - "TDD red-green per task: failing test committed before implementation"

key-files:
  created:
    - scripts/test_backfill_regrade.py
    - scripts/test_parlay_leg_backfill.py
    - scripts/test_side_parser.py
  modified:
    - scripts/sports_system_runner.py

key-decisions:
  - "TERMINAL_RESULTS is a frozenset (immutable module constant); MANUAL REVIEW and PENDING are intentionally absent — they re-enter grading on backfill re-runs"
  - "existing_result_map supersedes existing_result_refs at the guard site; existing_result_refs is preserved (still used by tests/callers that only need the set)"
  - "Parlay Legs column (pipe-separated) is the authoritative source of declared constituent refs — if Legs is empty, fall back to this-run graded legs only (no regression for non-backfill parlays)"
  - "parse_prop_ref uses _KNOWN_PROP_STATS longest-match (multi-word first) rather than naive rsplit — handles Hits Allowed/Total Bases/Pitcher Strikeouts without mis-segmentation"
  - "_side_unrecoverable flag in grade_prop is the backfill signal; callers set it when re-parsing from PROP: ref (where Over/Under is absent); normal rows with Opponent/Description set are byte-identical"
  - "Double-sync idempotency: sync_master_and_bankroll(date, []) with empty newly_graded only rebuilds Daily Log/Bankroll from existing Pick History — no double-count confirmed by test"

# Metrics
duration: ~15min
completed: 2026-06-22
---

# Phase 1 Plan 4: Money-Safe Backfill Guard + Parlay Full-Leg-Set + Side Re-Parser Summary

**Value-aware TERMINAL_RESULTS guard + parlay full-leg-set money-safety + multi-word-aware PROP: ref side re-parser — the money-safety layer of the trustworthy-results backfill**

## Performance

- **Duration:** ~15 min
- **Completed:** 2026-06-22
- **Tasks:** 2 (TDD: test → impl per task)
- **Files modified/created:** 4 (3 new test files + sports_system_runner.py)

## Accomplishments

### Task 1 — Value-aware TERMINAL_RESULTS guard + parlay full-leg-set money-safety fix

**Change 1 — TERMINAL_RESULTS guard (evolved, not reverted):**

Added `TERMINAL_RESULTS = frozenset({"WIN","LOSS","PUSH","VOID"})` module constant.

Added `existing_result_map(results_ws, date, sport_label) -> dict[str, str]` mirroring `existing_result_refs` but also reading the `Result` column via `result_headers`. Returns `{ref: current_result_str}`.

Replaced the call at `grade_game_in_workbook` from `already = existing_result_refs(...)` to `already = existing_result_map(...)`.

Changed all three loop guards (spread/total, prop, parlay) from the value-blind `if ref in already: continue` to:
```python
if (already.get(ref) or "").strip().upper() in TERMINAL_RESULTS: continue
```

The `.strip().upper()` normalization makes the guard robust to legacy/casing/whitespace variants in stored data:
- `"Win"` (titlecase) → TERMINAL, skipped
- `"push "` (trailing space) → TERMINAL, skipped
- `" VOID"` (leading space) → TERMINAL, skipped
- `"MANUAL REVIEW"` → NOT in TERMINAL_RESULTS, falls through → re-gradeable
- `"PENDING"` → NOT in TERMINAL_RESULTS, falls through → re-gradeable
- `""` / `None` → NOT in TERMINAL_RESULTS, falls through → re-gradeable

A settled real-money bet in any casing is never re-graded and flipped. The original value-blind `if ref in already: continue` form is confirmed gone (`grep` returns empty).

**Change 2 — Parlay full-leg-set merge (money-safety fix):**

Before computing a parlay verdict, the code now assembles the FULL leg-result set by:
1. Reading the `Legs` column (pipe-separated declared leg refs) from the parlay row
2. Looking up each declared ref in `already` (persisted terminal results from Results sheet)
3. Overlaying with this-run freshly-graded results from `graded`

If ALL declared legs have terminal results after the merge → compute verdict from the merged set.
If ANY leg is still non-terminal/absent → parlay ABSTAINS (the loop continues, `upsert_result_row` is NOT called → the parlay stays at its prior result).

Without this fix: a MANUAL REVIEW parlay whose legs settled in a prior run would re-aggregate against a partial `graded` list (those terminal legs were skipped by the new guard) and could flip a true LOSS to WIN.

**Double-sync idempotency confirmed:** `sync_master_and_bankroll(date, [])` with empty `newly_graded` only rebuilds Daily Log/Bankroll from existing Pick History (no append). A regression test pins this behavior.

### Task 2 — Multi-word-aware side re-parser from PROP: ref, abstaining on ambiguity

Added `_KNOWN_PROP_STATS` tuple (sourced from `stat_value_for_prop` disposition table; multi-word stats listed before single-word for longest-match priority).

Added `parse_prop_ref(ref) -> tuple[str, str | None, float | None]` helper:
- Strips "PROP:" prefix, locates trailing numeric Line float token
- Iterates stat_len from max to 1 (longest match first) matching `" ".join(tokens)` against `_KNOWN_PROP_STATS`
- Returns `(player, stat_original_casing, line)` on success
- Falls back to last-token-as-stat on no known match
- Returns `(body, None, None)` when ref cannot be parsed (too few tokens)

Test coverage for multi-word stat formats:
- `"PROP:Pablo Lopez Hits Allowed 5.5"` → stat=`"Hits Allowed"`, line=5.5 ✓
- `"PROP:Yordan Alvarez Total Bases 1.5"` → stat=`"Total Bases"`, line=1.5 ✓
- `"PROP:Pablo Lopez Pitcher Strikeouts 6.5"` → stat=`"Pitcher Strikeouts"`, line=6.5 ✓

Added `_side_unrecoverable` abstain policy to `grade_prop`:
- When a row has `_side_unrecoverable=True` AND `Opponent/Description` has no Over/Under text, return `("PENDING", None, "Side unrecoverable...", "manual", 0.0)` instead of defaulting "Over"
- This prevents a real-money 50/50 guess on backfill rows where the PROP: ref has no Over/Under
- Normal rows with Over/Under in `Opponent/Description` are byte-identical (no regression)

## Task Commits

1. **Task 1 RED — test_backfill_regrade.py + test_parlay_leg_backfill.py (failing):** `15d45e3`
2. **Task 1 GREEN — TERMINAL_RESULTS guard + parlay full-leg-set merge:** `64bbc3e`
3. **Task 2 RED — test_side_parser.py (failing):** `c9b91d7`
4. **Task 2 GREEN — parse_prop_ref + _KNOWN_PROP_STATS + grade_prop abstain:** `ab92a7b`

## Key Implementation Details for Plans 01-5 and 01-6

### parse_prop_ref usage in backfill path (plan 01-5 wiring)

When a backfill prop row has null structured columns but a valid PROP: ref, plan 01-5's grading path should:
```python
player, stat, line = parse_prop_ref(pick_ref)
if stat is not None and line is not None:
    row["Player Name"] = player
    row["Stat"] = stat
    row["Line"] = line
    row["_side_unrecoverable"] = True  # signal grade_prop to abstain on side
    result, actual, note, res_src, res_conf = grade_prop(row, player_stats, True)
    # If result is PENDING and note contains "Side unrecoverable" → stays MANUAL REVIEW
```

### The TERMINAL_RESULTS guard shape (confirmed for plan 01-6 backfill executor)

```python
# In grade_game_in_workbook — the evolved guard
already = existing_result_map(results_ws, date, sport_label)
# ...
if (already.get(ref) or "").strip().upper() in TERMINAL_RESULTS: continue
```

### Parlay Legs column dependency (plan 01-6 pick generation)

The parlay full-leg-set merge reads the `Legs` column (pipe-separated PROP: refs). For plan 01-6's backfill to resolve parlays, the generated parlay rows must have `Legs` populated with the exact constituent PROP: ref strings matching the Results sheet entries.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test fixture used "Home Team" column not in PROPS_HEADERS**
- **Found during:** Task 1 GREEN first run
- **Issue:** `test_backfill_regrade.py` attempted to set `props_ws.cell(r, props_cols["Home Team"])` but "Home Team" is not in `PROPS_HEADERS`
- **Fix:** Removed the "Home Team" cell write; added "Team" column with the team name (which IS in PROPS_HEADERS) so `game_matches_row`'s text-search fallback can match the prop to the game
- **Files modified:** scripts/test_backfill_regrade.py
- **Commit:** within Task 1 GREEN commit (64bbc3e)

**2. [Rule 1 - Bug] Test assertion for side abstain required `_side_unrecoverable` signal in grade_prop**
- **Found during:** Task 2 GREEN — `test_grade_prop_with_ref_parse_abstains_on_ambiguous_side` failed because `grade_prop` defaulted "Over" on empty `Opponent/Description` (a confidently-wrong guess)
- **Fix:** Added `_side_unrecoverable` check in `grade_prop` — when row has this flag AND no Over/Under text in `Opponent/Description`, returns PENDING rather than guessing
- **Files modified:** scripts/sports_system_runner.py
- **Commit:** within Task 2 GREEN commit (ab92a7b)

## Known Stubs

None — all grading paths resolve to a value or explicitly abstain. The `_side_unrecoverable` flag is a documented API for the backfill path (plan 01-5), not a placeholder.

## Threat Flags

| Flag | File | Description |
|------|------|-------------|
| None | — | No new network endpoints, auth paths, or file access patterns introduced |

All three STRIDE threat mitigations from the plan's threat register are implemented and pinned by tests:
- **T-01-07 (Tampering / TERMINAL_RESULTS guard):** `.strip().upper()` normalization pinned by `TestTerminalGuardNormalization` (9 cases)
- **T-01-08 (Elevation / parlay partial-leg):** Full-leg-set merge + abstain-on-incomplete pinned by `TestParlayFullLegSetBackfill`
- **T-01-09 (Spoofing / side re-parser):** Abstain-to-MANUAL-REVIEW pinned by `TestSideAbstainPolicy`
- **T-01-10 (Repudiation / double-sync):** Empty-call rebuild-only pinned by `test_double_sync_does_not_double_count`

## Self-Check

- `scripts/sports_system_runner.py` — FOUND (modified: TERMINAL_RESULTS, existing_result_map, _KNOWN_PROP_STATS, parse_prop_ref, grade_game_in_workbook guards, parlay full-leg-set block, grade_prop _side_unrecoverable branch)
- `scripts/test_backfill_regrade.py` — FOUND (26 tests, 0 failures)
- `scripts/test_parlay_leg_backfill.py` — FOUND (2 tests, 0 failures)
- `scripts/test_side_parser.py` — FOUND (13 tests, 0 failures)
- Old guard `if ref in already: continue` deleted: `grep "if ref in already"` returns empty (CONFIRMED)
- `TERMINAL_RESULTS` exists at module level: `grep "TERMINAL_RESULTS"` confirms constant + 4 guard usages (CONFIRMED)
- `existing_result_map` function exists after `existing_result_refs` (CONFIRMED)
- `parse_prop_ref` function exposed at module level (CONFIRMED — `runner.parse_prop_ref` importable)
- Commit 15d45e3 (RED test_backfill + test_parlay): FOUND
- Commit 64bbc3e (GREEN TERMINAL_RESULTS guard + parlay): FOUND
- Commit c9b91d7 (RED test_side_parser): FOUND
- Commit ab92a7b (GREEN parse_prop_ref + abstain): FOUND

## Self-Check: PASSED

---
*Phase: 01-trustworthy-results*
*Completed: 2026-06-22*
