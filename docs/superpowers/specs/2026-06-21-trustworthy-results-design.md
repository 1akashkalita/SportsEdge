# P1 — Trustworthy Results

**Goal:** Drive the ~37% MANUAL-REVIEW prop-grading rate toward zero, attach provenance (`Result Source` + `Result Confidence`) to every graded prop, recover the 86 historical MANUAL-REVIEW rows over June 8–21, and never crash grading — all within the 660s cron budget.

---

## Context & problem

Player props are graded by `grade_prop` (`sports_system_runner.py:4070`) → `stat_value_for_prop` (`:4039`), which reads an ESPN box-score dict from `espn_player_stats_by_event` (`:5318`). Two confirmed defects make ~37% of prop grades fail:

1. **Name lookup is exact.** `stat_value_for_prop:4040` does `row = player_stats.get(str(player or "").lower())` against keys built from ESPN `displayName`/`shortName` (`:5333`). There is zero accent-folding, punctuation, suffix, or "F. Last" handling. `normalize_player_name` (`:3482`) exists but is only `' '.join(str(value).replace('_',' ').lower().split())` and is **not** in the grading path. Any accent/suffix/initial/punct mismatch → `None`.
2. **MLB stat derivation is substring-only.** `stat_value_for_prop:4064-4066` falls through to `if s == key or s in key or key in s: return value`. There is no MLB composite logic (contrast NBA aliases at `:4044-4062`). This both **returns `None`** for many stats and **mis-grades** others (false positives — see below).

`grade_prop:4080-4081` turns a `None` into `("PENDING", None, f"No final stat line found for {player} {stat}")`, which `grade_game_in_workbook:4614-4616` escalates to `"MANUAL REVIEW"`.

A third defect blocks **batting/pitching disambiguation**: `espn_player_stats_by_event:5337` does `row = stats.setdefault(str(name).lower(), {})` and then writes each group's labels into that single flat dict. Shared MLB labels (`hits`, `runs`, `walks`, `strikeouts`, `homeRuns`) collide — a two-way player (pitcher who bats, or any name appearing in both a batting and a pitching group) has the later group clobber the earlier one. The current code cannot distinguish a hitter's `Strikeouts` from a pitcher's `Strikeouts`.

**Confirmed class breakdown** of the 86 MANUAL REVIEW rows in `data/pnl/master_pnl.xlsx` → "Pick History" (counts: 86 MANUAL REVIEW, 80 LOSS, 63 WIN, 4 PENDING, 4 VOID; 83 MLB / 3 NBA; all carry `Notes` = "No final stat line found…" with null Player/Stat/Line/side columns — only `Pick Ref` col2 `PROP:<Player> <Stat> <Line>` and `Notes` col7 are usable):

| Class | Count | Recoverable from ESPN summary JSON (no scrape)? |
|---|---|---|
| Composite / Fantasy Score (40 hitter + 6 pitcher) | 46 | Only with exact platform formula → **scoped to scraped fallback** |
| Singles | 18 | Yes — derived from `plays`/`atBats` hit types |
| Total Bases | 10 | Yes — derived from `plays`/`atBats` hit types |
| Pitching Outs | 5 | Yes — `innings_to_outs(fullInnings.partInnings)`; must handle `.1/.2` |
| Runs (pure name failure) | 2 | Yes — `R` is a direct box label |
| Hits Allowed / Hits+Runs+RBIs | 2 | Yes — direct / summation |
| NBA (3-PT Made, FG Attempted, Blks+Stls) | 3 | Yes — once name-punct + FG split + `blocks+steals` added |

**Recoverability is fixture-gated, not assumed.** The "recoverable without scrape" counts above are claims to be *proven* by a checked-in ESPN summary fixture (see Component 0) before they are treated as facts. Until that fixture confirms the exact key strings and the `plays`/`atBats` shape, the ~38–40 in-process-recoverable estimate is an upper bound. The **46 Fantasy Score composites** are the genuine residue requiring richer/scraped data and exact platform weighting.

---

## Success criteria (measurable)

1. **Grade coverage (hard gate).** After Layer-1 hardening, a backfill dry-run over **June 8** resolves **≥ 80% of the non-Fantasy-Score MANUAL REVIEW prop rows on that date** (i.e. the name-failure + DIRECT + DERIVED classes) to WIN/LOSS/PUSH. This is the single pass/fail dry-run gate. Over the full June 8–21 range, the 86 MANUAL REVIEW rows drop to the residual Fantasy-Score class minus whatever the (flag-gated) scraped fallback resolves.
2. **Provenance on every graded prop.** Every Results / Pick-History prop row written by grading carries `Result Source ∈ {api, scraped, manual}` and a numeric `Result Confidence`. Non-prop rows (spread/total/parlay/VOID) are handled per the explicit rule in Component 8.
3. **Backfill overwrites.** Re-grading a past date replaces MANUAL REVIEW / PENDING Results rows with terminal grades in place (no duplicate Results or Pick History rows) and leaves WIN/LOSS/PUSH/VOID rows untouched — robust to casing/whitespace variants of the stored Result string.
4. **No crashes.** Verifier crash / timeout / missing-binary / offline / rate-limit degrades to `MANUAL REVIEW`, never an uncaught exception; the runner never imports firecrawl and routes the scrape subprocess through the existing `_subprocess_run_with_retry` SIGALRM machinery.
5. **Cron budget (bounded, not asserted).** A daily reconciliation run stays under 660s. The scraped fallback is residue-only, cached per event, flag-gated (default off), and **capped at `RESULT_SCRAPE_MAX_PER_RUN` games per run** with a measured per-scrape worst case such that `RESULT_SCRAPE_MAX_PER_RUN × per_scrape_timeout < 600s` (see Performance).
6. **No false positives.** No previously-correct exact-match grade *verdict* changes; ambiguous fuzzy matches and ambiguous side parsing abstain to MANUAL REVIEW rather than guess. (Adding two populated provenance columns to an existing correct row is an additive row change, not a verdict change — explicitly permitted.)

