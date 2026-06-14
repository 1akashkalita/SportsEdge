# Phase 1: Diagnosis - Pattern Map

**Mapped:** 2026-06-13
**Files analyzed:** 3 (2 new, 1 modified)
**Analogs found:** 3 / 3

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `scripts/repro_broken_pipe.py` (NEW) | test/repro | request-response (subprocess pipe) | `scripts/test_prop_monitor_alert_aggregation.py` | role-match (same BrokenPipe concern); `scripts/test_game_completion_monitor_smoke.py` for subprocess+runner wiring |
| `scripts/sports_system_runner.py` (MODIFY — `main()` except block) | orchestrator | request-response | `scripts/sports_system_runner.py` lines 192–213 (`safe_print`, `log`) + lines 5636–5641 (existing except block) | exact — self-referential modification |
| `.planning/phases/01-diagnosis/DIAGNOSIS.md` (NEW) | doc | — | None (markdown deliverable, no code analog) | none |

---

## Pattern Assignments

### `scripts/repro_broken_pipe.py` (new test/repro, subprocess pipe)

**Primary analog:** `scripts/test_prop_monitor_alert_aggregation.py`
**Secondary analog (runner bootstrap):** `scripts/test_game_completion_monitor_smoke.py`

#### Header / shebang pattern (from `test_prop_monitor_alert_aggregation.py` lines 1–17)

```python
#!/usr/bin/env python3
"""Regression tests for prop-monitor alert aggregation and BrokenPipe hardening."""
from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parent / "sports_system_runner.py"
spec = importlib.util.spec_from_file_location("sports_system_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)
```

**Note for repro script:** The repro does NOT import the runner via importlib — it spawns it as a subprocess via `subprocess.Popen`. Use a simpler header without the importlib bootstrap. Copy the `Path(__file__).resolve().parent` idiom for `SCRIPTS_DIR`.

#### Runner path / SCRIPTS_DIR / RUN_LOG path pattern (from `test_game_completion_monitor_smoke.py` lines 18–36)

```python
RUNNER_PATH = Path('/Users/akashkalita/sports_picks/scripts/sports_system_runner.py')
# ...
# Path constants preferred over hardcoded absolute strings.
# Use Path(__file__).resolve().parent for portability:
SCRIPTS_DIR = Path(__file__).resolve().parent
RUNNER = SCRIPTS_DIR / "sports_system_runner.py"
```

The smoke test uses a hardcoded absolute path — prefer `Path(__file__).resolve().parent` per project style. The smoke test also shows patching of `runner.ROOT`, `runner.RUN_LOG`, etc. for isolation. For the repro, `RUN_LOG` must point to the **real** `data/pnl/logs/run_log.txt` (not a temp) so the traceback written by D-03 is observable.

Derive it as: `Path(__file__).resolve().parents[1] / "data" / "pnl" / "logs" / "run_log.txt"`

#### Subprocess spawn + pipe-closure pattern (no existing analog — new to the codebase)

The RESEARCH.md repro design specifies this pattern (lines 373–400):

```python
import subprocess, sys, os, time
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
RUNNER = SCRIPTS_DIR / "sports_system_runner.py"
RUN_LOG = SCRIPTS_DIR.parent / "data" / "pnl" / "logs" / "run_log.txt"

def count_broken_pipe_in_log(before_size: int) -> int:
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
        [sys.executable, str(RUNNER), "--test-telegram"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(SCRIPTS_DIR),
    )
    proc.stdout.close()          # simulate Hermes pipe closure
    proc.wait(timeout=60)
    new_errors = count_broken_pipe_in_log(log_size_before)
    if proc.returncode == 1 and new_errors > 0:
        print(f"PASS: BrokenPipeError reproduced and logged (returncode={proc.returncode}, new_errors={new_errors})")
        return 0
    ...

if __name__ == "__main__":
    raise SystemExit(main())
```

**Exit-code contract (from all existing test scripts):**
- `raise SystemExit(main())` — all scripts in the codebase use this pattern (`test_game_completion_monitor_smoke.py:117`, `test_mlb_system_stress.py:379`)
- Exit 0 = expected pre-fix behaviour confirmed (broken pipe reproduced)
- Exit 1 = test infrastructure failure
- Exit 2 = broken pipe NOT reproduced (unexpected; fix may already be applied)

#### BrokenPipeError assertion pattern (from `test_prop_monitor_alert_aggregation.py` lines 77–89)

```python
def test_broken_pipe_from_stdout_is_non_fatal(self) -> None:
    class BrokenStdout(io.StringIO):
        def write(self, s):
            raise BrokenPipeError("synthetic closed pipe")

    original_stdout = sys.stdout
    try:
        sys.stdout = BrokenStdout()
        runner.safe_print("this would have failed before")
        if sys.stdout is not original_stdout:
            sys.stdout.close()
    finally:
        sys.stdout = original_stdout
```

