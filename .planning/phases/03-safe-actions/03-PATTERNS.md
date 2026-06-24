# Phase 3: Safe Actions - Pattern Map

**Mapped:** 2026-06-24
**Files analyzed:** 5 (2 new, 3 modified)
**Analogs found:** 5 / 5

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `scripts/dashboard_writes.py` | utility / write-helper | CRUD (workbook upsert) | `scripts/dashboard_data.py` (module skeleton) + `scripts/workbook_io.py` (atomic save) + `scripts/grade_slips.py:454–464` (upsert scan) | role-match + exact for write path |
| `scripts/test_dashboard_actions.py` | test | request-response + CRUD | `scripts/test_dynamic_gate8.py` (importlib runner load + gate assertion) + `scripts/test_dashboard_views.py` (Flask test_client POST pattern) | exact |
| `scripts/dashboard.py` | controller / Flask app | request-response | existing routes + `_freshness_context()` in `scripts/dashboard.py:51–61` | exact (add to existing file) |
| `data/pnl/master_pnl.xlsx` Slip History columns | model / schema | CRUD | `scripts/sports_system_runner.py:6898–6904` (`ensure_ws_columns`) + `scripts/slip_payouts.py:187–197` (`ensure_slip_history_sheet`) | exact |
| `data/pnl/logs/sports_system_runner.lock` probe | middleware / guard | request-response | `scripts/sports_system_runner.py:7937–7940` (LOCK_EX acquisition) | exact (mirror, non-blocking) |

---

## Pattern Assignments

### `scripts/dashboard_writes.py` (utility, CRUD)

**Analogs:**
- Module skeleton → `scripts/dashboard_data.py:1–48`
- Atomic write path → `scripts/workbook_io.py:79–117` (`workbook_file_lock`) + `147–173` (`safe_save_workbook`)
- Additive column migration → `scripts/sports_system_runner.py:6898–6904` (`ensure_ws_columns`)
- Upsert key scan → `scripts/grade_slips.py:454–464`
- UTC timestamp → `scripts/slip_payouts.py:183–184` (`now_utc_iso`)

**Imports pattern** — copy from `dashboard_data.py:1–29` and `workbook_io.py:1–27`:
```python
#!/usr/bin/env python3
"""dashboard_writes.py — Additive write helpers for the Hermes Sports dashboard.

Write path for ACTION-02 (mark-placed) and ACTION-03 (add-note).
All writes go through workbook_io.safe_save_workbook (atomic temp-file swap).
Never changes gate logic, grades, EV, or exposure caps (ACTION-04 hard line).
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workbook_io import WorkbookAccessError, safe_load_workbook, safe_save_workbook, workbook_file_lock
```

**Path constants pattern** — copy from `dashboard_data.py:35–42` (always `Path.home()` anchored, never hardcoded username):
```python
# scripts/dashboard_data.py:35-42
HOME: Path = Path.home()
ROOT: Path = HOME / "sports_picks"
DATA: Path = ROOT / "data"
PNL_DIR: Path = DATA / "pnl"
```
`dashboard_writes.py` must define `PNL_DIR` the same way — `Path.home() / "sports_picks" / "data" / "pnl"` — as a module constant.

**Additive column migration pattern** — inline from `sports_system_runner.py:6898–6904` (do NOT import from runner — see Pitfall 6 in RESEARCH.md; inline the 4-line function):
```python
# scripts/sports_system_runner.py:6898-6904 — INLINE this, do not import from runner
def ensure_ws_columns(ws: Any, columns: list[str]) -> dict[str, int]:
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    for col in columns:
        if col not in headers:
            ws.cell(1, ws.max_column + 1).value = col
            headers.append(col)
    return {str(ws.cell(1, c).value): c for c in range(1, ws.max_column + 1)
            if ws.cell(1, c).value not in (None, "")}
```

**UTC timestamp helper** — copy from `slip_payouts.py:183–184`:
```python
# scripts/slip_payouts.py:183-184
def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
```

