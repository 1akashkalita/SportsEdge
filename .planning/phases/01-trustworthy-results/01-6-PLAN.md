---
phase: 01-trustworthy-results
plan: 6
type: execute
wave: 6
depends_on: ["01-4", "01-5"]
files_modified:
  - scripts/test_june8_dryrun_gate.py
autonomous: false
requirements: [RESULTS-06, RESULTS-07]
must_haves:
  truths:
    - "The June 8 dry-run resolves ≥80% of the non-Fantasy-Score MANUAL REVIEW prop rows on that date to WIN/LOSS/PUSH after Layer-1 hardening"
    - "Re-grading June 8–21 replaces MANUAL REVIEW / PENDING rows with terminal grades in place — no duplicate Results or Pick History rows, settled rows untouched"
    - "Rows that still cannot resolve return to MANUAL REVIEW and remain re-gradeable"
    - "The full backfill run stays under the 660s cron budget"
  artifacts:
    - path: "scripts/test_june8_dryrun_gate.py"
      provides: "The hard pass/fail gate: ≥80% non-Fantasy June-8 MANUAL REVIEW prop rows resolve after Layer-1"
      contains: "0.80"
  key_links:
    - from: "check_results"
      to: "game_completion_monitor(reconciliation=True) -> grade_game_in_workbook"
      via: "should_grade forced True; value-aware guard re-enters MANUAL REVIEW/PENDING rows"
      pattern: "reconciliation"
---

<objective>
Execute the June 8–21 backfill through the reconciliation path now that Layer 1 (and optional Layer 2) is hardened, and prove the RESULTS-07 hard gate: the June 8 dry-run resolves ≥80% of the non-Fantasy-Score MANUAL REVIEW prop rows to WIN/LOSS/PUSH (RESULTS-07). The backfill re-grades in place via the value-aware guard, abstaining on ambiguity, with a blocking human verification before the real-money write so a wrong mass re-grade cannot silently corrupt the ledger (RESULTS-06).

Purpose: This is the operator's waited-on recovery — the 86 MANUAL REVIEW rows + ungraded June 15–21 MLB picks. It is the single pass/fail gate for Criterion #1. ESPN summary availability for older dates is unverified, so the achievable rate is MEASURED in the dry-run, not assumed.

Output: `test_june8_dryrun_gate.py` (the automated ≥80% gate), the executed June 8–21 re-grade, and a human checkpoint confirming the backfilled ledger before persistence.
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
@.planning/phases/01-trustworthy-results/01-4-SUMMARY.md
@.planning/phases/01-trustworthy-results/01-5-SUMMARY.md

<interfaces>
<!-- The reconciliation path that drives the backfill. From sports_system_runner.py: -->

check_results() at :4771 -> game_completion_monitor(date, reconciliation=True) at :4684
  reconciliation=True forces should_grade=True for final/void games (:4700-4701).
  grade_game_in_workbook(sport, game, date, dry_run=...) at :4548 — dry_run=True returns
  {"would_grade": [...], "manual_reviews": [...]} WITHOUT writing the workbook (:4655-4657).

June 8 MLB workbook: data/mlb/mlb_2026-06-08.xlsx (confirmed present). The Results sheet holds the
  MANUAL REVIEW prop rows; the non-Fantasy subset = name-failure + DIRECT + DERIVED classes (exclude the
  Hitter/Pitcher/NBA Fantasy Score composites, which are the residue that only Layer-2 can resolve).

Operational note (Performance section): npx cold-start. Optionally `npm i -g firecrawl-cli@1.19.2` on the cron
  host to avoid the one-time penalty IF Layer-2 will run; with the flag OFF (default) this is irrelevant.
</interfaces>
</context>

<tasks>

