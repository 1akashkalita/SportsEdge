# Phase 3: Resilience — Research

**Researched:** 2026-06-20
**Domain:** Python subprocess retry, signal handling, per-task timeouts, regression test rigor
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Retry policy & budget (RES-01)**
- D-01: Retries live at the runner level — re-run the whole subprocess.
- D-02: Re-run on hard failures only (non-zero exit or TimeoutExpired). Exit 0 with empty rows is NOT retried.
- D-03: Budget = 1 re-run, short backoff.
- D-04: Telegram and Odds-API.io are left as-is (already retried by Phase 2 / existing client).

**Hard timeout design (RES-03)**
- D-05: Per-task budgets, not a single global cap. Anchor to 01-TIMING-EVIDENCE.md.
- D-06: On timeout — distinct `⏱ TASK TIMED OUT` alert + error log, separate from `❌ SPORTS TASK FAILED`.
- D-07: Timeout mechanism and mid-write safety are Claude's discretion (see below).

**Pipe-error reclassification (RES-02)**
- D-08: Reclassify only when the task body completed. Track a "result computed" flag.
- D-09: No explicit OS-level SIGPIPE handler. Python already raises BrokenPipeError.

**Regression-test scope (RES-04)**
- D-10: Scope = both audit (Phase-2 tests) and add (Phase-3 new behaviors).
- D-11: Rigor = fault-injection by construction. Test cannot pass without the fix.

### Claude's Discretion
- Timeout mechanism (signal.SIGALRM vs watchdog thread) — research resolves this below.
- Exact per-task budget values.
- Retry backoff seconds.
- Precise `⏱ TASK TIMED OUT` / warning wording.

### Deferred Ideas (OUT OF SCOPE)
- In-fetcher (per-HTTP-call) retry for PrizePicks/Underdog/ESPN.
- Retrying empty-but-clean fetch results.
- Pattern-aware alerting ("task failed N times in a row") — Phase 4 (OBS-03).
- Structured run-log records + health/heartbeat — Phase 4 (OBS-01/OBS-02).
- CI running the suite on every change — Phase 5 (CI-01/CI-02).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| RES-01 | Outbound network calls retry with backoff on transient failures instead of failing the whole task | D-01..D-03: subprocess re-run wraps run_fetch_dfs_props, run_build_hit_rate_db, run_generate_projections at the `subprocess.run()` call site |
| RES-02 | Broken-pipe / SIGPIPE conditions handled gracefully — logged and tolerated when non-fatal | D-08/D-09: "result computed" flag approach confirmed against actual main() structure; BrokenPipeError is already Python-level |
| RES-03 | Each task enforces a hard internal time budget; hung stage exits cleanly | D-05/D-06/D-07: SIGALRM is the recommended primitive; orphan kill required; per-task budgets derived from timing evidence |
| RES-04 | Every reliability fix lands with a regression test failing before / passing after | D-10/D-11: Phase-2 tests audited; Phase-3 new test stubs specified with fault-injection patterns |
</phase_requirements>

---

## Summary

Phase 3 adds a general safety net on top of the named-offender fixes Phase 2 already shipped. All four requirements are confined to making transient faults tolerated rather than fatal. The codebase is well-understood from Phase 1 diagnosis and Phase 2 implementation — the code under change is small and the integration points are precisely located.

The most consequential architectural decision is the RES-03 timeout primitive. Research confirms `signal.SIGALRM` is the correct choice for this architecture. It is available and tested working on macOS Python 3.14.0a2, it fires the handler on the main thread (where all task work runs — no threading in the runner), and it cleanly interrupts every blocking call that matters: `subprocess.run()`, `fcntl.flock()`, `time.sleep()`. The one real concern — subprocess child orphaning when SIGALRM fires mid-`subprocess.run()` — is a concrete, solvable problem: the timeout handler must kill the in-flight subprocess before raising, which requires tracking the active Popen object. This is the only non-trivial implementation detail.

