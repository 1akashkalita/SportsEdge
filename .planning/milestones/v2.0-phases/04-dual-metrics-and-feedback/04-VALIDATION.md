---
phase: 04
slug: dual-metrics-and-feedback
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-22
---

# Phase 04 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.
> Derived from `04-RESEARCH.md` § Validation Architecture (lines 645–744).

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.0.3 (stdlib `unittest.TestCase` style — match existing `scripts/test_*.py`) |
| **Config file** | none — pytest auto-discovery from `scripts/` |
| **Quick run command** | `cd scripts && python3 -m pytest test_weekly_metrics.py -x` |
| **Full suite command** | `cd scripts && python3 -m pytest -x` |
| **Estimated runtime** | quick: ~5s · full suite: ~34 min (run only at phase end) |

---

## Sampling Rate

- **After every task commit:** Run `cd scripts && python3 -m pytest test_weekly_metrics.py -x`
- **After every plan wave:** Run the new-module test files for that wave (`test_weekly_metrics.py`, plus any `test_calibration.py` / `test_metrics_report.py` the planner creates)
- **Before `/gsd:verify-work`:** Full suite must be green (baseline is "2 failed, 202 passed" — the 2 known pre-existing `test_generate_projections.py` failures; no NEW failures permitted)
- **Max feedback latency:** ~5 seconds (quick run)

---

## Per-Task Verification Map

> Task IDs are assigned by the planner (step 8). Rows below are keyed by requirement + the
> concrete test class the executor must create. The planner MUST attach each row to the task
> that delivers it and the Nyquist auditor links task IDs post-planning.

| Requirement | Wave | Behavior | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|-------------|------|----------|------------|-----------------|-----------|-------------------|-------------|--------|
| METRICS-01 | 1 | Slip ROI aggregated by week×sport from per-sport workbooks, staked slips only (D-04/D-05) | — | N/A | unit | `python3 -m pytest test_weekly_metrics.py::TestSlipRoiAggregation -x` | ❌ W0 | ⬜ pending |
| METRICS-01 | 1 | Prop hit-rate aggregated from `Prop Accuracy` sheet (reuses `refresh_prop_accuracy` output) | — | N/A | unit | `python3 -m pytest test_weekly_metrics.py::TestPropHitRateAggregation -x` | ❌ W0 | ⬜ pending |
| METRICS-01 | 1 | WoW delta + ↑/→/↓ arrow renders for increasing / flat / decreasing ROI (D-03) | — | N/A | unit | `python3 -m pytest test_weekly_metrics.py::TestWowArrow -x` | ❌ W0 | ⬜ pending |
| METRICS-02 | 1 | Calibration formula: with ≥30 MOP-backed outcomes, factor steps toward target but ≤±0.05/cycle and stays in [0.85,1.20] (D-07/D-10) | — | N/A | unit | `python3 -m pytest test_weekly_metrics.py::TestCalibrationFormula -x` | ❌ W0 | ⬜ pending |
| METRICS-02 | 1 | Calibration gate: with <30 MOP-backed outcomes, factor stays exactly 1.0 (D-10/D-11) | — | N/A | unit | `python3 -m pytest test_weekly_metrics.py::TestCalibrationGateNotMet -x` | ❌ W0 | ⬜ pending |
| METRICS-02 | 2 | `generate_projections.py` reads `calibration.json` factor and applies `sigma_eff = estimate_sigma(...) * factor` (D-07) | T-04-01 | Corrupt/missing JSON → factor 1.0 (fail-safe) | unit | `python3 -m pytest test_weekly_metrics.py::TestSigmaInjection -x` | ❌ W0 | ⬜ pending |
| METRICS-03 | 2 | Running the calibration loop changes NO existing `Result` value (WIN/LOSS/PUSH/VOID) — verdict snapshot before/after (Design A) | — | N/A | unit | `python3 -m pytest test_weekly_metrics.py::TestIntegrityNoVerdictChange -x` | ❌ W0 | ⬜ pending |
| METRICS-03 | 2 | `calibration.py` never imports `evaluate_no_bet_gates` or grading code — AST structural check (Design B) | — | N/A | unit | `python3 -m pytest test_weekly_metrics.py::TestIntegrityNoGateImport -x` | ❌ W0 | ⬜ pending |
| METRICS-03 | 2 | `evaluate_no_bet_gates` output unchanged for a fixed pick fixture regardless of `calibration.json` (Design C, defensive) | — | N/A | unit | `python3 -m pytest test_weekly_metrics.py::TestIntegrityGateOutput -x` | ❌ W0 | ⬜ pending |
| METRICS-02 (D-10) | 1 | Factor clamped to [0.85,1.20] and moves ≤±0.05 even with extreme inputs (all wins / all losses) | T-04-01 | Clamp validation before use | unit | `python3 -m pytest test_weekly_metrics.py::TestCalibrationBounds -x` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

**Recommended integrity-proof combination (from research):** Design A (verdict snapshot) + Design B (AST import check). Design A is the runtime proof; Design B is the cheap structural proof. Design C is defensive/redundant once the architecture (sigma factor affects only *future* projections, never stored probabilities) is confirmed.

---

## Wave 0 Requirements

- [ ] `scripts/test_weekly_metrics.py` — stubs for METRICS-01 / METRICS-02 / METRICS-03 test classes above
- [ ] `scripts/calibration.py` — new module scaffold (stub functions + docstrings): `load_calibration_factor`, `compute_and_update_calibration`
- [ ] `scripts/metrics_report.py` — new module scaffold (or runner functions, planner's discretion per D-12)
- [ ] No framework install needed — pytest 9.0.3 already present

*`data/research/calibration.json` is created on first task run, NOT in Wave 0.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Telegram digest actually delivers + renders | METRICS-01 (D-01) | External side effect (Telegram API); creds-gated, degrades to no-op | Run `cd scripts && python3 sports_system_runner.py --task weekly_metrics`; confirm digest message arrives in the home channel |
| Obsidian weekly-recap note written + synced | METRICS-01 (D-01) | External side effect (iCloud Obsidian vault via `obsidian_sync`) | After the task run, confirm the weekly-recap note exists under the SportsEdge vault Recaps folder with ROI/hit-rate by week×sport |
| Cron schedule entry added | METRICS-01 (D-02) | Cron schedule lives in `~/.hermes` outside the repo — operator action | Operator adds the Monday-morning `weekly_metrics` cron entry; note this in the phase SUMMARY |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (`test_weekly_metrics.py`, `calibration.py`, `metrics_report.py`)
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s (quick run)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