---

## Architecture — two isolated layers

**Layer 1 — In-process matching hardening (offline, kills most of the 37%).** Pure functions in `sports_system_runner.py`: a grading-local `_canonical_name` + `name_match`, an explicit `stat_value_for_prop` disposition table (DIRECT / DERIVED / NOT-DERIVABLE) that reads ESPN `plays`/`atBats`, and a batting/pitching namespace split in `espn_player_stats_by_event`. No network, no new deps. Exact match stays first-priority so currently-passing grade verdicts are unchanged.

**Layer 2 — Out-of-process scraped fallback (flagged, subprocess-isolated, residue-only).** A standalone `verify_results.py` wraps the `firecrawl` CLI bin (via `npx`) and is invoked through the runner's existing `_subprocess_run_with_retry` wrapper exactly like `fetch_dfs_props`/`build_hit_rate_db`. The runner **never imports firecrawl**. An in-runner adapter `resolve_missing_stat(...)` consults a per-event box-score cache, shells out only on a miss, parses, and maps. A verifier crash/timeout cannot kill grading because it unwinds through the same SIGALRM/kill path used by the other staged subprocesses.

---

## Components

### 0. ESPN summary fixtures (new, checked in) — the verification oracle
**What:** Two real ESPN summary JSON captures committed under `scripts/testdata/espn_summary/`: one MLB game (with at least one two-way / shared-label player, and a populated `plays`/`atBats` array) and one NBA game. The spec's DIRECT/DERIVED dispositions and the `plays`/`atBats` derivations are validated against the **exact key strings present in these fixtures** before any disposition is treated as confirmed. The full enumerated stat corpus (Component 3 test oracle) is checked in alongside as `scripts/testdata/stat_corpus.json`, sourced from a snapshot of the live Props sheets (NBA + MLB union).
**Why first-class:** Component 4's batting/pitching split and Component 3's key mappings (`defensiverebounds`, `offensiverebounds`, `earnedruns`, `pitches`, `fieldGoals[*]`, `threePoint[*]`) are **assumptions until a fixture confirms them**. If a key string differs, the disposition table is corrected to the real key before implementation — not discovered as a silent MANUAL REVIEW in production.
**Dependencies:** none (static JSON). Capture via the existing `espn_json` CDN endpoint at `:5323`.

### 1. `_canonical_name(name) -> str` (new, grading-local)
**What:** Accent+punct+suffix normalizer for name matching. Order: coerce str → lowercase → NFKD-normalize and drop Unicode combining marks (`unicodedata.combining`) → replace `.` `'` `’` `-` with spaces → drop a trailing token in `{jr, sr, ii, iii, iv}` → collapse whitespace.
**Signature:** `def _canonical_name(name: Any) -> str`
**Dependencies:** `unicodedata` (stdlib). Keep `normalize_player_name:3482` **unchanged** (it is used in non-grading prop-source lookups like `pp_lookup:3520`; changing it widens blast radius).

### 2. `name_match(prop_name, boxscore_keys, game_roster=None) -> str | None` (new)
**What:** Resolves a prop player name to the matching box-score **key** (callers still index `player_stats` by the original key). Tiers, first hit wins:
1. exact `prop_name.lower() in boxscore_keys` — preserves every currently-passing case byte-for-byte.
2. `_canonical_name` equality between prop and each key.
3. Initial-form bridge: one side is `"X last"` (single-letter first token) → match a key whose first token startswith `X` and last token equals last token, **only if exactly one** such key.
4. Last-name-unique fallback: if exactly one key shares the canonical last token, return it; else `None` (abstain).
**Signature:** `def name_match(prop_name: str, boxscore_keys, game_roster=None) -> str | None`
**Dependencies:** `_canonical_name`. Roster surrogate = `player_stats.keys()` (no new network call). Must canonicalize **both** sides — box keys can already be `"f. last"` form when `displayName` absent (`:5333` shortName fallback).
**Must match** (test corpus): Jokic/Jokić, Doncic/Dončić, Acuna Jr./Acuña Jr., Harris/Harris II, PJ/P.J. Washington, De'Aaron/DeAaron Fox, Gilgeous Alexander/Gilgeous-Alexander, "L. Doncic"/"Luka Dončić", "Guerrero Jr"/"Guerrero Jr.". **Must abstain:** `("J. Williams", {"jalen williams","jaylin williams"}) -> None`.