RES-01 subprocess re-run is minimal: wrap three `subprocess.run()` call sites in a `_run_with_retry()` helper. The existing `run_build_hit_rate_db()` / `run_generate_projections()` already handle non-zero exit gracefully (they return a result dict and log); the only new behavior is: on non-zero exit or TimeoutExpired, sleep a short backoff and try once more. The distinction between "hard failure" (retry) and "empty-but-clean" (don't retry) is already implicit in the exit-code contract these stages use.

RES-02 pipe reclassification is a small surgical change to `main()`'s try/except: add a `_task_result: dict | None = None` sentinel set to the result dict immediately after `run_task()` returns, and check it in the except branch.

**Hermes cron kill window — CONFIRMED HARD 120 s (orchestrator-verified 2026-06-20, supersedes the earlier "likely overridden" guess).** All 12 sports jobs in `~/.hermes/cron/jobs.json` are `no_agent: True` with **no per-job timeout override**. `no_agent` jobs execute via `_run_job_script()` (`scheduler.py:1399`) which runs `subprocess.run(argv, timeout=_get_script_timeout())` (`scheduler.py:1048-1056`). `_get_script_timeout()` resolves to `_DEFAULT_SCRIPT_TIMEOUT = 120` because **none** of its override sources are set: `HERMES_CRON_SCRIPT_TIMEOUT` env var is unset, the `cron:` block in `~/.hermes/config.yaml` has **no** `script_timeout_seconds` key, and the `_SCRIPT_TIMEOUT` module global is unpatched. The wrapper (`~/.hermes/scripts/mlb_daily_picks_cron.py`) runs `sports_system_runner.py` **synchronously** and propagates its exit code — so the 120 s applies to the whole task. This is a **hard wall-clock `subprocess.run` timeout**, NOT the agent-path *inactivity* timeout — emitting output does **not** reset it. The 1,128 s / 7,697 s durations in `01-TIMING-EVIDENCE.md` were the 2026-06-15 network-storm backlog (lock contention + Telegram retries); under the 120 s window those runs were killed by Hermes at 120 s while the orphaned runner kept churning and logged its own `completed in …` line. **Consequence: every RES-03 budget MUST sit below 120 s with enough headroom (~30 s) for the clean-shutdown sequence (subprocess kill + the `⏱ TASK TIMED OUT` Telegram, which can itself take up to ~30 s if the network is down + log/JSON flush) to finish before Hermes's hard kill.** An 1800 s budget (the earlier draft) would never fire.

**Primary recommendation:** Use `signal.SIGALRM` for RES-03 with an active subprocess kill in the timeout handler. The `safe_save_workbook()` atomic-save invariant (`workbook_io.py:154-165`) confirms interrupt-anywhere is safe for workbook writes.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Subprocess retry (RES-01) | Orchestrator (`sports_system_runner.py`) | — | The runner spawns subprocesses; retry wraps the invocation, not the fetcher internals (D-01) |
| Pipe-error reclassification (RES-02) | Orchestrator `main()` try/except | — | The except branch is the only place that can distinguish completed vs. failed before firing Telegram alert |
| Hard task timeout (RES-03) | Orchestrator `main()` try block | — | Wraps the lock+workbook acquisition + run_task() call; all task work is on main thread |
| Regression tests (RES-04) | `scripts/test_res*.py` + audit of `test_fix01/02/def01/02` | — | Plain `unittest`, same home as Phase-2 tests (D-10/D-11) |

---

## Standard Stack

### Core (no new packages required)
| Module | Source | Purpose |
|--------|--------|---------|
| `signal` (stdlib) | Already imported via stdlib | `signal.SIGALRM` for RES-03 timeout primitive |
| `threading.Timer` | Already imported (stdlib) | Fallback approach if SIGALRM has unexpected issue |
| `time.sleep` | Already used | Retry backoff in RES-01 |
| `subprocess` | Already imported | Existing subprocess stages; retry wraps these |
| `unittest`, `unittest.mock.patch` | Already used | Fault-injection regression tests (RES-04) |

**Phase 3 requires zero new package installations.** Everything needed is stdlib or already present.

---

## Package Legitimacy Audit

> No external packages are installed in this phase. All work uses stdlib and existing project dependencies (`requests`, `openpyxl`). This section is intentionally empty.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

---

## Architecture Patterns

### System Architecture Diagram

```
Hermes cron scheduler
  → subprocess.run(sports_system_runner.py --task X)
       [RES-03: signal.SIGALRM timer wraps this entire invocation's internals]
       main() [try block]
         reset _telegram_breaker, _task_log_lines
         _task_result = None                     ← [RES-02: sentinel]
         LOCK_FILE fcntl.LOCK_EX
           task_workbook_locks(task)
             run_task(task)
               daily_picks() / prop_monitor() / …
                 [RES-01] run_fetch_dfs_props()  → retry wrapper → subprocess.run(fetch_dfs_props.py, timeout=300)
                 [RES-01] run_build_hit_rate_db() → retry wrapper → subprocess.run(build_hit_rate_db.py, timeout=600)
                 [RES-01] run_generate_projections() → retry wrapper → subprocess.run(generate_projections.py, timeout=600)
               return result
             _task_result = result               ← [RES-02: flag set here, AFTER run_task returns]
         dispatch_alerts(task, result)           ← [RES-02: BrokenPipeError here = completed task]
         safe_print("JSON_RESULT=...")           ← [RES-02: BrokenPipeError here = completed task]
         return 0
       [except Exception as e:]
         if _task_result is not None and isinstance(e, BrokenPipeError):
             log("WARNING: BrokenPipeError after task completion — pipe closed by cron wrapper")
             # [RES-02] suppress TASK FAILED alert, exit clean
         else:
             send_telegram("❌ SPORTS TASK FAILED: …")  ← real failure: still fires
       [finally:]
         cancel SIGALRM timer                    ← [RES-03: always cancel]
         log elapsed, slow-run warning, suppressed count
         Obsidian end-of-task sync
```

### Recommended Project Structure

No new directories required. All Phase-3 additions are additive to existing files:

```
scripts/
├── sports_system_runner.py    # RES-01 retry wrappers + RES-02 flag + RES-03 timer
├── test_res01_subprocess_retry.py   # NEW: RES-01 regression (monkeypatch subprocess fail)
├── test_res02_pipe_reclassify.py    # NEW: RES-02 regression (pipe close after completion)
├── test_res03_task_timeout.py       # NEW: RES-03 regression (hung stage → timeout fires)
├── test_fix01_broken_pipe.py        # AUDIT: already passes/fails correctly
├── test_fix02_telegram_circuit_breaker.py  # AUDIT: already passes/fails correctly
├── test_def01_no_duplicate_defs.py  # AUDIT: already passes/fails correctly
└── test_def02_path_resolution.py    # AUDIT: already passes/fails correctly
```

---

## Q1: RES-03 Timeout Primitive — Recommendation

### SIGALRM — RECOMMENDED

**Mechanism:** `signal.signal(signal.SIGALRM, handler)` + `signal.alarm(N)` before entering the task; `signal.alarm(0)` in `finally` to cancel.

**Verified behavior on macOS Python 3.14.0a2:**

| Blocking call | SIGALRM interrupts? | Evidence |
|---------------|---------------------|---------|
| `subprocess.run()` | YES — raises handler exception | Tested: `SIGALRM interrupted subprocess.run()` |
| `fcntl.flock()` (LOCK_EX) | YES — raises handler exception | Tested: `SIGALRM interrupts fcntl.flock() - YES` |
| `time.sleep()` | YES — raises handler exception | Tested: `SIGALRM interrupts time.sleep() - YES` |

[VERIFIED: direct test on Python 3.14.0a2, macOS]

**Thread safety:** `signal.signal()` and `signal.alarm()` must be called from the main thread. All task work in `run_task()` and `main()` runs on the main thread — confirmed by grepping the runner: no `threading.Thread`, no `concurrent.futures` in `sports_system_runner.py`. The SIGALRM handler fires on the main thread (verified: `fired_thread=['MainThread']`).

**Python 3.14 alpha specifics:** No gotchas found. `signal.SIGALRM` and `signal.alarm()` are present and function correctly. `signal.alarm(0)` cancels cleanly — tested with 1.5-second sleep after cancel with no spurious fire.

**Critical hole — subprocess child orphaning:**

When SIGALRM fires during `subprocess.run()` (e.g., during `run_fetch_dfs_props`, `run_build_hit_rate_db`, or `run_generate_projections`), the child process is **orphaned**. `subprocess.run()` internally does `Popen() + wait()`; when the SIGALRM handler raises and unwinds the stack, the `subprocess.run()` internal `finally` block for `subprocess.TimeoutExpired` is NOT reached (SIGALRM is not `TimeoutExpired`), so the child is never killed.

Tested directly: `Child process {pid} is STILL RUNNING (orphaned!)` after SIGALRM fires during `proc.wait()`.

**Required mitigation:** Track the currently-running subprocess `Popen` object in a module-level variable. The SIGALRM handler kills it before raising. Pattern:

```python
# Module level
_current_subprocess: subprocess.Popen | None = None

def _sigalrm_handler(signum: int, frame: Any) -> None:
    global _current_subprocess
    if _current_subprocess is not None:
        try:
            _current_subprocess.kill()
            _current_subprocess.wait(timeout=5)
        except Exception:
            pass
        _current_subprocess = None
    raise TaskTimeoutError(f"Task exceeded wall-clock budget")

# In each subprocess stage wrapper:
def _run_stage_with_retry(cmd, timeout, ...):
    global _current_subprocess
    cp = subprocess.Popen(cmd, ...)
    _current_subprocess = cp
    try:
        cp.wait(timeout=timeout)
        _current_subprocess = None
        # read output ...
    except subprocess.TimeoutExpired:
        _current_subprocess = None
        cp.kill()
        cp.wait()
        raise
```

[ASSUMED: the pattern above is the right approach — verified that orphaning occurs and a kill is needed, but the specific implementation shape is a planning decision]

**Mid-write safety (D-07 — confirmed):**

`safe_save_workbook()` in `workbook_io.py:147-165` follows this sequence:
1. `wb.save(tmp)` — writes to temp file `{path}.tmp.{pid}.xlsx`
2. `zipfile.is_zipfile(tmp)` — validates temp
3. `load_workbook(tmp, read_only=True)` — validates further
4. `shutil.copy2(path, backup_path)` — backs up original
5. `os.replace(tmp, path)` — single atomic syscall

An interrupt at any point in this sequence leaves:
- Before `os.replace`: original workbook intact + orphaned `.tmp` file (cleaned by `finally:` block at line 168)
- After `os.replace`: new workbook in place (complete)

**The `finally:` block at `workbook_io.py:168-173` already cleans the `.tmp` file** — even on exception. `os.replace()` is atomic (POSIX), so the workbook is either old-intact or new-complete, never torn. **Interrupt-anywhere is safe.** The `save_workbook_atomic` path also follows this same pattern. [VERIFIED: read actual code at workbook_io.py:147-165]

**Conclusion: interrupt-anywhere design is correct.** The save invariant holds.

### SIGALRM vs. threading.Timer — Decision

| Property | signal.SIGALRM | threading.Timer |
|----------|---------------|----------------|
| Interrupts blocking subprocess.run() | YES (tested) | NO — fires on a daemon thread, cannot interrupt main-thread blocking calls |
| Interrupts fcntl.flock() | YES (tested) | NO — same reason |
| Requires main thread | YES | NO — but the interrupt problem makes this moot |
| Subprocess orphan risk | YES — needs explicit kill in handler | n/a — can't interrupt anyway |
| Complexity | Medium (handler + global state) | Higher (event-based polling needed, which defeats the purpose) |

**threading.Timer is NOT viable for RES-03** because it fires on a background thread and cannot interrupt the main thread's blocking calls. A timer thread could only signal the main thread (e.g., via `os.kill(os.getpid(), signal.SIGUSR1)`) — which is just SIGALRM with extra steps.

**Use SIGALRM.** The orphan mitigation (track `_current_subprocess`, kill in handler) is the only extra complexity, and it is straightforward.

**Fallback if SIGALRM has unexpected interaction:** `threading.Timer` + `os.kill(os.getpid(), signal.SIGUSR1)` in the timer callback, with a custom `SIGUSR1` handler that does the same kill+raise. Same behavior, one more hop. Use only if SIGALRM proves unreliable in production (unlikely — tested working).

---

## Q2: RES-01 Subprocess Re-Run — Exact Seam

### Current subprocess invocations (verified against actual code)

**`run_fetch_dfs_props()` — `sports_system_runner.py:1278-1292`**
```python
cp = subprocess.run(cmd, text=True, capture_output=True, timeout=300)
if cp.stdout:
    safe_print(cp.stdout.rstrip())
if cp.stderr:
    print(cp.stderr.rstrip(), file=sys.stderr)
if cp.returncode != 0:
    raise RuntimeError(f"fetch_dfs_props failed for {sport}: exit={cp.returncode}")
```
- **Hard failure detection:** `cp.returncode != 0` → `RuntimeError`. `subprocess.TimeoutExpired` propagates as-is.
- **Empty-but-clean:** exit 0 with no output or zero rows in JSON files → function returns without raising. This is a legitimate empty board (D-02: do NOT retry).
- **Retry seam:** wrap the `subprocess.run()` call (not the RuntimeError) in a helper. The helper catches `returncode != 0` OR `TimeoutExpired` and re-runs once after backoff.

**`run_build_hit_rate_db()` — `sports_system_runner.py:1359-1374`**
```python
cp = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
if cp.returncode != 0:
    log(f"... hit-rate build failed: exit={cp.returncode} ...")
    return {"status": "failed", ...}
```
- **Hard failure detection:** `cp.returncode != 0` → returns `{"status": "failed"}` (does NOT raise). `TimeoutExpired` propagates.
- **Empty-but-clean:** exit 0 with JSON result → `{"status": "ok"}`. Do not retry.
- **Retry seam:** The caller (`daily_picks()`) currently doesn't check for `{"status": "failed"}` and continues. Retry should happen inside `run_build_hit_rate_db()` before it returns, or in a wrapper around it. The wrapper pattern (same as D-01) is cleaner: wrap the `subprocess.run()` call.

**`run_generate_projections()` — `sports_system_runner.py:1393-1408`**
```python
cp = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
if cp.returncode != 0:
    log(f"... projection generation failed: exit={cp.returncode} ...")
    return {"status": "failed", ...}
```
- Same structure as `run_build_hit_rate_db()`. Same retry seam.

### Retry helper pattern

```python
# Fits the three call sites without changing return types or caller logic
def _subprocess_run_with_retry(
    cmd: list[str],
    *,
    timeout: int,
    backoff: int,
    context: str,
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    """Run subprocess, retry once on hard failure. Propagates on second failure."""
    for attempt in range(2):
        try:
            cp = subprocess.run(cmd, **kwargs, timeout=timeout)
        except subprocess.TimeoutExpired:
            if attempt == 0:
                log(f"WARNING: {context} timed out (attempt 1/2); retrying in {backoff}s")
                time.sleep(backoff)
                continue
            raise
        if cp.returncode != 0:
            if attempt == 0:
                log(f"WARNING: {context} exited {cp.returncode} (attempt 1/2); retrying in {backoff}s")
                time.sleep(backoff)
                continue
        return cp
    # Never reached (loop always returns or raises)
    raise RuntimeError(f"{context}: unreachable retry path")
```

**Backoff recommendation:** 5 seconds. Rationale:
- Fast enough to not meaningfully delay a healthy run (5s overhead on retry).
- Long enough for a transient DNS/connection failure to self-resolve.
- Keeps worst-case added latency per stage at 5s, well within even the tightest task budget.
- The `odds_api_io_client.py` uses `backoff=1` for its internal retry (line ~254). The subprocess re-run is a heavier operation (whole stage restarts), so 5s is more appropriate.

[ASSUMED: 5-second backoff is appropriate — no authoritative source constrains this]

### Hard failure vs. empty-but-clean distinction

| Condition | `returncode` | `TimeoutExpired` | Retry? | Reason |
|-----------|-------------|-------------------|--------|--------|
| Network failure mid-fetch | non-zero | no | YES | Fetcher exits non-zero on request error |
| Timeout (hung stage) | n/a | YES | YES | Transient hang |
| Empty board (no games today) | 0 | no | NO | Legitimate; retrying wastes time and creates duplicate log noise |
| Silent data degradation (exit 0, partial data) | 0 | no | NO | D-02: accepted trade-off |

### Worst-case latency budget

The per-stage subprocess timeouts (300 / 600 / 600 s) and the "with 1 re-run" stacked figure
(3,015 s) are **theoretical and unreachable under cron** — Hermes hard-kills the whole task at
120 s (see Q3), so no individual stage timeout can ever fully elapse in a cron run. They matter
only for manual `run_all_tasks.py` invocations.

What matters for cron: under normal conditions (fetch <5 s, hit-rate ~20 s, projections ~2 s) a
single re-run adds ~5 s backoff + a repeat of one fast stage — comfortably inside the 120 s window
and inside the RES-03 task budget (~90 s for daily_picks). The retry is **opportunistic within the
budget**, not sized against the stage ceilings. The SIGALRM task budget is the real backstop: if a
stage genuinely hangs, the RES-03 alarm fires at the task budget and the handler kills the in-flight
subprocess (orphan mitigation, Q1) — the retry loop never gets a second attempt because
`TaskTimeoutError` unwinds past it (see ordering note in Code Examples).

[VERIFIED: stage timeouts from code at lines 1286, 1365, 1399; Hermes 120 s kill confirmed in Q3]

---

## Q3: RES-03 Per-Task Budget Values

### Hermes cron kill window — CONFIRMED HARD 120 s [VERIFIED 2026-06-20, orchestrator]

> This subsection was rewritten after the initial draft. The earlier draft *assumed* the
> window was >1800 s ("likely overridden"). Direct inspection of the live Hermes install
> disproves that: the window is a **hard 120 s** and there is **no override**.

**The verified chain (every link inspected on this machine):**

1. **All 12 sports jobs are `no_agent: True`** with **no per-job timeout** (`~/.hermes/cron/jobs.json` — confirmed for `mlb_daily_picks`, `nba_daily_picks`, all prop/injury/clv monitors, `check_results`; `timeout` keys empty on every one).
2. **`no_agent` jobs run via `_run_job_script()`** — `scheduler.py:1362` ("no_agent short-circuit — the script IS the job") → `scheduler.py:1399` calls `_run_job_script(script_path)`.
3. **`_run_job_script()` hard-kills at `_get_script_timeout()`** via `subprocess.run(argv, capture_output=True, timeout=script_timeout)` (`scheduler.py:1048-1056`); on expiry it returns `"Script timed out after {script_timeout}s"` (`scheduler.py:1078-1079`).
4. **`_get_script_timeout()` returns 120** (`scheduler.py:924-954`): the module global `_SCRIPT_TIMEOUT` is unpatched (== default), `HERMES_CRON_SCRIPT_TIMEOUT` is **unset**, and `~/.hermes/config.yaml`'s `cron:` block has **no** `script_timeout_seconds` key → falls through to `_DEFAULT_SCRIPT_TIMEOUT = 120` (`scheduler.py:919`).
5. **The wrapper runs the runner synchronously.** `~/.hermes/scripts/mlb_daily_picks_cron.py` is literally `raise SystemExit(subprocess.run([python3, sports_system_runner.py, --task, mlb_daily_picks]).returncode)` — no backgrounding, exit code propagated. So the 120 s governs the entire task.

**This is a HARD wall-clock timeout, not an inactivity timeout.** `subprocess.run(timeout=120)` kills at 120 s of wall-clock regardless of how much stdout the task produces. (The *inactivity*-based 600 s timeout at `scheduler.py:1805` — `HERMES_CRON_TIMEOUT`, output resets it — applies only to the LLM/agent path, which `no_agent` jobs skip entirely.) Any earlier reasoning that "daily_picks survives because it emits `JSON_RESULT=` within the window" is wrong for `no_agent` jobs.

**Why the timing evidence showed 1,128 s / 7,697 s "completions":** those are the 2026-06-15 network-outage backlog (lock contention + Telegram retry storm, `01-TIMING-EVIDENCE.md:101-124`). Under a 120 s hard kill, Hermes killed the *wrapper* at 120 s; the *grandchild* runner was orphaned, kept running, and wrote its own `completed in 1128 s` line to the run log. Hermes had already declared the job timed out. This reconciles the contradiction and is exactly the "cron-job timeouts / spurious TASK FAILED" symptom this milestone exists to fix.

**`01-TIMING-EVIDENCE.md:194` had this `[ASSUMED]` as "approximately 60–120 s" — it is now CONFIRMED at exactly 120 s.**

### Sizing constraint (the hard rule for RES-03 budgets)

Every per-task budget **must be < 120 s**, and must leave headroom for the clean-shutdown
sequence so the task self-terminates *before* Hermes's hard kill:

- SIGALRM handler kills the in-flight subprocess + `wait(timeout=5)` → up to ~5 s
- `⏱ TASK TIMED OUT` Telegram alert → up to ~30 s worst case if the network is down at
  timeout (10 s/call × the Phase-2 3-strike breaker), typically <1 s
- error log + `JSON_RESULT=` flush → negligible

**Reserve ~30 s of headroom.** Practical ceiling for the slowest task ≈ **90 s**; faster
task-classes tighter (D-05's "monitors/verify tight"). Anchor to **post-Phase-2 clean medians**,
NOT the raw p75s in `01-TIMING-EVIDENCE.md` — those p75s are storm-contaminated (Telegram
retries) and the obsidian-decouple fix already removed ~58 s/run from prop_monitor
(`01-TIMING-EVIDENCE.md:181`, `876`).

**Structural caveat for the operator (out of Phase-3 scope, but flag it in the plan):** any task
whose *clean* runtime can exceed ~120 s is structurally incompatible with the current Hermes
window regardless of RES-03 — RES-03 only makes that failure *clean and labeled* instead of an
opaque Hermes kill. `mlb_daily_picks` (clean median 44 s, but stacks fetch+hitrate+projections
subprocess stages) and `mlb_prop_monitor` are closest to the edge. If legitimately-slow runs
start tripping RES-03, the real remedy is raising the Hermes cron timeout
(`cron.script_timeout_seconds` in `~/.hermes/config.yaml`, or `HERMES_CRON_SCRIPT_TIMEOUT`) —
a Hermes-config change *outside* the sports_picks repo and outside this phase's minimal-invasive
boundary.

### Per-task budget recommendations

**Hard constraint (see kill-window section above): every budget < 120 s, ~30 s shutdown
headroom → practical ceiling ~90 s.** All raw p75s in `01-TIMING-EVIDENCE.md` are
storm-contaminated; anchor to **post-Phase-2 clean medians** (strip Telegram-retry and the
already-removed ~58 s/run obsidian overhead). The old 300/600/1800 s budgets below were
relics of the wrong-kill-window draft and are **rejected** — they would never fire before
Hermes's 120 s kill.

The 1,500 s subprocess ceiling (fetch 300 + hitrate 600 + projections 600) and the 3,015 s
"with retry" figure from Q2 are **theoretical and moot under cron**: Hermes kills at 120 s, so
those stage timeouts can never actually elapse in a cron run. They matter only for manual runs.
RES-01's 1 re-run + ~5 s backoff is opportunistic *within* the 120 s window (normal stages run
~20 s each, so a single retry still fits); it is not sized against the stage ceilings.

**Task-class A — `daily_picks` (nba/mlb):** clean median nba 21 s, mlb 44 s. Slowest task-class
(stacks 3 subprocess stages). **Budget: 90 s** — the practical ceiling; ~2x the mlb clean median,
still leaves ~30 s for shutdown before 120 s. (Flag for operator: if clean mlb_daily_picks ever
legitimately approaches 90 s, the Hermes window itself is the bottleneck — see structural caveat.)

**Task-class B — `prop_monitor` (nba/mlb):** clean median ≈ nba 31 s; mlb raw median 98.7 s but
that *includes* residual network latency + the ~58 s obsidian overhead the Phase-2 decouple
removed, so clean mlb ≈ 40 s. **Budget: 80 s.**

**Task-class C — `clv_tracker` (nba/mlb):** raw medians (nba 240 s, mlb 206 s) and p75s (3,000 s+)
are ENTIRELY pre-Phase-2 Telegram + lock-contention stall; clean post-fix runtime should be tens
of seconds. **Budget: 80 s** (with a note to re-confirm against post-Phase-2 timing once available).

**Task-class D — `injury_monitor` (nba/mlb):** clean median nba 14 s, mlb 22 s, p75 nba 50 s.
**Budget: 75 s.**

**Task-class E — `game_completion_monitor`:** clean median 2 s, p75 5 s; rare 651 s lock-contention
spike. **Budget: 60 s** (30x median; a 60 s run is unambiguously hung).

**Task-class F — `check_results`:** clean median 49 s; p75 569 s and extreme 2,025 s are storm.
**Budget: 90 s.**

**Task-class G — `verify`:** clean median 27 s, p75 90 s (storm-inflated). **Budget: 60 s.**

> These are starting values within the confirmed 120 s constraint; the planner finalizes exact
> numbers (D-05 / "exact per-task budget values" = planner's call). The non-negotiable rule is
> **every value < ~90 s** so the clean-shutdown sequence completes before Hermes's hard 120 s kill.

### Summary table

| Task | Class | Budget | Rationale (all < 120 s Hermes hard kill, ~30 s shutdown headroom) |
|------|-------|--------|----------|
| `nba_daily_picks` | A | 90s | Slowest class; ~2–4x clean median |
| `mlb_daily_picks` | A | 90s | Same; closest to the 120 s edge — flag for operator |
| `nba_prop_monitor` | B | 80s | ~2x clean median |
| `mlb_prop_monitor` | B | 80s | Clean median ≈40 s post-obsidian-decouple |
| `nba_clv_tracker` | C | 80s | Re-confirm vs post-Phase-2 timing |
| `mlb_clv_tracker` | C | 80s | Same |
| `nba_injury_monitor` | D | 75s | ~1.5x p75 |
| `mlb_injury_monitor` | D | 75s | Same |
| `game_completion_monitor` | E | 60s | 30x median; covers rare lock contention |
| `check_results` | F | 90s | ~2x clean median |
| `verify` | G | 60s | ~2x clean median |

**TASK_TIMEOUTS dict pattern in runner:**

```python
TASK_TIMEOUTS: dict[str, int] = {  # all < 120 s — the confirmed Hermes no_agent hard kill
    "nba_daily_picks": 90,
    "mlb_daily_picks": 90,
    "nba_prop_monitor": 80,
    "mlb_prop_monitor": 80,
    "nba_clv_tracker": 80,
    "mlb_clv_tracker": 80,
    "nba_injury_monitor": 75,
    "mlb_injury_monitor": 75,
    "game_completion_monitor": 60,
    "check_results": 90,
    "verify": 60,
}
# Default fallback for any unlisted task MUST also be < ~90 s (e.g. 60), NOT 600.
```

---

## Q4: RES-02 Pipe Reclassification — Confirmed Structure

### Current `main()` structure (verified against `sports_system_runner.py:5566-5635`)

```python
def main() -> int:
    task_start_time = time.time()
    try:
        # reset per-invocation state
        ...
        with LOCK_FILE.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            ...
            with task_workbook_locks(args.task):
                result = run_task(args.task)   # ← run_task() returns here on success
        dispatch_alerts(args.task, result)     # ← BrokenPipeError CAN fire here
        safe_print("JSON_RESULT=" + ...)       # ← BrokenPipeError CAN fire here (but safe_print swallows it)
        return 0
    except Exception as e:
        ...
        log(f"ERROR task={args.task}: {e}")
        send_telegram(f"❌ SPORTS TASK FAILED: {args.task}\nError: {e}")
        safe_print("JSON_RESULT=" + json.dumps(err, sort_keys=True))
        return 1
    finally:
        ...
```

### Where BrokenPipeError can fire post-run_task()

1. **`dispatch_alerts()` (line 5592):** Calls `send_telegram()`, which calls `log()`, which calls `safe_print()`. `safe_print()` swallows `BrokenPipeError` (Phase 2 fix). However, `dispatch_alerts()` itself could have a direct `print` or propagate if `log()` raises for another reason.
2. **`safe_print("JSON_RESULT=...")` (line 5593):** Phase 2 already made this `safe_print()`, which swallows `BrokenPipeError` and redirects stdout to `/dev/null`.

**Key insight from Phase-2 analysis (confirmed):** The FIX-01 safe_print sweep means `BrokenPipeError` should NOT reach `main()`'s except block from the normal success path anymore. The RES-02 change is a defence-in-depth guard for any remaining cases where a `BrokenPipeError` could still reach the except block after the task completed — for example, if `dispatch_alerts()` itself raises (e.g., a direct `print` added in the future, or a bare stdout write inside a `send_telegram` code path that doesn't go through `safe_print`).

### "result computed" flag — exact placement

```python
def main() -> int:
    task_start_time = time.time()
    _task_result: dict[str, Any] | None = None   # ← ADD: sentinel before try
    try:
        ...
        with task_workbook_locks(args.task):
            result = run_task(args.task)
        _task_result = result                      # ← ADD: flag set AFTER run_task returns successfully
        dispatch_alerts(args.task, result)
        safe_print("JSON_RESULT=" + ...)
        return 0
    except Exception as e:
        if _task_result is not None and isinstance(e, BrokenPipeError):
            # [RES-02] Pipe closed AFTER task completed — this is NOT a task failure
            log(f"WARNING: BrokenPipeError after task completion — cron pipe closed; task data persisted")
            # Do NOT send TASK FAILED alert
            return 0  # or 1? See note below
        # Real failure — task body itself raised
        err = {...}
        log(f"ERROR task={args.task}: {e}")
        send_telegram(f"❌ SPORTS TASK FAILED: {args.task}\nError: {e}")
        safe_print("JSON_RESULT=" + json.dumps(err, sort_keys=True))
        return 1
    finally:
        ...
```

**Return code on pipe-close-after-completion:** Return 0. The task completed successfully; the pipe close is the cron wrapper's behavior, not an error in the task. The Hermes cron scheduler treats non-zero exit as failure and would fire its own alert (`⚠ Cron watchdog '...' script failed`). [ASSUMED: returning 0 on BrokenPipeError-after-completion is the correct exit code — this matches the Phase-3 criterion "exits clean" and does not trigger Hermes's own failure alert]

