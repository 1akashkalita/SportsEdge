# Phase 3: Safe Actions - Research

**Researched:** 2026-06-24
**Domain:** Flask POST actions — async subprocess spawn, workbook additive writes, ACTION-04 integrity tests
**Confidence:** HIGH (all key findings verified against live source files)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Curated task set = `nba_daily_picks`, `mlb_daily_picks`, `check_results`, `nba_prop_monitor`, `mlb_prop_monitor`.
- **D-02:** Run is async and never inline — web request returns immediately; run continues independently.
- **D-03:** Lock-aware: detects in-progress run and refuses concurrent spawn; runner's `fcntl.LOCK_EX` is the backstop.
- **D-04:** Status reuses existing signals — lock/"updating…" badge + latest `run_log.jsonl` record for the triggered task (✓/✗/⏱ + duration).
- **D-05:** Only the refresh/re-run gets an explicit confirm step. Mark-placed and add-note apply inline with no confirm.
- **D-06:** All action outcomes surface as inline flash banner via POST → redirect → render cycle.
- **D-07:** "Placed" lives in new additive columns on Slip History sheet: `"Placed"` (flag) + `"Placed At"` (timestamp). Toggle-able. Purely informational. Zero downstream effect on grading/bankroll/EV/exposure.
- **D-08:** `"Operator Note"` column — NOT the grading-owned `"Notes"` column. Add to Slip History (slips, keyed by `(Date, Slip ID)`). Also to Picks/Props if a robust pick key can be guaranteed; otherwise v1 scope is slips-only. Single overwrite-able note per entity.

### Claude's Discretion
- Async spawn mechanism (thread+run vs detached Popen)
- Lock-detection mechanism (fcntl probe vs lock-file presence vs run_log status)
- Refresh UI layout (buttons vs dropdown; sport-split vs combined for check_results/monitors)
- Status-poll endpoint shape + cadence; exact flash-banner copy/styling
- Mark-placed / note column names, exact keys, and toggle/overwrite mechanics
- Whether notes cover picks or slips-only for v1 (gated on verifiable pick key)

### Deferred Ideas (OUT OF SCOPE)
- Append-only / timestamped note history per slip/pick
- Pick-level notes if robust key cannot be guaranteed
- Full task picker (all 11 tasks)
- Dedicated run-status / action-outcomes panel
- Calibration/Line-changes/Live tabs (TAB-01..03)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ACTION-01 | Operator can trigger data refresh / task re-run from the dashboard; runs as lock-aware subprocess (refuses if run in progress), reports status, never runs inline in web process | Q1 (run_log schema), Q2 (lock model), Q3 (async spawn), Q4 (status poll) |
| ACTION-02 | Operator can mark a slip as placed from the dashboard (additive column, atomic save) | Q5 (Slip History location + headers), Q6 (additive migration), Q8 (atomic write path) |
| ACTION-03 | Operator can add a note to a slip or pick from the dashboard (additive, atomic save) | Q5–Q8, Q7 (pick key verdict) |
| ACTION-04 | No dashboard action changes gate logic, grades, EV, or exposure caps — all writes additive-only and proven by tests | Q9 (integrity test pattern) |
</phase_requirements>

---

## Summary

Phase 3 adds three guarded, additive write actions to the existing read-only Flask dashboard (`scripts/dashboard.py`), building entirely on already-shipped infrastructure. Every piece of required machinery was verified in the live codebase:

**ACTION-01 (refresh):** The runner's `LOCK_FILE` (`data/pnl/logs/sports_system_runner.lock`) uses `fcntl.LOCK_EX` on a plain text file (format: `pid=N task=T acquired_at=...`). The simplest reliable lock probe from the dashboard is `fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)` — if it raises `BlockingIOError`, a run is in progress; if it succeeds (acquire+release), no run is active. This is authoritative, zero-latency, and tested. The status source for D-04 is `run_log.jsonl` — 451 records in production, schema confirmed: `{task, status, duration_s, error, timestamp, exit_code, sport}`. The async spawn mechanism should be `threading.Thread` + `subprocess.Popen` (detached, no `communicate()`) — preserves `cwd=scripts/` and the `python3` interpreter, returns to the Flask worker immediately, and does not zombie. `subprocess.Popen` (not `subprocess.run`) is the existing pattern in the runner (line 187).

**ACTION-02 + ACTION-03 (mark-placed, add-note):** The canonical Slip History is in `data/pnl/master_pnl.xlsx` (verified: 88 data rows, headers confirmed). Per-sport workbooks also have a Slip History sheet, but only `master_pnl.xlsx` is the complete superset — the dashboard's `get_all_slips()` already reads from there exclusively. The upsert key is `(Date, Slip ID)` — Slip IDs are globally unique structured strings (`YYYY-MM-DD:category:hash8`). The write path is `workbook_io.safe_save_workbook` (mandatory). The additive migration helper is `ensure_ws_columns` (runner line 6898) — it appends missing column headers to the right without touching existing data, and returns a `{header: col_index}` mapping. New columns `"Placed"`, `"Placed At"`, and `"Operator Note"` slot into this pattern exactly.

**Pick key verdict (D-08 caveat):** The `Slip ID` column in Picks sheet rows is `None` in all observed live data. The Gate-10 dedup key is `safe_key(kind, game_id, projection_id, selection)` — stronger than `Selection` alone, but `projection_id` is not in PICKS_HEADERS as a column the dashboard can read back uniquely. `Date + Selection` is unique across observed dates (no duplicates found), but it is NOT guaranteed: two different-platform picks for the same player+stat+line could theoretically share the same `Selection` string. **Verdict: scope notes to slips-only for v1.** The risk of a note write hitting the wrong Picks row is not zero — the dedup guarantee is stronger than what the sheet exposes.

**ACTION-04 (hard line):** Tests use `importlib.util` to load the runner module, call `evaluate_no_bet_gates` / `allocate_eligible_candidates` directly on synthetic pick dicts, and assert `ok`, `skip`, and `passed` outputs. The test style is plain `unittest.TestCase` + `assert` functions, run from `scripts/`. The ACTION-04 test must assert: (a) after calling a dashboard write action, `evaluate_no_bet_gates` on a canonical pick produces the same `(ok, skip, passed)` tuple; (b) `PER_PLAYER_CAP` and `PER_GAME_CAP` are unchanged; (c) no row is added to Picks/Skipped Picks/CLV sheets. The "2 failed, 202 passed" clean baseline refers to the full suite — the new ACTION-04 test must not introduce pre-existing failures.

