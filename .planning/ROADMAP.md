# Roadmap: Hermes Sports Automation — Stability Hardening

## Overview

This milestone hardens an already-working Python sports-betting automation against the two failure modes the operator experiences daily: cron-job timeouts and the recurring `[Errno 32] Broken pipe` / `TASK FAILED` alert on `mlb_prop_monitor`. The work proceeds in strict diagnostic order — root-cause first, then targeted fixes, then a safety net, then visibility into the system's health, then CI so regressions cannot silently re-enter. No gate logic, pick outputs, or workbook schema changes. When complete, every cron job and pipeline runs unattended on schedule.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Diagnosis** - Root-cause the broken pipe and timeout failures with evidence (completed 2026-06-15)
- [x] **Phase 2: Reliability Fixes + Defect Removal** - Eliminate the confirmed failure modes and remove stability-threatening dead code (completed 2026-06-20)
- [x] **Phase 3: Resilience** - Add retries, hard timeouts, and SIGPIPE handling so transient faults are tolerated rather than fatal (completed 2026-06-21)
- [ ] **Phase 4: Observability** - Structured run logs, a heartbeat check, and pattern-aware alerting
- [ ] **Phase 5: CI** - Automated test suite on every change, with correct interpreter and working directory

## Phase Details

### Phase 1: Diagnosis
**Goal**: The operator can point to a documented, evidence-backed root cause for both the broken pipe failure and the cron-job timeouts — specific file, function, and mechanism
**Depends on**: Nothing (first phase)
**Requirements**: DIAG-01, DIAG-02
**Success Criteria** (what must be TRUE):
  1. A written diagnosis names the exact code path that produces `[Errno 32] Broken pipe` on `mlb_prop_monitor` runs, supported by a reproduction script or a captured real-run trace showing the error origin
  2. A written diagnosis names which task, stage, or subprocess exceeds the cron time budget, supported by timing evidence (logged durations or a timed dry run)
  3. The `log()`/`obsidian_sync()` per-line subprocess lead and the stacked subprocess timeout totals are confirmed or ruled out as contributors with evidence, not assumption
**Plans**: 3 plans
  - [x] 01-01-PLAN.md — Broken-pipe repro script + additive traceback hook (DIAG-01)
  - [x] 01-02-PLAN.md — Timing sweep evidence + ranked-contributors table (DIAG-02)
  - [x] 01-03-PLAN.md — Synthesize DIAGNOSIS.md from both evidence sets (DIAG-01, DIAG-02)

### Phase 2: Reliability Fixes + Defect Removal
**Goal**: The confirmed broken-pipe root cause is fixed, cron jobs complete within defined time budgets, all 11 runner tasks run without uncaught failures, and the two stability-threatening defects (duplicate definitions + hardcoded path) are removed
**Depends on**: Phase 1
**Requirements**: FIX-01, FIX-02, FIX-03, DEF-01, DEF-02
**Success Criteria** (what must be TRUE):
  1. A scheduled `mlb_prop_monitor` run (and any task sharing the broken-pipe root cause) completes with no `[Errno 32] Broken pipe` error and exits 0
  2. Every cron task completes within its defined time budget on a real or simulated scheduled run — no `subprocess.TimeoutExpired` and no cron-wrapper kill
  3. All 11 tasks (`daily_picks nba`, `daily_picks mlb`, `prop_monitor nba`, `prop_monitor mlb`, `injury_monitor nba`, `injury_monitor mlb`, `clv_tracker nba`, `clv_tracker mlb`, `game_completion_monitor`, `check_results`, `verify`) complete a clean end-to-end invocation without uncaught exceptions
  4. Only one definition of `injury_monitor` and one of `clv_tracker` exist in `sports_system_runner.py`; the active behavior is confirmed correct by the existing tests
  5. `generate_projections.py` uses `Path.home()` for its base path and runs successfully from any user or path prefix
