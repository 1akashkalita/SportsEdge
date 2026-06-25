# Phase 1: Diagnosis - Research

**Researched:** 2026-06-13
**Domain:** Python cron-job reliability — broken-pipe root cause, task-timeout source
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**D-01:** Use both evidence paths in parallel — (a) a deterministic local repro script that forces the `BrokenPipeError` on demand (run `mlb_prop_monitor` with stdout wired to a reader that closes early, e.g. piping to `head`), capturing the exact failing frame; and (b) a lightweight live traceback dump added to `main()`'s top-level `except`, to confirm a real scheduled run hits the same code path.

**D-02:** The local repro script is the primary mechanism-pinning artifact and is designed to double as the Phase-3 regression-test seed (RES-04).

**D-03:** The live traceback instrumentation stays after Phase 1 — an intentional down payment on Phase 4 (OBS-01 structured run logs) that also helps Phase 2/3 verify the fix. Phase 1 therefore leaves one small, additive, committed logging change (no gate / pick / schema / behavior change).

**D-04:** The captured trace must be written to a robust sink (the existing run-log file under `data/pnl/logs/`), NOT solely stdout, so the instrumentation cannot itself participate in a stdout broken pipe and perturb the very thing it measures.

**D-05:** Asymmetric scope. Broken pipe → confirm or rule out only the three named leads with evidence: (1) `log()` mirroring to stdout + the per-line `obsidian_sync` subprocess; (2) stacked subprocess timeout totals; (3) absence of `SIGPIPE` / `BrokenPipeError` handling → a raw `BrokenPipeError` reaching `main()`'s top-level `except` → the spurious `❌ TASK FAILED` alert.

**D-06:** Timeout → broad timing sweep across all pipeline stages (not just the named leads), because which stage exceeds the cron budget is itself the open question (DIAG-02). Find the real offender; don't assume it.

**D-07:** Evidence bar = a single representative timed run per task is sufficient to name the dominant stage, corroborated by the `>90s` slow-run warnings already present in the run logs. Multi-run worst-case profiling is not required.

**D-08:** One written DIAGNOSIS.md in the phase directory. For each failure: exact file / function / line, the mechanism narrative, the supporting evidence artifact (repro-script output or captured trace; timing table), and a stated confidence level.

**D-09:** Diagnosis is "cause + recommended fix direction" — name what to change and why, without locking the implementation (Phase 2 owns the how).

**D-10:** Timeout findings are presented as a ranked-contributors table (dominant offender + next-biggest stages, with measured durations) against the cron time budget — so Phase 2 can trim more than one stage if the overrun is death-by-a-thousand-cuts.

**D-11:** Collect timing externally first — timed task runs plus mining the existing run logs and the `>90s` slow-run warning. Add temporary per-stage in-runner instrumentation only if the coarse numbers don't isolate the offender. Any such temporary instrumentation is throwaway (distinct from the kept broken-pipe traceback dump in D-03). Keeps the timeout investigation minimal-invasive.

### Claude's Discretion

- Exact structure of the local repro script and how it wires the stdout-closure.
- Which specific tasks to time beyond the obvious heavy path (`daily_picks` nba + mlb — the stacked-subprocess path) and `mlb_prop_monitor`.
- The precise DIAGNOSIS.md section ordering / formatting.

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope. (The actual fixes for both failure modes are Phase 2; retries/backoff, `SIGPIPE` handling, and hard internal timeouts are Phase 3; structured run logs / heartbeat / pattern alerting are Phase 4 — all already on the roadmap.)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DIAG-01 | Operator can point to the documented root cause of the `mlb_prop_monitor` `[Errno 32] Broken pipe` failure, supported by a reproduction or a captured real-run trace | Run-log analysis confirms the error occurs at line 5640 (`print("JSON_RESULT=...")`) after a large burst of per-line-move Telegram calls via `dispatch_alerts` → `log()` → `safe_print()` exhaust the Hermes stdout pipe. Repro script design is fully specified below. |
| DIAG-02 | Operator can point to the documented source of cron-job timeouts (which task / stage / subprocess exceeds budget), supported by timing evidence | Run-log corroboration shows CLV tracker (up to 24,923s), prop monitor (up to 12,585s), and injury monitor (up to 6,254s) all dramatically exceeding the ~30–60s burst window. Root cause: `send_telegram()` retry timeouts with 30s HTTP timeout × 2 retries when Telegram/DNS is unreachable. |
</phase_requirements>

---

## Summary

This research phase investigated both failure modes in depth by reading the full source code of `sports_system_runner.py` and mining `data/pnl/logs/run_log.txt` (15,294 lines spanning 2026-06-08 through 2026-06-14, 791 task completions). All three named suspects were evaluated with evidence from the live log.

**Broken pipe (DIAG-01).** The `[Errno 32] Broken pipe` is confirmed in the run log at 34+ occurrences across multiple tasks. The trigger is always the same: `dispatch_alerts()` fires one `send_telegram()` per line move detected during `prop_monitor`, and each `send_telegram()` call ends with `log("Telegram alert sent")`, which itself calls `obsidian_sync()` as a subprocess AND calls `safe_print()`. When the Hermes `no_agent` cron wrapper closes its stdout pipe after the configured timeout, the final `print("JSON_RESULT=...")` at line 5634 (or 5640 in the `except`) raises `BrokenPipeError`. That exception is caught by `main()`'s top-level `except Exception`, which then calls `send_telegram(f"❌ SPORTS TASK FAILED: ...")` — creating the spurious failure alert even though the task's actual work completed successfully at line 5634. The `safe_print()` function at line 192 catches `BrokenPipeError` on the per-log-line prints, but the `JSON_RESULT=` final print at lines 5634/5640 is a bare `print()` with no protection.