### 3. `stat_value_for_prop` — explicit disposition table + provenance return (rewrite of `:4039-4067`)
**What:** Replace the substring fallback (`:4064-4066`, the root cause of false positives — `1st Inning Runs Allowed`→full-game `runs`, `Quarters with 3+ Points`→`points`, `Points - 1st 3 Minutes`→`minutes`, `Defensive/Offensive Rebounds`→total `rebounds`) with an explicit map keyed by canonical lowercased Stat (lowercase; collapse `+`/`_`/spaces consistently). One of three dispositions per Stat:

- **DIRECT box key** — NBA: Points→points, Rebounds→rebounds, Assists→assists, Steals→steals, Blocked Shots→blocks, Turnovers→turnovers, Personal Fouls→fouls, **Defensive Rebounds→defensiverebounds, Offensive Rebounds→offensiverebounds**, 3-PT Made→`3-pt made`; MLB: Hits→hits, Runs→runs, RBIs→rbis, Home Runs→homeruns, Walks→walks, Hitter/Pitcher Strikeouts→strikeouts (correct group), Hits Allowed→hits (pitching group), Earned Runs Allowed→earnedruns, Walks Allowed→walks (pitching), Pitches Thrown→pitches. **Every DIRECT key is confirmed against the Component 0 fixtures before commit; any key not present in the fixture is reclassified DERIVED or NOT-DERIVABLE.**
- **DERIVED by formula** — NBA: Blks+Stls=blocks+steals, FG Made=fieldGoals[0], FG Attempted=fieldGoals[1], Two Pointers Made=FGmade−3PTmade, Free Throws Made/Attempted split, 3-PT Attempted=threePoint[1] (existing PRA/Pts+Rebs/Pts+Asts/Rebs+Asts retained); MLB: Hits+Runs+RBIs=hits+runs+rbis, Total Bases=1B+2·2B+3·3B+4·HR (from `plays`/`atBats`), Singles=hits−2B−3B−HR (from play types), Pitching Outs=`innings_to_outs(fullInnings, partInnings)` (handle `.1/.2` fractional innings, not tenths).
- **NOT DERIVABLE from summary box** — Hitter/Pitcher Fantasy Score, NBA Fantasy Score/Dunks/Double-Double, all period/`1st 3 Minutes`/`Quarters with N+`/high-scorer specials, `1st Inning Runs/Walks Allowed` (needs play-by-play scoping, never full-game substring), `(Combo)` two-player props. Return `(None, "manual", 0.0)` (→ MANUAL REVIEW or scraped fallback); **never** substring-match these to a full-game stat.

**Batting vs pitching disambiguation:** shared keys (hits, runs, walks, strikeouts, homeRuns) exist in both groups. The disposition table tags each MLB Stat as a hitter or pitcher stat (PrizePicks encodes this: `Hitter Strikeouts` vs `Pitcher Strikeouts`; `Pitcher*`/`*Allowed` = pitching group) and pulls from the correct namespace produced by Component 4.

**Provenance return (signature change).** `stat_value_for_prop` now returns a 3-tuple so confidence/source propagate end-to-end:
`def stat_value_for_prop(player_stats, player, stat) -> tuple[float | None, str, float]` returning `(value, source, confidence)`:
- exact name + DIRECT key → `("api", 1.0)`
- DERIVED formula → `("api", 0.8)`
- fuzzy name (tiers 2–4) on a DIRECT/DERIVED stat → `("api", 0.6)`
- NOT-DERIVABLE or unresolved → `(None, "manual", 0.0)`

Name resolution swap at `:4040`: `key = name_match(str(player or ""), player_stats.keys()); row = player_stats.get(key) if key else None`.
**Caller updates (every call site).** `grade_prop:4079` consumes the new tuple. Any `test_*` caller of `stat_value_for_prop` is updated to the new return shape before the signature change lands (grep for callers; the function is otherwise internal to grading).
**Dependencies:** `name_match`, ESPN `plays`/`atBats` (already returned by the CDN endpoint at `:5323`), `innings_to_outs` (mirror `build_hit_rate_db.py:165/369`), Component 4 namespaced rows.

### 4. `espn_player_stats_by_event` extension (`:5318`) — namespaced groups + hit types
**What:** Two additive changes, both fixture-validated:
1. **Batting/pitching namespace split.** Replace the clobbering flat `row = stats.setdefault(name.lower(), {})` at `:5337` with per-group namespaces so shared labels do not overwrite: each player row becomes `{ "batting": {...}, "pitching": {...}, <existing flat NBA keys> }`. Group identity is derived from `group_data` (the ESPN `statistics` group name/keys at `:5329-5330`: e.g. `batting` vs `pitching`). NBA (single group) keeps its existing flat keys unchanged so NBA grading and aliases (`:5346-5357`) are byte-identical. `stat_value_for_prop` selects `row["batting"]` or `row["pitching"]` per the Stat's group tag.
2. **Per-player hit-type counts from `plays`/`atBats`.** Surface Single/Double/Triple/Home-Run counts per player from the summary `plays`/`atBats` arrays so Total Bases / Singles derive **without a scrape**. Exact array path and field names are taken from the Component 0 MLB fixture.
**Backward-compat guard:** the existing NBA aliasing and FG/3PT split-on-`-` logic (`:5341-5357`) is preserved verbatim for the NBA single-group case. A regression assertion confirms a known NBA box yields identical keys pre/post change.
**Dependencies:** existing `espn_json` CDN call (`:5323`); no new endpoint.

