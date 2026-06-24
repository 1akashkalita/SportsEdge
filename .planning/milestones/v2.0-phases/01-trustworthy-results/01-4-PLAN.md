---
phase: 01-trustworthy-results
plan: 4
type: execute
wave: 4
depends_on: ["01-3"]
files_modified:
  - scripts/sports_system_runner.py
  - scripts/test_backfill_regrade.py
  - scripts/test_parlay_leg_backfill.py
  - scripts/test_side_parser.py
autonomous: true
requirements: [RESULTS-06]
must_haves:
  truths:
    - "Re-grading a date overwrites MANUAL REVIEW / PENDING Results rows in place with terminal grades, with no duplicate Results or Pick History rows per ref"
    - "Settled rows (WIN/LOSS/PUSH/VOID, in any casing or whitespace variant) are skipped on re-grade, never flipped"
    - "A parlay is graded against its FULL persisted leg set (this-run graded merged with persisted terminal legs); it abstains if any leg is non-terminal"
    - "Bet side is re-parsed from the PROP:<Player> <Stat> <Line> ref with multi-word stats handled, abstaining to MANUAL REVIEW on ambiguity"
    - "The double sync_master_and_bankroll call does not double-count"
  artifacts:
    - path: "scripts/sports_system_runner.py"
      provides: "existing_result_map + TERMINAL_RESULTS value-aware guard; parlay full-leg-set merge; side re-parser"
      contains: "TERMINAL_RESULTS"
    - path: "scripts/test_backfill_regrade.py"
      provides: "Backfill regression: overwrite MANUAL REVIEW, skip casing-variant terminals, no dup rows, no double-count"
      contains: "MANUAL REVIEW"
    - path: "scripts/test_parlay_leg_backfill.py"
      provides: "Money-safety: parlay resolves from full persisted leg set, abstains on incomplete legs"
      contains: "abstain"
    - path: "scripts/test_side_parser.py"
      provides: "Side parser handles multi-word stats and abstains on unrecoverable side"
      contains: "Hits Allowed"
  key_links:
    - from: "grade_game_in_workbook three loop guards"
      to: "existing_result_map + TERMINAL_RESULTS"
      via: "(already.get(ref) or '').strip().upper() in TERMINAL_RESULTS"
      pattern: "TERMINAL_RESULTS"
    - from: "parlay verdict"
      to: "persisted terminal legs (Results sheet)"
      via: "merge this-run graded with existing_result_map leg results; abstain if incomplete"
      pattern: "leg"
---

<objective>
Evolve the value-blind `if ref in already: continue` guard (commit aa69c3b) into a value-aware, normalization-robust TERMINAL_RESULTS guard so backfill re-grades MANUAL REVIEW / PENDING rows in place while leaving settled rows untouched; fix the parlay aggregation so a real-money parlay is never graded against a partial leg set; and re-parse the bet side from the `PROP:` ref (abstaining on ambiguity) — all RESULTS-06. This is the money-safety layer of the backfill: the looser guard from Change 1 would, without Change 2, activate a parlay mis-grade.

Purpose: The read-side guard at `:4560` is value-blind — a MANUAL REVIEW / PENDING ref counts as "present" so the three loops silently skip re-grade even when reconciliation forces `should_grade=True`. Naively reverting the guard re-grades settled bets; the spec requires EVOLVING it, plus sourcing parlay legs from persisted Results, plus recovering the (null) side from the Pick Ref string.

Output: `existing_result_map` + `TERMINAL_RESULTS` constant + the three evolved loop guards, the parlay full-leg-set merge with abstain, the multi-word-aware side re-parser, and three offline tests.
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
@.planning/phases/01-trustworthy-results/01-3-SUMMARY.md

<interfaces>
<!-- Exact current shapes to evolve. From sports_system_runner.py: -->

existing_result_refs(results_ws, date, sport_label) -> set[str]   at :4430-4436
  Reads Date/Sport/Pick Ref columns via result_headers. MIRROR this to add:
  existing_result_map(results_ws, date, sport_label) -> dict[str, str]  returning {ref: current_result_str}
  (ALSO read the "Result" column via result_headers).

grade_game_in_workbook  at :4548
  :4560  already = existing_result_refs(...)          -> REPLACE with existing_result_map(...)
  Three loop guards (spread/total :4580, prop :4607, parlay :4632):  if ref in already: continue
    -> CHANGE to:  if (already.get(ref) or "").strip().upper() in TERMINAL_RESULTS: continue
  Parlay verdict block :4638-4648 currently aggregates legs ONLY from this-run `graded`
    (leg_results = [g["result"] for g in graded if g["result"] in {WIN,LOSS,PUSH}]).
  Prop ref format :4606 = f"PROP:{row.get('Player Name')} {row.get('Stat')} {row.get('Line')}".
  side derivation grade_prop:4076 = from row.get("Opponent/Description") (NULL on the 86 MANUAL REVIEW rows).

