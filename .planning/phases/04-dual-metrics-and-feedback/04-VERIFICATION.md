---
phase: 04-dual-metrics-and-feedback
verified: 2026-06-23T07:42:51Z
status: passed
human_verified: 2026-06-23T08:06:00Z
human_verified_note: "All 3 human-verification items confirmed via /gsd:verify-work (04-HUMAN-UAT.md, 3/3 pass): live weekly_metrics Telegram+Obsidian delivery, calibration.json real-data check, and the Monday cron entry (added to system crontab as HERMES_SPORTS_WEEKLY_METRICS, 0 8 * * 1)."
score: 3/3
overrides_applied: 0
human_verification:
  - test: "Run python3 sports_system_runner.py --task weekly_metrics from scripts/ against real workbook data"
    expected: "Telegram message arrives in the operator's sports channel with the current ISO-week, slip ROI%, hits%, WoW arrows, and zero-stake count line; an Obsidian note is created/overwritten at the weekly-recap path with the By Sport table and an Adjustments-for-Next-Week section containing the calibration note"
    why_human: "Telegram delivery and Obsidian sync both require live credentials, a running Obsidian vault, and a populated master_pnl.xlsx / per-sport workbooks — cannot be verified programmatically without real infrastructure"
  - test: "Verify calibration.json is created on first weekly_metrics run with correct structure"
    expected: "data/research/calibration.json exists after the first run, contains {version, updated_at, inception_date, factors:{NBA:float, MLB:float}, audit:[...]}; re-running produces a second audit entry and the factor advances by at most 0.05"
    why_human: "Requires a populated master_pnl.xlsx Pick History with graded PROP rows since 2026-06-08; absent from test environment"
  - test: "Add Monday-morning cron entry to ~/.hermes for weekly_metrics task"
    expected: "Cron entry of the form: 0 8 * * MON cd <scripts_dir> && /usr/local/bin/python3 sports_system_runner.py --task weekly_metrics is present in ~/.hermes cron config"
    why_human: "Cron entry lives outside the repo (D-02); operator must add it manually; verifier cannot read/modify ~/.hermes"
---

# Phase 4: Dual Metrics and Feedback — Verification Report

**Phase Goal:** The operator can answer "is the model improving?" from data — slip ROI and prop hit-rate are surfaced over time by week and sport, and realized outcomes flow back into projection/gate tuning through a bounded, integrity-safe feedback loop.
**Verified:** 2026-06-23T07:42:51Z
**Status:** human_needed (3/3 truths VERIFIED by code; 3 human items require live-run confirmation)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A report (Telegram message or Obsidian note) shows slip ROI and prop hit-rate broken down by week and by sport (NBA/MLB). | VERIFIED | `metrics_report.py` (526 lines) implements `aggregate_slip_roi_by_week_sport` (staked-only Σ Net PnL / Σ Stake per ISO-week × sport), `read_prop_hit_rate_by_week_sport` (Prop Accuracy sheet), `build_weekly_report` (WoW deltas + arrows, no verdict line), `format_telegram_digest`, and `fill_obsidian_recap_markdown`. 32/32 `test_metrics_report.py` tests pass. `weekly_metrics_task()` is wired in `run_task` and calls both delivery surfaces. |
| 2 | Realized slip and prop outcomes feed back into the projection or gate configuration in a bounded, observable way — at least one tunable parameter is updated by outcomes. | VERIFIED (with advisory) | `calibration.py` reads Pick History PROP WIN/LOSS rows, computes a per-sport sigma scaler via a formula with ±0.05 step clamp and [0.85, 1.20] range clamp, writes atomically to `data/research/calibration.json`. `generate_projections.py` calls `load_calibration_factor(sport)` inside `build_projection`, multiplying sigma before `model_over_probability`. 39/39 `test_weekly_metrics.py` tests pass. **Advisory (from code review, not blockers):** WR-01 gates on `n_outcomes` (wins+losses) while `model_implied` is computed over `n_with_mop` (MOP-backed subset only) — populations diverge when MOP coverage is partial, biasing `raw_ratio`. WR-02 re-running the task on the same data advances the factor by another ±0.05 — the docstring's idempotency claim is false. Both warnings affect calibration math accuracy but NOT the hard numeric bounds or observability (audit log in `calibration.json`). |
| 3 | The feedback loop cannot retroactively alter any graded verdict (WIN/LOSS/PUSH/VOID) and cannot modify no-bet gate logic or pick output verdicts — confirmed by a test. | VERIFIED | Three independent integrity proofs all pass: (A) `TestIntegrityNoVerdictChange` — 36-row in-memory workbook, verdict snapshot before == after `compute_and_update_calibration`; MLB factor changed proves loop actually ran. (B) `TestIntegrityNoGateImport` — AST walk of `calibration.py` confirms no import of `evaluate_no_bet_gates`, `grade_slips`, or `sports_system_runner`. (C) `TestIntegrityGateOutput` — `evaluate_no_bet_gates(pick, {})` called twice with different `calibration.json` content returns identical `(ok, skipped, passed)` tuple. |

