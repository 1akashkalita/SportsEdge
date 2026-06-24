# Phase 4: Dual Metrics and Feedback — Pattern Map

**Mapped:** 2026-06-23
**Files analyzed:** 5 (3 new, 2 modified)
**Analogs found:** 5 / 5

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `scripts/calibration.py` | utility/service | transform (read workbook JSON → compute → write JSON) | `scripts/slip_payouts.py` | role-match (stateless utility, plain-function module) |
| `scripts/metrics_report.py` | service | batch (read workbooks → aggregate → dispatch alerts) | `scripts/sports_system_runner.py` `refresh_prop_accuracy:5293` + `sync_slip_bankroll:5126` | role-match (in-runner aggregation functions) |
| `scripts/test_weekly_metrics.py` | test | request-response | `scripts/test_slip_bankroll.py` + `scripts/test_generate_projections.py` | exact (importlib bootstrap, `unittest.TestCase`, openpyxl in-memory fixtures) |
| `scripts/generate_projections.py` | service | transform | self (injection into existing `build_projection:380`) | exact (modify two lines around `estimate_sigma:393`) |
| `scripts/sports_system_runner.py` | orchestrator | request-response | self (add to `TASK_TIMEOUTS:120`, `task_workbook_paths:7192`, `run_task:7261`) | exact (mirror `grade_slips` / `rebuild_bankroll` wiring pattern) |

---

## Pattern Assignments

### `scripts/calibration.py` (utility, transform)

**Analog:** `scripts/slip_payouts.py`

**Why this analog:** `slip_payouts.py` is the canonical standalone helper module: no framework, no runner import, pure functions, `from __future__ import annotations`, type-annotated signatures, module-level constants, stdlib only, each module defines its own `now_utc_iso()`. `calibration.py` follows the same shape — pure functions, one JSON config artifact, no runner coupling.

**Shebang + module docstring** (`slip_payouts.py` lines 1–7):
```python
#!/usr/bin/env python3
"""Slip-level DFS payout accounting for SportsEdge.

Historical bankroll/Pick History values are never rewritten by this module.  It
only computes slip-level return objects and workbook rows for audit/reporting.
"""
from __future__ import annotations
```
Copy this shape exactly. The docstring must state the module's non-interference guarantee (calibration.py must say: "Never touches graded verdicts or gate logic").

**Imports pattern** (`slip_payouts.py` lines 8–17):
```python
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
PAYOUT_CONFIG_PATH = ROOT / "data" / "research" / "platform_payouts.json"
```
For `calibration.py`, use:
```python
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CALIBRATION_PATH = DATA / "research" / "calibration.json"
INCEPTION_DATE = "2026-06-08"
N_GATE = 30
MAX_STEP = 0.05
CLAMP_LO = 0.85
CLAMP_HI = 1.20
```
No third-party imports. No runner import (structural requirement for METRICS-03 / D-13).

**Fail-safe config read pattern** (`slip_payouts.py` `load_payout_config:27`):
```python
def load_payout_config(path: Path | str = PAYOUT_CONFIG_PATH) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text())
```
For `calibration.py` `load_calibration_factor`:
```python
def load_calibration_factor(sport: str, path: Path = CALIBRATION_PATH) -> float:
    """Read per-sport sigma scaler; default 1.0 if absent or malformed (never crashes)."""
    try:
        if Path(path).exists():
            cfg = json.loads(Path(path).read_text(encoding="utf-8"))
            return float(cfg.get("factors", {}).get(sport.upper(), 1.0))
    except Exception:
        pass
    return 1.0
```
The `try/except Exception: pass; return default` pattern is the exact fail-safe shape used throughout this codebase for config reads.

**Atomic JSON write pattern** (mirrors `workbook_io.safe_save_workbook:147` atomic `os.replace`):
```python
# workbook_io.py lines 151, 165:
tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.xlsx")
...
os.replace(tmp, path)
```
For `calibration.py` `write_calibration_json`:
```python
def write_calibration_json(
    factors: dict[str, float],
    audit_entry: dict[str, Any],
    path: Path = CALIBRATION_PATH,
    max_audit: int = 52,
) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    try:
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass
    audit: list[dict[str, Any]] = list(existing.get("audit", []))
    audit.append(audit_entry)
    audit = audit[-max_audit:]  # trim to last 52 entries (~1 year)
    doc = {
        "version": 1,
        "updated_at": _now_iso(),
        "inception_date": INCEPTION_DATE,
        "factors": factors,
        "audit": audit,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # atomic rename — same as save_workbook_atomic pattern
```

