---
phase: 04
slug: dual-metrics-and-feedback
status: secured
threats_total: 12
threats_closed: 12
threats_open: 0
asvs_level: 2
created: 2026-06-23
audited: 2026-06-23
auditor: gsd-security-auditor
register_authored_at_plan_time: true
---

# Phase 04 — Security: Dual Metrics and Feedback

> Per-phase security contract: threat register, accepted risks, and audit trail.
> Register authored at plan time (04-01/02/03-PLAN.md `<threat_model>`); auditor verified each mitigation exists in the implementation (verify-mitigations mode, not retroactive STRIDE).

**Audit Date:** 2026-06-23 · **ASVS Level:** 2 · **Auditor:** gsd-security-auditor · **Result:** SECURED (12/12 closed)

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| filesystem → calibration.py / generate_projections.py | `data/research/calibration.json` is read/written; a tampered/partial/out-of-range file is untrusted input | per-sport sigma factor (float) |
| filesystem → metrics_report.py | reads per-sport workbooks + master_pnl.xlsx (possibly half-written during a concurrent daily run) | graded slip/prop rows (read-only) |
| outcomes → selection | the ONLY coupling is calibration.json → projection sigma; the gate gauntlet and graded sheets are downstream-isolated by design (D-13) | sigma scaler (float, clamped) |
| weekly_metrics task → external | side-effecting Telegram/Obsidian delivery that must degrade to no-op, never crash the task | ROI % / hit-rate digest text |

---

## Threat Register

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T-04-01 | Tampering — load_calibration_factor | mitigate | CLOSED | `calibration.py:258-266` & `generate_projections.py:285-293`: reads wrapped in `try/except → return 1.0`; path built at call time, never import time (AST-confirmed). |
| T-04-02 | Input Validation (V5) — factor value | mitigate | CLOSED | `calibration.py:263` `max(CLAMP_LO,min(CLAMP_HI,raw))`; `generate_projections.py:290` `max(0.85,min(1.20,raw))`. Tested: `test_load_calibration_factor_clamps_out_of_range`, `test_out_of_range_factor_clamped_to_upper_bound`. |
| T-04-03 | Tampering — partial write | mitigate | CLOSED | `calibration.py:323-325` `.json.tmp` + `os.replace(tmp,path)`. Tested: `test_write_calibration_json_atomic_no_tmp_left`. |
| T-04-04 | Denial of Service — unbounded audit | mitigate | CLOSED | `calibration.py:308` `audit = audit[-52:]`. Tested: `test_write_calibration_json_trims_audit_to_52`. |
| T-04-05 | Tampering/Elevation — forbidden imports | mitigate | CLOSED | AST scan: `calibration.py` imports only `json, os, datetime, pathlib, typing.Any, workbook_io`; no `evaluate_no_bet_gates` / `grade_slips` / `sports_system_runner`. 3 `TestIntegrityNoGateImport` methods assert structurally. |
| T-04-06 | Tampering — half-written workbook | mitigate | CLOSED | `metrics_report.py:132,220` `safe_load_workbook(read_only=True, data_only=True)` with `except: continue`; short/malformed rows skipped at `:143`; absent sheet → SKIP. |
| T-04-07 | Information Disclosure — Telegram digest | accept | CLOSED | Accepted risk (see log) — operator-only channel already receives all picks. |
| T-04-08 | Denial of Service — ~30 workbook opens | accept | CLOSED | Accepted risk (see log) — small read-only files, <5s, weekly cadence, under 660s budget. |
| T-04-09 | Tampering/Elevation — feedback loop alters verdict/gate | mitigate | CLOSED | (A) `TestIntegrityNoVerdictChange` verdict snapshot identical before/after calibration (MLB factor moved → loop ran); (B) AST scan no forbidden imports; (C) `TestIntegrityGateOutput` + source scan: `evaluate_no_bet_gates` references neither `calibration.json` nor `load_calibration_factor` and returns identical `(ok,skipped,passed)`. Sigma injection at `generate_projections.py:416-419` is upstream of the gauntlet; the gate reads stored `model_over_probability`, not the factor. |
| T-04-10 | Denial of Service — 660s budget | mitigate | CLOSED | `sports_system_runner.py:143` `TASK_TIMEOUTS["weekly_metrics"]=660`. Read-only aggregation + 1 JSON write + 1 Telegram + 1 Obsidian. |
| T-04-11 | Denial of Service — delivery failure crashes task | mitigate | CLOSED | `sports_system_runner.py:7335-7342` (Telegram) & `:7345-7360` (Obsidian) in `try/except`; AST confirms `weekly_metrics_task` has zero `raise`, single `return result`. |
| T-04-SC | Tampering — package installs | accept | CLOSED | Accepted risk (see log) — no new third-party imports; stdlib + existing in-repo deps only. |

*Status: open · closed*

---

## Accepted Risks Log

| Threat ID | Category | Rationale | Accepted By |
|-----------|----------|-----------|-------------|
| T-04-07 | Information Disclosure — Telegram digest leaks ROI%, hit-rate | Low-value local operator data. The same Telegram channel already receives all picks, entry prices, and outcomes; weekly ROI/hit-rate are strictly less sensitive. No new attack surface. | Phase 04 threat register (04-02-PLAN.md) |
| T-04-08 | Denial of Service — iterating ~30 dated workbooks per weekly run | Files small, read-only, opened serially; <5s per RESEARCH §4, under the 660s budget; weekly cadence. | Phase 04 threat register (04-02-PLAN.md) |
| T-04-SC | Tampering — npm/pip/cargo supply-chain installs | No new third-party packages this phase. New modules use only stdlib + existing in-repo deps (`workbook_io`, `slip_payouts`, `openpyxl`). | Phase 04 threat register (04-01/02/03-PLAN.md) |

---

## Unregistered Flags

None. Both 04-01-SUMMARY.md and 04-03-SUMMARY.md `## Threat Flags` report no new network endpoints, auth paths, file-access patterns, or schema changes beyond the registered threat model. (04-03 notes the only new file I/O is reading `calibration.json` — an existing METRICS-02 design surface — and the existing `obsidian_sync` subprocess pattern.)

---

## Auditor Note — T-04-09 rigor

`TestIntegrityGateOutput.test_gate_output_identical_regardless_of_calibration_file` calls `evaluate_no_bet_gates` twice on the same pick dict without writing a differing `calibration.json` between calls (it asserts gate determinism). The load-bearing assertion is the companion source-scan test confirming `evaluate_no_bet_gates` has no reference to `calibration.json`/`load_calibration_factor`, plus the architecture: the gate reads the stored `model_over_probability` from the pick dict, while sigma injection only affects the projection output written upstream. The mitigation holds; a possible future hardening is to make that test write an extreme calibration.json between calls for belt-and-suspenders coverage.

---

## Implementation Notes

**Post-execution calibration math fix (commit eb6efcf, WR-01/WR-02):** Security mitigations unaffected. The fix corrected the MOP-backed population denominator (WR-01) and added a data-fingerprint idempotence guard (WR-02). All T-04-01..05 and T-04-09 controls verified present in the current (post-fix) code; the WR-01/WR-02 regression tests prove the math correction without altering any security boundary.

---

## Audit Trail

### Security Audit 2026-06-23
| Metric | Count |
|--------|-------|
| Threats found | 12 |
| Closed | 12 |
| Open | 0 |

*threats_open: 0*
