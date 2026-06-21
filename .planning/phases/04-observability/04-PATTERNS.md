# Phase 4: Observability - Pattern Map

**Mapped:** 2026-06-21
**Files analyzed:** 3 (1 new standalone script, 1 modified runner section, 1 new test file)
**Analogs found:** 3 / 3

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `scripts/sports_system_runner.py` (OBS-01 JSONL emit in `finally`) | utility | file-I/O | `scripts/sports_system_runner.py` `main()` `finally` existing `log()` + `RUN_LOG.open("a")` (lines 5731–5756) | exact — same block, sibling write |
| `scripts/sports_system_runner.py` (OBS-03 streak check in `except`/timeout branches) | utility | file-I/O + request-response | `scripts/sports_system_runner.py` `send_telegram()` call sites (lines 5705–5730) + `env_bool` flag cluster (lines 200–223) | exact — same branches, sibling alert |
| `scripts/health_check.py` (NEW, OBS-02) | utility / standalone script | file-I/O + request-response | `scripts/send_slips_telegram.py` — standalone `argparse` + duplicated `env_value` + `send_telegram` + `main() -> int` + `raise SystemExit(main())` pattern | role-match exact — read-only, no lock, same alert channel |
| `scripts/test_obs_*.py` (NEW, unit tests for OBS-01/02/03) | test | — | `scripts/test_line_timing.py` and `scripts/test_slip_payouts.py` — `unittest.TestCase`, `sys.path.insert`, optional `importlib` for runner | exact |

---

## Pattern Assignments

### OBS-01: JSONL emit in `main()`'s `finally` block

**Analog:** `scripts/sports_system_runner.py` lines 5731–5756 (the existing `finally` block) and lines 312–319 (`log()` writing to `RUN_LOG`).

**Path constants pattern** (lines 56–58):
```python
LOG_DIR = PNL_DIR / "logs"
RUN_LOG = LOG_DIR / "run_log.txt"
# Add sibling below RUN_LOG:
RUN_LOG_JSONL = LOG_DIR / "run_log.jsonl"
```

**Append-only file-write pattern** — existing `log()` (lines 312–319):
```python
def log(msg: str) -> None:
    ensure_dirs()
    line = f"[{now_iso()}] {msg}"
    with RUN_LOG.open("a") as f:
        f.write(line + "\n")
    _task_log_lines.append(line)
    safe_print(line)
```
The JSONL emit mirrors this but calls `json.dumps()` + `"\n"` instead of a formatted string.

**JSON serialization-to-file pattern** — `save_game_status_cache()` (line 4242):
```python
GAME_STATUS_CACHE_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True) + "\n")
```
For append-only JSONL the `open("a")` form from `log()` is correct; `write_text` overwrites. Use the `log()` append pattern, not `write_text`.

**Existing `finally` block where OBS-01 slots in** (lines 5731–5756):
```python
finally:
    # RES-03: always cancel SIGALRM and restore the prior handler, even on timeout/error.
    signal.alarm(0)
    signal.signal(signal.SIGALRM, old_handler)
    elapsed = time.time() - task_start_time
    log(f"[{args.task}] completed in {elapsed:.1f}s")
    if elapsed > 90:
        log(f"WARNING: {args.task} took {elapsed:.1f}s — consider further optimization")
    # WR-01: emit the REAL suppressed count at task end so operators can see it in logs.
    if _telegram_breaker["tripped"] and _telegram_breaker["suppressed"]:
        log(f"Telegram breaker suppressed {_telegram_breaker['suppressed']} alerts this run — Telegram unreachable")
    # Single end-of-task Obsidian sync (D-04)...
    try:
        task_name = getattr(args, "task", None) or "unknown"
        log_excerpt = "\n".join(_task_log_lines[-50:])
        summary_line = f"[{task_name}] completed in {round(elapsed, 1)}s\n{log_excerpt}"
        obsidian_sync({
            "trigger": "sports_run_log",
            "date": today_str(),
            "data": {"line": summary_line},
        })
    except Exception:
        pass
```
**OBS-01 record emit slots in BEFORE the Obsidian sync block** and AFTER the `log(f"[{args.task}] completed in ...")` call. The `finally` block already has `elapsed`, `args.task`, and all needed values. The current-run's `status` must be derived from the local `_task_result` sentinel (None means error/timeout) and any caught exception.

