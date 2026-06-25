---
slug: grading-pipeline-dormant
status: resolved
resolution_commit: aa69c3b
resolution_verified_by: orchestrator (Opus) — smoke test + 43 targeted tests + idempotency trace
trigger: "Model appears stagnant / bankroll frozen. Root question was 'is the model improving or stagnant'; investigation found the real blocker is that the grading+reconciliation pipeline is dormant — MLB picks generate daily but never grade, slips never record, bankroll frozen since ~June 10 2026."
created: 2026-06-21
updated: 2026-06-22
goal: find_and_fix
---

# Debug Session: grading-pipeline-dormant

## Symptoms

- **Expected:** Each day's generated picks get graded after games go final; Results sheet + Slip History + master_pnl Pick History fill; bankroll moves daily.
- **Actual:** Picks generate but never grade. Bankroll frozen at exactly 76.051 / ROI -15.65% every day 2026-06-10 → 2026-06-21. Slip History sheet empty everywhere.
- **Errors:** `game_completion_monitor checked_games=0 graded_games=0` in run_log; two `TIMEOUT exceeded 660s` on game_completion_monitor (2026-06-22 01:31/01:46 UTC); leftover aborted-save temp file `data/mlb/mlb_2026-06-21.xlsx.tmp.48351.xlsx`; stale lock `pid=48351 task=mlb_prop_monitor`.
- **Timeline:** Real grading last produced rows ~June 8–11. Worked before that (June 8 slate graded 230 picks). Recent run_log is dominated by offline Stability-Hardening fault-injection tests (every external host → NameResolutionError).
- **Reproduction:** Run `cd scripts && python3 sports_system_runner.py --task check_results` (or `game_completion_monitor`); observe checked_games=0 / no Results rows written for days that have completed games.

## Evidence (gathered by orchestrator before delegation)

- timestamp 2026-06-21: master_pnl.xlsx "Bankroll Chart Data" identical 76.051 / -15.65% for 12 consecutive days (June 10-21). "Daily Log" rows June 16-21 all 0W/0L/0 units, note "live game grading/reconciliation".
- timestamp 2026-06-21: Pick History = 233 rows; 230 dated 2026-06-08, only 3 after; newest "Graded At" ≈ June 11. Cumulative graded PnL = -23.949 == bankroll.json overall_profit_loss exactly (bankroll never updated since June 8 batch).
- timestamp 2026-06-21: master Pick History result distribution = {WIN 63, LOSS 80, MANUAL REVIEW 86, PENDING 4}. 37% MANUAL REVIEW = "No final stat line found" (ESPN box-score name matching).
- timestamp 2026-06-21: MLB workbooks June 15-21 each have Picks:4 but Results:0 and Slip History:0. NBA workbooks June 14-21 have Picks:0 (season over).
- timestamp 2026-06-21: Slip History sheet empty (header only) in master_pnl AND in every per-day workbook → slip recording never succeeded.
- timestamp 2026-06-21: game_status_cache.json has 185 games, 146 status=final with graded=true, 38 scheduled, 1 void. So games DO reach final and get flagged graded:true, yet no corresponding Results/Slip/PickHistory rows for the recent picks.
- timestamp 2026-06-21: bankroll.json: last_results_check=2026-06-08 (13 days stale) while updated_at=2026-06-21T08:00; last_update_timestamp=2024-06-07 (frozen junk field).

## Current Focus

status: fix_and_fix — applying fix for confirmed root causes

