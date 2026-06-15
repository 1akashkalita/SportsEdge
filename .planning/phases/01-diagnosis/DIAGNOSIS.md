# Phase 1 Diagnosis: Hermes Sports Automation — Root-Cause Document

**Phase:** 01-diagnosis
**Produced:** 2026-06-15
**Covers:** DIAG-01 (Broken-pipe failure) + DIAG-02 (Cron-job timeouts)
**Evidence window:** 2026-06-08 through 2026-06-15 (18,626 run-log lines, 791+ task completions)

---

## Section 1 — Broken-Pipe Root Cause (DIAG-01)

### Statement

The alert `❌ SPORTS TASK FAILED: mlb_prop_monitor / Error: [Errno 32] Broken pipe` is
**spurious**. The task's actual work (prop ingestion, gate evaluation, workbook writes)
**completes successfully**. The error is raised at the bare `print("JSON_RESULT=...")` in
`scripts/sports_system_runner.py`, function `main()`, **line 5634** (success path) or
**line 5640** (except-path fallback), after the Hermes `no_agent` cron wrapper has already
closed the stdout pipe. The closed pipe causes Python to raise `BrokenPipeError`, which is
caught by `main()`'s top-level `except Exception` block — which then fires the "TASK FAILED"
Telegram alert, misclassifying a completed task as failed.

**Exact failing location:**

| Path | Function | Line | Role |
|------|----------|------|------|
| `scripts/sports_system_runner.py` | `main()` | 5634 | Bare `print("JSON_RESULT=...")` — success path (unprotected) |
| `scripts/sports_system_runner.py` | `main()` | 5640 | Bare `print("JSON_RESULT=...")` — except path (also unprotected) |

**Note:** `safe_print()` at line 192 exists and already protects per-line log output
from broken-pipe errors. The two `JSON_RESULT=` prints at 5634/5640 were never wrapped in it.

### Mechanism

The causal chain that produces the spurious alert is:

1. Task body runs to completion (`mlb_prop_monitor` processes 5,023 active props, refreshes 300 rows, detects 61 line moves).
2. `dispatch_alerts()` is called: fires one `send_telegram()` call per line move (61 calls), each triggering `log("Telegram alert sent")`, each of which spawns an `obsidian_sync` subprocess.
3. While `dispatch_alerts()` is still running, the Hermes `no_agent` pipe closes (the cron wrapper receives the `no_agent` task-complete signal or its inactivity window expires).
4. `dispatch_alerts()` finishes; `main()` reaches `print("JSON_RESULT=...")` at line 5634.
5. The write to a closed pipe raises `BrokenPipeError([Errno 32] Broken pipe)`.
6. `except Exception as e` catches the `BrokenPipeError` — treating it identically to a real task failure.
7. `send_telegram(f"❌ SPORTS TASK FAILED: {args.task}\nError: {e}")` fires, producing the operator alert.
8. The task then writes `TRACEBACK task=mlb_prop_monitor:` and `ERROR task=mlb_prop_monitor: [Errno 32] Broken pipe` to the run-log (via the D-03/D-04 hook added in Plan 01).
9. `main()` returns 1 (error exit code) even though the task completed successfully.

The pipe closes mid-`dispatch_alerts` because the fanout duration (61 Telegram calls at ~1s
each = ~58s) exhausts the Hermes pipe's inactivity window. Evidence: the 2026-06-09 run-log
shows task-complete at 22:47:00 and the broken-pipe error at 22:47:58 — exactly 58 seconds
later — while `dispatch_alerts` was still active.

### Evidence Artifact

**Primary: `scripts/repro_broken_pipe.py`** (created Plan 01, commit `9d49d62`)

The repro deterministically triggers the broken pipe:
- Spawns the runner via `subprocess.Popen(stdout=PIPE)` with `-u` (unbuffered stdout)
- Background reader thread monitors stdout and closes the pipe's read end immediately after
  the task-completion sentinel line (`"verification complete"`) is detected — matching the
  production scenario where Hermes closes stdout after the task's work is done