### Alert strings to preserve

- **MUST fire (real failure):** `❌ SPORTS TASK FAILED: {task}\nError: {e}` — confirmed at `sports_system_runner.py:5606`
- **MUST NOT fire (pipe after completion):** suppress the above on `isinstance(e, BrokenPipeError) and _task_result is not None`
- **NEW timeout alert (D-06):** `⏱ TASK TIMED OUT: {task} exceeded {budget}s wall-clock budget`
- **New pipe warning log (not Telegram):** `WARNING: BrokenPipeError after task completion — cron pipe closed; task data persisted`

### D-09 — no explicit SIGPIPE handler needed

Python 3.14 already disables the default SIGPIPE disposition and raises `BrokenPipeError` instead. The `safe_print()` sweep handles it at the point of stdout writes. The `_task_result` flag handles it in the except branch. No `signal.signal(SIGPIPE, SIG_IGN)` or `signal.signal(SIGPIPE, SIG_DFL)` needed (the latter would be dangerous — SIG_DFL would hard-kill the process mid-task). [VERIFIED: confirmed Python behavior]

---

## Q5: RES-04 Test Strategy + WR-03

### Phase-2 test audit (D-10)

| Test file | Phase-2 fix | Fails before? | Passes after? | Gap? |
|-----------|-------------|---------------|---------------|------|
| `test_fix01_broken_pipe.py` | FIX-01 (safe_print sweep) | YES — pre-fix runner exits 1 with signals | YES — post-fix exits 0 with 0 signals | None — WR-03 hardening already applied (nonce fence) |
| `test_fix02_telegram_circuit_breaker.py` | FIX-02 (Telegram circuit-breaker) | YES — AttributeError on `_telegram_breaker`, or 100s+ stall | YES — trips in < 30s | None |
| `test_def01_no_duplicate_defs.py` | DEF-01 (duplicate defs removed) | YES — AST finds 2 defs | YES — finds exactly 1 | None |
| `test_def02_path_resolution.py` | DEF-02 (hardcoded path removed) | YES — source contains `akashkalita` | YES — source uses `Path.home()` | None |

