# Phase 3: Resilience - Context

**Gathered:** 2026-06-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Add the **general safety net** on top of the named-offender fixes Phase 2 already
shipped. Four requirements, all confined to making transient faults *tolerated*
rather than fatal:

- **RES-01** — outbound network calls retry with backoff on transient failure
  instead of failing the whole task.
- **RES-02** — broken-pipe / `SIGPIPE` at the task boundary is logged and tolerated,
  never surfaced as a spurious `❌ SPORTS TASK FAILED` when the task actually completed.
- **RES-03** — each task enforces a hard internal wall-clock budget so a hung stage
  fails cleanly (and safely, mid-write) instead of being killed by the cron wrapper.
- **RES-04** — every reliability fix lands with a fail-before / pass-after regression test.

**Already done in Phase 2 — DO NOT redo (locked):**
- `send_telegram()` (`sports_system_runner.py:238`) already has a 10s per-call HTTP
  timeout + a per-run 3-strike circuit-breaker + suppressed-count logging.
- `odds_api_io_client.py` already does 3-attempt exponential backoff (1s start) +
  429 `Retry-After`.
- All top-level prints already routed through `safe_print` (swallows `BrokenPipeError`).
- The duplicate `injury_monitor`/`clv_tracker` defs are removed; `generate_projections.py`
  uses `Path.home()`.

So the **gaps Phase 3 fills** are exactly: the un-retried DFS-fetcher + ESPN
subprocesses (RES-01), `main()`'s except-branch reclassification (RES-02), the missing
per-task hard timeout (RES-03), and the full regression sweep (RES-04).

**Out of bounds (Phase 4 — Observability, confirmed against ROADMAP.md):**
structured run-log records, the health/heartbeat check, and pattern-aware
"failed N times in a row" alerting. Phase 3 emits **one alert per occurrence**;
pattern-counting is Phase 4.

**Carried forward (locked — do not re-litigate):**
- **Minimal-invasive** — no gate-logic, pick-output, or workbook-schema changes
  (real-money system in active daily use).
- **Evidence-grounded** — harden the paths Phase 1 `DIAGNOSIS.md` actually named.
- **`python3` (3.14 alpha)**, run from `scripts/` — interpreter and CWD are fixed.

</domain>

<decisions>
## Implementation Decisions

### Retry policy & budget (RES-01)
- **D-01:** **Retries live at the runner level — re-run the whole subprocess.** The
  un-retried calls (PrizePicks/Underdog via `run_fetch_dfs_props`, ESPN via
  `run_build_hit_rate_db`) are spawned as `subprocess.run(...)` by the runner, so the
  retry wraps the subprocess invocation rather than the individual `requests.get`
  inside each fetcher. Chosen for minimal-invasiveness (one retry policy, fewest files
  touched) over in-fetcher retry. Accepted trade-off: a failure re-does the whole
  stage's work rather than just the failed HTTP call.
- **D-02:** **Re-run on hard failures only** — non-zero exit code or
  `subprocess.TimeoutExpired`. An empty-but-clean result (exit 0, zero rows) is treated
  as a legitimately empty board and is **NOT** retried (avoids wasted double-runs on
  quiet days). Accepted trade-off: a silently-degraded fetch that still exits 0 won't be
  retried — acceptable because the existing fetchers signal real failures via exit code.
- **D-03:** **Budget = 1 re-run, short backoff.** On a hard failure, wait a few seconds,
  re-run once; max one extra attempt per stage. Keeps worst-case added latency bounded
  (one extra subprocess) so retry latency never threatens the RES-03 hard timeout.
  After the single re-run fails, the stage fails and the failure is logged with context.
- **D-04:** **Telegram + Odds-API.io are left as-is** — both already retry (Phase 2 /
  existing client). RES-01's named call sites are covered without new code there.

### Hard timeout design (RES-03)
- **D-05:** **Per-task budgets**, not a single global cap. Each task (or task-class) gets
  a wall-clock ceiling sized to its real work — `daily_picks` generous (it stacks the
  fetch 300s + hit-rate 600s + projections 600s subprocess ceilings), monitors / `verify`
  tight. **Anchor the numbers to `01-TIMING-EVIDENCE.md`** (per-task duration profile).
  Rejected: a single global cap (useless for fast tasks — a hung `prop_monitor` would sit
  for a `daily_picks`-sized budget).
- **D-06:** **On timeout → distinct `⏱ TASK TIMED OUT` alert + error log**, separate from
  the `❌ SPORTS TASK FAILED` crash alert. Lets the operator tell a hang apart from a crash
  at a glance. One alert per occurrence (pattern-counting is Phase 4). The task must exit
  **cleanly with an error log** (the criterion), not wait for the cron wrapper to kill it.
