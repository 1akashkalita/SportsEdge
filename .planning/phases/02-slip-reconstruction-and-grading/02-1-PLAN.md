---
phase: 02-slip-reconstruction-and-grading
plan: 1
type: execute
wave: 1
depends_on: []
files_modified:
  - scripts/grade_slips.py
  - scripts/test_grade_slips_legs.py
autonomous: true
requirements: [SLIPS-02]
must_haves:
  truths:
    - "Given a fixture box score for a date, a leg {player_name, stat_type, line, side} resolves to WIN/LOSS/PUSH via the P1-hardened stat_value_for_prop + name_match"
    - "A leg whose player/stat cannot be resolved (DNP / NOT-DERIVABLE / absent / ambiguous name) returns an abstain marker (None), never a fabricated WIN or LOSS"
    - "A date-wide player_stats lookup is built by merging every final game's box score for that date so legs drawn from the full ~75-prop board (not just bet props) can be graded"
    - "Leg grading reuses P1 functions unchanged — no gate logic, pick verdict, or prop grading behavior is modified"
  artifacts:
    - path: "scripts/grade_slips.py"
      provides: "Slip-leg grading core: date-wide box-score merge + per-leg WIN/LOSS/PUSH/abstain"
      min_lines: 60
      exports: ["build_date_box_scores", "grade_leg", "LEG_PENDING"]
    - path: "scripts/test_grade_slips_legs.py"
      provides: "Offline unittest of leg grading against a fixture box score (WIN, LOSS, PUSH, abstain cases)"
      contains: "unittest"
  key_links:
    - from: "scripts/grade_slips.py"
      to: "sports_system_runner.stat_value_for_prop"
      via: "import + call per leg against merged box score"
      pattern: "stat_value_for_prop"
    - from: "scripts/grade_slips.py"
      to: "sports_system_runner.espn_player_stats_by_event"
      via: "per-final-game box-score fetch merged into a date-wide lookup"
      pattern: "espn_player_stats_by_event"
---

<objective>
Build the slip-leg grading core in a standalone `scripts/grade_slips.py`: a date-wide merged box-score lookup and a per-leg grader that reuses the P1-hardened `stat_value_for_prop` / `name_match` to resolve each `{player_name, stat_type, line, side}` leg to WIN / LOSS / PUSH, or ABSTAIN (None) when the leg cannot be resolved. This is the foundation Wave 2 aggregates into slip results (SLIPS-02).

Purpose: A slip's legs are drawn from the FULL projection board (~75 eligible props per `slips_<date>.json`), so most legs have NO row in the per-day Results sheet — they must be graded DIRECTLY against box scores. Reusing P1 grading guarantees slips are graded off the same trustworthy stat-resolution the props use, with the same abstain-on-ambiguity safety. Standalone module + offline fixture test keeps this fast, isolated, and verifiable without network.

Output: `scripts/grade_slips.py` (exports `build_date_box_scores`, `grade_leg`, `LEG_PENDING`) and `scripts/test_grade_slips_legs.py` (offline unittest with a fixture box score).
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/02-slip-reconstruction-and-grading/02-CONTEXT.md
@docs/superpowers/specs/2026-06-21-trustworthy-results-design.md

<interfaces>
<!-- P1 grading functions to REUSE (import from sports_system_runner). Do not modify them. -->
<!-- From scripts/sports_system_runner.py: -->

stat_value_for_prop(player_stats: dict, player: str, stat: str) -> tuple[float|None, str, float]
  # Returns (value, source, confidence). value is None (source "manual", conf 0.0) when the
  # player/stat is unresolved: name not matched, ambiguous name (abstains), DNP, NOT-DERIVABLE
  # stat, or absent key. A resolved value yields ("api", 1.0/0.8/0.6). MLB rows carry
  # row["batting"] / row["pitching"] sub-dicts; NBA rows are flat — stat_value_for_prop handles both.

name_match(prop_name: str, boxscore_keys, game_roster=None) -> str|None
  # 4-tier name resolver; returns None on no-match or ambiguity (used internally by stat_value_for_prop).

espn_player_stats_by_event(sport: str, event_id: str) -> dict[str, dict]
  # Per-player box-score lookup keyed by lowercased displayName. THE per-game source to merge date-wide.

espn_scoreboard_games_for_date(sport: str, date: str) -> list[dict]
  # Each game dict has: "event_id" (str), "status" ("final"|"void"|"live"|"scheduled"),
  # "home_team", "away_team". Iterate, keep status=="final", call espn_player_stats_by_event per event_id.
  # NOTE: this issues network calls. grade_leg / build_date_box_scores must accept an injected
  # player_stats dict so the test can run fully offline against a fixture (no network in tests).

_canon_stat(stat: str) -> str   # canonical stat key (lowercase, collapse + and spaces)