This in-process technique asserts that `safe_print` survives a broken stdout. The subprocess Popen technique in the repro script is a complement: it confirms the *process-level* broken pipe is caught by `main()`'s `except` and written to the log file. The Phase-3 regression reuse inverts the assertion: returncode=0 and no new broken-pipe log entries.

#### Type annotation style (from `test_prop_monitor_alert_aggregation.py` + runner)

```python
def count_broken_pipe_in_log(before_size: int) -> int: ...
def main() -> int: ...
```

Use `from __future__ import annotations` at top. All public functions annotated. No `Optional[]` — use `X | None` PEP 604 syntax.

---

### `scripts/sports_system_runner.py` — `main()` except block (MODIFY)

**Analog:** Existing `log()` + `safe_print()` at lines 192–213 and the `RUN_LOG.open("a")` write inside `log()` at line 206.

#### `log()` robust file-write pattern (lines 203–213)

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

**Key rules extracted:**
- File writes use `RUN_LOG.open("a")` (Path object `.open()`, not `open(str(RUN_LOG))`).
- Timestamp prefix: `f"[{now_iso()}] {msg}"` — always ISO UTC with seconds precision.
- `try / except Exception: pass` wraps every call that could fail without killing the enclosing block.
- Never write tracebacks to stdout — always to the file sink.

#### Exact insertion point for D-03/D-04 traceback dump (lines 5636–5641 — current code)

```python
    except Exception as e:
        err = {"status": "error", "task": args.task, "error": str(e), "traceback": traceback.format_exc()}
        log(f"ERROR task={args.task}: {e}")
        send_telegram(f"❌ SPORTS TASK FAILED: {args.task}\nError: {e}")
        print("JSON_RESULT=" + json.dumps(err, sort_keys=True))
        return 1
```

**Insert after line 5637 (the `err = {...}` assignment), before line 5638 (`log(...)`):**

```python
    except Exception as e:
        err = {"status": "error", "task": args.task, "error": str(e), "traceback": traceback.format_exc()}
        # D-03/D-04: Additive traceback dump to robust file sink — never stdout.
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

**Pattern rules:**
- `with RUN_LOG.open("a") as _tb_file:` — matches the `log()` write idiom exactly (same Path object, same mode).
- Wrapped in `try / except Exception: pass` — matches every other fallible operation in the codebase (`log()` line 211, `safe_print()` line 197).
- `f"[{now_iso()}] TRACEBACK task={args.task}:\n{traceback.format_exc()}\n"` — timestamp prefix matches the `log()` line format.
- Variable name `_tb_file` (underscore prefix) signals module-private/throwaway, matching CLAUDE.md naming convention: "Helper functions prefixed with `_` for module-private use."
- `traceback.format_exc()` is already imported at line 25 (`import traceback`) and already called at line 5637; no new import needed.
- `now_iso()` is already in scope; no new call site needed beyond the one in the f-string.
- **Phase 1 scope:** This three-block addition (comment + try/except + pass) is the ONLY change committed in Phase 1. Do not add `BrokenPipeError` branch or `safe_print` replacement — those are Phase 2.

#### `finally` / slow-run warning pattern (lines 5642–5646 — do not modify)

```python
    finally:
        elapsed = time.time() - task_start_time
        log(f"[{args.task}] completed in {elapsed:.1f}s")
        if elapsed > 90:
            log(f"WARNING: {args.task} took {elapsed:.1f}s — consider further optimization")
```

**Reference only — do not modify in Phase 1.** This is the pattern any temporary per-stage timing instrumentation (D-11) should mirror: `time.time()` before/after, duration formatted as `{elapsed:.1f}s`, written via `log()` (not bare `print()`), with a threshold check. If per-stage wrappers are added around `run_build_hit_rate_db` or `run_generate_projections`, follow this exact `t0 = time.time()` / `log(f"stage X: {time.time()-t0:.1f}s")` idiom.

#### Subprocess timing pattern — for optional D-11 per-stage instrumentation (lines 1345–1360)

```python
def run_build_hit_rate_db(sport: str, date: str) -> dict[str, Any]:
    """Refresh ESPN hit-rate database before daily pick generation."""
    ...
    cmd = ["/usr/local/bin/python3", str(HIT_RATE_SCRIPT), "--sport", sport, "--date", date, "--workers", "8"]
    cp = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if cp.returncode != 0:
        log(f"{sport.upper()} hit-rate build failed: exit={cp.returncode} stderr={cp.stderr[-500:]}")
        return {"status": "failed", "exit_code": cp.returncode, "stderr": cp.stderr[-1000:]}
    ...
    log(f"{sport.upper()} hit-rate build complete: {str(result)[:800]}")
    return result