**ISO timestamp helper** (lines 278–279):
```python
def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
```

**D-02 JSONL record shape** (all values are already in scope at `finally` time):
```python
record = {
    "task": args.task,
    "status": "ok" | "error" | "timeout",   # derived from _task_result / exception
    "duration_s": round(elapsed, 1),
    "error": str(e) | None,
    "timestamp": now_iso(),
    "exit_code": 0 | 1,
    # Only "nba_"/"mlb_"-prefixed tasks map to a sport; everything else
    # (game_completion_monitor, check_results, verify) is None. A bare
    # split("_")[0] would WRONGLY yield "game"/"check" — guard on the prefix.
    "sport": args.task.split("_")[0] if args.task.startswith(("nba_", "mlb_")) else None,
}
```
Wrap the append in `try/except Exception: pass` so a log-write failure never crashes the task — same defensive pattern as the Obsidian sync block above.

---

### OBS-03: Streak check in `except` / `TaskTimeoutError` branches

**Analog:** `scripts/sports_system_runner.py` lines 5705–5730 (the two alert call sites) and lines 200–204 (`env_bool` pattern).

**Existing timeout branch** (lines 5705–5712) — OBS-03 slots in AFTER `send_telegram(f"⏱ TASK TIMED OUT: ...")`:
```python
except TaskTimeoutError:
    # RES-03: distinct timeout alert — separate from ❌ SPORTS TASK FAILED (D-06).
    log(f"TIMEOUT task={args.task}: exceeded {budget}s wall-clock budget")
    send_telegram(f"⏱ TASK TIMED OUT: {args.task}\nBudget: {budget}s exceeded")
    safe_print("JSON_RESULT=" + json.dumps(
        {"status": "timeout", "task": args.task, "budget_s": budget}, sort_keys=True
    ))
    return 1
```

**Existing error branch** (lines 5713–5730) — OBS-03 slots in AFTER `send_telegram(f"❌ SPORTS TASK FAILED: ...")`:
```python
except Exception as e:
    if _task_result is not None and isinstance(e, BrokenPipeError):
        log("WARNING: BrokenPipeError after task completion — cron pipe closed; task data persisted")
        return 0
    err = {"status": "error", "task": args.task, "error": str(e), "traceback": traceback.format_exc()}
    try:
        with RUN_LOG.open("a") as _tb_file:
            _tb_file.write(
                f"[{now_iso()}] TRACEBACK task={args.task}:\n{traceback.format_exc()}\n"
            )
    except Exception:
        pass
    log(f"ERROR task={args.task}: {e}")
    send_telegram(f"❌ SPORTS TASK FAILED: {args.task}\nError: {e}")
    safe_print("JSON_RESULT=" + json.dumps(err, sort_keys=True))
    return 1
```

**`env_bool` config pattern for OBS-03 threshold knob** (lines 200–223):
```python
def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "enabled"}

USE_PRIZEPICKS_FOR_PLAYER_PROPS = env_bool("USE_PRIZEPICKS_FOR_PLAYER_PROPS", True)
ENABLE_DABBLE_PROP_COMPARISON = env_bool("ENABLE_DABBLE_PROP_COMPARISON", False)
```
For OBS-03 the threshold is an integer, not a bool — use `env_value()` (lines 322–336) and `int()` with a fallback:
```python
REPEATED_FAILURE_THRESHOLD = int(env_value("REPEATED_FAILURE_THRESHOLD") or "2")
```
This constant is declared at module level beside `TASK_TIMEOUTS` (line 112).

**`TASK_TIMEOUTS` structure for the sibling cadence map** (lines 112–124):
```python
TASK_TIMEOUTS: dict[str, int] = {
    "nba_daily_picks": 660,
    "mlb_daily_picks": 660,
    "nba_prop_monitor": 660,
    "mlb_prop_monitor": 660,
    "nba_clv_tracker": 660,
    "mlb_clv_tracker": 660,
    "nba_injury_monitor": 660,
    "mlb_injury_monitor": 660,
    "game_completion_monitor": 660,
    "check_results": 660,
    "verify": 660,
}
```
The OBS-02 cadence map mirrors the same 11 keys with `max_staleness_seconds` values instead of budget seconds.