**Primary recommendation:** Implement the fcntl non-blocking probe for lock detection, `threading.Thread` + `subprocess.Popen` for async spawn, `ensure_ws_columns` for additive column migration, and scope notes to slips-only in v1.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Async subprocess spawn (ACTION-01) | Flask app (`dashboard.py`) | None | POST handler spawns; runner process is self-contained |
| Lock detection (ACTION-01) | Flask app (`dashboard.py`) | `fcntl` (stdlib) | Probes `LOCK_FILE` before spawn — no new state needed |
| Status poll (D-04) | Flask app endpoint + `dashboard_data.py` | `run_log.jsonl` | Reuses existing `last_updated_hhmm()` + new task-specific query |
| Additive workbook writes (ACTION-02/03) | New `dashboard_writes.py` helper | `workbook_io.safe_save_workbook` | Separated from read layer; read accessors stay read-only |
| Schema migration for new columns | `ensure_ws_columns` (runner) | `ensure_slip_history_sheet` (slip_payouts) | Existing pattern; new columns appended to Slip History only |
| Flash/session for action outcomes | Flask app (`dashboard.py`) | `base.html` flash block | POST→redirect→render; requires `app.secret_key` |
| ACTION-04 test | `test_dashboard_actions.py` | `sports_system_runner` (via importlib) | Asserts gate outputs unchanged by write actions |

---

## Per-ACTION Findings

### ACTION-01: Refresh / Async Subprocess + Lock-Aware

#### Q1 — run_log.jsonl schema + helpers

**File:** `scripts/sports_system_runner.py` line 61: `RUN_LOG_JSONL = LOG_DIR / "run_log.jsonl"`  
**Path:** `data/pnl/logs/run_log.jsonl` — VERIFIED live (451 records)

**Append helper** — `append_run_record(record)` at line 374:
```python
def append_run_record(record: dict[str, Any]) -> None:
    try:
        ensure_dirs()
        with RUN_LOG_JSONL.open("a") as f:
            f.write(json.dumps(record, sort_keys=True) + "\n")
    except Exception:
        pass
```

**Record schema** (confirmed from live file):
```json
{
  "task": "mlb_clv_tracker",
  "status": "ok",
  "duration_s": 24.4,
  "error": null,
  "exit_code": 0,
  "sport": "mlb",
  "timestamp": "2026-06-24T09:00:41+00:00"
}
```

**Status values:** `"ok"`, `"error"`, `"timeout"`, `"partial"` (from runner lines 7925–8039)

**Read helper** — `trailing_failure_streak(task)` at line 414 shows the pattern: read entire file, parse each line as JSON, filter by `rec.get("task") == task`, walk backward. For the status poll, the same pattern applied to get the LAST record for a specific task:

```python
def last_run_record(task: str) -> dict | None:
    """Return the most recent run_log.jsonl record for `task`, or None."""
    try:
        lines = RUN_LOG_JSONL.read_text().splitlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if isinstance(rec, dict) and rec.get("task") == task:
                return rec
    except Exception:
        pass
    return None
```

**How the poller finds "latest record for task X":** iterate `reversed(lines)`, return first match on `rec["task"] == task`. The log is append-only, so last is always the most recent.

#### Q2 — Lock model + detection mechanism

**LOCK_FILE** — `scripts/sports_system_runner.py` line 63: `LOCK_FILE = LOG_DIR / "sports_system_runner.lock"`  
**Path:** `data/pnl/logs/sports_system_runner.lock`  
**Format when runner holds it:** `pid=<N> task=<task> acquired_at=<UTC ISO>\n`

**Runner acquires at lines 7937–7938:**
```python
with LOCK_FILE.open("w") as lock:
    fcntl.flock(lock, fcntl.LOCK_EX)
    lock.write(f"pid={os.getpid()} task={args.task} acquired_at={now_iso()}\n")
    lock.flush()
```

The `fcntl.LOCK_EX` is held for the ENTIRE duration of `run_task()` (including all subprocess stages). It is released automatically when the `with` block exits (file handle closed).

**Lock contract:** The lock is a **kernel-level exclusive flock**, not a cooperative advisory lock. If the runner crashes mid-run, macOS/Linux will release the flock automatically when the file descriptor is closed by the OS. The lock file itself persists on disk after the run — it is re-opened (truncated) on the next run with `open("w")`.

**Detection mechanism options evaluated:**

| Option | Reliability | Simplicity | Verdict |
|--------|-------------|------------|---------|
| `fcntl.flock(f, LOCK_EX \| LOCK_NB)` — non-blocking probe | HIGH (kernel-level, authoritative) | Simple (5 lines) | **RECOMMENDED** |
| Lock-file presence + PID liveness | MEDIUM (stale lock if runner crashed) | Medium (parse file, `os.kill`) | Acceptable fallback |
| `run_log.jsonl` "in progress" status | LOW (log written only AFTER completion) | Complex | Not suitable |
| `dashboard_data.write_in_progress()` | MEDIUM (probes `locks/*.xlsx.lock` per-workbook cooperative locks, NOT `LOCK_FILE`) | Already available | WRONG target — this probes workbook locks, not the runner lock |

**Important distinction:** `dashboard_data.write_in_progress()` (line 164) probes `ROOT/locks/*.xlsx.lock` files — these are per-workbook cooperative locks written by `workbook_io.workbook_file_lock()`. This is NOT the same as `LOCK_FILE`. A cron run IS in progress during workbook writes, but the runner lock is acquired earlier and released later. The fcntl probe of `LOCK_FILE` is the correct and earliest signal.

**RECOMMENDED implementation for lock-aware refusal (ACTION-01):**
```python
import fcntl
from pathlib import Path

RUNNER_LOCK_FILE = Path.home() / "sports_picks" / "data" / "pnl" / "logs" / "sports_system_runner.lock"

def runner_is_locked() -> bool:
    """Return True iff the runner is currently holding its fcntl.LOCK_EX."""
    try:
        # Open for reading (does not truncate); probe with LOCK_EX | LOCK_NB.
        # If BlockingIOError: lock held by runner → return True.
        # If acquire succeeds: no runner active → release and return False.
        with RUNNER_LOCK_FILE.open("r") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(f, fcntl.LOCK_UN)
                return False
            except BlockingIOError:
                return True
    except FileNotFoundError:
        return False  # Lock file not yet created — no run ever started
    except OSError:
        return False  # Conservative: don't block the UI on unexpected errors
```