```

If D-11 timing wrappers are needed, add `t0 = time.time()` before `subprocess.run(...)` and `log(f"... completed in {time.time()-t0:.1f}s")` immediately after the `cp = subprocess.run(...)` line — before the `returncode` check. This matches the overall timing style in `finally` (line 5643). These wrappers are throwaway per D-11 and should be removed before the phase is closed.

---

### `.planning/phases/01-diagnosis/DIAGNOSIS.md` (new doc)

**No code analog.** This is a plain Markdown deliverable for the operator and Phase 2 planner. No codebase file uses this format.

**Shape:** Per D-08–D-10, the document must contain:
1. **Section 1 — Broken-Pipe Root Cause (DIAG-01):** Statement, mechanism narrative, evidence artifact (run-log excerpt), confidence level, fix direction.
2. **Section 2 — Timeout Root Cause (DIAG-02):** Statement, ranked-contributors table (D-10), evidence artifact, confidence level, fix direction.

The RESEARCH.md at lines 438–463 provides the exact content for each section and the ranked-contributors table schema. The planner should reference RESEARCH.md §§ "DIAGNOSIS.md Shape" and "Ranked contributors table" directly when generating the DIAGNOSIS.md action.

---

## Shared Patterns

### File-sink write (robust, never stdout)

**Source:** `scripts/sports_system_runner.py` lines 203–213 (`log()`)
**Apply to:** The D-03/D-04 traceback hook and any other new write to `data/pnl/logs/`

```python
with RUN_LOG.open("a") as f:
    f.write(line + "\n")
```

Wrapped in `try / except Exception: pass`. Uses the `RUN_LOG` Path constant (line 57), not a string. Appends, never overwrites.

### `try / except Exception: pass` defensive wrapper

**Source:** `scripts/sports_system_runner.py` lines 209–212 (inside `log()`), line 196–200 (inside `safe_print()`)
**Apply to:** Every new fallible call added inside an already-failing `except` block

```python
try:
    <fallible operation>
except Exception:
    pass
```

Never let a secondary failure inside the `except` block mask the original exception or propagate further.

### `raise SystemExit(main())` entry point

**Source:** `test_game_completion_monitor_smoke.py` line 117, `test_mlb_system_stress.py` line 379, `sports_system_runner.py` line 5650
**Apply to:** `scripts/repro_broken_pipe.py`

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

All scripts in this codebase use `raise SystemExit(main())`, not `sys.exit(main())` or bare `main()`.

### `from __future__ import annotations` + type annotation style

**Source:** Every test file (`test_prop_monitor_alert_aggregation.py` line 5, `test_game_completion_monitor_smoke.py` line 9, `test_mlb_system_stress.py` line 9)
**Apply to:** `scripts/repro_broken_pipe.py`

```python
from __future__ import annotations
```

All parameters and return types annotated. Use `X | None` not `Optional[X]`. Use `dict[str, Any]` not `Dict[str, Any]`.

### `cwd=str(SCRIPTS_DIR)` for subprocess invocations

**Source:** CLAUDE.md and RESEARCH.md (sibling module imports require `scripts/` as cwd)
**Apply to:** `scripts/repro_broken_pipe.py` Popen call

```python
proc = subprocess.Popen(
    [sys.executable, str(RUNNER), "--test-telegram"],
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=str(SCRIPTS_DIR),
)
```

Must pass `cwd=str(SCRIPTS_DIR)` — the runner's sibling imports (`from slip_payouts import ...`) require `scripts/` to be the working directory.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `scripts/repro_broken_pipe.py` — subprocess pipe-closure mechanism | test/repro | subprocess pipe | No existing test in the codebase spawns the runner as a subprocess and closes the pipe; all existing tests use importlib in-process loading or mock.patch |
| `.planning/phases/01-diagnosis/DIAGNOSIS.md` | doc | — | No markdown report files in `scripts/` or `data/` serve as analogs |

---

## Metadata

**Analog search scope:** `scripts/test_*.py` (20 files), `scripts/sports_system_runner.py` (lines 1–215, 1264–1395, 5610–5651)
**Files scanned:** 7 (test_prop_monitor_alert_aggregation.py, test_game_completion_monitor_smoke.py, test_mlb_system_stress.py, test_stage1_platform_outputs.py, test_stage5_telegram_platform.py, test_prop_monitor_full_board.py, sports_system_runner.py)
**Pattern extraction date:** 2026-06-13
