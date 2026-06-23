---
phase: 01-trustworthy-results
plan: 9
subsystem: grading
tags: [dnp, void, appearance, layer-2, firecrawl, mlb, nba, results, money-safety]

# Dependency graph
requires:
  - "01-5 (resolve_missing_stat + Layer-2 scraped fallback + per-event cache)"
  - "01-7 (prop PnL = 0 / BANKROLL-01)"
provides:
  - "verify_results.player_appearance(players, player, status) -> 'played'|'dnp'|'unknown'"
  - "sports_system_runner.resolve_player_appearance(sport, game, player) -> str"
  - "grade_game_in_workbook MANUAL REVIEW branch: confirmed DNP -> VOID, scraped/1.0, PnL=0"
  - "scripts/test_dnp_void.py — 30 offline tests pinning all three behaviour contracts"
affects:
  - "01-UAT GAP 1 closure (DNP->VOID auto-detection)"

# Tech tracking
tech-stack:
  added:
    - "verify_results.player_appearance() — tri-state (played/dnp/unknown) from scraped box"
    - "sports_system_runner.resolve_player_appearance() — cache-reusing appearance helper"
    - "scripts/test_dnp_void.py — 30 TDD offline tests (RED then GREEN)"
  patterns:
    - "Tri-state appearance signal: 'dnp' requires status=ok + unambiguous absence"
    - "Money-safety gate: VOID only on 'dnp'; 'played'/'unknown' -> MANUAL REVIEW (abstain)"
    - "Cache reuse: resolve_player_appearance shares the 01-5 per-event cache — zero extra subprocess budget"
    - "Degrade-never-crash: any failure/timeout/skip/missing-binary/offline -> 'unknown'"
    - "Flag-gated: resolve_player_appearance inside ENABLE_FIRECRAWL_RESULT_FALLBACK + budget gate"

key-files:
  created:
    - scripts/test_dnp_void.py
  modified:
    - scripts/verify_results.py
    - scripts/sports_system_runner.py

key-decisions:
  - "player_appearance uses _canonical_name (same as the parser) for name normalisation — no separate matching path"
  - "resolve_player_appearance loads verify_results at call time via importlib (not import-time) to avoid coupling"
  - "VOID grading uses res_conf=1.0 (not 0.5) — confirmed absence is high-confidence, unlike partial scraped stat"
  - "DNP check is placed after resolve_missing_stat attempt (if stat was somehow derivable, it wins)"
  - "TestGradeGameDNPToVoid patches save_workbook_atomic + sync_master_and_bankroll to stay fully offline"

# Metrics
duration: ~8min
completed: 2026-06-23
---

# Phase 1 Plan 9: DNP -> VOID Auto-Detection Summary

**When Layer-1 stat resolution returns None and the player confirmably did not play, grade VOID (no action / refund) with scraped/1.0 provenance — the no-stat-line path never produces LOSS (GAP 1 closure)**

## Performance

- **Duration:** ~8 min
- **Completed:** 2026-06-23
- **Tasks:** 2 (RED commit d936ca0; GREEN commit 3d2cb95)
- **Files modified/created:** 3

## Accomplishments

### Task 1 — RED: test_dnp_void.py (30 failing tests)

Created `scripts/test_dnp_void.py` (stdlib unittest, importlib-loaded, fully offline):

Four test sections pin all three behaviour contracts:

**Section 1 — player_appearance in verify_results:**
- Present player (status=ok) → "played" (canonical name matching, case-insensitive)
- Absent player (status=ok) → "dnp" (confirmed; includes empty-box edge case)
- status=skip → "unknown" (transient failure; abstain)
- Empty/None player name → "unknown" (ambiguous)

**Section 2 — resolve_player_appearance in runner:**
- Cached status=ok box + absent player → "dnp"
- Cached status=ok box + present player → "played"
- Cached status=skip envelope → "unknown"
- No cache + no npx → "unknown"
- No event_id → "unknown"
- Budget cap → "unknown"

**Section 3 — grade_game_in_workbook MANUAL REVIEW branch:**
- appearance="dnp" → result="VOID", PnL=0, Result Source="scraped", Result Confidence=1.0
- appearance="played" → result="MANUAL REVIEW"
- appearance="unknown" → result="MANUAL REVIEW"

**Section 4 — Hard money-safety:**
- Confirmed DNP → VOID, never LOSS or WIN
- Unknown appearance → MANUAL REVIEW, never LOSS or WIN
- Flag-OFF gate: resolve_player_appearance not called when ENABLE_FIRECRAWL_RESULT_FALLBACK=False

All 30 tests FAILED on commit d936ca0 (correct RED state, pinning missing functions).

### Task 2 — GREEN: verify_results.py + sports_system_runner.py