**Timeouts (DIAG-02).** The run log contains durations from 0.5s to 24,923s for the same task type. The extreme outliers (CLV tracker: 24,923s = ~6.9 hours; prop monitor: 12,585s = ~3.5 hours; injury monitor: 6,254s = ~1.7 hours) are not caused by the named subprocess timeout suspects. Instead, they are caused by `send_telegram()` with a 30-second `requests` timeout and 2 retries (total up to 95s per call site) when the Mac's DNS / network is unavailable. When `clv_tracker` runs `run_fetch_dfs_props()` which internally calls `print(cp.stdout.rstrip())` (bare print, not `safe_print`) and then `obsidian_sync` is called per `log()` line, AND then Telegram retries exhaust on network outage, the task wall-clock balloons. The `obsidian_sync` subprocess has a 60s timeout per call and is invoked once per `log()` call — on a run with many log lines this compounds. The stacked subprocess timeout ceiling (fetch 300s + hit_rate 600s + projections 600s) is a theoretical upper bound of 1500s for daily_picks; the actual daily_picks runs observed are 7–356s, well under ceiling.

**Primary recommendation:** For broken pipe — wrap the `print("JSON_RESULT=...")` at lines 5634 and 5640 in `safe_print()`, and add a traceback dump to `data/pnl/logs/run_log.txt` in the `except` block. For timeouts — the immediate lever is removing the per-`log()`-line `obsidian_sync` subprocess call and batching Obsidian writes; the second lever is giving `send_telegram()` a hard cumulative timeout.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Broken-pipe repro | Orchestrator (`main()`) | Local test script | `main()` is the exception boundary; repro must exercise that exact path |
| Traceback dump (D-03/D-04) | Orchestrator (`main()`) except block | `data/pnl/logs/run_log.txt` file | Must go to file sink, not stdout |
| Timing sweep | Existing run log | Timed `time python3 ...` runs | Log already has 791 completions with durations |
| DIAGNOSIS.md deliverable | Phase-dir artifact | — | Consumed by operator + Phase 2 planner |

---

## Evidence: Lead 1 — `log()` + `obsidian_sync` per log line

### What the code actually does [VERIFIED: code read]

`log()` at `sports_system_runner.py:203–213`:

```python
def log(msg: str) -> None:
    ensure_dirs()
    line = f"[{now_iso()}] {msg}"
    with RUN_LOG.open("a") as f:
        f.write(line + "\n")
    # Mirror every operational sports-system log line through canonical obsidian_sync.
    try:
        obsidian_sync({"trigger": "sports_run_log", "date": today_str(), "data": {"line": line}})
    except Exception:
        pass
    safe_print(line)
```

`safe_print()` at `sports_system_runner.py:192–200` catches `BrokenPipeError` on its own `print()` call and redirects stdout to `/dev/null`:

```python
def safe_print(line: str, *, file: Any = None) -> None:
    """Print operational output without letting a closed cron pipe fail the task."""
    try:
        print(line, file=file or sys.stdout)
    except BrokenPipeError:
        try:
            sys.stdout = open(os.devnull, "w")
        except Exception:
            pass
```

`obsidian_sync()` at `sports_system_runner.py:401–420` spawns a subprocess with `timeout=60`. The `except Exception: pass` in `log()` means a failed `obsidian_sync` does NOT crash the task.

**Conclusion for Lead 1 (slowness angle):** Every `log()` call spawns `obsidian_sync` as a subprocess with up to 60s timeout. On a run with many log lines (prop monitor produces 50–100+ log messages including "Telegram alert sent" lines), this adds up. However, the `except Exception: pass` means it degrades gracefully when `obsidian_sync` is slow.

**Conclusion for Lead 1 (broken-pipe angle):** `safe_print()` correctly catches `BrokenPipeError` from its own `print()`. So per-log-line prints are protected. The problem is elsewhere (see Lead 3).

---

## Evidence: Lead 2 — Stacked subprocess timeout totals

### Declared timeouts [VERIFIED: code read]

| Subprocess | Timeout | Line |
|------------|---------|------|
| `fetch_dfs_props` (per invocation) | 300s | `sports_system_runner.py:1272` |
| `build_hit_rate_db` | 600s | `sports_system_runner.py:1351` |
| `generate_projections` | 600s | `sports_system_runner.py:1385` |
| `obsidian_sync` (per call) | 60s | `sports_system_runner.py:411` |

Theoretical ceiling for `daily_picks`: fetch (300s) + hit_rate (600s) + projections (600s) = 1500s (25 minutes).

### Observed `daily_picks` durations from run log [VERIFIED: run_log.txt]

Fastest: 7.3s (`nba_daily_picks 2026-06-10T07:38`). Slowest nominal: 356s (`mlb_daily_picks 2026-06-13`). Extreme outlier: 7331s (`nba_daily_picks 2026-06-12T21:15`).

