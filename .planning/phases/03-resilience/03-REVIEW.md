---
phase: 03-resilience
reviewed: 2026-06-20T00:00:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - scripts/sports_system_runner.py
  - scripts/test_res01_subprocess_retry.py
  - scripts/test_res02_pipe_reclassify.py
  - scripts/test_res03_task_timeout.py
findings:
  critical: 2
  warning: 4
  info: 2
  total: 8
status: resolved
resolution_commit: 04f72c6
resolution_note: >
  CR-01, CR-02, WR-01, WR-02, WR-04, IN-01 fixed in 04f72c6 (helper rewritten to
  translate capture_output -> PIPE and drain via communicate(); real-child tests
  added; full suite green at baseline 2 failed / 224 passed). WR-03 ESCALATED: the
  90s/80s/75s/60s RES-03 budgets are far below observed task runtimes (mlb_daily_picks
  509s, check_results 394s, mlb_prop_monitor up to 340s) — pending an operator budget
  decision before RES-03 ships. IN-02 left as a defensive sentinel (acceptable).
---

# Phase 03: Code Review Report

**Reviewed:** 2026-06-20T00:00:00Z
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Phase 03 (resilience) adds `_subprocess_run_with_retry` (RES-01), module-level Popen tracking
plus a SIGALRM per-task timeout (RES-03), and BrokenPipeError reclassification in `main()`
(RES-02). The SIGALRM arm/disarm logic and the `_task_result` reclassification guard are
correctly scoped and read cleanly.

However, the central RES-01 helper is **broken against the real `subprocess` module** in two
independent ways, and the new regression test cannot catch either defect because it injects a
fake `Popen` that silently discards the offending kwargs and never exercises the pipe-drain
path. Both defects sit directly on the `daily_picks` hot path (fetch DFS props → hit-rate build
→ projections), so this change as written makes the core pipeline crash or hang instead of
hardening it. These must be fixed before the phase ships.

I reproduced both Critical findings against the live Python 3.14 interpreter (see evidence in
each finding). The remaining findings are robustness/clarity issues that do not block but should
be addressed.

## Critical Issues

### CR-01: `_subprocess_run_with_retry` passes `capture_output=True` to `subprocess.Popen`, which raises `TypeError` — every routed stage crashes on first call

**File:** `scripts/sports_system_runner.py:155` (helper) — triggered from `:1370`, `:1449`, `:1483`

**Issue:**
`capture_output` is a convenience argument of `subprocess.run`, **not** of `subprocess.Popen`.
All three rewired call sites still pass it:

- `run_fetch_dfs_props` → `_subprocess_run_with_retry(..., text=True, capture_output=True)` (line 1370)
- `run_build_hit_rate_db` → `_subprocess_run_with_retry(..., capture_output=True, text=True)` (line 1449)
- `run_generate_projections` → `_subprocess_run_with_retry(..., capture_output=True, text=True)` (line 1483)

The helper forwards `**kwargs` straight into `subprocess.Popen(cmd, **kwargs)` (line 155), which
rejects `capture_output`:

```
RAISED: TypeError - Popen.__init__() got an unexpected keyword argument 'capture_output'
```

(Reproduced by calling `_subprocess_run_with_retry` exactly as `run_build_hit_rate_db` does
against the real interpreter.) This means the very first subprocess stage of every
`daily_picks` run dies with a `TypeError`, which propagates as a task failure — i.e. the
hardening change converts a working pipeline into one that fails on every invocation. This is a
data-pipeline outage on a real-money system, not a degradation.

The new RES-01 test does not catch this: `_FakePopen.__init__(self, returncode, *, raise_timeout=False)`
is constructed via `_fake_popen(cmd, *args, **kwargs)` which discards `**kwargs`, so the
production-breaking `capture_output=True` is silently swallowed and never validated.

**Fix:** Translate the high-level kwargs to Popen-native pipe arguments inside the helper, and
update call sites to stop passing `capture_output`. Minimal helper change:

