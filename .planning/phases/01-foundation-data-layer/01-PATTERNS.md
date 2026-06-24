# Phase 1: Foundation & Data Layer - Pattern Map

**Mapped:** 2026-06-23
**Files analyzed:** 6 new files (2 modules, 2 tests, 2+ templates) + 1 net-new directory pair (templates/static)
**Analogs found:** 4 / 6 (the 2 net-new files — `dashboard.py` Flask shell + Jinja templates — have NO in-repo analog; follow design doc + verified research snippets)

> **Net-new pattern flag:** There is **zero existing web code** in this repo (`grep` for `flask`/`render_template`/`jinja2`/`app.run`/`webbrowser` across `scripts/*.py` returns nothing; no `templates/` or `static/` dirs exist). Flask/Jinja is a **fresh capability** — the planner/executor must follow the **design doc + the live-verified research snippets in `01-RESEARCH.md` (Patterns 1-3, Code Examples)**, NOT a local analog, for the HTTP/template layer. Everything that touches **data** (`dashboard_data.py`) and everything **structural** (config, `__main__`, tests, "today" semantics) DOES have strong in-repo analogs — use them.

## File Classification

| New File | Role | Data Flow | Closest Analog | Match Quality |
|----------|------|-----------|----------------|---------------|
| `scripts/dashboard_data.py` | service (read layer) | file-I/O, transform | `scripts/metrics_report.py` (read fn) + `scripts/workbook_io.py` (`safe_load_workbook`) | exact (data-read), exact (lock tolerance) |
| `scripts/dashboard.py` (config/`__main__`) | config / entrypoint | request-response | `scripts/sports_system_runner.py` `main()` (argparse + `__main__`), `env_value`/`env_bool` | role-match (entry pattern only; Flask app body is net-new) |
| `scripts/dashboard.py` (Flask app + routes + Jinja render) | controller | request-response | **NONE** | net-new (no in-repo web code) |
| `scripts/templates/*.html` (base/index, Pico dark shell) | component (view) | request-response | **NONE** | net-new (no in-repo templates) |
| `scripts/static/*` (optional CSS overrides) | config (asset) | file-I/O | **NONE** | net-new (Pico/Chart.js are CDN) |
| `scripts/test_dashboard_data.py` | test | file-I/O | `scripts/test_metrics_report.py` (workbook fixtures) + `scripts/test_def02_path_resolution.py` (sys.path bootstrap) | exact |
| `scripts/test_dashboard.py` | test | request-response | `scripts/test_def02_path_resolution.py` (sys.path bootstrap) + Flask `app.test_client()` (research) | role-match (bootstrap exact; route/bind test is net-new via `test_client`) |

## Pattern Assignments

### `scripts/dashboard_data.py` — read layer (service, file-I/O + transform)

This is the highest-value mapping: every accessor must mirror the **lock-tolerant load + `iter_rows` header-map** pattern and the **`WorkbookAccessError` → last-known-good** contract (D-01).

**Analog A — lock-aware load + retry + `WorkbookAccessError`:** `scripts/workbook_io.py`

`safe_load_workbook` (`workbook_io.py:120-144`) is the function to call — do NOT bare `load_workbook`. It does the stable-file size check, 5 retries, and raises the catchable `WorkbookAccessError`:

```python
# workbook_io.py:120-144 (call this; don't reimplement)
def safe_load_workbook(path: Path, retries: int = 5, delay: float = 1.0, **kwargs: Any):
    ...
    size_a, size_b = wait_for_stable_file(path, delay=delay)
    if size_a != size_b:
        raise WorkbookAccessError(f"Workbook size not stable ({size_a} -> {size_b})")
    if not zipfile.is_zipfile(path):
        raise zipfile.BadZipFile(f"Not a valid xlsx/zip: {path}")
    wb = load_workbook(path, **kwargs)
    ...
    raise WorkbookAccessError(f"Workbook unreadable after {retries} attempts: {path}; ...")
```

`WorkbookAccessError` is defined at `workbook_io.py:30-31`. The cooperative-lock JSON shape the badge reads is written at `workbook_io.py:90`:
```python
fh.write(json.dumps({"pid": os.getpid(), "path": str(path), "acquired_at": now_iso()}) + "\n")
```
`stale_seconds=600` (the reaping threshold the badge must mirror) is the default at `workbook_io.py:80`.