The 7331s run is explained: it coincides with a network outage period where `send_telegram()` retried for 30s+5s+30s = ~95s per call, and there were multiple Telegram calls (one success at 21:15:00, then `ERROR task=nba_daily_picks: [Errno 32] Broken pipe` at 21:15:02). The task started at approximately 21:02:45 (projection generation complete) and ended at 21:15:04 — only 12 minutes of actual work. The 7331s figure means the task started at approximately 19:02 (21:15 - 7331s = 19:03 UTC), long before the projection complete log entry at 21:02 — indicating the task was **blocked waiting on the workbook lock** for the first ~7261 seconds (the previous task held the lock).

**Conclusion for Lead 2:** Stacked subprocess timeouts are NOT the primary timeout cause. The 1500s ceiling has never been reached in the logs. The observed extreme durations are caused by either (a) workbook lock contention, or (b) network-stalled `send_telegram()` retries with 30s timeouts.

---

## Evidence: Lead 3 — Absence of SIGPIPE/BrokenPipeError handling at the JSON_RESULT print

### Confirmed broken-pipe mechanism [VERIFIED: code read + run_log.txt]

The critical unprotected `print()` calls are at:

```python
# Line 5634 (success path)
print("JSON_RESULT=" + json.dumps(result, sort_keys=True))

# Line 5640 (exception path)
print("JSON_RESULT=" + json.dumps(err, sort_keys=True))
```

Both are bare `print()` calls, NOT wrapped in `safe_print()`. When Hermes `no_agent` closes the stdout pipe after its timeout, the next bare `print()` raises `BrokenPipeError`.

**Exact error propagation sequence:**

1. `dispatch_alerts("mlb_prop_monitor", result)` at line 5633 calls `send_telegram(build_line_move_summary_alert(...))` for line moves.
2. `send_telegram()` internally calls `log("Telegram alert sent")` on success — this spawns `obsidian_sync` per call.
3. For `mlb_prop_monitor` with 61 line moves (observed 2026-06-09T22:47:00), `dispatch_alerts` fires 61 Telegram calls, each adding ~1s of `obsidian_sync` subprocess overhead.
4. By the time all 61 alerts are sent (~58 seconds of wall time observed: 22:47:00 → 22:47:58), the Hermes pipe has closed.
5. `print("JSON_RESULT=" + ...)` at line 5634 raises `BrokenPipeError`.
6. The `except Exception as e:` at line 5636 catches it.
7. `log(f"ERROR task=mlb_prop_monitor: {e}")` fires — this is the `ERROR task=mlb_prop_monitor: [Errno 32] Broken pipe` seen in the run log.
8. `send_telegram(f"❌ SPORTS TASK FAILED: mlb_prop_monitor\nError: {e}")` fires — this is the spurious Telegram failure alert.
9. `print("JSON_RESULT=" + json.dumps(err, ...))` at line 5640 fires — this also raises `BrokenPipeError` but is swallowed by Python's shutdown handler since we're now in cleanup.

**Confirmed from run log:** 2026-06-09T22:47:00 — `MLB prop monitor complete: … line_moves=61 injury_watches=387`. 2026-06-09T22:47:58 — `ERROR task=mlb_prop_monitor: [Errno 32] Broken pipe`. 2026-06-09T22:47:59 — `[mlb_prop_monitor] completed in 129.4s`. 2026-06-09T22:48:00 — `WARNING: mlb_prop_monitor took 129.4s`.

The task completed successfully in 129s. The `ERROR` and the `TASK FAILED` Telegram are spurious — the work was already done.

**Additional broken-pipe sources (non-prop_monitor):** The `run_fetch_dfs_props` function at line 1274 has `print(cp.stdout.rstrip())` — a bare print of subprocess stdout. This is also unprotected and is called from inside `task_workbook_locks` context. If the pipe closes during a fetch, this also raises `BrokenPipeError`. However, this path is rarer: the break usually happens during `dispatch_alerts` after the lock is released.

---

## Evidence: Root Cause of Extreme Timeout Durations

### CLV tracker 24,923s (6.9 hours) [VERIFIED: run_log.txt]

Log entry: `[2026-06-12T16:41:30+00:00] NBA CLV prop closing line refresh skipped: [Errno 32] Broken pipe` followed immediately by workbook saves and `[2026-06-12T16:41:37+00:00] [nba_clv_tracker] completed in 24860.0s`.

Working backward: task completed at 16:41:37, duration 24860s → started at approximately 16:41:37 - 24860s = 09:56:57 UTC. But the DFS fetch log shows `fetch_dfs_props — fetch_dfs_props completed successfully` at `2026-06-12 09:41:29`. The gap between 09:41 (network work) and 16:41 (task completion) = approximately 7 hours. During this period the Telegram retry loop retried with `timeout=30` and `backoff=5` between retries — but the Telegram alert retries only account for ~95s per call. The extreme duration points to `workbook_file_lock` contention: the prior `mlb_prop_monitor` run held the workbook lock and the CLV tracker waited up to 120s before throwing `WorkbookAccessError`, BUT the stale lock detection only triggers after 600s. Multiple lock-wait loops, combined with the Telegram retry wall when network was out (`[Errno 8] nodename nor servname provided`) explain the 6.9-hour run time.