<task type="auto">
  <name>Task 1: June 8 dry-run hard gate (≥80% non-Fantasy MANUAL REVIEW prop rows resolve)</name>
  <read_first>
    - docs/superpowers/specs/2026-06-21-trustworthy-results-design.md (Success criterion #1; Testing strategy #11; Backfill plan steps 3-6; the confirmed class breakdown of the 86 rows)
    - .planning/phases/01-trustworthy-results/01-4-SUMMARY.md (the reconciliation guard + side re-parser behavior)
    - scripts/sports_system_runner.py (check_results:4771; game_completion_monitor:4684; grade_game_in_workbook dry_run path :4655-4657)
  </read_first>
  <files>scripts/test_june8_dryrun_gate.py</files>
  <action>
    Write `scripts/test_june8_dryrun_gate.py` (Testing strategy #11) that runs the backfill dry-run over `data/mlb/mlb_2026-06-08.xlsx`: drive `grade_game_in_workbook(..., dry_run=True)` (via the reconciliation path or directly per the final-game objects for that date) for each June-8 game, collect the would-grade results, and compute the resolution rate over the NON-Fantasy-Score MANUAL REVIEW prop rows on that date (the name-failure + DIRECT + DERIVED classes; EXCLUDE the Hitter/Pitcher/NBA Fantasy Score composites and any rows whose side is unrecoverable per the 01-4 abstain policy — those are excluded from the denominator by design, not counted as failures). Assert the resolved fraction (rows now WIN/LOSS/PUSH) is `>= 0.80`. If ESPN summary JSON is unavailable for June 8 and caps the achievable rate, the test must surface the measured numerator/denominator in its failure message so the operator sees the real ceiling rather than a bare assertion failure. This is a dry-run only — it must NOT write any workbook.
  </action>
  <verify>
    <automated>cd scripts && python3 test_june8_dryrun_gate.py</automated>
  </verify>
  <done>`test_june8_dryrun_gate.py` exits 0: ≥80% of non-Fantasy-Score MANUAL REVIEW prop rows for June 8 resolve to WIN/LOSS/PUSH after Layer-1, with the measured numerator/denominator reported. No workbook is written by the dry-run.</done>
</task>

<task type="checkpoint:human-verify" gate="blocking">
  <name>Task 2: Execute and verify the June 8–21 real-money backfill</name>
  <what-built>
    Layer-1 (and flag-gated Layer-2) grading hardening is complete and the June-8 dry-run gate passes. The reconciliation path (`check_results` → `game_completion_monitor(reconciliation=True)`) will now re-grade the MANUAL REVIEW / PENDING Results rows across June 8–21 IN PLACE: `upsert_result_row` overwrites the same Results row, `sync_master_and_bankroll` replaces Pick History by ref and rebuilds Daily Log / Bankroll Chart Data, settled WIN/LOSS/PUSH/VOID rows (any casing) are skipped, parlays grade only against the full persisted leg set, and unrecoverable rows return to MANUAL REVIEW. This touches the real-money ledger (`data/pnl/master_pnl.xlsx`, `data/pnl/bankroll.json`), so it pauses for human verification.
  </what-built>
  <how-to-verify>
    1. First run a DRY-RUN sweep over June 8–21 (one date at a time) and review the would-grade / manual_reviews counts per date — confirm the totals look sane (the 86 MANUAL REVIEW rows should drop toward the residual Fantasy-Score class) and that no previously-settled bet is being re-graded:
         cd scripts && for d in 08 09 10 11 12 13 14 15 16 17 18 19 20 21; do python3 -c "import sports_system_runner as s; ..." ; done   # dry_run=True per date
    2. Spot-check 3–5 newly-resolved rows in `data/mlb/mlb_2026-06-XX.xlsx` Results against the actual ESPN box score to confirm the WIN/LOSS verdict and the Result Source / Result Confidence are correct.
    3. Confirm a known previously-settled row (a real WIN or LOSS) is UNCHANGED in the dry-run output.
    4. Only after the dry-run looks correct, run the real backfill: `cd scripts && python3 sports_system_runner.py --task check_results` (or the per-date reconciliation) for the June 8–21 range. With `ENABLE_FIRECRAWL_RESULT_FALLBACK` OFF (default), only Layer-1 runs. Confirm each run completes under 660s (watch for the 90s slow-run warning vs the 720s cron kill).
    5. Verify the ledger after: no duplicate Results or Pick History rows per ref; the bankroll/Daily Log reflect the newly-terminal rows; remaining MANUAL REVIEW rows are the Fantasy-Score residue (and any unrecoverable-side rows).
  </how-to-verify>
  <resume-signal>Type "approved" once the June 8–21 backfill is verified correct (or describe the rows that re-graded wrong / the dates where ESPN data capped recovery).</resume-signal>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| reconciliation re-grade → real-money ledger | A mass re-grade writes directly to master_pnl.xlsx / bankroll.json — a wrong batch corrupts the operator's ledger |
| ESPN summary availability (older dates) → recovery rate | Missing historical box data caps how many rows are re-gradable regardless of matching |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-01-15 | Tampering | June 8–21 backfill write | mitigate | Blocking human-verify after a dry-run sweep + spot-check before the real write; in-place upsert + replace-by-ref prevent duplicates (pinned by plan 01-4 tests) |
| T-01-16 | Denial of Service | per-date reconciliation runtime | mitigate | Layer-2 default-off + per-run scrape cap keep each run <660s; 90s slow-run warning observed against the 720s cron kill |
| T-01-17 | Repudiation | recovery-rate ceiling | accept | ESPN historical availability may cap recovery; the dry-run MEASURES and reports the real numerator/denominator rather than assuming 100% |
</threat_model>

<verification>
- `python3 test_june8_dryrun_gate.py` exits 0 (the RESULTS-07 hard gate).
- The dry-run sweep over June 8–21 shows MANUAL REVIEW counts dropping to the residual Fantasy-Score class; no settled row re-graded.
- After the human-approved real backfill: no duplicate Results/Pick-History rows per ref; bankroll/Daily Log updated; remaining MANUAL REVIEW = Fantasy-Score residue + unrecoverable-side rows.
- Each reconciliation run completes under 660s.
- At PHASE END: run the full `python3 -m pytest` from `scripts/` once and confirm the clean baseline ("2 failed, 202 passed" — the 2 known projection failures) plus all new Phase-1 tests pass.
</verification>

<success_criteria>
- RESULTS-07 gate passes: ≥80% of non-Fantasy-Score June-8 MANUAL REVIEW prop rows resolve.
- June 8–21 backfill re-grades in place with no duplicate rows and settled rows untouched (human-verified).
- The full backfill stays under the 660s budget; unrecoverable rows remain MANUAL REVIEW and re-gradeable.
- Phase-end full pytest matches the clean baseline plus the new tests.
</success_criteria>

<output>
Create `.planning/phases/01-trustworthy-results/01-6-SUMMARY.md` when done. Record the MEASURED June-8 resolution rate (numerator/denominator), the post-backfill MANUAL REVIEW residual count across June 8–21, the max per-run wall-clock observed, and the phase-end full-pytest result.
</output>
