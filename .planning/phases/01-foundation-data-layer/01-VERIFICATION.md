---
phase: 01-foundation-data-layer
verified: 2026-06-23T22:10:00Z
status: human_needed
score: 8/8 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Run `cd scripts && python3 dashboard.py` and confirm the browser opens at http://127.0.0.1:8787 showing the dark Pico.css shell"
    expected: "Browser tab opens within ~1 second; dark themed page with nav items Today/Slips/History and inert Calibration/Line-changes/Live stubs; no console errors"
    why_human: "Browser auto-open, visual theme, and nav rendering cannot be verified without a running process and a display"
  - test: "From a second machine on the same LAN, attempt `curl http://<mac-ip>:8787`"
    expected: "Connection refused; the dashboard is not reachable from other machines"
    why_human: "Network isolation of a loopback-only bind requires an actual second-machine network probe — grep on HOST is necessary but not sufficient"
---

# Phase 1: Foundation & Data Layer Verification Report

**Phase Goal:** A one-command localhost dashboard process exists on the verified web stack, bound to 127.0.0.1 only, with a read-only data layer that surfaces persisted workbook + JSON data without ever modifying or corrupting it — even when a workbook is locked mid-write.
**Verified:** 2026-06-23T22:10:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Running `python3 dashboard.py` from `scripts/` starts the server; the operator can open it at a `127.0.0.1` localhost URL (DASH-01) | ✓ VERIFIED | `dashboard.py` exists (116 lines); `app = Flask(__name__)` and `HOST = "127.0.0.1"` at module level; `main()` with `app.run(host=HOST, port=args.port, ...)`; test_route_index passes (WSGI GET / → 200) |
| 2 | Flask imports and serves on system Python 3.14.0a2 — web stack confirmed before anything is built on it (DASH-02) | ✓ VERIFIED | `test_flask_serves` uses `werkzeug.serving.make_server` to bind 127.0.0.1 ephemeral port and issues real TCP GET; test passes live: "Ran 1 test in 0.880s: OK" |
| 3 | The server binds to `127.0.0.1` only and is not reachable from another machine (DASH-03) | ✓ VERIFIED (automated); ? UNCERTAIN (network isolation needs human) | `HOST: str = "127.0.0.1"` (line 27); `app.run(host=HOST, ...)` (line 96); grep for `0.0.0.0` and `host=""` returns nothing; `test_loopback_only` asserts `dashboard.HOST == "127.0.0.1"` and probes a bound socket — PASSES. Physical isolation from other machines requires human test (see Human Verification) |
| 4 | The data layer reads workbooks (`read_only=True`) and JSON without writing; source mtime + sha256 unchanged after a read (DASH-04) | ✓ VERIFIED | `read_sheet_rows` calls `safe_load_workbook(Path(xlsx), read_only=True, data_only=True)`; grep for `safe_save_workbook`, `wb.save`, `.save(` in `dashboard_data.py` returns nothing; `test_read_only_untouched` asserts mtime AND sha256 byte-identical after read — PASSES |
| 5 | When a workbook is locked mid-write, a read returns last-known-good (None/[]) and never raises (DASH-04/D-01) | ✓ VERIFIED | `read_sheet_rows` catches `(WorkbookAccessError, FileNotFoundError, Exception)` → returns `None`; `test_lock_tolerant` monkeypatches `safe_load_workbook` to raise `WorkbookAccessError` and asserts result `in (None, [])` — PASSES |
| 6 | Missing workbook/JSON returns empty state and never raises | ✓ VERIFIED | `read_json` catches `(FileNotFoundError, json.JSONDecodeError, OSError)` → returns `None`; `read_sheet_rows` catches `FileNotFoundError` → returns `None`; `test_missing_is_empty` verifies both — PASSES |
| 7 | `today` matches the runner's naive-local `today_str()` with no ZoneInfo (D-02) | ✓ VERIFIED | `today_str()` at line 56: `return datetime.now().strftime("%Y-%m-%d")`; grep for `zoneinfo`/`ZoneInfo` in `dashboard_data.py` returns nothing; `test_today_matches_runner` asserts equality AND source-text absence of `ZoneInfo` — PASSES; spot-check confirms both return `2026-06-23` |
| 8 | `write_in_progress()` is True only for a live + fresh pid; dead or stale pids read as False (D-01) | ✓ VERIFIED | `os.kill(pid, 0)` liveness probe (line 190); `age >= STALE_SECONDS` gate (line 174); `STALE_SECONDS = 600` module constant; `test_write_in_progress` covers three sub-cases: live+fresh → True, dead pid 99999999 → False, live+stale (>660s) → False — all PASS |

**Score:** 8/8 truths verified (automated)

---

