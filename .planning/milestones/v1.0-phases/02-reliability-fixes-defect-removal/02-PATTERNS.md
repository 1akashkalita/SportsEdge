# Phase 2: Reliability Fixes + Defect Removal - Pattern Map

**Mapped:** 2026-06-15
**Files analyzed:** 6 (3 modified, 1 extended, 2 new)
**Analogs found:** 6 / 6

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `scripts/sports_system_runner.py` — `send_telegram()` (D-02/D-03) | utility/alerter | request-response | `scripts/sports_system_runner.py` `send_telegram()` itself (current state is the before-image) | self |
| `scripts/sports_system_runner.py` — `log()` + `dispatch_alerts()` (D-04) | orchestrator | event-driven | `scripts/sports_system_runner.py` `dispatch_alerts()` + `log()` themselves | self |
| `scripts/sports_system_runner.py` — `safe_print()` sweep + `main()` (D-05/D-07) | utility | request-response | `scripts/sports_system_runner.py` `safe_print()` itself (reuse target) | self |
| `scripts/sports_system_runner.py` — remove duplicate `injury_monitor` (~3610) / `clv_tracker` (~3651) (DEF-01) | orchestrator | CRUD | active definitions at lines 5049 / 5443 | self/exact |
| `scripts/generate_projections.py` — replace hardcoded `BASE` path (DEF-02) | subprocess stage | batch | `scripts/repro_broken_pipe.py` portable-path idiom; `test_game_completion_monitor_smoke.py` `patch_isolated_paths` | role-match |
| `scripts/repro_broken_pipe.py` — extend for FIX-01/FIX-02 regression (D-09) | regression harness | event-driven | `scripts/repro_broken_pipe.py` itself (current state is the base to extend) | self |
| NEW `scripts/test_fix01_broken_pipe.py` | test | event-driven | `scripts/repro_broken_pipe.py`, `scripts/test_game_completion_monitor_smoke.py` | role-match |
| NEW `scripts/test_fix02_telegram_circuit_breaker.py` | test | request-response | `scripts/test_odds_api_io_client.py` (mock/FakeSession), `scripts/test_stage5_telegram_platform.py` (importlib load + monkeypatch) | exact |
| NEW `scripts/test_def02_path_resolution.py` | test | batch | `scripts/test_generate_projections.py` (direct-import + unittest.TestCase) | exact |
| NEW `scripts/run_all_tasks.py` — D-08 run-all harness | harness/ops | batch | `scripts/repro_broken_pipe.py` (subprocess.Popen of runner, CWD=scripts/, exit-code check) | role-match |

---

## Pattern Assignments

### `scripts/sports_system_runner.py` — `send_telegram()` (D-02: cap + circuit-breaker)

**Analog:** `scripts/sports_system_runner.py` lines 233–259 (current `send_telegram`)

**Current state — imports and signature** (lines 233–234):
```python
def send_telegram(message: str, retries: int = 2, backoff: int = 5) -> bool:
    """Send a real Telegram alert to the configured Hermes home channel without crashing tasks."""
```

**Current retry loop** (lines 244–258) — this is the unbounded stall source:
```python
    delay = backoff
    for attempt in range(retries):
        try:
            r = requests.post(TELEGRAM_API.format(token=token), json=payload, timeout=30)
            if r.status_code == 200:
                log("Telegram alert sent")
                return True
            log(f"Telegram alert failed attempt {attempt+1}/{retries}: status={r.status_code} body={r.text[:300]}")
        except requests.exceptions.RequestException as e:
            log(f"Telegram alert failed attempt {attempt+1}/{retries}: {e}")
        except Exception as e:
            log(f"Telegram alert failed attempt {attempt+1}/{retries}: {e}")
        if attempt < retries - 1:
            time.sleep(delay)
    log("Telegram alert failed after all retries; continuing without crashing task")
    return False
```