**Conclusion:** All four Phase-2 regression tests already have genuine fail-before/pass-after rigor. No gaps found. [VERIFIED: read all four test files]

**WR-03 status:** `repro_broken_pipe.py` has already been hardened (nonce fence approach, WR-03 fix applied). The `test_fix01_broken_pipe.py` test also uses the nonce fence. The production log pollution and racy byte-offset issues from Phase-1 review are resolved. [VERIFIED: read repro_broken_pipe.py — contains nonce fence implementation, INFRA_FAILURE sentinel, isolated scan]

### Phase-3 new regression tests (D-11)

**`test_res01_subprocess_retry.py` — RES-01**

Fault injection: monkeypatch the subprocess call inside `run_fetch_dfs_props()` / `run_build_hit_rate_db()` / `run_generate_projections()` to fail once (non-zero exit), then succeed.

```python
class TestRes01SubprocessRetry(unittest.TestCase):

    def test_subprocess_retry_on_nonzero_exit(self):
        """First call exits 1, second call exits 0 — assert second call happens and stage succeeds."""
        call_count = 0
        original_run = subprocess.run

        def fake_run(cmd, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First attempt: simulate hard failure
                return subprocess.CompletedProcess(cmd, returncode=1, stdout=b"", stderr=b"error")
            return original_run(cmd, *args, **kwargs)

        with patch("subprocess.run", side_effect=fake_run):
            # Call the stage; should succeed on retry
            result = runner.run_fetch_dfs_props("nba")
            # (adjust depending on return type)

        self.assertEqual(call_count, 2, "Expected exactly 2 subprocess calls (1 failure + 1 retry)")

    def test_no_retry_on_clean_exit(self):
        """Exit 0 with empty output is NOT retried."""
        call_count = 0
        def fake_run(cmd, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")
        with patch("subprocess.run", side_effect=fake_run):
            runner.run_fetch_dfs_props("nba")
        self.assertEqual(call_count, 1, "Exit 0 should NOT be retried — empty board is legitimate")

    def test_after_one_retry_fails_raises(self):
        """Two consecutive failures → stage raises (not silently continues)."""
        def fake_run(cmd, *args, **kwargs):
            return subprocess.CompletedProcess(cmd, returncode=1, stdout=b"", stderr=b"fail")
        with patch("subprocess.run", side_effect=fake_run):
            with self.assertRaises((RuntimeError, Exception)):
                runner.run_fetch_dfs_props("nba")
```

