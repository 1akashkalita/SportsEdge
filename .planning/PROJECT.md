# Hermes Sports Automation — Stability Hardening

## What This Is

The Hermes sports-betting automation is an existing, in-use Python system that runs as unattended cron jobs: it fetches DFS player props and sportsbook game lines for NBA + MLB, runs every candidate pick through a fixed "no-bet gate" gauntlet, persists results to per-sport Excel workbooks, and pushes Telegram alerts + Obsidian vault notes. **This milestone is a reliability-hardening pass on that system** — diagnose and eliminate the cron-job timeouts, kill the bug causing the recurring `❌ SPORTS TASK FAILED … [Errno 32] Broken pipe`, and get every task and pipeline running dependably on schedule. It is for the system's single operator (the author), who needs to trust the automation before improving the model.

## Core Value

Every cron job and pipeline runs correctly on schedule — no timeouts, no task-failure alerts — so the operator can stop babysitting it and confidently move on to model/accuracy work next.

## Current Milestone: v3.0 Local Dashboard

**Goal:** A `localhost` web dashboard so the operator can *see* the whole system at a glance — today's props/picks by platform & sport (with +EV and probabilities), all slips with why-they're-paired insight, and win/loss history overall + per sport — plus a few safe actions, without touching any betting logic.

**Why now:** v1.0 made the pipeline reliable and v2.0 made measurement trustworthy. Everything the operator needs to judge the system now lives in Excel workbooks, JSON artifacts, Obsidian, and Telegram — with no single place to view it. A dashboard is low-risk (almost entirely a read-layer over already-persisted data) and is the surface for the project's core value: "can I tell whether the model is improving." It is the first of a 4-milestone post-v2.0 arc and is intentionally sequenced *before* the model work so the operator has a window into the data the later milestones produce.

**Target features:**
- **Today view:** props/picks grouped by platform & sport with +EV, model probability, edge, confidence; filter by platform/sport, sort by EV.
- **Slips view:** all slips (status, payout, legs) with "why paired" insight — surfaced from the Correlated Parlays `Reasoning`/`Correlation Group`, derived for general slips.
- **History view:** W/L overall + per sport, bankroll/ROI time-series chart, per-confidence-tier breakdown.
- **Safe actions (guarded writes):** refresh/re-run a task via subprocess (lock-aware, async), mark a slip placed, add a note — additive columns via atomic save; never touches gate logic / grades / EV / exposure.
- **Tech foundation:** Flask/Jinja + openpyxl `read_only` + Chart.js/Pico.css via CDN, bound to `127.0.0.1`, launched via `python3 dashboard.py`; first task verifies Flask imports on Python 3.14.0a2 (stdlib `http.server` fallback).

*(Spec approved & committed: `docs/superpowers/specs/2026-06-23-localhost-dashboard-design.md`. Roadmap context — M2 model accuracy & calibration, M3 line-change re-eval, M4 live in-game — in `docs/superpowers/specs/2026-06-23-model-accuracy-calibration-design.md`.)*

## Current State

**Shipped v1.0 — Stability Hardening (2026-06-22):** 5 phases / 17 plans, 16/16 v1 requirements satisfied. The broken-pipe `TASK FAILED` is eliminated, cron timeouts are root-caused and bounded (660s SIGALRM budget under a 720s cron ceiling), and a resilience + observability + CI safety net guards every fix. Milestone audit: `tech_debt` (no blockers). Outstanding before the system is fully "trusted in production": 5 live-environment human-UAT confirmations + optional Nyquist/hardening follow-ups (see STATE.md → Deferred Items). **Next milestone:** model/accuracy work — the explicit "after stability" goal — once the live UAT confirms the hardening on the real cron host. Start with `/gsd-new-milestone`.

