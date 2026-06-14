# Coding Conventions

**Analysis Date:** 2026-06-14

## Naming Patterns

**Files:**
- `snake_case.py` for all scripts: `sports_system_runner.py`, `fetch_dfs_props.py`, `slip_payouts.py`
- Test files prefix with `test_`: `test_slip_payouts.py`, `test_dynamic_gate8.py`
- Stage regression tests use numbered prefix: `test_stage1_platform_outputs.py` through `test_stage5_telegram_platform.py`
- Archive/dead code lives in `scripts/archive/` — never import from there

**Functions:**
- `snake_case` throughout, no exceptions
- Helper functions prefixed with `_` for module-private use: `_clean_slip_type`, `_parse_rate_limit_int`, `_nested_get`, `_warn_if_rate_limit_low`
- Utility functions named descriptively as verb-noun: `to_float`, `normalize_player_name`, `normalize_stat_type`, `safe_load_workbook`, `save_workbook_atomic`
- Task functions named as `daily_picks(sport)`, `prop_monitor(sport)`, `injury_monitor(sport)`, `clv_tracker(sport)` — sport is always a lowercase string `"nba"` or `"mlb"`

**Variables:**
- `snake_case` throughout
- Constants in `UPPER_SNAKE_CASE`: `DAILY_EXPOSURE_CAP`, `PICKS_HEADERS`, `SKIP_HISTORY_HEADERS`, `GENERATED_MARKER`
- Global path constants at module top: `ROOT`, `DATA`, `NBA_DIR`, `MLB_DIR`, `PNL_DIR`, `LOG_DIR`, `SCRIPTS`

**Types:**
- `dict[str, Any]` for all pick/row dicts
- `list[str]` for headers
- `tuple[bool, dict[str, Any] | None, list[str]]` for gate results
- `str | None` for optional string parameters
- `Path` from `pathlib` for all filesystem paths (never raw strings)

## Code Style

**Formatting:**
- No automated formatter enforced (no `.prettierrc`, `pyproject.toml`, `ruff.toml`, or `.flake8`)
- PEP 8 style followed manually: 4-space indentation, lines mostly <100 chars
- No trailing commas enforced, but used consistently in multiline lists/dicts

**Linting:**
- No configured linter. Convention is enforced through code review and test suite.

## Type Annotations

**Mandatory header:**
Every source file begins with:
```python
#!/usr/bin/env python3
"""Module docstring."""
from __future__ import annotations
```

All 38 Python files use `from __future__ import annotations` — this is a hard convention.

**Annotation style:**
- All function signatures annotated: parameters and return types
- Use `Any` from `typing` for untrusted/heterogeneous dict values, not `object`
- Union types use PEP 604 syntax (`str | None`, `float | None`) enabled by `__future__` import
- Container types use lowercase built-ins: `dict[str, Any]`, `list[str]`, `tuple[bool, ...]`

```python
def to_float(value: Any) -> float | None:
    ...

def evaluate_no_bet_gates(pick: dict[str, Any], suppressed_edges: dict[str, str]) -> tuple[bool, dict[str, Any] | None, list[str]]:
    ...
```

## Import Organization

**Order (followed in all modules):**
1. `from __future__ import annotations`
2. stdlib imports (alphabetical): `argparse`, `json`, `os`, `pathlib`, `sys`, `time`, `traceback`, etc.
3. Third-party imports: `import fcntl`, `import requests`, `from openpyxl import ...`
4. Local sibling imports: `from slip_payouts import ...`, `from line_timing import ...`

**Path setup in tests:**
Tests insert the scripts directory into `sys.path` before local imports:
```python
sys.path.insert(0, str(Path(__file__).resolve().parent))
```

Or load `sports_system_runner` via `importlib`:
```python
spec = importlib.util.spec_from_file_location("sports_system_runner", MOD_PATH)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
```

**No path aliases** — only `sys.path` manipulation and `importlib`.

## Error Handling

**Core defensive principle:** Tasks never raise uncaught exceptions. Missing data becomes an explicit SKIP state, not a crash. This is the contract for Hermes cron compatibility.

**`to_float` pattern** — used everywhere unsafe numeric parsing occurs:
```python
def to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None
```
Never call `float()` directly on data from workbooks or APIs — always use `to_float()`.

**Gate skip record pattern** — gate failures return a structured dict, never raise:
```python
def skip_record(pick: dict[str, Any], gate: str, reason: str) -> dict[str, Any]:
    ...
    return {
        "gate_failed": gate,
        "reason": reason,
        ...
    }

# At each gate:
return False, skip_record(pick, "GATE 1 — MINIMUM EDGE", f"edge {edge} < 0.5"), passed
```

**External calls degrade gracefully** — `send_telegram`, `obsidian_sync`, external HTTP calls all catch `Exception` and log without raising:
```python
try:
    obsidian_sync({"trigger": "sports_run_log", ...})
except Exception:
    pass
```

**Retry pattern for HTTP** — retries with exponential backoff, never crash on failure:
```python
for attempt in range(retries):
    try:
        r = requests.post(..., timeout=30)
        if r.status_code == 200:
            return True
        log(f"failed attempt {attempt+1}/{retries}: status={r.status_code}")
    except requests.exceptions.RequestException as e:
        log(f"failed attempt {attempt+1}/{retries}: {e}")
    if attempt < retries - 1:
        time.sleep(delay)
```

