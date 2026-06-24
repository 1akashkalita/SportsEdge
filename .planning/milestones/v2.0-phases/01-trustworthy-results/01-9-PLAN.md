---
phase: 01-trustworthy-results
plan: 9
type: execute
wave: 2
depends_on: [01-7]
files_modified:
  - scripts/verify_results.py
  - scripts/sports_system_runner.py
  - scripts/test_dnp_void.py
autonomous: true
gap_closure: true
requirements: [RESULTS-05, RESULTS-06]
must_haves:
  truths:
    - "When stat_value_for_prop returns None AND the player confirmably did NOT play (DNP / not in box score / scratched), the prop grades VOID (no action), not MANUAL REVIEW and never auto-LOSS"
    - "When appearance cannot be determined, the prop stays MANUAL REVIEW (abstain — no guess)"
    - "A player who DID play but lacks the specific stat stays MANUAL REVIEW (not VOID — they appeared)"
    - "DNP detection runs in the Layer-2 fallback lane (firecrawl) and degrades safely (never crashes, stays within the 660s budget)"
  artifacts:
    - path: "scripts/verify_results.py"
      provides: "appearance/DNP detection from the scraped box score (player present-in-box vs absent)"
      contains: "def "
    - path: "scripts/sports_system_runner.py"
      provides: "resolve_missing_stat + grade_game_in_workbook MANUAL REVIEW branch grade VOID on confirmed DNP, abstain otherwise"
      contains: "resolve_missing_stat"
    - path: "scripts/test_dnp_void.py"
      provides: "RED-first tests: DNP→VOID, played-but-missing→MANUAL REVIEW, undetermined→MANUAL REVIEW, never auto-LOSS"
  key_links:
    - from: "scripts/sports_system_runner.py grade_game_in_workbook MANUAL REVIEW branch"
      to: "resolve_missing_stat appearance check"
      via: "DNP → result=VOID, source=scraped, conf=1.0"
      pattern: "VOID"
    - from: "scripts/verify_results.py"
      to: "scraped box-score player roster"
      via: "player-present-in-box test"
      pattern: "players"
---