### 5. `verify_results.py` (new, subprocess-isolated scraped fallback)
**What:** Standalone script (never imported by the runner). Scrapes one ESPN box-score web page for the residue Fantasy-Score class and emits a normalized JSON stat dict on stdout.
**Invocation contract (corrected, exact).** Invoke the real `firecrawl` bin (the package `firecrawl-cli` exposes a bin named `firecrawl`) with **markdown** output (1 credit, server-rendered ESPN box is sufficient), not LLM `--format json` (which needs a `--schema`/`--prompt` and costs 4 extra credits):
```
npx -y firecrawl-cli@1.19.2 firecrawl scrape \
  https://www.espn.com/{sport}/boxscore/_/gameId/{game_id} \
  --format markdown
```
(`sport ∈ {mlb, nba}`; `game_id` = ESPN numeric id.) `verify_results.py` contains a **deterministic ESPN box-table markdown parser** that turns the rendered table into `{ "<canonical_name>": { "<stat_key>": <float> } }`. The `--format json` path is explicitly rejected (no schema = empty extraction; +4 credits worsens the daily cap). `--browser` is **forbidden** in the command (it triggers cloud-Chromium/login flows irrelevant to a static box score).
**Keyless-first (corrected premise).** Firecrawl supports keyless scraping via the CLI (rate-limited per IP). The script runs with **no key by default**; `FIRECRAWL_API_KEY` is injected only when present (for higher limits). The runner/adapter does **not** treat a missing key as "fallback off" — only a missing binary/Node, a non-zero npx exit, or a 429/rate-limit response degrades the run.
**Version pin (no `@latest`).** Pin the concrete version `firecrawl-cli@1.19.2` in a module constant; `@latest` is forbidden in cron (per-run re-resolve + drift). Do **not** run `init` / `init --all` on the cron host (mutates coding-agent configs).
**CLI:** `python3 verify_results.py --sport <mlb|nba> --game-id <id> [--date <YYYY-MM-DD>]`
**Output schema (versioned, status-tagged).** `JSON_RESULT={...}` with an explicit envelope so the adapter distinguishes "scraped fine but player/stat absent" from "scrape failed":
```
{ "status": "ok" | "skip", "schema": 1, "reason": "<str, when skip>",
  "players": { "<canonical_name>": { "<stat_key>": <float>, ... }, ... } }
```
`status="skip"` ⇒ scrape could not run (binary/Node/network/429); `status="ok"` with the player absent ⇒ a legitimate "not in box" that the adapter records so it is **not** re-scraped every run.
**Dependencies:** `subprocess`, `json`, Node/npx + `firecrawl-cli@1.19.2` (pinned), optional `FIRECRAWL_API_KEY`. Node v26 / npx 11 are present on the current cron host (verified); a programmatic preflight (Component 6) guards drift.

### 6. `resolve_missing_stat(sport, game, player, stat) -> tuple[float|None, str, float]` (new in-runner adapter)
**What:** Called by the grading loop **only** when Layer-1 returns `(None, "manual", 0.0)` **and** `ENABLE_FIRECRAWL_RESULT_FALLBACK` is on **and** the per-run scrape budget is not exhausted. Steps:
1. **Preflight:** `shutil.which("npx")` and `shutil.which("node")`; if either is absent, log a one-time warning and return `(None, "manual", 0.0)` (degrade, never raise).
2. **game_id resolution:** the ESPN numeric `game_id` is taken from `game.get("event_id") or game.get("id")` (the same value `grade_game_in_workbook:4565` already passes to `espn_player_stats_by_event`). If absent, degrade — a scrape with no game id is impossible.
3. **Cache read** `data/research/results_cache/<event_id>.json` (mkdir `parents=True, exist_ok=True` on first write, since `results_cache/` does not yet exist).
4. **On cache miss:** invoke `verify_results.py` via the runner's existing **`_subprocess_run_with_retry`** (NOT a bare `subprocess.run`) with a hard `timeout` of `RESULT_SCRAPE_TIMEOUT` and `context="verify_results <event_id>"`. Inherit `os.environ` (npx needs `PATH`/`HOME` to find node) and overlay `FIRECRAWL_API_KEY` only when present — never pass a minimal `env=` that strips `PATH`. Parse `JSON_RESULT`; on `status="ok"` write the cache, on `status="skip"` do **not** cache a permanent failure.
5. **Resolve** the player via `name_match` over the scraped dict; map the Stat via the same disposition table.
**Returns** `(value, "scraped", 0.5)` on success; `(None, "manual", 0.0)` on any failure, skip, timeout, or absent player/stat. A successful scrape that legitimately lacks the player/stat (`status="ok"`, player absent) is cached so it is not re-attempted each run.
**Signature:** `def resolve_missing_stat(sport: str, game: dict, player: str, stat: str) -> tuple[float | None, str, float]`
**Dependencies:** box-score cache, `verify_results.py` (via `_subprocess_run_with_retry`), `name_match`, `shutil`.

