---
phase: 03
slug: safe-actions
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-24
---

# Phase 03 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Sourced from `03-RESEARCH.md` → "## Validation Architecture". Per-task IDs are
> finalized by the planner once PLAN.md waves exist.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | `pytest` 9.0.3 + `unittest.TestCase` (loaded via `importlib`, run from `scripts/`) |
| **Config file** | None — discovery by convention |
| **Quick run command** | `python3 -m pytest test_dashboard_actions.py -q` (from `scripts/`) |
| **Full suite command** | `python3 -m pytest -q` (from `scripts/`) |
| **Estimated runtime** | full suite ~34 min; quick file <10s — sample with targeted files, run full only at wave/phase gates |
| **Known pre-existing failures** | 2 in `test_generate_projections.py` (clean baseline; not introduced by this phase) |

---

## Sampling Rate

- **After every task commit:** `python3 -m pytest test_dashboard_actions.py test_dashboard.py test_dashboard_data.py -q`
- **After every plan wave:** `python3 -m pytest -q` (full suite from `scripts/`)
- **Before `/gsd:verify-work`:** Full suite green except the 2 known `test_generate_projections.py` failures
- **Max feedback latency:** ~10 seconds (quick file); full suite reserved for wave/phase gates

---

## Per-Task Verification Map

> Planner populates Task ID / Plan / Wave columns. The Requirement → Behavior →
> Command rows below come from research and are the required coverage floor.

| Req ID | Behavior | Test Type | Automated Command | File Exists |
|--------|----------|-----------|-------------------|-------------|
| ACTION-01a | `/action/refresh` POST with valid task triggers async subprocess (returns immediately, never inline) | integration | `pytest test_dashboard_actions.py::TestRefreshAction::test_refresh_triggers_subprocess -x` | ❌ W0 |
| ACTION-01b | `/action/refresh` refuses (flash warning) when runner `fcntl` lock held | unit | `pytest test_dashboard_actions.py::TestRefreshAction::test_refresh_refused_when_locked -x` | ❌ W0 |
| ACTION-01c | `/action/refresh` with task not in `ALLOWED_TASKS` whitelist is rejected | unit | `pytest test_dashboard_actions.py::TestRefreshAction::test_refresh_invalid_task_rejected -x` | ❌ W0 |
| ACTION-01d | `/api/status` returns `locked` + latest `run_log.jsonl` record for the task | unit | `pytest test_dashboard_actions.py::TestStatusEndpoint::test_status_fields -x` | ❌ W0 |
| ACTION-02 | `/action/mark-placed` adds `Placed`/`Placed At` columns additively, toggles correct row in `master_pnl.xlsx` | unit | `pytest test_dashboard_actions.py::TestMarkPlaced::test_mark_placed_additive -x` | ❌ W0 |
| ACTION-03 | `/action/add-note` writes `Operator Note` additively; grading `Notes` column untouched | unit | `pytest test_dashboard_actions.py::TestAddNote::test_add_note_additive -x` | ❌ W0 |
| ACTION-04a | `evaluate_no_bet_gates` output identical before/after a write action | unit | `pytest test_dashboard_actions.py::TestActionFourHardLine::test_mark_placed_does_not_alter_gate_output -x` | ❌ W0 |
| ACTION-04b | `PER_PLAYER_CAP` / `PER_GAME_CAP` unchanged after any write action | unit | `pytest test_dashboard_actions.py::TestActionFourHardLine::test_exposure_caps_unchanged -x` | ❌ W0 |
| ACTION-04c | Write actions only touch Slip History sheet (Picks/Skipped Picks/CLV unmodified) | unit | `pytest test_dashboard_actions.py::TestActionFourHardLine::test_write_only_touches_slip_history -x` | ❌ W0 |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `scripts/test_dashboard_actions.py` — RED stubs for all 9 cases above (ACTION-01..04)
- [ ] `scripts/dashboard_writes.py` — new module stub with correct function signatures (preserves the read-only contract on `dashboard_data.py`)
- [ ] `app.secret_key` wired in `dashboard.py` — required before `flash()` works (D-06 inline banner)

*Framework already installed (pytest 9.0.3) — no install needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Async refresh actually re-runs the board end-to-end and the board visibly updates | ACTION-01 | Spawns a real cron-style subprocess that hits live external APIs; not deterministic in CI | From `scripts/`, click Refresh → confirm; observe the "updating…" badge, then the Today board + `run_log.jsonl` reflect the new run |
| Mark-placed / note round-trip survives a real workbook save + reload in the running dashboard | ACTION-02/03 | End-to-end UI + atomic-save round-trip across a live `master_pnl.xlsx` | Mark a slip placed, add a note, reload `/slips` → values persist and toggle |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (`test_dashboard_actions.py`, `dashboard_writes.py`, `app.secret_key`)
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s (quick file)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
