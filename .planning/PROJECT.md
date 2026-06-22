# Hermes Sports Automation — Stability Hardening

## What This Is

The Hermes sports-betting automation is an existing, in-use Python system that runs as unattended cron jobs: it fetches DFS player props and sportsbook game lines for NBA + MLB, runs every candidate pick through a fixed "no-bet gate" gauntlet, persists results to per-sport Excel workbooks, and pushes Telegram alerts + Obsidian vault notes. **This milestone is a reliability-hardening pass on that system** — diagnose and eliminate the cron-job timeouts, kill the bug causing the recurring `❌ SPORTS TASK FAILED … [Errno 32] Broken pipe`, and get every task and pipeline running dependably on schedule. It is for the system's single operator (the author), who needs to trust the automation before improving the model.

## Core Value

Every cron job and pipeline runs correctly on schedule — no timeouts, no task-failure alerts — so the operator can stop babysitting it and confidently move on to model/accuracy work next.

## Current Milestone: v2.0 Slips & Props Tracking

**Goal:** Make the bankroll reflect actual DFS slips (not individual props), track and grade both slips and props, backfill from inception (2026-06-08), and feed realized outcomes back into selection — so the operator can finally tell whether the model is improving.

**Why now:** v1.0 made the pipeline run reliably; investigation then showed the bankroll has been frozen because grading was broken and ~37% of props never resolved (MANUAL REVIEW), and slips were never recorded at all. Trustworthy measurement must come before any model tuning.