reasoning_checkpoint:
  hypothesis: "game_matches_row() never matches Props sheet rows because (A) Picks sheet 'Home Team' contains a composite matchup string ('BAL @ LAD') with Away Team=None making the home/away branch always-False, and (B) Props sheet 'Team' field is a UUID string (e.g., '5a5a4e8a-...') since Underdog API changed its team field from abbreviation to team_id; team_aliases(uuid) never matches any real team; text fallback has no team names in the row text. Additionally, game_completion_monitor marks state['graded']=True even when grade_game_in_workbook returns 0 graded rows, poisoning all future reconciliation attempts."
  confirming_evidence:
    - "June 8 workbook Props Team='LAA' (abbreviation, grading worked). June 21 workbook Props Team='5a5a4e8a-d364-4fba-9b76-add9ed5d9ad7' (UUID, grading fails)."
    - "game_status_cache: all 146 final games have graded=True yet Results/Slip sheets empty for June 15-21."
    - "run_log: checked_games=15, graded_games=0 for 50+ consecutive monitor runs on June 21."
    - "Picks sheet row: Away Team=None, Home Team='BAL @ LAD' — game_matches_row branch (line 4364) evaluates team_aliases(None) & anything = set() (falsy) → returns False."
    - "Props sheet row: Team='5a5a4e8a-...' (UUID) → team_aliases returns {uuid, uuid.lower()} → never matches 'Los Angeles Dodgers' → text fallback has no team name in row → returns False."
  falsification_test: "If team alias fix is wrong, dry-run grade_game_in_workbook on mlb_2026-06-21.xlsx with a known-final game using fixed game_matches_row would still return graded=[]."
  fix_rationale: "Fix game_matches_row to handle composite Home Team strings (split on '@') and UUID Team fields (skip alias check, use start-time window). Fix game_completion_monitor to not mark graded=True unless actual rows were written. These directly address both failure modes."
  blind_spots: "ESPN event_id in the game dict vs Game ID in workbook (DFS platform match_id) — these are different ID spaces; Game ID match in game_matches_row will never fire for these rows regardless."

next_action: apply fixes to sports_system_runner.py

## Key code locations

- `scripts/sports_system_runner.py:4647` game_completion_monitor (iterates espn_scoreboard_games_for_date per sport for `date`; skips games already graded:true unless reconciliation=True)
- `scripts/sports_system_runner.py:4731` check_results (1am reconciliation; date=today_str(); calls sync_master_and_bankroll)
- `grade_game_in_workbook` (matches games→picks; produces MANUAL REVIEW when ESPN stat line not found)
- `scripts/slip_payouts.py:187` ensure_slip_history_sheet, `:200` slip_history_row; runner usage at `sports_system_runner.py:3142`
- `espn_scoreboard_games_for_date` (source of games; returns [] offline)

## Constraints (HARD — real-money system)

- Minimal-invasive: stability/defect fixes only, no broad restructuring.
- MUST NOT change gate logic, pick outputs, or workbook schema.
- Runner must be invoked from `scripts/` with `python3` (3.14). Tests are unittest, run from `scripts/`.
- Cron hard-kill ceiling currently 720s; task budgets 660s — fixes must stay under the active ceiling.

## Eliminated

- hypothesis: H1 (offline / network) — eliminated; run_log shows checked_games=15 for ~100 runs on June 21; ESPN scoreboard was reachable during overnight cron window
  evidence: run_log June 21 07:00-09:55 UTC shows checked_games=15 graded_games=0 in every run
  timestamp: 2026-06-21

