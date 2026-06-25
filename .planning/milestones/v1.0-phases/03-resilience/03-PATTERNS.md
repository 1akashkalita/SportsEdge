# Phase 3: Resilience - Pattern Map

**Mapped:** 2026-06-20
**Files analyzed:** 4 (3 new tests + 1 modified runner)
**Analogs found:** 4 / 4

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `scripts/test_res01_subprocess_retry.py` | test | request-response (monkeypatch subprocess) | `scripts/test_fix02_telegram_circuit_breaker.py` | exact |
| `scripts/test_res02_pipe_reclassify.py` | test | event-driven (subprocess-spawn + pipe-close) | `scripts/test_fix01_broken_pipe.py` | exact |
| `scripts/test_res03_task_timeout.py` | test | event-driven (subprocess-spawn + SIGALRM) | `scripts/test_fix01_broken_pipe.py` | role-match |
| `scripts/sports_system_runner.py` | orchestrator (modified) | batch (subprocess pipeline) | self — existing `main()` + `_telegram_breaker` reset pattern | self-analog |

---

## Pattern Assignments

### `scripts/test_res01_subprocess_retry.py` (test, monkeypatch/request-response)

**Analog:** `scripts/test_fix02_telegram_circuit_breaker.py`

**Why:** test_fix02 is the canonical monkeypatch-the-module-attribute + recording-pattern test. test_res01 mirrors it exactly: import runner via `importlib`, monkeypatch a module function — **`subprocess.Popen`** (NOT `subprocess.run`: the RES-01 helper `_subprocess_run_with_retry` uses `Popen` so RES-03's handler can kill the in-flight child via `_current_subprocess`) inside a runner stage function instead of `requests.post` — call the stage, assert call count and error propagation.

**Imports pattern** (`scripts/test_fix02_telegram_circuit_breaker.py` lines 27-51):
```python
from __future__ import annotations

import importlib.util
import os
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

SCRIPT: Path = Path(__file__).resolve().with_name("sports_system_runner.py")
spec = importlib.util.spec_from_file_location("sports_system_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)
```

**setUp/tearDown pattern for per-test state reset** (lines 57-79):
```python
def setUp(self) -> None:
    """Reset breaker state and inject dummy creds so the creds guard passes."""
    os.environ["TELEGRAM_BOT_TOKEN"] = "x"
    os.environ["TELEGRAM_HOME_CHANNEL"] = "y"
    runner._telegram_breaker["consecutive_failures"] = 0
    runner._telegram_breaker["tripped"] = False
    runner._telegram_breaker["suppressed"] = 0

def tearDown(self) -> None:
    os.environ.pop("TELEGRAM_BOT_TOKEN", None)
    os.environ.pop("TELEGRAM_HOME_CHANNEL", None)
    runner._telegram_breaker["consecutive_failures"] = 0
    runner._telegram_breaker["tripped"] = False
    runner._telegram_breaker["suppressed"] = 0
```

**Monkeypatch call-counting pattern** (lines 81-109):
```python
def test_breaker_trips_after_n_failures(self) -> None:
    start = time.monotonic()
    with patch.object(
        requests,
        "post",
        side_effect=requests.exceptions.ConnectionError("simulated unreachable"),
    ):
        for _ in range(5):
            runner.send_telegram("test message — breaker trip test")
    elapsed = time.monotonic() - start

    self.assertTrue(
        runner._telegram_breaker["tripped"],
        "_telegram_breaker['tripped'] is False after 5 forced failures — "
        "FIX-02 regression: breaker did not trip (pre-fix runner has no breaker)",
    )
    self.assertLess(elapsed, 30.0, ...)
```

**Log-capturing pattern (for asserting log side-effects without touching run_log.txt)** (lines 143-173):
```python
log_lines: list[str] = []
original_log = runner.log

def capturing_log(msg: str) -> None:
    log_lines.append(msg)

runner.log = capturing_log
try:
    # ... exercise the code ...
finally:
    runner.log = original_log

matching = [line for line in log_lines if "alerts suppressed" in line.lower()]
self.assertTrue(len(matching) > 0, ...)
```

**Adaptation for test_res01:** Replace `patch.object(requests, "post", ...)` with **`patch("subprocess.Popen", ...)`** (or `patch.object(runner.subprocess, "Popen", ...)`) plus a nonlocal `call_count` closure. **Do NOT patch `subprocess.run`** — the RES-01 helper calls `subprocess.Popen` (so the SIGALRM handler can kill `_current_subprocess`); patching `subprocess.run` would leave the real `Popen` call un-intercepted, so `call_count` stays at the wrong value and the test passes even on pre-fix code (silently violating D-11). The fake must return a fake-Popen object exposing the attributes the helper reads: `.wait(timeout=...)` (return the simulated returncode or raise `subprocess.TimeoutExpired`), `.returncode`, `.kill()`, `.stdout`/`.stderr`. The key pattern is the same: count `Popen` constructions, assert the retry wrapper constructed it twice on first hard failure and once on clean exit (exit 0 NOT retried, D-02). The stage functions are accessed as `runner.run_fetch_dfs_props(...)` after `importlib` load.

---

### `scripts/test_res02_pipe_reclassify.py` (test, subprocess-spawn + pipe-close)

**Analog:** `scripts/test_fix01_broken_pipe.py`

**Why:** test_fix01 IS the canonical subprocess-spawn + reader-thread sentinel-close + nonce-log-fence pattern. RES-02 extends it with one additional assertion: not only does the runner exit 0 (which test_fix01 already proves), but no `send_telegram("TASK FAILED")` call fires. The pipe-close timing mechanism is identical; only the post-run assertions differ.

**Imports pattern** (`scripts/test_fix01_broken_pipe.py` lines 27-35):
```python
from __future__ import annotations

import subprocess
import sys
import threading
import time
import unittest
import uuid
from pathlib import Path
```

**Module-level constants** (lines 37-51):
```python
SCRIPTS_DIR: Path = Path(__file__).resolve().parent
RUNNER: Path = SCRIPTS_DIR / "sports_system_runner.py"
RUN_LOG: Path = SCRIPTS_DIR.parent / "data" / "pnl" / "logs" / "run_log.txt"

REPRO_TASK: str = "verify"
_SENTINEL: str = "verification complete"

_WAIT_TIMEOUT: float = 90.0
_INFRA_FAILURE: int = -1
```

**Drain-and-close-at-sentinel thread function** (lines 54-69):
```python
def _drain_and_close_at_sentinel(proc: subprocess.Popen) -> None:
    try:
        assert proc.stdout is not None
        for raw_line in proc.stdout:
            try:
                line = raw_line.decode("utf-8", errors="replace").rstrip()
            except Exception:
                line = ""
            if _SENTINEL in line:
                proc.stdout.close()
                return
    except Exception:
        pass
```

**Nonce-fence log isolation** (lines 72-93):
```python
def _count_nonce_signals(nonce: str) -> int:
    try:
        content = RUN_LOG.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return _INFRA_FAILURE
    fence_pos = content.find(nonce)
    if fence_pos == -1:
        return _INFRA_FAILURE
    after_fence = content[fence_pos:]
    return (
        after_fence.count("Broken pipe")
        + after_fence.count("ERROR task=")
        + after_fence.count("TRACEBACK task=")
    )
```

**Test body — nonce write + Popen + reader thread + proc.wait + assertions** (lines 111-184):
```python
def test_no_spurious_task_failed_after_pipe_close(self) -> None:
    nonce: str = uuid.uuid4().hex
    try:
        RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
        with RUN_LOG.open("a", encoding="utf-8") as fence_f:
            fence_f.write(f"[test-fix01-fence] nonce={nonce}\n")
    except Exception as exc:
        self.skipTest(f"Could not write nonce fence to run-log (infra): {exc}")

    try:
        proc = subprocess.Popen(
            [sys.executable, "-u", str(RUNNER), "--task", REPRO_TASK],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(SCRIPTS_DIR),
        )
    except Exception as exc:
        self.fail(f"Could not spawn runner subprocess (infra failure): {exc}")

    reader = threading.Thread(
        target=_drain_and_close_at_sentinel,
        args=(proc,),
        daemon=True,
    )
    reader.start()

    try:
        proc.wait(timeout=_WAIT_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        self.fail(f"Runner subprocess timed out after {_WAIT_TIMEOUT:.0f}s ...")

    reader.join(timeout=5.0)
    returncode = proc.returncode
    new_signals = _count_nonce_signals(nonce)

    self.assertEqual(returncode, 0, ...)
    if new_signals != _INFRA_FAILURE:
        self.assertEqual(new_signals, 0, ...)
```

**Adaptation for test_res02:** Copy the entire Popen + reader-thread + nonce-fence structure. Add a second assertion that scans the post-fence log for `"TASK FAILED"` and asserts it does NOT appear. The nonce fence + `_count_nonce_signals`-style scan is the right tool — extend it to count `"TASK FAILED"` lines instead of (or in addition to) `"ERROR task="` lines. No in-process monkeypatch of `send_telegram` is needed because the subprocess model captures all output through the log file.

---

### `scripts/test_res03_task_timeout.py` (test, subprocess-spawn + SIGALRM)

**Analog:** `scripts/test_fix01_broken_pipe.py` (subprocess-spawn structure)

**Why:** SIGALRM state is process-global — it MUST NOT be tested in-process alongside other test cases (Pitfall 3 in RESEARCH.md). The only safe approach is spawning the runner as a subprocess (matching test_fix01's Popen pattern), then asserting the subprocess exits within budget + margin. The reader-thread is not needed (no sentinel-close), but `proc.wait(timeout=budget+margin)` and exit-code assertions are identical.

**Core subprocess-spawn pattern** (same as test_fix01, lines 120-148):
```python
proc = subprocess.Popen(
    [sys.executable, "-u", str(RUNNER), "--task", REPRO_TASK],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=str(SCRIPTS_DIR),
)
try:
    proc.wait(timeout=_WAIT_TIMEOUT)
except subprocess.TimeoutExpired:
    proc.kill()
    proc.wait()
    self.fail(f"Runner subprocess timed out after {_WAIT_TIMEOUT:.0f}s ...")
```

**Adaptation for test_res03 — CONFIRMED mechanism (no production-runner change):** The task that
hangs is injected via a **generated child shim script**, NOT an env-var hook in the runner. The
test writes a tiny temp `.py` shim that runs in the isolated child process:

```
import sports_system_runner as r, time, sys
r.verify = lambda: time.sleep(9999)        # rebind the module-level task fn
r.TASK_TIMEOUTS["verify"] = 3              # short budget so the test is fast
sys.exit(r.main())                          # main() arms SIGALRM(3) → fires → kills child → exits
```
Spawn that shim with `subprocess.Popen([sys.executable, shim_path, "--task", "verify"], ...)`.
This works because `run_task` builds its dispatch `mapping` at call-time and references `verify`
by name (`sports_system_runner.py:5559`), so rebinding `r.verify` before `r.main()` runs takes
effect; and `TASK_TIMEOUTS` is a module-level dict read by `main()` at call-time. SIGALRM is
process-global but harmless here — the shim child runs exactly one task then exits. **No env-var
hook or test-mode branch is added to the production runner** (honors the minimal-invasive
constraint). The `time.sleep(9999)` cannot complete, so the test FAILS on pre-fix code (no SIGALRM
→ child never exits → harness `proc.wait(timeout=_WAIT_TIMEOUT)` raises) and PASSES post-fix
(SIGALRM fires at 3s → `⏱ TASK TIMED OUT` → exit 1) — satisfying D-11.

Set `_WAIT_TIMEOUT = budget + 30` (≈33s here) so the harness gives the clean-shutdown sequence
headroom but still fails fast if SIGALRM never fires. The healthy-task counter-case (3-RES03-b)
spawns the same shim WITHOUT the hang rebind (real `verify`, short budget large enough for a clean
run, e.g. leave `verify` at its real 60s budget or set a comfortable value) and asserts no
`TIMED OUT`/`TASK FAILED` and exit 0.

The test assertions are:
- `self.assertLess(elapsed, budget + margin)` — timeout fired
- scan stdout/stderr or the nonce-fenced log for `"TIMED OUT"` — correct alert type emitted
- scan for `"TASK FAILED"` and assert it is NOT present — wrong alert type not fired
- `self.assertEqual(returncode, 1)` — non-zero exit on timeout

Use the nonce-fence log scan from test_fix01 (lines 72-93 above) to isolate assertions to this run.

---

### `scripts/sports_system_runner.py` (orchestrator, modified)

**Analog:** self — existing code at the named line ranges

The runner is its own analog. The three patches are surgical additions within established patterns already in the file.

#### RES-01: `_subprocess_run_with_retry()` helper

**Analog call sites** (`sports_system_runner.py` lines 1286, 1365, 1399):

`run_fetch_dfs_props` (lines 1278-1292):
```python
def run_fetch_dfs_props(sport: str) -> None:
    """Refresh all first-class DFS prop sources and the unified comparison table."""
    script = SCRIPTS / "fetch_dfs_props.py"
    if not script.exists():
        run_fetch_prizepicks(sport)
        return
    cmd = [sys.executable, str(script), "--league", sport]
    cp = subprocess.run(cmd, text=True, capture_output=True, timeout=300)
    if cp.stdout:
        safe_print(cp.stdout.rstrip())
    if cp.stderr:
        print(cp.stderr.rstrip(), file=sys.stderr)
    if cp.returncode != 0:
        raise RuntimeError(f"fetch_dfs_props failed for {sport}: exit={cp.returncode}")
```

`run_build_hit_rate_db` (lines 1359-1374):
```python
def run_build_hit_rate_db(sport: str, date: str) -> dict[str, Any]:
    cmd = ["/usr/local/bin/python3", str(HIT_RATE_SCRIPT), "--sport", sport, "--date", date, "--workers", "8"]
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if cp.returncode != 0:
        log(f"{sport.upper()} hit-rate build failed: exit={cp.returncode} stderr={cp.stderr[-500:]}")
        return {"status": "failed", "exit_code": cp.returncode, "stderr": cp.stderr[-1000:]}
    try:
        result = json.loads(cp.stdout)
    except Exception:
        result = {"status": "ok", "raw_stdout": cp.stdout[-1000:]}
    log(f"{sport.upper()} hit-rate build complete: {str(result)[:800]}")
    return result
```

`run_generate_projections` (lines 1393-1407) — identical structure to `run_build_hit_rate_db`.

**Retry shape analog:** `scripts/odds_api_io_client.py` lines 166-211 (`_request` method):
```python
attempts = self.max_retries   # == 3
delay = self.backoff           # == 1.0
for attempt in range(1, attempts + 1):
    try:
        response = self.session.request(...)
        ...
        if status == 429 or 500 <= status < 600:
            if attempt < attempts:
                time.sleep(sleep_for)
                delay *= 2
                continue
            return last_error
        ...
        return {"ok": True, ...}
    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
        if attempt < attempts:
            time.sleep(delay)
            delay *= 2
            continue
        return last_error
```

**New helper shape** (from RESEARCH.md — planner uses this as the template):
```python
# Module-level global (alongside _telegram_breaker and _task_log_lines at ~line 92)
_current_subprocess: subprocess.Popen | None = None

def _subprocess_run_with_retry(
    cmd: list[str],
    *,
    timeout: int,
    backoff: int = 5,
    context: str,
    **kwargs: Any,
) -> subprocess.CompletedProcess:
    """Run subprocess, retry once on hard failure (non-zero exit or TimeoutExpired).
    Exit 0 (empty board) is NOT retried per D-02."""
    global _current_subprocess
    for attempt in range(2):
        try:
            proc = subprocess.Popen(cmd, **kwargs)
            _current_subprocess = proc
            try:
                proc.wait(timeout=timeout)
            finally:
                _current_subprocess = None
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
    raise RuntimeError(f"{context}: unreachable retry path")
```

Note: `_current_subprocess` must be set via `Popen` (not `subprocess.run`) so the SIGALRM handler (RES-03) can kill the child before the retry loop's `TimeoutExpired` path. The `TaskTimeoutError` from SIGALRM will unwind past the retry loop — the retry loop must NOT catch `TaskTimeoutError`.

#### RES-02: `_task_result` sentinel in `main()`

**Analog:** `_telegram_breaker` per-invocation reset pattern at `sports_system_runner.py` lines 92, 5582-5584.

`_telegram_breaker` module-level definition (line 92):
```python
_telegram_breaker: dict[str, Any] = {"consecutive_failures": 0, "tripped": False, "suppressed": 0}
```

`_telegram_breaker` reset in `main()` try block (lines 5580-5584):
```python
task_start_time = time.time()
try:
    # Reset per-invocation state so each task run starts with a fresh breaker and log buffer.
    _telegram_breaker["consecutive_failures"] = 0
    _telegram_breaker["tripped"] = False
    _telegram_breaker["suppressed"] = 0
    _task_log_lines.clear()
```

The `_task_result` sentinel follows the SAME per-invocation reset pattern: declare at module level (or as a local before the `try`), initialize to `None`, set only after `run_task()` returns successfully.

Current `main()` try/except structure (lines 5580-5608) — the patch target:
```python
try:
    # ... reset breaker, clear log lines ...
    with LOCK_FILE.open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        lock.write(...)
        lock.flush()
        with task_workbook_locks(args.task):
            result = run_task(args.task)
    dispatch_alerts(args.task, result)
    safe_print("JSON_RESULT=" + json.dumps(result, sort_keys=True))
    return 0
except Exception as e:
    err = {"status": "error", "task": args.task, "error": str(e), "traceback": traceback.format_exc()}
    try:
        with RUN_LOG.open("a") as _tb_file:
            _tb_file.write(f"[{now_iso()}] TRACEBACK task={args.task}:\n{traceback.format_exc()}\n")
    except Exception:
        pass
    log(f"ERROR task={args.task}: {e}")
    send_telegram(f"❌ SPORTS TASK FAILED: {args.task}\nError: {e}")
    safe_print("JSON_RESULT=" + json.dumps(err, sort_keys=True))
    return 1
finally:
    elapsed = time.time() - task_start_time
    log(f"[{args.task}] completed in {elapsed:.1f}s")
    if elapsed > 90:
        log(f"WARNING: {args.task} took {elapsed:.1f}s — consider further optimization")
    if _telegram_breaker["tripped"] and _telegram_breaker["suppressed"]:
        log(f"Telegram breaker suppressed {_telegram_breaker['suppressed']} alerts this run — Telegram unreachable")
    try:
        # ... obsidian sync ...
    except Exception:
        pass
```

RES-02 adds `_task_result: dict[str, Any] | None = None` before the `try`, then `_task_result = result` immediately after the `with task_workbook_locks(...)` block exits, then in `except`: `if _task_result is not None and isinstance(e, BrokenPipeError): log("WARNING: ..."); return 0`.

#### RES-03: SIGALRM timer + `TASK_TIMEOUTS` dict + `_sigalrm_handler`

**Analog:** `_telegram_breaker` per-invocation reset pattern (same structural position) and `safe_print` module-level helper at lines 200-208.

`safe_print` as the model for a `_`-prefixed module-private helper (lines 200-208):
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

`signal` is already importable from stdlib — check that `import signal` is not already in the file:
```bash
# Not currently imported; must be added to the import block (lines 14-39).
```

New module-level additions (pattern: alongside `_telegram_breaker` at line 92):
```python
# TASK_TIMEOUTS: all values < 120 s (confirmed Hermes no_agent hard kill window).
# Reserve ~30 s for clean shutdown (subprocess kill + Telegram alert + log flush).
TASK_TIMEOUTS: dict[str, int] = {
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

class TaskTimeoutError(Exception):
    """Raised by _sigalrm_handler when a task exceeds its wall-clock budget."""

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
    raise TaskTimeoutError("Task exceeded wall-clock budget (SIGALRM)")
```

`main()` integration — arm before locks, cancel in `finally`, handle in a separate `except TaskTimeoutError` before `except Exception` (lines 5580-5631 are the patch target):
```python
import signal

task_start_time = time.time()
_task_result: dict[str, Any] | None = None
budget = TASK_TIMEOUTS.get(args.task, 60)
old_handler = signal.signal(signal.SIGALRM, _sigalrm_handler)
signal.alarm(budget)
try:
    # ... reset breaker, clear log lines ...
    with LOCK_FILE.open("w") as lock:
        ...
        with task_workbook_locks(args.task):
            result = run_task(args.task)
    _task_result = result                    # RES-02 flag
    dispatch_alerts(args.task, result)
    safe_print("JSON_RESULT=" + json.dumps(result, sort_keys=True))
    return 0
except TaskTimeoutError as e:              # RES-03 — must come BEFORE except Exception
    log(f"TIMEOUT task={args.task}: exceeded {budget}s wall-clock budget")
    send_telegram(f"⏱ TASK TIMED OUT: {args.task}\nBudget: {budget}s exceeded")
    safe_print("JSON_RESULT=" + json.dumps(
        {"status": "timeout", "task": args.task, "budget_s": budget}, sort_keys=True
    ))
    return 1
except Exception as e:
    if _task_result is not None and isinstance(e, BrokenPipeError):  # RES-02
        log(f"WARNING: BrokenPipeError after task completion — cron pipe closed; task data persisted")
        return 0
    # real failure
    err = {...}
    log(f"ERROR task={args.task}: {e}")
    send_telegram(f"❌ SPORTS TASK FAILED: {args.task}\nError: {e}")
    safe_print("JSON_RESULT=" + json.dumps(err, sort_keys=True))
    return 1
finally:
    signal.alarm(0)                         # RES-03 — always cancel SIGALRM
    signal.signal(signal.SIGALRM, old_handler)
    elapsed = time.time() - task_start_time
    log(f"[{args.task}] completed in {elapsed:.1f}s")
    if elapsed > 90:
        log(f"WARNING: {args.task} took {elapsed:.1f}s — consider further optimization")
    if _telegram_breaker["tripped"] and _telegram_breaker["suppressed"]:
        log(f"Telegram breaker suppressed {_telegram_breaker['suppressed']} alerts this run — Telegram unreachable")
    try:
        # ... obsidian sync (unchanged) ...
    except Exception:
        pass
```

---

## Shared Patterns

### importlib runner load (for in-process test access)
**Source:** `scripts/test_fix02_telegram_circuit_breaker.py` lines 47-51
**Apply to:** `test_res01_subprocess_retry.py` (in-process monkeypatch requires this)
```python
SCRIPT: Path = Path(__file__).resolve().with_name("sports_system_runner.py")
spec = importlib.util.spec_from_file_location("sports_system_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)
```

### Subprocess-spawn subprocess test harness (for out-of-process fault injection)
**Source:** `scripts/test_fix01_broken_pipe.py` lines 120-148
**Apply to:** `test_res02_pipe_reclassify.py`, `test_res03_task_timeout.py`
```python
proc = subprocess.Popen(
    [sys.executable, "-u", str(RUNNER), "--task", REPRO_TASK],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=str(SCRIPTS_DIR),
)
try:
    proc.wait(timeout=_WAIT_TIMEOUT)
except subprocess.TimeoutExpired:
    proc.kill()
    proc.wait()
    self.fail(f"Runner subprocess timed out after {_WAIT_TIMEOUT:.0f}s ...")
```

### Nonce log fence + post-fence scan (for isolated log assertions)
**Source:** `scripts/test_fix01_broken_pipe.py` lines 72-93 (`_count_nonce_signals`) and 111-119 (fence write)
**Apply to:** `test_res02_pipe_reclassify.py`, `test_res03_task_timeout.py`
```python
nonce: str = uuid.uuid4().hex
RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
with RUN_LOG.open("a", encoding="utf-8") as fence_f:
    fence_f.write(f"[test-resNN-fence] nonce={nonce}\n")

# After proc.wait():
content = RUN_LOG.read_text(encoding="utf-8", errors="replace")
fence_pos = content.find(nonce)
after_fence = content[fence_pos:]
# count occurrences of target strings in after_fence
```

### `_`-prefixed module-private helper convention
**Source:** `scripts/sports_system_runner.py` lines 200-208 (`safe_print`), line 92 (`_telegram_breaker`)
**Apply to:** `_sigalrm_handler`, `_subprocess_run_with_retry`, `_current_subprocess`, `_task_result` in runner

### Per-invocation state reset in `main()` try block
**Source:** `scripts/sports_system_runner.py` lines 5582-5585
**Apply to:** `_task_result` sentinel reset (add alongside the `_telegram_breaker` reset)
```python
_telegram_breaker["consecutive_failures"] = 0
_telegram_breaker["tripped"] = False
_telegram_breaker["suppressed"] = 0
_task_log_lines.clear()
# RES-02 addition: _task_result is declared before the try as None (local variable, not module-level)
```

### Shebang + `from __future__ import annotations` + type annotations
**Source:** All existing test files (`test_fix01`, `test_fix02`, `test_def01`, `test_def02`) lines 1-2
**Apply to:** All three new test files
```python
#!/usr/bin/env python3
"""<docstring>"""
from __future__ import annotations
```

### `if __name__ == "__main__": unittest.main()` footer
**Source:** All existing test files, final 2 lines
**Apply to:** All three new test files

---

## Atomic Save Invariant (RES-03 mid-write safety)

**Source:** `scripts/workbook_io.py` lines 147-174

The `safe_save_workbook` sequence is interrupt-safe by construction:
```python
def safe_save_workbook(wb: Any, path: Path) -> Path | None:
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.xlsx")
    try:
        wb.save(tmp)                        # writes to temp file only
        if not zipfile.is_zipfile(tmp):
            raise zipfile.BadZipFile(...)
        test_wb = load_workbook(tmp, read_only=True, data_only=True)
        test_wb.close()
        if path.exists() and zipfile.is_zipfile(path):
            shutil.copy2(path, backup_path) # backup original
        os.replace(tmp, path)               # single atomic POSIX syscall
        return backup_path
    finally:
        if tmp.exists():
            tmp.unlink()                    # cleans orphaned .tmp on interrupt
```

SIGALRM interrupt at any point before `os.replace` leaves original workbook intact + orphaned `.tmp` (cleaned by `finally`). SIGALRM after `os.replace` leaves new workbook in place (complete). The interrupt-anywhere design (D-07) is safe; no additional guard region needed.

---

## No Analog Found

None. All four files have close analogs in the existing codebase.

---

## Metadata

**Analog search scope:** `scripts/` directory — all `test_*.py` files, `sports_system_runner.py`, `odds_api_io_client.py`, `workbook_io.py`
**Files scanned:** 7 source files read directly (test_fix01, test_fix02, test_def01, test_def02, sports_system_runner.py sections, odds_api_io_client.py sections, workbook_io.py section)
**Pattern extraction date:** 2026-06-20