**Pre-fix behavior (makes test FAIL):** No retry helper — `call_count` stays at 1 on second test, stage raises immediately on first failure in third test (correct behavior already). The key failure is test_subprocess_retry_on_nonzero_exit expecting `call_count == 2` — pre-fix, it would be 1.

**`test_res02_pipe_reclassify.py` — RES-02**

Fault injection: close the pipe AFTER `run_task()` completes. Assert no `TASK FAILED` Telegram alert fires. Reuses the reader-thread sentinel pattern from `test_fix01_broken_pipe.py`.

Key assertion difference from FIX-01 test:
- FIX-01 tests that `safe_print()` absorbs EPIPE (runner exits 0)
- RES-02 tests that even if a `BrokenPipeError` reaches `main()`'s except branch after the task completed, no `TASK FAILED` Telegram fires

The test must verify:
1. The runner exits 0 (not 1)
2. No `TASK FAILED` alert was sent (monkeypatch `send_telegram` to record calls; assert no call with "TASK FAILED" in message)
3. A warning log line is written instead

```python
def test_no_task_failed_alert_on_post_completion_pipe_close(self):
    """BrokenPipeError after task completion → warning logged, TASK FAILED alert NOT sent."""
    telegram_calls = []
    original_send = runner.send_telegram

    def recording_send(msg, *args, **kwargs):
        telegram_calls.append(msg)
        return False  # simulate unreachable but don't crash

    # Patch send_telegram to record calls
    runner.send_telegram = recording_send
    try:
        # Use the sentinel-pipe-close mechanism (same as test_fix01)
        # ... spawn runner with pipe close at sentinel ...
        # assert:
        self.assertFalse(
            any("TASK FAILED" in m for m in telegram_calls),
            f"TASK FAILED alert fired after completed task hit broken pipe. "
            f"RES-02 regression. Calls: {telegram_calls}"
        )
    finally:
        runner.send_telegram = original_send
```

