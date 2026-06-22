---
phase: 01-trustworthy-results
plan: 1
type: execute
wave: 1
depends_on: []
files_modified:
  - scripts/testdata/espn_summary/mlb_summary.json
  - scripts/testdata/espn_summary/nba_summary.json
  - scripts/testdata/stat_corpus.json
  - scripts/testdata/README.md
autonomous: true
requirements: [RESULTS-02, RESULTS-03]
must_haves:
  truths:
    - "An MLB ESPN summary fixture exists containing at least one two-way / shared-label player and a populated plays/atBats array"
    - "An NBA ESPN summary fixture exists with a single-group box score"
    - "A stat_corpus.json enumerates the NBA+MLB union of Stat strings that grading must classify"
    - "The exact ESPN box-score key strings the disposition table depends on are recorded from the real fixtures, not assumed"
  artifacts:
    - path: "scripts/testdata/espn_summary/mlb_summary.json"
      provides: "Real ESPN MLB summary capture (gamepackageJSON.boxscore) with a two-way/shared-label player and plays/atBats"
      min_lines: 50
    - path: "scripts/testdata/espn_summary/nba_summary.json"
      provides: "Real ESPN NBA summary capture (single statistics group)"
      min_lines: 50
    - path: "scripts/testdata/stat_corpus.json"
      provides: "Enumerated NBA+MLB Stat-string corpus sourced from live Props sheets"
      contains: "Total Bases"
    - path: "scripts/testdata/README.md"
      provides: "Records the exact fixture key strings each DIRECT/DERIVED disposition relies on (the verification oracle ledger)"
  key_links:
    - from: "scripts/testdata/espn_summary/mlb_summary.json"
      to: "espn_player_stats_by_event / stat_value_for_prop (downstream plans)"
      via: "gamepackageJSON.boxscore.players[*].statistics[*].keys/athletes shape"
      pattern: "gamepackageJSON"
---

<objective>
Build the verification oracle for Phase 1: two real ESPN summary JSON captures plus an enumerated stat corpus, all checked in under `scripts/testdata/`. Every DIRECT/DERIVED key string the later disposition table relies on is confirmed against these fixtures BEFORE any source code is touched — so a wrong key surfaces here in a test, never as a silent MANUAL REVIEW in production grading.

Purpose: Component 0 of the spec is first-class precisely because Component 3's key mappings (`defensiverebounds`, `offensiverebounds`, `earnedruns`, `pitches`, `fieldGoals[*]`, `threePoint[*]`) and Component 4's batting/pitching split are assumptions until a fixture confirms the literal key strings and the `plays`/`atBats` array shape.

Output: `scripts/testdata/espn_summary/mlb_summary.json`, `scripts/testdata/espn_summary/nba_summary.json`, `scripts/testdata/stat_corpus.json`, and a `scripts/testdata/README.md` ledger of the confirmed key strings. NO edits to `sports_system_runner.py` in this plan (parallel-safe foundation).
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

<interfaces>
<!-- The capture endpoint already used by the grading path. Use it verbatim to get fixtures
     that match exactly what grading will see at runtime. From sports_system_runner.py: -->

espn_player_stats_by_event(sport, event_id) at :5318 fetches:
  espn_json(f"https://cdn.espn.com/core/{cdn}/game", {"xhr": "1", "gameId": event_id})
  then reads data["gamepackageJSON"]["boxscore"]["players"][*]["statistics"][*]
    group_data["keys"] | ["names"] | ["labels"]   (the label list)
    group_data["athletes"][*]["athlete"]["displayName" | "shortName"]
    group_data["athletes"][*]["stats"]             (the value list, positionally zipped with labels)

