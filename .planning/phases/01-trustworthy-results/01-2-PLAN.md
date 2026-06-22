---
phase: 01-trustworthy-results
plan: 2
type: execute
wave: 2
depends_on: ["01-1"]
files_modified:
  - scripts/sports_system_runner.py
  - scripts/test_name_match.py
  - scripts/test_espn_namespacing.py
autonomous: true
requirements: [RESULTS-01, RESULTS-03]
must_haves:
  truths:
    - "A prop player name with accents, punctuation, a Jr/Sr/II–IV suffix, or 'F. Last' initial form resolves to the correct box-score key"
    - "An ambiguous fuzzy name match abstains (returns None) rather than guessing"
    - "An exact name match resolves byte-identically to the pre-change behavior"
    - "An MLB two-way / shared-label player's batting strikeouts and pitching strikeouts are both retrievable and do not clobber each other"
    - "An NBA single-group box yields keys and aliases byte-identical to the pre-change output"
  artifacts:
    - path: "scripts/sports_system_runner.py"
      provides: "_canonical_name, name_match, and the batting/pitching namespace split + hit-type counts in espn_player_stats_by_event"
      contains: "def name_match"
    - path: "scripts/test_name_match.py"
      provides: "Offline unit test for the 9 positive name pairs + the abstain case"
      contains: "J. Williams"
    - path: "scripts/test_espn_namespacing.py"
      provides: "Fixture-backed test for the namespace split and NBA byte-identity regression"
      contains: "strikeouts"
  key_links:
    - from: "name_match"
      to: "_canonical_name"
      via: "canonicalizes both prop name and box-score keys"
      pattern: "_canonical_name"
    - from: "espn_player_stats_by_event"
      to: "stat_value_for_prop (plan 01-3)"
      via: "row[\"batting\"] / row[\"pitching\"] namespaces + per-player hit-type counts"
      pattern: "batting|pitching"
---

<objective>
Land Layer-1 matching primitives: a grading-local `_canonical_name` + `name_match` (RESULTS-01), and the batting/pitching namespace split plus per-player hit-type counts in `espn_player_stats_by_event` (RESULTS-03). These are the inputs the disposition table in plan 01-3 consumes. Exact-match behavior is preserved byte-for-byte so no currently-passing grade verdict changes, and NBA single-group output stays identical.

Purpose: The two confirmed defects (exact-only name lookup at `:4040`; shared MLB labels clobbering at `:5337`) are the upstream causes of the ~37% MANUAL REVIEW rate. This plan fixes the matching substrate without yet touching `stat_value_for_prop`'s disposition logic (that is plan 01-3, which depends on this).

Output: `_canonical_name`, `name_match`, the namespaced `espn_player_stats_by_event`, and two offline fixture-backed tests.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/01-trustworthy-results/01-CONTEXT.md
@docs/superpowers/specs/2026-06-21-trustworthy-results-design.md
@.planning/phases/01-trustworthy-results/01-1-SUMMARY.md

<interfaces>
<!-- Current grading-path code in sports_system_runner.py. DO NOT change normalize_player_name. -->

normalize_player_name(value) at :3482  ->  " ".join(str(value or "").replace("_"," ").lower().split())
  USED OUTSIDE GRADING (pp_lookup:3520). Leave it untouched — changing it widens blast radius.

espn_player_stats_by_event(sport, event_id) -> dict[str, dict[str, float]]  at :5318
  Builds: row = stats.setdefault(str(name).lower(), {})  at :5337  (THE CLOBBERING LINE)
  group_data["keys"|"names"|"labels"] = labels;  group_data has a group name distinguishing batting vs pitching.
  Existing NBA FG/3PT split-on-"-" logic at :5341-5342 and alias_pairs at :5347-5357 MUST be preserved verbatim for the NBA single-group case.