**Pattern to apply (D-02/D-03):**
- Add a module-level mutable state object `_telegram_breaker: dict[str, Any]` with keys `consecutive_failures: int`, `tripped: bool`, `suppressed: int`. Reset it at the start of each task invocation (e.g. in `run_task()` or at the top of `main()`'s try block).
- Shorten `timeout=30` to a short value (planner discretion: 8–10s suggested).
- At the top of `send_telegram()`, check `_telegram_breaker["tripped"]`; if true, increment `suppressed`, return `False` immediately.
- After all retries exhausted, increment `consecutive_failures`; if `>= N` (planner: N=3), set `tripped=True`.
- On success, reset `consecutive_failures=0`.
- The suppressed-count log line (D-03) is written exactly once, lazily, when `tripped` transitions from `False` to `True`: `log(f"{suppressed+1} Telegram alerts suppressed — Telegram unreachable")`. Subsequent suppressed calls just increment the counter and return silently (the one summary line already written covers all of them).

**Defensive "never crash a task" invariant — preserve this:**
```python
    except Exception as e:
        log(f"Telegram alert failed attempt {attempt+1}/{retries}: {e}")
```
All exceptions inside `send_telegram()` are caught; the function always returns `bool`.

---

### `scripts/sports_system_runner.py` — `log()` + `dispatch_alerts()` (D-04: decouple Obsidian to summary-only)

**Analog:** `scripts/sports_system_runner.py` lines 203–213 (current `log`) and 1040–1054 (current `dispatch_alerts`)

**Current `log()` — the per-line Obsidian fanout (the Rank 2 stall source):**
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

**Pattern to apply (D-04):**
- Remove the `obsidian_sync(...)` call from `log()`. The `try/except` wrapper stays absent — no per-line sync.
- Add a `_task_log_lines: list[str]` module-level accumulator. Append to it inside `log()`.
- In `dispatch_alerts()` (after task success) OR in `main()`'s `finally` block (after both success and failure), call `obsidian_sync` exactly once with the meaningful task-result summary. The payload should include the task name, final result dict, and a joined excerpt of key log lines (not every raw line — just the meaningful task summary the operator relies on per vault section: Dashboard / Picks / Recaps / Intel).
- Preserve the `safe_print(line)` call in `log()` — it is the stdout mirror and is not removed.
- Preserve the `RUN_LOG.open("a")` write — the run-log file write stays per-line as now.

**Current `dispatch_alerts()` — call site for single-shot Obsidian sync:**
```python
def dispatch_alerts(task: str, result: dict[str, Any]) -> None:
    if result.get("status") != "ok":
        return
    if task in ("nba_daily_picks", "mlb_daily_picks"):
        send_telegram(build_picks_alert(task.split("_", 1)[0], result))
    elif task in ("nba_prop_monitor", "mlb_prop_monitor"):
        moves = result.get("line_moves", []) or []
        if moves:
            send_telegram(build_line_move_summary_alert(task, moves))
    elif task in ("nba_injury_monitor", "mlb_injury_monitor"):
        for change in result.get("status_changes", []):
            send_telegram(build_injury_alert(change))
    elif task == "check_results":
        send_telegram(build_recap_alert(result))
    maybe_rate_limit_alert(result)
```
Add the single `obsidian_sync(...)` call at the end of `dispatch_alerts()` (after the `send_telegram` calls), guarded by `try/except Exception`.

---

### `scripts/sports_system_runner.py` — `safe_print()` sweep in `main()` and `run_fetch_dfs_props` (D-05/D-07)

**Analog:** `scripts/sports_system_runner.py` lines 192–200 (`safe_print` definition) — **reuse unchanged**

**`safe_print()` — the existing swallow pattern (lines 192–200):**
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

**Sites to sweep (D-05) — replace bare `print(...)` with `safe_print(...)`:**

Site 1 — `main()` success path (line 5634):
```python
    # BEFORE:
    print("JSON_RESULT=" + json.dumps(result, sort_keys=True))
    # AFTER:
    safe_print("JSON_RESULT=" + json.dumps(result, sort_keys=True))
```

Site 2 — `main()` except-block error path (line 5648):
```python
    # BEFORE:
    print("JSON_RESULT=" + json.dumps(err, sort_keys=True))
    # AFTER:
    safe_print("JSON_RESULT=" + json.dumps(err, sort_keys=True))
```

Site 3 — `run_fetch_dfs_props` subprocess stdout relay (line 1274):
```python
    # BEFORE:
    print(cp.stdout.rstrip())
    # AFTER:
    safe_print(cp.stdout.rstrip())
```

**Invariant to preserve (D-07):** Under normal (non-broken-pipe) operation, `safe_print()` calls `print()` and returns normally. The `JSON_RESULT=` contract is unchanged for callers.

---

### `scripts/sports_system_runner.py` — DEF-01: Remove duplicate `injury_monitor` / `clv_tracker`

**Dead definitions to remove** (lines 3610–3648 `injury_monitor`, lines 3651–3667 `clv_tracker`):
The earlier `injury_monitor` (~3610) is a 38-line stub that reads only from the workbook's cached baseline and never calls ESPN, `espn_injury_rows`, or `calculate_injury_impact`. It is functionally dead (Python uses the last definition) and the active version at 5049 is a strict superset.

The earlier `clv_tracker` (~3651) is a 17-line version that calls only `odds_api()` and appends game rows. The active version at 5443 is a strict superset.

**Diff evidence:**
- Earlier `injury_monitor` (3610): reads `injuries.cell(r, 5/6).value` directly — no ESPN call, no `espn_injury_rows`, no `calculate_injury_impact`, no `find_injury_baseline_row`.
- Active `injury_monitor` (5049): calls `espn_injury_rows`, `espn_injury_news_flags`, `enrich_picks_with_espn_odds`, `calculate_injury_impact`, `find_injury_baseline_row`, `affected_items_for_player`, `set_affected_statuses`, `extract_current_pp_line` — full implementation.
- Earlier `clv_tracker` (3651): calls `odds_api()` directly and uses `append_unique`. Active version (5443) uses the `OddsApiIoClient` path with `resolve_odds_api_io_league` and richer result dict.

**No unique logic in either earlier definition** — safe to delete both blocks.

**Active definitions location for reference:**
- `injury_monitor` active: lines 5049–(~5180)
- `clv_tracker` active: lines 5443–(~5540)

---

### `scripts/generate_projections.py` — DEF-02: Replace hardcoded `BASE` path

**Hardcoded path (line 26):**
```python
BASE = Path("/Users/akashkalita/sports_picks")
```

**Portable pattern — from `scripts/repro_broken_pipe.py` lines 113–114:**
```python
SCRIPTS_DIR: Path = Path(__file__).resolve().parent
RUNNER: Path = SCRIPTS_DIR / "sports_system_runner.py"
```

**Apply the same idiom in `generate_projections.py`:**
```python
# BEFORE:
BASE = Path("/Users/akashkalita/sports_picks")

# AFTER:
BASE = Path(__file__).resolve().parents[1]   # scripts/ -> repo root
```
`Path(__file__).resolve().parent` is `scripts/`; `.parents[1]` is the repo root (`sports_picks/`). All downstream constants (`DATA`, `HIT_RATE_DIR`, `PROJ_DIR`, `NBA_DIR`, `MLB_DIR`, `RUN_LOG`) derived from `BASE` remain unchanged in their derivation — only the root anchor changes.

**Secondary cross-check — `test_game_completion_monitor_smoke.py` lines 18–19 also derives root portably:**
```python
RUNNER_PATH = Path('/Users/akashkalita/sports_picks/scripts/sports_system_runner.py')
```
Note: that file uses a hardcoded path too — but `repro_broken_pipe.py` is the cleaner model. Do NOT update `test_game_completion_monitor_smoke.py` in Phase 2 (out of scope).

---

### `scripts/repro_broken_pipe.py` — Extend for FIX-01/FIX-02 regression (D-09)

**Base to extend:** the full existing `repro_broken_pipe.py` (289 lines).

**WR-03 harden — current racy log-scan issue (lines 195, 154–165):**
The script snapshots `RUN_LOG.stat().st_size` (byte offset) before the run and later seeks to that offset. The risk is if `RUN_LOG` doesn't exist yet (`RUN_LOG.stat()` raises). The existing guard `if RUN_LOG.exists() else 0` handles non-existence. The racy aspect noted in WR-03 is: if another process appends to the log between the `stat()` call and the subprocess start, the offset is stale. Fix: use `RUN_LOG.stat().st_size` inside a `try/except OSError` and hold it as a local — no other changes needed for Phase 2 scope.

**FIX-01 regression assertion (post-fix behavior):** After `safe_print()` is swept, the runner exits 0 with no broken-pipe log signals. The current script already handles this case as exit code 2:
```python
elif returncode == 0 and new_signals == 0:
    # Fix already applied: runner exited cleanly with no broken-pipe log signals.
    print(
        f"FAIL (not reproduced): runner exited 0 with no broken-pipe log signals. "
        f"Fix may already be applied. "
        ...
    )
    return 2
```
Invert the pass/fail logic: after the fix, the **regression** test asserts `returncode == 0 and new_signals == 0` is the **PASS** condition (fix is working). Rename exit 2 from "not reproduced" to "PASS: fix confirmed" in this branch, and rename the old exit 0 to "FAIL: regression — broken pipe leaked".

**FIX-02 Telegram circuit-breaker regression:** Add a second `main`-style function (or a new `--mode fix02` argument) that:
1. Monkeypatches `requests.post` inside the runner module to always raise `requests.exceptions.ConnectionError("simulated unreachable")`.
2. Spawns the runner with `--task verify` (or invokes `runner.send_telegram()` directly after importlib load).
3. Asserts: task completes within a bounded wall-clock time (< 30s with short timeout and N=3), `send_telegram()` returns `False`, `_telegram_breaker["tripped"]` is `True`, and `RUN_LOG` contains a line matching `"alerts suppressed — Telegram unreachable"`.

**Subprocess spawn pattern — preserve from existing file (lines 205–213):**
```python
proc = subprocess.Popen(
    [sys.executable, "-u", str(RUNNER), "--task", REPRO_TASK],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=str(SCRIPTS_DIR),
)
```

---

### NEW `scripts/test_fix01_broken_pipe.py`

**Analog:** `scripts/repro_broken_pipe.py` (subprocess pattern) + `scripts/test_game_completion_monitor_smoke.py` (structured test script pattern)

**Header pattern** (from `test_game_completion_monitor_smoke.py` lines 1–21):
```python
#!/usr/bin/env python3
"""Regression test: FIX-01 — safe_print() sweep prevents spurious TASK FAILED on broken pipe."""
from __future__ import annotations

import subprocess
import sys
import threading
import unittest
from pathlib import Path

SCRIPTS_DIR: Path = Path(__file__).resolve().parent
RUNNER: Path = SCRIPTS_DIR / "sports_system_runner.py"
RUN_LOG: Path = SCRIPTS_DIR.parent / "data" / "pnl" / "logs" / "run_log.txt"
```

**Test class structure** (from `test_stage5_telegram_platform.py` lines 11–20):
```python
class TestFix01BrokenPipe(unittest.TestCase):
    def test_no_spurious_task_failed_after_pipe_close(self) -> None:
        # spawn runner with -u, close pipe at sentinel, assert returncode == 0
        ...
```

**`__main__` pattern** (from `test_slip_payouts.py` lines 102–103):
```python
if __name__ == "__main__":
    unittest.main()
```

---

### NEW `scripts/test_fix02_telegram_circuit_breaker.py`

**Analog:** `scripts/test_odds_api_io_client.py` (FakeSession + `unittest.mock.patch`) + `scripts/test_stage5_telegram_platform.py` (importlib runner load + attribute monkeypatch)

**Importlib-load pattern** (from `test_stage5_telegram_platform.py` lines 15–20):
```python
SCRIPT = Path(__file__).resolve().with_name("sports_system_runner.py")
spec = importlib.util.spec_from_file_location("sports_system_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)
```

**Mock-network pattern** (from `test_odds_api_io_client.py` lines 37–48):
```python
class FakeSession:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []

    def request(self, method, url, params=None, timeout=None):
        self.calls.append({"method": method, "url": url, ...})
        if self.responses:
            item = self.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item
        return FakeResponse(data=[])
```

**`unittest.mock.patch` pattern** (from `test_stage1_platform_outputs.py` lines 48–50):
```python
with patch.object(runner, "obsidian_sync", side_effect=lambda payload: captured.append(payload) or {"ok": True}):
    runner.obsidian_append_line_moves([...], sport="MLB", date="2026-06-10")
```

**Test structure for circuit breaker:**
```python
import importlib.util
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import requests

SCRIPT = Path(__file__).resolve().with_name("sports_system_runner.py")
spec = importlib.util.spec_from_file_location("sports_system_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)


class TestFix02TelegramCircuitBreaker(unittest.TestCase):
    def setUp(self) -> None:
        # Reset breaker state before each test
        runner._telegram_breaker["consecutive_failures"] = 0
        runner._telegram_breaker["tripped"] = False
        runner._telegram_breaker["suppressed"] = 0

    def test_breaker_trips_after_n_failures(self) -> None:
        with patch.object(requests, "post", side_effect=requests.exceptions.ConnectionError("simulated")):
            # force enough failures to trip the breaker
            for _ in range(5):
                runner.send_telegram("test message")
        self.assertTrue(runner._telegram_breaker["tripped"])

    def test_breaker_tripped_suppresses_immediately(self) -> None:
        runner._telegram_breaker["tripped"] = True
        start = time.monotonic()
        result = runner.send_telegram("suppressed message")
        elapsed = time.monotonic() - start
        self.assertFalse(result)
        self.assertLess(elapsed, 0.1)   # must return immediately, not stall

    def test_suppressed_count_logged(self) -> None:
        log_lines: list[str] = []
        original_log = runner.log
        runner.log = lambda msg: log_lines.append(msg)
        try:
            runner._telegram_breaker["tripped"] = True
            runner.send_telegram("suppressed message")
        finally:
            runner.log = original_log
        # At least one log line must mention suppression
        self.assertTrue(
            any("suppressed" in l.lower() or "unreachable" in l.lower() for l in log_lines)
        )


if __name__ == "__main__":
    unittest.main()
```

---

### NEW `scripts/test_def02_path_resolution.py`

**Analog:** `scripts/test_generate_projections.py` (direct-import + `unittest.TestCase`, lines 1–16)

**Direct-import pattern** (from `test_generate_projections.py` lines 11–16):
```python
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_projections as gp
```

**Test structure:**
```python
#!/usr/bin/env python3
"""Regression test: DEF-02 — generate_projections BASE path resolves portably."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_projections as gp


class TestDef02PathResolution(unittest.TestCase):
    def test_base_does_not_contain_hardcoded_username(self) -> None:
        base_str = str(gp.BASE)
        self.assertNotIn("akashkalita", base_str,
            f"BASE still contains hardcoded username: {base_str!r}")

    def test_base_is_absolute_and_exists(self) -> None:
        self.assertTrue(gp.BASE.is_absolute(), f"BASE is not absolute: {gp.BASE}")
        self.assertTrue(gp.BASE.exists(), f"BASE path does not exist: {gp.BASE}")

    def test_data_dir_is_under_base(self) -> None:
        self.assertTrue(str(gp.DATA).startswith(str(gp.BASE)),
            f"DATA {gp.DATA!r} is not under BASE {gp.BASE!r}")

    def test_hit_rate_dir_exists(self) -> None:
        self.assertTrue(gp.HIT_RATE_DIR.exists(),
            f"HIT_RATE_DIR not found: {gp.HIT_RATE_DIR}")


if __name__ == "__main__":
    unittest.main()
```

---

### NEW `scripts/run_all_tasks.py` — D-08 run-all harness

**Analog:** `scripts/repro_broken_pipe.py` (subprocess.Popen of runner, `cwd=SCRIPTS_DIR`, exit-code assertions, structured `main() -> int` + `raise SystemExit(main())`)

**Subprocess invocation pattern** (from `repro_broken_pipe.py` lines 205–213):
```python
proc = subprocess.Popen(
    [sys.executable, "-u", str(RUNNER), "--task", REPRO_TASK],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=str(SCRIPTS_DIR),
)
```

**Complete structure:**
```python
#!/usr/bin/env python3
"""D-08 run-all harness: invoke all 11 runner tasks sequentially and assert each exits 0."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR: Path = Path(__file__).resolve().parent
RUNNER: Path = SCRIPTS_DIR / "sports_system_runner.py"

ALL_TASKS: list[str] = [
    "nba_daily_picks",
    "mlb_daily_picks",
    "nba_prop_monitor",
    "mlb_prop_monitor",
    "nba_injury_monitor",
    "mlb_injury_monitor",
    "nba_clv_tracker",
    "mlb_clv_tracker",
    "game_completion_monitor",
    "check_results",
    "verify",
]

TASK_TIMEOUT: float = 600.0   # seconds; matches runner's max subprocess budget


def run_task(task: str) -> tuple[int, str, str]:
    """Run a single task, return (returncode, stdout, stderr)."""
    proc = subprocess.Popen(
        [sys.executable, "-u", str(RUNNER), "--task", task],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(SCRIPTS_DIR),
    )
    try:
        stdout_raw, stderr_raw = proc.communicate(timeout=TASK_TIMEOUT)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        return -1, "", f"TIMEOUT after {TASK_TIMEOUT:.0f}s"
    return proc.returncode, stdout_raw.decode("utf-8", errors="replace"), stderr_raw.decode("utf-8", errors="replace")


def main() -> int:
    failures: list[str] = []
    for task in ALL_TASKS:
        print(f"[run-all] running: {task} ...", flush=True)
        rc, stdout, stderr = run_task(task)
        ok = rc == 0 and "JSON_RESULT=" in stdout
        status = "OK" if ok else f"FAIL (exit={rc})"
        print(f"[run-all] {task}: {status}")
        if not ok:
            failures.append(task)
            if stderr.strip():
                print(f"  stderr: {stderr.strip()[:300]}")
    if failures:
        print(f"\nFAILED tasks: {', '.join(failures)}")
        return 1
    print(f"\nAll {len(ALL_TASKS)} tasks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

---

## Shared Patterns

### `safe_print()` — the BrokenPipeError swallow
**Source:** `scripts/sports_system_runner.py` lines 192–200
**Apply to:** ALL bare top-level `print(...)` calls in `main()` (lines 5634, 5648) and `run_fetch_dfs_props` (line 1274)

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

### Importlib module load (all runner-touching tests)
**Source:** `scripts/test_stage5_telegram_platform.py` lines 15–20 and `scripts/test_dynamic_gate8.py` lines 8–12
**Apply to:** `test_fix01_broken_pipe.py`, `test_fix02_telegram_circuit_breaker.py`

```python
SCRIPT = Path(__file__).resolve().with_name("sports_system_runner.py")
spec = importlib.util.spec_from_file_location("sports_system_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)
```

### Portable path root derivation
**Source:** `scripts/repro_broken_pipe.py` lines 113–114
**Apply to:** `scripts/generate_projections.py` (DEF-02), all new test/harness files

```python
SCRIPTS_DIR: Path = Path(__file__).resolve().parent   # scripts/
# repo root = one level up:
BASE: Path = Path(__file__).resolve().parents[1]
```

### Defensive "never crash a task" exception handling
**Source:** `scripts/sports_system_runner.py` `send_telegram()` lines 252–255 and `log()` lines 209–212
**Apply to:** the circuit-breaker block in the new `send_telegram()`, the Obsidian summary-sync call in `dispatch_alerts()`

```python
    try:
        obsidian_sync({"trigger": "...", ...})
    except Exception:
        pass
```

### Module-level state dict for per-invocation circuit-breaker
**Pattern:** New dict initialized at module load, reset at task-run boundary. No class, no threading primitives — single-process, single-task model.

```python
# module level (after imports):
_telegram_breaker: dict[str, Any] = {
    "consecutive_failures": 0,
    "tripped": False,
    "suppressed": 0,
}
```
Reset in `main()` or `run_task()` before the task body runs:
```python
_telegram_breaker.update({"consecutive_failures": 0, "tripped": False, "suppressed": 0})
```

### `unittest.TestCase` with `__main__` guard
**Source:** `scripts/test_slip_payouts.py` lines 17, 102–103; `scripts/test_generate_projections.py` lines 45, 133–134
**Apply to:** all new `test_*.py` files

```python
class TestFooBar(unittest.TestCase):
    def test_something(self) -> None:
        ...

if __name__ == "__main__":
    unittest.main()
```

### `sys.path.insert` for direct-import tests
**Source:** `scripts/test_generate_projections.py` lines 11–13; `scripts/test_slip_payouts.py` lines 7–8
**Apply to:** `test_def02_path_resolution.py` (direct `import generate_projections`)

```python
sys.path.insert(0, str(Path(__file__).resolve().parent))
```

---

## No Analog Found

All files have close analogs in the codebase. No new external patterns required.

| File | Note |
|---|---|
| `_telegram_breaker` circuit-breaker dict | Pattern is novel for this codebase but follows the existing module-level-constant convention (e.g. `DAILY_EXPOSURE_CAP`, `GENERATED_MARKER`). Use a plain `dict[str, Any]` at module level — no class needed. |

---

## Metadata

**Analog search scope:** `scripts/` (all `.py` files)
**Files scanned:** 10 source files read in full or targeted sections
**Pattern extraction date:** 2026-06-15
