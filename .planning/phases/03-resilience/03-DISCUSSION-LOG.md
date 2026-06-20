# Phase 3: Resilience - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-20
**Phase:** 3-Resilience
**Areas discussed:** Retry policy & budget, Hard timeout design, Pipe-error reclassification, Regression-test scope & rigor

---

## Retry policy & budget (RES-01)

### Q1 — Where should retry-with-backoff for the un-retried subprocesses live?

| Option | Description | Selected |
|--------|-------------|----------|
| Inside each fetcher script | Wrap `requests.get` in fetch_prizepicks/fetch_underdog/build_hit_rate_db with a shared retry helper; retries the individual HTTP call, partial-success preserved | |
| Runner re-runs subprocess | Runner re-invokes the whole subprocess on non-zero exit / timeout; one policy, fewest files, but re-does all work | ✓ |
| Both layers | In-process retry + runner-level re-run wrapper; most robust, likely overkill | |

**User's choice:** Runner re-runs subprocess
**Notes:** Minimal-invasive preference. Flagged trade-off: re-does the whole stage's work; fetchers exit 0 even when blocked — addressed by the next question.

### Q2 — What triggers a re-run?

| Option | Description | Selected |
|--------|-------------|----------|
| Hard failures only | Re-run only on non-zero exit or `subprocess.TimeoutExpired`; empty-but-clean (exit 0, zero rows) NOT retried | ✓ |
| Hard failures + empty result | Also re-run when a primary source returns zero usable rows; catches silent degradation, more logic/latency | |
| You decide | Claude picks during planning | |

**User's choice:** Hard failures only
**Notes:** Predictable latency, no double-runs on genuinely quiet days.

### Q3 — Retry budget / added wall-clock

| Option | Description | Selected |
|--------|-------------|----------|
| 1 re-run, short backoff | One extra attempt per stage after a short wait; bounded worst-case latency under the hard timeout | ✓ |
| 2 re-runs, exponential backoff | Up to two re-runs with growing waits; a retried 600s ESPN build could add ~20+ min | |
| You decide per stage | Different budgets per stage; Claude tunes | |

**User's choice:** 1 re-run, short backoff
**Notes:** Keeps retry latency from fighting the RES-03 budget.

---

## Hard timeout design (RES-03)

### Q1 — Budget granularity across the 11 tasks

| Option | Description | Selected |
|--------|-------------|----------|
| Per-task budgets | Each task/task-class gets a cap sized to its real work; anchored to Phase-1 timing evidence | ✓ |
| Single global cap | One ceiling for every task; useless for fast tasks | |
| Global cap, override a few | Default global cap with overrides for the slow daily_picks tasks | |

**User's choice:** Per-task budgets
**Notes:** 10x+ spread between daily_picks (minutes) and verify (seconds) makes per-task accurate.

### Q2 — Mid-write safety guarantee on timeout

| Option | Description | Selected |
|--------|-------------|----------|
| Interrupt anywhere, lean on atomic save | Timeout fires wherever the task is; relies on temp-file + os.replace invariant | |
| Never interrupt a save | Guard the critical save region; strongest guarantee, more invasive | |
| You decide | Claude chooses after confirming save_workbook_atomic / safe_save_workbook sequencing | ✓ |

**User's choice:** You decide
**Notes:** Deferred to planning. Direction recorded in CONTEXT D-07: save is already atomic (temp `{path}.tmp.{pid}.xlsx` → single `os.replace`), so prefer interrupt-anywhere unless a real partial-write hole is found.

### Q3 — How a self-timeout surfaces to the operator

| Option | Description | Selected |
|--------|-------------|----------|
| Distinct 'timed out' alert | Separate `⏱ TASK TIMED OUT` Telegram + error log, distinct from the crash alert | ✓ |
| Reuse TASK FAILED path | Treat as another failure through the existing `❌ TASK FAILED` alert | |
| You decide | Claude chooses during planning | |

**User's choice:** Distinct 'timed out' alert
**Notes:** Lets a hang be told apart from a crash at a glance; still one alert per occurrence (pattern-counting is Phase 4).

---

## Pipe-error reclassification (RES-02)

### Q1 — How the except branch distinguishes spurious vs. real

| Option | Description | Selected |
|--------|-------------|----------|
| Only if task body completed | Track a 'result computed' flag; suppress TASK FAILED only when run_task() already returned; mid-task BrokenPipeError still alerts | ✓ |
| Downgrade all pipe errors | Any BrokenPipeError → warning, never alert; risks masking a genuine incomplete run | |
| You decide | Claude chooses during planning | |

**User's choice:** Only if task body completed
**Notes:** Matches the criterion's "when the task completed successfully" wording; won't mask a real-money mid-task failure.

### Q2 — Explicit OS-level SIGPIPE handler?

| Option | Description | Selected |
|--------|-------------|----------|
| Exception boundary is enough | Rely on Python's BrokenPipeError; no signal.signal() handler | ✓ |
| Add explicit SIGPIPE handler | Install a signal handler for defense-in-depth; largely redundant, risks subprocess interference | |
| You decide | Claude confirms during planning | |

**User's choice:** Exception boundary is enough
**Notes:** SIGPIPE on stdout already arrives as BrokenPipeError; SIG_DFL would hard-kill the process mid-task.

---

## Regression-test scope & rigor (RES-04)

### Q1 — Test scope for Phase 3

| Option | Description | Selected |
|--------|-------------|----------|
| Both: audit P2 + cover P3 | Audit Phase-2 fix tests for fail-before/pass-after AND add a test per new Phase-3 behavior | ✓ |
| Phase 3 behaviors only | Trust Phase-2 tests as-is; only add new-behavior tests | |
| You decide | Claude scopes during planning | |

**User's choice:** Both: audit P2 + cover P3
**Notes:** Satisfies both the ROADMAP "per Phase 2 fix" criterion and the RES-04 "every fix" wording.

### Q2 — Rigor bar for fails-before / passes-after

| Option | Description | Selected |
|--------|-------------|----------|
| Fault-injection by construction | Each test injects the exact fault; cannot pass without the fix; CI-friendly (Phase-2 D-09 approach) | ✓ |
| Injection + documented revert proof | Above plus a one-time documented revert showing each test red | |
| You decide | Claude picks per test during planning | |

**User's choice:** Fault-injection by construction
**Notes:** Repeatable, runs in CI, no manual reverts.

---

## Claude's Discretion

- **Timeout mechanism & mid-write safety (RES-03 Q2 → CONTEXT D-07):** chosen at planning
  after confirming the `safe_save_workbook` atomic sequence; direction is interrupt-anywhere
  unless a real partial-write hole surfaces.
- Exact per-task budget values, retry backoff seconds, the timeout primitive
  (`SIGALRM` vs watchdog thread), and the precise alert/warning wording.

## Deferred Ideas

- In-fetcher per-HTTP-call retry (rejected for RES-01 in favor of subprocess re-run).
- Retrying empty-but-clean fetch results / blocked-source detection (rejected for D-02).
- Pattern-aware "failed N times in a row" alerting → Phase 4 (OBS-03).
- Structured run-log records + health/heartbeat check → Phase 4 (OBS-01/OBS-02).
- CI running the suite on every change → Phase 5.