**v2.0 — Slips & Props Tracking (in progress):** Phase 1 (trustworthy results) and Phase 2 (slip reconstruction + grading) are complete; **Phase 3 — Slips-Only Bankroll is complete (2026-06-22).** The bankroll ledger is now sourced exclusively from DFS slip Net PnL with confidence-scaled stakes (`stake_sizing.confidence_stake`), the prop→bankroll coupling is severed (`sync_slip_bankroll` owns `bankroll.json` / Daily Log / Bankroll Chart Data and runs on the daily grade path), prop W/L is preserved as a separate `Prop Accuracy` sheet, the Gate-8 *global* exposure caps were removed (concentration caps + the no-bet gauntlet preserved unchanged), and the historical ledger was rebased from inception (2026-06-08) onto a slips-only basis (100 → 126.778, idempotent, backed up). **Phase 4 — Dual Metrics and Feedback is complete (2026-06-23), closing the v2.0 milestone (4/4 phases this milestone).** A read-only `metrics_report.py` surfaces slip ROI + prop hit-rate by ISO-week × sport (Telegram digest + Obsidian recap); a bounded per-sport sigma-calibration engine (`calibration.py`, ±0.05/cycle, [0.85,1.20] clamp, ≥30 MOP-backed-outcome gate, data-fingerprint-idempotent) feeds realized outcomes back into projection sigma; and the feedback loop is integrity-locked — AST-isolated from gates/grading and proven by verdict-snapshot + gate-output tests to never alter a graded verdict or gate result. Outstanding before fully "trusted in production": 3 live-environment human-UAT items (live `weekly_metrics` delivery, `calibration.json` real-data check, operator Monday cron entry). **Phase 04.1 — Close v2.0 Audit Gaps is complete (2026-06-23):** the four functional gaps from the v2.0 milestone audit are closed in production — confidence staking is now applied live on the daily slip-build path (`build_slips.main()` reads `bankroll.json` and applies `apply_confidence_stakes` per category, with a money-safe literal-1.0 fallback; the BANKROLL-02 forward path is no longer flat-staked), `Prop Accuracy` is refreshed on the daily `sync_slip_bankroll` path (weekly metrics no longer stale; `weekly_metrics` stays read-only), `load_calibration_factor` is de-duplicated to a single canonical copy in `calibration.py`, and a persistent `weekly_metrics` partial is now visibly surfaced (degraded Telegram digest + `run_log.jsonl` status + repeated-partial OBS-03 alert) instead of silently reading green — verified 10/10 must-haves with zero new test failures and no gate/verdict/schema changes. The two remaining v2.0 audit items (RESULTS-07, SLIPS-03 verification debt) are routed to `/gsd-verify-work 1` and `/gsd-verify-work 2`.

**v2.0 SHIPPED (2026-06-24).** RESULTS-07 and SLIPS-03 verification debt is closed — Phase 1 verified 5/5 (`01-VERIFICATION.md`) and Phase 2 verified 4/4 (`02-VERIFICATION.md`, SLIPS-03 backfill confirmed: 88 slips / 12 dates / 0 duplicate keys). **18/18 v2.0 requirements satisfied**; milestone audit status `resolved` (all functional gaps closed by Phase 04.1 + this verification). Archived to `milestones/v2.0-*`, tagged `v2.0`. Acknowledged deferred tech-debt: Nyquist VALIDATION across phases + 3 live human-UAT items. **Next milestone = model / accuracy work** — the explicit "after trustworthy measurement" goal. Start with `/gsd-new-milestone`.

