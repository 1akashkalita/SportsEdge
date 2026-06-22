# Testdata Oracle Ledger

**Captured:** 2026-06-22
**Purpose:** Component 0 of the P1 Trustworthy Results design — the verification oracle.
Plan 01-3 builds its DIRECT/DERIVED disposition table against the confirmed key strings
recorded here, not against the spec's assumed names.

---

## Fixtures

### MLB: `espn_summary/mlb_summary.json`

- **Game:** Detroit Tigers (DET) vs Chicago White Sox (CHW), 2026-06-21
- **ESPN event_id:** `401815839`
- **CDN endpoint:** `https://cdn.espn.com/core/mlb/game?xhr=1&gameId=401815839`
- **Two-way/shared-label player:** Will Vest (appears in BOTH batting and pitching groups)
- **plays array:** present (`gamepackageJSON.plays`), 573 entries
- **atBats array:** NOT present at top level (`gamepackageJSON.atBats` does not exist)
- **Fixture path in `espn_player_stats_by_event`:** `data["gamepackageJSON"]["boxscore"]["players"]`

### NBA: `espn_summary/nba_summary.json`

- **Game:** New York Knicks vs San Antonio Spurs (NBA Finals Game 3), 2026-06-10
- **ESPN event_id:** `401859966`
- **CDN endpoint:** `https://cdn.espn.com/core/nba/game?xhr=1&gameId=401859966`
- **Statistics structure:** single group per team (no `type` or `name` field on group — `None`)
- **Fixture path:** `data["gamepackageJSON"]["boxscore"]["players"]`

---

## ESPN Box-Score Key Strings (Confirmed from Fixtures)

This section records the EXACT key strings as they literally appear in the fixture JSON.
Plan 01-3 must use these confirmed keys, not assumed names from the spec.
Where a fixture key differs from the spec's assumed name, it is flagged **RECLASSIFY**.

### Group Identity

| Sport | How to identify group | Confirmed field | Value |
|-------|----------------------|-----------------|-------|
| MLB   | `group_data["type"]` | `"type"` | `"batting"` or `"pitching"` |
| NBA   | `group_data.get("type")` returns `None`; single group per team | `"type"` | `None` |
| MLB   | `group_data.get("name")` | `"name"` | `None` (name field absent) |

**Implementation note:** Group identity for MLB must use `group_data.get("type")`, NOT
`group_data.get("name")` (which is `None`). The existing runner code at `:5330` uses
`group_data.get("keys")` which works as a label list — group type is separate.

---

### NBA Keys — Confirmed from Fixture

The runner reads `group_data["keys"]` (not `"labels"` or `"names"`).
`"labels"` and `"names"` both exist and are identical abbreviations (MIN/PTS/FG/...) —
but `espn_player_stats_by_event:5330` reads `"keys"` first, which is the full-form list.

**Full NBA `keys` array (confirmed):**
```json
["minutes", "points", "fieldGoalsMade-fieldGoalsAttempted",
 "threePointFieldGoalsMade-threePointFieldGoalsAttempted",
 "freeThrowsMade-freeThrowsAttempted", "rebounds", "assists",
 "turnovers", "steals", "blocks", "offensiveRebounds", "defensiveRebounds",
 "fouls", "plusMinus"]
```

#### NBA DIRECT Disposition Keys (Confirmed)

| Stat (from Props sheet) | Spec assumed key | CONFIRMED fixture key | Status |
|-------------------------|------------------|-----------------------|--------|
| Points | `points` | `points` | CONFIRMED |
| Rebounds | `rebounds` | `rebounds` | CONFIRMED |
| Assists | `assists` | `assists` | CONFIRMED |
| Steals | `steals` | `steals` | CONFIRMED |
| Blocks / Blocked Shots | `blocks` | `blocks` | CONFIRMED |
| Turnovers | `turnovers` | `turnovers` | CONFIRMED |
| Personal Fouls | `fouls` | `fouls` | CONFIRMED |
| Offensive Rebounds | `offensiverebounds` | `offensiveRebounds` (camelCase) | **RECLASSIFY** |
| Defensive Rebounds | `defensiverebounds` | `defensiveRebounds` (camelCase) | **RECLASSIFY** |

