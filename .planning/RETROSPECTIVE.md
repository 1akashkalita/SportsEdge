# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — Stability Hardening

**Shipped:** 2026-06-22
**Phases:** 5 | **Plans:** 17 | **Commits:** 114 (~8 days, 2026-06-13 → 2026-06-21)

### What Was Built
- Evidence-backed diagnosis (`DIAGNOSIS.md`) pinning the `[Errno 32] Broken pipe` to an unprotected `JSON_RESULT=` print in `main()` and the dominant timeout to the `send_telegram()` retry loop.
- The reliability fixes: `safe_print` stdout sweep, `send_telegram` timeout + circuit breaker, single task-end Obsidian sync, duplicate-definition removal, `Path.home()` de-hardcoding — plus an 11/11 live task pass.
- A resilience net: subprocess retry-with-backoff, post-completion BrokenPipeError reclassification, and a 660s SIGALRM per-task budget under a raised 720s cron ceiling.
- Observability: structured `run_log.jsonl`, a read-only `health_check.py` heartbeat, and additive 🔁 repeated-failure alerting.
- A push-time CI gate (`run_ci_gate.py` + committed `hooks/pre-push`) with a fault-injection proof that it goes RED on a real regression.

### What Worked
- **Diagnosis-first ordering.** Phase 1 produced reproductions and timing evidence before any fix — which correctly *ruled out* the intuitively-suspected stacked subprocess timeouts and avoided fixing the wrong thing.
- **One regression test per fix (RES-04).** Every reliability fix landed with a test that fails on the pre-fix path, so the CI gate now defends each fix concretely.
- **Minimal-invasive discipline held.** The verifier confirmed zero gate-logic / pick-output / workbook-schema changes across the whole milestone — exactly the real-money constraint.

### What Was Inefficient
- **The cron-timeout root cause was external config, not code.** Significant investigation (code-review WR-03) was needed to discover the Hermes `cron.script_timeout_seconds` was 120s while tasks legitimately run to ~509s — the 120s default was orphan-killing healthy jobs. Clamping budgets under 120s (the initial instinct) would have made it worse.
- **A mocked test masked two real defects.** The first RES-01 helper passed `capture_output=True` to `Popen` (TypeError on every real call) and drained via `wait()`+`read()` (deadlock on large output); a fake `Popen` in the test hid both until code review caught them.

### Patterns Established
- **`safe_print` stdout discipline** — never bare-`print` to a pipe a cron parent may close.
- **Structured JSONL run records** written in `main()`'s `finally` so they fire on every exit path without ever crashing a task.
- **Fast-subset CI gate with an include-by-default denylist** — new `test_*.py` are gated automatically; only known live-network/data-dependent files are excluded.
- **SIGALRM per-task hard budget** that self-terminates cleanly just below the external scheduler kill.

### Key Lessons
1. Diagnose with reproductions and timing evidence before fixing — the obvious suspect (subprocess timeouts) was not the cause; the retry loop was.
2. Mocks can hide real defects — exercise resilience/subprocess helpers against real child processes, not fakes.
3. The root cause can live outside the repo — an external scheduler ceiling was the actual timeout driver; fix the ceiling, don't clamp the code under it.
4. "Verified" ≠ "confirmed in production" — Phases 4 & 5 are code-verified but carry live-environment human UAT (Telegram delivery, real `git push`) that only the operator can close.

### Cost Observations
- Model mix: planner on opus; executor / plan-checker / verifier / integration-checker on sonnet (balanced profile).
- Notable: subagent dispatch hit sustained API 529 (Overloaded) during this close — the quick-task executor and the integration checker were both run inline by the orchestrator as a fallback, without loss of rigor.

---

## Milestone: v2.0 — Slips & Props Tracking

**Shipped:** 2026-06-24
**Phases:** 5 (1–4 + inserted 04.1) | **Plans:** 24 | **Requirements:** 18/18

### What Was Built
- Trustworthy prop grading: 4-tier name matching with abstain-on-ambiguity, MLB batting/pitching namespace split, an explicit stat disposition table, `Result Source`/`Result Confidence` provenance, and a money-safe June 8–21 backfill (gate cleared 94.6%).
- Slip reconstruction + grading: `build_slips` wired in, the once-empty Slip History populated, and an 88-slip / 12-date backtest backfilled with an idempotent `(Date, Slip ID)` upsert.
- Slips-only bankroll: bankroll sourced strictly from slip Net PnL with confidence-scaled stakes; prop→bankroll coupling severed; ledger rebased from inception (100 → 126.778).
- Dual metrics + bounded feedback: slip ROI + prop hit-rate by week × sport, and an integrity-locked sigma-calibration loop proven (verdict-snapshot + gate-output tests) to never alter a graded verdict or gate result.