espn_sport_parts(sport) at :4856 -> (group, league, cdn).  innings_to_outs analog in build_hit_rate_db.py:165
  (handles ".1/.2" fractional innings: int(whole)*3 + int(frac[:1])) — mirror it when plan 01-3 needs Pitching Outs.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add _canonical_name + name_match with the abstain policy</name>
  <read_first>
    - docs/superpowers/specs/2026-06-21-trustworthy-results-design.md (Components 1 & 2 — exact normalization order and the 4 match tiers; the must-match/must-abstain corpus)
    - scripts/sports_system_runner.py (normalize_player_name:3482 — do NOT modify; stat_value_for_prop:4039 to see where name_match will plug in next plan)
  </read_first>
  <files>scripts/sports_system_runner.py, scripts/test_name_match.py</files>
  <behavior>
    - "Jokic" vs box key "jokić" -> resolves to "jokić" (NFKD accent fold)
    - "Acuna Jr." vs "acuña jr." -> resolves (accent + trailing-suffix drop)
    - "PJ Washington" / "P.J. Washington" -> resolves (punct -> space)
    - "L. Doncic" vs "luka dončić" -> resolves via the "X last" initial bridge (single matching key)
    - "Guerrero Jr" vs "Guerrero Jr." -> resolves (suffix normalization)
    - "Gilgeous Alexander" vs "gilgeous-alexander" -> resolves (hyphen -> space)
    - exact: prop_name.lower() already a box key -> that exact key returned, byte-identical
    - ("J. Williams", {"jalen williams","jaylin williams"}) -> None (ambiguous initial bridge abstains)
    - last-name shared by 2+ keys with no unique bridge -> None (abstain, never guess)
  </behavior>
  <action>
    Add `def _canonical_name(name: Any) -> str` near the grading helpers in `sports_system_runner.py`. Order EXACTLY per Component 1: coerce to str -> lowercase -> NFKD-normalize and drop Unicode combining marks via `unicodedata.combining` -> replace `.` `'` `’` `-` with spaces -> drop a trailing token in `{jr, sr, ii, iii, iv}` -> collapse whitespace. Add `import unicodedata` if not already imported. Then add `def name_match(prop_name: str, boxscore_keys, game_roster=None) -> str | None` implementing the 4 tiers, first hit wins, returning the ORIGINAL box-score key (callers still index `player_stats` by it): (1) exact `prop_name.lower() in boxscore_keys`; (2) `_canonical_name` equality between prop and each key; (3) initial-form bridge — one side is "X last" (single-letter first token) and a key's first token startswith X and last token equals last token, only if EXACTLY ONE such key; (4) last-name-unique fallback — if exactly one key shares the canonical last token, return it, else None. Canonicalize BOTH sides (box keys can already be "f. last" form when displayName is absent). Do NOT modify `normalize_player_name`. Write `scripts/test_name_match.py` (stdlib unittest, importing the runner via importlib from `scripts/`) asserting all 9 positive pairs resolve to the correct key and `("J. Williams", {"jalen williams","jaylin williams"}) -> None`, plus an exact-match byte-identity assertion.
  </action>
  <verify>
    <automated>cd scripts && python3 test_name_match.py</automated>
  </verify>
  <done>`test_name_match.py` exits 0: all 9 positive pairs resolve, the ambiguous case returns None, exact match is byte-identical. `normalize_player_name` is unchanged.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Namespace-split espn_player_stats_by_event + per-player hit-type counts</name>
  <read_first>
    - docs/superpowers/specs/2026-06-21-trustworthy-results-design.md (Component 4 — both additive changes; backward-compat guard)
    - .planning/phases/01-trustworthy-results/01-1-SUMMARY.md (the confirmed fixture key strings + any RECLASSIFY flags)
    - scripts/sports_system_runner.py (espn_player_stats_by_event:5318-5358 — the clobber at :5337 and the NBA alias/split logic at :5341-5357)
  </read_first>
  <files>scripts/sports_system_runner.py, scripts/test_espn_namespacing.py</files>
  <behavior>
    - MLB two-way/shared-label player: row["batting"]["strikeouts"] and row["pitching"]["strikeouts"] are BOTH present and distinct (no clobber)
    - MLB player: per-player hit-type counts (Single/Double/Triple/HomeRun) derived from the fixture's plays/atBats are attached so Total Bases / Singles can derive without a scrape
    - NBA single-group box: the returned dict for each player has keys + aliases byte-identical to the pre-change output (regression)
  </behavior>
  <action>
    In `espn_player_stats_by_event`, replace the clobbering flat `row = stats.setdefault(str(name).lower(), {})` (:5337) with a per-group namespace: each player row becomes `{"batting": {...}, "pitching": {...}, <existing flat NBA keys>}`. Derive group identity (batting vs pitching) from `group_data` (the ESPN `statistics` group name/keys at :5329-5330) using the literal group strings confirmed in the 01-1 fixture ledger. For the NBA single-group case, keep writing the existing flat keys AND the alias_pairs/FG-3PT-split logic (:5341-5357) VERBATIM so NBA output is byte-identical — only MLB gains the batting/pitching sub-dicts. Add per-player hit-type counts (Single/Double/Triple/Home-Run) read from the summary `plays`/`atBats` array using the exact array path and field names taken from the 01-1 MLB fixture; attach them on the player row so plan 01-3's Total Bases / Singles derivations have a non-scrape source. Write `scripts/test_espn_namespacing.py` (stdlib unittest) that loads `scripts/testdata/espn_summary/mlb_summary.json` and `nba_summary.json`, calls the parsing logic against them, asserts batting vs pitching `strikeouts` are both retrievable on the two-way player, asserts the hit-type counts exist, and asserts the NBA player keys/aliases are byte-identical to a captured pre-change snapshot.
  </action>
  <verify>
    <automated>cd scripts && python3 test_espn_namespacing.py</automated>
  </verify>
  <done>`test_espn_namespacing.py` exits 0: shared MLB labels no longer clobber (batting/pitching strikeouts both present), hit-type counts surface from plays/atBats, NBA flat keys/aliases byte-identical to pre-change.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| ESPN CDN summary JSON → grading | Untrusted external JSON shape; key strings and array presence are not guaranteed |