**Analog B — the actual read + tolerate-lock + sheet/header-map loop:** `scripts/metrics_report.py:130-165`

This is the exact "load `read_only=True, data_only=True` → skip on failure → check `sheetnames` → `iter_rows` → map columns" idiom the data layer should copy. Note the **bare `try/except` around the load that `continue`s (serves last-known-good) instead of raising** — that IS the D-01 contract in production code:

```python
# metrics_report.py:130-141
try:
    wb = safe_load_workbook(wb_path, read_only=True, data_only=True)
except Exception:
    # SKIP: unreadable or locked workbook  ← D-01 last-known-good behavior, never raises
    continue
if "Slip History" not in wb.sheetnames:
    continue
ws = wb["Slip History"]
for row_vals in ws.iter_rows(min_row=2, values_only=True):
    ...
```

**Header-mapping note:** `metrics_report.py` maps columns by **index** (precomputed `date_idx`, `stake_idx`, …). The research's Pattern 2 instead recommends the cleaner **`dict(zip(headers, row))`** form for the dashboard (headers from row 1):
```python
# 01-RESEARCH.md Pattern 2 (recommended for dashboard_data.py)
it = ws.iter_rows(values_only=True)
headers = list(next(it, []) or [])
rows = [dict(zip(headers, r)) for r in it]
wb.close()          # ← MANDATORY in finally: read_only keeps the zip open (Pitfall 4)
```
Use the **`*_HEADERS` constants** (next section) as the authoritative column contract rather than `data/nxls_schema.txt` (STALE — see research Runtime State Inventory).

**Authoritative column contracts** (import these or mirror them; they are the schema, not `nxls_schema.txt`):
- `PICKS_HEADERS` — `sports_system_runner.py:277`
- `PROPS_HEADERS` — `sports_system_runner.py:284`
- `PARLAY_HEADERS` — `sports_system_runner.py:294` (`Reasoning` + `Correlation Group` = the "why paired" insight)
- `RESULT_HEADERS` — `sports_system_runner.py:318`
- `PROP_ACCURACY_HEADERS` — `sports_system_runner.py:325`
- `SLIP_HISTORY_HEADERS` — `slip_payouts.py:18-24`

**JSON-first read (lock-free fast path, D-03):** no single existing helper, but the shape is trivial and the research gives the canonical version (return `None` on missing/partial, never crash):
```python
# 01-RESEARCH.md Pattern 2 — JSON-first accessor
def read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None
```
Sources to read JSON-first: `data/pnl/bankroll.json`, `data/research/calibration.json`, `data/{nba,mlb}/*_latest.json`.

**Path constants to mirror** (`sports_system_runner.py:52-59`, `workbook_io.py:22-27`) — anchor on `Path.home()`, never hardcode a username (DEF-02 guard, see `test_def02`):
```python
HOME = Path.home()                 # runner:52 / workbook_io:22
ROOT = HOME / "sports_picks"       # runner:53 / workbook_io:23
DATA = ROOT / "data"               # runner:54 / workbook_io:24
NBA_DIR = DATA / "nba"; MLB_DIR = DATA / "mlb"   # runner:55-56
LOCK_DIR = ROOT / "locks"          # workbook_io:25  ← badge signal source
RUN_LOG (.jsonl) lives under DATA / "pnl" / "logs"               # badge "last updated"
```

**"today" semantics (D-02) — MIRROR, do not re-derive with ZoneInfo:** `today_str()` at `sports_system_runner.py:334-335` (identical copy at `workbook_io.py:38-39`):
```python
# sports_system_runner.py:334 — naive LOCAL time, NO ZoneInfo (Pitfall 2)
def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")
```
The dashboard's Today view must compute the date this exact way (or import `today_str`); a `ZoneInfo("America/Los_Angeles")` conversion would mismatch the pipeline's workbook filename near midnight.

---

### `scripts/dashboard.py` — config + `__main__` entrypoint (the structural half)

