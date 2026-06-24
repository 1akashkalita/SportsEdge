---
phase: 02-slip-reconstruction-and-grading
plan: 3
type: execute
wave: 3
depends_on: ["02-2"]
files_modified:
  - scripts/grade_slips.py
  - scripts/sports_system_runner.py
  - scripts/test_grade_slips_backfill.py
requirements: [SLIPS-01, SLIPS-03, SLIPS-04]
autonomous: false
must_haves:
  truths:
    - "Slip definitions exist for every date June 8–21 — missing dates have build_slips.py run first so the backfill has slips to grade"
    - "The June 8–21 Slip History backfill executes and populates per-day + master Slip History with graded slips"
    - "Re-running the backfill on a date that already has slip records is idempotent — no duplicate Slip History rows"
    - "A grade_slips runner task exposes slip grading through the system flow so a daily run produces Slip History records (SLIPS-01 wired in)"
    - "Slip success (Slip History: slip result, payout multiplier, net PnL) is demonstrably separate from prop success (Results / Pick History) across the backfilled range"
  artifacts:
    - path: "scripts/grade_slips.py"
      provides: "ensure_slip_defs (build missing slips_<date>.json) + a backfill_range entry point + CLI"
      min_lines: 180
      exports: ["ensure_slip_defs", "backfill_range", "main"]
    - path: "scripts/test_grade_slips_backfill.py"
      provides: "Offline unittest: missing-def build is invoked, idempotent multi-date backfill, slip vs prop separation"
      contains: "unittest"
  key_links:
    - from: "scripts/sports_system_runner.py run_task"
      to: "grade_slips.grade_slips_for_date / backfill_range"
      via: "a grade_slips task mapping entry"
      pattern: "grade_slips"
    - from: "scripts/grade_slips.py ensure_slip_defs"
      to: "build_slips.py --date <date>"
      via: "subprocess when slips_<date>.json absent"
      pattern: "build_slips"
---

<objective>
Complete the phase: guarantee slip definitions exist for every June 8–21 date (run `build_slips.py` for missing dates), execute the idempotent June 8–21 Slip History backfill, wire a `grade_slips` task into the runner so the daily flow produces Slip History records (SLIPS-01, SLIPS-03), and confirm slip success is recorded separately from prop success across the range (SLIPS-04). A blocking human-verify checkpoint guards the real-money Slip History / master_pnl write, mirroring P1's 01-6.

Purpose: This is the operator's backtest of the model's slip recommendations from inception. The grading + idempotent persistence built in Waves 1–2 is now run for real across the historical range, behind a human gate because it writes the money-bearing ledger. Wiring a runner task means future daily runs keep Slip History populated automatically.

Output: extended `scripts/grade_slips.py` (`ensure_slip_defs`, `backfill_range`, CLI `main`), a `grade_slips` runner task, `scripts/test_grade_slips_backfill.py`, and the executed + human-verified June 8–21 backfill.
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
@.planning/phases/02-slip-reconstruction-and-grading/02-1-SUMMARY.md
@.planning/phases/02-slip-reconstruction-and-grading/02-2-SUMMARY.md

<interfaces>
<!-- Wave 2 (grade_slips.py) provides: -->
grade_slips_for_date(date, *, dry_run=False, player_stats_by_sport=None) -> summary dict
  # loads data/research/slips/slips_<date>.json; grades + idempotently writes per-day + master Slip History.
  # returns {"status": "no_slip_file", ...} when the slip def is missing.

<!-- From scripts/build_slips.py: -->
#   CLI: python3 build_slips.py --date <YYYY-MM-DD>  → writes data/research/slips/slips_<date>.json (+ .md)
#   It needs that date's projections (data/research/projections / backtest_<date>.json), which exist for the range.

<!-- From scripts/sports_system_runner.py: -->
run_task(task) at ~6679 — dispatch dict mapping task name → callable. Add a "grade_slips" entry.
#   Existing tasks: nba_daily_picks, mlb_daily_picks, ...prop_monitor, ...injury_monitor, ...clv_tracker,
#   check_results, game_completion_monitor, verify. Tasks return a dict and print JSON_RESULT=.
#   main() acquires the fcntl lock and emits JSON_RESULT; a grade_slips task slots in with no lock changes.