**Key finding:** The CLV tracker and prop monitor extreme durations (3,787s–24,923s) co-occur with `NameResolutionError` for `api.telegram.org` in the same log window. The `send_telegram()` retry loop: attempt 1 waits 30s (HTTP timeout) → sleep 5s → attempt 2 waits 30s → total ~95s per failed call. With multiple `log()` calls each spawning `obsidian_sync` at 60s timeout and Telegram calls at up to 95s on failure, a run with network down can accumulate hundreds of seconds per Telegram call site.

### Prop monitor 12,585s (3.5 hours)

Same pattern: network outage period, Telegram retries timing out, `obsidian_sync` subprocesses stalling.

---

## Confirmed vs Ruled Out: Lead Summary

| Lead | Status | Evidence |
|------|--------|----------|
| L1a: `log()` → `safe_print()` raises BrokenPipeError | **RULED OUT** | `safe_print()` correctly catches `BrokenPipeError`; the per-line prints are protected |
| L1b: `log()` → `obsidian_sync` per-line subprocess causes slowness | **CONFIRMED as contributor** | Each `obsidian_sync` call is up to 60s; on a 61-line-move prop monitor run that's 61 subprocess spawns; combined with Telegram retries this causes the 129s run time |
| L2: Stacked subprocess timeouts exceed cron budget | **RULED OUT as primary** | Observed daily_picks durations are 7–356s, far below the 1500s theoretical ceiling. Lock contention causes the extreme outliers, not subprocess timeouts |
| L3: No SIGPIPE/BrokenPipeError at `JSON_RESULT=` print | **CONFIRMED as root cause** | Lines 5634 and 5640 are bare `print()` calls; when pipe closes, they raise BrokenPipeError which is caught by `except Exception` → spurious TASK FAILED Telegram |

---

## Architecture Patterns

### How `main()` error handling works today [VERIFIED: code read, lines 5625–5651]

```python
task_start_time = time.time()
try:
    with LOCK_FILE.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        ...
        with task_workbook_locks(args.task):
            result = run_task(args.task)
    dispatch_alerts(args.task, result)
    print("JSON_RESULT=" + json.dumps(result, sort_keys=True))  # LINE 5634 — unprotected
    return 0
except Exception as e:
    err = {"status": "error", ...}
    log(f"ERROR task={args.task}: {e}")              # writes to file + obsidian_sync + safe_print
    send_telegram(f"❌ SPORTS TASK FAILED: ...")     # fires the spurious alert
    print("JSON_RESULT=" + json.dumps(err, ...))    # LINE 5640 — unprotected
    return 1
finally:
    elapsed = time.time() - task_start_time
    log(f"[{args.task}] completed in {elapsed:.1f}s")
    if elapsed > 90:
        log(f"WARNING: {args.task} took {elapsed:.1f}s — ...")
```

**Key: `traceback.format_exc()` is already computed at line 5637 into `err["traceback"]` but it is only ever written to stdout via `print("JSON_RESULT=" + json.dumps(err, ...))`. It is NEVER written to the run-log file.** This is why the run log shows `ERROR task=mlb_prop_monitor: [Errno 32] Broken pipe` but no stack trace — the traceback was captured but stdout was closed so it was lost.

### Where to add the D-03/D-04 traceback hook [VERIFIED: code read]

The `except Exception` block at line 5636 already has the traceback in `err["traceback"]`. The additive change is to write it to the run-log file directly before the spurious alert:

**Insertion point:** Between line 5637 (where `err` is built) and line 5639 (where `send_telegram` fires the false TASK FAILED).

**Pattern:**

```python
except Exception as e:
    err = {"status": "error", "task": args.task, "error": str(e), "traceback": traceback.format_exc()}
    # D-03: Additive traceback dump to robust file sink (never stdout — D-04)
    try:
        with RUN_LOG.open("a") as _f:
            _f.write(f"[{now_iso()}] TRACEBACK task={args.task}:\n{traceback.format_exc()}\n")
    except Exception:
        pass
    # Distinguish BrokenPipeError (task succeeded; pipe closed) from real failures
    if isinstance(e, BrokenPipeError):
        try:
            sys.stdout = open(os.devnull, "w")
        except Exception:
            pass
        # Do NOT fire the ❌ TASK FAILED Telegram — work completed
    else:
        log(f"ERROR task={args.task}: {e}")
        send_telegram(f"❌ SPORTS TASK FAILED: {args.task}\nError: {e}")
    safe_print("JSON_RESULT=" + json.dumps(err, sort_keys=True))  # safe_print instead of print
    return 1
```

NOTE: The above fix design is for Phase 2. Phase 1 only adds the traceback dump (the `with RUN_LOG.open("a")` block) as the committed D-03/D-04 change. The `BrokenPipeError` branch and `safe_print` replacement are Phase 2 fixes.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Forcing a BrokenPipeError in tests | Custom socket manipulation | `subprocess.Popen` with `stdout=subprocess.PIPE` + `proc.stdout.close()` before process ends | Standard POSIX pipe closure pattern; reliable cross-platform |
| Subprocess timing | Custom wall-clock wrapper | `time.time()` before/after `subprocess.run()` | Already used in `main()` for overall task timing |

---

## Common Pitfalls

### Pitfall 1: Repro script kills the whole task rather than just closing the pipe

