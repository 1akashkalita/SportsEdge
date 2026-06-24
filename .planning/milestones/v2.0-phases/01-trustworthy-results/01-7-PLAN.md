---
phase: 01-trustworthy-results
plan: 7
type: execute
wave: 1
depends_on: []
files_modified:
  - scripts/sports_system_runner.py
  - scripts/test_prop_pnl_slip_terms.py
autonomous: true
gap_closure: true
requirements: [BANKROLL-01, RESULTS-06]
must_haves:
  truths:
    - "A graded PROP row carries PnL = 0 in Results and Pick History, regardless of WIN/LOSS"
    - "A single-pick SPREAD/TOTAL row carries PnL = 0 (no standalone bankroll PnL)"
    - "The WIN/LOSS/PUSH/VOID Result on a prop row is unchanged — the accuracy signal is preserved"
    - "The bankroll balance is unaffected by prop-row PnL — it is sourced only from Slip History (D-09)"
  artifacts:
    - path: "scripts/sports_system_runner.py"
      provides: "grade_game_in_workbook writes pnl=0.0 for PROP and single-pick SPREAD/TOTAL rows"
      contains: "grade_game_in_workbook"
    - path: "scripts/test_prop_pnl_slip_terms.py"
      provides: "RED-first test proving prop/single-pick PnL is 0 while Result is unchanged"
  key_links:
    - from: "scripts/sports_system_runner.py grade_game_in_workbook"
      to: "Results sheet PnL column"
      via: "rec PnL field = 0.0 for prop/single-pick"
      pattern: "pnl = 0\\.0"
    - from: "sync_slip_bankroll"
      to: "Slip History Net PnL only (not prop rows)"
      via: "D-09 slips-only bankroll"
      pattern: "Net PnL"
---

<objective>
Sever standalone money PnL from individual prop and single-pick rows. A single DFS
prop cannot be staked on its own (DFS requires a multi-leg slip), so a per-prop
money PnL is conceptually wrong post-P3 (BANKROLL-01: props are accuracy-only,
bankroll is slips-only). Closes GAP 4 (the +0.909 / -1.0 per-prop PnL).

Purpose: Make the persisted ledger honest — Result carries the accuracy signal,
real money PnL is computed only by grade_slips at the Slip History level.
Output: PROP and single-pick SPREAD/TOTAL Results/Pick-History rows write PnL = 0;
the bankroll (already slips-only via D-09) is provably unaffected.
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
- scripts/sports_system_runner.py:5853-6063 — `grade_game_in_workbook`. Three loops:
  picks (spread/total/VOID) at :5881-5911, props at :5913-5972, parlays at :5974-6056.
  - Single-pick PnL is computed at :5900 / :5903 (`pnl = odds_profit(result, units, row.get("Odds"))`).
  - Prop PnL is computed at :5967 (`pnl = odds_profit(result, units, None)`).
  - The `pnl` value flows into `result_record_from_source(...)` then `upsert_result_row(...)`
    and into the appended `graded` dict (`"pnl": pnl`).
- scripts/sports_system_runner.py:4669-4674 — `pnl_for_result` (WIN→+0.909·units, LOSS→−units).
- scripts/sports_system_runner.py:4990-5001 — `odds_profit` (the function currently producing the per-prop money figure).
- scripts/sports_system_runner.py:5132-5231 — `sync_slip_bankroll`: bankroll is computed
  strictly from Slip History "Net PnL" (D-09). Confirm it does NOT read prop-row PnL.
- scripts/sports_system_runner.py:5103-5125 — the prop-day-pnl fallback in sync_master_and_bankroll
  (`prop_day_pnl` is summed from prop rows ONLY as a fallback when no slip row exists). Setting
  prop PnL to 0 must NOT silently zero a date's reporting where slips exist — confirm slip_day_pnl
  takes precedence (`day_pnl = slip_day_pnl if slip_day_pnl is not None else prop_day_pnl`).
</read_first>

