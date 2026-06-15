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

### Active

<!-- This milestone. Hypotheses until shipped and validated. -->

- [ ] Cron-job timeouts are root-caused and eliminated — every task completes within a defined time budget
- [ ] The `[Errno 32] Broken pipe` failure (seen on `mlb_prop_monitor`) and any shared root cause are fixed — no more `❌ TASK FAILED` from it
- [ ] All 11 runner tasks and their pipelines run correctly end-to-end on schedule
- [ ] Stability-threatening defects fixed (duplicate `injury_monitor` / `clv_tracker` definitions; hardcoded `BASE` path in `generate_projections.py`)
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
*Last updated: 2026-06-15 after Phase 1 (Diagnosis) completion*