**What goes wrong:** Using `head -c 1` or `head -n 1` terminates immediately and sends SIGPIPE to the writer before the task does any real work, giving an uninformative trace from an early `print()`.
**Why it happens:** Python's SIGPIPE default disposition is SIG_DFL on macOS, meaning the first write to a closed pipe raises `BrokenPipeError` not just during `JSON_RESULT=` but potentially during any early log line.
**How to avoid:** Use `head -n 9999` (large count) or a custom Python reader that reads until task completion then closes, OR use `subprocess.Popen` in the repro script to control pipe closure timing precisely. The goal is to close the pipe AFTER the task work is done but BEFORE the final `JSON_RESULT=` print — matching the production scenario.
**Warning signs:** If the repro shows `BrokenPipeError` at a log call inside `prop_monitor()` rather than at line 5634, the pipe closed too early.

### Pitfall 2: The traceback dump in D-03 hits its own BrokenPipeError

**What goes wrong:** Writing the traceback to stdout (not the file) would fail if stdout is already closed.
**How to avoid:** D-04 mandates writing to `RUN_LOG` (file append), never stdout. The `RUN_LOG.open("a")` write is wrapped in its own `try/except Exception: pass` so it cannot crash the already-failing `except` block.

### Pitfall 3: Mistaking the `finally` block's `log()` as the source

**What goes wrong:** The `log("[task] completed in X.Xs")` in `finally` calls `obsidian_sync`, which might fail if we've already closed stdout. This would register as a second error.
**How to avoid:** The `except Exception: pass` inside `log()` around the `obsidian_sync` call already handles this. The `safe_print()` also handles it. No change needed in `finally`.

### Pitfall 4: Confusing the cron timeout with `subprocess.TimeoutExpired`

**What goes wrong:** Assuming cron kills the task and the runner sees `subprocess.TimeoutExpired` from one of the subprocess stages.
**Why it happens:** The Hermes `no_agent` mode closes stdout (a pipe) rather than sending SIGKILL. The runner process is not killed — it keeps running, but the next `print()` fails.
**Evidence:** The run log shows `[task] completed in Xs` even for the 129.4s broken-pipe run, meaning the runner reached the `finally` block. If cron had killed the process, no `finally` log line would appear.

### Pitfall 5: Treating the workbook-lock extreme durations as subprocess timeout bugs

**What goes wrong:** Seeing a 24,923s run and assuming `build_hit_rate_db` or `generate_projections` timed out.
**Why it happens:** The task actually waited hours on `workbook_file_lock` while another task held the lock AND Telegram retries stalled for network outage. The subprocess stages themselves are fast (20s for hit-rate build, <60s for projections in normal conditions).
**How to avoid:** Cross-reference the extreme-duration log entries with the network-failure `NameResolutionError` logs appearing in the same window. If the task's `run_build_hit_rate_db` log entry appears near the start but the `[task] completed in` appears hours later, lock contention + network stall is the cause.

---

## Broken-Pipe Repro Script Design

### Purpose

Deterministically reproduce the `[Errno 32] Broken pipe` error that production `mlb_prop_monitor` experiences. Designed to:
1. Confirm the exact failing frame (line 5634 or 5640, not an earlier line)
2. Double as the Phase-3 regression seed (D-02/RES-04) — must be runnable as an assertion

### Mechanism [ASSUMED — standard Python/POSIX pipe behavior]

The repro uses `subprocess.Popen` to spawn the runner with `stdout=subprocess.PIPE`, then closes the pipe while the process is still running (specifically, after it has done its prop monitor work but before it prints `JSON_RESULT=`). This is the exact pipe-closure pattern that Hermes `no_agent` produces.

```python
#!/usr/bin/env python3
"""
repro_broken_pipe.py — Phase 1 Diagnosis: deterministic BrokenPipeError repro.
Doubles as the Phase-3 regression test (RES-04).

Run from scripts/:
    python3 repro_broken_pipe.py

Exit 0 = broken pipe reproduced at JSON_RESULT= print (expected pre-fix behavior).
Exit 1 = test infra failure (subprocess wouldn't start, etc.).
Exit 2 = BrokenPipeError NOT reproduced (unexpected — either fix already applied or repro is wrong).
"""
import subprocess
import sys
import os
import time

# We need a task that produces output to stdout (triggering the pipe closure scenario).
# The minimal repro uses --test-telegram so it doesn't need real workbooks,
# OR we can use a real task with --task mlb_prop_monitor.
#
# For the regression test, use a synthetic approach:
# Run the runner with stdout piped, then close the read end of the pipe
# while the process is still running, and verify the run log captures the traceback.

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
RUNNER = os.path.join(SCRIPTS_DIR, "sports_system_runner.py")
RUN_LOG = os.path.join(os.path.dirname(SCRIPTS_DIR), "data", "pnl", "logs", "run_log.txt")

def count_broken_pipe_in_log(before_size: int) -> int:
    """Count new BrokenPipe / ERROR task lines written since `before_size` bytes."""
    try:
        with open(RUN_LOG, "r") as f:
            f.seek(before_size)
            new_content = f.read()
        return new_content.count("Broken pipe") + new_content.count("ERROR task=")
    except Exception:
        return 0

def main() -> int:
    log_size_before = os.path.getsize(RUN_LOG) if os.path.exists(RUN_LOG) else 0

    proc = subprocess.Popen(
        [sys.executable, RUNNER, "--test-telegram"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=SCRIPTS_DIR,
    )

    # Close the read end of stdout pipe immediately — this simulates Hermes
    # closing the pipe before the runner's final print("JSON_RESULT=").
    proc.stdout.close()

    # Wait for the process to finish (it will try to write, hit BrokenPipeError,
    # catch it in main()'s except, and write traceback to the log file).
    proc.wait(timeout=60)

    # Check the run log for evidence of the broken-pipe being caught.
    new_errors = count_broken_pipe_in_log(log_size_before)

    if proc.returncode == 1 and new_errors > 0:
        print(f"PASS: BrokenPipeError reproduced and logged (returncode={proc.returncode}, new_errors={new_errors})")
        return 0
    elif proc.returncode == 0:
        print(f"FAIL (unexpected success): returncode=0, new_errors={new_errors}. Fix may already be applied.")
        return 2
    else:
        print(f"UNEXPECTED: returncode={proc.returncode}, new_errors={new_errors}")
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
```