<!-- Slip files PRESENT (confirmed): June 08,09,10,15,17,18,19,20,21 (+22 today). -->
<!-- Slip files MISSING in range: June 11,12,13,14,16 → ensure_slip_defs must build these. -->
<!-- Per-day + master workbooks for the whole June 8–21 range exist on disk. -->

<!-- P1 precedent for the money-write human gate: .planning/phases/01-trustworthy-results/01-6-PLAN.md -->
<!--   (dry-run sweep → spot-check → human "approved" → real write). Mirror that structure. -->
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: ensure_slip_defs + backfill_range + grade_slips runner task + CLI</name>
  <read_first>
    - .planning/phases/02-slip-reconstruction-and-grading/02-CONTEXT.md (If a date has no slip file, run build_slips.py --date <date> first; grade EVERY category; idempotent backfill)
    - scripts/build_slips.py (the --date CLI and the slips_<date>.json output path data/research/slips/)
    - scripts/sports_system_runner.py (run_task dispatch ~6679; how tasks return dicts; the subprocess.run pattern used for fetchers — reuse it to shell out to build_slips, isolating a crash)
    - scripts/grade_slips.py (Wave 2 grade_slips_for_date contract + no_slip_file return)
    - CLAUDE.md (run from scripts/ with python3; 660s budget; subprocess-isolate child scripts; never change gate/pick logic)
  </read_first>
  <files>scripts/grade_slips.py, scripts/sports_system_runner.py</files>
  <action>
    Extend `scripts/grade_slips.py`:
    (1) `ensure_slip_defs(date)` — if `data/research/slips/slips_<date>.json` is missing, `subprocess.run([sys.executable, "build_slips.py", "--date", date], cwd=SCRIPTS, timeout=...)` (mirror the runner's fetcher subprocess isolation; capture output; on non-zero or timeout return a clear status without crashing). Return whether a def now exists. Idempotent: do nothing when the file already exists.
    (2) `backfill_range(start_date, end_date, *, dry_run=False)` — iterate each date in `[start, end]` (inclusive, YYYY-MM-DD), call `ensure_slip_defs(date)` then `grade_slips_for_date(date, dry_run=dry_run)`; collect per-date summaries (slips graded, WIN/LOSS/reconcile counts, rows written, any no_slip_file). Idempotent across re-runs (Wave 2 upsert guarantees no duplicate rows). Keep each date's work well under the 660s budget.
    (3) `main()` — argparse CLI: `--date` (single date) OR `--start`/`--end` (range), `--dry-run`; default `--date today`. Prints `JSON_RESULT={...}` summary, mirroring the runner's stdout contract. `__main__` calls `main()`.
    In `scripts/sports_system_runner.py` make THREE additive edits (no change to any task function, gate, or pick logic; serialize this single-file edit): (a) add a `"grade_slips"` entry to the `run_task` mapping (~6679) that imports `grade_slips` and calls `grade_slips.grade_slips_for_date(today_str())`, returning its summary dict; (b) add `"grade_slips": 660` to `TASK_TIMEOUTS` (~line 121) — otherwise the task falls back to the 60s default (`budget = TASK_TIMEOUTS.get(args.task, 60)`) and a date's ESPN box-score fetches would trip the SIGALRM kill (plan-checker WARNING-2); (c) add a `grade_slips` branch to `task_workbook_paths` (~line 6647) returning `[workbook_path("nba", date), workbook_path("mlb", date), PNL_DIR / "master_pnl.xlsx"]` (mirror check_results) so the cooperative locks cover the per-day workbooks AND master_pnl during the slip write, preventing a race with daily_picks/check_results (plan-checker WARNING-3).
  </action>
  <verify>
    <automated>cd scripts && python3 -c "import grade_slips as g; import sports_system_runner as s; assert callable(g.ensure_slip_defs) and callable(g.backfill_range); assert 'grade_slips' in s.run_task.__code__.co_consts, 'grade_slips not registered in run_task'; assert s.TASK_TIMEOUTS.get('grade_slips')==660, 'grade_slips missing/incorrect TASK_TIMEOUTS'; print('OK')"</automated>
  </verify>
  <acceptance_criteria>
    - `ensure_slip_defs` builds a missing slips_<date>.json by subprocess-ing build_slips.py and is a no-op when the file exists.
    - `backfill_range` iterates a date range, ensures defs, grades + (unless dry-run) writes idempotently, returns per-date summaries.
    - A `grade_slips` task is registered in run_task and returns a summary dict; no existing task/gate/pick logic is changed.
    - `python3 grade_slips.py --date <date> --dry-run` prints a JSON_RESULT summary and writes nothing.
  </acceptance_criteria>
</task>

<task type="auto">
  <name>Task 2: Offline unittest — missing-def build, idempotent multi-date backfill, slip vs prop separation</name>
  <read_first>
    - scripts/test_grade_slips_aggregate.py (Wave 2 fixture + workbook assertion patterns to reuse)
    - scripts/grade_slips.py (ensure_slip_defs / backfill_range / grade_slips_for_date)
    - scripts/slip_payouts.py (SLIP_HISTORY_HEADERS for row/column assertions)
    - MEMORY: run THIS file only; baseline "2 failed, 202 passed"
  </read_first>
  <files>scripts/test_grade_slips_backfill.py</files>
  <action>
    Write `scripts/test_grade_slips_backfill.py` (stdlib `unittest`, `__main__` block), fully offline. Cover: (a) `ensure_slip_defs` invokes the builder when the file is missing — monkeypatch/stub the `subprocess.run` call (or point at a temp SLIP_DIR) and assert it is called for a missing date and NOT called when the file exists; (b) idempotent multi-date backfill — run `backfill_range` (or `grade_slips_for_date` per date) TWICE over a small set of dates using injected fixture box scores and temp workbooks, assert the Slip History data-row count is identical after the second run (no duplicates) and each Slip ID appears once; (c) slip vs prop separation — assert across the run that slip rows live only in the "Slip History" sheet and any Results/Pick History rows are untouched (SLIPS-04). Avoid network and avoid touching the real data/ workbooks (use temp paths / dependency injection).
  </action>
  <verify>
    <automated>cd scripts && python3 test_grade_slips_backfill.py</automated>
  </verify>
  <acceptance_criteria>
    - Test exits 0 fully offline, touching no real data/ workbook and no network.
    - Asserts the builder is invoked for a missing slip def and skipped when present.
    - Asserts a second backfill pass produces no duplicate Slip History rows (idempotent).
    - Asserts slip rows are confined to Slip History, prop rows untouched (SLIPS-04 demonstrable).
  </acceptance_criteria>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 3: Execute and verify the June 8–21 real-money Slip History backfill</name>
  <what-built>
    Waves 1–2 built a slip grader that reuses P1 results and writes Slip History idempotently; Task 1 added `ensure_slip_defs`, `backfill_range`, a `grade_slips` runner task, and a CLI. The backfill re-grades the model's recommended slips across June 8–21 and writes Slip History into each per-day workbook AND `data/pnl/master_pnl.xlsx`. Missing slip defs (June 11,12,13,14,16) are built first via `build_slips.py`. Because this writes the real-money ledger (master_pnl Slip History), it pauses for human verification — mirroring P1's 01-6.
  </what-built>
  <how-to-verify>
    1. First run a DRY-RUN over the range and review per-date counts (slips graded, WIN / LOSS / reconciliation):
         cd scripts && python3 grade_slips.py --start 2026-06-08 --end 2026-06-21 --dry-run
       Confirm: every date has slip defs (missing ones were built), slip counts look sane (e.g. ~8 categories/day where projections existed), and slips with any unresolved leg show as PENDING / Needs Payout Reconciliation — NOT as WIN/LOSS.
    2. Spot-check 3–5 graded slips: open `data/mlb/mlb_2026-06-XX.xlsx` → Slip History and confirm a 2-leg power all-WIN slip shows 3.0x / +2.0u and a slip with a losing leg shows 0x / -1u, and the legs text matches `slips_2026-06-XX.json`.
    3. Confirm idempotency BEFORE the money write: re-run the dry-run for one date and verify it reports no new rows would be added for already-present Slip IDs.
    4. Only after the dry-run looks correct, run the REAL backfill:
         cd scripts && python3 grade_slips.py --start 2026-06-08 --end 2026-06-21
       Confirm each date completes well under the 660s budget (watch the 90s slow-run warning vs the 720s cron kill).
    5. Verify after: `data/pnl/master_pnl.xlsx` → Slip History is populated with the range's slips, NO duplicate Slip IDs per date, and the Results / Pick History prop rows are unchanged (slip success separate from prop success — SLIPS-04). Re-run the full backfill once more and confirm the Slip History row count does NOT grow (idempotent — SLIPS-03).
  </how-to-verify>
  <resume-signal>Type "approved" once the June 8–21 Slip History backfill is verified correct and idempotent (or describe slips that graded wrong / dates where ESPN box data capped resolution).</resume-signal>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| backfill execution → real-money ledger | A mass slip backfill writes master_pnl.xlsx Slip History; a wrong/duplicated batch corrupts the backtest |
| build_slips subprocess → slip defs | A failing builder for a missing date must not crash the backfill or fabricate slips |
| ESPN historical box availability → slip resolution | Missing older box data caps how many legs resolve; unresolved slips must stay PENDING, not fabricated |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-02-08 | Tampering | June 8–21 Slip History backfill write | mitigate | Blocking human-verify after a dry-run sweep + spot-check before the real write; Wave 2 upsert-by-Slip-ID prevents duplicates (pinned by Task 2 idempotency test) |
| T-02-09 | Denial of Service | build_slips subprocess / per-date runtime | mitigate | subprocess-isolated builder with timeout (mirrors runner fetcher isolation); each date's grade well under 660s; degrade to a status, never crash |
| T-02-10 | Repudiation | slip-resolution ceiling on old dates | accept | ESPN historical box availability may cap leg resolution; unresolved slips stay PENDING/reconcile and the dry-run surfaces the real counts |
| T-02-11 | Tampering | slip metrics interleaving into prop ledger | mitigate | Writes confined to Slip History sheet; Task 2 test + step-5 verification assert Results/Pick History untouched (SLIPS-04) |
</threat_model>

<verification>
- `python3 test_grade_slips_backfill.py` exits 0 (missing-def build, idempotent backfill, slip/prop separation).
- The dry-run `grade_slips.py --start 2026-06-08 --end 2026-06-21 --dry-run` shows defs present for all dates and PENDING (not LOSS) for unresolved-leg slips.
- After the human-approved real backfill: master_pnl Slip History populated, no duplicate Slip IDs per date, Results/Pick History prop rows unchanged; a re-run does not grow the row count.
- Each backfill date completes under the 660s budget.
- At PHASE END: run the full `python3 -m pytest` from `scripts/` once and confirm the clean baseline ("2 failed, 202 passed") plus all new Phase-2 tests pass.
</verification>

<success_criteria>
- Slip defs exist for every June 8–21 date (missing ones built) and the backfill populates Slip History across the range (SLIPS-03).
- The backfill is idempotent — re-running a date adds no duplicate Slip History rows (SLIPS-03).
- A `grade_slips` runner task wires slip grading into the system flow so daily runs produce Slip History records (SLIPS-01).
- Slip success is demonstrably separate from prop success across the persisted sheets (SLIPS-04).
- Phase-end full pytest matches the clean baseline plus the new Phase-2 tests.
</success_criteria>

<output>
Create `.planning/phases/02-slip-reconstruction-and-grading/02-3-SUMMARY.md` when done. Record the dates whose slip defs were built, the per-date graded-slip / WIN / LOSS / reconciliation counts, the post-backfill Slip History row totals (per-day + master), the max per-date wall-clock observed, and the phase-end full-pytest result.
</output>