**Local `_now_iso()` helper** (each helper module defines its own, never imports from runner):
```python
# slip_payouts.py line 183:
def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
```
Use the same pattern in `calibration.py`:
```python
def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
```

**Type annotations** (`slip_payouts.py` lines 56–77):
```python
def calculate_slip_payout(
    *,
    platform: str,
    slip_type: str,
    total_legs: int,
    ...
) -> dict[str, Any]:
```
All `calibration.py` functions must be annotated with PEP 604 union types and lowercase container types (`dict[str, Any]`, `list[float]`, `tuple[float, dict[str, Any]]`).

---

### `scripts/metrics_report.py` (service, batch aggregation)

**Analog:** `scripts/sports_system_runner.py` — `refresh_prop_accuracy:5293` and `sync_slip_bankroll:5126`

**Why this analog:** `refresh_prop_accuracy` is the exact pattern for ISO-week × sport aggregation from workbook rows. `sync_slip_bankroll` is the exact pattern for reading Slip History columns by header-name lookup. Both iterate workbook rows with `iter_rows(min_row=2, values_only=True)`.

**Shebang + imports** (mirror `generate_projections.py` lines 1–24 but remove `requests`, `re`, `statistics`, `argparse`):
```python
#!/usr/bin/env python3
"""Weekly metrics report for SportsEdge: slip ROI + prop hit-rate by ISO-week × sport.

Read-only from master_pnl.xlsx and per-sport workbooks. Outputs: Telegram digest +
Obsidian note. Never writes to workbooks, Pick History, Results, or gate logic.
"""
from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date as _date_cls, datetime, timezone
from pathlib import Path
from typing import Any

from workbook_io import safe_load_workbook
from slip_payouts import SLIP_HISTORY_HEADERS
```
No runner import — avoids circular dependency. `workbook_io` and `slip_payouts` are always importable from `scripts/`.

**Path constants** (mirror `generate_projections.py` lines 26–32 shape):
```python
ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
NBA_DIR = DATA / "nba"
MLB_DIR = DATA / "mlb"
PNL_DIR = DATA / "pnl"
```

**ISO-week aggregation loop** (`refresh_prop_accuracy:5320–5353` — copy this exact iteration shape):
```python
# sports_system_runner.py lines 5321-5343:
from datetime import date as _date_cls
agg: dict[tuple[str, str], dict[str, int]] = {}
for row_vals in ph.iter_rows(min_row=2, values_only=True):
    date_val = str(row_vals[h["Date"]] or "")[:10]
    result_val = str(row_vals[h["Result"]] or "").upper().strip()
    sport_val = str(row_vals[h.get("Sport", -1)] ...) or "UNKNOWN"

    if not date_val or result_val not in {"WIN", "LOSS", "PUSH"}:
        continue

    try:
        d = _date_cls.fromisoformat(date_val)
        iso_week = f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"
    except Exception:
        continue

    key = (iso_week, sport_val)
    rec = agg.setdefault(key, {"wins": 0, "losses": 0, "pushes": 0})
    ...
```
The slip ROI aggregation in `metrics_report.py` follows the same loop shape but reads `Stake Units` / `Net PnL` / `Slip Result` / `Needs Payout Reconciliation` using `SLIP_HISTORY_HEADERS` index lookups.

**Header-name column lookup** (`sync_slip_bankroll:5159–5163` — never hardcode column offsets):
```python
# sports_system_runner.py lines 5159-5163:
from slip_payouts import SLIP_HISTORY_HEADERS as _SHH
date_col = _SHH.index("Date") + 1
net_pnl_col = _SHH.index("Net PnL") + 1
recon_col = _SHH.index("Needs Payout Reconciliation") + 1
stake_units_col = _SHH.index("Stake Units") + 1
```
Use the same index-from-header-list approach for any column in Slip History or Prop Accuracy. For Pick History, look up dynamically:
```python
# sports_system_runner.py lines 5313-5314:
ph_headers = [ph.cell(1, c).value for c in range(1, ph.max_column + 1)]
h = {col: idx for idx, col in enumerate(ph_headers) if col}
```