### 7. Per-event box-score cache
**What:** `data/research/results_cache/<event_id>.json` holds the normalized scraped stat dict per game so a backfill verifies each game **at most once**. `data/research/` already exists; `results_cache/` is created on first write (`mkdir(parents=True, exist_ok=True)`) — alternatively `ensure_dirs():288` may create it. A cache hit avoids any npx call.

### 8. Provenance columns + end-to-end plumbing (additive)
**What:** Append `"Result Source"` and `"Result Confidence"` to the `RESULT_HEADERS` **list literal after the `+ MARKET_CONTEXT_FIELDS` term** (`:271-277` ends with `+ MARKET_CONTEXT_FIELDS` spliced at `:277`; the two new names go after that splice). Column **order is irrelevant** — `ensure_ws_columns` appends missing columns at `max_column+1` by name and every Results read is name-keyed via `result_headers(ws):4126`. Migration is automatic via `result_headers(ws)` and the schema-migrating `ensure_workbook:1782`; new columns flow to master/bankroll through `sync_master_and_bankroll` because `Pick History` shares `RESULT_HEADERS` (`master_pnl_workbook:4285`).

**End-to-end contract (the previously-missing wiring), naming every touched line:**
- (a) `stat_value_for_prop` returns `(value, source, confidence)` — Component 3.
- (b) `grade_prop:4070` returns a 5-tuple `(result, actual, note, source, confidence)`. It unpacks `stat_value_for_prop` at `:4079`, carries `source`/`confidence` through the WIN/LOSS/PUSH branches (`:4082-4090`), and returns `("manual", 0.0)` on the PENDING/missing-line branches (`:4072`, `:4078`, `:4081`).
- (c) `result_record_from_source:4229` gains two record keys (`record["Result Source"]`, `record["Result Confidence"]` added in the dict at `:4237-4270`) sourced from `extra.get("Result Source")` / `extra.get("Result Confidence")`.
- (d) Prop call site `:4613-4620`: unpack the 5-tuple from `grade_prop`; pass `"Result Source"`/`"Result Confidence"` through the existing `extra` dict at `:4620`. The MANUAL REVIEW escalation branch (`:4614-4616`) sets `source="manual", confidence=0.0`. When `result == "MANUAL REVIEW"` and `ENABLE_FIRECRAWL_RESULT_FALLBACK` is on and budget remains, call `resolve_missing_stat`; on a `"scraped"` resolve, re-grade the side and set `Result Source="scraped"`, `Result Confidence=0.5`.
- (e) VOID branch (`:4611`) and **non-prop rows** (spreads/totals `:4595`, parlays `:4651`): set `Result Source="api"`, `Result Confidence=1.0` explicitly. Rationale: these grade deterministically from the final game object, not from name/stat matching, so `api`/`1.0` is accurate and avoids leaving blank cells that a reviewer could misread. Criterion #6 is satisfied — the grade *verdict* is unchanged; only two additive columns populate.

**Values summary:** `api` (Layer-1 resolve — 1.0 exact-DIRECT / 0.8 derived / 0.6 fuzzy-name; 1.0 for spread/total/parlay/VOID), `scraped` (Layer-2 resolve — 0.5), `manual` (unresolved → MANUAL REVIEW — 0.0).

---

## Data flow

### Grading (per prop)
ESPN summary box score (`espn_player_stats_by_event:5318`, now namespaced + incl. `plays`/`atBats`) → `stat_value_for_prop:4039` (hardened `name_match` + disposition table) → `(value, source, confidence)`. Value found → grade with that `Result Source`/`Result Confidence`. If `value is None` (→ MANUAL REVIEW) **and** `ENABLE_FIRECRAWL_RESULT_FALLBACK` **and** budget remains → `resolve_missing_stat` (preflight → cache → `_subprocess_run_with_retry` `verify_results.py` → parse → map): resolved → grade with `Result Source=scraped`, `0.5`; else → `MANUAL REVIEW`, `Result Source=manual`, `0.0`. The existing PENDING→MANUAL REVIEW escalation (`grade_prop`/`:4614-4616`) remains the final fallback.

### Backfill overwrite mechanism (the exact, money-safe guard change)
The read-side guard at `:4560` (`already = existing_result_refs(...)`) is value-blind: a MANUAL REVIEW / PENDING ref is "present", so the three loops' `if ref in already: continue` (`:4580`, `:4607`, `:4632`) silently skip re-grade even when `check_results:4771 → game_completion_monitor(reconciliation=True)` forces `should_grade=True`.