### Required Artifacts

| Artifact | Minimum Lines | Actual Lines | Status | Details |
|----------|--------------|-------------|--------|---------|
| `scripts/dashboard.py` | 50 | 116 | ✓ VERIFIED | Exports `app` (Flask) and `HOST = "127.0.0.1"`; loopback-only `app.run`; `--port`/`DASHBOARD_PORT` override; auto-open; no write path |
| `scripts/dashboard_data.py` | 80 | 245 | ✓ VERIFIED | Exports `read_json`, `read_sheet_rows`, `today_str`, `write_in_progress`, `last_updated_hhmm`; `LOCK_DIR`, `STALE_SECONDS = 600` module-level constants; no write path |
| `scripts/templates/base.html` | 30 | 75 | ✓ VERIFIED | Contains `data-theme="dark"`, Pico.css CDN link, `{% block content %}`, `{% block scripts %}`, `write_in_progress` conditional, `last_updated` label, Calibration/Line-changes/Live stub tabs with `aria-disabled="true"` |
| `scripts/templates/index.html` | 5 | 11 | ✓ VERIFIED | `{% extends "base.html" %}` at line 1; fills `{% block content %}` |
| `scripts/test_dashboard.py` | 60 | 132 | ✓ VERIFIED | Defines `test_flask_serves`, `test_route_index`, `test_loopback_only`; no `flask.__version__`; no `0.0.0.0` |
| `scripts/test_dashboard_data.py` | 80 | 329 | ✓ VERIFIED | Defines all five required test methods; imports `WorkbookAccessError` from `workbook_io`; uses `TemporaryDirectory`; mtime+sha256 assertions present |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|-----|-----|--------|---------|
| `dashboard.py` | `dashboard_data.write_in_progress / last_updated_hhmm` | computed per request, passed to `render_template` | ✓ WIRED | Lines 62-63: `write_in_progress=dashboard_data.write_in_progress(), last_updated=dashboard_data.last_updated_hhmm()` |
| `dashboard.py` | `127.0.0.1` | `app.run(host=HOST, ...)` loopback-only bind | ✓ WIRED | `HOST: str = "127.0.0.1"` line 27; `app.run(host=HOST, ...)` line 96; grep for `0.0.0.0`/`host=""` returns nothing |
| `templates/index.html` | `templates/base.html` | Jinja extends | ✓ WIRED | Line 1: `{% extends "base.html" %}` |
| `dashboard_data.py` | `workbook_io.safe_load_workbook` | lock-aware `read_only=True` load | ✓ WIRED | Line 107: `wb = safe_load_workbook(Path(xlsx), read_only=True, data_only=True)` |
| `dashboard_data.py` | `locks/*.xlsx.lock` | pid liveness via `os.kill(pid, 0)` + age < 600 | ✓ WIRED | `LOCK_DIR.glob("*.xlsx.lock")` (line 162); `os.kill(pid, 0)` (line 190); `age >= STALE_SECONDS` gate (line 174) |

---

### Data-Flow Trace (Level 4)

`dashboard.py`'s index route calls `write_in_progress()` and `last_updated_hhmm()` — both read from filesystem sources, not from hardcoded stubs.

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|--------------|--------|--------------------|--------|
| `dashboard.py` index route | `write_in_progress` | `LOCK_DIR.glob("*.xlsx.lock")` + `os.kill` liveness | Yes — reads live lock files, degrades to `False` when none exist | ✓ FLOWING |
| `dashboard.py` index route | `last_updated` | `RUN_LOG_JSONL` last line `["timestamp"]` | Yes — reads the real run log; returns `None` when log absent (correct empty state for Phase 1 shell) | ✓ FLOWING |

Note: Phase 1 ships the shell only — the Today/Slips/History data tables are Phase 2. The index template's `{% block content %}` renders a placeholder heading, which is the designed state for this phase.

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `test_flask_serves` — Flask binds 127.0.0.1 and serves HTTP 200 on Python 3.14.0a2 | `cd scripts && python3 -m unittest test_dashboard -v` | "Ran 3 tests in 0.880s: OK" | ✓ PASS |
| `test_route_index` — GET / via test client returns 200 | Same run | PASS (status 200, body 2682 bytes, contains `data-theme` and `pico`) | ✓ PASS |
| `test_loopback_only` — `dashboard.HOST == "127.0.0.1"` and socket bind confirms loopback | Same run | PASS | ✓ PASS |
| All five DASH-04/D-01/D-02 data-layer tests | `cd scripts && python3 test_dashboard_data.py` | "Ran 5 tests in 5.112s: OK" | ✓ PASS |
| `dashboard.HOST` and `app` importable | `python3 -c "import dashboard; print(dashboard.HOST, type(dashboard.app).__name__)"` | `127.0.0.1 Flask` | ✓ PASS |
| `today_str()` matches naive local datetime | `python3 -c "import dashboard_data; ..."` | Both return `2026-06-23` | ✓ PASS |

