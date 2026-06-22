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

## Cross-Milestone Trends

### Process Evolution

| Milestone | Phases | Plans | Key Change |
|-----------|--------|-------|------------|
| v1.0 | 5 | 17 | First milestone — established diagnosis-first ordering, one-test-per-fix, and a push-time CI gate |

### Cumulative Quality

| Milestone | Tests (CI subset) | Zero-Dep Additions |
|-----------|-------------------|--------------------|
| v1.0 | ~276 collected (gate green) | Yes — no new runtime deps; stdlib + existing requests/openpyxl only |

### Top Lessons (Verified Across Milestones)

1. Evidence before fixes (to be re-validated in the next milestone).