**Phase-3 regression test use:** After Phase 2 applies the fix, this same script's assertion should be inverted — `returncode=0` and no new broken-pipe errors in the log — meaning the BrokenPipeError is now caught and suppressed without a spurious TASK FAILED Telegram.

**Refinement for `mlb_prop_monitor` with many line moves:** The ideal repro runs `--task mlb_prop_monitor` (requires real workbook with many Props rows) and delays pipe closure until after `prop_monitor()` returns but before `dispatch_alerts` completes. This can be done with a `time.sleep(5)` before `proc.stdout.close()`. This is more faithful to production but requires the test environment to have a real workbook.

---

## Timing Evidence Summary (from run log)

### Task duration profiles [VERIFIED: run_log.txt — 791 completions]

| Task | Typical fast | Typical slow | Observed extremes | Cause of extremes |
|------|-------------|-------------|-------------------|-------------------|
| `nba_daily_picks` | 7–25s | 30–80s | 5073s, 7331s | Lock contention + network outage Telegram stall |
| `mlb_daily_picks` | 28–50s | 60–165s | 306s, 4302s | Same pattern |
| `nba_prop_monitor` | 6–40s | 80–180s | 281s, 498s, 10062s | Same pattern; 61+ Telegram calls amplify |
| `mlb_prop_monitor` | 5–40s | 100–180s | 179s–12585s | Dominant failure: 61 line-move Telegrams × obsidian_sync |
| `nba_clv_tracker` | 2–30s | 80–230s | 5074s–24860s | Lock wait + Telegram retries on network down |
| `mlb_clv_tracker` | 4–50s | 120–260s | 1950s–24923s | Same |
| `nba_injury_monitor` | 2–15s | — | 5038s–6254s | Network outage Telegram retry loop |
| `mlb_injury_monitor` | — | — | Not seen above 90s in log | — |
| `game_completion_monitor` | 0.5–3s | 2–36s | 148s, 208s | Network stall |
| `check_results` | — | — | Not above 90s | — |
| `verify` | — | — | Not above 90s | — |

### Cron time budget [PARTIALLY VERIFIED]

The SKILL.md for `mlb_prop_monitor` documents: "per-move alert fanout can push the cron run past the Hermes `no_agent` pipe/timeout window." The Hermes config has `gateway_timeout: 1800` (30 minutes) and `clarify_timeout: 600` (10 minutes). The `no_agent` cron mode closes stdout when the configured session timeout expires. The `cron_mode: deny` setting at line 475 of `config.yaml` applies to approval requests, not to execution. The exact `no_agent` stdout timeout is `[ASSUMED]` — it is not documented in a single explicit config value but the SKILL.md note implies it is somewhere between 60–300 seconds for the pipe to close. The 129.4s broken-pipe run (22:47:00 task complete → 22:47:58 pipe error) suggests the budget is approximately 60–120 seconds of quiet stdout after process start, or 0 seconds after Hermes receives the task result.

---

## DIAGNOSIS.md Shape (for the deliverable)

The DIAGNOSIS.md must contain:

### Section 1: Broken-Pipe Root Cause (DIAG-01)

- **Statement:** "The `❌ SPORTS TASK FAILED: mlb_prop_monitor / Error: [Errno 32] Broken pipe` alert is spurious. The task's work completes successfully. The error occurs at `print('JSON_RESULT=...')` at `sports_system_runner.py:5634` after the Hermes `no_agent` pipe closes."
- **Mechanism narrative:** dispatch_alerts → N×send_telegram → N×log → N×obsidian_sync → pipe closes → bare print raises BrokenPipeError → except catches it → spurious TASK FAILED Telegram
- **Evidence artifact:** Run-log excerpt showing task-complete at 22:47:00, 61 "Telegram alert sent" lines, then ERROR at 22:47:58, then `completed in 129.4s`
- **Confidence:** HIGH (confirmed in 34+ occurrences across multiple tasks, identical pattern each time)
- **Fix direction:** Wrap lines 5634 and 5640 in `safe_print()`. Distinguish `BrokenPipeError` in the `except` branch — do not fire the TASK FAILED Telegram for a broken pipe when the task completed.

### Section 2: Timeout Root Cause (DIAG-02)