**RECLASSIFY — Offensive/Defensive Rebounds:**
The spec says `offensiverebounds` and `defensiverebounds` (all lowercase), but the fixture
contains `offensiveRebounds` and `defensiveRebounds` (camelCase). The runner lowercases
labels via `label_l = str(label).lower()` at `:5339`, so the stored key is
`offensiverebounds` and `defensiverebounds`. The disposition table in plan 01-3 should
map to the lowercased form: `offensiverebounds` / `defensiverebounds`.

#### NBA DERIVED Disposition Keys (Confirmed)

| Derived Stat | Formula | Fixture raw key | Post-lowercase key |
|-------------|---------|-----------------|-------------------|
| FG Made | `fieldGoalsMade-fieldGoalsAttempted`.split("-")[0] | `fieldGoalsMade-fieldGoalsAttempted` | `fieldgoalsmade-fieldgoalsattempted` |
| FG Attempted | split("-")[1] | same | same |
| 3-PT Made / `3-PT Made` | `threePointFieldGoalsMade-threePointFieldGoalsAttempted`.split("-")[0] | `threePointFieldGoalsMade-threePointFieldGoalsAttempted` | `threepointfieldgoalsmade-threepointfieldgoalsattempted` |
| 3-PT Attempted | split("-")[1] | same | same |
| FT Made | `freeThrowsMade-freeThrowsAttempted`.split("-")[0] | `freeThrowsMade-freeThrowsAttempted` | `freethrowsmade-freethrowsattempted` |
| FT Attempted | split("-")[1] | same | same |
| Blks+Stls / Blocks+Steals | `blocks + steals` | both present | `blocks`, `steals` |
| Two Pointers Made | FG_made - 3PT_made | derived | derived |
| PRA / Pts+Rebs+Asts variants | `points + rebounds + assists` | all present | `points`, `rebounds`, `assists` |

**Note on FG/3PT/FT split:** The existing runner code at `:5341-5342` already splits
`"x-y"` strings on `"-"` for `fieldgoals`, `threepoint`, `freethrows`, `fg`, `3pt`, `ft`
keys and stores the first part. So `fieldgoalsmade-fieldgoalsattempted` → stored as
`fieldgoalsmade-fieldgoalsattempted` (split string) = first part of "2-9" = 2.0.
Plan 01-3 must account for this when defining DERIVED formulas.

**The existing alias `"3-pt made"` at `:5349`:**
The runner aliases `"threepointfieldgoalsmade-threepointfieldgoalsattempted"` → `"3-pt made"`.
The disposition table should map `"3-PT Made"` → key `"3-pt made"` (alias already applied).

---

### MLB Keys — Confirmed from Fixture

**Full MLB batting `keys` array (confirmed):**
```json
["hits-atBats", "atBats", "runs", "hits", "RBIs", "homeRuns", "walks",
 "strikeouts", "pitches", "avg", "onBasePct", "slugAvg"]
```

**Full MLB pitching `keys` array (confirmed):**
```json
["fullInnings.partInnings", "hits", "runs", "earnedRuns", "walks",
 "strikeouts", "homeRuns", "pitches-strikes", "ERA", "pitches"]
```

**Shared labels between batting and pitching groups (clobber hazard):**
`hits`, `runs`, `walks`, `strikeouts`, `homeRuns`
Will Vest appears in BOTH groups — without namespace split, the second group
(pitching) would clobber the first (batting) for these keys.

#### MLB DIRECT Disposition Keys (Confirmed)