| prop player-name string → box-score key | A wrong fuzzy match silently grades a real-money bet against the wrong player's line |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-01 | Tampering | name_match fuzzy tiers | mitigate | Tiers 3–4 require a UNIQUE match; ambiguous → None (abstain), proven by the `J. Williams` test case |
| T-01-02 | Information Disclosure | espn_player_stats_by_event missing keys | mitigate | Missing group/labels/plays degrade to empty sub-dicts, never raise; fixture test pins the shapes |
| T-01-03 | Spoofing | NBA byte-identity regression | mitigate | Byte-identity assertion guards against an unintended verdict change on currently-passing NBA grades |
</threat_model>

<verification>
- `python3 test_name_match.py` exits 0 (run from `scripts/`).
- `python3 test_espn_namespacing.py` exits 0.
- `normalize_player_name:3482` is byte-identical to its pre-plan form (grep diff).
- No change to gate logic or pick verdicts; this plan only adds matching primitives and namespaces the box parser.
</verification>

<success_criteria>
- `_canonical_name` + `name_match` exist with the exact tiers and abstain policy; the 9-pair corpus + abstain case pass.
- `espn_player_stats_by_event` returns batting/pitching namespaces for MLB (no clobber) + hit-type counts, with NBA output byte-identical.
- Both targeted tests pass; full pytest is NOT run here (run at phase end per the slow-suite memory; clean baseline "2 failed, 202 passed").
</success_criteria>

<output>
Create `.planning/phases/01-trustworthy-results/01-2-SUMMARY.md` when done. Document the exact group-name strings used for the batting/pitching split and the plays/atBats array path — plan 01-3 consumes both.
</output>