**Score:** 3/3 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `scripts/calibration.py` | compute_calibration_target, read_graded_outcomes_for_sport, compute_and_update_calibration, load_calibration_factor, write_calibration_json; min 120 lines | VERIFIED | 343 lines; all 5 functions present; constants N_GATE=30, MAX_STEP=0.05, CLAMP_LO=0.85, CLAMP_HI=1.20, INCEPTION_DATE="2026-06-08" confirmed at runtime. |
| `scripts/test_weekly_metrics.py` | TestCalibrationFormula, TestCalibrationGateNotMet, TestCalibrationBounds, TestIntegrityNoGateImport, TestSigmaInjection, TestIntegrityNoVerdictChange, TestIntegrityGateOutput; min 80 lines | VERIFIED | 660 lines; all 7 active test classes collect and pass (39 passed, 3 expected skips for Plan 02 stubs). |
| `data/research/calibration.json` | Per-sport sigma scaler state; created on first compute_and_update_calibration run | VERIFIED (design) | Module writes atomically via `.json.tmp` + `os.replace`; `write_calibration_json` and `load_calibration_factor` tested; file is created at runtime (not pre-created — correct per plan spec). |
| `scripts/metrics_report.py` | aggregate_slip_roi_by_week_sport, read_prop_hit_rate_by_week_sport, wow_arrow, build_weekly_report, format_telegram_digest, fill_obsidian_recap_markdown; min 140 lines | VERIFIED | 526 lines; all 6 functions present; imports cleanly with no sports_system_runner import. |
| `scripts/test_metrics_report.py` | TestSlipRoiAggregation, TestPropHitRateAggregation, TestWowArrow, TestZeroStakeSeparation; min 90 lines | VERIFIED | 501 lines; 32/32 tests pass across 6 test classes (includes TestFormatTelegramDigest, TestFillObsidianMarkdown beyond plan spec). |
| `scripts/generate_projections.py` | load_calibration_factor + sigma injection in build_projection | VERIFIED | `load_calibration_factor` at line 277; sigma injection at lines 416-419 (`cal_factor = load_calibration_factor(sport)` + `sigma = sigma * cal_factor`); `model_over_probability` and `estimate_sigma` bodies unchanged (confirmed by TestSigmaInjection). |
| `scripts/sports_system_runner.py` | weekly_metrics task wiring in TASK_TIMEOUTS, task_workbook_paths, run_task; weekly_metrics_task() function | VERIFIED | TASK_TIMEOUTS["weekly_metrics"]=660; task_workbook_paths("weekly_metrics") returns [master_pnl.xlsx]; run_task mapping contains "weekly_metrics": lambda: weekly_metrics_task(); weekly_metrics_task() callable — confirmed programmatically. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `calibration.py compute_and_update_calibration` | `data/research/calibration.json` | atomic `.json.tmp` + `os.replace` | WIRED | `os.replace(tmp, path)` at calibration.py:275; TestIntegrityNoGateImport test_write_calibration_json_atomic_no_tmp_left PASSES. |
| `calibration.py read_graded_outcomes_for_sport` | `data/pnl/master_pnl.xlsx Pick History` | `safe_load_workbook` + header-name column lookup for `Model Over Probability` | WIRED | Pattern confirmed at calibration.py:162-207; `"Model Over Probability"` resolved by header-map lookup; PUSH/VOID excluded. |
| `generate_projections.py build_projection` | `data/research/calibration.json` | `load_calibration_factor(sport)` at call time; `sigma *= factor` | WIRED | Injection confirmed at lines 416-419; read at call time (anti-pattern avoided); TestSigmaInjection::test_mlb_factor_loaded_correctly PASSES. |
| `sports_system_runner.py run_task` | `weekly_metrics_task` | `run_task` mapping + `TASK_TIMEOUTS` + `task_workbook_paths` | WIRED | All three wiring points confirmed by runtime bootstrap check. |
| `sports_system_runner.py weekly_metrics_task` | Telegram + Obsidian | `send_telegram(format_telegram_digest(...))` + `obsidian_sync(fill_obsidian_recap_markdown(...))` | WIRED (code; unverifiable without live credentials) | Both delivery calls present at lines 7339 and 7348; both wrapped in try/except; Obsidian bypass of `path.exists` guard confirmed. |
| `metrics_report.py aggregate_slip_roi_by_week_sport` | `data/nba/nba_*.xlsx + data/mlb/mlb_*.xlsx Slip History` | per-sport workbook glob + `SLIP_HISTORY_HEADERS` index lookup | WIRED | Pattern confirmed at metrics_report.py:126-194; "Slip History" sheet check at line 137; SLIP_HISTORY_HEADERS.index() used for all column lookups. |
| `metrics_report.py read_prop_hit_rate_by_week_sport` | `data/pnl/master_pnl.xlsx Prop Accuracy` | `PROP_ACCURACY_HEADERS` read; column-name lookup | WIRED | Pattern confirmed at metrics_report.py:201-254; header-name lookup; returns {} on missing sheet. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `calibration.py` | `new_factor` (per-sport sigma scaler) | master_pnl.xlsx Pick History via `safe_load_workbook` | Yes — reads real graded PROP rows with WIN/LOSS + MOP; clamped formula (WR-01 population caveat noted) | FLOWING (with advisory on math accuracy — see WR-01 in Warnings) |
| `metrics_report.py` | `roi_agg`, `prop_rates` | per-sport workbooks (Slip History) + master_pnl (Prop Accuracy) | Yes — reads real staked slips with Net PnL/Stake and persisted hit-rate | FLOWING |
| `generate_projections.py build_projection` | `sigma` (calibrated) | `data/research/calibration.json` via `load_calibration_factor` | Yes — reads written calibration.json; neutral 1.0 fallback if absent | FLOWING |
| `sports_system_runner.py weekly_metrics_task` | Telegram digest + Obsidian markdown | `metrics_report.build_weekly_report` output | Yes — strings produced by real aggregation functions | FLOWING (delivery confirmed in code; live delivery is human-verification item) |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| calibration.py imports cleanly | `python3 -c "import calibration"` | Clean — no runner side effects | PASS |
| metrics_report.py imports cleanly | `python3 -c "import metrics_report"` | Clean — no sports_system_runner import | PASS |
| generate_projections.py imports cleanly | `python3 -c "import generate_projections"` | Clean | PASS |
| Runner wiring: TASK_TIMEOUTS, callable, workbook paths | Bootstrap verification command | TASK_TIMEOUTS["weekly_metrics"]==660, callable, paths=[master_pnl.xlsx] | PASS |
| AST integrity: calibration.py imports no gate/grading code | `ast.walk` scan | Clean — evaluate_no_bet_gates / grade_slips / sports_system_runner absent | PASS |
| WR-01 population mismatch is real | `compute_calibration_target(15, 15, [0.9]*3, 1.0)` with n_outcomes=30, n_with_mop=3 | new_factor=1.05 — factor moved on 3-sample model estimate | CONFIRMED (advisory) |
| WR-02 double-step is real | Two identical calls with prev_factor from run 1 | Run 1: 1.0→1.05; Run 2: 1.05→1.10 | CONFIRMED (advisory) |