```python
def _subprocess_run_with_retry(cmd, *, timeout, backoff=5, context, **kwargs):
    # subprocess.run accepts capture_output/text; Popen does not. Translate.
    if kwargs.pop("capture_output", False):
        kwargs.setdefault("stdout", subprocess.PIPE)
        kwargs.setdefault("stderr", subprocess.PIPE)
    text = kwargs.get("text", False)
    ...
        proc = subprocess.Popen(cmd, **kwargs)
```

Then drain via `communicate()` rather than `wait()`+`read()` (see CR-02).

---

### CR-02: `proc.wait(timeout=...)` followed by `proc.stdout.read()` deadlocks on large child output

**File:** `scripts/sports_system_runner.py:157-166`

**Issue:**
Even after CR-01 is fixed (so pipes are actually set up), the helper drains output incorrectly:

```python
proc = subprocess.Popen(cmd, **kwargs)
_current_subprocess = proc
try:
    proc.wait(timeout=timeout)          # <-- blocks until child exits
finally:
    _current_subprocess = None
stdout = proc.stdout.read() if proc.stdout else b""   # read happens AFTER wait
```

When `stdout`/`stderr` are real pipes, the child blocks once it fills the OS pipe buffer
(~64 KB on macOS) because nothing is reading. `proc.wait()` then never returns, so it raises
`TimeoutExpired` even on a healthy child that simply produced a lot of output. The original
`subprocess.run` avoided this by using `communicate()`, which reads the pipes concurrently with
waiting. Reproduced against the real interpreter with 200 KB of child stdout:

```
DEADLOCK: wait() timed out because child blocked writing to full pipe buffer
```

This is squarely on the hot path: `run_build_hit_rate_db` (`--workers 8`, full NBA board) and
`run_generate_projections` emit large JSON to stdout. Under this change those stages will spuriously
time out, trigger the (broken) retry, time out again, and fail the task — the opposite of the
RES-01 goal. The RES-01 test uses `_FakePopen` with `io.StringIO("")` (empty, in-memory) so it
never exercises the pipe-buffer path.

**Fix:** Use `communicate()` for draining; let it honor the timeout. Keep `_current_subprocess`
tracking for the SIGALRM kill path:

```python
proc = subprocess.Popen(cmd, **kwargs)
_current_subprocess = proc
try:
    stdout, stderr = proc.communicate(timeout=timeout)
finally:
    _current_subprocess = None
cp = subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
```

`communicate(timeout=...)` raises `subprocess.TimeoutExpired` (already handled at line 167) and,
critically, it kills nothing on its own — so on `TimeoutExpired` you must also `proc.kill()` +
`proc.communicate()` before retrying to avoid leaking the orphaned child during the backoff
window (the current code sets `_current_subprocess = None` on timeout but never kills the child
that timed out on attempt 1).

## Warnings

### WR-01: On `TimeoutExpired` retry, the timed-out child is never killed — orphan + double-run risk

**File:** `scripts/sports_system_runner.py:167-173`

**Issue:** When attempt 1 raises `subprocess.TimeoutExpired`, the handler only does
`_current_subprocess = None` and then `time.sleep(backoff)` + `continue`. It never calls
`proc.kill()`/`proc.wait()`. The original child is still running (a hung fetcher/ESPN scrape),
so attempt 2 launches a *second* concurrent child doing the same network work, and the first is
orphaned for the rest of the process lifetime. For the hit-rate build (8-worker ESPN load) this
can double API pressure and leave a zombie. Only the SIGALRM path kills the tracked child, and
after `_current_subprocess = None` the handler can no longer reach it.

**Fix:** Kill and reap before retrying:

```python
except subprocess.TimeoutExpired:
    try:
        proc.kill()
        proc.communicate()
    except Exception:
        pass
    _current_subprocess = None
    if attempt == 0:
        log(...); time.sleep(backoff); continue
    raise
```

### WR-02: SIGALRM can fire during `time.sleep(backoff)` and orphan the running child

**File:** `scripts/sports_system_runner.py:124-134`, `:171`, `:177`