**verify_results.py — player_appearance(players, player, status):**
- Uses `_canonical_name()` (same normaliser as parse_espn_box_markdown) for both sides
- Empty/None player name → "unknown"
- status != "ok" → "unknown"
- Player found in canonical-name comparison → "played"
- Player absent + status="ok" → "dnp" (includes empty players dict)

**sports_system_runner.py — resolve_player_appearance(sport, game, player):**
- Loads verify_results at call time via importlib (not import-time coupling)
- Steps 1–4 identical to resolve_missing_stat (preflight, game_id, cache, subprocess)
- Reuses the SAME per-event cache — no extra subprocess budget consumed
- Routed through `_subprocess_run_with_retry` (SIGALRM safe)
- status=ok cached (including absent-player cases); status=skip NOT cached
- Degrades to "unknown" on every error path

**grade_game_in_workbook MANUAL REVIEW branch (inside flag + budget gate):**
```
# After resolve_missing_stat attempt (stat still unresolved):
if result == "MANUAL REVIEW":
    _appearance = resolve_player_appearance(sport, game, _prop_player)
    if _appearance == "dnp":
        result = "VOID"
        actual = None
        note = f"{_prop_player} DNP — no action (refunded)"
        res_src, res_conf = "scraped", 1.0
        pnl = 0.0
        # Not appended to manual_reviews (resolved)
```
- "played" and "unknown" leave result = "MANUAL REVIEW" unchanged
- Flag OFF → resolve_player_appearance not called (behavior preserved)
- NEVER produces LOSS or WIN from the no-stat-line path (T-01-G1-02 mitigated)

**All 30 tests pass on commit 3d2cb95 (GREEN). 01-5 tests still 48/48 (no regression).**

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test used RESULTS_HEADERS instead of RESULT_HEADERS**
- **Found during:** Task 2 first test run — `AttributeError: module has no attribute 'RESULTS_HEADERS'`
- **Issue:** The runner's header constant is `RESULT_HEADERS` (not `RESULTS_HEADERS`)
- **Fix:** Changed all occurrences in test to `runner.RESULT_HEADERS`
- **Files modified:** scripts/test_dnp_void.py
- **Commit:** within Task 2 commit (3d2cb95)

**2. [Rule 1 - Bug] Test used `dry_run=True` but checked `result_dict.get("graded")`**
- **Found during:** Task 2 — grade_game_in_workbook returns `"would_grade"` key when dry_run=True, not `"graded"`. Resulted in 0 PROP rows found.
- **Fix:** Removed `dry_run=True` from TestGradeGameDNPToVoid and TestNeverAutoLoss; patched `sync_master_and_bankroll` to stay offline
- **Files modified:** scripts/test_dnp_void.py
- **Commit:** within Task 2 commit (3d2cb95)

**3. [Rule 1 - Bug] Test props rows lacked Game ID — game_matches_row fell through to text search**
- **Found during:** Task 2 — props rows had no team/game fields; text-search fallback in game_matches_row passed string matching correctly, but the Game ID path is cleaner and deterministic
- **Fix:** Added `"Game ID": "401815839"` to test prop rows; updated props_headers to include it
- **Files modified:** scripts/test_dnp_void.py
- **Commit:** within Task 2 commit (3d2cb95)

## Known Stubs

None — all paths resolve to either VOID (confirmed DNP) or MANUAL REVIEW (abstain). The `resolve_player_appearance` importlib approach adds ~5ms overhead per call (one-time module load, no scrape); negligible within the 660s budget.

## Threat Flags

No new threat surface introduced. The two new code paths are extensions within the existing Layer-2 flag-gated block:
- `player_appearance` is pure Python dict lookup — no network, no subprocess
- `resolve_player_appearance` reuses the 01-5 subprocess + cache path; all T-01-G1 entries mitigated:

| Threat ID | Status |
|-----------|--------|
| T-01-G1-01 (Tampering: DNP -> VOID) | Mitigated: VOID requires status=ok + unambiguous absence; pinned by RED tests |
| T-01-G1-02 (Elevation: no-stat-line -> LOSS) | Mitigated: path can only produce VOID or MANUAL REVIEW; asserted by TestNeverAutoLoss |
| T-01-G1-03 (DoS: extra scrape for appearance) | Mitigated: reuses 01-5 per-event cache — no extra subprocess; budget enforced |
| T-01-G1-SC (Tampering: firecrawl supply chain) | Accept: no new package; pin established in 01-5 |

## Self-Check

- `scripts/verify_results.py` — FOUND; `player_appearance` function defined at line 127
- `scripts/sports_system_runner.py` — FOUND; `resolve_player_appearance` and MANUAL REVIEW wiring present
- `scripts/test_dnp_void.py` — FOUND (30 tests, 0 failures)
- Commit d936ca0 (Task 1 — RED test): FOUND
- Commit 3d2cb95 (Task 2 — GREEN): FOUND

## Self-Check: PASSED