### Probe Execution

No probe scripts declared or present for this phase (`scripts/*/tests/probe-*.sh` not found). Step 7c: SKIPPED — no declared probes.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| METRICS-01 | 04-02-PLAN.md, 04-03-PLAN.md | A report aggregates slip ROI and prop hit-rate by ISO-week × sport so "improving vs stagnant" is answerable from data | SATISFIED | `metrics_report.py` produces week×sport ROI + hit-rate; `weekly_metrics_task` delivers via Telegram + Obsidian; 32 test_metrics_report.py tests pass. |
| METRICS-02 | 04-01-PLAN.md, 04-03-PLAN.md | Realized slip/prop outcomes feed back into projection/gate tuning via a bounded feedback loop | SATISFIED (with advisory) | `calibration.py` computes per-sport sigma scaler from Pick History; `generate_projections.py` applies it at sigma time; bounds enforced (±0.05 step, [0.85,1.20] clamp). WR-01/WR-02 advisory warnings noted. |
| METRICS-03 | 04-01-PLAN.md (AST), 04-03-PLAN.md (Design A+C) | The feedback loop is safe — cannot retroactively change graded verdicts or gate output | SATISFIED | Three-design proof: AST import check (Design B) + verdict snapshot test (Design A) + gate-output determinism test (Design C); all 14 integrity tests pass. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `scripts/calibration.py` | 72 | Gates on `n_outcomes` (wins+losses), not `n_with_mop`; `empirical` and `model_implied` use different populations | Warning (WR-01 from code review) | Can bias raw_ratio and move the factor on a small MOP sample while claiming a 30-sample guarantee. Numeric bounds still hold. |
| `scripts/calibration.py` | 288 | Docstring claims idempotency ("running twice on unchanged data is idempotent") that is empirically false — same data re-runs step the factor again | Warning (WR-02 from code review) | Operator re-running weekly_metrics the same week double-steps the sigma factor without new data. The ±0.05 step clamp and [0.85,1.20] clamp still hold. |
| `scripts/sports_system_runner.py` | 7309, 7331 | `result["status"] = "partial"` on calibration/aggregation failure exits 0; the existing `trailing_failure_streak` counter never sees these; silent dead feedback loop | Warning (WR-03 from code review) | A persistently failing calibration phase would show green exits in run logs, invisible to the operator. |
| `scripts/calibration.py` | 26 | `INCEPTION_DATE = "2026-06-08"` duplicated across calibration.py, metrics_report.py, sports_system_runner.py | Info (IN-01 from code review) | Three independent edits required if the operator re-baselines; silent drift risk. |
| `scripts/metrics_report.py` | 132 | `safe_load_workbook` called in loop with no `wb.close()` | Info (IN-02 from code review) | File descriptor leak; operationally safe given macOS fd limits but fragile at default `ulimit -n`. |