| Stat (Props sheet) | Group | Spec assumed key | CONFIRMED fixture key (pre-lowercase) | Post-lowercase |
|-------------------|-------|------------------|--------------------------------------|----------------|
| Hits | batting | `hits` | `hits` | `hits` |
| Runs | batting | `runs` | `runs` | `runs` |
| RBIs | batting | `rbis` | `RBIs` | `rbis` |
| Home Runs | batting | `homeruns` | `homeRuns` | `homeruns` |
| Walks / Batter Walks | batting | `walks` | `walks` | `walks` |
| Hitter Strikeouts / Batter Strikeouts | batting | `strikeouts` | `strikeouts` | `strikeouts` |
| Hits Allowed | pitching | `hits` | `hits` | `hits` |
| Earned Runs Allowed | pitching | `earnedruns` | `earnedRuns` | `earnedruns` |
| Walks Allowed | pitching | `walks` | `walks` | `walks` |
| Pitcher Strikeouts | pitching | `strikeouts` | `strikeouts` | `strikeouts` |
| Pitches Thrown | pitching | `pitches` | `pitches` | `pitches` |

**RECLASSIFY — `earnedruns`:**
Spec says `earnedruns`. Fixture key is `earnedRuns` (camelCase). Runner lowercases via
`label_l = str(label).lower()`, so stored key is `earnedruns`. CONFIRMED: spec is correct
for the post-lowercase stored key.

**RECLASSIFY — Pitching innings:**
Spec mentions `innings_to_outs(fullInnings, partInnings)`. Fixture key is
`fullInnings.partInnings` (a SINGLE key with a dot, NOT two separate keys).
The value stored is `"1.0"` (a string like "6.2" for 6 full + 2/3 innings).
Implementation must parse `fullInnings.partInnings` as a dotted-decimal where `.1`=1/3 out
and `.2`=2/3 out. The key lowercases to `fullInnings.partInnings` → `fullinnings.partinnings`.

**RECLASSIFY — `pitches` key collision:**
`pitches` appears in BOTH batting and pitching keys.
- Batting `pitches`: pitches SEEN by the batter
- Pitching `pitches`: pitches THROWN by the pitcher
Disambiguation requires namespace split (batting vs pitching group).
`Pitches Thrown` → pitching group `pitches`.

**RECLASSIFY — `homeRuns` in pitching group:**
The pitching group contains `homeRuns` (home runs ALLOWED by pitcher). This is a
shared label with batting. Disambiguation required via namespace split.

#### MLB DERIVED Disposition Keys (Confirmed)

| Derived Stat | Formula | Data Source | Confirmed |
|-------------|---------|-------------|-----------|
| Total Bases | 1×Singles + 2×Doubles + 3×Triples + 4×HRs | `gamepackageJSON.plays[].type.type` in {"single","double","triple","home-run"} per batter | CONFIRMED — play type.type values present |
| Singles | hits - 2B - 3B - HR (OR count plays type.type=="single") | batting hits + plays | CONFIRMED — "single" plays present |
| Pitching Outs | parse `fullInnings.partInnings` value: int_part×3 + frac_part (0, 1, or 2) | pitching key `fullinnings.partinnings` | CONFIRMED — key present, value is "X.Y" dotted string |
| Hits+Runs+RBIs | hits + runs + rbis (batting group) | batting `hits`, `runs`, `rbis` | CONFIRMED — all present |
| Doubles | count plays type.type=="double" per batter (NOT in batting keys directly) | plays | CONFIRMED — "double" plays present |
| Triples | count plays type.type=="triple" per batter | plays | triple not seen in this fixture; "triple" is a valid type per ESPN spec |

**Note — plays `type.type` hit values confirmed in fixture:**
```
"single", "double", "home-run"
```
"triple" not observed in this specific game but is a valid ESPN play type.

**Note — plays batter identification:**
Each play has `participants` array. The batter participant has `type == "batter"` and
`athlete.id` (ESPN athlete numeric ID). Matching plays to players requires cross-referencing
`athlete.id` from the boxscore athletes list.