---

### Requirements Coverage

| Requirement | Plan | Description | Status | Evidence |
|-------------|------|-------------|--------|----------|
| DASH-01 | 01-03 | Operator can launch the dashboard with one command and open it at a localhost URL | ✓ SATISFIED | `dashboard.py` exists; `main()` starts Flask on 127.0.0.1; `test_route_index` passes (GET / → 200) |
| DASH-02 | 01-01 | Dashboard runs on system Python 3.14 — Flask verified at setup | ✓ SATISFIED | `test_flask_serves` does a live TCP bind+GET on 3.14.0a2 and passes |
| DASH-03 | 01-03 | Dashboard binds to `127.0.0.1` only | ✓ SATISFIED | `HOST = "127.0.0.1"` constant; `app.run(host=HOST)`; no `0.0.0.0`/`""` in codebase; `test_loopback_only` passes; external network isolation is UNCERTAIN (human test required) |
| DASH-04 | 01-02 | Data layer reads without writing; tolerates locked workbook mid-write | ✓ SATISFIED | `read_only=True, data_only=True`; no write path (grep clean); all five data-layer tests pass |

All four Phase 1 requirements are covered. No orphaned REQUIREMENTS.md entries for this phase — traceability table maps DASH-01..04 → Phase 1 (Complete).

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `dashboard_data.py` | 131 | `except (WorkbookAccessError, FileNotFoundError, Exception):` — bare `Exception` catch-all masks any reader bug as "locked" (CR-01 from 01-REVIEW.md) | ⚠️ Warning | D-01 contract (never raise on locked workbook) is satisfied. The risk is that a future bug in the reader body (KeyError, AttributeError, openpyxl schema regression) is silently returned as `None` — indistinguishable from a genuine lock. Does NOT affect this phase's goal. Documented in 01-REVIEW.md; recommended fix is to narrow to `(WorkbookAccessError, FileNotFoundError, OSError, zipfile.BadZipFile)` and let unexpected exceptions surface. |
| `dashboard_data.py` | 128 | `dict(zip(headers, row))` — duplicate column headers silently overwrite earlier values (WR-01 from 01-REVIEW.md) | ⚠️ Warning | No impact in Phase 1 (no data table rendering). Becomes a risk in Phase 2 when `read_sheet_rows` drives rendered views over wide workbook sheets with potential blank/duplicate header cells. |
| `dashboard.py` | 92 | `threading.Timer(1.0, ...)` started before `app.run` — timer fires even if bind fails, opening browser to a port nobody is serving (WR-04 from 01-REVIEW.md) | ⚠️ Warning | Cosmetic nuisance, not a correctness defect; port-conflict path still fails fast with a clear message. |

No `TBD`, `FIXME`, or `XXX` debt markers found in any phase file. No `return null`, `return {}`, `return []` stubs in rendering paths. No hardcoded empty props passed to templates.

---

### Human Verification Required

#### 1. Browser auto-open and visual shell rendering

**Test:** Run `cd scripts && python3 dashboard.py` and observe.
**Expected:** Browser opens to http://127.0.0.1:8787 within ~1 second; dark Pico.css theme; nav shows Today / Slips / History as active links and Calibration / Line-changes / Live as greyed inert stubs; badge area is empty (no writes in progress); no JavaScript errors in browser console.
**Why human:** Browser auto-open, visual theme correctness, and nav/stub rendering cannot be verified by grep or test-client — requires a running process and a display.

#### 2. Network isolation — loopback only, not reachable from another machine

**Test:** From a second machine on the same LAN while the dashboard is running, attempt `curl http://<mac-ip>:8787` (substituting the Mac's LAN IP address for `<mac-ip>`).
**Expected:** Connection refused or connection timeout — the dashboard must NOT respond from a non-loopback address.
**Why human:** `dashboard.HOST == "127.0.0.1"` and the bound socket probe (both VERIFIED programmatically) are necessary but not sufficient — only a real external network probe proves the OS-level loopback isolation, which is the DASH-03 security claim.

---

### Gaps Summary

No automated gaps. All 8 must-haves are VERIFIED. The two items above are the only outstanding checks, and both require physical/visual human action. The three warnings from 01-REVIEW.md (CR-01, WR-01, WR-04) are quality-improvement candidates for Phase 2 or a follow-up plan — none of them block the Phase 1 goal.

---

_Verified: 2026-06-23T22:10:00Z_
_Verifier: Claude (gsd-verifier)_