**Pre-fix behavior (makes test FAIL):** Without the `_task_result` flag check, the except branch fires `send_telegram("❌ SPORTS TASK FAILED: ...")` whenever a `BrokenPipeError` reaches it — including after task completion.

**`test_res03_task_timeout.py` — RES-03**

Fault injection: force a hang inside `run_task()` by monkeypatching the task function to `time.sleep(9999)`. Assert the timeout fires, the `⏱ TASK TIMED OUT` alert is sent, and the runner exits within the timeout budget + a small margin.

```python
def test_task_timeout_fires_on_hung_task(self):
    """A hung task fires ⏱ TASK TIMED OUT alert and exits within budget."""
    # Override verify task to hang
    original_verify = runner.verify
    def hanging_verify():
        time.sleep(9999)

    runner_mapping_backup = None  # patch run_task to use hanging_verify
    telegram_calls = []
    runner.send_telegram = lambda msg, *a, **kw: telegram_calls.append(msg)

    try:
        runner.verify = hanging_verify
        # Set a very short timeout for this test (e.g. 3 seconds)
        with patch.dict(runner.TASK_TIMEOUTS, {"verify": 3}):
            start = time.monotonic()
            result = runner.main_with_args(["--task", "verify"])  # or invoke via subprocess
            elapsed = time.monotonic() - start

        self.assertLess(elapsed, 5.0, f"Timeout did not fire within 5s (hung for {elapsed:.1f}s)")
        self.assertTrue(
            any("TIMED OUT" in m for m in telegram_calls),
            f"⏱ TASK TIMED OUT alert not sent. Calls: {telegram_calls}"
        )
        self.assertNotIn(
            True, [("TASK FAILED" in m) for m in telegram_calls],
            "TASK FAILED fired instead of TIMED OUT — wrong alert type"
        )
    finally:
        runner.verify = original_verify
```

**Note:** Testing SIGALRM behavior in a `unittest` subprocess is tricky because SIGALRM is process-wide. The cleanest approach is spawning the runner as a subprocess (matching the repro harness pattern) with a patched task that hangs, and asserting the subprocess exits within the budget + margin. This avoids SIGALRM interference between test cases.

**Pre-fix behavior (makes test FAIL):** No `TASK_TIMEOUTS` dict and no `signal.alarm()` call — the hung task runs forever. The subprocess never exits, `proc.wait(timeout=5)` raises `TimeoutExpired` in the test, and the `⏱ TASK TIMED OUT` alert is never observed.

---

## Common Pitfalls

### Pitfall 1: Subprocess orphaning on SIGALRM
**What goes wrong:** SIGALRM fires during `subprocess.run()` (e.g., a long `build_hit_rate_db` call). Python's `subprocess.run()` internal finally block for `TimeoutExpired` does NOT run — SIGALRM raises a different exception. The child process (running ESPN scraping / projection math) keeps running after the parent handler fires and raises.
**Why it happens:** `subprocess.run()` only kills children on `subprocess.TimeoutExpired`, not on arbitrary exceptions.
**How to avoid:** Track `_current_subprocess: Popen | None` at module level. The SIGALRM handler reads this variable and calls `.kill()` + `.wait()` before raising `TaskTimeoutError`. Set to `None` after subprocess completes normally.
**Warning signs:** Zombie or orphaned Python processes for build_hit_rate_db/generate_projections in `ps aux` after a timeout event.

### Pitfall 2: SIGALRM handler registered after locks acquired
**What goes wrong:** If the SIGALRM timer is set INSIDE the `with LOCK_FILE... with task_workbook_locks()` blocks, and the timeout fires, the `finally` block of the context managers may or may not run depending on where exactly the stack unwinds. This could leave lock files on disk.
**Why it happens:** SIGALRM raises an exception that unwinds the call stack. Python context managers' `__exit__` blocks DO run on exception (that's the point of `with`). So locks ARE released on timeout. But if the timeout fires during lock acquisition (the `fcntl.flock()` call itself), the behavior depends on whether SIGALRM interrupts flock. Tested: it does interrupt flock.
**How to avoid:** Set the SIGALRM timer BEFORE the lock acquisition. The `finally` block MUST call `signal.alarm(0)` to cancel the timer unconditionally. [VERIFIED: Python context managers call `__exit__` on any exception, including SIGALRM-raised exceptions]
**Warning signs:** Stale `.lock` files in `data/locks/` after a timeout event.

### Pitfall 3: SIGALRM in test harness bleeds between test cases
**What goes wrong:** If `test_res03` uses `signal.alarm()` to test timeout behavior in-process, the alarm can fire in a subsequent test case if the previous test didn't cancel it (e.g., the test failed before `signal.alarm(0)` ran).
**Why it happens:** `signal.alarm()` state persists in the process.
**How to avoid:** Run SIGALRM-based timeout tests in a subprocess (use `subprocess.Popen` + `proc.wait(timeout=N)`) rather than in-process. This matches the `test_fix01_broken_pipe.py` pattern exactly.
**Warning signs:** Random test failures with `TimeoutError` from SIGALRM in tests that don't use alarms.

### Pitfall 4: Retry on empty-but-clean fetch (D-02 violation)
**What goes wrong:** A guard for "should we retry" that checks `len(result_rows) == 0` instead of `returncode != 0`. On a quiet day (NBA off-season, no games), the fetch exits 0 with empty rows — the retry fires, the second fetch also returns 0 empty rows, both runs are wasted.
**Why it happens:** Confusing "no data" with "fetch failed."
**How to avoid:** The retry condition is strictly `returncode != 0 OR TimeoutExpired`. Exit 0 with any output (including empty) is NOT retried per D-02.

### Pitfall 5: _task_result flag set before run_task() completes
**What goes wrong:** If `_task_result` is set BEFORE `run_task()` returns (e.g., inside the `with` block before the return), and `run_task()` then raises, the `except` branch sees `_task_result is not None` and incorrectly suppresses the TASK FAILED alert.
**Why it happens:** Misplacing the flag assignment.
**How to avoid:** `_task_result = result` must be the FIRST line AFTER `run_task()` returns successfully, outside the `with task_workbook_locks()` block but inside the `try` block. The code at `sports_system_runner.py:5591` is:
```python
with task_workbook_locks(args.task):
    result = run_task(args.task)
```
The flag must go AFTER this `with` block exits, not inside it.