**Analog — argparse + `if __name__ == "__main__"`:** `sports_system_runner.py` `main()` (`:7907-7911`) and dispatch at `:8059`:
```python
# sports_system_runner.py:7907-7911
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task")
    parser.add_argument("--test-telegram", action="store_true", help="...")
    args = parser.parse_args()
# ...
# sports_system_runner.py:8059
if __name__ == "__main__":
```
Mirror this shape for `--port` (int-cast, V5 input validation per research Security Domain). The Flask launch body inside `__main__` (bind `127.0.0.1`, `webbrowser` auto-open, `use_reloader=False`) is **net-new** — copy `01-RESEARCH.md` Pattern 1 verbatim (verified live).

**Analog — config override pattern (`--port`/theme via env):** `env_value` (`sports_system_runner.py:388-402`) and `env_bool` (`:220-224`):
```python
# sports_system_runner.py:388 — env first, then ~/.hermes/.env fallback
def env_value(key: str) -> str | None:
    value = os.environ.get(key)
    if value:
        return value.strip().strip('"').strip("'")
    ...
# sports_system_runner.py:220 — boolean feature flags
def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "enabled"}
```
For a single `DASHBOARD_PORT` override the research used the lighter `int(os.environ.get("DASHBOARD_PORT", "8787"))` (Pattern 1) — either is acceptable; if you want the `~/.hermes/.env` fallback, reuse `env_value`. No secrets are read in this phase.

---

### `scripts/dashboard.py` — Flask app, routes, Jinja render (NET-NEW, no analog)

No in-repo precedent. Follow the **design doc §3-4** and the **live-verified** `01-RESEARCH.md` snippets:
- **Pattern 1** (`01-RESEARCH.md`): `app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)` + `threading.Timer(1.0, lambda: webbrowser.open(url)).start()`. **Never** bind `0.0.0.0`/`host=""` (violates DASH-03).
- **Code Examples → Minimal verified serve** (`01-RESEARCH.md`): the exact `@app.route("/")` + render shape that returned a live 200 on 3.14.0a2.
- **Pattern 3** (`01-RESEARCH.md`): `write_in_progress()` (lock pid + `os.kill(pid,0)` liveness + age<600) and `last_updated_hhmm()` (tail `run_log.jsonl`) for the badge/timestamp — computed per render, passed to the template.
- Jinja **autoescaping stays ON** (never `| safe` on workbook string fields like `Reasoning` — XSS, research Security Domain).

### `scripts/templates/*.html` + `scripts/static/*` (NET-NEW, no analog)

No existing templates. Follow design doc §3/§5 + D-05: Pico.css dark via CDN `<link>` (`data-theme="dark"`), dense tables, extensible `<nav>` tab stubs for Calibration/Line-changes/Live (leave empty — deferred). Chart.js CDN `<script>` slot reserved (Phase 2). Verify exact CDN URLs at build time (research A1/A2).

---

### `scripts/test_dashboard_data.py` (test, file-I/O)

**Analog A — run-from-`scripts/` bootstrap:** `test_def02_path_resolution.py:12-20`:
```python
# test_def02_path_resolution.py:12-20 — the canonical sys.path bootstrap + bare import
import sys, unittest
from pathlib import Path
SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import generate_projections as gp        # ← bare sibling import (becomes `import dashboard_data`)
```
End every test file with `if __name__ == "__main__": unittest.main()` (`test_metrics_report.py:500-501`).

**Analog B — synthetic workbook fixtures + tmpdir + module-dir override:** `test_metrics_report.py:26-50` (build a sheet from `*_HEADERS`) and `:65-91` (write to `TemporaryDirectory`, monkeypatch module path constants, restore in `finally`):
```python
# test_metrics_report.py:32-37 — build a sheet from the header constant
wb = Workbook(); ws = wb.active; ws.title = "Slip History"
ws.append(SLIP_HISTORY_HEADERS)
for row in rows:
    ws.append([row.get(h) for h in SLIP_HISTORY_HEADERS])
# test_metrics_report.py:73-91 — override module dirs to a tmpdir, restore in finally
orig_nba = metrics_report.NBA_DIR
try:
    metrics_report.NBA_DIR = sport_dir
    result = metrics_report.aggregate_slip_roi_by_week_sport()
finally:
    metrics_report.NBA_DIR = orig_nba
```