**v3.0 Local Dashboard — Phase 1 (Foundation & Data Layer) complete (2026-06-24).** The Flask-on-3.14.0a2 tech choice (D-06) is proven live, so the stdlib `http.server` fallback stays documented-only. `scripts/dashboard.py` launches a one-command localhost server bound to **127.0.0.1 only** (port 8787, overridable via `--port`/`DASHBOARD_PORT`, browser auto-open, `use_reloader=False`); `scripts/dashboard_data.py` is a strictly read-only data layer (JSON-first + `read_only=True/data_only=True` workbook reads that leave source bytes byte-identical) that tolerates a mid-write atomic swap by returning last-known-good without raising (D-01), matches the runner's naive-local `today_str()` (D-02), and derives the updating-badge/last-updated signals from live+fresh cooperative-lock pids; the dark Pico.css shell (`templates/base.html` + `index.html`) renders the extensible nav with reserved Calibration/Line-changes/Live stubs and autoescape-on. **DASH-01..04 verified 8/8 must-haves; code-review blocker CR-01 resolved (narrowed exception handler).** Pending: 2 live human-UAT items (browser visual shell, off-box network-isolation curl) tracked in `01-HUMAN-UAT.md`. **Next: Phase 2 — Read Views** (`/gsd-discuss-phase 2`).

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
- ✓ Dual metrics + bounded feedback loop — `metrics_report.py` surfaces slip ROI + prop hit-rate by ISO-week × sport with WoW arrows via Telegram + Obsidian (METRICS-01); a bounded per-sport sigma-calibration engine (`calibration.py`: ≥30 MOP-backed-outcome gate, ±0.05/cycle step, [0.85,1.20] clamp, data-fingerprint idempotent) injects a factor into projection sigma in `build_projection` (METRICS-02); the loop is integrity-locked — AST-isolated from gates/grading and proven by verdict-snapshot + gate-output tests to never alter a graded verdict or gate result (METRICS-03) — Phase 4 (v2.0) (78 tests incl. 2 post-review calibration-math fixes WR-01/WR-02; live delivery + real-data calibration + Monday cron pending human UAT)

### Active

<!-- This milestone (v3.0 Local Dashboard). Hypotheses until shipped and validated. See REQUIREMENTS.md for REQ-IDs. -->

- Operator can launch a localhost dashboard with one command and view today's props/picks by platform & sport with +EV, model probability, edge, and confidence
- Operator can view all slips with status/payout/legs and a "why these legs are paired" insight
- Operator can view win/loss history overall and per sport, plus a bankroll/ROI chart and per-confidence-tier breakdown
- Operator can trigger safe actions from the dashboard (refresh/re-run a task, mark a slip placed, add a note) without affecting gate logic, grades, EV, or exposure
- Dashboard reads existing persisted data without corrupting it and uses an additive-only, atomic write path for its safe actions

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
*Last updated: 2026-06-24 — v3.0 "Local Dashboard" Phase 1 (Foundation & Data Layer) COMPLETE: one-command 127.0.0.1-only Flask shell + read-only lock-tolerant data layer, DASH-01..04 verified 8/8, CR-01 resolved, 2 live human-UAT items pending (01-HUMAN-UAT.md). Next: Phase 2 Read Views. Prior: 2026-06-24 — v3.0 "Local Dashboard" milestone STARTED (first of a 4-milestone post-v2.0 arc: dashboard → calibration → line-change re-eval → live in-game; design docs in docs/superpowers/specs/). Prior: 2026-06-24 — v2.0 "Slips & Props Tracking" milestone CLOSED (5 phases / 24 plans, 18/18 requirements; P1+P2 formally verified, RESULTS-07/SLIPS-03 debt closed; archived + tagged v2.0). Prior: 2026-06-23 after v2.0 Phase 04.1 (Close v2.0 Audit Gaps) complete — forward confidence staking now live (BANKROLL-02 forward path), daily Prop-Accuracy refresh, calibration dedup, and WR-03 partial visibility shipped; 10/10 must-haves verified, zero new test failures. RESULTS-07/SLIPS-03 verification debt routed to /gsd-verify-work. Prior: v2.0 Phase 4 (Dual Metrics and Feedback) complete — closes the v2.0 milestone (METRICS-01..03 validated; 3 live human-UAT items pending). Prior: v2.0 Phase 3 (Slips-Only Bankroll) complete — bankroll rebased to a slips-only basis from 2026-06-08 (BANKROLL-01..04 validated). Prior: v1.0 Stability Hardening milestone close — archived to milestones/, tagged v1.0 (17/17 plans, 16/16 requirements validated; audit status tech_debt, no blockers)*