**Issue:** The retry backoff `time.sleep(5)` runs while attempt 1's child may still be alive
(see WR-01) but `_current_subprocess` has already been reset to `None` on the timeout path. If
the per-task SIGALRM budget expires during that sleep, `_sigalrm_handler` sees
`_current_subprocess is None`, kills nothing, and raises `TaskTimeoutError` — leaving the
still-running attempt-1 child orphaned past process exit. Even on the non-timeout retry path
(non-zero exit), the child has exited so this is benign, but combined with WR-01 the timeout
path can leak a live subprocess. Fixing WR-01 (kill before resetting the tracker) closes this.

**Fix:** Ensure the child is killed/reaped before `_current_subprocess = None` on every retry
branch, so there is never a window where a live child exists but is untracked.

### WR-03: `verify` task budget (60 s) is smaller than the subprocess timeouts it can reach (no per-stage cap reconciliation)

**File:** `scripts/sports_system_runner.py:105-117`

**Issue:** `daily_picks` carries a 90 s task budget but invokes stages with `timeout=300`
(`fetch_dfs_props`) and `timeout=600` (hit-rate, projections). The intent is "SIGALRM wins,"
which is fine — but it means the documented per-stage retry (RES-01) is effectively dead on the
daily-picks path: the 90 s alarm fires long before a 300/600 s stage timeout or its 5 s backoff
+ second attempt could ever complete. The retry helper's value is therefore limited to fast
sub-90 s failures. Worth confirming this is the intended interaction and not an accidental
neutering of RES-01 on the most important task. Not a correctness bug, but the budgets and the
retry semantics are in tension and undocumented at the call sites.

**Fix:** Document at each routed call site that the task-level SIGALRM budget (90 s) supersedes
the stage `timeout` argument, or lower stage timeouts to fit within the budget so a retry can
actually occur before the alarm.

### WR-04: RES-01 regression test cannot detect CR-01 or CR-02 — fake Popen masks both production defects

**File:** `scripts/test_res01_subprocess_retry.py:47-72`, `:108-112`

**Issue:** `_FakePopen` (a) discards all constructor kwargs via `_fake_popen(cmd, *args, **kwargs)`,
so `capture_output=True` (CR-01) is never validated against the real signature; and (b) backs
`.stdout`/`.stderr` with empty `io.StringIO`, so the `wait()`-then-`read()` pipe-buffer deadlock
(CR-02) is never exercised. The test asserts `call_count` (retry counting) only — it gives green
confidence while the production helper is non-functional. A regression test for a subprocess
hardening helper that never touches a real pipe or the real `Popen` signature provides false
assurance.

**Fix:** Add at least one test that drives `_subprocess_run_with_retry` against a real child
process (e.g. `[sys.executable, "-c", "..."]`) with `capture_output=True, text=True`, asserting
it returns the captured stdout — and one with a large-stdout child to guard CR-02. Keep the
fake-Popen tests for retry-counting, but do not let them stand in for end-to-end behavior.

## Info

### IN-01: Unused exception binding in the timeout handler

**File:** `scripts/sports_system_runner.py:5688`

**Issue:** `except TaskTimeoutError as e:` binds `e` but the handler body uses only `budget` and
`args.task`; `e` is never referenced.

**Fix:** Drop the binding: `except TaskTimeoutError:`.

### IN-02: Unreachable sentinel `raise RuntimeError("...: unreachable retry path")` is dead by construction

**File:** `scripts/sports_system_runner.py:180`

**Issue:** The `for attempt in range(2)` loop always either `return cp` or `raise` on attempt 1,
and on attempt 1 (the last iteration) both the `TimeoutExpired` branch and the non-zero-exit
branch fall through to `return cp` / `raise`, so the trailing `raise RuntimeError(... unreachable ...)`
can never execute. Harmless as a defensive guard, but it is genuinely dead code. Acceptable to
keep as a belt-and-suspenders sentinel; noting it so it is not mistaken for live error handling.

**Fix:** Optional — leave as a defensive sentinel, or remove and rely on the loop's exhaustive
branches.

---

_Reviewed: 2026-06-20T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