**Why this is the simplest reliable refusal:** Zero state, zero polling, zero extra files. The kernel provides the authoritative answer in one syscall. Even if the runner crashes, the kernel releases the flock — so the probe never falsely blocks. The runner's own `fcntl.LOCK_EX` remains the backstop: even if the probe races with a concurrent spawn, the runner will acquire the lock first and the second invocation will wait (or fail, per its own lock-acquisition behavior).

#### Q3 — Async spawn mechanism

**Cron invocation pattern** (from CLAUDE.md):
```bash
cd scripts && python3 sports_system_runner.py --task <task>
```

**Interpreter:** `/usr/local/bin/python3` (CLAUDE.md; `python` is 3.13 and lacks deps)  
**CWD requirement:** MUST be `scripts/` — sibling imports (`slip_payouts`, `line_timing`, etc.) require it

**Option A — `threading.Thread` + `subprocess.Popen` (RECOMMENDED):**
```python
import subprocess, threading
from pathlib import Path

PYTHON3 = "/usr/local/bin/python3"
SCRIPTS_DIR = Path(__file__).resolve().parent  # scripts/ when dashboard.py is run from scripts/

def _spawn_task(task: str) -> None:
    """Fire-and-forget: spawn runner subprocess, ignore stdout/stderr."""
    subprocess.Popen(
        [PYTHON3, "sports_system_runner.py", "--task", task],
        cwd=str(SCRIPTS_DIR),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        # No communicate() — returns immediately; child runs independently
    )

def spawn_task_async(task: str) -> None:
    """Spawn from a daemon thread so the Flask worker returns immediately."""
    t = threading.Thread(target=_spawn_task, args=(task,), daemon=True)
    t.start()
```

**Why `Popen` not `subprocess.run`:** `subprocess.run` blocks until completion (300–660s for daily_picks). `Popen` without `communicate()` returns immediately — the subprocess runs independently. The process will NOT zombie because macOS reaps reaperless Popen children on process exit. `daemon=True` on the thread means the thread won't block dashboard shutdown.