<interfaces>
From scripts/sports_system_runner.py:
```python
def grade_game_in_workbook(sport, game, date=None, dry_run=False) -> dict[str, Any]: ...
def odds_profit(result: str, units: float, odds: Any = None) -> float: ...   # leave UNCHANGED — used by slips too
# Results row dict carries "PnL"; Pick History mirrors it.
```
The parlay loop (:5974-6056) DOES represent a staked unit and is NOT in scope —
parlays/slips keep their PnL. Only individual PROP rows and single-pick SPREAD/TOTAL
rows lose standalone money PnL.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: RED — prop / single-pick PnL = 0 while Result preserved</name>
  <files>scripts/test_prop_pnl_slip_terms.py</files>
  <behavior>
    - Build a minimal in-memory/temp workbook with one final game, one PROP row that
      grades WIN (actual > line, Over) and one PROP row that grades LOSS, plus one
      SPREAD single pick that grades WIN.
    - After `grade_game_in_workbook(..., dry_run=False)` (or dry_run with would_grade),
      assert the WIN prop row's Result == "WIN" AND its PnL == 0 (not 0.909).
    - Assert the LOSS prop row's Result == "LOSS" AND its PnL == 0 (not -1.0).
    - Assert the SPREAD single-pick row's Result is preserved AND PnL == 0.
    - Assert that a VOID/PENDING/MANUAL REVIEW prop row still has PnL == 0 (unchanged).
    - Money-safety guard: assert the parlay path is untouched — a parlay row that
      grades WIN keeps a non-prop-style PnL (do NOT zero parlays).
  </behavior>
  <action>
    Create `scripts/test_prop_pnl_slip_terms.py` as a stdlib `unittest.TestCase` loaded
    via importlib (mirror the pattern in test_backfill_regrade.py / test_provenance_plumbing.py).
    Use a tmp workbook seeded via `ensure_workbook` + direct sheet writes (reuse the fixture
    helpers already present in test_backfill_regrade.py for Props/Picks rows and a final game
    dict). Run the grader against a deterministic player_stats stub so the WIN/LOSS outcomes
    are fixed. This test MUST FAIL initially (current code writes ±0.909/−1.0 for props).
    Run from scripts/ with python3.
  </action>
  <verify>
    <automated>cd scripts && python3 -m pytest test_prop_pnl_slip_terms.py -x 2>&1 | tail -20  # MUST FAIL (RED)</automated>
  </verify>
  <done>test_prop_pnl_slip_terms.py exists, runs, and fails proving the current per-prop money PnL bug</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: GREEN — write PnL=0 for PROP and single-pick SPREAD/TOTAL rows (BANKROLL-01)</name>
  <files>scripts/sports_system_runner.py</files>
  <action>
    In `grade_game_in_workbook` (:5853-6063), set the per-row money PnL to 0 for the two
    single-pick lanes — implementing BANKROLL-01 (props accuracy-only, bankroll slips-only):
    1. PROP loop (:5913-5972): replace the prop PnL assignment at :5967
       (`pnl = odds_profit(result, units, None)`) with `pnl = 0.0`. The Result variable
       (WIN/LOSS/PUSH/VOID/MANUAL REVIEW) is unchanged — only money PnL is zeroed.
    2. SPREAD/TOTAL single-pick loop (:5881-5911): replace the `pnl = odds_profit(...)`
       assignments at :5900 and :5903 with `pnl = 0.0`. VOID already uses 0.0 (:5897) — leave it.
    3. Do NOT touch the PARLAY loop (:5974-6056) — parlays/slips are staked and keep their PnL.
    4. Do NOT modify `odds_profit` or `pnl_for_result` — those helpers are still used by the
       slip-grading path (grade_slips / calculate_slip_payout) where money IS realized.
    5. Confirm `sync_slip_bankroll` (:5132-5231) reads bankroll only from Slip History "Net PnL"
       (D-09) and that `day_pnl = slip_day_pnl if slip_day_pnl is not None else prop_day_pnl`
       (:5125) still falls back correctly — with prop PnL now 0, dates with NO slip rows will
       report a 0 prop_day_pnl, which is the intended slip-terms-only behavior (props carry
       accuracy via Result, not money). Add an inline comment citing BANKROLL-01 / D-09 at each edit.
    Additive/no-schema-change. Keep the daily run < 660s (this is a constant-time edit).
  </action>
  <verify>
    <automated>cd scripts && python3 -m pytest test_prop_pnl_slip_terms.py -x 2>&1 | tail -15  # MUST PASS (GREEN)</automated>
    <automated>cd scripts && grep -n "pnl = 0.0" sports_system_runner.py | grep -c "" ; grep -n "odds_profit(result, units, None)" sports_system_runner.py | grep -v '^#' | grep -c "odds_profit" </automated>
  </verify>
  <done>Prop rows and single-pick spread/total rows write PnL=0; Result preserved; odds_profit/pnl_for_result intact for slips; bankroll provably slips-only</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| grader → persisted ledger | grading writes money values that historically fed the bankroll |
| prop row PnL → bankroll | the coupling this gap severs (props must not move money) |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-G4-01 | Tampering | grade_game_in_workbook prop/single-pick PnL | mitigate | Zero only the prop + single-pick money PnL; Result untouched; parlay/slip PnL preserved (pinned by test asserting parlay non-zero) |
| T-01-G4-02 | Repudiation | sync_slip_bankroll | accept | Bankroll already sources from Slip History Net PnL only (D-09); confirmed by read, no code change needed |
| T-01-G4-SC | Tampering | npm/pip/cargo installs | mitigate | No package installs in this plan; nothing to verify |
</threat_model>

<verification>
- `python3 -m pytest test_prop_pnl_slip_terms.py -x` passes.
- `grep` confirms `odds_profit(result, units, None)` is gone from the prop lane.
- Spot-check: `sync_slip_bankroll` still references "Net PnL" from Slip History (D-09 intact).
</verification>

<success_criteria>
- PROP and single-pick SPREAD/TOTAL Results/Pick-History rows write PnL = 0.
- WIN/LOSS/PUSH/VOID Result on prop rows is unchanged (accuracy signal preserved).
- Parlay/slip PnL untouched; `odds_profit`/`pnl_for_result` unchanged.
- Bankroll computation provably unaffected (sourced from Slip History only).
</success_criteria>

<output>
Create `.planning/phases/01-trustworthy-results/01-7-SUMMARY.md` when done
</output>