**Core write pattern — `mark_placed`** (composite from `workbook_io.py:79–117` lock context + `grade_slips.py:454–464` upsert scan):
```python
# workbook_io.py:79-117 — workbook_file_lock is a @contextmanager
# grade_slips.py:454-464 — (Date, Slip ID) upsert scan with [:10] date normalisation

def mark_placed(date: str, slip_id: str, placed: bool) -> None:
    """Toggle Placed / Placed At on the matching Slip History row in master_pnl.xlsx.

    Uses workbook_file_lock → safe_load_workbook → ensure_ws_columns → cell write
    → safe_save_workbook (ACTION-04: additive columns only, no other row modified).
    """
    master_path = PNL_DIR / "master_pnl.xlsx"
    with workbook_file_lock(master_path):
        wb = safe_load_workbook(master_path)
        ws = wb["Slip History"]
        cols = ensure_ws_columns(ws, ["Placed", "Placed At", "Operator Note"])
        date_norm = str(date)[:10]
        for r in range(2, ws.max_row + 1):
            if (str(ws.cell(r, 1).value or "")[:10] == date_norm
                    and str(ws.cell(r, 2).value or "") == slip_id):
                ws.cell(r, cols["Placed"]).value = placed
                ws.cell(r, cols["Placed At"]).value = now_utc_iso() if placed else None
                break
        safe_save_workbook(wb, master_path)
```

Key details from analogs:
- `workbook_file_lock` is a `@contextmanager` yielding the lock path (`workbook_io.py:79`)
- `safe_load_workbook` signature: `(path, retries=5, delay=1.0, **kwargs)` — call without `read_only=True` for write access (`workbook_io.py:120`)
- `safe_save_workbook` signature: `(wb, path) -> Path | None` — returns backup path (`workbook_io.py:147`)
- Date normalisation `[:10]` is the established pattern from `grade_slips.py:458`: `str(cell_date or "")[:10] == date_norm`
- Column 1 = Date, Column 2 = Slip ID (per `SLIP_HISTORY_HEADERS` in `slip_payouts.py:18–24`)

**Error handling pattern** — callers (`dashboard.py` route handlers) wrap in `try/except Exception as exc` and `flash(f"Save failed: {exc}", "error")`. The write helper itself should let `WorkbookAccessError` propagate; it must NOT swallow errors silently (unlike `append_run_record` which swallows — that pattern is for logging only).

**add_note pattern** — same structure as `mark_placed`; only the cell written differs:
```python
def add_note(date: str, slip_id: str, note: str) -> None:
    master_path = PNL_DIR / "master_pnl.xlsx"
    with workbook_file_lock(master_path):
        wb = safe_load_workbook(master_path)
        ws = wb["Slip History"]
        cols = ensure_ws_columns(ws, ["Placed", "Placed At", "Operator Note"])
        date_norm = str(date)[:10]
        for r in range(2, ws.max_row + 1):
            if (str(ws.cell(r, 1).value or "")[:10] == date_norm
                    and str(ws.cell(r, 2).value or "") == slip_id):
                ws.cell(r, cols["Operator Note"]).value = str(note).strip()
                break
        safe_save_workbook(wb, master_path)
```

**Naming / type / style conventions:**
- `snake_case` for all function names
- Type annotations on all signatures: `date: str`, `slip_id: str`, `placed: bool`, `note: str`, return `-> None`
- `Path` from `pathlib` for all filesystem paths — never raw strings
- `dict[str, Any]` for workbook row dicts; `dict[str, int]` for the col-index map returned by `ensure_ws_columns`
- `from __future__ import annotations` at top (enables PEP 604 `str | None` syntax)
- Module-private helpers prefixed `_` (e.g. `_ensure_ws_columns` if not needed outside)

---

### `scripts/test_dashboard_actions.py` (test, request-response + CRUD)