**Per-sport workbook glob** (mirrors `grade_slips.py:618` routing — read `data/nba/nba_*.xlsx` and `data/mlb/mlb_*.xlsx`):
```python
for wb_path in sorted(NBA_DIR.glob("nba_*.xlsx")):
    wb = safe_load_workbook(wb_path, read_only=True, data_only=True)
    if "Slip History" not in wb.sheetnames:
        continue
    sh = wb["Slip History"]
    for row_vals in sh.iter_rows(min_row=2, values_only=True):
        ...
```
Use `safe_load_workbook` (retry-on-stale) not bare `load_workbook`. Pass `read_only=True, data_only=True` for report reads to avoid write-locking.

**SKIP-not-crash defensive pattern** (matches task contracts in CLAUDE.md):
```python
# Pattern from sports_system_runner.py sync_slip_bankroll:5149 / refresh_prop_accuracy:5316-5317:
if "Pick History" not in wb.sheetnames:
    return  # SKIP — workbook has no data yet

if not date_val or result_val not in {"WIN", "LOSS", "PUSH"}:
    continue  # skip malformed rows silently
```
Every exception path in metrics functions must return a SKIP result or empty aggregate, never raise uncaught exceptions.

**Telegram call pattern** (`send_telegram:428` — not imported by the module; called from the runner task function):
```python
# sports_system_runner.py lines 428-463:
def send_telegram(message: str, retries: int = 2, backoff: int = 5) -> bool:
    token = env_value("TELEGRAM_BOT_TOKEN")
    ...
    if not token or not chat_id:
        log("Telegram alert skipped: ...")
        return False
    ...
```
`metrics_report.py` produces the formatted message string; `weekly_metrics_task()` in the runner calls `send_telegram(msg)` — the report module never calls Telegram directly (no `requests` import needed).

**Obsidian call pattern** (`obsidian_create_weekly_recap:1034–1098`):
```python
# sports_system_runner.py lines 1034-1098:
def obsidian_create_weekly_recap(date: str | None = None, summary: dict[str, Any] | None = None) -> Path:
    date = date or today_str()
    ...
    if path.exists():
        return path   # PITFALL: second run won't overwrite — bypass with obsidian_sync directly
    ...
    obsidian_sync({"trigger": "check_results", "sport": "NBA", "date": date,
                   "data": {"weekly_recap_date": date, "weekly_recap_markdown": markdown, ...}})
    return path
```
The plan must bypass the `if path.exists(): return path` guard for idempotent re-runs (RESEARCH.md Pitfall 5). Call `obsidian_sync` directly with the filled markdown, or pass the markdown into a modified call that overwrites.

---

### `scripts/test_weekly_metrics.py` (test, request-response)

**Analog 1:** `scripts/test_slip_bankroll.py` — importlib runner bootstrap + openpyxl in-memory workbook fixtures
**Analog 2:** `scripts/test_generate_projections.py` — direct module import, synthetic hit records, pure unit tests

**Shebang + module docstring** (`test_slip_bankroll.py` lines 1–6):
```python
#!/usr/bin/env python3
"""Tests for ..."""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
```

**`sys.path.insert` guard** — every test file in this codebase does this:
```python
# test_slip_bankroll.py line 16:
sys.path.insert(0, str(Path(__file__).resolve().parent))
```

**importlib runner bootstrap** (`test_slip_bankroll.py` lines 19–23 / `test_dynamic_gate8.py` lines 8–12):
```python
# test_slip_bankroll.py lines 19-23:
MOD_PATH = Path(__file__).with_name("sports_system_runner.py")
spec = importlib.util.spec_from_file_location("sports_system_runner", MOD_PATH)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)
```
Use this exact pattern to access `runner.evaluate_no_bet_gates`, `runner.RESULT_HEADERS`, `runner.sync_slip_bankroll` without a bare `import sports_system_runner` that triggers side effects.

**In-memory workbook fixture** (`test_slip_bankroll.py` lines 33–55):
```python
def _make_master_wb_with_slip_history(slip_rows: list[list]) -> Workbook:
    wb = Workbook()
    wb.active.title = "Daily Log"
    dl_ws = wb["Daily Log"]
    dl_ws.append(["Date", "Sport", "Wins", ...])
    ph = wb.create_sheet("Pick History")
    ph.append(runner.RESULT_HEADERS)
    sh = wb.create_sheet("Slip History")
    sh.append(SLIP_HISTORY_HEADERS)
    for row in slip_rows:
        sh.append(row)
    return wb
```
For `test_weekly_metrics.py`, build a `_make_pick_history_wb` with rows that have `Date`, `Sport`, `Result` (WIN/LOSS), `Model Over Probability`, and `Pick Type` = "PROP". Column positions must come from `runner.RESULT_HEADERS` index lookups — never hardcoded offsets.