**Net-new for this test (no analog, use research):** the `read_only` byte-preservation assertion — copy `01-RESEARCH.md` "Read-only proves source untouched" (asserts `st_mtime` + `sha256` unchanged) for the `read_only_untouched` case; and the badge liveness test (`write_in_progress` with a live vs dead/stale pid) from Pattern 3.

### `scripts/test_dashboard.py` (test, request-response)

**Analog — same `sys.path` bootstrap** as above (`test_def02:12-20`). Route-200 and loopback-bind assertions are **net-new** — use Flask `app.test_client()` for routes and a real ephemeral-port bind + `socket.getsockname()` for the `127.0.0.1`-only check (research Wave 0 Gaps / Phase Requirements → Test Map). The DASH-02 "flask serves" smoke is the live-verified bind+self-GET from `01-RESEARCH.md` Code Examples.

## Shared Patterns

### Lock tolerance / last-known-good (D-01) — applies to EVERY `dashboard_data.py` accessor
**Source:** `metrics_report.py:130-135` (try/except-continue around `safe_load_workbook`) + `workbook_io.py:30-31,120-144` (`WorkbookAccessError`).
**Rule:** catch `(WorkbookAccessError, FileNotFoundError, Exception)` → return `None`/`[]` (empty/last-known-good), never propagate. Always `wb.close()` in `finally` (Pitfall 4). Always `read_only=True, data_only=True` (Pitfall 3 — else formulas render as `=` strings).

### "today" date — applies to the Today view + any date-keyed read
**Source:** `sports_system_runner.py:334-335` (`today_str()` = naive `datetime.now().strftime("%Y-%m-%d")`).
**Rule:** mirror exactly; **do not** import `zoneinfo` (Pitfall 2). Either replicate the one-liner or `from sports_system_runner import today_str` (heavier import).

### Portable paths — applies to all new files
**Source:** `sports_system_runner.py:52-59`, `workbook_io.py:22-27` — anchor on `Path.home() / "sports_picks"`. Never hardcode `/Users/<name>` (`test_def02` is a standing regression guard against this).

### Config override — applies to `--port`/theme
**Source:** `env_value` (`sports_system_runner.py:388-402`), `env_bool` (`:220-224`). Validate `--port` as `int` (research V5).

### Test bootstrap — applies to both test files
**Source:** `test_def02_path_resolution.py:12-20` (`sys.path.insert(0, SCRIPT_DIR)` + bare import) + `test_metrics_report.py:500-501` (`unittest.main()`). Run from `scripts/`: `cd scripts && python3 test_dashboard_data.py`.

## No Analog Found

Files/concerns with no close match in the codebase (use design doc + verified research snippets in `01-RESEARCH.md`):

| File / Concern | Role | Data Flow | Reason |
|----------------|------|-----------|--------|
| `scripts/dashboard.py` (Flask app body, routes, render) | controller | request-response | No web framework code exists anywhere in `scripts/`. Use `01-RESEARCH.md` Patterns 1 & 3 + Code Examples (live-verified on 3.14.0a2). |
| `scripts/templates/*.html` | component | request-response | No `templates/` dir or Jinja usage exists. Use design doc §3/§5 + D-05 (Pico dark, dense tables, tab stubs). |
| `scripts/static/*` | config (asset) | file-I/O | No `static/` dir; Pico/Chart.js are CDN. Optional local CSS only. |
| `read_only` byte-preservation assertion (in `test_dashboard_data.py`) | test | file-I/O | No existing test asserts mtime+sha256 unchanged. Copy `01-RESEARCH.md` "Read-only proves source untouched". |
| `127.0.0.1`-only bind assertion (in `test_dashboard.py`) | test | request-response | No socket-bind test exists. Use `socket.getsockname()` / `app.test_client()` per research Wave 0. |

## Metadata

**Analog search scope:** `scripts/` (modules: `workbook_io.py`, `metrics_report.py`, `sports_system_runner.py`, `slip_payouts.py`; tests: `test_metrics_report.py`, `test_def02_path_resolution.py`, `test_res03_task_timeout.py`; plus a repo-wide grep for web code).
**Files scanned:** ~9 source/test files read or grepped; full `scripts/test_*.py` listing enumerated for the bootstrap analog.
**Pattern extraction date:** 2026-06-23
