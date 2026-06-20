# Hermes Sports Automation — Stability Hardening

## What This Is

The Hermes sports-betting automation is an existing, in-use Python system that runs as unattended cron jobs: it fetches DFS player props and sportsbook game lines for NBA + MLB, runs every candidate pick through a fixed "no-bet gate" gauntlet, persists results to per-sport Excel workbooks, and pushes Telegram alerts + Obsidian vault notes. **This milestone is a reliability-hardening pass on that system** — diagnose and eliminate the cron-job timeouts, kill the bug causing the recurring `❌ SPORTS TASK FAILED … [Errno 32] Broken pipe`, and get every task and pipeline running dependably on schedule. It is for the system's single operator (the author), who needs to trust the automation before improving the model.

## Core Value

Every cron job and pipeline runs correctly on schedule — no timeouts, no task-failure alerts — so the operator can stop babysitting it and confidently move on to model/accuracy work next.

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

### Active

<!-- This milestone. Hypotheses until shipped and validated. -->

- [ ] Cron-job timeouts fully eliminated — the dominant contributors (Telegram retry loop, per-line Obsidian subprocess) were bounded in Phase 2 (FIX-02: 10s timeout + circuit-breaker, single task-end vault sync); the general hard self-timeout / `SIGPIPE` safety net lands in Phase 3
- [ ] Safety net added: retries/backoff on network calls, sane + hard timeouts, broken-pipe/`SIGPIPE` handling, and a regression test for each fix
- [ ] Observability added: structured run logs, a health/heartbeat check, and alerting on failure patterns
- [ ] CI runs the test suite to catch breakage before cron does

### Out of Scope

<!-- Explicit boundaries with reasoning to prevent re-adding. -->

- Model accuracy / projection-quality improvements — the explicit "after" goal; stability comes first
- New sports or new bet types — not part of stabilization
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
| Scope = full hardening (root-cause fixes + safety net + observability + CI) | Operator wants to fully trust the system before model work | — Pending |
| Fix only stability-threatening defects; no broad monolith refactor | "Stable before changing stuff" | — Pending |
| Defer all model/accuracy work to a later milestone | Build a reliable foundation first | — Pending |
| Definition of done = all cron jobs + pipelines run correctly (no timeouts, no task-failed alerts) | The operator's stated bar for "stable" | — Pending |
| Treat diagnosis as a first-class step (reproduce + root-cause before fixing) | The exact cause of the broken pipe is not yet pinned down | ✓ Phase 1 — `DIAGNOSIS.md`: broken pipe = bare `JSON_RESULT=` print in `main()` (`sports_system_runner.py:5634`/`:5640`); dominant timeout = `send_telegram()` retry loop (30s×2 per call site, 24,923s max observed), NOT stacked subprocess timeouts (ruled out) |
| Bound the diagnosed failure modes minimally rather than install the general safety net in the same phase | Fix the proven, dominant contributors first; defer retries/hard-timeouts/SIGPIPE to Phase 3 so regression tests cover the actual fix paths | ✓ Phase 2 — `safe_print` stdout sweep (FIX-01), `send_telegram` 10s timeout + per-invocation circuit-breaker, Obsidian decoupled to one task-end `sports_run_log` sync (FIX-02), duplicate defs removed (DEF-01), `Path.home()` base (DEF-02); live 11/11 task pass (FIX-03) |

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
*Last updated: 2026-06-20 after Phase 2 (Reliability Fixes + Defect Removal) completion*