**Monkeypatch pattern** (`test_slip_bankroll.py` lines 109–123):
```python
orig_bankroll = runner.BANKROLL
try:
    runner.BANKROLL = bankroll_path
    result = runner.sync_slip_bankroll(date, _wb_override=wb, ...)
    self.assertAlmostEqual(result["day_pnl"], 5.0, places=3)
finally:
    runner.BANKROLL = orig_bankroll
```
For testing `calibration.py` functions, pass `path=Path(tmp_path / "calibration.json")` directly (the calibration functions take `path` as a parameter — no monkeypatching needed).

**Direct module import** (`test_generate_projections.py` lines 15–16):
```python
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_projections as gp
```
For calibration-only tests (D-10 bounds, gate checks), import `calibration` directly — faster and fully offline.

**`__main__` block** — every test file in this codebase ends with:
```python
# test_slip_payouts.py lines 102-103:
if __name__ == "__main__":
    unittest.main()
```

**TestCase class structure** (`test_grade_slips_aggregate.py` lines 128–151):
```python
class TestGradeSlipPower(unittest.TestCase):
    """(a) + (b): power slip payout paths."""

    def test_power_both_win(self) -> None:
        """2-leg power all-WIN → GRADED, 3.0x, net +2.0, reconcile=False."""
        ...
        self.assertEqual(p["slip_result"], "GRADED")
        self.assertAlmostEqual(p["net_pnl"], 2.0, places=6)
```
Use one `TestCase` class per requirement (e.g., `TestCalibrationFormula`, `TestCalibrationBounds`, `TestSlipRoiAggregation`, `TestIntegrityNoVerdictChange`, `TestIntegrityGateOutput`, `TestWowArrow`).

---

### `scripts/generate_projections.py` (modified — sigma injection)

**Analog:** self, lines 277–294 and 380–394

**Current `estimate_sigma` + caller** (lines 277–286, 393–394):
```python
# generate_projections.py lines 277-286:
def estimate_sigma(stat: dict[str, Any], stat_name: str, sigma_floor: float = 0.75) -> tuple[float, str]:
    vals = recent_actuals(stat)
    if len(vals) >= 2:
        sigma = statistics.pstdev(vals)
        source = f"sample_games sigma n={len(vals)}"
    else:
        sigma = fallback_sigma_for_stat(stat_name)
        source = f"fallback {normalize_prop_stat(stat_name)} sigma"
    sigma = max(sigma_floor, sigma)
    return sigma, source

# generate_projections.py lines 393-394 (in build_projection):
    sigma, sigma_source = estimate_sigma(stat, stat_name)
    over_prob = round(model_over_probability(projection, pp_line, sigma), 4)
```

**Injection pattern** (two-line change at lines 393–394 — add `load_calibration_factor` helper at module top):
```python
# NEW helper function at module top (after imports, before estimate_sigma):
def load_calibration_factor(sport: str) -> float:
    """Read per-sport sigma scaler from calibration.json; default 1.0 if absent.

    ANTI-PATTERN: Do NOT read at import time — read at call time to avoid caching
    a stale factor across the subprocess lifetime.
    """
    path = DATA / "research" / "calibration.json"
    try:
        if path.exists():
            cfg = json.loads(path.read_text(encoding="utf-8"))
            return float(cfg.get("factors", {}).get(sport.upper(), 1.0))
    except Exception:
        pass
    return 1.0

# MODIFIED in build_projection (lines 393-394):
    sigma, sigma_source = estimate_sigma(stat, stat_name)
    cal_factor = load_calibration_factor(sport)
    if cal_factor != 1.0:
        sigma = sigma * cal_factor
        sigma_source = f"{sigma_source} × cal={cal_factor:.4f}"
    over_prob = round(model_over_probability(projection, pp_line, sigma), 4)
```
`model_over_probability:289` and `evaluate_no_bet_gates` are byte-for-byte unchanged (D-13 / METRICS-03). `DATA` is already defined at line 27 — no new path constant needed.