- hypothesis: H2 (date boundary / yesterday's games missed at 1am) — partially correct but secondary; the primary failure was that games were checked but graded_games=0 even when games were visible; the 1am checked_games=0 is a downstream symptom (all games pre-marked graded=True before results were written)
  evidence: overnight runs had 15 games checked, still 0 graded; 1am run was after cache poisoning
  timestamp: 2026-06-21

## Evidence

- timestamp: 2026-06-21
  checked: game_status_cache.json
  found: ALL 146 final games have graded=True, 0 results rows in workbooks for June 15-21
  implication: cache was poisoned — graded=True was set prematurely before any rows were written

- timestamp: 2026-06-21
  checked: mlb_2026-06-21.xlsx Props sheet Team field
  found: Team = UUID (e.g., '5a5a4e8a-d364-4fba-9b76-add9ed5d9ad7'), June 8 had Team = 'LAA' (abbreviation)
  implication: Underdog API changed team field from abbreviation to UUID; team_aliases(uuid) never matches; game_matches_row always returns False for Props rows

- timestamp: 2026-06-21
  checked: mlb_2026-06-21.xlsx Picks sheet Away/Home Team fields
  found: Away Team=None, Home Team='BAL @ LAD' (composite matchup in Home Team field, Away Team missing)
  implication: game_matches_row home/away branch evaluates team_aliases(None) = set() which is always falsy; match fails for Picks PROP rows too (though PROPs are actually skipped from Picks sheet and graded from Props sheet)

- timestamp: 2026-06-21
  checked: sports_system_runner.py imports section
  found: import re is missing from top-level imports; parse_confidence_from_reasoning() at line 4163 uses re.search; result_record_from_source calls parse_confidence_from_reasoning for PROP rows
  implication: ALL prop grading crashes with NameError: name 're' is not defined — even when game_matches_row succeeds, no prop result rows are ever written. This is the third independent root cause.

## Resolution

root_cause: Three independent bugs all blocking prop grading:
  1. game_matches_row: UUID Team fields (Underdog API changed team_id format from abbreviation to UUID since ~June 12) + composite Home Team strings ('BAL @ LAD' with Away Team=None) — both cause zero game-to-pick matching for Props rows
  2. game_completion_monitor: state["graded"]=True set even when graded=[]; permanently poisons the game cache, blocking all future reconciliation retries
  3. Missing top-level import re: parse_confidence_from_reasoning() uses re.search but re was never imported at module level; every PROP grading path crashes with NameError on result_record_from_source

fix:
  - Added import re to top-level imports (line 19)
  - game_matches_row: detect composite Home Team 'AWAY @ HOME' strings (split on '@') to extract team tokens; guard UUID Team fields (skip alias check when team_aliases returns <=2 items i.e. no real team expansion); add 5-minute start-time window fallback for Props rows using Game Start Time / Start Time UTC field
  - parse_espn_scoreboard_game: added start_time field to returned dict (using event.get("date")) for the start-time fallback in game_matches_row
  - game_completion_monitor: only set state["graded"]=True when graded.get("graded") or graded.get("would_grade") is truthy
  - game_status_cache: cleared graded=True from all 146 final games so reconciliation can retry all ungraded June 15-21 picks

verification:
  - 5-case unit test of game_matches_row: all pass (composite Home Team, UUID Team+start_time, UUID Team+wrong game, old abbreviation, normal full names)
  - test_game_completion_monitor_smoke.py: now grades 3 picks (previously crashed with NameError); graded_count=3 vs required >=2
  - 77 tests pass across test_dynamic_gate8, test_slip_payouts, test_game_completion_monitor_smoke, test_def01, test_def02, test_fix02, test_health_check
  - test_fix01_broken_pipe confirmed pre-existing failure (fails identical on clean checkout)

files_changed:
  - scripts/sports_system_runner.py

orchestrator_independent_verification (2026-06-22, Opus):
  - import re root cause CONFIRMED timeline-consistent: re.search at line 4164 introduced by commit 74b84e8 (2026-06-14) which is AFTER the last successful grade (~June 11) and the June 8 slate. Top-level `import re` now present (line 20).
  - grade_game_in_workbook idempotency CONFIRMED: existing_result_refs() + `if ref in already: continue` (lines 4560/4580/4607/4632) skip already-graded picks; sync_master_and_bankroll only runs on NEW rows (4659). => clearing the 146 cache graded-flags CANNOT double-count June 8-11 results.
  - graded-guard CONFIRMED correct: grade_game_in_workbook returns {"graded": [rows]} (4660) → graded.get("graded") truthy iff rows written.
  - Smoke test re-run: grades 3 picks end-to-end (SPREAD+TOTAL+PROP). Targeted regression: 43 passed / 0 failed (test_dynamic_gate8, test_slip_payouts, test_audit/build_slips, test_prop_monitor_*, test_stage1/2/3/5, smoke).

residual_risks / follow-ups (NOT blocking, operator decision):
  - START-TIME FALLBACK is a LIVE path (Picks has 'Game Start Time'; Props has 'Start Time UTC'+'Game Start Time'). 5-min window can match a pick to a SIMULTANEOUS MLB game when team-matching fails. Practical impact mostly limited to Props → wrong game → MANUAL REVIEW (no money error), because composite-team split now makes SPREAD/TOTAL match by team. Cleaner fix = resolve Underdog UUID team_id → team name. Recommend hardening before relying on it long-term.
  - 37% MANUAL REVIEW (ESPN box-score name matching) is a SEPARATE pre-existing reliability gap, unaddressed by this fix — next target.
  - PERF: games with no bets never get marked graded → re-scanned + box-score-fetched every 5-min monitor run; watch against the 660s budget.
  - DATA RECOVERY: code is fixed but the June 15-21 picks are still ungraded on disk. They will only grade on the next reconciliation run WITH NETWORK (current env is offline: NameResolutionError on all hosts). Run `cd scripts && python3 sports_system_runner.py --task check_results` online to recover them.
  - Stale lock (pid 48351 dead) + leftover *.tmp.*.xlsx files = separate cleanup; a live cron monitor (pid 52246) was running during verification, so left untouched.

status_note: code fix verified in working tree, UNCOMMITTED — pending operator decision on commit + start-time hardening.