**OBS-03 streak-read logic note (from D-09):** At failure time, the current run's record has NOT yet been written to JSONL (it is written in `finally` which runs after the `except` block). The streak helper must therefore read only PRIOR records from the JSONL file and then combine the current outcome's status (`"error"` or `"timeout"`) to arrive at the trailing count. Pattern: read tail of JSONL for `task`, filter to trailing records where `status in {"error", "timeout"}` (stop at first `status == "ok"`), then add 1 for the current failure.

**`🔁` alert shape mirrors existing sibling alerts:**
```python
send_telegram(f"🔁 REPEATED FAILURE: {args.task} failed {streak} times in a row\nLast error: {e}")
```
Fires after `send_telegram(f"❌ ...")` / `send_telegram(f"⏱ ...")`, never replaces them (D-09).

---

### `scripts/health_check.py` (NEW, OBS-02)

**Analog:** `scripts/send_slips_telegram.py` — standalone read-only script with duplicated `env_value`, local `send_telegram`, `main() -> int`, `raise SystemExit(main())`.

**Shebang + module docstring pattern** (send_slips_telegram.py line 1–2):
```python
#!/usr/bin/env python3
"""Send today's SportsEdge slip recommendations to Telegram after audit passes."""
```

**`from __future__ import annotations` + stdlib-only imports** (send_slips_telegram.py lines 4–14):
```python
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
```
`health_check.py` uses `requests` for Telegram but can use `urllib.request` (no third-party dep) — follow `send_slips_telegram.py`'s `urllib.request` pattern to keep the script self-contained without importing from the runner.

**Path constants pattern** (send_slips_telegram.py lines 17–23):
```python
HOME = Path.home()
ROOT = HOME / "sports_picks"
HERMES_ENV = HOME / ".hermes" / ".env"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
```
Add for `health_check.py`:
```python
LOG_DIR = ROOT / "data" / "pnl" / "logs"
RUN_LOG_JSONL = LOG_DIR / "run_log.jsonl"
```

**Duplicated `env_value` pattern** (send_slips_telegram.py lines 37–50):
```python
def env_value(key: str) -> str | None:
    value = os.environ.get(key)
    if value:
        return value.strip().strip('"').strip("'")
    if not HERMES_ENV.exists():
        return None
    for line in HERMES_ENV.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        k, v = stripped.split("=", 1)
        if k.strip() == key:
            return v.strip().strip('"').strip("'") or None
    return None
```
Copy this verbatim — identical to the runner's `env_value` (runner line 322) but self-contained.

**Local `send_telegram` pattern** (send_slips_telegram.py lines 78–106):
```python
def send_telegram(message: str) -> int:
    token = env_value("TELEGRAM_BOT_TOKEN")
    chat_id = env_value("TELEGRAM_HOME_CHANNEL") or env_value("TELEGRAM_CHAT_ID")
    thread_id = env_value("TELEGRAM_CRON_THREAD_ID") or env_value("TELEGRAM_HOME_CHANNEL_THREAD_ID")
    if not token or not chat_id:
        ...
        return 2
    url = TELEGRAM_API.format(token=token)
    payload = {"chat_id": chat_id, "text": message, "disable_web_page_preview": True}
    if thread_id:
        payload["message_thread_id"] = thread_id
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            ...
    except Exception as exc:
        ...
        return 1
    return 0
```

**`main() -> int` + `raise SystemExit(main())` pattern** (send_slips_telegram.py lines 109–128, build_hit_rate_db.py lines 586–616):
```python
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="today")
    args = parser.parse_args()
    ...
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
```

**JSONL tail-read pattern** — no direct analog exists; nearest is `bankroll_state()` (runner line 377–381) for `try/except json.loads()`:
```python
def bankroll_state() -> dict[str, Any]:
    try:
        return json.loads(BANKROLL.read_text()) if BANKROLL.exists() else {}
    except Exception:
        return {}
```
For multi-line JSONL, iterate `.splitlines()` and call `json.loads()` per line inside a try/except, skipping blank/corrupt lines. Collect as `list[dict]`.

**OBS-02 cadence map** — sibling to `TASK_TIMEOUTS` (runner lines 112–124). In `health_check.py` define as a module-level constant (same 11 task keys):
```python
TASK_CADENCE_SECONDS: dict[str, int] = {
    "nba_daily_picks":        86400,   # once daily
    "mlb_daily_picks":        86400,
    "nba_prop_monitor":       3600,    # example hourly
    "mlb_prop_monitor":       3600,
    "nba_clv_tracker":        86400,
    "mlb_clv_tracker":        86400,
    "nba_injury_monitor":     3600,
    "mlb_injury_monitor":     3600,
    "game_completion_monitor": 3600,
    "check_results":          86400,
    "verify":                 86400,
}
```
Concrete values are Claude's discretion (D-05); adjust to match actual cron schedule.