<objective>
Auto-detect did-not-play props and grade them VOID instead of parking them in
MANUAL REVIEW. When Layer-1 (`stat_value_for_prop`) returns None ("no final stat
line found"), confirm whether the player actually appeared in the game; if the player
did NOT play (DNP / not in box score / scratched) → grade VOID (no action). If
appearance cannot be determined → stay MANUAL REVIEW (abstain, no guess). Never auto-LOSS.
Closes GAP 1.

Real-money proof points (manually resolved this session, must now auto-resolve):
Nick Martinez & Masataka Yoshida (June 8, both played June 9), Shohei Ohtani (June 12),
Zack Gelof (June 20) — all DNP, all should be VOID.

Purpose: A DNP is a refund (VOID), not an unresolved review item and not a loss.
Output: DNP→VOID auto-detection in the Layer-2 fallback lane, money-safe (abstain on
ambiguity), with provenance.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/PROJECT.md
@.planning/ROADMAP.md
@.planning/STATE.md
@.planning/phases/01-trustworthy-results/01-UAT.md

<read_first>
- scripts/sports_system_runner.py:5913-5972 — the prop loop's MANUAL REVIEW branch.
  - :5931-5933 — `if result == "PENDING" and "No final stat line" in note: result = "MANUAL REVIEW"`.
  - :5937-5964 — the Layer-2 firecrawl gate (`ENABLE_FIRECRAWL_RESULT_FALLBACK` + budget),
    calling `resolve_missing_stat(...)`; on `scraped` value it re-grades inline.
  - :5965-5966 — if still MANUAL REVIEW, appended to manual_reviews.
- scripts/sports_system_runner.py:5711-5852 — `resolve_missing_stat(sport, game, player, stat)`.
  Currently returns `(value|None, source, confidence)`. It already scrapes the box via
  verify_results.py, reads `JSON_RESULT={"status":..,"players":{...}}`, resolves the player via
  `name_match`, and resolves the stat via `stat_value_for_prop`. The player-resolution step is
  exactly where "player present in box?" is knowable.
- scripts/verify_results.py:354+ — `parse_espn_box_markdown(md_text)` returns
  `{player_name: {batting/pitching|flat stats}}`. A player ABSENT from this dict (when the
  scrape status is "ok", i.e. the box was successfully read) is the DNP signal. A "skip"
  status (scrape could not run) is NOT a DNP signal — abstain.
- scripts/verify_results.py:60-134 — name canonicalization + the `players` envelope contract:
  `status="ok"` with player absent = legitimate "not in box"; `status="skip"` = transient.
- scripts/sports_system_runner.py:4990-5001 — `odds_profit`: VOID → 0.0 PnL (correct, no action).
- 01-5-SUMMARY.md — resolve_missing_stat contract, cache rules (status=ok cached incl. absent
  player; status=skip NOT cached), provenance (scraped/0.5), degrade-never-crash.
</read_first>

<interfaces>
DNP detection extends the Layer-2 lane with a tri-state appearance result. Proposed contract
(implementer may choose helper placement, but the semantics are fixed):
```python
# In verify_results.py — appearance tri-state from a successfully-read box:
#   "played"   → player present in scraped players dict (has a row)
#   "dnp"      → player absent AND scrape status == "ok" (box fully read; player not listed)
#   "unknown"  → scrape status == "skip"/error, or name match ambiguous → ABSTAIN
def player_appearance(players: dict, player: str, status: str) -> str: ...  # "played"|"dnp"|"unknown"

# In sports_system_runner.py — resolve_missing_stat may surface the appearance signal so the
# caller can grade VOID on "dnp", abstain on "unknown". Keep the existing 3-tuple return for
# stat resolution; add a way to learn appearance (e.g. a 4th return slot or a sibling helper
# resolve_player_appearance(sport, game, player) -> "played"|"dnp"|"unknown").
```
Money-safety: VOID requires a CONFIRMED dnp (status=ok + absent + unambiguous name).
Everything else (played-but-stat-missing, status=skip, ambiguous name) → MANUAL REVIEW.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: RED — DNP→VOID, played-but-missing→MANUAL REVIEW, undetermined→MANUAL REVIEW (never auto-LOSS)</name>
  <files>scripts/test_dnp_void.py</files>
  <behavior>
    - verify_results.player_appearance: player present in box → "played"; player absent
      with status="ok" → "dnp"; status="skip" → "unknown"; ambiguous/empty name → "unknown".
    - resolve_missing_stat / appearance path: a confirmed DNP (status=ok, player absent)
      surfaces "dnp"; a played player with a non-derivable stat surfaces "played".
    - grade_game_in_workbook MANUAL REVIEW branch (simulated with a stubbed appearance
      resolver): when Layer-1 returns None AND appearance == "dnp" → Result == "VOID",
      PnL == 0, Result Source == "scraped", Result Confidence == 1.0.
    - When appearance == "played" but stat unresolved → Result stays "MANUAL REVIEW".
    - When appearance == "unknown" → Result stays "MANUAL REVIEW" (abstain, no guess).
    - Hard money-safety: assert a DNP prop is NEVER graded LOSS (or WIN) — only VOID or
      MANUAL REVIEW are acceptable terminals for the "no stat line" path.
    - Use the espn_box_ok.md fixture for a present player and a synthesized "absent player"
      case so the test is offline.
  </behavior>
  <action>
    Create `scripts/test_dnp_void.py` (stdlib unittest, importlib-loaded). Reuse
    `scripts/testdata/firecrawl/espn_box_ok.md` and `verify_skip.json` (the skip envelope)
    from plan 01-5. Stub the subprocess/scrape so no network is required (mirror
    test_scraped_fallback.py's monkeypatch of `_subprocess_run_with_retry` / cache fixture
    pattern). This test MUST FAIL initially. Run from scripts/ with python3.
  </action>
  <verify>
    <automated>cd scripts && python3 -m pytest test_dnp_void.py -x 2>&1 | tail -20  # MUST FAIL (RED)</automated>
  </verify>
  <done>test_dnp_void.py exists and fails, pinning DNP→VOID, played→MANUAL REVIEW, unknown→MANUAL REVIEW, and never-auto-LOSS</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: GREEN — appearance detection in verify_results + DNP→VOID wiring in the Layer-2 lane</name>
  <files>scripts/verify_results.py, scripts/sports_system_runner.py</files>
  <action>
    1. verify_results.py: add `player_appearance(players, player, status)` returning
       "played" | "dnp" | "unknown" per the interface. Use the same `_canonical_name` matching
       the parser already uses so name formats reconcile. "dnp" requires status == "ok" AND the
       player is unambiguously absent; ambiguity or status != "ok" → "unknown".
    2. sports_system_runner.py: expose the appearance signal to the grader. Either extend
       `resolve_missing_stat` to also return the appearance verdict, or add a sibling
       `resolve_player_appearance(sport, game, player) -> "played"|"dnp"|"unknown"` that reuses
       the SAME scrape + cache path (do NOT add a second scrape — reuse the per-event cache from
       01-5 so the budget is unchanged). Route through `_subprocess_run_with_retry`; degrade to
       "unknown" on any failure/timeout/missing-binary/offline/429 (RESULTS-05 contract).
    3. grade_game_in_workbook MANUAL REVIEW branch (:5931-5966): after Layer-1 yields None and
       BEFORE/within the existing firecrawl block, when the scraped stat is still unresolved,
       consult the appearance verdict:
          - "dnp"     → result = "VOID", actual = None, note = "... DNP — no action (refunded)",
                        res_src = "scraped", res_conf = 1.0, pnl = 0.0. Do NOT append to manual_reviews.
          - "played"  → stays MANUAL REVIEW (the player appeared; stat genuinely not derivable).
          - "unknown" → stays MANUAL REVIEW (abstain).
       This must sit inside the flag/budget gate (only when ENABLE_FIRECRAWL_RESULT_FALLBACK is on
       and budget remains) so behavior with the flag OFF is unchanged (stays MANUAL REVIEW —
       Layer-1-only milestone state preserved). NEVER produce LOSS/WIN from the no-stat-line path.
    4. Keep additive schema; keep daily run < 660s (DNP check reuses the existing scrape/cache —
       no extra subprocess budget). Add inline comments citing GAP 1 / RESULTS-05.
    Run from scripts/ with python3.
  </action>
  <verify>
    <automated>cd scripts && python3 -m pytest test_dnp_void.py -x 2>&1 | tail -15  # MUST PASS (GREEN)</automated>
    <automated>cd scripts && python3 -m pytest test_scraped_fallback.py test_verify_results_parser.py -x 2>&1 | tail -8  # 01-5 tests still green (no regression)</automated>
    <automated>cd scripts && grep -n "player_appearance\|VOID" verify_results.py sports_system_runner.py | grep -i "appear\|dnp" | head</automated>
  </verify>
  <done>Confirmed DNP grades VOID (scraped/1.0, PnL 0); played→MANUAL REVIEW; unknown→MANUAL REVIEW; never auto-LOSS; flag-OFF behavior unchanged; 01-5 tests still pass; budget unchanged</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| scraped box → grade verdict | a scrape result decides a real-money VOID — must be confirmed, not inferred |
| absent player → DNP | only valid when the box was fully read (status=ok); a transient skip must not VOID |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-G1-01 | Tampering | DNP→VOID decision | mitigate | VOID requires status=ok + unambiguous absence; status=skip/ambiguous → MANUAL REVIEW (abstain); pinned by RED test |
| T-01-G1-02 | Elevation | no-stat-line path → LOSS | mitigate | Test asserts the path can only produce VOID or MANUAL REVIEW, never auto-LOSS/WIN |
| T-01-G1-03 | DoS | extra scrape for appearance | mitigate | Reuse the 01-5 per-event cache + budget; no second subprocess; routed through _subprocess_run_with_retry (SIGALRM) |
| T-01-G1-SC | Tampering | firecrawl-cli@1.19.2 (existing) | accept | No new package; pin + legitimacy already established in 01-5 (T-01-SC) |
</threat_model>

<verification>
- `python3 -m pytest test_dnp_void.py -x` passes.
- `python3 -m pytest test_scraped_fallback.py test_verify_results_parser.py -x` still pass (01-5 not regressed).
- Flag OFF → behavior unchanged (rows stay MANUAL REVIEW); flag ON + confirmed DNP → VOID.
</verification>

<success_criteria>
- Confirmed DNP props grade VOID (no action), with scraped/1.0 provenance and PnL 0.
- Played-but-missing and undetermined props stay MANUAL REVIEW (abstain, no guess).
- The no-stat-line path never produces an auto-LOSS.
- Layer-2 budget and degrade-never-crash contract preserved; daily run < 660s.
</success_criteria>

<output>
Create `.planning/phases/01-trustworthy-results/01-9-SUMMARY.md` when done
</output>