### Pitfall 6: TaskTimeoutError vs. Exception handler ordering
**What goes wrong:** `TaskTimeoutError` (raised by the SIGALRM handler) is a subclass of `Exception` and is caught by the existing `except Exception as e` block. This is intended. But if the code inside the except block calls `signal.alarm()` again (to prevent infinite retry), it could interfere.
**Why it happens:** The timeout exception and the fail-path share the same except block.
**How to avoid:** Detect `TaskTimeoutError` specifically (or check `isinstance(e, TaskTimeoutError)`) in the except block; send the `⏱ TASK TIMED OUT` alert and return 1 (not 0). The `signal.alarm(0)` cancellation should be in `finally`, not in the except branch.

---

## Code Examples

### SIGALRM timeout pattern (RES-03)

```python
# Source: verified against Python 3.14.0a2 signal module behavior
import signal

class TaskTimeoutError(Exception):
    pass

_current_subprocess: subprocess.Popen | None = None

TASK_TIMEOUTS: dict[str, int] = {  # all < 120 s — confirmed Hermes no_agent hard kill
    "nba_daily_picks": 90, "mlb_daily_picks": 90,
    "nba_prop_monitor": 80, "mlb_prop_monitor": 80,
    "nba_clv_tracker": 80, "mlb_clv_tracker": 80,
    "nba_injury_monitor": 75, "mlb_injury_monitor": 75,
    "game_completion_monitor": 60,
    "check_results": 90,
    "verify": 60,
}

def _sigalrm_handler(signum: int, frame: Any) -> None:
    global _current_subprocess
    if _current_subprocess is not None:
        try:
            _current_subprocess.kill()
            _current_subprocess.wait(timeout=5)
        except Exception:
            pass
        _current_subprocess = None
    raise TaskTimeoutError(f"Task exceeded wall-clock budget (SIGALRM)")

# In main() try block, before locks:
budget = TASK_TIMEOUTS.get(args.task, 60)  # default < 120 s Hermes hard kill, NOT 600
old_handler = signal.signal(signal.SIGALRM, _sigalrm_handler)
signal.alarm(budget)
try:
    ...
    with LOCK_FILE.open("w") as lock:
        ...
        result = run_task(args.task)
    _task_result = result
    ...
except TaskTimeoutError as e:
    log(f"TIMEOUT task={args.task}: exceeded {budget}s budget")
    send_telegram(f"⏱ TASK TIMED OUT: {args.task}\nBudget: {budget}s exceeded")
    safe_print("JSON_RESULT=" + json.dumps({"status": "timeout", "task": args.task}, sort_keys=True))
    return 1
except Exception as e:
    if _task_result is not None and isinstance(e, BrokenPipeError):
        log(f"WARNING: BrokenPipeError after task completion — cron pipe closed; task data persisted")
        return 0
    # real failure
    ...
finally:
    signal.alarm(0)
    signal.signal(signal.SIGALRM, old_handler)
    ...
```

### Subprocess retry wrapper (RES-01)

```python
# Source: pattern derived from existing subprocess.run() call sites in runner
def _subprocess_run_with_retry(
    cmd: list[str],
    *,
    timeout: int,
    backoff: int = 5,
    context: str,
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    """Run subprocess with one re-run on hard failure. Signal failure via exit code."""
    global _current_subprocess
    for attempt in range(2):
        try:
            proc = subprocess.Popen(cmd, **kwargs)
            _current_subprocess = proc
            try:
                proc.wait(timeout=timeout)
            finally:
                _current_subprocess = None
            # Reconstruct CompletedProcess-like object (or use subprocess.run directly)
            stdout = proc.stdout.read() if proc.stdout else b""
            stderr = proc.stderr.read() if proc.stderr else b""
            cp = subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
        except subprocess.TimeoutExpired:
            _current_subprocess = None
            if attempt == 0:
                log(f"WARNING: {context} timed out on attempt 1/2; retrying in {backoff}s")
                time.sleep(backoff)
                continue
            raise
        if cp.returncode != 0:
            if attempt == 0:
                log(f"WARNING: {context} exited {cp.returncode} on attempt 1/2; retrying in {backoff}s")
                time.sleep(backoff)
                continue
        return cp
    raise RuntimeError(f"{context}: unreachable")  # never reached
```

Note: the actual implementation may be simpler — using `subprocess.run()` directly (since it internally does Popen+wait). The `_current_subprocess` tracking for SIGALRM orphan kill requires Popen. The planner should reconcile this: if SIGALRM is the timeout primitive, the retry wrapper needs Popen to track the child; if SIGALRM kills the subprocess before the retry wrapper can, the retry logic in the wrapper may be unreachable (the SIGALRM exception would bypass the retry loop). [ASSUMED: the interaction between SIGALRM timeout and the per-stage retry wrapper needs careful ordering — the retry wrapper should not catch TaskTimeoutError, only TimeoutExpired and non-zero exit]

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-task wall-clock timeout on main thread | Custom polling loop | `signal.SIGALRM` + handler | SIGALRM interrupts blocking calls; polling cannot |
| Atomic file write for workbooks | Custom lock or temp-then-copy | `os.replace()` (already in `safe_save_workbook`) | `os.replace` is a single POSIX atomic syscall |
| Telegram rate limiting | Custom sliding-window counter | Existing `_telegram_breaker` (Phase 2) | Already implemented and tested |
| Subprocess timeout | Custom watchdog thread | `subprocess.run(timeout=N)` (already used) | stdlib, tested, kills correctly on `TimeoutExpired` |

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `send_telegram()` with 30s timeout × 2 retries, no circuit-breaker | 10s timeout × 2 retries, 3-failure circuit-breaker | Phase 2 | Max stall from Telegram now ~20s per call, not 60s; breaker trips after 3 failures |
| Bare `print("JSON_RESULT=...")` | `safe_print("JSON_RESULT=...")` | Phase 2 | BrokenPipeError no longer reaches main()'s except block from known print sites |
| `obsidian_sync` subprocess per log() line | Single end-of-task Obsidian sync | Phase 2 | ~58s obsidian overhead eliminated from prop_monitor fan-out |
| Two definitions of `injury_monitor` / `clv_tracker` | Exactly one each | Phase 2 | No ambiguity in Python name resolution |
| Hardcoded `/Users/akashkalita` in `generate_projections.py` | `Path.home() / "sports_picks"` | Phase 2 | Runs on any machine/user |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | 5-second retry backoff is appropriate for subprocess re-run | Q2 (Retry helper) | Too short: doesn't help transient failures; too long: adds latency. Operator can tune. |
| A2 | ~~The Hermes kill window for sports jobs is >1800s~~ **RESOLVED → CONFIRMED 120 s hard.** | Q3 (Cron kill window) | Resolved by orchestrator inspection 2026-06-20: all sports jobs `no_agent:True`, no override, `_run_job_script` → `subprocess.run(timeout=120)`. All RES-03 budgets revised to < 120 s. No remaining risk on this item. |
| A3 | Returning exit code 0 on BrokenPipeError-after-completion is correct | Q4 (Return code) | If Hermes expects exit 1 on any pipe error and uses it for delivery decisions, returning 0 could suppress valid error signals. Low risk: the task DID complete. |
| A4 | `_task_result` flag approach correctly handles all BrokenPipeError scenarios | Q4 (Flag placement) | Edge case: if the task completes but `dispatch_alerts` raises a non-BrokenPipeError before it raises a BrokenPipeError, the flag is set but the wrong exception is in the except branch. Low risk given the dispatch_alerts structure. |
| A5 | The SIGALRM + subprocess kill pattern correctly prevents orphans | Q1 (Orphan mitigation) | If kill() returns before the subprocess terminates and the handler proceeds, the orphan can still exist briefly. The `.wait(timeout=5)` handles this. |

---

## Open Questions

1. **Hermes kill window for sports jobs — RESOLVED (no longer open).**
   - CONFIRMED 2026-06-20: hard **120 s** `subprocess.run` timeout, no override (env unset, no
     `cron.script_timeout_seconds`, jobs all `no_agent:True` with no per-job timeout). See Q3 for
     the full verified chain. All RES-03 budgets are now < 120 s.
   - The 1128 s / 7697 s "completions" were orphaned-runner log lines after Hermes killed the
     wrapper at 120 s during the 2026-06-15 network storm — not clean completions.
   - Residual operator action (optional, OUT of Phase-3 scope): if legitimately-slow daily_picks
     runs trip RES-03 post-fix, raise `cron.script_timeout_seconds` in `~/.hermes/config.yaml`.
     That is a Hermes-config change, not a sports_picks code change.

