# Milestones

## v2.0 Slips & Props Tracking (Shipped: 2026-06-24)

**Delivered:** The bankroll now reflects actual DFS slips instead of individual props; slips and props are both graded against trustworthy results, backfilled from inception (2026-06-08), and realized outcomes feed back into selection — so the operator can finally tell whether the model is improving.

**Phases completed:** 5 phases (1–4 + inserted 04.1), 24 plans, 35 tasks. 18/18 v2.0 requirements satisfied; all phases carry a passing VERIFICATION.md.

**Key accomplishments:**

- **Phase 1 — Trustworthy Results:** Hardened prop grading (4-tier `name_match` with abstain-on-ambiguity, MLB batting/pitching namespace split, explicit DIRECT/DERIVED/NOT-DERIVABLE disposition table) and attached `Result Source`/`Result Confidence` provenance to every graded row. The June 8–21 MANUAL-REVIEW backlog was recovered money-safely — June 8 dry-run gate cleared at 94.6% (RESULTS-07). Four gap closures: DNP→VOID detection, PrizePicks/Underdog Fantasy-Score derivation, an idempotent gate test, and prop PnL=0 (money realized only at slip level). Verified 5/5.
- **Phase 2 — Slip Reconstruction and Grading:** `build_slips.py` wired into the flow; the always-empty Slip History sheet is now populated (legs, result, payout multiplier, gross return, net PnL). The June 8–21 backtest backfilled **88 slips across 12 dates with an idempotent (Date, Slip ID) upsert (0 duplicate keys)**; slip success and prop success are tracked as distinct metrics (SLIPS-01..04). Verified 4/4.
- **Phase 3 — Slips-Only Bankroll:** Bankroll computed strictly from slip Net PnL with confidence-scaled stakes; prop→bankroll coupling severed (`sync_slip_bankroll`); prop W/L preserved as a separate Prop Accuracy signal; Gate-8 *global* exposure caps removed (concentration caps + the no-bet gauntlet preserved unchanged); ledger rebased from 2026-06-08 (100 → 126.778, idempotent, backed up) (BANKROLL-01..04). Verified 4/4.
- **Phase 4 — Dual Metrics and Feedback:** `metrics_report.py` surfaces slip ROI + prop hit-rate by ISO-week × sport (Telegram + Obsidian); a bounded per-sport sigma-calibration engine (≥30-outcome gate, ±0.05/cycle, [0.85,1.20] clamp, fingerprint-idempotent) feeds realized outcomes back into projection sigma; the loop is integrity-locked — AST-isolated and proven by verdict-snapshot + gate-output tests to never alter a graded verdict or gate result (METRICS-01..03). Verified 3/3.
- **Phase 04.1 — Close v2.0 Audit Gaps:** Closed the four functional gaps from the milestone audit — forward confidence staking now live on the daily `build_slips` path (no more flat `stake_units=1.0`; BANKROLL-02 forward path), daily Prop-Accuracy refresh (weekly metrics no longer stale), `load_calibration_factor` de-duplicated to one canonical copy, and a persistent `weekly_metrics` partial made visibly degraded instead of silently green (WR-03). 10/10 must-haves, zero new test failures.

**Stability hardening during the milestone (quick tasks):** fixed an O(n²) recap-read hang and the chronic Skipped-Picks generation bloat (root-caused as a stat-coverage gap, not a runaway append; 14,463 noise rows cleaned across 33 workbooks while preserving the Gate-8 vetted slip universe).

**Known deferred items at close:** Nyquist VALIDATION incomplete across phases (acknowledged tech-debt, consistent with the v1.0 close) and 3 live-environment human-UAT items (live `weekly_metrics` delivery, `calibration.json` real-data check, operator Monday cron entry). Milestone audit status: `resolved` — all functional gaps closed. See `milestones/v2.0-MILESTONE-AUDIT.md`.

---

## v1.0 Stability Hardening (Shipped: 2026-06-22)

**Delivered:** The Hermes NBA+MLB betting automation now runs unattended on schedule — the recurring `[Errno 32] Broken pipe` / `TASK FAILED` alert is eliminated, cron timeouts are root-caused and bounded, and a resilience + observability + CI safety net guards every fix.

**Phases completed:** 5 phases, 17 plans · ~8 days (2026-06-13 → 2026-06-21) · 114 commits · ~21.7K LOC tracked in `scripts/`

**Key accomplishments:**

- **Phase 1 — Diagnosis:** Root-caused both failures with evidence. `DIAGNOSIS.md` pins the broken pipe to the unprotected in-`try` `JSON_RESULT=` print in `main()` (`sports_system_runner.py:5634/5640`, HIGH confidence, deterministic repro) and the dominant timeout to the `send_telegram()` retry loop (24,923s max observed); stacked subprocess timeouts ruled out.
- **Phase 2 — Reliability Fixes + Defect Removal:** `safe_print` stdout sweep kills the broken pipe (FIX-01); `send_telegram` 10s timeout + per-run circuit breaker and a single task-end Obsidian sync close the timeout (FIX-02); all 11 runner tasks pass live end-to-end (FIX-03); duplicate `injury_monitor`/`clv_tracker` defs removed (DEF-01) and `generate_projections.py` de-hardcoded to `Path.home()` (DEF-02).
- **Phase 3 — Resilience:** Subprocess stages re-run once with backoff (RES-01); post-completion `BrokenPipeError` reclassified at the task boundary so a closed cron pipe never fires `TASK FAILED` (RES-02); every task self-terminates cleanly under a 660s SIGALRM budget below the cron kill — which was raised 120s→720s after proving tasks legitimately run to ~509s (RES-03); every Phase-2 fix is regression-tested (RES-04).
- **Phase 4 — Observability:** Every run appends a structured Core+ JSONL record to `run_log.jsonl` (OBS-01); a standalone read-only `health_check.py` surfaces overdue/last-failed tasks with a 🩺 heartbeat (OBS-02); a 🔁 REPEATED FAILURE alert fires additively on consecutive failures (OBS-03) — 55 tests.
- **Phase 5 — CI:** A committed `hooks/pre-push` (wired via `core.hooksPath=hooks`) runs a fast-subset `run_ci_gate.py` (fail-loud preflight: python3 3.14 + `requests`/`openpyxl` + `scripts/` CWD) on every push; an environment guard proves the interpreter/CWD contract (CI-02); `repro_ci_regression.py` fault-injection proves the gate goes RED on a real regression and GREEN on revert (CI-01).

**Requirements:** 16/16 v1 requirements satisfied (verified with code + passing regression tests).

**Known deferred items at close:** 5 (see STATE.md → Deferred Items). All non-blocking: 5 live-environment human-UAT confirmations (real cron run / Telegram delivery / real `git push`), Nyquist validation incomplete across all 5 phases, and 5 non-critical Phase-5 hardening warnings (WR-01…05). Milestone audit status: `tech_debt` — no blockers. See `milestones/v1.0-MILESTONE-AUDIT.md`.

---