No TBD/FIXME/XXX debt markers found in any phase-4 modified files.

### Human Verification Required

#### 1. Live weekly_metrics task delivery

**Test:** Run `cd scripts && python3 sports_system_runner.py --task weekly_metrics` with real credentials and a populated workbook.
**Expected:** Telegram message arrives in the operator's sports channel containing the current ISO-week, slip ROI% with arrow, prop hits% with arrow, zero-stake informational count, and a calibration note. An Obsidian note is created/overwritten at the weekly-recap path containing the By Sport table and Adjustments-for-Next-Week section.
**Why human:** Telegram delivery and Obsidian sync require live `TELEGRAM_BOT_TOKEN`, `TELEGRAM_HOME_CHANNEL`, and a populated `master_pnl.xlsx` + per-sport workbooks — not available in the test environment.

#### 2. calibration.json created and updated correctly on real data

**Test:** After running `weekly_metrics`, inspect `data/research/calibration.json`.
**Expected:** File exists with structure `{version:1, inception_date:"2026-06-08", factors:{NBA:float, MLB:float}, audit:[...]}`. If graded PROP rows with MOP are present (≥30 per sport), the factor differs from 1.0. If data is insufficient (per WR-01 caveat, this means ≥30 MOP-backed rows, not just 30 WIN/LOSS rows), the audit entry shows `"reason": "gate not met"` with the actual counts.
**Why human:** Requires real `master_pnl.xlsx` with graded PROP history since 2026-06-08.

#### 3. Operator must add Monday-morning cron entry in ~/.hermes

**Test:** Verify a cron entry exists in `~/.hermes` scheduling `weekly_metrics` every Monday morning.
**Expected:** Entry of the form: `0 8 * * MON cd <scripts_dir> && /usr/local/bin/python3 sports_system_runner.py --task weekly_metrics`
**Why human:** Cron entry lives outside the repo (D-02 constraint); operator must add it manually; cannot be verified or created by the verifier.

### Gaps Summary

No hard gaps. All 3 must-have success criteria are verified in the codebase. The 3 items in the Human Verification section are practical live-run confirmations that require credentials and real data — they are normal human-verification items, not code defects.

**Known advisory findings from code review (not blockers):**
1. **WR-01** — Calibration gate/population mismatch (n_outcomes vs n_with_mop) may bias the sigma factor in sparse-MOP scenarios. The numeric bounds still hold. The review recommends gating on `n_with_mop` and computing `empirical` over the same MOP-backed population.
2. **WR-02** — Double-step on same-week re-run. The docstring idempotency claim is false. The factor advances by ±0.05 on every invocation regardless of new data. The clamped bounds prevent runaway, but the claim of "one step per data window" requires the operator to ensure the cron job runs once per Monday.
3. **WR-03** — Persistent `status:"partial"` is invisible to `trailing_failure_streak` — the operator would get green exits while the feedback loop is silently dead.

These are documented in the REVIEW.md. None breach the integrity contract (SC#3) or prevent the goal from being observably true. They are accuracy/observability improvements recommended for a follow-on fix cycle.

---

_Verified: 2026-06-23T07:42:51Z_
_Verifier: Claude (gsd-verifier)_