**Change 1 — value-aware, normalization-robust guard.** Add `existing_result_map(results_ws, date, sport_label) -> dict[str, str]` returning `{ref: current_result_str}` (mirror `existing_result_refs:4430-4436`, also reading the `Result` column via `result_headers`). Define a module constant `TERMINAL_RESULTS = {"WIN", "LOSS", "PUSH", "VOID"}`. Replace `:4560` with this map and change all three loop guards to:
```
if (already.get(ref) or "").strip().upper() in TERMINAL_RESULTS: continue
```
The `.strip().upper()` makes the guard robust to legacy/casing/whitespace variants (`"Win"`, `"push "`, `" VOID"`) so a settled bet is never re-graded and flipped. An empty/blank stored `Result` is intentionally **non-terminal** → re-gradeable (a present-but-ungraded row should grade). PENDING and MANUAL REVIEW fall through and re-grade; settled rows are skipped.

**Change 2 — parlay legs sourced from persisted Results, not only this-run `graded` (money-safety fix).** Under Change 1, already-terminal prop/spread legs are skipped and therefore **absent** from the in-process `graded` list, but the parlay loop at `:4638` aggregates legs solely from `graded`. A MANUAL REVIEW parlay whose legs settled in a prior run would re-aggregate against a partial leg set and could flip a true LOSS to WIN — a real-money mis-grade the looser guard *activates*. Fix: before computing a parlay verdict at `:4638`, assemble the **full** leg-result set for that game/date by merging (a) this-run `graded` legs with (b) the persisted terminal leg results read from `existing_result_map` (Results sheet). If any constituent leg is still non-terminal/absent after the merge, the parlay **abstains** (stays at its prior result, skipped) rather than grading against an incomplete set. The previous claim "props run before parlays so aggregation sees freshly re-graded legs" is corrected: it sees only *freshly* re-graded legs, which is insufficient under mixed-settlement backfill.

**No other change needed.** `upsert_result_row:4439` is an in-place upsert keyed on Date[:10]+Sport+Pick Ref (overwrites the same Results row — no duplicate). `sync_master_and_bankroll:4465` calls `remove_master_pick_history_ref:4456` per newly-graded ref **before** `ph.append` (replace-by-ref — no duplicate Pick History row). Daily Log / Bankroll Chart Data are rebuilt from Pick History each sync (`:4495-4503`), and units/pnl already exclude PENDING/MANUAL REVIEW (`:4501-4502`), so a re-graded terminal row contributes correctly. **Double-sync idempotency (explicit):** `grade_game_in_workbook` calls `sync_master_and_bankroll(date, graded)` at `:4659`, and `check_results:4775` calls `sync_master_and_bankroll(date, [])` again; the second call with empty `newly_graded` only rebuilds Daily Log / Bankroll from existing Pick History (no append), so it does **not** double-count — a regression test pins this so a future signature edit can't silently break it. A re-graded row ESPN still can't resolve returns to MANUAL REVIEW and stays re-gradeable next run.