**Batting keys NOT present as direct DIRECT keys (require plays derivation):**
- `doubles`, `triples` — NOT in the batting `keys` array; must derive from plays
- `singles` — NOT in batting keys; derive from plays OR `hits - 2B - 3B - HR`
- `totalbases` — NOT in batting keys for this fixture (present in some ESPN formats via alias)

---

### MLB Two-Way Player: Will Vest (game 401815839)

Will Vest appears in both groups in the Chicago White Sox batting lineup.
This confirms that namespace collision is real:

**Batting group (Will Vest):**
```json
{"hits-atBats": "0-0", "atBats": "0", "runs": "0", "hits": "0", "RBIs": "0",
 "homeRuns": "0", "walks": "0", "strikeouts": "0", "pitches": "0",
 "avg": ".000", "onBasePct": ".000", "slugAvg": ".000"}
```

**Pitching group (Will Vest):**
```json
{"fullInnings.partInnings": "1.0", "hits": "0", "runs": "1", "earnedRuns": "0",
 "walks": "0", "strikeouts": "0", "homeRuns": "0", "pitches-strikes": "16-11",
 "ERA": "5.92", "pitches": "16"}
```

Without namespace split, the flat dict at `:5337` would write PITCHING `hits`/`runs`/`walks`/
`strikeouts`/`homeRuns`/`pitches` over the BATTING values for Will Vest's key. The batting
stats (0 hits, 0 runs) and pitching stats (1 run allowed) would be indistinguishable.

---

## Stat Corpus Summary

**Source:** `stat_corpus.json` — NBA+MLB union from live Props and Player Props sheets.

| Sport | Count | Includes |
|-------|-------|---------|
| NBA   | 59    | Points, Rebounds, Assists, FG/3PT/FT splits, Blks+Stls, Defensive/Offensive Rebounds, Fantasy Score, all NOT-DERIVABLE specials |
| MLB   | 35    | Hits, Runs, RBIs, Home Runs, Walks, Strikeouts, Total Bases, Singles, Pitching Outs, Fantasy Score variants, 1st inning specials |

"Total Bases" is present in the MLB corpus. Confirmed.

---

## Key Findings for Plan 01-3

The following confirmed corrections affect the disposition table in plan 01-3:

1. **offensiveRebounds / defensiveRebounds** — Runner stores as `offensiverebounds` /
   `defensiverebounds` (lowercased). Use lowercased forms in disposition table.

2. **fieldGoalsMade-fieldGoalsAttempted** — Runner stores as the split string; existing
   alias at `:5349` maps to `"3-pt made"`. Disposition table: map `"FG Made"` to reading
   the split value from the stored key.

3. **earnedRuns** → `earnedruns` (post-lowercase). Spec's `earnedruns` is CORRECT.

4. **fullInnings.partInnings** — This is a SINGLE dot-notation key, NOT two separate keys.
   Value is a string like `"6.2"` where `.1`=1/3 out, `.2`=2/3 out (not decimals).
   `Pitching Outs` derivation: `int("6.2".split(".")[0]) × 3 + int("6.2".split(".")[1])`.

5. **Total Bases / Singles / Doubles** — NOT direct batting keys; must derive from
   `gamepackageJSON.plays[].type.type` per batter athlete ID.

6. **`pitches` key collision** — appears in both batting and pitching groups with different
   meanings. Namespace split (Component 4) is required before `Pitches Thrown` can be
   correctly resolved to the pitching group `pitches`.

7. **`atBats` top-level** — `gamepackageJSON.atBats` does NOT exist in this fixture.
   Hit-type data must come from `gamepackageJSON.plays`, not `atBats`.

8. **Group identity** — `group_data.get("type")` returns `"batting"` / `"pitching"` for MLB,
   and `None` for NBA. `group_data.get("name")` is `None` for BOTH sports in these fixtures.
   The NBA path (single group, no type) must be handled distinctly from MLB's two-group path.