<!-- Leg shape from data/research/slips/slips_<date>.json (legs[]): -->
<!-- {player_name, stat_type, line (float), side ("OVER"/"UNDER"), sport ("NBA"/"MLB"), prop_id, confidence_tier, over_probability} -->
<!-- All P2 legs in the sample file are side="OVER"; grade_leg MUST still honor UNDER correctly. -->

<!-- Existing fixture pattern (reuse, do not reinvent): -->
<!-- scripts/testdata/espn_summary/mlb_summary.json and nba_summary.json exist. -->
<!-- P1 tests (scripts/test_stat_value_for_prop.py) build player_stats dicts inline — MLB rows with -->
<!-- "batting"/"pitching" sub-dicts, NBA rows flat. Mirror that shape for this test's fixture. -->
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Date-wide box-score merge + per-leg grader in grade_slips.py</name>
  <read_first>
    - .planning/phases/02-slip-reconstruction-and-grading/02-CONTEXT.md (How to grade a slip: steps 1-3 — date-wide merge, stat_value_for_prop per leg, abstain on unresolved)
    - scripts/sports_system_runner.py (stat_value_for_prop ~4322; name_match ~3540; _canon_stat ~4311; espn_player_stats_by_event ~6169; espn_scoreboard_games_for_date ~4937; grade_prop ~4626 for the side/diff/PUSH convention to mirror)
    - scripts/slip_payouts.py (the leg shape consumed downstream in Wave 2 — leg keys player_name/stat_type/line/side)
    - data/research/slips/slips_2026-06-22.json (concrete leg structure)
    - CLAUDE.md (run from scripts/ with python3; reuse-don't-modify P1 grading; no schema/gate changes)
  </read_first>
  <files>scripts/grade_slips.py</files>
  <behavior>
    - build_date_box_scores(date, player_stats_by_sport=None): when an injected dict is provided, returns it unchanged (offline path); otherwise iterates espn_scoreboard_games_for_date for nba+mlb, keeps status=="final" games, calls espn_player_stats_by_event per event_id, and merges into one lookup PER SPORT keyed by lowercased player name. Returns {"NBA": {...}, "MLB": {...}}.
    - grade_leg(leg, box_scores) for a leg whose player+stat resolves and actual > line, side OVER → returns "WIN" with the resolved actual value.
    - grade_leg for actual < line, side OVER → "LOSS"; actual == line → "PUSH".
    - grade_leg for side UNDER inverts: actual < line → "WIN", actual > line → "LOSS", equal → "PUSH".
    - grade_leg when stat_value_for_prop returns None (DNP / NOT-DERIVABLE / ambiguous name / absent) → returns LEG_PENDING (the abstain sentinel), NEVER "LOSS".
    - grade_leg selects the per-sport box score from leg["sport"] before calling stat_value_for_prop.
  </behavior>
  <action>
    Create `scripts/grade_slips.py`. Import the P1 functions from `sports_system_runner` (the module must be importable when run from scripts/): `stat_value_for_prop`, `espn_player_stats_by_event`, `espn_scoreboard_games_for_date`. Define `LEG_PENDING = "PENDING"` (the abstain sentinel; reuse the same token P1 uses for unresolved props so Wave 2 can treat it as "unresolved leg"). Implement:
    (1) `build_date_box_scores(date, player_stats_by_sport=None)` — if `player_stats_by_sport` is given, return it (offline/test injection); else build the date-wide merged lookup per sport by iterating `espn_scoreboard_games_for_date(sport, date)`, filtering `status == "final"`, and merging `espn_player_stats_by_event(sport, event_id)` dicts into one per-sport dict (later games do not clobber earlier players since names are unique keys; if a duplicate name appears, keep the first non-empty row). Return `{"NBA": {...}, "MLB": {...}}`.
    (2) `grade_leg(leg, box_scores)` — pick the per-sport lookup via `str(leg.get("sport") or "").upper()`; call `stat_value_for_prop(sport_stats, leg["player_name"], leg["stat_type"])`. If the returned value is None → return a dict `{"result": LEG_PENDING, "actual": None, "source": src, "confidence": conf}`. Otherwise compute the verdict from `actual` vs `float(leg["line"])` honoring `leg["side"]` (OVER: actual>line WIN, <line LOSS, ==line PUSH; UNDER inverts) — mirror the diff/PUSH convention in `grade_prop`. Return `{"result": "WIN"|"LOSS"|"PUSH", "actual": actual, "source": src, "confidence": conf}`.
    Keep the module free of any workbook writes (Wave 2 owns persistence) and free of side effects at import time. Type-annotate per project conventions (PEP 604, lowercase builtins).
  </action>
  <verify>
    <automated>cd scripts && python3 -c "import grade_slips; print(grade_slips.LEG_PENDING, callable(grade_slips.grade_leg), callable(grade_slips.build_date_box_scores))"</automated>
  </verify>
  <acceptance_criteria>
    - `grade_slips.py` imports cleanly from scripts/ and exports `build_date_box_scores`, `grade_leg`, `LEG_PENDING`.
    - `grade_leg` reuses `stat_value_for_prop` (no reimplemented name/stat matching) and returns the abstain sentinel on a None value, never LOSS.
    - `build_date_box_scores` accepts an injected per-sport dict for offline use and otherwise merges all final-game box scores for the date.
    - No P1 function in sports_system_runner.py is modified; no workbook is touched.
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 2: Offline unittest — leg grading WIN/LOSS/PUSH/abstain against a fixture box score</name>
  <read_first>
    - scripts/test_stat_value_for_prop.py (how P1 tests construct inline player_stats dicts: MLB rows with "batting"/"pitching" sub-dicts incl. aliased canonical keys; NBA flat rows — mirror exactly so stat_value_for_prop resolves them)
    - scripts/grade_slips.py (the grade_leg / build_date_box_scores contract from Task 1)
    - data/research/slips/slips_2026-06-22.json (real leg dicts to copy as fixtures — e.g. Zebby Matthews outs 15.5 OVER, Isaac Collins hits runs rbis 0.5 OVER)
    - MEMORY: baseline is "2 failed, 202 passed"; run THIS file only (not the 34-min suite)
  </read_first>
  <files>scripts/test_grade_slips_legs.py</files>
  <action>
    Write `scripts/test_grade_slips_legs.py` (stdlib `unittest`, a `__main__` block like the other P1 test files). Construct an inline `box_scores = {"NBA": {...}, "MLB": {...}}` fixture — an MLB player row with `batting`/`pitching` sub-dicts carrying canonical keys (e.g. `hits`, `runs`, `rbis`, and for a pitcher `outs`/`strikeouts`) shaped exactly as `espn_player_stats_by_event` emits, plus an NBA flat row. Cover: (a) OVER leg where actual > line → WIN; (b) OVER leg where actual < line → LOSS; (c) leg where actual == line → PUSH; (d) UNDER leg where actual < line → WIN; (e) a leg whose player is absent from the box score → result == `grade_slips.LEG_PENDING` (assert it is NOT "LOSS"); (f) a NOT-DERIVABLE stat (e.g. "fantasy score") → `LEG_PENDING`. Pass the fixture into `build_date_box_scores(date, player_stats_by_sport=box_scores)` to prove the injection path returns it unchanged, then call `grade_leg` on each constructed leg. Do NOT hit the network.
  </action>
  <verify>
    <automated>cd scripts && python3 test_grade_slips_legs.py</automated>
  </verify>
  <acceptance_criteria>
    - Test runs fully offline (no network) and exits 0.
    - Asserts WIN, LOSS, PUSH, UNDER-WIN, absent-player-abstain, and NOT-DERIVABLE-abstain cases.
    - The two abstain cases explicitly assert the result equals `LEG_PENDING` and is NOT "LOSS" (money-safety).
    - `build_date_box_scores(..., player_stats_by_sport=fixture)` returns the injected fixture unchanged.
  </acceptance_criteria>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| ESPN box-score availability (older dates) → leg resolution | Missing/partial historical box data must abstain (PENDING), never fabricate a leg result |
| leg stat-string → box-score key | Untrusted player/stat strings from slips_<date>.json cross into stat_value_for_prop; ambiguity must abstain |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-02-01 | Tampering | grade_leg verdict on unresolved leg | mitigate | Return LEG_PENDING (abstain) on any None from stat_value_for_prop; unittest asserts absent/NOT-DERIVABLE legs are PENDING, never LOSS |
| T-02-02 | Spoofing | name resolution of a leg player | mitigate | Reuse P1 name_match (abstains on ambiguity); no new matching logic introduced |
| T-02-03 | Information Disclosure | network calls in unit tests | accept | Tests inject a fixture box score (offline); no secrets or live endpoints touched |
</threat_model>

<verification>
- `python3 grade_slips.py` import check passes (exports present).
- `python3 test_grade_slips_legs.py` exits 0 with all WIN/LOSS/PUSH/abstain cases.
- Manual read confirms no edit to any sports_system_runner.py P1 function and no workbook write in grade_slips.py.
</verification>

<success_criteria>
- A date-wide merged box-score lookup is built from all final games for a date (with offline injection for tests).
- Each leg grades to WIN/LOSS/PUSH via reused P1 stat_value_for_prop, or abstains (LEG_PENDING) when unresolved — never a fabricated result.
- SLIPS-02 foundation is offline-testable and passes.
</success_criteria>

<output>
Create `.planning/phases/02-slip-reconstruction-and-grading/02-1-SUMMARY.md` when done. Record the exported function signatures, the abstain sentinel value, and the fixture-test cases covered.
</output>