### Side recovery for backfill (new parsing, must abstain on ambiguity)
The 86 MANUAL REVIEW rows have null `Player/Stat/Line/Side` structured columns; `grade_prop:4076` derives side from `Opponent/Description`, which is also null on these rows. Side must be re-parsed from the `PROP:<Player> <Stat> <Line>` Pick Ref string. The parser must handle **multi-word stats** (`Hits Allowed`, `Total Bases`, `Pitcher Strikeouts`) — a naive split-on-space mis-segments stat vs line. Because the Pick Ref alone may not encode Over/Under, **if the side cannot be unambiguously recovered, the row abstains to MANUAL REVIEW** (consistent with `name_match`'s abstain policy) rather than producing a confidently-wrong terminal grade — strictly safer than the current MANUAL REVIEW state. A test covers the exact `PROP:<Player> <Stat> <Line>` format with multi-word stats and confirms whether side is recoverable at all for these rows; if not, those specific rows remain MANUAL REVIEW by design and are not counted against Criterion #1's non-Fantasy target.

---

## Config / flags / secrets

- `ENABLE_FIRECRAWL_RESULT_FALLBACK` — `env_bool`, **default off**. When off, Layer-2 is never invoked; Layer-1 alone runs.
- `FIRECRAWL_API_KEY` — read via `env_value('FIRECRAWL_API_KEY')` from `~/.hermes/.env` (currently commented). **Optional** — scraping runs keyless by default; the key only raises limits. A missing key does **not** disable the fallback.
- `RESULT_SCRAPE_TIMEOUT` — per-game hard subprocess timeout (default 45s; passed to `_subprocess_run_with_retry`).
- `RESULT_SCRAPE_MAX_PER_RUN` — max games scraped per run (default 8), enforcing Criterion #5's budget bound. Backfill is resumable across days against this cap; the per-event cache prevents re-scraping resolved games.
- Pinned CLI version constant `firecrawl-cli@1.19.2` in `verify_results.py`; never `@latest`.
- No secrets hardcoded; no in-code fallback key.

---

## Error handling & degradation

- **Verifier failure / timeout / offline / non-zero npx exit / 429 rate-limit** → adapter logs → returns `(None, "manual", 0.0)` → MANUAL REVIEW. Routed through `_subprocess_run_with_retry`, so SIGALRM kills a hung child and unwinds past the retry (alarm always wins) — the broken-pipe/timeout failure class this milestone exists to kill cannot be reintroduced here.
- **`npx` / `node` missing (binary preflight)** → `shutil.which` guard → one-time warning → Layer-1-only; grading proceeds.
- **firecrawl key missing** → irrelevant; keyless scrape proceeds (degradation is keyed on binary/exit/429, not key presence).
- **Ambiguous name match** (`name_match` tiers 3–4 not unique) → `None` → MANUAL REVIEW. Never guess in a real-money grader.
- **Ambiguous side parse** (backfill) → MANUAL REVIEW. Never produce a confidently-wrong terminal grade.
- **NOT-DERIVABLE stats** → `(None, "manual", 0.0)` → MANUAL REVIEW (or scraped when flagged). Never substring-fall-through.
- **Incomplete parlay leg set** → abstain (parlay stays at prior result). Never aggregate a real-money parlay against partial legs.
- **Runner never imports firecrawl** — all firecrawl risk is contained in the `verify_results.py` child process.

---

## Performance / cron budget

- Layer-1 is offline and adds negligible time; it removes most MANUAL REVIEW work.
- Layer-2 is **residue-only** (invoked only on Layer-1 `None` + flag on + budget remaining) and **cached per event**, so each game is scraped at most once across a backfill.
- **Bounded budget (not asserted).** Worst case per run = `RESULT_SCRAPE_MAX_PER_RUN × RESULT_SCRAPE_TIMEOUT`. With defaults `8 × 45s = 360s < 600s` (active cron kill 720s; RES-03 budget <660s). A single backfill date with > 8 residue games carries the remainder to the next run (resumable), so no single run exceeds the cap. The per-scrape wall-clock (cold `npx` start + cloud scrape + markdown parse) is **measured once empirically** before the defaults are committed; if the measured worst case pushes `MAX_PER_RUN × TIMEOUT` toward 600s, `MAX_PER_RUN` is lowered or the backfill scrape pass is moved out of the cron path into a manual one-off.
- **Keyless caps are per-day, not 10/min.** Keyless firecrawl enforces per-IP per-day request and credit caps (429 on breach); a markdown scrape is 1 credit. The cap and the `MAX_PER_RUN` budget are reconciled by resumable backfill + caching; on a 429 the run degrades the remaining residue to MANUAL REVIEW and resumes next day.
- **npx cold-start note:** `npx -y firecrawl-cli@1.19.2` re-resolves/downloads on a cache-cold host. Recommended (operational, not code): `npm i -g firecrawl-cli@1.19.2` on the cron host to avoid the one-time multi-second penalty; otherwise accept it once. Noted in the backfill plan.
- With the flag off (default), Layer-2 budget impact is ~zero.

---

## Testing strategy (offline-first)

1. **`test_name_match.py` (offline unit).** Assert the 9 positive (prop_name, espn_name) pairs in Component 2 resolve to the correct box-score key, plus `("J. Williams", {"jalen williams","jaylin williams"}) -> None`. Assert exact-match cases are byte-identical (pure superset of current behavior).
2. **`test_stat_value_for_prop.py` (offline unit, fixture-backed).** Drive the **checked-in stat corpus** (`scripts/testdata/stat_corpus.json`, NBA + MLB union) through `stat_value_for_prop` against the Component 0 fixtures and assert **each stat maps to exactly one enumerated disposition** — `{DIRECT key X, DERIVED formula Y, NOT-DERIVABLE}` per the spec's table, which is the test oracle. (The assertion is "resolves to the enumerated disposition," not "didn't hit a substring fallback" — the fallback no longer exists.) Include regression cases for the prior false positives (Defensive vs Offensive Rebounds distinct, `1st Inning Runs Allowed` → `None`, `Points - 1st 3 Minutes` → `None`) and the derived MLB stats (Total Bases, Singles via `plays`, Pitching Outs `.1/.2`, H+R+RBI). Assert each tuple's `(source, confidence)` matches the Component 3 table.
3. **`test_espn_namespacing.py` (offline, fixture).** Against the MLB fixture with a two-way/shared-label player, assert batting `strikeouts` and pitching `strikeouts` are both retrievable and do not clobber. Against the NBA fixture, assert the namespaced change leaves NBA flat keys/aliases byte-identical to the pre-change output.
4. **`verify_results.py` parser test (saved markdown fixture, no live scrape).** Parse a **saved firecrawl markdown fixture** of one ESPN box score; assert the normalized `{name: {stat: value}}` dict and the `status="ok"` envelope. Plus a `status="skip"` fixture asserting the adapter degrades to `(None,"manual",0.0)`. No network in CI.
5. **`verify_results.py` smoke test (live, CI-skippable).** Run the exact `npx … firecrawl scrape … --format markdown` command against one real `game_id` and assert a non-empty parse. Marked skip-by-default (network) so CI stays offline; run once manually to confirm the keyless contract before wiring into cron.
6. **Integration (scraped path).** API box deliberately misses a player but the per-event cache resolves it → assert grade is WIN/LOSS and `Result Source=scraped`, `Result Confidence=0.5`.
7. **Provenance plumbing test.** A normal API grade writes `Result Source=api` with the correct confidence (1.0 exact / 0.8 derived / 0.6 fuzzy); a spread/total/parlay/VOID row writes `Result Source=api`, `1.0`.
8. **Backfill regression (`grade_game_in_workbook`).** Seed Results rows: one `MANUAL REVIEW` prop, one `WIN` prop, and stored-Result casing variants (`"Win"`, `"push "`, `" VOID"`); run `grade_game_in_workbook` with a final game + valid stat line. Assert: the MANUAL REVIEW row overwrites to terminal; the casing-variant terminal rows are **skipped** (not re-graded); the Results row count per ref stays 1; master_pnl Pick History has exactly one row per ref; and the second `sync_master_and_bankroll(date, [])` does not double-count.
9. **Parlay-leg backfill test (money-safety).** Seed two terminal prop legs (1 WIN, 1 LOSS) as existing Results rows plus a MANUAL REVIEW parlay over both; re-grade with the new guard. Assert the parlay resolves to **LOSS** (full leg set from persisted Results), not WIN/PENDING; and a parlay with one still-missing leg **abstains** (stays prior).
10. **Side-parser test.** Parse `PROP:<Player> <Stat> <Line>` with multi-word stats (`Hits Allowed`, `Total Bases`, `Pitcher Strikeouts`); assert correct stat/line segmentation and **abstain-to-MANUAL-REVIEW** when side is unrecoverable.
11. **Backfill dry-run gate on June 8.** Assert ≥ 80% of the non-Fantasy MANUAL REVIEW prop rows for `data/mlb/mlb_2026-06-08.xlsx` resolve to WIN/LOSS/PUSH after Layer-1 hardening (Criterion #1 pass/fail gate).

Run targeted (`python3 test_name_match.py`) per the slow-suite memory; full `pytest` only at phase end (clean baseline = "2 failed, 202 passed", the 2 known projection failures).

---

## Backfill plan for June 8–21

1. Land Component 0 fixtures + Layer-1 hardening (name_match, disposition table, ESPN namespacing) + the value-aware/normalization-robust guard + the parlay full-leg-set fix + provenance columns/plumbing.
2. (Optional, operational) `npm i -g firecrawl-cli@1.19.2` on the cron host to avoid npx cold-start latency if Layer-2 will run.
3. For each date June 8–21, run `check_results` (→ `game_completion_monitor(reconciliation=True)`, forcing `should_grade=True`). MANUAL REVIEW / PENDING Results rows re-enter grading; settled WIN/LOSS/PUSH/VOID rows are skipped (casing-robust).
4. Re-grading re-parses the bet **side** from the `PROP:` Pick Ref (rows have null structured columns), abstaining to MANUAL REVIEW on ambiguity; resolves via Layer-1; flag-gated Layer-2 handles residue within `RESULT_SCRAPE_MAX_PER_RUN`. `upsert_result_row` overwrites in place; `sync_master_and_bankroll` replaces Pick History by ref and rebuilds Daily Log / Bankroll Chart Data.
5. Rows that still cannot resolve return to MANUAL REVIEW and remain re-gradeable. Fixing the guard also clears the persistent "Pending/manual review rows still open" telegram loop (`check_results:4776/4798`) for backfilled dates.
6. ESPN summary availability for older dates is unverified and may cap how many of the 86 are re-gradable regardless of matching; this is measured during the dry-run, not assumed.

---

## Open questions / risks

- **Fantasy Score formula (46 rows, the residue).** Components are in the ESPN box + `plays`, but the exact PrizePicks/Underdog weighting is unencoded; a subtly-wrong formula would mis-grade real money. Separate, higher-risk sub-workstream; the scraped fallback is scoped **only** to this class, never to Singles/Total Bases.
- **Keyless firecrawl, empirically unconfirmed end-to-end.** The keyless markdown-scrape + parser contract must be confirmed once via the live smoke test (Strategy #5) before the flag is enabled in cron. Until then the flag stays off and Layer-1 carries the milestone.
- **ESPN summary key strings.** The DIRECT/DERIVED dispositions are validated against the Component 0 fixtures before commit; any mismatch is corrected there, not in production.
- **Side recovery.** MANUAL REVIEW rows lack a stored Over/Under side; it is re-parsed from the Pick Ref and abstains on ambiguity. Going forward, persist Player/Stat/Line/Side as real columns so future failures are gradable without string-parsing (recommended, additive, **out of scope for P1**).
- **ESPN box vs gamelog divergence.** Grading uses the summary CDN endpoint (narrow keys, IP as innings); the gamelog endpoint `build_hit_rate_db.py` uses has totalBases/innings→outs natively. This spec derives the missing MLB stats from the summary `plays`/`atBats` rather than switching endpoints — that boundary stays explicit.
- **VOID is intentionally permanent.** `TERMINAL_RESULTS` includes VOID, so a previously-VOID game that ESPN later un-postpones will not auto-re-grade. Accepted for P1.

---

## Out of scope

Slip reconstruction (P2), bankroll rebase (P3), feedback loop (P4), live board fetching. No changes to gate logic, pick generation, or pick output verdicts. No workbook schema changes beyond the two additive `RESULT_HEADERS` columns. No self-hosted firecrawl instance; no `init` / `init --all` on the cron host; no `--browser`/`--format json` in the scrape command. Persisting Player/Stat/Line/Side as real structured columns is recommended but deferred.
