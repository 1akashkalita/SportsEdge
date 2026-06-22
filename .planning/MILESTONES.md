# Milestones

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