**Workbook I/O** — always use `safe_load_workbook` / `save_workbook_atomic` from `workbook_io.py`, never `openpyxl.load_workbook()` directly:
```python
from workbook_io import safe_load_workbook, safe_save_workbook
wb = safe_load_workbook(path, read_only=True, data_only=True)
```

## Configuration & Secrets

**Never hardcode secrets.** All config accessed via two helpers only:

```python
def env_value(key: str) -> str | None:
    """Checks os.environ first, then falls back to ~/.hermes/.env."""

def env_bool(name: str, default: bool) -> bool:
    """Reads env var, interprets '1'/'true'/'yes'/'on'/'enabled' as True."""
```

Feature flags are module-level constants set at import time:
```python
USE_PRIZEPICKS_FOR_PLAYER_PROPS = env_bool("USE_PRIZEPICKS_FOR_PLAYER_PROPS", True)
ENABLE_ODDS_API_IO_PLAYER_PROPS = env_bool("ENABLE_ODDS_API_IO_PLAYER_PROPS", False)
```

Tunable thresholds read from env with typed defaults:
```python
DAILY_EXPOSURE_CAP = 10.0
ODDS_API_IO_RATE_LIMIT_CRITICAL_REMAINING = int(os.environ.get("ODDS_API_IO_RATE_LIMIT_CRITICAL_REMAINING", "10"))
```

## Logging

**Framework:** Custom `log()` function (no stdlib `logging` in the runner; `odds_api_io_client.py` uses `logging` module for internal diagnostics).

**Pattern:**
```python
def log(msg: str) -> None:
    ensure_dirs()
    line = f"[{now_iso()}] {msg}"
    with RUN_LOG.open("a") as f:
        f.write(line + "\n")
    safe_print(line)
```

Log file: `data/pnl/logs/run_log.txt`. Timestamp format: ISO 8601 UTC (`now_iso()` → `datetime.now(timezone.utc).isoformat(timespec="seconds")`).

**`safe_print`** wraps every `print()` call to silently swallow `BrokenPipeError` (cron pipe safety):
```python
def safe_print(line: str, *, file: Any = None) -> None:
    try:
        print(line, file=file or sys.stdout)
    except BrokenPipeError:
        ...
```

## Stdout Contract

Every task run must emit exactly one line to stdout in the form:
```
JSON_RESULT={"status": "ok", "task": "...", ...}
```
This is emitted by `main()` in `sports_system_runner.py` via:
```python
print("JSON_RESULT=" + json.dumps(result, sort_keys=True))
```
The Hermes cron orchestrator reads this line. Tasks return `dict[str, Any]` — never print intermediary JSON lines that could be confused with this contract. Use `log()` for operational output.

Subprocess scripts (`fetch_dfs_props.py`, `generate_projections.py`) print plain JSON to stdout; the runner captures it via `subprocess.run(..., capture_output=True)` and reads `data/` files rather than parsing stdout.

## Data Access Patterns

**Dates:** Always `YYYY-MM-DD` strings via `today_str()`:
```python
def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")
```
Never construct date strings manually.

**Workbook row access:** Rows read from openpyxl are tuples indexed by position. Column positions must be matched against the corresponding `*_HEADERS` list. Never hardcode a column index without referencing the header constant.

**Dict keys for pick records:** Use lowercase snake_case keys when building pick dicts in Python (e.g. `"model_over_probability"`, `"edge_type_tags"`). Workbook sheet headers are Title Case with spaces (e.g. `"Model Over Probability"`, `"Edge Type Tags"`).

**Platform fallback chain:** When a pick has no platform set, use `"DFS"` (not `"PrizePicks"`) as the neutral fallback label:
```python
platform = p.get("platform") or p.get("primary_platform") or ("DFS" if p.get("kind") == "prop" else "")
```

## Module Design

**Exports:** No `__all__` used. Public API is implicit — underscore-prefixed functions are private.

**Barrel files:** None. Each module is imported directly by name.

**Module-level side effects:** Avoided in helper modules (`line_timing.py`, `slip_payouts.py`, `special_line_value.py`). `fetch_dfs_props.py` creates directories at import time — be aware when testing.

**`if __name__ == "__main__"` guard:** Present in all source scripts and most test files. Every test file supports both `python3 test_x.py` direct execution and `python3 -m pytest` discovery.

## Comments

**Module docstrings:** Every file has a module-level docstring explaining purpose and any important boundaries/constraints.

**Inline comments:** Used for non-obvious logic, especially data-source boundaries and gate semantics:
```python
# New provider key is read from ODDS_API_IO_KEY only; no fallback/hardcoded secret.
# Research-only game-market context attached to DFS prop rows.
# These fields are stored for future backtests only; they must not adjust
# projections, confidence tiers, approved picks, or gate outcomes until...
```

**Boundary comments:** DFS data-source boundary rules are documented with inline comments at the flag declarations and at the top of `fetch_dfs_props.py`.

---

*Convention analysis: 2026-06-14*