**stdout print contract** (build_hit_rate_db.py line 612):
```python
print(json.dumps({"status": "ok", ...}, indent=2))
```
`health_check.py` prints a human-readable snapshot via `print()` (no `JSON_RESULT=` prefix — it is not a runner task; it's ad-hoc operator output). Return non-zero exit code when any task is overdue or last-failed.

---

### `scripts/test_obs_*.py` (NEW unit tests)

**Analog:** `scripts/test_slip_payouts.py` (direct import, no runner loading) and `scripts/test_line_timing.py` (importlib runner load).

**Direct-import test pattern** (test_slip_payouts.py lines 1–16):
```python
#!/usr/bin/env python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from slip_payouts import calculate_slip_payout, ...

class TestSlipPayouts(unittest.TestCase):
    ...

if __name__ == "__main__":
    unittest.main()
```
Use this for tests of `health_check.py` functions (import directly since it has no runner coupling).

**importlib runner-loading pattern** (test_line_timing.py lines 1–18):
```python
#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

MOD_PATH = SCRIPT_DIR / "sports_system_runner.py"
spec = importlib.util.spec_from_file_location("sports_system_runner", MOD_PATH)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)
runner.load_suppressed_edge_types = lambda: {}
```
Use this for OBS-01/OBS-03 tests that need to exercise the `main()` `finally`/`except` logic with a patched runner.

---

## Shared Patterns

### `env_value` — config/secrets reader
**Source:** `scripts/sports_system_runner.py` lines 322–336  
**Apply to:** OBS-03 threshold constant in runner; duplicated verbatim in `health_check.py`
```python
def env_value(key: str) -> str | None:
    value = os.environ.get(key)
    if value:
        return value.strip().strip('"').strip("'")
    if not HERMES_ENV.exists():
        return None
    for line in HERMES_ENV.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        k, v = stripped.split("=", 1)
        if k.strip() == key:
            return v.strip().strip('"').strip("'") or None
    return None
```

### Telegram alert — resilient send
**Source:** `scripts/sports_system_runner.py` lines 339–374  
**Apply to:** OBS-03 `🔁` alert in runner (reuses existing `send_telegram()`); `health_check.py` duplicates a simpler local version using `urllib.request` (like `send_slips_telegram.py`) to avoid importing the runner.

### Defensive try/except around side-effects
**Source:** `scripts/sports_system_runner.py` lines 5746–5756 (Obsidian sync wrapped in `try/except Exception: pass`)  
**Apply to:** OBS-01 JSONL-write in `finally` and OBS-03 streak-read — both must never raise.

### `safe_print` for cron-pipe safety
**Source:** `scripts/sports_system_runner.py` lines 301–309  
**Apply to:** Any `print()` in `main()` already uses `safe_print`. New OBS-01/OBS-03 code in the runner must use `safe_print`, not bare `print`. `health_check.py` (standalone) uses `print()` directly — it runs interactively and does not share the cron pipe.

### `now_iso()` — UTC ISO timestamp
**Source:** `scripts/sports_system_runner.py` lines 278–279  
**Apply to:** OBS-01 `timestamp` field in the JSONL record; `health_check.py` defines its own `now_iso()` (see `workbook_io.py` line 34 for the copy pattern).

---

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| JSONL tail-read + streak-count logic | utility function | file-I/O | No existing file in the codebase reads an append-only log and counts trailing same-status entries; nearest is `bankroll_state()` JSON single-object read |
| `TASK_CADENCE_SECONDS` dict | config constant | — | Cadence concept is new; `TASK_TIMEOUTS` provides the key list template but the values (staleness windows) have no precedent |

---

## Metadata

**Analog search scope:** `scripts/sports_system_runner.py` (primary), `scripts/send_slips_telegram.py`, `scripts/build_hit_rate_db.py`, `scripts/generate_projections.py`, `scripts/workbook_io.py`, `scripts/test_slip_payouts.py`, `scripts/test_line_timing.py`, `scripts/test_dynamic_gate8.py`
**Files scanned:** 9
**Pattern extraction date:** 2026-06-21
</content>