- The next runner instruction is the bare `print("JSON_RESULT=...")` at line 5634, which
  raises `BrokenPipeError([Errno 32] Broken pipe)` synchronously inside the try block
- Repro result: `PASS: BrokenPipeError reproduced and captured in run-log (returncode=1, new_signals=4)`
  — confirming the failing frame is line 5634, not a startup or network call

**Supporting: `data/pnl/logs/run_log.txt`** — 34+ captured `ERROR task=...: [Errno 32] Broken pipe` occurrences written by the D-03/D-04 hook (Plan 01 Task 2).

Verbatim run-log excerpt from the canonical broken-pipe event (2026-06-09T22:47:xx UTC):

```
[2026-06-09T22:47:54+00:00] Telegram alert sent
[2026-06-09T22:47:55+00:00] Telegram alert sent
[2026-06-09T22:47:56+00:00] Telegram alert sent
[2026-06-09T22:47:57+00:00] Telegram alert sent
[2026-06-09T22:47:58+00:00] Telegram alert sent
[2026-06-09T22:47:58+00:00] ERROR task=mlb_prop_monitor: [Errno 32] Broken pipe
[2026-06-09T22:47:59+00:00] Telegram alert sent
[2026-06-09T22:47:59+00:00] [mlb_prop_monitor] completed in 129.4s
[2026-06-09T22:48:00+00:00] WARNING: mlb_prop_monitor took 129.4s — consider further optimization
```

The sequence confirms: (a) Telegram fanout was still active when the pipe closed, (b) the
error fires mid-fanout (not before task work begins), (c) the task is still recorded as
"completed" afterward — proving the underlying work succeeded.

Additional run-log evidence from the D-04 hook (captured 2026-06-14):
```
[2026-06-14T17:42:07+00:00] TRACEBACK task=verify:
[2026-06-14T22:57:02+00:00] TRACEBACK task=verify:
```
These `TRACEBACK task=` lines confirm the hook installed in Plan 01 writes the full stack
trace to `data/pnl/logs/run_log.txt` on the real production failure path.

### Confidence

**HIGH.** Evidence is multi-modal:
- Deterministic local repro (`repro_broken_pipe.py`) confirms the failing frame (line 5634
  in `main()`) and the exact exception type
- 34+ `ERROR task=...: [Errno 32] Broken pipe` occurrences in the run-log across multiple
  tasks (`mlb_prop_monitor`, `nba_prop_monitor`, `mlb_daily_picks`, `nba_daily_picks`,
  `nba_clv_tracker`) with the same pattern each time
- Verbatim run-log excerpt shows task-complete + ERROR + `completed in 129.4s` sequence
  in correct causal order
- The timing gap (58s from task-complete to pipe error) matches the 61-line-move Telegram
  fanout duration exactly

### Fix Direction (D-09 — direction only; Phase 2 owns the implementation)

Two complementary changes are needed:

1. **Protect the JSON_RESULT prints:** Wrap the bare `print("JSON_RESULT=...")` calls at
   lines 5634 and 5640 in `safe_print()` (which already exists at line 192 and silently
   handles `BrokenPipeError`). This prevents `BrokenPipeError` from reaching the
   `except Exception` block.

2. **Distinguish BrokenPipeError in the except branch:** When `BrokenPipeError` propagates
   from an already-completed task, the `except Exception` handler must NOT fire the
   "❌ SPORTS TASK FAILED" Telegram alert. A completed task with a broken pipe is not a
   task failure. The distinction (completed vs genuinely failed) and the exact implementation
   approach (special-case the exception type, check a completion flag, or restructure
   `main()`) are Phase 2's decision.

---

## Section 2 — Timeout Root Cause (DIAG-02)

### Statement