**Plans**: 5 plans
  - [x] 02-01-PLAN.md — Runner reliability fixes: safe_print sweep + Telegram circuit-breaker + Obsidian decouple (FIX-01, FIX-02)
  - [x] 02-02-PLAN.md — Remove dead duplicate injury_monitor / clv_tracker defs + DEF-01 regression test (DEF-01)
  - [x] 02-03-PLAN.md — Portable generate_projections BASE path + DEF-02 path-resolution test (DEF-02)
  - [x] 02-04-PLAN.md — FIX-01/FIX-02 regression tests + hardened repro harness (FIX-01, FIX-02)
  - [x] 02-05-PLAN.md — Run-all harness over all 11 tasks for the clean-pass proof (FIX-03)

### Phase 3: Resilience
**Goal**: Transient network failures are retried with backoff, broken-pipe / SIGPIPE conditions are caught and tolerated, every task enforces a hard internal time budget, and every fix from Phase 2 is protected by a regression test
**Depends on**: Phase 2
**Requirements**: RES-01, RES-02, RES-03, RES-04
**Success Criteria** (what must be TRUE):
  1. A simulated transient HTTP failure (Odds-API.io, ESPN, Telegram, DFS fetchers) causes a retry with backoff rather than an immediate task failure; after retries are exhausted the failure is logged with context
  2. A broken-pipe or SIGPIPE condition on stdout is caught at the task boundary, logged as a warning, and does not produce a `TASK FAILED` Telegram alert when the underlying task completed successfully
  3. Each task invocation enforces a hard internal timeout; a hung stage exits cleanly with an error log rather than waiting to be killed by the cron wrapper
  4. Running the test suite shows at least one regression test per Phase 2 fix, each test failing on the pre-fix code path and passing on the post-fix code path
**Plans**: 3 plans
  - [x] 03-01-PLAN.md — Runner resilience: subprocess re-run + pipe reclassification + SIGALRM per-task timeout (RES-01, RES-02, RES-03)
  - [x] 03-02-PLAN.md — RES-01 + RES-03 regression tests (subprocess retry, isolated SIGALRM timeout) (RES-01, RES-03, RES-04)
  - [x] 03-03-PLAN.md — RES-02 pipe-reclassify test + Phase-2 audit + full-suite regression sweep (RES-02, RES-04)

### Phase 4: Observability
**Goal**: The operator can review a structured record of every run after the fact, know at a glance whether a scheduled task ran and succeeded, and receive a qualitatively different alert when failures repeat in a pattern rather than just once
**Depends on**: Phase 3
**Requirements**: OBS-01, OBS-02, OBS-03
**Success Criteria** (what must be TRUE):
  1. After any task run, the operator can read a structured log record (task name, status, duration in seconds, error message if any) without parsing free-form text
  2. A health check command or script reports which tasks have not run within their scheduled window and which last ended in failure — the operator can run it at any time to get a system-health snapshot
  3. When the same task fails two or more times in a row, a distinct Telegram alert fires that identifies the pattern (task name, failure count, last error), separate from the per-occurrence failure alert
**Plans**: TBD
**UI hint**: no

### Phase 5: CI
**Goal**: The unittest suite runs automatically on every code change and reports pass/fail, with the run environment matching the production environment (correct interpreter, correct working directory)
**Depends on**: Phase 4
**Requirements**: CI-01, CI-02
**Success Criteria** (what must be TRUE):
  1. A push or pull-request event triggers the test suite automatically and the result (pass/fail) is visible without manual intervention
  2. CI invokes the suite with `python3` from the `scripts/` directory, matching production; a test that requires the `scripts/` working directory or the `python3` interpreter passes in CI and would fail if run with `python` from the project root
  3. A deliberate regression introduced to a tested code path causes the CI run to fail and surface the failure within the CI report
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Diagnosis | 3/3 | Complete   | 2026-06-15 |
| 2. Reliability Fixes + Defect Removal | 5/5 | Complete   | 2026-06-20 |
| 3. Resilience | 3/3 | Complete   | 2026-06-21 |
| 4. Observability | 0/TBD | Not started | - |
| 5. CI | 0/TBD | Not started | - |
