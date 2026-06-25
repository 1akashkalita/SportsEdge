---
phase: 3
slug: resilience
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-06-20
---

# Phase 3 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 9.x (discovery only) + `unittest.TestCase` (test bodies) — no pytest fixtures |
| **Config file** | none — discovered via `python3 -m pytest` run from `scripts/` |
| **Quick run command** | `cd scripts && python3 -m pytest test_res01_subprocess_retry.py test_res02_pipe_reclassify.py test_res03_task_timeout.py -x` |
| **Full suite command** | `cd scripts && python3 -m pytest` |
| **Estimated runtime** | quick: ~30–90 s · **full: ~34 min (slow — run only at wave/phase end, not per task)** |

> **Interpreter/CWD are load-bearing:** use `python3` (3.14 at `/usr/local/bin/python3`), run from
> `scripts/`. `python` (3.13) lacks `requests`; running from repo root breaks sibling imports.
>
> **Known-green baseline = `2 failed, 202 passed`.** The 2 failures are pre-existing in
> `test_generate_projections.py` and are NOT caused by this phase. A clean Phase-3 run must not
> add new failures beyond that baseline.

---

## Sampling Rate

- **After every task commit:** Run the quick command (the 3 RES-* files, plus the touched Phase-2
  audit test, e.g. `test_fix01_broken_pipe.py` / `test_fix02_telegram_circuit_breaker.py`).
- **After every plan wave:** Run the full suite (budget ~34 min; expect `2 failed, 202+ passed`).
- **Before `/gsd:verify-work`:** Full suite green relative to the known baseline.
- **Max feedback latency:** quick ≤ 90 s.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 3-RES01-a | RES-01 | 1 | RES-01 | — | Subprocess re-run once on non-zero exit (assert exactly 2 invocations) | unit (monkeypatch `subprocess`) | `python3 -m pytest test_res01_subprocess_retry.py -x` | ❌ W0 | ⬜ pending |
| 3-RES01-b | RES-01 | 1 | RES-01 | — | Exit 0 / empty board is NOT retried (assert exactly 1 invocation) | unit | same | ❌ W0 | ⬜ pending |
| 3-RES01-c | RES-01 | 1 | RES-01 | DoS (retry amplification) | Two consecutive hard failures → stage raises/propagates (no silent continue) | unit | same | ❌ W0 | ⬜ pending |
| 3-RES02-a | RES-02 | 1 | RES-02 | Repudiation (masked failure) | `BrokenPipeError` AFTER task completion → no `TASK FAILED` Telegram, warning logged, exit 0 | integration (subprocess + pipe close) | `python3 -m pytest test_res02_pipe_reclassify.py -x` | ❌ W0 | ⬜ pending |
| 3-RES02-b | RES-02 | 1 | RES-02 | Repudiation | `BrokenPipeError` DURING `run_task()` (task NOT complete) → still fires `TASK FAILED` | integration | same | ❌ W0 | ⬜ pending |
| 3-RES03-a | RES-03 | 1 | RES-03 | DoS (orphaned children) | Hung task → SIGALRM fires within budget, `⏱ TASK TIMED OUT` alert sent, in-flight subprocess killed (no orphan), exits cleanly | integration (subprocess, short patched budget) | `python3 -m pytest test_res03_task_timeout.py -x` | ❌ W0 | ⬜ pending |
| 3-RES03-b | RES-03 | 1 | RES-03 | — | Healthy task → `signal.alarm(0)` cancels timer, no spurious `TIMED OUT`, no `TASK FAILED` | integration | same | ❌ W0 | ⬜ pending |
| 3-RES04-a | RES-04 | 1 | RES-04 | — | Audit: all 4 Phase-2 tests genuinely fail-before / pass-after (no gaps) | audit + run | `python3 -m pytest test_fix01_broken_pipe.py test_fix02_telegram_circuit_breaker.py test_def01_no_duplicate_defs.py test_def02_path_resolution.py` | ✅ exists | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

> Every RES-03 / RES-02 SIGALRM/pipe test MUST run the runner as a **subprocess** (not in-process):
> `signal.alarm()` is process-wide and bleeds between in-process test cases, and pipe-close timing
> needs a real reader. This mirrors the existing `test_fix01_broken_pipe.py` subprocess pattern.

---

## Wave 0 Requirements

- [ ] `scripts/test_res01_subprocess_retry.py` — RES-01 (subprocess retry; monkeypatch `subprocess`)
- [ ] `scripts/test_res02_pipe_reclassify.py` — RES-02 (pipe close after vs during completion)
- [ ] `scripts/test_res03_task_timeout.py` — RES-03 (hung task timeout + orphan kill + clean healthy run)

*Framework already present (pytest 9.x + unittest). No install needed. The 4 Phase-2 audit tests
already exist.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| End-to-end behavior under real Hermes cron (120 s hard kill) | RES-03 | Cannot reproduce the live cron scheduler in unittest; the 120 s window is enforced by Hermes, not the runner | After merge, let an enabled cron job (`mlb_daily_picks`) run on schedule; confirm a healthy run completes < 120 s and does not emit `Script timed out after 120s`. Confirm a forced-hang (temporary) self-terminates with `⏱ TASK TIMED OUT` before the Hermes kill. |

*All in-runner behaviors have automated fault-injection coverage; only the live-cron interaction is manual.*

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references (3 new RES-* test files)
- [ ] No watch-mode flags
- [ ] Feedback latency < 90s (quick command)
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