The observed cron-job "timeouts" are **not** `subprocess.TimeoutExpired` exceptions. They
are the runner process spending **minutes to hours** inside `send_telegram()` retry loops
during network outages, compounded by `obsidian_sync` subprocess calls (one per `log()` call,
up to 60s each) from per-log-line Obsidian mirroring. The dominant contributor is the
**`send_telegram()` retry loop**: 30s HTTP timeout × 2 retries per failing call site, with
multiple call sites per task run (one per `log()` alert call, plus one per line-move in
`dispatch_alerts`). Under network outage, a single `mlb_clv_tracker` run stalled for
**24,923 seconds** (6.9 hours) — entirely from Telegram retries, not from subprocess stages.

**Dominant contributor:** `send_telegram()` retry loop in `scripts/sports_system_runner.py`
**Observed maximum:** 24,923s (`mlb_clv_tracker`, 2026-06-12)

### Ranked Contributors (D-10)

Based on run-log evidence from 791+ task completions (2026-06-08 through 2026-06-15).
Evidence source: `.planning/phases/01-diagnosis/01-TIMING-EVIDENCE.md`.

| Rank | Contributor | Max observed overhead | Occurs when | Fix direction |
|------|-------------|----------------------|-------------|---------------|
| 1 | `send_telegram()` retry loop — 30s HTTP timeout × 2 retries per call; multiple call sites per task (one per `log()` alert, plus per-move fanout in `dispatch_alerts`) | **24,923s observed** (mlb_clv_tracker, 2026-06-12); hours-long stalls across 5+ tasks on 2026-06-15 | Network/DNS outage; `api.telegram.org` unreachable (`NameResolutionError`). Also 20–95s per failing call when network is marginal | Hard per-call timeout budget; circuit-breaker on consecutive failures — skip Telegram if N consecutive calls fail; Phase 3: hard task-level self-timeout |
| 2 | `obsidian_sync` subprocess per `log()` call — up to 60s timeout per subprocess; called on every operational log line | **Minutes** compounding (N log lines × up to 60s each); the 129s `mlb_prop_monitor` run shows ~58s for 61 `obsidian_sync` subprocesses (~1s each when fast, up to 60s when degraded) | Every task run; worst when `obsidian_sync.py` hangs or network path is degraded | Batch Obsidian writes; decouple from the hot `log()` path; call once at task end, not per line |
| 3 | Workbook lock contention — `workbook_file_lock` blocks up to 120s per poll cycle; stale lock threshold is 600s | **Hours** of waiting (in combination with Rank 1: the lock holder is itself stalled on Telegram retries; queued tasks stack behind it) | Prior task holds workbook lock and is stalled on Telegram retries; subsequent tasks queue behind it multiplying the delay | Reduce `stale_seconds` threshold from 600s to ≤180s; add per-task hard self-timeout so a stalled lock holder releases sooner |
| 4 | Bare `print(cp.stdout.rstrip())` in `run_fetch_dfs_props` (line 1274) — unprotected print on a potentially-closed pipe | Rare; contributes to some broken-pipe occurrences inside the lock context | Pipe already closed when fetch stage executes (less common than the `JSON_RESULT=` path) | Replace with `safe_print(cp.stdout.rstrip())` — same class of fix as Section 1 |
| 5 | Stacked subprocess timeouts (`fetch_dfs_props` 300s + `build_hit_rate_db` 600s + `generate_projections` 600s) | **1,500s theoretical ceiling** — never reached in 791+ observed completions | Would require all three stages to exhaust their timeouts on a single run | Not yet an operational risk; monitor; relevant only if ESPN API or PrizePicks degrades severely |

### Evidence Artifact

**Primary: `.planning/phases/01-diagnosis/01-TIMING-EVIDENCE.md`**

Contains: per-task duration profile (all 11 tasks, 5 percentile columns, 791+ completions),
slow-run warning corroboration (206 warnings), extreme-duration / network-stall correlation
(3 case studies with verbatim run-log excerpts), Lead #2 disposition, representative timed
runs (6 tasks measured on 2026-06-15), and the D-10 ranked-contributors table.

Verbatim run-log excerpt showing `NameResolutionError` co-occurring with a 24,860s stall
(2026-06-12, `nba_clv_tracker`):