**Analogs:**
- Runner importlib load idiom → `scripts/test_dynamic_gate8.py:1–13`
- Synthetic pick dict → `scripts/test_dynamic_gate8.py:16–54` (`cand()` helper)
- Flask test_client POST → `scripts/test_dashboard_views.py` + `scripts/test_dashboard.py:95–103`
- Synthetic workbook fixture → `scripts/test_dashboard_views.py:33–80` (`_make_today_wb`)

**File header / sys.path pattern** — copy from `test_dashboard_views.py:1–27`:
```python
#!/usr/bin/env python3
"""test_dashboard_actions.py — ACTION-01..04 tests for Phase 3 safe write actions."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from openpyxl import Workbook

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
```

**Runner importlib load pattern** — copy from `test_dynamic_gate8.py:1–13` (the ONLY supported way to load the runner in tests):
```python
# scripts/test_dynamic_gate8.py:1-13
import importlib.util
from pathlib import Path

MOD_PATH = Path(__file__).with_name("sports_system_runner.py")
spec = importlib.util.spec_from_file_location("sports_system_runner", MOD_PATH)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)
runner.load_suppressed_edge_types = lambda: {}  # stub external I/O
```
Place this in `setUpClass` to load once per test class (same pattern `test_dynamic_gate8.py` uses at module level).

**Canonical pick fixture** — model after `test_dynamic_gate8.py:16–54` (`cand()` helper); all required gate fields must be present. Key fields that gates check:
```python
# test_dynamic_gate8.py:16-54 — minimum viable pick dict for evaluate_no_bet_gates
{
    "kind": "prop",
    "date": "2026-06-24",
    "sport": "MLB",
    "game_id": "g1",
    "projection_id": "proj-1",
    "selection": "Player A Over 0.5 Hits",
    "line": 0.5,
    "odds": "standard",
    "score": 3,
    "confidence": "A",
    "units": 1.0,
    "player": "Player A",
    "team": "T1",
    "model_projection": 0.7,
    "edge": 1.5,
    "model_over_probability": 0.65,
    "ev": 0.2,
    "edge_type_tags": "projection_edge",
    "injury_status": "ACTIVE",
    "sportsbook_verified": True,
    "hit_row": {"sample_size": 20, "hit_rate_l10": 0.7},
    "line_timing": "pregame",
    "line_timing_confidence": "high",
    "line_timing_reason": "test fixture pregame",
    "live_line_flag": False,
    "stale_line_flag": False,
}
```

**Gate output assertion pattern** — copy from `test_dynamic_gate8.py:65–80` style:
```python
# evaluate_no_bet_gates signature (runner line 2457):
# (ok: bool, skip_record: dict|None, gates_passed: list[str])
ok, skip, passed = runner.evaluate_no_bet_gates(pick, {})
```

**Flask test_client POST pattern** — copy from `test_dashboard.py:95–103` extended to POST:
```python
# test_dashboard.py:100-103 — GET pattern
import dashboard
client = dashboard.app.test_client()
response = client.get("/")
self.assertEqual(response.status_code, 200)

# For POST routes (new pattern for ACTION-01..03):
response = client.post("/action/mark-placed", data={
    "date": "2026-06-24",
    "slip_id": "2026-06-24:safest_2_leg:abc123ef",
    "placed": "1",
})
self.assertEqual(response.status_code, 302)  # POST→redirect
```

**Synthetic workbook fixture pattern** — copy from `test_dashboard_views.py:33–56` (`_make_today_wb`):
```python
# test_dashboard_views.py:33-56 — build in-memory workbook with exact headers
from openpyxl import Workbook

def _make_slip_history_wb(rows: list[dict]) -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "Slip History"
    headers = [
        "Date", "Slip ID", "Platform", "Slip Type", "Number of Legs", "Legs",
        "Stake Units", "Winning Legs", "Losing Legs", "Push/Void/DNP Legs",
        "Contains Demon", "Contains Goblin", "Special Line Count", "Slip Result",
        "Standard Payout Multiplier", "Estimated Payout Multiplier",
        "Actual Payout Multiplier", "Payout Confidence", "Gross Return", "Net PnL",
        "Needs Payout Reconciliation", "Graded At", "Notes",
    ]
    ws.append(headers)
    for row in rows:
        ws.append([row.get(h) for h in headers])
    return wb
```