2. **SIGALRM interaction with `fcntl.LOCK_EX` during task_workbook_locks acquisition**
   - What we know: SIGALRM interrupts `fcntl.flock()` cleanly (tested), Python context managers run `__exit__` on exception (spec), so lock files are released
   - What's unclear: whether a partially-acquired workbook lock stack (e.g., first path locked, second path blocked when SIGALRM fires) cleans up the first lock in `task_workbook_locks`'s `finally`
   - Recommendation: read `task_workbook_locks()` at `sports_system_runner.py:5533-5544` — the `finally` block calls `cm.__exit__(None, None, None)` for each acquired context manager. This should clean up correctly. Low risk; verify in the test.

3. **Test isolation for SIGALRM tests**
   - What we know: `test_res03` must test SIGALRM behavior; in-process SIGALRM bleeds between test cases
   - What's unclear: exact subprocess-based test structure
   - Recommendation: spawn the runner as a subprocess with a patched/monkeypatched task (via env var or a test-mode flag). The Phase-2 test pattern (`subprocess.Popen` + wait) is the right model.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `/usr/local/bin/python3` | Run tests from scripts/ | Yes | 3.14.0a2 | None — this is the required interpreter |
| `signal.SIGALRM` | RES-03 timeout | Yes | stdlib | threading.Timer + os.kill() — tested viable |
| `signal.alarm()` | RES-03 SIGALRM arm/cancel | Yes | stdlib | Same fallback |
| `unittest.mock.patch` | RES-04 fault injection | Yes | stdlib (unittest.mock) | None needed |
| `fcntl` | Existing runner lock | Yes | stdlib (POSIX) | None — macOS only, already required |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.x (for discovery) + unittest.TestCase (for test bodies) |
| Config file | none — discovered via `python3 -m pytest` from `scripts/` |
| Quick run command | `python3 -m pytest test_res01_subprocess_retry.py test_res02_pipe_reclassify.py test_res03_task_timeout.py -x` |
| Full suite command | `python3 -m pytest` (from `scripts/`) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RES-01 | Subprocess re-run on nonzero exit | unit (monkeypatch) | `python3 -m pytest test_res01_subprocess_retry.py -x` | Wave 0 |
| RES-01 | No retry on exit 0 / empty board | unit | same | Wave 0 |
| RES-01 | Two failures → stage raises | unit | same | Wave 0 |
| RES-02 | BrokenPipeError after completion → no TASK FAILED | integration (subprocess) | `python3 -m pytest test_res02_pipe_reclassify.py -x` | Wave 0 |
| RES-03 | Hung task → timeout fires + TIMED OUT alert | integration (subprocess) | `python3 -m pytest test_res03_task_timeout.py -x` | Wave 0 |
| RES-03 | Healthy task → timeout cancelled, no spurious fire | integration (subprocess) | same | Wave 0 |
| RES-04 | Phase-2 test audit: all 4 tests fail-before/pass-after | audit (manual + run) | `python3 -m pytest test_fix01_broken_pipe.py test_fix02_telegram_circuit_breaker.py test_def01_no_duplicate_defs.py test_def02_path_resolution.py` | Yes (all 4 exist) |

### Sampling Rate

- **Per task commit:** `python3 -m pytest test_res01_subprocess_retry.py test_res02_pipe_reclassify.py test_res03_task_timeout.py test_fix01_broken_pipe.py test_fix02_telegram_circuit_breaker.py -x`
- **Per wave merge:** `python3 -m pytest` (full suite from `scripts/`)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `scripts/test_res01_subprocess_retry.py` — covers RES-01 (subprocess retry)
- [ ] `scripts/test_res02_pipe_reclassify.py` — covers RES-02 (pipe reclassification)
- [ ] `scripts/test_res03_task_timeout.py` — covers RES-03 (task timeout)

---

## Security Domain

> `security_enforcement` not explicitly set in `.planning/config.json` — treating as enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | n/a (no auth in this phase) |
| V3 Session Management | No | n/a |
| V4 Access Control | No | n/a |
| V5 Input Validation | No | No new user inputs |
| V6 Cryptography | No | n/a |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Signal handler executes arbitrary code (if `_current_subprocess` is tampered) | Tampering | `_current_subprocess` is module-level; not exposed externally; only set by runner internals |
| Retry loop amplifying requests (DoS to external APIs on retry) | Denial of Service | 1 re-run maximum (D-03); exit-0 not retried (D-02); backoff between attempts |
| Orphaned child processes accumulating | Denial of Service | SIGALRM handler kills `_current_subprocess` before raising |
| `_task_result` flag bypassing genuine failure alerts | Repudiation | Flag only set AFTER `run_task()` returns successfully; checked with `isinstance(e, BrokenPipeError)` |

---

## Sources

### Primary (HIGH confidence)
- `scripts/sports_system_runner.py` — read directly; lines 92, 200-218, 238-273, 1278-1408, 5533-5635 [VERIFIED: read]
- `scripts/workbook_io.py:147-174` — read directly; atomic-save invariant confirmed [VERIFIED: read]
- `scripts/repro_broken_pipe.py` — read directly; WR-03 hardening confirmed applied [VERIFIED: read]
- `scripts/test_fix01_broken_pipe.py`, `test_fix02_telegram_circuit_breaker.py`, `test_def01_no_duplicate_defs.py`, `test_def02_path_resolution.py` — read directly; fail-before/pass-after rigor confirmed [VERIFIED: read]
- `.planning/phases/01-diagnosis/01-TIMING-EVIDENCE.md` — per-task duration profile, 791+ completions [VERIFIED: read]
- `.planning/phases/01-diagnosis/DIAGNOSIS.md` — broken-pipe mechanism, timing root cause [VERIFIED: read]
- `.planning/phases/01-diagnosis/01-REVIEW.md` — WR-03 concern, now resolved [VERIFIED: read]
- `.planning/phases/02-reliability-fixes-defect-removal/02-CONTEXT.md` — Phase-2/3 boundary [VERIFIED: read]
- `~/.hermes/hermes-agent/cron/scheduler.py:919-1081` — `_DEFAULT_SCRIPT_TIMEOUT = 120`, `_run_job_script()` implementation [VERIFIED: read]
- Python 3.14.0a2 direct tests — SIGALRM interrupts subprocess.run(), fcntl.flock(), time.sleep(); SIGALRM handler fires on main thread; alarm(0) cancels cleanly; subprocess child orphaning confirmed [VERIFIED: run directly on the target interpreter]

### Secondary (MEDIUM confidence)
- `.planning/codebase/INTEGRATIONS.md`, `CONCERNS.md`, `ARCHITECTURE.md` — not read directly in this session; context from CONTEXT.md references

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all stdlib on verified Python 3.14
- Architecture (SIGALRM primitive): HIGH — tested directly on target interpreter
- Per-task budget values: MEDIUM-HIGH — Hermes kill window now CONFIRMED 120 s; budgets sized < 120 s from clean medians. Residual uncertainty is only in the exact clean-median values (storm-contaminated source data), not the hard ceiling.
- Pitfalls (orphan risk): HIGH — directly reproduced
- Test strategy: HIGH — follows Phase-2 patterns; specific test stubs are ASSUMED
- Hermes kill window: HIGH (was LOW) — orchestrator-verified 2026-06-20: hard 120 s, no override. Full chain inspected: jobs.json (all no_agent, no timeout) → _run_job_script → subprocess.run(timeout=_get_script_timeout()=120) → synchronous wrapper.

**Research date:** 2026-06-20
**Valid until:** 2026-07-20 (30 days — stable stdlib, no fast-moving dependencies)
