---
phase: 01-trustworthy-results
plan: 3
type: execute
wave: 3
depends_on: ["01-1", "01-2"]
files_modified:
  - scripts/sports_system_runner.py
  - scripts/test_stat_value_for_prop.py
  - scripts/test_provenance_plumbing.py
autonomous: true
requirements: [RESULTS-01, RESULTS-02, RESULTS-03, RESULTS-04]
must_haves:
  truths:
    - "Each Stat in the corpus resolves to exactly one enumerated disposition: a DIRECT key, a DERIVED formula, or NOT-DERIVABLE"
    - "The substring fallback is gone: '1st Inning Runs Allowed' and 'Points - 1st 3 Minutes' return None, and Defensive vs Offensive Rebounds resolve to distinct keys"
    - "stat_value_for_prop returns a 3-tuple (value, source, confidence) with the spec's source/confidence mapping"
    - "Every prop Results row written by grading carries Result Source and Result Confidence; spread/total/parlay/VOID rows carry api/1.0"
    - "Existing exact-match grade verdicts are unchanged (additive provenance columns only)"
  artifacts:
    - path: "scripts/sports_system_runner.py"
      provides: "Rewritten stat_value_for_prop disposition table (3-tuple), 5-tuple grade_prop, RESULT_HEADERS + provenance, end-to-end plumbing"
      contains: "Result Source"
    - path: "scripts/test_stat_value_for_prop.py"
      provides: "Fixture+corpus disposition test with false-positive regressions and (source,confidence) assertions"
      contains: "Total Bases"
    - path: "scripts/test_provenance_plumbing.py"
      provides: "Asserts api/scraped/manual provenance flows to Results rows incl. spread/total/parlay/VOID = api/1.0"
      contains: "Result Confidence"
  key_links:
    - from: "stat_value_for_prop"
      to: "name_match + espn batting/pitching namespaces (plan 01-2)"
      via: "name resolution swap + group-tagged stat lookup"
      pattern: "name_match"
    - from: "grade_prop"
      to: "result_record_from_source extra dict"
      via: "5-tuple -> Result Source / Result Confidence keys"
      pattern: "Result Source"
---

<objective>
Replace `stat_value_for_prop`'s substring fallback with an explicit DIRECT/DERIVED/NOT-DERIVABLE disposition table that returns `(value, source, confidence)` (RESULTS-01/02/03), and thread provenance end-to-end so every graded Results row carries `Result Source` and `Result Confidence` (RESULTS-04). This is the heart of Layer 1: it kills the false-positive substring matches AND closes the name/stat coverage gap, using the `name_match` and batting/pitching namespaces delivered in plan 01-2.

Purpose: The substring fallback at `:4064-4066` both returns None for derivable stats and mis-grades others (`1st Inning Runs Allowed` → full-game `runs`, `Points - 1st 3 Minutes` → `minutes`, Defensive/Offensive Rebounds → total `rebounds`). An explicit table validated against the 01-1 fixtures eliminates both failure modes and makes provenance observable on every row.

Output: rewritten `stat_value_for_prop`, 5-tuple `grade_prop`, two new `RESULT_HEADERS` columns with full plumbing through `result_record_from_source` and every grading call site, and two offline tests.
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
@.planning/phases/01-trustworthy-results/01-2-SUMMARY.md

<interfaces>
<!-- Exact current shapes to evolve. From sports_system_runner.py: -->

stat_value_for_prop(player_stats, player, stat) -> float | None   at :4039
  CURRENTLY: row = player_stats.get(str(player or "").lower()); substring fallback at :4064-4066 (DELETE THIS).
  NEW SIGNATURE: -> tuple[float | None, str, float]   returning (value, source, confidence).
  Name swap at :4040: key = name_match(str(player or ""), player_stats.keys()); row = player_stats.get(key) if key else None.