**Option B — detached Popen (alternative):** `subprocess.Popen(..., start_new_session=True)` launches in a new session (detached from Flask's signal group). More isolation, but harder to track. No compelling advantage for this use case.

**Chosen recommendation: Option A** — thread+Popen. Simpler, matches existing `subprocess.Popen` usage in the runner (line 187), and daemon=True means no orphan threads on shutdown.

**Valid `--task` values for D-01 curated set** (confirmed from `run_task()` dispatch map, line 7878):
- `nba_daily_picks` → `daily_picks("nba")`
- `mlb_daily_picks` → `daily_picks("mlb")`
- `nba_prop_monitor` → `prop_monitor("nba")`
- `mlb_prop_monitor` → `prop_monitor("mlb")`
- `check_results` → `check_results()`

All five are in `TASK_TIMEOUTS` (660s budget each).

#### Q4 — Status poll endpoint (D-04)

**Existing freshness signals in `dashboard_data.py`:**
- `write_in_progress()` (line 164): probes per-workbook cooperative locks — shows "updating" badge in `base.html`
- `last_updated_hhmm()` (line 231): reads last line of `RUN_LOG_JSONL`, parses `"timestamp"` field, returns "HH:MM" local time

**`_freshness_context()` in `dashboard.py`** (line 51) returns:
```python
{
    "write_in_progress": dashboard_data.write_in_progress(),
    "last_updated": dashboard_data.last_updated_hhmm(),
}
```

**Smallest extension for D-04 status poll:**

Add a `/api/status` GET endpoint to `dashboard.py`:
```python
@app.route("/api/status")
def api_status() -> str:
    from flask import jsonify
    locked = runner_is_locked()  # new fcntl probe
    task = request.args.get("task")  # optional: last record for a specific task
    last_record = dashboard_data.last_run_record(task) if task else None
    return jsonify({
        "locked": locked,
        "write_in_progress": dashboard_data.write_in_progress(),
        "last_updated": dashboard_data.last_updated_hhmm(),
        "last_run": last_record,  # {task, status, duration_s, timestamp} or null
    })
```

The refresh button JS can poll `/api/status?task=nba_daily_picks` every 5s and update an in-page badge once `locked=False` and `last_run.task` matches and `last_run.timestamp` > spawn time. This is pure vanilla JS — no new framework. The `"last updated HH:MM"` badge in `base.html` auto-updates via the next page load (per D-04: reuse existing signals).

`last_run_record()` belongs in `dashboard_data.py` as a new public function (read-only, no writes).

---

### ACTION-02: Mark Placed + ACTION-03: Add Note

#### Q5 — Slip History: exact location + headers

**Canonical location (VERIFIED):** `data/pnl/master_pnl.xlsx` — sheet `"Slip History"`  
Live rows: 88 (plus header row = 89 total)

**Confirmed headers** (from `slip_payouts.SLIP_HISTORY_HEADERS`, line 18, AND verified against live workbook):
```
Date, Slip ID, Platform, Slip Type, Number of Legs, Legs, Stake Units,
Winning Legs, Losing Legs, Push/Void/DNP Legs, Contains Demon, Contains Goblin,
Special Line Count, Slip Result, Standard Payout Multiplier, Estimated Payout Multiplier,
Actual Payout Multiplier, Payout Confidence, Gross Return, Net PnL,
Needs Payout Reconciliation, Graded At, Notes
```

**The last column `"Notes"` is grading-owned** — written by `slip_history_row()` as `notes=payout.get("reason", "")` and preserved by `write_slip_history_rows()` (IN-01 preservation rule). **Must NOT be reused for operator notes (D-08).**

**Per-sport workbooks also have Slip History sheets** but they are empty (header-only, or single-date subsets for the day). `get_all_slips()` reads exclusively from `master_pnl.xlsx` — that is the correct write target.

**Upsert key:** `(Date, Slip ID)` — used by `grade_slips.write_slip_history_rows()` (line 406). Slip IDs are stable structured strings `YYYY-MM-DD:category:hash8` (confirmed from live data). The mark-placed and add-note writes should use the same key for their targeted cell updates.

#### Q6 — Additive schema migration path

**Pattern 1: `ensure_ws_columns` (runner line 6898):**
```python
def ensure_ws_columns(ws, columns: list[str]) -> dict[str, int]:
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    for col in columns:
        if col not in headers:
            ws.cell(1, ws.max_column + 1).value = col
            headers.append(col)
    return {str(ws.cell(1, c).value): c for c in range(1, ws.max_column + 1) 
            if ws.cell(1, c).value not in (None, "")}
```

Calling `ensure_ws_columns(ws, ["Placed", "Placed At", "Operator Note"])` on the Slip History sheet is the exact correct pattern to add the three new columns. It appends to the right of existing columns — additive-only, never drops or reorders.

**Pattern 2: `ensure_workbook` (runner line 1842):** Would add new columns to ALL workbooks via the `expected` dict, but that is for per-sport workbooks. For `master_pnl.xlsx`, use `ensure_ws_columns` directly.

**Pattern 3: `ensure_slip_history_sheet` (slip_payouts line 187):** Only migrates columns in `SLIP_HISTORY_HEADERS`. The new action columns are NOT in that list — adding them there would change the shared module and affect the runner. Do NOT modify `SLIP_HISTORY_HEADERS`. Use `ensure_ws_columns` in the new write helper instead.

**Recommended additive write helper pattern:**
```python
# In new scripts/dashboard_writes.py (or at bottom of dashboard_data.py write section)

def _add_action_columns(ws) -> dict[str, int]:
    """Ensure Placed / Placed At / Operator Note columns exist; return col-index map."""
    return ensure_ws_columns(ws, ["Placed", "Placed At", "Operator Note"])
```

**Column contract:**
- `"Placed"`: Python `bool` or `"Y"`/`""` — flag that operator placed this slip
- `"Placed At"`: UTC ISO timestamp string (`datetime.now(timezone.utc).isoformat(timespec="seconds")`)
- `"Operator Note"`: free-text string; single overwrite per slip (not append-only)

**Grading-owned `"Notes"` column MUST NOT be reused** — it is written by `slip_history_row()` as the payout `reason` field and preserved by `write_slip_history_rows()`'s IN-01 preservation rule.

#### Q7 — Pick key stability verdict (D-08 caveat)

**VERDICT: Scope notes to slips-only for v1.**

**Evidence:**
1. `Slip ID` column in live Picks sheet rows = `None` for all observed records (6/22, 6/23 MLB workbooks). The field exists in `PICKS_HEADERS` (index 26) but is not populated for prop picks in the current pipeline.
2. Gate-10 dedup key is `safe_key(kind, game_id, projection_id, selection)` (line 2701) — which is stronger than `Selection` alone. However, `projection_id` is not a column that the dashboard can reliably use as an upsert key (it IS a `Props` sheet column but not in the Picks sheet at a stable index that maps to a unique-enough key).
3. `Date + Selection` was unique across all observed live data (no duplicates), but this uniqueness is NOT guaranteed: the same player+stat+line from two DFS platforms (PrizePicks vs Underdog) could produce the same `Selection` string. The same-name collision risk is documented in project memory (`prop-game-binding-gotcha`).
4. `Date + Sport + Selection` is a stronger key but still not guaranteed unique if both platforms approve the same pick.

**Conclusion for the planner:** Do NOT implement pick-notes in v1. Implement `"Operator Note"` additively on the Slip History sheet only, keyed by `(Date, Slip ID)`. Document in the plan that pick-level notes require a stable pick identifier (either backfill `Slip ID` on Picks rows, or introduce a `Pick ID` column) as a future enhancement.

#### Q8 — Atomic write path

**Mandatory write path:** `workbook_io.safe_save_workbook(wb, path)` (line 147)

```python
def safe_save_workbook(wb: Any, path: Path) -> Path | None:
    # 1. wb.save(tmp) → temp file with PID in name
    # 2. Validate: zipfile.is_zipfile(tmp) + test load
    # 3. Backup current workbook to BACKUP_DIR/today/filename.HHMMSS.xlsx
    # 4. os.replace(tmp, path) — atomic swap
    # Returns backup_path or None
```

**Cooperative locks:** `workbook_file_lock(path)` acquires `ROOT/locks/{filename}.lock` before writing. The dashboard write helper MUST use `workbook_file_lock` before loading for write, then `safe_save_workbook` to persist. Pattern:

```python
from workbook_io import workbook_file_lock, safe_load_workbook, safe_save_workbook

def mark_placed(date: str, slip_id: str, placed: bool) -> None:
    """Toggle Placed flag on a Slip History row in master_pnl.xlsx."""
    master_path = PNL_DIR / "master_pnl.xlsx"
    with workbook_file_lock(master_path):
        wb = safe_load_workbook(master_path)
        ws = wb["Slip History"]
        cols = ensure_ws_columns(ws, ["Placed", "Placed At", "Operator Note"])
        # Find the (Date, Slip ID) row
        for r in range(2, ws.max_row + 1):
            if (str(ws.cell(r, 1).value or "")[:10] == date and 
                    str(ws.cell(r, 2).value or "") == slip_id):
                ws.cell(r, cols["Placed"]).value = True if placed else False
                ws.cell(r, cols["Placed At"]).value = now_utc_iso() if placed else None
                break
        safe_save_workbook(wb, master_path)
```

**Read accessors stay read-only:** `dashboard_data.read_sheet_rows()` opens with `read_only=True` and never writes. The write path lives in a separate module (`dashboard_writes.py` or a clearly separated section) and uses the `workbook_file_lock` → load → modify → `safe_save_workbook` pattern.

**Dashboard reads after a write:** After a write, the next page load calls `get_all_slips()` which re-reads from the workbook. The `Placed` and `Operator Note` columns are additive — `read_sheet_rows()` returns them as part of the row dict automatically (header-mapped). The slips.html template will need to render them.

---

### ACTION-04: The Hard Line

#### Q9 — Integrity test pattern

**Existing test idiom** (from `test_dynamic_gate8.py`):

```python
# Load runner via importlib (pattern from test_dynamic_gate8.py lines 1-13)
import importlib.util
from pathlib import Path

MOD_PATH = Path(__file__).with_name("sports_system_runner.py")
spec = importlib.util.spec_from_file_location("sports_system_runner", MOD_PATH)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)
runner.load_suppressed_edge_types = lambda: {}  # stub external I/O
```

**`evaluate_no_bet_gates` signature** (line 2457):
```python
def evaluate_no_bet_gates(
    pick: dict[str, Any], 
    suppressed_edges: dict[str, str]
) -> tuple[bool, dict[str, Any] | None, list[str]]:
    # Returns: (passed: bool, skip_record: dict|None, gates_passed: list[str])
```

**`allocate_eligible_candidates` signature** (line 2695):
```python
def allocate_eligible_candidates(
    candidates: list[dict[str, Any]], 
    starting_exposure: float = 0.0
) -> dict[str, Any]:
    # Returns: {picks, skipped, board_quality, dynamic_daily_cap, ...}
```

**Relevant constants** (confirmed live):
- `PER_PLAYER_CAP = 6.0` (line 2584)
- `PER_GAME_CAP = 6.0` (line 2585)
- No `DAILY_EXPOSURE_CAP` constant (removed in Phase 3 of v2.0; Gate-8 dynamic cap also removed)

**Known clean baseline:** "2 failed, 202 passed" — the 2 known failures are in `test_generate_projections.py` (pre-existing). Total test collection: 832 tests (confirmed 2026-06-24). New ACTION-04 tests must not touch these.

**ACTION-04 test strategy:**

The ACTION-04 test (`test_dashboard_actions.py`) must prove:
1. Calling a dashboard write action (mark_placed, add_note) on a workbook does NOT alter any value in the Picks/Props/CLV/Results/Skipped Picks/Slip History `"Notes"` column.
2. `evaluate_no_bet_gates` on a fixed pick dict returns the SAME `(bool, skip_record, passed_gates)` before and after a write action.
3. `PER_PLAYER_CAP` and `PER_GAME_CAP` are unchanged by any write.
4. The write action only modifies the specific column/row it was told to (additive-only assertion).

```python
# Sketch of ACTION-04 test idiom:
class TestActionFourHardLine(unittest.TestCase):
    """ACTION-04: dashboard write actions must not alter gate logic, grades, EV, or caps."""

    @classmethod
    def setUpClass(cls):
        # Load runner via importlib (standard pattern)
        spec = importlib.util.spec_from_file_location(
            "sports_system_runner", MOD_PATH
        )
        cls.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runner)
        cls.runner.load_suppressed_edge_types = lambda: {}

    def _canonical_pick(self) -> dict:
        return {
            "kind": "prop", "date": "2026-06-24", "sport": "MLB",
            "game_id": "g1", "projection_id": "proj-1", 
            "selection": "Player A Over 0.5 Hits",
            "line": 0.5, "odds": "standard", "score": 3, "confidence": "A",
            "units": 1.0, "player": "Player A", "team": "T1",
            "model_projection": 0.7, "edge": 1.5, "model_over_probability": 0.65,
            "ev": 0.2, "edge_type_tags": "projection_edge",
            "injury_status": "ACTIVE", "sportsbook_verified": True,
            "hit_row": {"sample_size": 20, "hit_rate_l10": 0.7},
            "line_timing": "pregame", "line_timing_confidence": "high",
            "line_timing_reason": "test", "live_line_flag": False, "stale_line_flag": False,
        }

    def test_mark_placed_does_not_alter_gate_output(self):
        """mark_placed() must not change evaluate_no_bet_gates output."""
        pick = self._canonical_pick()
        # Snapshot gate output BEFORE any write
        before_ok, before_skip, before_passed = self.runner.evaluate_no_bet_gates(pick, {})
        
        # Simulate mark_placed (using in-memory workbook, no real file I/O)
        # ... (use tmp workbook + dashboard_writes.mark_placed_in_wb)
        
        # Snapshot AFTER write (same pick dict, unmodified)
        after_ok, after_skip, after_passed = self.runner.evaluate_no_bet_gates(pick, {})
        self.assertEqual(before_ok, after_ok)
        self.assertEqual(before_skip, after_skip)
        self.assertEqual(before_passed, after_passed)

    def test_exposure_caps_unchanged(self):
        """PER_PLAYER_CAP and PER_GAME_CAP must not be altered by any write action."""
        import dashboard_writes  # new module
        self.assertEqual(self.runner.PER_PLAYER_CAP, 6.0)
        self.assertEqual(self.runner.PER_GAME_CAP, 6.0)
        # No write action imports or modifies runner module constants
        # (structural assertion — import dashboard_writes, check runner constants unchanged)
        self.assertEqual(self.runner.PER_PLAYER_CAP, 6.0)

    def test_write_is_additive_only(self):
        """mark_placed only adds Placed/Placed At columns; existing Notes column unchanged."""
        # Build synthetic workbook with known Notes content
        # Call mark_placed → assert Notes column cell == original value
        # Assert new Placed column cell == expected value
```

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Workbook column addition | Custom "add column if missing" loop | `ensure_ws_columns(ws, [cols])` (runner line 6898) | Already handles header scanning and right-append |
| Atomic workbook save | `wb.save(path)` directly | `workbook_io.safe_save_workbook(wb, path)` | temp-file swap, zip validation, backup — essential for correctness |
| Workbook write locking | Roll own lock file | `workbook_io.workbook_file_lock(path)` | Cooperative lock with staleness reaping already wired |
| Lock-tolerant workbook read | Try/except load | `dashboard_data.read_sheet_rows(path, sheet)` | Returns None on lock, empty list on missing sheet — safe contract |
| Run-in-progress detection | Poll a file, check mtime | `fcntl.flock(LOCK_FILE, LOCK_EX|LOCK_NB)` | Authoritative kernel-level answer, zero latency |
| Run log parsing | Custom JSONL scanner | `last_run_record(task)` pattern from `trailing_failure_streak` | Already proven pattern in runner lines 414–451 |
| Flash messages | Custom session store | `flask.flash()` + `get_flashed_messages()` | Standard Flask — just add `app.secret_key` |

---

## Architecture Patterns

### System Architecture Diagram

```
browser (127.0.0.1:8787)
     │
     │ GET /api/status?task=T         POST /action/refresh        POST /action/mark-placed
     ▼                                     │                            │
dashboard.py (Flask)                       │                            │
     │                                     ▼                            ▼
     │               runner_is_locked()    spawn_task_async(task)   dashboard_writes.mark_placed()
     │               (fcntl probe on       └─ Thread → Popen        └─ workbook_file_lock
     │                LOCK_FILE)               └─ python3               └─ safe_load_workbook
     │                                             runner.py --task T   └─ ensure_ws_columns
     │                                             cwd=scripts/          └─ write cell
     ▼                                                                   └─ safe_save_workbook
dashboard_data.py (READ ONLY)
     │ last_run_record(task)              runner's LOCK_FILE           master_pnl.xlsx
     │ last_updated_hhmm()               (fcntl.LOCK_EX held           Slip History sheet
     ▼                                    during entire run)            (additive columns)
run_log.jsonl
```

### Recommended Project Structure

```
scripts/
├── dashboard.py          # Flask app — add POST routes + /api/status endpoint, secret_key
├── dashboard_data.py     # Read-only layer — add last_run_record(), runner_is_locked()
├── dashboard_writes.py   # NEW: additive write helpers (mark_placed, add_note)
├── templates/
│   ├── base.html         # Add flash message block + Refresh UI widget
│   ├── index.html        # Add "Add Note" forms on pick rows (if pick notes scoped in)
│   └── slips.html        # Add "Mark Placed" + "Add Note" forms on slip rows
└── test_dashboard_actions.py  # NEW: ACTION-01..04 tests
```

### Pattern 1: Lock-Aware Refresh POST Route

```python
# In dashboard.py
from flask import Flask, flash, redirect, request, url_for
import threading, subprocess, fcntl
from pathlib import Path

PYTHON3 = "/usr/local/bin/python3"
SCRIPTS_DIR = Path(__file__).resolve().parent
RUNNER_LOCK_FILE = SCRIPTS_DIR.parent / "data" / "pnl" / "logs" / "sports_system_runner.lock"
ALLOWED_TASKS = frozenset({"nba_daily_picks", "mlb_daily_picks", "check_results",
                            "nba_prop_monitor", "mlb_prop_monitor"})

@app.route("/action/refresh", methods=["POST"])
def action_refresh():
    task = request.form.get("task", "")
    if task not in ALLOWED_TASKS:
        flash(f"Unknown task: {task!r}", "error")
        return redirect(request.referrer or url_for("index"))
    if runner_is_locked():
        flash("Run already in progress — try again shortly.", "warning")
        return redirect(request.referrer or url_for("index"))
    threading.Thread(
        target=lambda: subprocess.Popen(
            [PYTHON3, "sports_system_runner.py", "--task", task],
            cwd=str(SCRIPTS_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        ),
        daemon=True
    ).start()
    flash(f"Re-run triggered: {task}. Check status in a few minutes.", "success")
    return redirect(request.referrer or url_for("index"))
```

### Pattern 2: Mark-Placed POST Route

```python
@app.route("/action/mark-placed", methods=["POST"])
def action_mark_placed():
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

### Pattern 3: Additive Column Write (dashboard_writes.py)

```python
# Source: verified pattern from workbook_io.py + runner ensure_ws_columns
from pathlib import Path
from workbook_io import workbook_file_lock, safe_load_workbook, safe_save_workbook

def mark_placed(date: str, slip_id: str, placed: bool) -> None:
    from sports_system_runner import ensure_ws_columns  # or inline
    master_path = Path.home() / "sports_picks" / "data" / "pnl" / "master_pnl.xlsx"
    with workbook_file_lock(master_path):
        wb = safe_load_workbook(master_path)
        ws = wb["Slip History"]
        cols = ensure_ws_columns(ws, ["Placed", "Placed At", "Operator Note"])
        for r in range(2, ws.max_row + 1):
            if (str(ws.cell(r, 1).value or "")[:10] == str(date)[:10]
                    and str(ws.cell(r, 2).value or "") == slip_id):
                ws.cell(r, cols["Placed"]).value = placed
                if placed:
                    ws.cell(r, cols["Placed At"]).value = now_utc_iso()
                break
        safe_save_workbook(wb, master_path)
```

### Pattern 4: Flash Message Block in base.html

```html
<!-- Add before {% block content %} -->
{% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}
    {% for category, message in messages %}
      <div style="padding:0.4rem 1rem; background:{% if category == 'error' %}#7d1a1a{% elif category == 'success' %}#1a4d2e{% else %}#4d3a1a{% endif %}; color:#fff; margin-bottom:0.5rem;">
        {{ message }}
      </div>
    {% endfor %}
  {% endif %}
{% endwith %}
```

**Secret key requirement:** `app.secret_key` must be set for `flash()` to work (uses signed session cookies). For a local single-user tool, generate at startup:
```python
app.secret_key = os.environ.get("DASHBOARD_SECRET_KEY") or os.urandom(16)
```

### Anti-Patterns to Avoid

- **Importing or calling `run_task()` inline in the Flask worker:** The Flask worker thread would block for 300–660s. Always spawn via subprocess.
- **Using `dashboard_data.write_in_progress()` as the lock check for ACTION-01:** That function probes per-workbook cooperative locks (`ROOT/locks/*.xlsx.lock`), NOT the runner's `fcntl.LOCK_EX` on `LOCK_FILE`. They are different lock mechanisms for different things.
- **Writing to the grading-owned `"Notes"` column:** It is written by `slip_history_row()` and preserved by `write_slip_history_rows()` IN-01. Overwriting it would corrupt the payout-reason audit trail.
- **Calling `wb.save(path)` directly in a write helper:** Always use `safe_save_workbook` — direct save bypasses the temp-file swap, zip validation, and backup.
- **Modifying `SLIP_HISTORY_HEADERS` to add new columns:** That list is the shared contract for `ensure_slip_history_sheet()` and `write_slip_history_rows()`. Adding `"Placed"` there would write `None` values into every new graded slip row. Use `ensure_ws_columns` in the write helper instead.

---

## Common Pitfalls

### Pitfall 1: dashboard_data.write_in_progress() is NOT the right lock check for ACTION-01

**What goes wrong:** Developer checks `dashboard_data.write_in_progress()` before spawning — sees `False` (no workbook locks held yet), spawns a second runner. The second runner acquires the `fcntl.LOCK_EX` only after the first runner's workbook-write phase — so both runners run the gate/pick/injection phases concurrently for a few minutes before one eventually blocks.

**Root cause:** `write_in_progress()` probes `ROOT/locks/*.xlsx.lock` (workbook-level cooperative locks), which are acquired/released per-sheet-write during a run, not at run start. The runner's `fcntl.LOCK_EX` on `LOCK_FILE` is the full-run lock.

**Prevention:** Use the fcntl probe on `LOCK_FILE`, not `write_in_progress()`.

### Pitfall 2: Flask flash() fails silently if secret_key is None

**What goes wrong:** `flash("run started")` is called but the flash never appears on the redirect target. No error is thrown in the POST handler — the redirect happens — but the message is lost.

**Root cause:** Flask flash uses signed session cookies. If `app.secret_key is None`, the session silently fails to store the message.

**Prevention:** Add `app.secret_key = os.environ.get("DASHBOARD_SECRET_KEY") or os.urandom(16)` near the `app = Flask(__name__)` line.

**Warning signs:** Flash messages work in Flask test client (test_client sets a dummy secret_key) but not in live browser.

### Pitfall 3: subprocess.Popen without stdout/stderr=DEVNULL blocks on pipe buffer

**What goes wrong:** `Popen` without output redirection leaves the child writing to inherited stdout/stderr of the dashboard process. If the child writes enough output (daily_picks writes considerable JSON logs), the OS pipe buffer fills and the child blocks waiting for the parent to drain it. The child never finishes; the lock is held indefinitely.

**Root cause:** Inherited file descriptors from the parent process.

**Prevention:** Always pass `stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL` when spawning fire-and-forget subprocesses.

### Pitfall 4: Writing to per-sport workbook instead of master_pnl.xlsx

**What goes wrong:** Mark-placed writes to `data/mlb/mlb_{today}.xlsx` Slip History. The dashboard reads from `master_pnl.xlsx`. The Placed flag appears written but never shows up in the UI.

**Root cause:** `get_all_slips()` explicitly reads `PNL_DIR / "master_pnl.xlsx"` (confirmed in `dashboard_data.py` line 417).

**Prevention:** Dashboard write helpers MUST target `data/pnl/master_pnl.xlsx`.

### Pitfall 5: ALLOWED_TASKS whitelist not enforced

**What goes wrong:** The POST handler accepts any `--task` value from the form, allowing the operator to accidentally trigger `rebuild_bankroll` or `verify` from the browser.

**Prevention:** Check `task in ALLOWED_TASKS` before spawning; flash an error and redirect on mismatch.

### Pitfall 6: ensure_ws_columns imported from runner causes full runner module load in dashboard

**What goes wrong:** `from sports_system_runner import ensure_ws_columns` in `dashboard_writes.py` triggers `spec.loader.exec_module(runner)` and all 8,000+ lines of runner module-level code (imports, constants, feature flags, possibly side effects).

**Prevention:** Either (a) inline the 4-line `ensure_ws_columns` function in `dashboard_writes.py`, or (b) import it from a utility-only context. The function is trivial enough to inline.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Gate 8 global dynamic exposure cap | Removed; only per-player/per-game concentration caps remain | Phase 3 v2.0 (2026-06-22) | `DAILY_EXPOSURE_CAP` constant no longer exists in runner; ACTION-04 tests must not assert its presence |
| Slip History only in per-sport workbooks | Also in `master_pnl.xlsx` (superset) | Phase 2 v2.0 | Dashboard writes target `master_pnl.xlsx` exclusively |
| Dashboard write actions | NOT YET BUILT | Phase 3 v3.0 (this phase) | Requires `app.secret_key`, new POST routes, `dashboard_writes.py` module |

---

## Validation Architecture

Nyquist validation ENABLED (confirmed from `.planning/config.json`).

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest` 9.0.3 + `unittest.TestCase` |
| Config file | None (discovery by convention) |
| Quick run command | `python3 -m pytest test_dashboard_actions.py -q` (from `scripts/`) |
| Full suite command | `python3 -m pytest -q` (from `scripts/`) |
| Known pre-existing failures | 2 in `test_generate_projections.py` (clean baseline: "2 failed, 202 passed" — but total is now 832 tests) |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ACTION-01a | `/action/refresh` POST with valid task triggers async subprocess | integration | `pytest test_dashboard_actions.py::TestRefreshAction::test_refresh_triggers_subprocess -x` | ❌ Wave 0 |
| ACTION-01b | `/action/refresh` refuses (flash warning) when runner lock held | unit | `pytest test_dashboard_actions.py::TestRefreshAction::test_refresh_refused_when_locked -x` | ❌ Wave 0 |
| ACTION-01c | `/action/refresh` with invalid task is rejected | unit | `pytest test_dashboard_actions.py::TestRefreshAction::test_refresh_invalid_task_rejected -x` | ❌ Wave 0 |
| ACTION-01d | `/api/status` returns `locked`, `last_run` fields | unit | `pytest test_dashboard_actions.py::TestStatusEndpoint::test_status_fields -x` | ❌ Wave 0 |
| ACTION-02 | `/action/mark-placed` adds `Placed`/`Placed At` columns additively and writes correct row | unit | `pytest test_dashboard_actions.py::TestMarkPlaced::test_mark_placed_additive -x` | ❌ Wave 0 |
| ACTION-03 | `/action/add-note` writes `Operator Note` additively; grading `Notes` column unchanged | unit | `pytest test_dashboard_actions.py::TestAddNote::test_add_note_additive -x` | ❌ Wave 0 |
| ACTION-04a | `evaluate_no_bet_gates` output identical before/after mark_placed write | unit | `pytest test_dashboard_actions.py::TestActionFourHardLine::test_mark_placed_does_not_alter_gate_output -x` | ❌ Wave 0 |
| ACTION-04b | `PER_PLAYER_CAP`, `PER_GAME_CAP` unchanged after any write action | unit | `pytest test_dashboard_actions.py::TestActionFourHardLine::test_exposure_caps_unchanged -x` | ❌ Wave 0 |
| ACTION-04c | Write actions do not modify Picks/Skipped Picks/CLV sheets | unit | `pytest test_dashboard_actions.py::TestActionFourHardLine::test_write_only_touches_slip_history -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `python3 -m pytest test_dashboard_actions.py test_dashboard.py test_dashboard_data.py -q`
- **Per wave merge:** `python3 -m pytest -q` (full suite from `scripts/`)
- **Phase gate:** Full suite green (except 2 known `test_generate_projections.py` failures) before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `test_dashboard_actions.py` — all 9 test cases above (Wave 0 must create this file with RED stubs)
- [ ] `dashboard_writes.py` — new module; Wave 0 must create empty stub with correct function signatures
- [ ] `app.secret_key` in `dashboard.py` — required for flash to work; must be added in Wave 0 or Plan 1

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `Popen` without `communicate()` will not zombie on macOS (OS reaps the child on exit) | ACTION-01 async spawn | Low — macOS and Linux both reap orphaned children; but if wrong, zombie processes accumulate (no functional impact on correctness) |
| A2 | `Date + Slip ID` is unique within `master_pnl.xlsx` Slip History | ACTION-02/03 write key | Medium — if a slip is written twice with same (Date, Slip ID), the row scan finds the first match and overwrites it; the second row becomes unreachable. Currently not observed in 88 rows. |
| A3 | `ensure_ws_columns` from runner can be safely inlined in `dashboard_writes.py` (no hidden dependencies) | Architecture | LOW — the 4-line function uses only `ws.cell()` API and `ws.max_column` |

---

## Open Questions

1. **Whether `dashboard_writes.py` is a new file or a section in `dashboard_data.py`**
   - What we know: `dashboard_data.py` is explicitly read-only (its module docstring says "Never writes — all paths are read_only")
   - What's unclear: whether the planner prefers tight colocation or explicit separation
   - Recommendation: new `scripts/dashboard_writes.py` — preserves the read-only contract on `dashboard_data.py`, cleaner test imports

2. **Whether the Refresh UI is a dropdown or separate buttons**
   - What we know: D-01 curated set has 5 tasks; whether check_results/monitors are sport-split or combined is discretion
   - Recommendation: a small `<select>` dropdown for the 5 tasks + a single "Run" button with confirm step; sport-split (nba/mlb versions) for prop_monitor is already in the task names, so just expose them individually

3. **Whether the status poll uses JS setInterval or a full page reload**
   - What we know: D-04 says polling cadence is discretion; D-06 says flash banner for action outcomes does NOT require JS
   - Recommendation: light JS `setInterval(5000)` on the refresh-triggered page only, to update an in-page status badge from `/api/status?task=T`; no polling on other pages

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.14.0a2 | All scripts | ✓ | 3.14.0a2 at `/usr/local/bin/python3` | None (required) |
| Flask + Werkzeug | `dashboard.py` | ✓ | Already confirmed serving in Phase 1 | stdlib `http.server` (Phase 1 D-06) |
| `fcntl` (stdlib) | Lock probe | ✓ | Confirmed importable: `LOCK_EX=2, LOCK_NB=4` | None (POSIX only — macOS verified) |
| `openpyxl` | Workbook writes | ✓ | 3.1.5 | None (required) |
| `workbook_io.py` | Atomic saves | ✓ | Phase 1 ships it in `scripts/` | None (required) |
| `data/pnl/master_pnl.xlsx` | ACTION-02/03 target | ✓ | 88 Slip History rows, Slip History sheet confirmed | If absent: flash error, no write |
| `data/pnl/logs/run_log.jsonl` | ACTION-01 status | ✓ | 451 records confirmed | If absent: `last_run_record()` returns None gracefully |

**Missing dependencies with no fallback:** None.

---

## Package Legitimacy Audit

This phase installs no new external packages. All dependencies (`flask`, `openpyxl`, `fcntl`, `threading`, `subprocess`) are already installed and verified from Phases 1–2 or are stdlib. No package legitimacy gate required.

---

## Security Domain

`security_enforcement` is not explicitly set to `false` in `.planning/config.json`. Applies at minimal scope — this is a single-operator localhost tool.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Localhost solo, no auth by design (REQUIREMENTS.md Out-of-Scope) |
| V3 Session Management | Minimal | Flask session used only for flash messages; `secret_key` must be set |
| V4 Access Control | No | 127.0.0.1 bind only; all requests are from the operator |
| V5 Input Validation | Yes | `task` form field must be in `ALLOWED_TASKS` whitelist before subprocess spawn |
| V6 Cryptography | No | No crypto; workbook writes use atomic `os.replace` |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Arbitrary `--task` injection via form field | Tampering | `ALLOWED_TASKS` frozenset whitelist on POST handler |
| CSRF (form submission) | Tampering | Out-of-scope: localhost only, single operator, no auth |
| Path traversal in slip_id/date form fields | Tampering | Validate against known format; do NOT use form fields in filesystem paths |

---

## Sources

### Primary (HIGH confidence)
- `scripts/sports_system_runner.py` — LOCK_FILE (line 63), RUN_LOG_JSONL (line 61), `append_run_record` (line 374), `fcntl.LOCK_EX` (line 7937-7938), PICKS_HEADERS (line 277), `ensure_ws_columns` (line 6898), `run_task` dispatch (line 7878), PER_PLAYER_CAP/PER_GAME_CAP (line 2584-2585), `evaluate_no_bet_gates` (line 2457)
- `scripts/slip_payouts.py` — SLIP_HISTORY_HEADERS (line 18), `ensure_slip_history_sheet` (line 187), `slip_history_row` (line 200)
- `scripts/grade_slips.py` — `write_slip_history_rows` (line 406), upsert key pattern (line 454-464)
- `scripts/workbook_io.py` — `safe_save_workbook` (line 147), `workbook_file_lock` (line 80), `safe_load_workbook` (line 120)
- `scripts/dashboard.py` — `_freshness_context()` (line 51), existing route handlers (line 68-100)
- `scripts/dashboard_data.py` — `write_in_progress()` (line 164), `last_updated_hhmm()` (line 231), `get_all_slips()` target = `master_pnl.xlsx` (line 417), RUN_LOG_JSONL alias (line 42)
- `scripts/templates/base.html`, `slips.html`, `index.html` — confirmed no flash block, no POST forms, no secret_key
- Live workbook verification: `master_pnl.xlsx` Slip History headers confirmed (88 rows + header = 89), per-sport Slip History confirmed header-only or sparse
- Live `run_log.jsonl` schema confirmed: 451 records, fields `{task, status, duration_s, error, exit_code, sport, timestamp}`
- Live `fcntl` probe on `LOCK_FILE` confirmed working (LOCK_NB raises BlockingIOError when held)
- `test_dynamic_gate8.py` — importlib+runner load pattern (lines 1-13), gate output assertion idiom

### Secondary (MEDIUM confidence)
- `.planning/phases/03-safe-actions/03-CONTEXT.md` — D-01..D-08, discretion areas, deferred ideas
- `.planning/REQUIREMENTS.md` — ACTION-01..04 definitions
- `.planning/ROADMAP.md` — Phase 3 success criteria
- `docs/superpowers/specs/2026-06-23-localhost-dashboard-design.md` §6–9 — approved spec

### Tertiary (LOW confidence)
- None — all key claims verified against live source files.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all verified from live source files
- Architecture: HIGH — patterns extracted from existing working code
- Pitfalls: HIGH — 3 of 6 pitfalls derived from verified source code behavior
- ACTION-04 test idiom: HIGH — modeled on `test_dynamic_gate8.py` which already passes

**Research date:** 2026-06-24
**Valid until:** 2026-07-24 (stable internal codebase; no external API changes)