**Target features (strict dependency chain P1→P2→P3→P4):**
- **P1 — Trustworthy results:** drive the ~37% prop MANUAL-REVIEW rate toward zero via in-process name/stat matching hardening, then a flagged, subprocess-isolated firecrawl keyless scrape for the residue; add `Result Source`/`Result Confidence` provenance; money-safe June 8–21 backfill. *(Spec approved & committed: `docs/superpowers/specs/2026-06-21-trustworthy-results-design.md`.)*
- **P2 — Slips: reconstruct → grade → record:** wire `build_slips.py` per day, populate the always-empty Slip History sheet (forward + June 8–21 backtest of the model's recommended slips).
- **P3 — Slips-only bankroll:** rebase bankroll to sum slip Net PnL with confidence-scaled stakes; props become accuracy-only (out of the bankroll).
- **P4 — Dual metrics + feedback into selection:** report slip ROI + prop hit-rate; feed realized outcomes back into projection/gate tuning.

## Current State

**Shipped v1.0 — Stability Hardening (2026-06-22):** 5 phases / 17 plans, 16/16 v1 requirements satisfied. The broken-pipe `TASK FAILED` is eliminated, cron timeouts are root-caused and bounded (660s SIGALRM budget under a 720s cron ceiling), and a resilience + observability + CI safety net guards every fix. Milestone audit: `tech_debt` (no blockers). Outstanding before the system is fully "trusted in production": 5 live-environment human-UAT confirmations + optional Nyquist/hardening follow-ups (see STATE.md → Deferred Items). **Next milestone:** model/accuracy work — the explicit "after stability" goal — once the live UAT confirms the hardening on the real cron host. Start with `/gsd-new-milestone`.

## Requirements

### Validated

<!-- Existing capabilities inferred from the codebase map (.planning/codebase/). Shipped and relied upon. -->

- ✓ Daily picks pipeline for NBA + MLB: fetch DFS props → game markets → hit-rate DB → projections → gate gauntlet → workbook → alerts — existing
- ✓ No-bet gate gauntlet (`evaluate_no_bet_gates`: G1–G9, G12 + MLB sub-gates) filtering every candidate pick — existing
- ✓ DFS prop aggregation from PrizePicks + Underdog (Dabble comparison present but disabled) — existing
- ✓ Odds-API.io game-market integration with rate-limit tracking — existing
- ✓ Prop monitor (intraday line-move detection) for NBA + MLB — existing
- ✓ Injury monitor (ESPN status polling) for NBA + MLB — existing
- ✓ CLV tracker (closing-line-value logging) for NBA + MLB — existing
- ✓ Game-completion monitor + results grading + bankroll / master-P&L updates — existing
- ✓ Daily recap, Telegram alerts, and Obsidian vault sync — existing
- ✓ Excel-workbook persistence with schema migration, atomic saves, `fcntl` locking, and dated backups — existing
- ✓ Defensive SKIP-state handling + single-process lock + `JSON_RESULT` stdout contract — existing
- ✓ `unittest`-based test suite (`scripts/test_*.py`, incl. stage1–5 end-to-end pipeline tests) — existing
- ✓ Broken-pipe `[Errno 32]` failure fixed — all bare stdout prints routed through `safe_print`; a completed task survives a closed cron pipe with no spurious `TASK FAILED` (regression-tested) — Phase 2 (FIX-01)
- ✓ All 11 runner tasks run clean end-to-end — proven by `scripts/run_all_tasks.py` live pass (11/11 on 2026-06-20) — Phase 2 (FIX-03)
- ✓ Stability-threatening defects removed — duplicate `injury_monitor`/`clv_tracker` defs deleted (DEF-01); `generate_projections.py` BASE de-hardcoded to `Path.home()` (DEF-02) — Phase 2
- ✓ Resilience safety net — subprocess stages re-run once with backoff (RES-01), post-completion `BrokenPipeError` reclassified at the task boundary so a closed cron pipe no longer fires `TASK FAILED` (RES-02), every task enforces a SIGALRM hard wall-clock budget that self-terminates cleanly before the cron kill (RES-03), and every Phase-2 fix is regression-tested (RES-04) — Phase 3
- ✓ Cron timeout root cause resolved at the ceiling, not by clamping — the Hermes `cron.script_timeout_seconds` was 120s while tasks genuinely run up to ~509s (orphan-killing them mid-run); raised to 720s with RES-03 budgets at 660s self-terminating just below it — Phase 3
- ✓ Observability layer — every runner invocation appends a structured Core+ JSONL record to `data/pnl/logs/run_log.jsonl` (OBS-01); a standalone read-only `health_check.py` reports overdue / last-failed tasks with a non-zero exit + 🩺 heartbeat (OBS-02); a 🔁 REPEATED FAILURE alert fires on consecutive failures, additive to the per-occurrence ❌/⏱ alerts (OBS-03) — Phase 4 (55 tests; live cron/Telegram end-to-end pending human UAT)
- ✓ CI gate catches breakage before cron does — a committed `hooks/pre-push` (wired via `core.hooksPath=hooks` by `install_hooks.py`) runs a fast-subset gate (`run_ci_gate.py`: fail-loud preflight asserting python3 3.14 + `requests`/`openpyxl` + `scripts/` CWD, then a 3-file-denylist pytest) on every `git push`; an environment guard test proves the python3/`scripts/` contract (CI-02), and `repro_ci_regression.py` fault-injection proves the gate goes RED on a real regression and GREEN on revert (CI-01) — Phase 5 (8/8 verified; end-to-end push-fire pending human UAT — no git remote yet)

### Active

<!-- This milestone. Hypotheses until shipped and validated. -->

- (none — all milestone requirements validated)

### Out of Scope

<!-- Explicit boundaries with reasoning to prevent re-adding. -->

- Full projection-model rebuild / new ML training pipeline — v2.0 adds trustworthy measurement and a bounded outcome→selection feedback loop (P4), not a ground-up model rewrite
- New sports or new bet types — not part of this milestone
- Broad refactor of the ~5,650-line `sports_system_runner.py` monolith — only stability-threatening defects are in-bounds, not restructuring
- Migrating off Excel persistence to a database — Excel works today; harden it, don't replace it

## Context

- The existing system is fully mapped in `.planning/codebase/` (`ARCHITECTURE.md`, `STACK.md`, `STRUCTURE.md`, `CONVENTIONS.md`, `TESTING.md`, `INTEGRATIONS.md`, `CONCERNS.md`).
- **Reported pain:** cron jobs sometimes time out; the operator frequently receives `❌ SPORTS TASK FAILED: mlb_prop_monitor / Error: [Errno 32] Broken pipe`.
- **Leads surfaced during questioning / codebase mapping (to confirm in the diagnosis phase, not assume):**
  - No broken-pipe / `SIGPIPE` handling exists anywhere; a raw `BrokenPipeError` propagates to the top-level `try/except` in `main()`, which turns *any* failure into the `TASK FAILED` Telegram alert.
  - `log()` mirrors every line to stdout **and spawns an `obsidian_sync()` subprocess per log line** — a prime suspect for both slowness (timeouts) and broken pipes.
  - Nested subprocess timeouts stack: `fetch_dfs_props` 300s, `build_hit_rate_db` 600s, `generate_projections` 600s, `obsidian_sync` 60s — a slow day can exceed a cron budget.
  - The runner logs a >90s slow-run warning but has **no internal hard self-timeout**, so a "timeout" is likely the cron wrapper killing the job or a `subprocess.TimeoutExpired`.
  - `injury_monitor` and `clv_tracker` are each **defined twice** (lines ~3610/5049 and ~3651/5443); Python silently keeps the second — a latent-bug smell worth chasing.
  - `generate_projections.py` hardcodes `BASE = Path("/Users/akashkalita/sports_picks")` instead of `Path.home()`.
- **Environment:** personal macOS; Hermes cron (`no_agent=True`); system `python3` (3.14) with ambient deps — there is no `requirements.txt`, lockfile, or virtualenv. The default `python` (3.13) lacks the dependencies.

## Constraints

- **Tech stack**: Python 3.14 + `requests` + `openpyxl`; the runner must be invoked from `scripts/` with `python3` — sibling imports and ambient deps require it.
- **Environment**: fixes must work under Hermes cron on the operator's Mac — that's where the failures occur and where "stable" must be proven.
- **Compatibility**: must not change gate logic, pick outputs, or the workbook schema — this is a real-money system in active daily use.
- **Approach**: minimal-invasive — stability fixes and stability-threatening defect fixes only; no broad restructuring.

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Scope = full hardening (root-cause fixes + safety net + observability + CI) | Operator wants to fully trust the system before model work | ✓ v1.0 — all 5 phases shipped (diagnosis → fixes → resilience → observability → CI); 16/16 requirements validated |
| Fix only stability-threatening defects; no broad monolith refactor | "Stable before changing stuff" | ✓ v1.0 — held: only FIX/DEF/RES/OBS/CI changes; verifier confirmed zero gate-logic / pick-output / workbook-schema changes |
| Defer all model/accuracy work to a later milestone | Build a reliable foundation first | ✓ v1.0 — held: model/accuracy stayed Out of Scope; carried to the next milestone |
| Definition of done = all cron jobs + pipelines run correctly (no timeouts, no task-failed alerts) | The operator's stated bar for "stable" | ✓ v1.0 — met by code + regression tests (16/16); final live-cron confirmation deferred as human UAT |
| Treat diagnosis as a first-class step (reproduce + root-cause before fixing) | The exact cause of the broken pipe is not yet pinned down | ✓ Phase 1 — `DIAGNOSIS.md`: broken pipe = bare `JSON_RESULT=` print in `main()` (`sports_system_runner.py:5634`/`:5640`); dominant timeout = `send_telegram()` retry loop (30s×2 per call site, 24,923s max observed), NOT stacked subprocess timeouts (ruled out) |
| Bound the diagnosed failure modes minimally rather than install the general safety net in the same phase | Fix the proven, dominant contributors first; defer retries/hard-timeouts/SIGPIPE to Phase 3 so regression tests cover the actual fix paths | ✓ Phase 2 — `safe_print` stdout sweep (FIX-01), `send_telegram` 10s timeout + per-invocation circuit-breaker, Obsidian decoupled to one task-end `sports_run_log` sync (FIX-02), duplicate defs removed (DEF-01), `Path.home()` base (DEF-02); live 11/11 task pass (FIX-03) |
| RES-01 retry scoped to the subprocess stages, not every HTTP call | The fetch/ESPN/projection stages are already isolated subprocesses with clean exit codes; Telegram (Phase-2 circuit breaker) and Odds-API.io (own retry loop) handle their own transient faults | ✓ Phase 3 — `_subprocess_run_with_retry` wraps the 3 stages with one backoff re-run (D-04) |
| Catch `BrokenPipeError` at the task boundary instead of installing a `SIGPIPE` handler | A post-completion sentinel (`_task_result`) cleanly distinguishes "pipe closed after success" from a genuine mid-task failure without a process-wide signal handler (D-09) | ✓ Phase 3 — RES-02, both cases regression-tested |
| Raise the Hermes 120s cron kill to 720s rather than clamp RES-03 budgets under 120s | Investigation (code-review WR-03) proved tasks genuinely run up to ~509s and the 120s default was orphan-killing them; clamping would have made every slow task time out. Operator chose to lift the external ceiling and keep RES-03 (660s) as a clean-shutdown net just below it | ✓ Phase 3 — `cron.script_timeout_seconds: 720` in `~/.hermes/config.yaml` (outside repo; scheduler restart required), RES-03 budgets 660s |
| Repair RES-01 helper defects found in code review before shipping | The first implementation passed `capture_output=True` to `Popen` (TypeError on every call) and drained via `wait()`+`read()` (deadlock on large output); the regression test's fake `Popen` masked both | ✓ Phase 3 — fixed in `04f72c6`; real-child regression tests added; full suite green at baseline |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-22 after v1.0 Stability Hardening milestone close — archived to milestones/, tagged v1.0 (17/17 plans, 16/16 requirements validated; audit status tech_debt, no blockers)*