**ACTION-04 integrity assertion pattern** — `evaluate_no_bet_gates` output must be bit-identical before and after a write:
```python
# Pattern from test_dynamic_gate8.py allocate/assert style
before_ok, before_skip, before_passed = runner.evaluate_no_bet_gates(pick, {})
# ... perform write action on in-memory/temp workbook ...
after_ok, after_skip, after_passed = runner.evaluate_no_bet_gates(pick, {})
self.assertEqual(before_ok, after_ok)
self.assertEqual(before_skip, after_skip)
self.assertEqual(before_passed, after_passed)
```

**Cap constants assertion** — `PER_PLAYER_CAP` and `PER_GAME_CAP` (runner lines 2584–2585), **not** `DAILY_EXPOSURE_CAP` (removed in Phase 3 v2.0 — do NOT assert it):
```python
self.assertEqual(runner.PER_PLAYER_CAP, 6.0)
self.assertEqual(runner.PER_GAME_CAP, 6.0)
```

**Naming / type / style conventions** for the test file:
- Class names: `TestRefreshAction`, `TestMarkPlaced`, `TestAddNote`, `TestStatusEndpoint`, `TestActionFourHardLine`
- Use `unittest.TestCase` base class, not bare pytest functions
- `setUpClass` for one-time runner load; `setUp` for per-test workbook fixtures
- `tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)` for temp workbook paths in write tests; clean up in `tearDown` or `addCleanup`

---

### `scripts/dashboard.py` — add POST routes + `/api/status` + `app.secret_key` (controller, request-response)

**Analog:** existing routes + `_freshness_context()` at `scripts/dashboard.py:51–101`

**`app.secret_key` addition** — add immediately after `app: Flask = Flask(__name__)` at line 32:
```python
# scripts/dashboard.py:32 — current state (no secret_key)
app: Flask = Flask(__name__)

# Add after line 32 (required for flash() to work — Pitfall 2 from RESEARCH.md):
app.secret_key = os.environ.get("DASHBOARD_SECRET_KEY") or os.urandom(16)
```

**Existing route template to copy** — copy from `dashboard.py:68–76` (the `index()` route is the pattern every new route must match):
```python
# scripts/dashboard.py:68-76 — GET route pattern (the template)
@app.route("/")
def index() -> str:
    board = dashboard_data.get_today_board()
    return render_template("index.html", board=board, **_freshness_context())
```

**POST route pattern** — extend the existing import line (`from flask import Flask, render_template`) and add `flash, redirect, request, url_for`. New POST routes follow this structure:
```python
# New imports to add at dashboard.py top (extend line 22):
from flask import Flask, flash, redirect, render_template, request, url_for

# New constants (add after HOST constant at line 27):
import fcntl
import subprocess
import threading
import dashboard_writes  # new module

PYTHON3: str = "/usr/local/bin/python3"
SCRIPTS_DIR: Path = Path(__file__).resolve().parent
RUNNER_LOCK_FILE: Path = SCRIPTS_DIR.parent / "data" / "pnl" / "logs" / "sports_system_runner.lock"
ALLOWED_TASKS: frozenset[str] = frozenset({
    "nba_daily_picks", "mlb_daily_picks", "check_results",
    "nba_prop_monitor", "mlb_prop_monitor",
})
```

**`_freshness_context()` pattern to extend** — the existing `_freshness_context()` at `dashboard.py:51–61` returns `write_in_progress` + `last_updated`. The `/api/status` endpoint extends this with `locked` + `last_run` — but `_freshness_context()` itself should NOT be changed (DRY contract for all GET routes stays the same):
```python
# scripts/dashboard.py:51-61 — DO NOT MODIFY this function; it is the DRY helper for GET routes
def _freshness_context() -> dict[str, object]:
    return {
        "write_in_progress": dashboard_data.write_in_progress(),
        "last_updated": dashboard_data.last_updated_hhmm(),
    }
```