**Existing imports to extend** (lines 10–24 — add `json` if not already imported):
```python
# generate_projections.py line 11 — json is already imported:
import json
```
`json` is already imported at line 11. No new dependency needed.

---

### `scripts/sports_system_runner.py` (modified — task wiring)

**Analog:** self — `grade_slips` / `rebuild_bankroll` entries at lines 134–137, 7208–7213, 7274–7279

**TASK_TIMEOUTS entry** (lines 120–138 — add one entry):
```python
# sports_system_runner.py lines 120-138:
TASK_TIMEOUTS: dict[str, int] = {
    "nba_daily_picks": 660,
    ...
    "grade_slips": 660,
    "rebuild_bankroll": 660,
    # ADD:
    "weekly_metrics": 660,  # read-only workbook + 1 JSON write + Telegram + Obsidian
}
```

**`task_workbook_paths` entry** (lines 7192–7214 — add before the fallback `return`):
```python
# Mirrors rebuild_bankroll at lines 7210-7213:
# rebuild_bankroll is a one-time manual task that writes only the master P&L ledger;
# hold the cooperative lock so it cannot race grade_slips or check_results.
if task == "rebuild_bankroll":
    return [PNL_DIR / "master_pnl.xlsx"]

# ADD immediately after (before the final return):
# weekly_metrics reads master_pnl (Prop Accuracy + Pick History) and per-sport workbooks;
# holds the master lock to prevent races with grade_slips / check_results.
if task == "weekly_metrics":
    return [PNL_DIR / "master_pnl.xlsx"]
```

**`run_task` mapping entry** (lines 7261–7283 — add before closing brace):
```python
# Mirrors grade_slips lambda at line 7276:
"grade_slips": lambda: _grade_slips_then_sync(today_str()),
# rebuild_bankroll: one-time manual task ...
"rebuild_bankroll": lambda: rebuild_slip_bankroll(),

# ADD:
# weekly_metrics: aggregates slip ROI + prop hit-rate by ISO-week × sport,
# updates calibration.json sigma scalers, delivers Telegram digest + Obsidian note.
"weekly_metrics": lambda: weekly_metrics_task(),
```

**`weekly_metrics_task()` function placement:** Define it near `rebuild_slip_bankroll` / `_grade_slips_then_sync` (around line 7232). Use the same function shape:
- Returns `dict[str, Any]` with status, summary counts, and whether alerts were sent
- Wraps all non-fatal failures with `try/except` and logs — never crashes the task
- Uses `safe_print("JSON_RESULT=" + json.dumps(result, sort_keys=True))` — this is done by `main()`, the task just returns the dict

**`safe_print` + `JSON_RESULT` output contract** (lines 7295, 7326):
```python
# main() at line 7295:
safe_print("JSON_RESULT=" + json.dumps(result, sort_keys=True))
```
The task function returns a `dict`; `main()` handles the `JSON_RESULT=` line. The function itself only `log()`s and returns.

---

## Shared Patterns

### Atomic JSON write (fail-safe config persistence)
**Source:** `scripts/workbook_io.py` lines 147–173 (`safe_save_workbook`, `os.replace` pattern)
**Apply to:** `scripts/calibration.py` `write_calibration_json`
```python
# workbook_io.py lines 151, 165:
tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.xlsx")
...
os.replace(tmp, path)
```
For JSON: use `path.with_suffix(".json.tmp")` and `os.replace(tmp, path)`.

### Fail-safe config read (`try/except Exception: pass; return default`)
**Source:** `scripts/slip_payouts.py` lines 27–31 (`load_payout_config`) and `scripts/sports_system_runner.py` `bankroll_state:467`
**Apply to:** `scripts/calibration.py` `load_calibration_factor`, `scripts/generate_projections.py` `load_calibration_factor`
```python
# sports_system_runner.py lines 467-470:
def bankroll_state() -> dict[str, Any]:
    try:
        return json.loads(BANKROLL.read_text()) if BANKROLL.exists() else {}
    except Exception:
        return {}
```