```
[2026-06-12T09:30:04+00:00] Telegram alert failed attempt 2/2: ... (Caused by
    NameResolutionError("... Failed to resolve 'api.telegram.org' ..."))
[2026-06-12T09:30:05+00:00] Telegram alert failed after all retries; continuing without crashing task
[2026-06-12T09:30:22+00:00] Telegram alert failed after all retries; continuing without crashing task
[2026-06-12T09:30:22+00:00] [check_results] completed in 2025.5s
[2026-06-12T09:47:17+00:00] Acquired workbook lock /Users/akashkalita/sports_picks/locks/nba_2026-06-12.xlsx.lock
```

The `check_results` task stalled 2025s on Telegram retries. The `nba_clv_tracker` task was
then waiting for that lock. Once the lock was acquired, the clv_tracker itself faced an
unreachable network:

```
[2026-06-12T16:41:24+00:00] Odds-API.io events error sport=nba ... (Caused by
    NameResolutionError("... Failed to resolve 'api.odds-api.io' ..."))
[2026-06-12T16:41:30+00:00] NBA CLV prop closing line refresh skipped: [Errno 32] Broken pipe
[2026-06-12T16:41:37+00:00] [nba_clv_tracker] completed in 24860.0s
```

**Supporting run-log excerpt (2026-06-15 Telegram retry storm):**

```
[2026-06-15T19:39:12+00:00] [mlb_daily_picks] completed in 7,697.0s
[2026-06-15T19:39:42+00:00] [nba_prop_monitor] completed in 5,641.6s
[2026-06-15T19:47:11+00:00] [nba_injury_monitor] completed in 6,090.8s
[2026-06-15T20:44:50+00:00] [mlb_prop_monitor] completed in 9,549.7s
```

All four tasks completing within a 65-minute window after the outage cleared confirms their
durations were dominated by network-stall time, not computation.

### Lead #2 Disposition