**Lock probe helper** — new private function, add before the routes section (after `_freshness_context`):
```python
# Pattern: mirrors sports_system_runner.py:7937-7940 (the acquisition) in non-blocking probe form
def _runner_is_locked() -> bool:
    """Return True iff the runner holds its fcntl.LOCK_EX on LOCK_FILE."""
    try:
        with RUNNER_LOCK_FILE.open("r") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
                return False
            except BlockingIOError:
                return True
    except FileNotFoundError:
        return False
    except OSError:
        return False
```

**POST→redirect→render pattern** — copy from standard Flask idiom (no existing example in `dashboard.py` yet, but the test_dashboard_views.py + Flask docs confirm `302` is the expected redirect status):
```python
@app.route("/action/mark-placed", methods=["POST"])
def action_mark_placed() -> object:
    date = request.form.get("date", "")
    slip_id = request.form.get("slip_id", "")
    placed = request.form.get("placed", "0") == "1"
    if not date or not slip_id:
        flash("Missing date or slip_id.", "error")
        return redirect(url_for("slips"))
    try:
        dashboard_writes.mark_placed(date, slip_id, placed)
        flash(f"Slip {'placed' if placed else 'unplaced'}.", "success")
    except Exception as exc:
        flash(f"Save failed: {exc}", "error")
    return redirect(url_for("slips"))
```

**`/api/status` GET endpoint** — uses `from flask import jsonify`:
```python
@app.route("/api/status")
def api_status() -> object:
    from flask import jsonify
    task = request.args.get("task")
    locked = _runner_is_locked()
    last_record = dashboard_data.last_run_record(task) if task else None
    return jsonify({
        "locked": locked,
        "write_in_progress": dashboard_data.write_in_progress(),
        "last_updated": dashboard_data.last_updated_hhmm(),
        "last_run": last_record,
    })
```
Note: `dashboard_data.last_run_record()` is a NEW function to be added to `dashboard_data.py` (see Shared Patterns below).

**Naming / type conventions** for new routes:
- Return type annotation `-> object` (Flask response types are complex; `object` is the safe annotation used in Phase 1 convention)
- Redirect targets use `url_for("slips")` / `url_for("index")` — never hardcoded strings
- Flash categories: `"success"`, `"error"`, `"warning"` (matching the 3 states in the flash block CSS in RESEARCH.md)

---

### Additive workbook schema: `Slip History` new columns (model, CRUD)

**Analog:** `scripts/sports_system_runner.py:6898–6904` (`ensure_ws_columns`) + `scripts/slip_payouts.py:18–24` (`SLIP_HISTORY_HEADERS`) + `scripts/slip_payouts.py:187–197` (`ensure_slip_history_sheet`)

**`ensure_ws_columns` — the exact function to inline** (`sports_system_runner.py:6898–6904`):
```python
# scripts/sports_system_runner.py:6898-6904
def ensure_ws_columns(ws, columns: list[str]) -> dict[str, int]:
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    for col in columns:
        if col not in headers:
            ws.cell(1, ws.max_column + 1).value = col
            headers.append(col)
    return {str(ws.cell(1, c).value): c for c in range(1, ws.max_column + 1)
            if ws.cell(1, c).value not in (None, "")}
```

**Current `SLIP_HISTORY_HEADERS` tail** (`slip_payouts.py:18–24`) — confirms the three new columns must append AFTER `"Notes"`:
```python
# scripts/slip_payouts.py:18-24
SLIP_HISTORY_HEADERS = [
    "Date", "Slip ID", "Platform", "Slip Type", "Number of Legs", "Legs", "Stake Units",
    "Winning Legs", "Losing Legs", "Push/Void/DNP Legs", "Contains Demon", "Contains Goblin",
    "Special Line Count", "Slip Result", "Standard Payout Multiplier", "Estimated Payout Multiplier",
    "Actual Payout Multiplier", "Payout Confidence", "Gross Return", "Net PnL",
    "Needs Payout Reconciliation", "Graded At", "Notes",  # ← last; DO NOT add new columns here
]
```
New columns `"Placed"`, `"Placed At"`, `"Operator Note"` are added via `ensure_ws_columns(ws, ["Placed", "Placed At", "Operator Note"])` in `dashboard_writes.py` — NOT by modifying `SLIP_HISTORY_HEADERS` (doing so would write `None` into every new graded row).