### Header-name column lookup (never hardcode offsets)
**Source:** `scripts/sports_system_runner.py` lines 5313–5314
**Apply to:** `scripts/calibration.py` (Pick History reads), `scripts/metrics_report.py` (Prop Accuracy + Slip History reads)
```python
ph_headers = [ph.cell(1, c).value for c in range(1, ph.max_column + 1)]
h = {col: idx for idx, col in enumerate(ph_headers) if col}
# then: row_vals[h["Model Over Probability"]]
```
For sheets with fixed headers (Slip History, Prop Accuracy), use `SLIP_HISTORY_HEADERS.index("Net PnL")` directly.

### SKIP-not-crash defensive task contract
**Source:** `scripts/sports_system_runner.py` `refresh_prop_accuracy:5309–5317`
**Apply to:** All functions in `calibration.py`, `metrics_report.py`, `weekly_metrics_task()` in runner
```python
if "Pick History" not in wb.sheetnames:
    return  # missing data → SKIP, not exception

if not date_val or result_val not in {"WIN", "LOSS", "PUSH"}:
    continue  # malformed row → skip silently
```

### Safe workbook load (retry-on-stale)
**Source:** `scripts/workbook_io.py` `safe_load_workbook:120`
**Apply to:** All workbook opens in `calibration.py`, `metrics_report.py`, `weekly_metrics_task()`
```python
# workbook_io.py lines 120-144:
def safe_load_workbook(path: Path, retries: int = 5, delay: float = 1.0, **kwargs: Any):
    ...
    wb = load_workbook(path, **kwargs)
    return wb
```
Always pass `read_only=True, data_only=True` for report-only reads.

### Telegram non-crashing dispatch
**Source:** `scripts/sports_system_runner.py` `send_telegram:428`
**Apply to:** `weekly_metrics_task()` in runner (call `send_telegram(msg)` wrapped in try/except)
```python
# Pattern from _grade_slips_then_sync lines 7248-7256:
try:
    slip_bankroll_result = sync_slip_bankroll(date)
except Exception as exc:  # noqa: BLE001
    print(f"[...] failed: {exc}", flush=True)
    slip_bankroll_result = {"error": str(exc)}
```

### Module-private `_now_iso()` helper (no cross-module import)
**Source:** `scripts/slip_payouts.py` line 183 (`now_utc_iso`), `scripts/workbook_io.py` line 34 (`now_iso`)
**Apply to:** `scripts/calibration.py` (define locally as `_now_iso`)
Each helper module in this codebase defines its own timestamp helper — never imports from runner.

### ISO-week key format
**Source:** `scripts/sports_system_runner.py` `refresh_prop_accuracy:5332`
**Apply to:** `scripts/calibration.py`, `scripts/metrics_report.py`
```python
# sports_system_runner.py line 5332:
iso_week = f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"
```
Use this exact format — ISO-8601, zero-padded week number.

---

## No Analog Found

All files have close matches. No entries.

---

## Key Anti-Patterns (from RESEARCH.md)

These must NOT appear in any new file:

| Anti-pattern | Correct pattern |
|---|---|
| `import sports_system_runner` from `calibration.py` or `metrics_report.py` | Each module is standalone; runner imports helpers, not vice versa |
| Hardcoded column offsets (`row_vals[12]`) | Always `SLIP_HISTORY_HEADERS.index("Net PnL")` or dynamic header map |
| `path.write_text(json.dumps(...))` directly | Write to `.json.tmp`, then `os.replace(tmp, path)` |
| `load_calibration_factor(sport)` at import time | Call inside `build_projection()` at projection time |
| `evaluate_no_bet_gates` touched or imported by calibration | Structurally forbidden — METRICS-03 |
| Parsing `Legs` free-text for sport attribution | Read per-sport workbooks (`data/nba/nba_*.xlsx`) |
| Including PUSH or VOID rows in calibration wins/losses | Only WIN and LOSS with non-null MOP count |

---

## Metadata

**Analog search scope:** `scripts/*.py`, `scripts/test_*.py`
**Files read:** `slip_payouts.py`, `line_timing.py` (header only), `workbook_io.py`, `generate_projections.py` (lines 1–50, 270–414), `sports_system_runner.py` (lines 44–70, 119–155, 290–340, 428–464, 1034–1099, 4849–4870, 5126–5190, 5293–5355, 7192–7283), `test_slip_bankroll.py`, `test_slip_payouts.py`, `test_generate_projections.py`, `test_grade_slips_aggregate.py`, `test_dynamic_gate8.py`, `grade_slips.py` (lines 598–627)
**Pattern extraction date:** 2026-06-23