grade_prop(row, player_stats, game_final) -> tuple[str, float|None, str]   at :4070
  NEW: -> tuple[str, float|None, str, str, float]  (result, actual, note, source, confidence).
  Unpacks stat_value_for_prop at :4079; carries source/confidence through WIN/LOSS/PUSH at :4082-4090;
  returns ("manual", 0.0) on PENDING/missing-line branches at :4072, :4078, :4081.

result_record_from_source(date, sport_label, source, ref, result, actual, units, pnl, graded_at, note, game_label, clv_row=None, extra=None)  at :4229
  ADD two record keys (in the dict at :4237-4270): record["Result Source"] = extra.get("Result Source"); record["Result Confidence"] = extra.get("Result Confidence").

RESULT_HEADERS  at :271-277  ends with  ] + MARKET_CONTEXT_FIELDS  (splice at :277).
  Append "Result Source" and "Result Confidence" AFTER the + MARKET_CONTEXT_FIELDS term. Order is irrelevant —
  ensure_ws_columns appends missing columns by name; every Results read is name-keyed via result_headers(ws):4126.
  Migration is automatic via result_headers + ensure_workbook:1782; flows to master/bankroll because Pick History
  shares RESULT_HEADERS (master_pnl_workbook:4285).

Prop call site at :4613-4620 (in grade_game_in_workbook). Spread/total grade at :4585-4590; VOID at :4583/:4610; parlay at :4651.
innings_to_outs analog in build_hit_rate_db.py:165 (handles ".1/.2": int(whole)*3+int(frac[:1])).
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Rewrite stat_value_for_prop as an explicit disposition table returning (value, source, confidence)</name>
  <read_first>
    - docs/superpowers/specs/2026-06-21-trustworthy-results-design.md (Component 3 — the full DIRECT/DERIVED/NOT-DERIVABLE table; batting/pitching group tagging; the provenance source/confidence mapping; Testing strategy #2)
    - .planning/phases/01-trustworthy-results/01-1-SUMMARY.md (confirmed key strings + RECLASSIFY flags — the source of truth over the spec's assumed names)
    - .planning/phases/01-trustworthy-results/01-2-SUMMARY.md (the batting/pitching group strings and plays/atBats path)
    - scripts/sports_system_runner.py (stat_value_for_prop:4039-4067; existing NBA aliases at :4044-4062)
    - scripts/build_hit_rate_db.py (innings_to_outs:165 — mirror for Pitching Outs)
  </read_first>
  <files>scripts/sports_system_runner.py, scripts/test_stat_value_for_prop.py</files>
  <behavior>
    - NBA Defensive Rebounds -> defensiverebounds key; Offensive Rebounds -> offensiverebounds key (distinct, not total rebounds) -> ("api", 1.0) on exact name
    - NBA Blks+Stls -> blocks+steals; FG Made -> fieldGoals[0]; FG Attempted -> fieldGoals[1]; 3-PT Attempted -> threePoint[1] -> ("api", 0.8) derived
    - MLB Total Bases -> 1B+2*2B+3*3B+4*HR from hit-type counts; Singles -> hits-2B-3B-HR; Pitching Outs -> innings_to_outs (.1/.2); H+R+RBI -> hits+runs+rbis -> ("api", 0.8)
    - MLB Hitter Strikeouts -> batting namespace strikeouts; Pitcher Strikeouts / *Allowed -> pitching namespace (correct group)
    - NOT-DERIVABLE: Hitter/Pitcher Fantasy Score, NBA Fantasy Score/Dunks/Double-Double, "1st Inning Runs Allowed", "Points - 1st 3 Minutes", "Quarters with N+", "(Combo)" two-player -> (None, "manual", 0.0). NEVER substring-fall-through.
    - fuzzy name (name_match tiers 2-4) on a DIRECT/DERIVED stat -> ("api", 0.6)
    - unresolved / NOT-DERIVABLE -> (None, "manual", 0.0)
  </behavior>
  <action>
    Rewrite `stat_value_for_prop:4039-4067` to: (a) resolve the player via `key = name_match(str(player or ""), player_stats.keys()); row = player_stats.get(key) if key else None` (whether the exact tier fired determines confidence 1.0 vs 0.6 — capture which tier matched, e.g. by also calling exact membership directly or having name_match signal exactness); (b) canonicalize the Stat string (lowercase; collapse `+`/`_`/spaces consistently); (c) look the canonical Stat up in an explicit disposition map built from the spec's Component 3 table AND corrected per the 01-1 ledger RECLASSIFY flags — each entry is a DIRECT key, a DERIVED formula closure, or NOT-DERIVABLE. For MLB, select `row["batting"]` or `row["pitching"]` per the Stat's group tag (Hitter vs Pitcher / `*Allowed` = pitching). DERIVED MLB stats (Total Bases, Singles, H+R+RBI) read the plays/atBats hit-type counts from plan 01-2; Pitching Outs uses a mirrored `innings_to_outs` handling `.1/.2`. DELETE the `:4064-4066` substring loop entirely. Return `(value, source, confidence)` with the exact mapping: exact-name+DIRECT → ("api",1.0); DERIVED → ("api",0.8); fuzzy-name on DIRECT/DERIVED → ("api",0.6); NOT-DERIVABLE/unresolved → (None,"manual",0.0). Retain the existing PRA/Pts+Rebs/Pts+Asts/Rebs+Asts NBA combos. Write `scripts/test_stat_value_for_prop.py` (stdlib unittest) that drives `scripts/testdata/stat_corpus.json` against the 01-1 fixtures and asserts every Stat resolves to its enumerated disposition, with explicit regression cases for the prior false positives (Defensive vs Offensive Rebounds distinct, `1st Inning Runs Allowed` → None, `Points - 1st 3 Minutes` → None) and the derived MLB stats (Total Bases, Singles via plays, Pitching Outs `.1/.2`, H+R+RBI), and asserts each returned `(source, confidence)` tuple matches the table.
  </action>
  <verify>
    <automated>cd scripts && python3 test_stat_value_for_prop.py</automated>
  </verify>
  <done>`test_stat_value_for_prop.py` exits 0: every corpus Stat maps to exactly one enumerated disposition, the prior false positives now return None, derived MLB stats compute correctly, and (source, confidence) match the spec table. The substring fallback no longer exists.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Make grade_prop a 5-tuple, add provenance columns, thread source/confidence to every Results row</name>
  <read_first>
    - docs/superpowers/specs/2026-06-21-trustworthy-results-design.md (Component 8 — the full end-to-end contract (a)-(e) naming every touched line; the values summary)
    - scripts/sports_system_runner.py (grade_prop:4070-4090; result_record_from_source:4229-4273; RESULT_HEADERS:271-277; grade_game_in_workbook prop site :4613-4620, spread/total :4585-4590, VOID :4583/:4610, parlay :4651)
  </read_first>
  <files>scripts/sports_system_runner.py, scripts/test_provenance_plumbing.py</files>
  <behavior>
    - A normal API prop grade writes Result Source="api" with confidence 1.0 (exact+DIRECT) / 0.8 (derived) / 0.6 (fuzzy)
    - A spread, total, parlay, and VOID row each write Result Source="api", Result Confidence=1.0
    - A prop that resolves to MANUAL REVIEW (Layer-1 None, flag off) writes Result Source="manual", Result Confidence=0.0
    - No existing exact-match grade VERDICT changes — only the two additive columns populate
  </behavior>
  <action>
    Per Component 8: (a) `stat_value_for_prop` already returns `(value, source, confidence)` from Task 1. (b) Change `grade_prop:4070` to return a 5-tuple `(result, actual, note, source, confidence)`: unpack the 3-tuple at :4079, carry source/confidence through the WIN/LOSS/PUSH branches (:4082-4090), and return `("manual", 0.0)` on the PENDING/missing-line branches (:4072, :4078, :4081). (c) Append `"Result Source"` and `"Result Confidence"` to `RESULT_HEADERS` AFTER the `+ MARKET_CONTEXT_FIELDS` term (:277); add `record["Result Source"] = extra.get("Result Source")` and `record["Result Confidence"] = extra.get("Result Confidence")` to the dict in `result_record_from_source` (:4237-4270). (d) At the prop call site (:4613-4620): unpack the 5-tuple from `grade_prop`, and pass `"Result Source"`/`"Result Confidence"` through the existing `extra` dict at :4620; the MANUAL REVIEW escalation branch (:4614-4616) sets source="manual", confidence=0.0 (do NOT call Layer-2 here — that wiring lands in plan 01-5, behind the flag). (e) For the VOID branch (:4583/:4610) and the non-prop spread/total (:4585-4590) and parlay (:4651) rows, set `Result Source="api"`, `Result Confidence=1.0` explicitly in their extra dicts. Confirm migration is automatic (no manual column add) by relying on `result_headers`/`ensure_workbook`. Write `scripts/test_provenance_plumbing.py` (stdlib unittest) that runs an API prop grade and asserts `Result Source=api` with the correct confidence, and that a spread/total/parlay/VOID row writes `Result Source=api, 1.0`. (f) BEFORE finishing, `grep -rn "stat_value_for_prop\|grade_prop" scripts/test_*.py` and update every existing caller that unpacks a scalar or 3-tuple to the new 3-tuple / 5-tuple shapes respectively — the signature change is internal to grading but existing tests may call these directly, and the targeted `<verify>` here won't catch them (only phase-end full pytest would).
  </action>
  <verify>
    <automated>cd scripts && python3 test_provenance_plumbing.py</automated>
  </verify>
  <done>`test_provenance_plumbing.py` exits 0: api/scraped/manual sources and the 1.0/0.8/0.6/0.0 confidences land on the right Results rows; spread/total/parlay/VOID = api/1.0; no exact-match verdict changes. Any `test_*` caller of the old `stat_value_for_prop`/`grade_prop` signatures is updated to the new shapes.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| Stat string → disposition | A wrong substring match silently grades a real-money prop against an unrelated full-game stat |
| ESPN box value → grade verdict | A derived-formula error (e.g. Total Bases, Pitching Outs) mis-grades real money |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-04 | Tampering | substring fallback removal | mitigate | Disposition table is exhaustive; NOT-DERIVABLE returns None (→ MANUAL REVIEW), never a substring guess — proven by the `1st Inning Runs Allowed`→None regression |
| T-01-05 | Repudiation | provenance columns | mitigate | Every graded row records Result Source + Result Confidence so a verdict's basis is auditable |
| T-01-06 | Spoofing | exact-match verdict preservation | mitigate | Provenance is additive; the test asserts no exact-match verdict changes (Criterion #6) |
</threat_model>

<verification>
- `python3 test_stat_value_for_prop.py` and `python3 test_provenance_plumbing.py` exit 0 (run from `scripts/`).
- The `:4064-4066` substring loop is deleted (grep confirms it is gone).
- `RESULT_HEADERS` contains `"Result Source"` and `"Result Confidence"`; no manual workbook migration code is added (relies on `ensure_ws_columns`/`result_headers`).
- Re-run `test_name_match.py` and `test_espn_namespacing.py` from plan 01-2 to confirm no regression from the new caller wiring.
</verification>

<success_criteria>
- `stat_value_for_prop` is an explicit 3-tuple disposition table validated against the 01-1 fixtures; the substring fallback is gone.
- `grade_prop` is a 5-tuple; provenance columns exist and populate on every Results/Pick-History prop row, with spread/total/parlay/VOID = api/1.0.
- All four targeted tests pass; full pytest deferred to phase end (clean baseline "2 failed, 202 passed").
</success_criteria>

<output>
Create `.planning/phases/01-trustworthy-results/01-3-SUMMARY.md` when done. Note the final 5-tuple `grade_prop` signature and the `extra`-dict keys used for provenance — plan 01-4 (parlay/guard) and plan 01-5 (Layer-2 scraped re-grade) both build on this call-site shape.
</output>