**`ensure_slip_history_sheet` — DO NOT modify** (`slip_payouts.py:187–197`): This function handles only `SLIP_HISTORY_HEADERS` columns and is called by the runner's grading path. Do not add `"Placed"` / `"Operator Note"` here.

**Upsert scan pattern** — `grade_slips.py:454–464` provides the exact scan idiom (key: date normalisation with `[:10]` is mandatory):
```python
# scripts/grade_slips.py:454-464
date_norm = str(date)[:10]
target_row: int | None = None
for r in range(2, ws.max_row + 1):
    cell_date = ws.cell(r, date_col).value
    cell_slip_id = ws.cell(r, slip_id_col).value
    if str(cell_date or "")[:10] == date_norm and str(cell_slip_id or "") == graded["slip_id"]:
        target_row = r
        break
```
In `dashboard_writes.py`, Date is always column 1 and Slip ID is always column 2 (per `SLIP_HISTORY_HEADERS` order) — no need for `_date_col_index()` / `_slip_id_col_index()` helpers.

---

### Runner lock probe (guard, request-response)

**Analog:** `scripts/sports_system_runner.py:7937–7940` — the LOCK_EX acquisition that the probe mirrors

**Runner's acquisition** (what we are probing):
```python
# scripts/sports_system_runner.py:7937-7940
with LOCK_FILE.open("w") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    lock.write(f"pid={os.getpid()} task={args.task} acquired_at={now_iso()}\n")
    lock.flush()
```