espn_sport_parts(sport) at :4856 returns (group, league, cdn) where cdn = "nba" | "mlb".
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: Capture the two ESPN summary fixtures</name>
  <read_first>
    - docs/superpowers/specs/2026-06-21-trustworthy-results-design.md (Component 0; Components 3 & 4 key lists)
    - scripts/sports_system_runner.py (espn_player_stats_by_event:5318, espn_json:4847, espn_sport_parts:4856, espn_scoreboard_games_for_date — to pick a real final game id)
  </read_first>
  <files>scripts/testdata/espn_summary/mlb_summary.json, scripts/testdata/espn_summary/nba_summary.json</files>
  <action>
    Create `scripts/testdata/espn_summary/`. Write a small throwaway capture step (run from `scripts/` with `python3`, NOT committed) that imports `sports_system_runner` and calls `espn_json("https://cdn.espn.com/core/{cdn}/game", {"xhr":"1","gameId": <id>})` for one real FINAL MLB game and one real FINAL NBA game, dumping the full JSON response to the two fixture files. Pick a completed MLB game whose box score contains BOTH a player who appears in a `batting` group and a player (or the same two-way player) in a `pitching` group, AND whose `gamepackageJSON.plays`/`atBats` array is populated — the spec requires a shared-label player so the namespace-split test in plan 01-2 is meaningful. Save the raw `gamepackageJSON` (or the whole response) so the fixture matches exactly what `espn_player_stats_by_event` consumes at runtime. Trim only obviously irrelevant top-level keys if size is a concern, but KEEP `boxscore.players[*].statistics` (with `keys`/`names`/`labels`, `athletes`, `stats`) and the `plays`/`atBats` arrays intact. If the live CDN endpoint is unreachable, degrade by using a saved `data/` capture for a known event id; do NOT fabricate key strings.
  </action>
  <verify>
    <automated>cd scripts && python3 -c "import json; m=json.load(open('testdata/espn_summary/mlb_summary.json')); n=json.load(open('testdata/espn_summary/nba_summary.json')); assert m and n; b=(m.get('gamepackageJSON') or m).get('boxscore') or m.get('boxscore'); assert b and b.get('players'), 'mlb boxscore.players missing'; print('OK', len(b['players']))"</automated>
  </verify>
  <done>Both fixture files exist and parse as JSON; the MLB fixture's `boxscore.players` is non-empty and contains at least one batting group and one pitching group with shared labels; a `plays` or `atBats` array is present.</done>
</task>

<task type="auto">
  <name>Task 2: Enumerate the stat corpus and record the confirmed key strings</name>
  <read_first>
    - docs/superpowers/specs/2026-06-21-trustworthy-results-design.md (Component 3 disposition table — the exact DIRECT/DERIVED/NOT-DERIVABLE enumeration; Testing strategy #2)
    - data/mlb/*.xlsx and data/nba/*.xlsx (the live Props sheets — source of the real Stat strings)
  </read_first>
  <files>scripts/testdata/stat_corpus.json, scripts/testdata/README.md</files>
  <action>
    Build `scripts/testdata/stat_corpus.json` as the union of distinct `Stat` strings appearing on the live Props sheets across NBA + MLB workbooks under `data/`. Read the `Props` sheet of a representative sample of `data/{nba,mlb}/*.xlsx` via openpyxl from `scripts/`, collect the distinct `Stat` column values, and write them as a JSON list (or `{"nba":[...], "mlb":[...]}`). Then write `scripts/testdata/README.md` as the oracle ledger: for each DIRECT key and DERIVED formula the spec's Component 3 table names (NBA: points, rebounds, assists, steals, blocks, turnovers, fouls, defensiverebounds, offensiverebounds, `3-pt made`, fieldGoals[0/1], threePoint[1]; MLB: hits, runs, rbis, homeruns, walks, strikeouts, earnedruns, pitches, plus Total Bases / Singles / Pitching Outs / H+R+RBI derivations), record the EXACT key string as it literally appears in the captured fixtures from Task 1. Where the fixture key string differs from the spec's assumed name, note the real key in the ledger and flag it RECLASSIFY — downstream plan 01-3 uses this ledger as the source of truth, not the spec's assumed names. Do NOT edit any source file.
  </action>
  <verify>
    <automated>cd scripts && python3 -c "import json; c=json.load(open('testdata/stat_corpus.json')); flat=sum(c.values(),[]) if isinstance(c,dict) else c; assert isinstance(flat,list) and len(flat)>=5, flat; import os; assert os.path.getsize('testdata/README.md')>200; print('corpus', len(flat))"</automated>
  </verify>
  <done>`stat_corpus.json` contains the NBA+MLB Stat-string union (≥5 entries, including at least one MLB derived stat such as "Total Bases"); `README.md` ledger maps every DIRECT/DERIVED disposition to the literal key string confirmed in the Task 1 fixtures, flagging any spec/fixture mismatch as RECLASSIFY.</done>
</task>

</tasks>

<verification>
- Both fixtures parse and expose `gamepackageJSON.boxscore.players` (MLB with batting+pitching shared-label coverage and a `plays`/`atBats` array).
- `stat_corpus.json` is a non-trivial union of real Props-sheet Stat strings.
- `README.md` records each Component 3 DIRECT/DERIVED key string AS IT LITERALLY APPEARS in the fixtures, so plan 01-3 builds the disposition table against confirmed keys.
- No source file under `scripts/*.py` is modified (this is a testdata-only, parallel-safe foundation plan).
</verification>

<success_criteria>
- `scripts/testdata/espn_summary/{mlb_summary,nba_summary}.json` and `scripts/testdata/stat_corpus.json` checked in.
- The oracle ledger confirms (or corrects) every key string the disposition table will rely on.
- Zero edits to `sports_system_runner.py`.
</success_criteria>

<output>
Create `.planning/phases/01-trustworthy-results/01-1-SUMMARY.md` when done. Record any spec→fixture key-string corrections (RECLASSIFY flags) prominently — plan 01-3 depends on them.
</output>