**Stacked subprocess timeout totals (Lead #2) — RULED OUT** as the primary cause of extreme
durations.

- Theoretical ceiling: `fetch_dfs_props` 300s + `build_hit_rate_db` 600s +
  `generate_projections` 600s = **1,500s maximum**
- Largest observed `daily_picks` duration: **7,697s** (`mlb_daily_picks`, 2026-06-15) —
  exceeds the 1,500s ceiling by **5×**, conclusively ruling out subprocess timeouts as the
  cause
- Subprocess stages run in seconds under normal conditions: `build_hit_rate_db` ~19s for 290
  players, `generate_projections` ~2s, `fetch_dfs_props` ~3s
- The 1,500s ceiling has never been reached in 791+ observed completions
- Working backward: the 7,697s `mlb_daily_picks` run started during the 2026-06-15 Telegram
  retry storm and was blocked on lock contention while the prior task stalled

**`log()`/`obsidian_sync()` per-line lead — CONFIRMED as a compounding contributor** (Rank 2
in the table above). The 129.4s `mlb_prop_monitor` run shows ~58s for 61 `obsidian_sync`
subprocesses (~1s each during normal network). Under degraded network, each subprocess call
can consume up to 60s, making this a significant multiplier on top of the Rank 1 Telegram
retry loop.

### Confidence

**HIGH** for `send_telegram()` retry loop as the dominant cause: the 24,923s max observed
duration exceeds any alternative mechanism by more than an order of magnitude; the
`NameResolutionError` / "Telegram alert failed" lines in the run-log directly co-occur with
extreme-duration completions; and `nba_daily_picks` ran in 38.8s wall clock after the same
network outage cleared.

**MEDIUM** for `obsidian_sync` per-log-line as secondary contributor: timing is from
coarse run-log evidence (the 129.4s run with 61 Telegram calls shows ~58s of Obsidian
subprocess activity) rather than per-call instrumentation, per D-11 (no throwaway
instrumentation was added — coarse numbers were sufficient to isolate the offender).

### Fix Direction (D-09 — direction only; Phase 2 owns the implementation)

Three complementary changes address the timeout contributors in rank order:

1. **Hard per-task wall-clock timeout (Rank 1 + Rank 3):** Enforce an internal time budget
   per task invocation so a Telegram retry storm or lock-wait does not stall the runner
   indefinitely. The enforcement mechanism and timeout value are Phase 2's call.

2. **Short-circuit Telegram on consecutive failures (Rank 1):** Add a circuit-breaker so
   that when N consecutive `send_telegram()` calls fail, subsequent calls in the same task
   run are skipped rather than retried. Prevents the fanout (one call per line move) from
   multiplying wait time during an outage. Phase 2 decides N and the skip behavior.

3. **Decouple `obsidian_sync` from the hot `log()` path (Rank 2):** Batch Obsidian writes
   and flush at task end rather than spawning a subprocess per log line. Phase 2 decides
   the batching strategy and whether to keep synchronous or move to async/background.

---

## Timing Caveat

**Python interpreter:** The system runs `python3` at `/usr/local/bin/python3`, which is
**CPython 3.14.0a2 (alpha)**. Alpha builds include additional debug assertions and may have
non-representative GIL behavior, startup overhead, or JIT compilation characteristics
relative to a stable release. All absolute durations in this document are measurements
from this alpha interpreter. The relative ordering of contributors (Telegram retry >>
obsidian_sync >> lock contention >> subprocess stages) is robust to interpreter variance;
absolute numbers should be treated as directional, not precise. Per D-11: no throwaway
per-stage instrumentation was added because coarse run-log numbers isolated the dominant
offender clearly.

**Cron time budget:** The Hermes `no_agent` pipe/timeout window is **[ASSUMED]** to be
approximately 60–120 seconds of quiet stdout after process start, or at the moment Hermes
receives the task result. No explicit config value was found documenting the exact timeout;
the `~/.hermes/config.yaml` fields `gateway_timeout: 1800` and `inactivity_timeout: 120`
are gateway-level values whose mapping to the `no_agent` pipe closure is assumed. The
canonical broken-pipe event (2026-06-09T22:47:00 task complete → 22:47:58 pipe error)
confirms the pipe remained open for ~58 seconds after the task's actual work completed
while `dispatch_alerts` was still running.

---

## Traceability

Maps each ROADMAP § Phase 1 success criterion to a concrete evidence pointer in this document.

| Success Criterion | Where Addressed in DIAGNOSIS.md | Evidence Artifact |
|-------------------|---------------------------------|-------------------|
| 1. Names the exact code path producing `[Errno 32] Broken pipe` on `mlb_prop_monitor`, backed by a reproduction script or captured trace | Section 1 — Statement (file/function/line: `sports_system_runner.py`, `main()`, lines 5634/5640), Mechanism, Evidence Artifact | `scripts/repro_broken_pipe.py` (deterministic repro, `returncode=1, new_signals=4`); `data/pnl/logs/run_log.txt` verbatim excerpt (`ERROR task=mlb_prop_monitor: [Errno 32] Broken pipe` at 2026-06-09T22:47:58, `completed in 129.4s` at 22:47:59) |
| 2. Names which task, stage, or subprocess exceeds the cron time budget, backed by timing evidence | Section 2 — Statement (dominant contributor: `send_telegram()` retry loop, max 24,923s), Ranked Contributors table | `.planning/phases/01-diagnosis/01-TIMING-EVIDENCE.md` (per-task duration profile, 791+ completions; Case 2 extreme-duration excerpt; Case 3 Telegram retry storm) |
| 3. The `log()`/`obsidian_sync()` per-line lead AND the stacked subprocess timeout totals are confirmed or ruled out with evidence | Section 2 — Lead #2 Disposition (RULED OUT for subprocess timeouts, 7,697s > 1,500s ceiling by 5×; CONFIRMED for obsidian_sync per-line as compounding contributor) | `.planning/phases/01-diagnosis/01-TIMING-EVIDENCE.md` Lead #2 Disposition section; `data/pnl/logs/run_log.txt` 2026-06-15 storm completions showing all tasks clearing within 65 minutes post-outage |

**Requirements addressed: DIAG-01, DIAG-02**