- **D-07 (Claude's discretion — see below):** the timeout *mechanism* and the exact
  mid-write safety guarantee are deferred to planning, grounded by the atomic-save finding
  in `<code_context>`.

### Pipe-error reclassification (RES-02)
- **D-08:** **Reclassify only when the task body completed.** Track a "result computed"
  flag: if `run_task()` returns successfully and **then** a `BrokenPipeError` occurs (in
  `dispatch_alerts` or the final `JSON_RESULT` print), log a **warning**, suppress the
  `TASK FAILED` alert, and exit clean. A `BrokenPipeError` raised **during** `run_task()`
  is still a genuine failure and **still alerts**. Matches the criterion's "when the
  underlying task completed successfully" wording and never masks a real mid-task failure
  (critical for a real-money system).
- **D-09:** **No explicit OS-level `SIGPIPE` handler.** Python already disables the default
  SIGPIPE disposition and raises `BrokenPipeError`, so the task-boundary catch (D-08)
  covers the stdout-pipe case. Avoids the footgun where `signal.signal(SIGPIPE, SIG_DFL)`
  would hard-kill the process mid-task or interfere with subprocess pipes.

### Regression-test scope & rigor (RES-04)
- **D-10:** **Scope = both.** (a) **Audit** the existing Phase-2 fix tests to confirm each
  genuinely fails-before / passes-after, closing any gaps; AND (b) **add** one regression
  test for each new Phase-3 behavior — the subprocess re-run (D-01..D-03), the per-task
  hard timeout (D-05/D-06), and the pipe-error reclassification (D-08). Satisfies both the
  ROADMAP "per Phase 2 fix" criterion and the RES-04 "every reliability fix" wording.
- **D-11:** **Rigor = fault-injection by construction.** Each test injects the exact fault
  its fix addresses (monkeypatch the subprocess to fail once → assert one re-run; force a
  hang → assert the timeout fires + the `⏱ TASK TIMED OUT` path; close the pipe *after*
  completion → assert no `TASK FAILED`). Constructed so the test cannot pass without the
  fix — the same approach as Phase 2's D-09 tests. CI-friendly, repeatable, no manual
  reverts required.

### Claude's Discretion
- **Timeout mechanism & mid-write safety (D-07):** Choose during planning after confirming
  the `safe_save_workbook` sequencing (see `<code_context>`). **Direction:** the save is
  already atomic — temp file `{path}.tmp.{pid}.xlsx` then a single `os.replace(tmp, path)`
  (`workbook_io.py:151,165`) — so an interrupt mid-write leaves the original workbook intact
  (worst case: a harmless orphaned `.tmp`). Prefer the simpler **interrupt-anywhere** design
  (lean on that invariant) unless planning finds a real partial-write hole, in which case
  guard the critical save region. Per-task budgets are sized so a healthy save finishes
  long before the cap — firing mid-save means something was already badly wrong.
- **Exact per-task budget values**, the retry backoff seconds, the timeout primitive
  (e.g. `signal.SIGALRM` vs a watchdog thread), and the precise `⏱ TASK TIMED OUT` /
  warning wording — all planner's call within the decisions above.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` § "Phase 3: Resilience" — goal + the 4 success criteria; and
  § "Phase 4: Observability" — the OBS boundary Phase 3 must NOT cross (structured logs,
  heartbeat, pattern alerts).
- `.planning/REQUIREMENTS.md` § "Resilience" — RES-01, RES-02, RES-03, RES-04 (and the
  OBS-01..03 boundary deferred to Phase 4).
- `.planning/PROJECT.md` § "Context" / "Constraints" — minimal-invasive contract and the
  Hermes-cron / `python3` 3.14-alpha environment notes.

### Phase-1 diagnosis (the evidence base this phase hardens — most important)
- `.planning/phases/01-diagnosis/DIAGNOSIS.md` — the named failure modes (broken pipe at
  `main()` prints; `send_telegram()` retry loop as dominant timeout contributor) that
  Phase 3's safety net generalizes.
- `.planning/phases/01-diagnosis/01-TIMING-EVIDENCE.md` — **per-task duration profile;
  the anchor for sizing the RES-03 per-task budgets (D-05).**
- `.planning/phases/01-diagnosis/01-REVIEW.md` — Phase-1 review findings on the fix
  surfaces (notably **WR-03**: harden `repro_broken_pipe.py`'s run-log scan before reusing
  it as a standing regression test).

### Phase-2 boundary & what's already fixed (do not redo)
- `.planning/phases/02-reliability-fixes-defect-removal/02-CONTEXT.md` — the locked
  Phase-2/3 boundary and the Telegram breaker / `safe_print` sweep / Obsidian decouple
  decisions (D-02..D-10 there) Phase 3 builds on, not over.

### Code under change
- `scripts/sports_system_runner.py` — `main()`'s top-level `try/except/finally`
  (lines ~5580–5631, the RES-02 reclassification + RES-03 timeout boundary live here);
  `run_task()` (~5547, the "task body" whose completion D-08 keys on); the subprocess
  stages `run_fetch_dfs_props` (~1278), `run_build_hit_rate_db` (~1359),
  `run_generate_projections` (~1393, the RES-01 re-run targets); `dispatch_alerts` (~1054);
  `send_telegram` (~238, already retried — reference only); `safe_print` (~182/192, reuse).
- `scripts/workbook_io.py` — `safe_save_workbook` (lines 147–165): the temp-file +
  `os.replace` atomic-save sequence the RES-03 mid-write safety decision (D-07) depends on.
- `scripts/odds_api_io_client.py` — existing retry pattern (reference for RES-01 backoff
  shape; not re-implemented).
- `scripts/repro_broken_pipe.py` — extend into the RES-02 pipe-reclassification regression
  test (heed WR-03 first); `scripts/run_all_tasks.py` — the 11-task harness, useful for the
  timeout/regression sweep.
- `scripts/test_*.py` — existing `unittest` suite; home for the Phase-3 regression tests
  and the Phase-2 test audit (D-10).

### Codebase maps (lead inventory — dated 2026-06-14, pre-Phase-2)
- `.planning/codebase/INTEGRATIONS.md` — every external call site (Odds-API.io, PrizePicks,
  Underdog, ESPN, Telegram, Obsidian) and its current retry/timeout posture.
- `.planning/codebase/CONCERNS.md`, `.planning/codebase/ARCHITECTURE.md` — subprocess-timeout
  budgets and the orchestration model.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`safe_print()`** (`sports_system_runner.py` ~182/192): already swallows
  `BrokenPipeError`; RES-02's boundary handling complements it (it handles the *known*
  prints; D-08 catches the catch-all at `main()`).