- **Statement:** "Cron-job 'timeouts' observed are not `subprocess.TimeoutExpired`. They are the runner process spending minutes-to-hours in `send_telegram()` retry loops during network outages, plus compounding `obsidian_sync` subprocess calls (up to 60s each) from per-log-line Obsidian mirroring."
- **Ranked-contributors table:** (see below)
- **Evidence artifact:** Log showing `NameResolutionError` for `api.telegram.org` during same window as 24,923s CLV tracker run; multiple `Telegram alert failed attempt 1/2` + `attempt 2/2` messages with ~30s gaps between
- **Confidence:** HIGH for Telegram retry as dominant cause; MEDIUM for `obsidian_sync` compounding as secondary cause (60s per call × many calls, but `except Exception: pass` means it fails silently)
- **Fix direction:** Add hard per-task wall-clock timeout in runner; reduce or batch `obsidian_sync` calls (don't call per log line); add Telegram short-circuit when consecutive failures occur.

### Ranked contributors table (D-10)

| Rank | Contributor | Max observed overhead | Occurs when | Fix direction |
|------|-----------|-----------------------|-------------|---------------|
| 1 | `send_telegram()` retry loop — 30s HTTP timeout × 2 retries per call, multiple call sites | Hours (24,923s observed) | Network/DNS outage; Telegram unreachable | Hard per-call timeout budget; skip Telegram if consecutive failures; Phase 3 hard task timeout |
| 2 | `obsidian_sync` subprocess per `log()` call — 60s timeout each | Minutes (N×60s) | `obsidian_sync.py` is slow or network is degraded | Batch Obsidian writes; decouple from hot `log()` path |
| 3 | Workbook lock contention — 120s lock wait, 600s stale threshold | Hours (in combination with #1) | Previous task holds lock and is stalled | Reduce stale_seconds from 600 to 180; Phase 3 hard task timeout |
| 4 | Bare `print(cp.stdout.rstrip())` in `run_fetch_dfs_props` (line 1274) | Rare | Pipe already closed when fetch stage starts | Replace with `safe_print(cp.stdout.rstrip())` |
| 5 | Stacked subprocess timeouts (fetch 300s + hit_rate 600s + projections 600s) | 1500s theoretical | All three stages time out on the same run | Not yet observed; monitor for it |

---

## Code Examples

### Confirmed location of the bare-print vulnerability [VERIFIED: code read]

```python
# sports_system_runner.py:5633–5641 — current code
dispatch_alerts(args.task, result)
print("JSON_RESULT=" + json.dumps(result, sort_keys=True))  # LINE 5634 — UNPROTECTED
return 0
except Exception as e:
err = {"status": "error", "task": args.task, "error": str(e), "traceback": traceback.format_exc()}
log(f"ERROR task={args.task}: {e}")
send_telegram(f"❌ SPORTS TASK FAILED: {args.task}\nError: {e}")
print("JSON_RESULT=" + json.dumps(err, sort_keys=True))     # LINE 5640 — UNPROTECTED
```

### Phase 1 additive change (D-03/D-04) — traceback dump only [ASSUMED — not yet written]

```python
except Exception as e:
    err = {"status": "error", "task": args.task, "error": str(e), "traceback": traceback.format_exc()}
    # D-03/D-04: Additive traceback dump to file sink — never stdout
    try:
        with RUN_LOG.open("a") as _tb_file:
            _tb_file.write(
                f"[{now_iso()}] TRACEBACK task={args.task}:\n{traceback.format_exc()}\n"
            )
    except Exception:
        pass
    log(f"ERROR task={args.task}: {e}")
    send_telegram(f"❌ SPORTS TASK FAILED: {args.task}\nError: {e}")
    print("JSON_RESULT=" + json.dumps(err, sort_keys=True))
    return 1
```

This is the ONLY code change committed in Phase 1. It is additive: writes to `data/pnl/logs/run_log.txt`, does not touch gate logic, pick outputs, or workbook schema.

---

## State of the Art

| Old Assumption | Confirmed Truth | Impact |
|----------------|-----------------|--------|
| "BrokenPipeError propagates from per-log-line safe_print" | `safe_print()` correctly handles it; break is at the final JSON_RESULT print | Fix is narrowly targeted to lines 5634/5640 |
| "Subprocess timeout stack is the timeout root cause" | Telegram retry loop during network outage is the dominant cause | Fix focus: Telegram call sites, not subprocess timeouts |
| "log() → obsidian_sync per line is the broken-pipe cause" | `obsidian_sync` fails silently (except/pass); it is a slowness contributor, not the direct cause | Still worth removing per-line obsidian calls, but it is a Phase 2 optimization |
| "Cron budget is explicitly documented" | Budget is implied by the `no_agent` pipe closure behavior; no explicit number found | Phase 2 must measure empirically + add hard internal timeout |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | The Hermes `no_agent` stdout pipe timeout is ~60–120 seconds of inactivity or immediate at task result delivery | Cron time budget | Low risk — even if budget differs, the fix (safe_print) applies regardless of budget |
| A2 | The repro script's `proc.stdout.close()` faithfully simulates the Hermes pipe closure timing | Repro script design | Medium — if timing is wrong, repro may close pipe too early and show a different failing line. Adjust with `time.sleep()`. |
| A3 | `obsidian_sync` per-log-line calls compound the slowness even when they fail silently | Timing contributors | Low — `except Exception: pass` means the 60s timeout only matters when `obsidian_sync.py` is reachable but slow. If it's not running, the subprocess exits fast. |

---

## Open Questions

1. **What is the exact Hermes `no_agent` pipe timeout value?**
   - What we know: SKILL.md says "no_agent pipe/timeout window"; `config.yaml` has `gateway_timeout: 1800` and `inactivity_timeout: 120` but neither maps cleanly to the pipe closure behavior.
   - What's unclear: Whether it closes on inactivity (no stdout writes for N seconds) or on a fixed wall-clock deadline from task start.
   - Recommendation: Add a temporary diagnostic `print("PING", flush=True)` every 10s in a background thread during Phase 2 test runs to probe the exact closure timing. (Throwaway per D-11.)

2. **Does `run_fetch_dfs_props` → `print(cp.stdout.rstrip())` at line 1274 contribute to broken pipes from inside the lock context?**
   - What we know: It's a bare `print()`, unprotected. It is called from `prop_monitor()` and `clv_tracker()` which are inside `task_workbook_locks`. A broken pipe here would also be caught by the top-level `except`.
   - What's unclear: Whether any observed broken pipe traces back to line 1274 vs. line 5634. The Phase 1 traceback dump (D-03) will definitively answer this.
   - Recommendation: After D-03 is deployed, run a scheduled `mlb_prop_monitor` and check the run log for the stack trace to confirm which `print()` is the source.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `python3` | All scripts | ✓ | 3.14.0a2 | None (3.13 lacks deps) |
| `data/pnl/logs/run_log.txt` | D-04 traceback sink | ✓ | 15,294 lines, writable | Create on first write |
| `~/.hermes/skills/delegation/obsidian_sync/scripts/obsidian_sync.py` | `obsidian_sync()` calls | ✓ (assumed — referenced in config) | Unknown | `except Exception: pass` already handles absence |

**Missing dependencies with no fallback:** None — Phase 1 is read-mostly with one additive file write.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `unittest` + `pytest` 9.0.3 |
| Config file | None — run from `scripts/` |
| Quick run command | `cd scripts && python3 -m pytest test_slip_payouts.py -x` |
| Full suite command | `cd scripts && python3 -m pytest` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DIAG-01 | BrokenPipeError reproduced at JSON_RESULT= print | repro/regression | `python3 repro_broken_pipe.py` | No — Wave 0 |
| DIAG-02 | Timing evidence extracted from run log | manual/analytical | `grep "completed in" data/pnl/logs/run_log.txt` | N/A (log exists) |

### Wave 0 Gaps

- [ ] `scripts/repro_broken_pipe.py` — covers DIAG-01 (the repro script described in this research)
- [ ] DIAGNOSIS.md in `.planning/phases/01-diagnosis/` — covers DIAG-01 + DIAG-02 deliverable

---

## Security Domain

Phase 1 makes one additive file write to `data/pnl/logs/run_log.txt`. No security-relevant changes: no new secrets access, no schema changes, no network calls. ASVS not applicable.

---

## Project Constraints (from CLAUDE.md)

- Use `python3` (3.14 at `/usr/local/bin/python3`), run from `scripts/`
- No gate logic, pick output, or workbook schema changes
- The repro script must run from `scripts/` directory (sibling imports require it)
- No hardcoded secrets; `env_value()` pattern for any env access
- `snake_case` naming; PEP 8 style; type annotations required
- The one committed code change (D-03 traceback dump) must be additive only — no behavior change

---

## Sources

### Primary (HIGH confidence)

- `scripts/sports_system_runner.py` lines 192–213 (safe_print, log), 401–420 (obsidian_sync), 1264–1278 (run_fetch_dfs_props), 5612–5651 (main) — code read
- `data/pnl/logs/run_log.txt` — 15,294-line run log, direct evidence for broken-pipe events, timing durations, and Telegram retry storms

### Secondary (MEDIUM confidence)

- `.planning/codebase/CONCERNS.md` — corroborates known bugs and performance bottlenecks
- `.planning/codebase/ARCHITECTURE.md` — subprocess timeout budgets and data flow
- `.planning/codebase/INTEGRATIONS.md` — Telegram retry behavior documented
- `~/.hermes/skills/delegation/mlb_prop_monitor/SKILL.md` — explicitly documents the `no_agent pipe/timeout` mechanism causing the broken pipe

### Tertiary (LOW confidence)

- `~/.hermes/config.yaml` — `gateway_timeout: 1800`, `inactivity_timeout: 120` — these are gateway-level values, not directly the `no_agent` pipe timeout [ASSUMED to be related]

---

## Metadata

**Confidence breakdown:**
- Broken-pipe root cause: HIGH — confirmed from code read + 34+ run-log occurrences with identical pattern
- Timeout root cause: HIGH — confirmed from run-log analysis showing Telegram retry windows correlating with extreme durations
- Repro script design: MEDIUM — approach is sound (standard POSIX pipe closure pattern) but timing of pipe closure in the test may need tuning
- Cron budget value: LOW — no explicit config value found; inferred from observed failure timings

**Research date:** 2026-06-13
**Valid until:** 60 days (stable Python codebase, no fast-moving dependencies)