### What Worked
- **UAT → diagnose → fix → re-verify gap loop.** Phase 1's UAT surfaced 4 grading defects; each became a scoped gap-closure plan (01-7…01-11) with its own green test, then a re-verification — none regressed.
- **Money-safe abstain discipline.** Every uncertain grade (ambiguous name, platform disagreement, missing component) abstains to MANUAL REVIEW / PENDING rather than guessing — the right default for a real-money grader.
- **Independent goal-backward verification at close.** Two parallel verifiers re-checked P1/P2 against live code + data (not SUMMARY claims), re-proving the slip-upsert idempotency by re-executing it — which is how the verification debt got closed with evidence rather than assertion.

### What Was Inefficient
- **Verification debt diverged from reality.** Phases shipped "done in substance" but without `VERIFICATION.md`, and requirements (RESULTS-07, SLIPS-03) stayed marked `Pending` long after the work was done — the milestone audit read `gaps_found` mostly on bookkeeping, not missing function. Closing verification as each phase lands would have avoided the late reconciliation.
- **A forward-path gap shipped silently.** BANKROLL-02 confidence staking worked in the one-time rebuild but the daily `build_slips` path stayed flat-staked (`stake_units=1.0`) until the audit caught it and Phase 04.1 fixed it — the integration seam between "rebuild" and "daily" wasn't exercised end-to-end at first.
- **Generation noise surfaced reactively as a stability bug.** ~88% of MLB candidates are unprojectable markets logged as GATE-1 skips, bloating Skipped Picks to ~1,500 rows/slate — which only surfaced when it caused an O(n²) recap hang, fixed across two reactive quick tasks rather than designed-out up front.

### Patterns Established
- **Provenance on every graded row** (`Result Source` / `Result Confidence`) — grading is auditable, and scraped/manual recoveries are distinguishable from API truth.
- **Idempotent upsert on a stable business key** (`(Date, Slip ID)`) so backfills and re-runs converge instead of duplicating.
- **Integrity-locked feedback** — AST-isolate the feedback writer from the gate/grading code and assert via verdict-snapshot + gate-output tests that the loop can't rewrite history.
- **Single-source reason-prefix predicate** for log-write filtering (defined once, imported by both the writer and the cleanup) — no duplicated literal to drift.

### Key Lessons
1. Close verification debt as each phase lands — "done in substance" silently diverging from "marked done / verified" turns milestone close into archaeology.
2. Exercise integration seams end-to-end, not just each side — the rebuild path and the daily path both "worked" while the daily one was flat-staked.
3. A test that reads red for already-passed work (the non-idempotent June-8 gate) pollutes the baseline — make historical gates idempotent (pin a pre-state fixture).
4. Generation behavior that floods a persisted log sheet is a latent stability risk, not just noise — bound what gets written before it grows into an O(n²) read.

### Cost Observations
- Model mix: opus planner; sonnet executors; parallel sonnet/opus verifiers at close.
- Notable: the two phase verifiers ran concurrently and each re-derived its evidence from live data/code (re-running tests + re-executing the slip upsert), so the close rests on reproduction, not on trusting prior SUMMARY notes.

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 5 | 17 | First milestone — established diagnosis-first ordering, one-test-per-fix, and a push-time CI gate |
| v2.0 | 5 | 24 | Real-money grading discipline — money-safe abstain, provenance on every row, idempotent backfills, and independent goal-backward verification at close |

### Cumulative Quality

| Milestone | Tests (CI subset) | Zero-Dep Additions |
|-----------|-------------------|--------------------|
| v1.0 | ~276 collected (gate green) | Yes — no new runtime deps; stdlib + existing requests/openpyxl only |
| v2.0 | ~775 collected (2 pre-existing baseline failures) | Yes — still stdlib + requests/openpyxl only |

### Top Lessons (Verified Across Milestones)

1. **Evidence before fixes / before "done."** v1.0: diagnose with reproductions before fixing. v2.0: verify goal-backward against live data before marking complete. Both reject assertion in favor of reproduction.
2. **Root causes hide outside the obvious place** — v1.0's timeout was an external cron ceiling; v2.0's bankroll freeze was three independent grading bugs + a UUID team-field API change, not the model.
3. **"Verified" ≠ "confirmed in production"** — both milestones close with live-environment human-UAT items only the operator can clear.
4. **Close verification/validation debt continuously** — both milestones deferred Nyquist VALIDATION; v2.0 also had to reconcile late requirement/VERIFICATION bookkeeping at close.