- **`safe_save_workbook()`** (`workbook_io.py:147`): atomic via temp file
  `{path}.tmp.{pid}.xlsx` → `os.replace(tmp, path)` (a single syscall). This is the
  invariant the RES-03 mid-write safety decision (D-07) leans on.
- **`scripts/repro_broken_pipe.py`** + **`scripts/run_all_tasks.py`**: the Phase-1/2
  fault-injection harness and the 11-task clean-pass harness — seed the RES-04 tests.
- **`odds_api_io_client.py` retry loop**: the canonical backoff shape to mirror for D-03.
- **`_telegram_breaker`** + per-invocation reset in `main()`'s try block (~5582): the
  pattern for any new per-run resilience state Phase 3 adds.

### Established Patterns
- The orchestrator **subprocesses** the fetch/projection stages and reads results back from
  files — so RES-01's "re-run the subprocess" (D-01) fits the existing seam exactly; it
  wraps `subprocess.run` call sites, not the fetchers' internals.
- Telegram/Obsidian are **best-effort side-effects** already wrapped so they never crash a
  task; Phase 3 tightens *when* failures are tolerated vs. alerted, not whether they run.
- Tasks are **defensive** (missing games/workbooks → SKIP, not exceptions) and the
  `JSON_RESULT={…}` stdout contract is load-bearing — preserve both.

### Integration Points
- RES-02 + RES-03 both live in `main()`'s `try/except/finally` (~5580–5631): the except
  branch gains pipe reclassification (D-08); a timeout primitive wraps the `with`-locked
  `run_task()` call (D-05); the `finally` already computes `elapsed` and emits the
  suppressed-count line — the timeout alert (D-06) slots in alongside.
- RES-01 re-run logic wraps the three `subprocess.run` stages in `run_fetch_dfs_props` /
  `run_build_hit_rate_db` / `run_generate_projections` — additive, single-file.

</code_context>

<specifics>
## Specific Ideas

- The operator-facing crash alert to preserve is `❌ SPORTS TASK FAILED: <task> / Error: <e>`
  (`sports_system_runner.py:5606`). After RES-02 it must NOT fire when a completed task hits
  a broken pipe. The new timeout alert (D-06) is a sibling: `⏱ TASK TIMED OUT`.
- Heed Phase-1 review **WR-03**: harden `repro_broken_pipe.py`'s run-log scan (avoid writing
  to the production log / racy byte-offset) before it becomes the standing RES-02 test.
- Size the RES-03 per-task budgets from `01-TIMING-EVIDENCE.md` so each cap sits comfortably
  above the task's real worst-case but below the cron wrapper's kill window.

</specifics>

<deferred>
## Deferred Ideas

- **In-fetcher (per-HTTP-call) retry** for PrizePicks/Underdog/ESPN — considered for RES-01,
  rejected in favor of runner-level subprocess re-run (D-01) for minimal-invasiveness. A
  future accuracy/perf milestone could revisit if re-running whole stages proves wasteful.
- **Retrying empty-but-clean fetch results** (blocked-source detection) — rejected for D-02;
  revisit only if silent fetch degradation becomes a real observed problem.
- **Pattern-aware alerting** ("task failed N times in a row" / distinct repeat alert) →
  Phase 4 (OBS-03). Phase 3 fires one alert per occurrence.
- **Structured run-log records + health/heartbeat check** → Phase 4 (OBS-01/OBS-02).
- **CI running the suite on every change** → Phase 5 (CI-01/CI-02); Phase 3 only ensures the
  regression tests exist and are fault-injection-rigorous.

</deferred>

---

*Phase: 3-Resilience*
*Context gathered: 2026-06-20*