upsert_result_row:4439  in-place upsert keyed on Date[:10]+Sport+Pick Ref (no dup Results row).
sync_master_and_bankroll:4465  calls remove_master_pick_history_ref:4456 per newly-graded ref BEFORE ph.append
  (replace-by-ref, no dup Pick History row); units/pnl already exclude PENDING/MANUAL REVIEW at :4501-4502.
  Double-sync: grade_game_in_workbook calls it at :4659 with `graded`; check_results:4775 calls it again with []
  (the empty call only rebuilds Daily Log / Bankroll from existing Pick History — must not double-count).
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Value-aware TERMINAL_RESULTS guard + parlay full-leg-set money-safety fix</name>
  <read_first>
    - docs/superpowers/specs/2026-06-21-trustworthy-results-design.md (Backfill overwrite mechanism — Change 1 and Change 2; the double-sync idempotency note; Testing strategy #8 and #9)
    - .planning/phases/01-trustworthy-results/01-3-SUMMARY.md (the grade_prop 5-tuple shape + extra-dict provenance keys)
    - scripts/sports_system_runner.py (existing_result_refs:4430; grade_game_in_workbook:4548 — guard :4560, three loop guards :4580/:4607/:4632, parlay block :4638-4648; upsert_result_row:4439; sync_master_and_bankroll:4465)
  </read_first>
  <files>scripts/sports_system_runner.py, scripts/test_backfill_regrade.py, scripts/test_parlay_leg_backfill.py</files>
  <behavior>
    - Seed a MANUAL REVIEW prop row + a valid stat line -> re-grade overwrites it to terminal in place (Results count per ref stays 1; Pick History exactly 1 row per ref)
    - Seed stored-Result casing variants "Win", "push ", " VOID" -> all SKIPPED (not re-graded, not flipped)
    - Seed two terminal prop legs (1 WIN, 1 LOSS) + a MANUAL REVIEW parlay over both -> parlay resolves to LOSS from the FULL persisted leg set (not WIN/PENDING)
    - A parlay with one still-missing/non-terminal leg -> ABSTAINS (stays at prior result, skipped)
    - The second sync_master_and_bankroll(date, []) does not double-count
  </behavior>
  <action>
    Add `def existing_result_map(results_ws, date, sport_label) -> dict[str, str]` mirroring `existing_result_refs:4430-4436` but returning `{ref: current_result_str}` (also reading the `Result` column via `result_headers`). Add a module constant `TERMINAL_RESULTS = {"WIN", "LOSS", "PUSH", "VOID"}`. Replace `:4560` `already = existing_result_refs(...)` with `already = existing_result_map(...)`, and change ALL THREE loop guards (:4580, :4607, :4632) from `if ref in already: continue` to `if (already.get(ref) or "").strip().upper() in TERMINAL_RESULTS: continue` — the `.strip().upper()` makes it robust to legacy casing/whitespace; an empty/blank stored Result is intentionally NON-terminal → re-gradeable. NEVER revert the guard to the original commit-aa69c3b form. For the parlay block (:4638), before computing the verdict, assemble the FULL leg-result set for that game/date by merging (a) this-run `graded` legs with (b) the persisted terminal leg results read from `existing_result_map` (Results sheet). If any constituent leg is still non-terminal/absent after the merge, the parlay ABSTAINS (stays at its prior result / is skipped) rather than grading against an incomplete set. Preserve `upsert_result_row` and `sync_master_and_bankroll`'s replace-by-ref idempotency (no code change needed there — confirm with a test). Write `scripts/test_backfill_regrade.py` (Testing strategy #8): seed Results rows (one MANUAL REVIEW prop, one WIN prop, casing variants "Win"/"push "/" VOID"); run `grade_game_in_workbook` with a final game + valid stat line; assert the MANUAL REVIEW row overwrites to terminal, the casing-variant terminals are skipped, Results count per ref stays 1, master Pick History has exactly one row per ref, and a second `sync_master_and_bankroll(date, [])` does not double-count. Write `scripts/test_parlay_leg_backfill.py` (Testing strategy #9): seed two terminal prop legs (1 WIN, 1 LOSS) + a MANUAL REVIEW parlay over both; re-grade and assert the parlay resolves to LOSS from the full persisted set; then assert a parlay with one still-missing leg abstains (stays prior).
  </action>
  <verify>
    <automated>cd scripts && python3 test_backfill_regrade.py && python3 test_parlay_leg_backfill.py</automated>
  </verify>
  <done>Both tests exit 0: value-aware guard re-grades MANUAL REVIEW/PENDING and skips settled rows (any casing) with no dup rows and no double-count; parlay grades from the full persisted leg set and abstains on incomplete legs. The guard is EVOLVED, never reverted.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Multi-word-aware side re-parser from the PROP: ref, abstaining on ambiguity</name>
  <read_first>
    - docs/superpowers/specs/2026-06-21-trustworthy-results-design.md (Side recovery for backfill — multi-word stats, abstain-to-MANUAL-REVIEW policy; Testing strategy #10)
    - scripts/sports_system_runner.py (grade_prop:4076 side derivation; the prop ref format at :4606)
  </read_first>
  <files>scripts/sports_system_runner.py, scripts/test_side_parser.py</files>
  <behavior>
    - "PROP:Player Name Hits Allowed 5.5" -> stat="Hits Allowed", line=5.5 (multi-word stat, not mis-segmented)
    - "PROP:Player Total Bases 1.5" -> stat="Total Bases", line=1.5
    - "PROP:Player Pitcher Strikeouts 6.5" -> stat="Pitcher Strikeouts", line=6.5
    - When the ref/row does not unambiguously encode Over/Under -> side unrecoverable -> row ABSTAINS to MANUAL REVIEW (no confidently-wrong terminal grade)
  </behavior>
  <action>
    Add a helper that, for backfill rows whose structured `Player/Stat/Line/Side` columns and `Opponent/Description` are null, re-parses `Player`, `Stat`, and `Line` from the `PROP:<Player> <Stat> <Line>` Pick Ref string. The parser MUST handle multi-word stats (`Hits Allowed`, `Total Bases`, `Pitcher Strikeouts`) — a naive split-on-space mis-segments stat vs line; segment by locating the trailing numeric line token and matching the stat against the known disposition-table Stat strings (from plan 01-3) rather than blind whitespace splitting. Wire this into the prop grading path so the re-parsed Stat/Line feed `stat_value_for_prop`. Because the Pick Ref alone may not encode Over/Under, if the side cannot be unambiguously recovered (no side in ref and no other side signal on the row), the row ABSTAINS to MANUAL REVIEW (consistent with `name_match`'s abstain policy) rather than producing a confidently-wrong terminal grade — strictly safer than the current MANUAL REVIEW state. Write `scripts/test_side_parser.py` (Testing strategy #10) covering the three multi-word `PROP:` formats above for correct stat/line segmentation and asserting abstain-to-MANUAL-REVIEW when side is unrecoverable.
  </action>
  <verify>
    <automated>cd scripts && python3 test_side_parser.py</automated>
  </verify>
  <done>`test_side_parser.py` exits 0: multi-word stats segment correctly (Hits Allowed / Total Bases / Pitcher Strikeouts), and an unrecoverable side abstains to MANUAL REVIEW instead of guessing.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| stored Results Result string → re-grade decision | A casing/whitespace variant could let a settled real-money bet be re-graded and flipped |
| this-run graded legs → parlay verdict | Aggregating a real-money parlay against a partial leg set can flip a true LOSS to WIN |
| PROP: ref string → bet side | A wrong side parse produces a confidently-wrong terminal grade on real money |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-07 | Tampering | TERMINAL_RESULTS guard | mitigate | `.strip().upper()` normalization means a settled bet in any casing is never re-graded; VOID is terminal (permanent) — pinned by the casing-variant test |
| T-01-08 | Elevation of Privilege | parlay partial-leg aggregation | mitigate | Parlay verdict uses the FULL persisted leg set and ABSTAINS on any non-terminal leg — money-safety pinned by the parlay-leg test |
| T-01-09 | Spoofing | side re-parser | mitigate | Ambiguous side abstains to MANUAL REVIEW; never guesses Over/Under on real money |
| T-01-10 | Repudiation | double-sync double-count | mitigate | Replace-by-ref + empty-call rebuild-only is pinned by a regression test so a future signature edit can't silently double-count |
</threat_model>

<verification>
- `python3 test_backfill_regrade.py`, `python3 test_parlay_leg_backfill.py`, `python3 test_side_parser.py` all exit 0 (run from `scripts/`).
- The guard at `:4560` and the three loop guards use `existing_result_map` + `TERMINAL_RESULTS`; the original `if ref in already: continue` form is gone (grep confirms).
- Re-run plan 01-3's tests to confirm the new guard/parlay wiring did not regress provenance or disposition behavior.
- No gate logic or pick-generation change; only the grading/reconciliation path is touched.
</verification>

<success_criteria>
- Value-aware, normalization-robust guard re-grades MANUAL REVIEW/PENDING and skips settled rows; no duplicate Results/Pick-History rows; no double-count.
- Parlay grades from the full persisted leg set and abstains on incomplete legs (money-safe).
- Side re-parser handles multi-word stats and abstains on ambiguity.
- All three targeted tests pass; full pytest deferred to phase end.
</success_criteria>

<output>
Create `.planning/phases/01-trustworthy-results/01-4-SUMMARY.md` when done. Confirm the guard was EVOLVED (not reverted) and document the parlay merge approach — plan 01-6's backfill execution relies on this reconciliation path.
</output>