**Non-blocking probe** (the dashboard's lock-aware check):
```python
# Open with "r" (not "w") — must NOT truncate the file
# Use LOCK_EX|LOCK_NB: if BlockingIOError → runner holds the lock
with RUNNER_LOCK_FILE.open("r") as f:
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(f, fcntl.LOCK_UN)
        return False   # no runner active
    except BlockingIOError:
        return True    # runner holds LOCK_EX
```
`LOCK_NB = 4`, `LOCK_EX = 2` (confirmed importable on macOS from RESEARCH.md). File not found = no run ever started = return `False`.

---

### `run_log.jsonl` status reader (utility, request-response)

**Analog:** `scripts/sports_system_runner.py:414–451` (`trailing_failure_streak`) — same reversed-lines pattern

**New `last_run_record` function for `dashboard_data.py`** — derived from `trailing_failure_streak`:
```python
# Pattern: sports_system_runner.py:414-451 (trailing_failure_streak)
# New function to add to dashboard_data.py (read-only, no writes)
def last_run_record(task: str) -> dict[str, Any] | None:
    """Return the most recent run_log.jsonl record for `task`, or None.

    Iterates reversed lines (append-only log, last = most recent).
    Returns None on any I/O or parse error — never raises.
    """
    try:
        text = RUN_LOG_JSONL.read_text()
    except (FileNotFoundError, OSError):
        return None
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if isinstance(rec, dict) and rec.get("task") == task:
            return rec
    return None
```

`RUN_LOG_JSONL` is already defined at `dashboard_data.py:42` — the function goes in `dashboard_data.py` after `last_updated_hhmm()` (line 231).

**Record schema** (live, confirmed in RESEARCH.md):
```json
{"task": "mlb_clv_tracker", "status": "ok", "duration_s": 24.4,
 "error": null, "exit_code": 0, "sport": "mlb", "timestamp": "2026-06-24T09:00:41+00:00"}
```
Status values: `"ok"`, `"error"`, `"timeout"`, `"partial"`.

---

## Shared Patterns

### Atomic workbook save (ACTION-02 / ACTION-03)
**Source:** `scripts/workbook_io.py:79–173`
**Apply to:** all write helpers in `dashboard_writes.py`

The mandatory sequence is always:
1. `with workbook_file_lock(path):` — acquires cooperative lock file
2. `wb = safe_load_workbook(path)` — retrying load WITHOUT `read_only=True`
3. Modify cells via `ws.cell(r, col).value = value`
4. `safe_save_workbook(wb, path)` — atomic temp-file swap + zip validation + dated backup

Never call `wb.save(path)` directly. Never open the workbook with `read_only=True` when writing.

```python
# workbook_io.py:79-117 (workbook_file_lock signature)
@contextmanager
def workbook_file_lock(path: Path, wait_seconds: int = 120, stale_seconds: int = 600):
    ...  # yields lock_path; releases on exit (even on exception)

# workbook_io.py:147-173 (safe_save_workbook)
def safe_save_workbook(wb: Any, path: Path) -> Path | None:
    # 1. wb.save(tmp)  2. zipfile validate  3. test load  4. backup  5. os.replace
```

### POST → redirect → render (ACTION-01/02/03)
**Source:** Flask standard + `dashboard.py:68–100` (existing GET routes as the render half)
**Apply to:** all POST route handlers in `dashboard.py`

- POST handler validates input → calls helper → `flash(message, category)` → `return redirect(url_for(...))`
- GET handler calls data accessor → `return render_template(..., **_freshness_context())`
- Templates call `get_flashed_messages(with_categories=true)` to display the banner
- `app.secret_key` must be set or flash silently fails

### importlib runner load (ACTION-04 tests)
**Source:** `scripts/test_dynamic_gate8.py:1–13`
**Apply to:** `test_dashboard_actions.py` ACTION-04 test class

```python
MOD_PATH = Path(__file__).with_name("sports_system_runner.py")
spec = importlib.util.spec_from_file_location("sports_system_runner", MOD_PATH)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)
runner.load_suppressed_edge_types = lambda: {}
```

### sys.path setup for test files
**Source:** `scripts/test_dashboard_views.py:22–24`
**Apply to:** `test_dashboard_actions.py`

```python
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
```

---

## No Analog Found

All files in this phase have close analogs. No file requires fallback to RESEARCH.md-only patterns.

---

## Critical Anti-Patterns (from RESEARCH.md)

| Anti-Pattern | Why Wrong | What to Do Instead |
|---|---|---|
| `from sports_system_runner import ensure_ws_columns` in `dashboard_writes.py` | Loads all 8,000+ lines of runner at dashboard startup | Inline the 4-line function |
| `wb.save(path)` directly | Bypasses temp-file swap, zip validation, backup | Always `safe_save_workbook(wb, path)` |
| `dashboard_data.write_in_progress()` as lock check for ACTION-01 | Probes workbook cooperative locks, NOT the runner's `LOCK_FILE` flock | Use the `fcntl.flock(LOCK_EX|LOCK_NB)` probe on `LOCK_FILE` |
| Writing to grading-owned `"Notes"` column | Corrupts payout-reason audit trail | Write to `"Operator Note"` column only |
| Modifying `SLIP_HISTORY_HEADERS` to add new columns | Injects `None` into every new graded slip row | Use `ensure_ws_columns` in the write helper |
| `subprocess.Popen` without `stdout=DEVNULL, stderr=DEVNULL` | Pipe buffer fills, child blocks indefinitely | Always pass `DEVNULL` for fire-and-forget |
| `assert DAILY_EXPOSURE_CAP` in ACTION-04 tests | Constant removed in Phase 3 v2.0 | Assert `PER_PLAYER_CAP == 6.0` and `PER_GAME_CAP == 6.0` |

---

## Metadata

**Analog search scope:** `scripts/` directory (dashboard.py, dashboard_data.py, workbook_io.py, slip_payouts.py, grade_slips.py, sports_system_runner.py, test_dynamic_gate8.py, test_dashboard.py, test_dashboard_views.py)
**Files scanned:** 9
**Pattern extraction date:** 2026-06-24
