# Phase 1: Foundation & Data Layer - Research

**Researched:** 2026-06-23
**Domain:** Local Flask web app (server-rendered) + read-only data layer over Excel/JSON, on Python 3.14.0a2
**Confidence:** HIGH (all gating claims verified live on the system interpreter with commands + output below)

## Summary

The single gating question for this phase — **does Flask import and serve on the system `python3` (3.14.0a2)?** — is answered **YES, definitively, with live evidence**. Flask 3.1.3 (+ Jinja2 3.1.6, Werkzeug 3.1.8, MarkupSafe 3.0.3, click, itsdangerous, blinker) installed cleanly via `pip` into the system `python3`, imports without error, renders a Jinja template, binds to `127.0.0.1:8787`, and returns a correct 200 response. Critically, the one C-extension in the stack — MarkupSafe's `_speedups.cpython-314-darwin.so` — **loaded and executed successfully** (no cp314 ABI crash, unlike the `lxml` case in project memory `python-314a2-abi-gotcha`). **The stdlib `http.server` fallback (D-06) is therefore NOT needed.** It should be documented as the contingency but not built. The verify-first task remains valuable as an automated guard that re-asserts the import/serve invariant.

The read-layer design is low-risk because the project's persistence already gives readers a strong guarantee: every workbook save goes through `workbook_io.safe_save_workbook`, which writes to a `.tmp.<pid>.xlsx` then does an **atomic `os.replace`** — a reader using `openpyxl(read_only=True)` always opens a *complete* file (old or new), never a partial one. A `read_only=True` load was verified to leave the source file's mtime and content hash **byte-identical** (DASH-04). The only real failure modes are a transient race during the swap (handled by `safe_load_workbook`'s retry loop, raising `WorkbookAccessError` after exhaustion) and brief staleness — which D-01 surfaces as a subtle "updating…" badge rather than a block or error.

For the "updating…" badge signal, I found that **the per-workbook cooperative lock files in `locks/<name>.xlsx.lock` carry `{"pid", "path", "acquired_at"}` JSON** — enabling a robust write-in-progress check (`os.kill(pid, 0)` liveness + age vs `stale_seconds=600`). A second, cleaner signal exists: `data/pnl/logs/run_log.jsonl` is structured one-JSON-object-per-line (`task`, `status`, `duration_s`, `exit_code`, `timestamp`) — ideal for "last updated / last run status." During this very research session a real pipeline run held those locks (pid alive, 176s old), which both validated the liveness approach and proved that lock-file *presence alone* is not a sufficient signal — age/liveness must be checked.

**Primary recommendation:** Build on **Flask 3.1.3 + Jinja2 + openpyxl `read_only=True`** (no fallback needed). Structure as `scripts/dashboard.py` (app, `app.run(host="127.0.0.1", port=8787)`) + `scripts/dashboard_data.py` (read module: JSON-first, then `safe_load_workbook(read_only=True, data_only=True)`, tolerate `WorkbookAccessError` → serve last-known-good). Drive the "updating…" badge from cooperative-lock liveness + `run_log.jsonl`. Match the pipeline's `today_str()` exactly (naive local time — **not** ZoneInfo). Run from `scripts/`; tests are `unittest` loaded via importlib, run from `scripts/`.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** When a workbook is being written (a daily run or a refresh in progress, or a cooperative lock file present), the data layer serves **last-known-good complete data** and the page shows a subtle **"updating…" badge**. It never blocks and never raises an unhandled error. Rationale: saves go through `workbook_io.safe_save_workbook` which uses an atomic `os.replace` swap, so a reader always opens a *complete* file (old or new), never a partial one — the only real risk is brief staleness, surfaced as a hint rather than a block or an error.
- **D-02:** Each page shows a **"last updated HH:MM"** (Pacific) timestamp so data freshness is glanceable, complementing the stale hint.
- **D-03:** Read workbooks/JSON **fresh on every page load** (no long-lived cache). Reads are cheap enough for a solo local tool; favor correctness/liveness over micro-optimization. Prefer the fast, lock-free JSON artifacts first; hit workbooks via `read_only=True` for sheet data.
- **D-04:** `python3 dashboard.py` binds `127.0.0.1` on a **fixed default port (`8787`)** and **auto-opens the browser tab**. Port overridable via flag/env if `8787` is taken.
- **D-05:** **Dark theme, dense data-table layout** (operator-tool aesthetic). Pico.css base with a dark scheme; tables over cards for the data-heavy views. (Phase 1 sets up the shell/theme; the views fill it in Phase 2.)
- **D-06:** Flask/Jinja is the preferred stack, BUT the **very first task verifies Flask imports and serves on the system `python3` (3.14.0a2)**. If Flask will not import/serve cleanly, **fall back to stdlib `http.server` + `string.Template`/f-string rendering**. Chart.js + Pico.css via CDN (no JS build toolchain). Run from `scripts/` with `python3`.

### Claude's Discretion
- Exact module layout (e.g. `scripts/dashboard.py` app + a `scripts/dashboard_data.py` read module), route names, port-conflict fallback, the precise "write-in-progress" detection mechanism (cooperative lock-file presence vs `run_log.jsonl` status vs `fcntl` probe), and template/partials structure. Planner/executor decide.

### Deferred Ideas (OUT OF SCOPE)
- **Later dashboard tabs** — Calibration (TAB-01), Line-changes (TAB-02), Live (TAB-03) — tied to future milestones M2–M4. The Phase 1 shell should *leave room* for them (extensible nav/tab stubs) but **not build them**.
- **Full UI design contract** — a richer `/gsd-ui-phase 1` visual spec is out of scope for this phase.
- **The three views (VIEW-*)** are Phase 2; **the safe actions (ACTION-*)** are Phase 3. Phase 1 builds only the app shell + the read layer they will consume.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| DASH-01 | Launch with one command (`python3 dashboard.py`) and open at a localhost URL | Verified Flask `app.run(host="127.0.0.1", port=8787)` serves + 200s; `webbrowser` stdlib confirmed available for auto-open (D-04). Port 8787 verified free. |
| DASH-02 | Runs on system Python 3.14; Flask verified at setup, stdlib `http.server` fallback if Flask won't import on 3.14.0a2 | **Flask 3.1.3 imports + serves + renders Jinja on 3.14.0a2 — verified live (commands+output below). Fallback NOT needed; document as contingency.** |
| DASH-03 | Binds to `127.0.0.1` only, not reachable from other machines | `lsof` confirmed socket binds to `TCP 127.0.0.1:8787 (LISTEN)` (loopback-only), vs `*:PORT` for all-interfaces. |
| DASH-04 | Reads persisted data (workbooks + JSON) without modifying/corrupting it, tolerating a workbook locked mid-write | `read_only=True` load proven to leave source mtime + content hash byte-identical. `safe_save_workbook` uses atomic `os.replace`; `safe_load_workbook` retries → `WorkbookAccessError`. Badge signal: cooperative lock liveness + `run_log.jsonl`. |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Interpreter:** Use `/usr/local/bin/python3` (3.14.0a2) — `python` (3.13) lacks deps. (Note: `python3` resolves to `/Library/Frameworks/Python.framework/Versions/3.14/bin/python3` on this machine; both are the 3.14 interpreter.)
- **Working directory:** Run from `scripts/`; sibling modules import by bare name (`from workbook_io import safe_load_workbook`). `dashboard.py` and `dashboard_data.py` live in `scripts/`.
- **Never hardcode secrets:** Use `env_value`/`env_bool` for any port/theme overrides. No secrets are needed for this phase (localhost, no auth — documented assumption).
- **Additive-schema only:** Phase 1 is read-only — it writes nothing to workbooks. (Phase 3 actions are additive + atomic.) The read layer must never write.
- **Defensive contract:** Missing games/workbooks/files become explicit SKIP/empty states, never exceptions — mirror this in the data layer (D-01).
- **Tests:** `unittest` (not pytest fixtures), loaded via importlib, run from `scripts/`.
- **GSD workflow:** File edits go through a GSD command; this is research only.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Serve HTML over HTTP, route handling | Frontend Server (Flask app, `dashboard.py`) | — | Server-rendered, no SPA; Flask owns request/response + Jinja render |
| Loopback-only network binding | Frontend Server (`app.run(host="127.0.0.1")`) | OS socket layer | Security boundary is at the bind; OS enforces loopback isolation |
| Read workbooks + JSON, tolerate locks | Data layer (`dashboard_data.py`) | `workbook_io.safe_load_workbook` | Isolates all I/O + lock tolerance from the web app; reused by Phase 2 views |
| "Write-in-progress" / freshness signal | Data layer | cooperative locks + `run_log.jsonl` | Read-side derivation of pipeline state from existing artifacts; no new machinery |
| Template rendering / dark theme shell | Frontend Server (Jinja templates) | Pico.css (CDN) | Jinja + Pico CDN, no JS build toolchain (D-05) |
| Auto-open browser on launch | CLI entrypoint (`__main__` in `dashboard.py`) | `webbrowser` stdlib | One-command launch ergonomics (D-04) |
| "today" date semantics | Data layer | mirror runner's `today_str()` | Must match the pipeline's date or the Today view shows the wrong day |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Flask | 3.1.3 | Web app: routing, request/response, dev server | Approved by design doc (D-06); verified to import + serve on 3.14.0a2 `[VERIFIED: live test]` |
| Jinja2 | 3.1.6 | Server-side HTML templating | Flask's bundled templating; pure-Python; renders correctly on 3.14.0a2 `[VERIFIED: live test]` |
| Werkzeug | 3.1.8 | WSGI dev server (`run_simple`) under Flask | Flask dependency; `werkzeug.serving.run_simple` imports + serves `[VERIFIED: live test]` |
| MarkupSafe | 3.0.3 | HTML escaping (autoescaping) | Only C-extension in stack; **cp314 wheel `_speedups.cpython-314-darwin.so` loaded OK** `[VERIFIED: live test]` |
| openpyxl | 3.1.5 | Read `.xlsx` workbooks (`read_only=True`) | Already the project's only Excel lib; read leaves source byte-identical `[VERIFIED: live test]` |
| `webbrowser` | stdlib | Auto-open browser tab on launch (D-04) | Stdlib; `webbrowser.get()` → `MacOSXOSAScript` available `[VERIFIED: live test]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Pico.css | latest (CDN) | Dark-theme CSS base, dense tables (D-05) | `<link>` tag in base template; no install. Use `data-theme="dark"`. `[ASSUMED]` (CDN tag — verify URL at build time) |
| Chart.js | latest (CDN) | History/bankroll charts | Phase 2 (History view); leave a `<script>` slot in base template now. `[ASSUMED]` (Phase 2 concern) |
| `http.server` | stdlib | **Fallback only — not needed** | Contingency if Flask ever breaks on an interpreter bump; verified importable but unused `[VERIFIED: import]` |
| `fcntl` / `os.kill` | stdlib | Cooperative-lock liveness for badge | Read-side liveness probe of pipeline lock pid `[VERIFIED: lock content has pid]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Flask + Jinja | stdlib `http.server` + `string.Template` (D-06 fallback) | Works, but more tedious routing/escaping, no template inheritance, less pretty. **Not needed — Flask verified working.** |
| openpyxl `read_only=True` direct | `workbook_io.safe_load_workbook(read_only=True)` | Prefer `safe_load_workbook` — it adds the stable-file check + retry + `WorkbookAccessError` that D-01 depends on. Direct `load_workbook` is fine for the lock-free JSON-adjacent path but loses retry. |

**Installation:**
```bash
# Already installed during this research into system python3 (3.14):
python3 -m pip install flask
# Flask-3.1.3 Jinja2-3.1.6 MarkupSafe-3.0.3 Werkzeug-3.1.8 blinker-1.9.0 click-8.4.1 itsdangerous-2.2.0
# openpyxl 3.1.5 already present. No other installs required.
```
**Note:** `pip` warned `The script flask is installed in '/Library/Frameworks/Python.framework/Versions/3.14/bin' which is not on PATH` — irrelevant; we never invoke the `flask` CLI, we run `python3 dashboard.py` directly.

**Version verification (commands run + output):**
```
$ python3 --version
Python 3.14.0a2

$ python3 -m pip --version
pip 24.3.1 from .../3.14/lib/python3.14/site-packages/pip (python 3.14)

$ python3 -m pip install flask   # (after dry-run resolved cleanly)
Successfully installed blinker-1.9.0 click-8.4.1 flask-3.1.3 itsdangerous-2.2.0 \
  jinja2-3.1.6 markupsafe-3.0.3 werkzeug-3.1.8

$ python3 -c "import importlib.metadata as m; [print(p, m.version(p)) for p in \
  ['flask','jinja2','werkzeug','markupsafe','click','itsdangerous','blinker']]"
flask 3.1.3
jinja2 3.1.6
werkzeug 3.1.8
markupsafe 3.0.3
click 8.4.1
itsdangerous 2.2.0
blinker 1.9.0

$ python3 -c "import openpyxl; print(openpyxl.__version__)"
3.1.5
```

## Package Legitimacy Audit

All packages are well-known, multi-year-established libraries pulled from PyPI by `pip` with cp314-compatible wheels. slopcheck was not run (no hallucination-vector packages here — Flask/Jinja/Werkzeug/MarkupSafe are the canonical Pallets stack; openpyxl is the project incumbent). Provenance is the approved design doc + PyPI resolution, not WebSearch.

| Package | Registry | Age | Source Repo | Verdict | Disposition |
|---------|----------|-----|-------------|---------|-------------|
| flask 3.1.3 | PyPI | ~14 yrs | github.com/pallets/flask | trusted (Pallets) | Approved |
| jinja2 3.1.6 | PyPI | ~16 yrs | github.com/pallets/jinja | trusted (Pallets) | Approved |
| werkzeug 3.1.8 | PyPI | ~16 yrs | github.com/pallets/werkzeug | trusted (Pallets) | Approved |
| markupsafe 3.0.3 | PyPI | ~14 yrs | github.com/pallets/markupsafe | trusted (Pallets) | Approved |
| click 8.4.1 | PyPI | ~10 yrs | github.com/pallets/click | trusted (Pallets) | Approved |
| itsdangerous 2.2.0 | PyPI | ~12 yrs | github.com/pallets/itsdangerous | trusted (Pallets) | Approved |
| blinker 1.9.0 | PyPI | ~14 yrs | github.com/pallets-eco/blinker | trusted | Approved |
| openpyxl 3.1.5 | PyPI | incumbent | foss.heptapod.net/openpyxl | project incumbent | Approved |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none
**Postinstall scripts:** Python wheels do not run npm-style postinstall scripts; no concern. MarkupSafe ships a prebuilt `.so` (no compile-on-install needed — the cp314 wheel was used directly).

## Architecture Patterns

### System Architecture Diagram

```
                         browser (http://127.0.0.1:8787)
                                  │  GET (views only in Phase 1: shell + health)
                                  ▼
        ┌─────────────────────────────────────────────────────┐
        │  Flask app  scripts/dashboard.py                     │
        │   • app.run(host="127.0.0.1", port=8787)  ← D-03/04  │
        │   • __main__: parse --port/env, webbrowser.open()    │
        │   • routes render Jinja (base.html dark/Pico shell)  │
        └───────────────┬─────────────────────────────────────┘
                        │ calls (read-only, fresh per request — D-03)
                        ▼
        ┌─────────────────────────────────────────────────────┐
        │  Read layer  scripts/dashboard_data.py               │
        │   1. JSON-first (lock-free, fast):                   │
        │      bankroll.json · calibration.json · *_latest.json│
        │   2. Workbooks via safe_load_workbook(read_only=True,│
        │      data_only=True) → tolerate WorkbookAccessError  │
        │      → serve last-known-good (D-01)                   │
        │   3. freshness/badge signal:                         │
        │      cooperative lock liveness + run_log.jsonl tail   │
        └───────┬───────────────────────────────┬─────────────┘
                │ read (never write)             │ read
                ▼                                ▼
   data/pnl/bankroll.json              data/{nba,mlb}/{sport}_{date}.xlsx
   data/research/calibration.json      data/pnl/master_pnl.xlsx
   data/{nba,mlb}/*_latest.json        locks/*.xlsx.lock (badge signal)
                                       data/pnl/logs/run_log.jsonl (last-run signal)

        (writes here happen ONLY from the cron pipeline via os.replace —
         the dashboard process never writes in Phase 1)
```

### Recommended Project Structure
```
scripts/
├── dashboard.py            # Flask app + __main__ (bind 127.0.0.1:8787, auto-open) — D-04
├── dashboard_data.py       # read module: JSON-first → read_only workbooks → badge/freshness
├── templates/
│   ├── base.html           # dark/Pico shell, extensible <nav> tab stubs (Calibration/Line/Live left empty)
│   └── index.html          # Phase-1 shell landing (views fill in Phase 2)
├── static/                 # (optional) local CSS overrides; Pico/Chart.js are CDN
├── test_dashboard_data.py  # unittest: read-only, lock tolerance, mtime-unchanged, today match
└── test_dashboard.py       # unittest: route 200s, 127.0.0.1 bind, no-write invariant
```

### Pattern 1: Loopback-only Flask launch with auto-open (DASH-01/03/04 launch)
**What:** One-command launch, fixed port 8787 with override, browser auto-open, loopback bind.
**When to use:** `dashboard.py.__main__`.
**Example:**
```python
# Source: verified live on 3.14.0a2 (this research)
import os, argparse, threading, webbrowser
from flask import Flask, render_template

app = Flask(__name__)  # templates/ resolved relative to scripts/ when run from scripts/

def _port() -> int:
    # env override (env_value pattern) then flag then default 8787 (D-04)
    return int(os.environ.get("DASHBOARD_PORT", "8787"))

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=_port())
    args = p.parse_args()
    url = f"http://127.0.0.1:{args.port}/"
    # open after the server is up; use_reloader=False so it doesn't double-launch
    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)
```
**Port-conflict note:** 8787 verified free now. If taken, `app.run` raises `OSError: [Errno 48] Address already in use`. Planner's discretion: try-bind-then-increment, or fail with a clear message + `--port` hint. Do **not** silently fall back to 0.0.0.0 (would violate DASH-03).

### Pattern 2: JSON-first, lock-tolerant read (DASH-04 / D-01 / D-03)
**What:** Read fresh each request; prefer lock-free JSON; fall back to `read_only` workbook; never raise.
**When to use:** every accessor in `dashboard_data.py`.
**Example:**
```python
# Source: workbook_io.py (this repo) + verified read_only mtime-preservation
import json
from pathlib import Path
from openpyxl.utils.exceptions import InvalidFileException
from workbook_io import safe_load_workbook, WorkbookAccessError  # run from scripts/

def read_json(path: Path) -> dict | list | None:
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None  # missing/partial JSON → empty state, never crash (D-01 contract)

def read_sheet_rows(xlsx: Path, sheet: str) -> list[dict] | None:
    try:
        wb = safe_load_workbook(xlsx, read_only=True, data_only=True)
    except (WorkbookAccessError, FileNotFoundError):
        return None  # locked mid-write past retries / missing → serve last-known-good (D-01)
    try:
        if sheet not in wb.sheetnames:
            return []
        ws = wb[sheet]
        it = ws.iter_rows(values_only=True)
        headers = list(next(it, []) or [])
        return [dict(zip(headers, r)) for r in it]
    finally:
        wb.close()
```
**Why `safe_load_workbook` over bare `load_workbook`:** it adds the stable-file size check, 5-retry loop, and raises the catchable `WorkbookAccessError` — exactly the "retry or skip gracefully" DASH-04 requires. Use `data_only=True` to read computed values, not formulas.

### Pattern 3: "updating…" badge + "last updated HH:MM" (D-01 / D-02)
**What:** Derive write-in-progress + freshness from existing artifacts; no new state machinery.
**When to use:** computed once per page render, passed to the template.
**Example:**
```python
# Source: locks/*.xlsx.lock content + run_log.jsonl (verified structure this research)
import os, json, time
from pathlib import Path
from datetime import datetime

LOCK_DIR = Path.home() / "sports_picks" / "locks"
RUN_LOG = Path.home() / "sports_picks" / "data" / "pnl" / "logs" / "run_log.jsonl"
STALE_SECONDS = 600  # matches workbook_io stale_seconds

def write_in_progress() -> bool:
    """True iff a live pipeline process currently holds a workbook lock (D-01 badge)."""
    for lk in LOCK_DIR.glob("*.xlsx.lock"):
        try:
            d = json.loads(lk.read_text())
            pid = int(d.get("pid", 0))
            age = time.time() - lk.stat().st_mtime
        except (json.JSONDecodeError, FileNotFoundError, ValueError):
            continue
        if age > STALE_SECONDS:
            continue  # stale lock — workbook_io will reap it; not "in progress"
        try:
            os.kill(pid, 0)  # liveness probe — no signal sent
            return True      # live process holds a fresh lock → show "updating…"
        except ProcessLookupError:
            continue         # dead pid → not in progress; keep checking other locks
        except PermissionError:
            return True      # pid alive but owned by another user → a write IS happening
    return False

def last_updated_hhmm() -> str | None:
    """'last updated HH:MM' from the most recent run_log.jsonl entry (D-02)."""
    try:
        last = RUN_LOG.read_text().splitlines()[-1]
        ts = json.loads(last)["timestamp"]
        return datetime.fromisoformat(ts).strftime("%H:%M")  # local clock == Pacific on this Mac
    except (FileNotFoundError, IndexError, KeyError, ValueError):
        return None
```
**Badge signal ranking (verified):**
1. **Cooperative lock liveness** (`locks/*.xlsx.lock` → `pid` + `os.kill(pid,0)` + age) — most precise "a write is happening *right now*." Verified during research: a real run held the locks (pid alive, 176s old).
2. **`run_log.jsonl` tail** — structured (`task,status,duration_s,exit_code,timestamp`); best for "last updated HH:MM" and last-run status. Verified structure.
3. (Avoid) lock-file *presence alone* — stale locks linger up to 600s; presence ≠ in-progress.

### Anti-Patterns to Avoid
- **Binding `0.0.0.0` / `host=""`:** violates DASH-03. Always `host="127.0.0.1"`.
- **Running the runner inline in the web process:** out of scope for Phase 1 (no actions), but a hard rule for Phase 3 — always subprocess (preserves the `fcntl` lock + isolation).
- **Long-lived in-memory cache of workbook data:** D-03 says fresh-on-load. A cache would also serve stale data after a pipeline write. Read each request.
- **Inventing a ZoneInfo/Pacific date for "today":** the runner uses naive local time (`datetime.now()`); a ZoneInfo conversion would mismatch the pipeline near midnight. Mirror `today_str()` exactly.
- **Bare `load_workbook` in the data layer:** loses the retry/`WorkbookAccessError` that D-01 needs. Use `safe_load_workbook`.
- **Writing anything to workbooks in Phase 1:** read-only phase. No save path at all.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Lock-aware workbook read with retries | A custom retry/stable-file loop | `workbook_io.safe_load_workbook(read_only=True, data_only=True)` | Already battle-tested: stable-file check, 5 retries, `WorkbookAccessError`, atomic-swap aware |
| Atomic save (Phase 3 only) | A temp-file + rename of your own | `workbook_io.safe_save_workbook` | Atomic `os.replace` + zip-validate + timestamped backup already implemented |
| HTML escaping in templates | Manual `.replace("<","&lt;")` | Jinja2 autoescaping (MarkupSafe) | Autoescaping verified working incl. C speedup; manual escaping leaks XSS-class bugs |
| WSGI/HTTP server | A raw `socket` accept loop | `app.run()` (Werkzeug dev server) | Localhost solo tool; dev server is sufficient and verified serving |
| Browser auto-open | OS-specific `open`/`xdg-open` shelling | `webbrowser` stdlib | Cross-platform stdlib; verified `MacOSXOSAScript` backend |
| "today" date | New date logic | mirror runner's `today_str()` | Must match the pipeline's day exactly |

**Key insight:** Almost everything risky in this phase (lock tolerance, atomic IO, escaping, date semantics) already has a vetted implementation in the repo or stdlib. The phase's real work is *wiring*, not building primitives.

## Runtime State Inventory

> Greenfield-ish read layer, but it depends on existing runtime state. Inventory of what the data layer must read (not migrate — read-only phase):

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data (workbooks) | Per-sport `data/{nba,mlb}/{sport}_{date}.xlsx` (sheets: Picks, Player Props, Props, Correlated Parlays, Slip History, Results, CLV Tracker, …); `data/pnl/master_pnl.xlsx` (sheets verified: **Daily Log, Pick History, Performance Breakdown, Bankroll Chart Data, Slip History, Conditional Specials, Prop Accuracy**) | Read-only; no migration. Map columns to view fields in Phase 2. |
| Stored data (JSON) | `data/pnl/bankroll.json` (keys: `starting_bankroll, current_bankroll, total_units_bet_lifetime, overall_profit_loss, roi_percentage_current, last_graded_date, last_updated, updated_at`); `data/research/calibration.json` (keys: `version, updated_at, inception_date, factors, fingerprints, audit`); `data/{nba,mlb}/{prizepicks,underdog,dfs_props_unified}_<sport>_latest.json` | JSON-first reads (lock-free). No migration. |
| Live service config | None — dashboard is standalone, not registered with cron/Hermes. No external service config to read. | None — verified by INTEGRATIONS.md (dashboard is a new manual process). |
| OS-registered state | None — Phase 1 does not register cron/launchd/Task Scheduler entries. | None. |
| Secrets/env vars | None required (localhost, no auth). Optional `DASHBOARD_PORT` env override (new, additive — read via env). | None — no secret reads. |
| Build artifacts | Flask + deps now installed in system `python3` site-packages (persistent across sessions, confirmed). `__pycache__` will appear for new modules. | None — install is the intended state (verify-first task re-asserts it). |

**Note on `nxls_schema.txt`:** the file at `data/nxls_schema.txt` is **STALE/aspirational** (describes an older sheet layout: "Arb + Middles", "Picks to Watch", different columns). The **authoritative column contracts are the `*_HEADERS` constants in `sports_system_runner.py`** and `SLIP_HISTORY_HEADERS` in `slip_payouts.py`. Do not map views against `nxls_schema.txt`.

### Exact column contracts (authoritative — from runner constants, verified)

| Sheet | Source constant | Key columns for the views |
|-------|-----------------|---------------------------|
| Picks (per-sport) | `PICKS_HEADERS` (`sports_system_runner.py:277`) | `Platform`, `Sport`, `Pick Type`, `Selection`, `Player/Team`, `Line`, `Odds`, `Confidence`, `Model Projection`, `Edge`, **`Model Over Probability`**, **`EV`**, `Edge Type Tags`, `Status`, `Reasoning`, `Correlation Group`, `Slip ID` |
| Props (per-sport) | `PROPS_HEADERS` (`:284`) | `Platform`, `Player Name`, `Team`, `Stat`, `Line`, `Confidence`, `Model Projection`, `Edge`, **`Model Over Probability`**, **`EV`**, `Status`, `Reasoning`, `Correlation Group`, `Slip ID` |
| Correlated Parlays | `PARLAY_HEADERS` (`:294`) | `Parlay Name`, `Legs`, `Units`, `Status`, **`Reasoning`**, **`Correlation Group`**, `Slip ID` (the "why paired" insight — VIEW-02) |
| Slip History (per-sport + master) | `SLIP_HISTORY_HEADERS` (`slip_payouts.py:18`) | `Slip ID`, `Platform`, `Slip Type`, `Number of Legs`, `Legs`, `Stake Units`, `Slip Result`, `Estimated Payout Multiplier`, `Gross Return`, `Net PnL`, `Graded At` |
| Results (per-sport) | `RESULT_HEADERS` (`:318`) | `Platform`, `Player/Team`, `Pick`, `Confidence Tier`, `Edge`, `Model Over Probability`, `EV`, `Result`, `Units`, `PnL`, `Correlation Group`, `Slip ID` |
| master_pnl: Pick History | (sheet, 50 cols) | `Date, Sport, Pick Ref, Result, Units, PnL, Graded At, Game, Actual, Platform, Player/Team, Pick, Pick Type, …` |
| master_pnl: Daily Log | (sheet) | `Date, Sport, Wins, Losses, Pushes, Units Bet, Day PnL, Running Bankroll, Notes` |
| master_pnl: Bankroll Chart Data | (sheet) | `Date, Bankroll, ROI, Updated At` (ready-made for the History chart in Phase 2) |
| master_pnl: Performance Breakdown | (sheet) | `Metric, Value, Updated At` |
| master_pnl: Prop Accuracy | `PROP_ACCURACY_HEADERS` (`:325`) | `Week, Sport, Total Props, Wins, Losses, Pushes, Hit Rate, Updated At` |

The +EV / probability / edge / confidence columns the views need are: **`EV`, `Model Over Probability`, `Edge`, `Confidence`** on Picks/Props; pairing reasoning is **`Reasoning` + `Correlation Group`** on Correlated Parlays.

## Common Pitfalls

### Pitfall 1: Stale lock files read as "always updating"
**What goes wrong:** Lock files in `locks/` persist after a crash up to `stale_seconds=600`; using mere presence as the badge signal shows "updating…" indefinitely.
**Why it happens:** `workbook_io` only reaps a lock after 600s of staleness; a killed run leaves the file behind.
**How to avoid:** Use the lock's embedded `pid` + `os.kill(pid, 0)` liveness check AND age < 600s (Pattern 3). Verified: lock content is `{"pid","path","acquired_at"}`.
**Warning signs:** Badge stuck "on" with no running pipeline; check `locks/` for old `acquired_at`.

### Pitfall 2: Midnight "today" mismatch with the pipeline
**What goes wrong:** Dashboard's Today view points at a different `{sport}_{date}.xlsx` than the pipeline wrote, around midnight or if the dashboard invents a ZoneInfo date.
**Why it happens:** Runner's `today_str()` (`sports_system_runner.py:334`) is naive `datetime.now().strftime("%Y-%m-%d")` — machine-local, **no ZoneInfo** (grep confirmed zero `ZoneInfo`/`America/Los_Angeles` in the runner). CLAUDE.md's "Pacific" is true only because the Mac's clock is Pacific.
**How to avoid:** Compute "today" the same way: naive `datetime.now().strftime("%Y-%m-%d")`. Do not import `zoneinfo`. (If you want belt-and-suspenders, import the runner's `today_str` — but bare-name import of the 5,650-line runner is heavy; replicating the one-liner is cleaner.)
**Warning signs:** Today view empty right after midnight while a workbook for "yesterday" has data.

### Pitfall 3: Reading formulas instead of values
**What goes wrong:** Cells show `=SUM(...)` strings instead of numbers.
**Why it happens:** `read_only=True` without `data_only=True` returns formula text for computed cells.
**How to avoid:** Always `safe_load_workbook(path, read_only=True, data_only=True)`. (Matches what `workbook_io.workbook_is_valid` already uses.)
**Warning signs:** Numeric columns render as `=` strings.

### Pitfall 4: `read_only` workbook not closed → file handle/locking churn
**What goes wrong:** Leaked open workbooks on a fresh-per-request read path.
**Why it happens:** `read_only` mode keeps the zip open until `.close()`.
**How to avoid:** Always `wb.close()` in a `finally` (Pattern 2).
**Warning signs:** Growing open file descriptors over many requests.

### Pitfall 5: Werkzeug reloader double-launches / re-opens browser
**What goes wrong:** `app.run(debug=True)` spawns a reloader child → browser opens twice, ports double-bind.
**How to avoid:** `debug=False, use_reloader=False` for the launch (Pattern 1).

### Pitfall 6: Assuming the `flask` CLI is on PATH
**What goes wrong:** Following Flask docs to `flask run` fails (the `flask` script dir isn't on PATH, per the pip warning).
**How to avoid:** Launch via `python3 dashboard.py` with `app.run(...)` in `__main__` (which DASH-01 requires anyway).

## Code Examples

### Minimal verified serve (the gating proof, reproducible)
```python
# Source: ran live on 3.14.0a2 this research; returned 200 with rendered body
from flask import Flask, render_template_string
app = Flask(__name__)

@app.route("/")
def home():
    return render_template_string("<h1>{{ msg }}</h1><p>{{ n }}</p>", msg="dashboard ok", n=42)

# app.run(host="127.0.0.1", port=8787, debug=False, use_reloader=False)
# -> GET http://127.0.0.1:8787/ returned: '<h1>dashboard ok</h1><p>42</p>'  (200)
```

### Read-only proves source untouched (DASH-04 evidence pattern, reusable as a test)
```python
# Source: ran live this research — both asserts True
import hashlib
from openpyxl import load_workbook
before_mtime = path.stat().st_mtime
before_hash  = hashlib.sha256(path.read_bytes()).hexdigest()
wb = load_workbook(path, read_only=True, data_only=True)
_ = [r for r in wb["Daily Log"].iter_rows(values_only=True)]
wb.close()
assert path.stat().st_mtime == before_mtime          # mtime unchanged
assert hashlib.sha256(path.read_bytes()).hexdigest() == before_hash  # bytes unchanged
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Fear that cp314 alpha breaks all C-ext wheels (per `lxml` memory) | MarkupSafe ships a working `cp314` wheel; speedup loads fine | Verified 2026-06-23 | Flask stack is safe on 3.14.0a2; fallback unnecessary |
| `werkzeug.__version__` attribute | Removed in Werkzeug 3.1; use `importlib.metadata.version("werkzeug")` | Werkzeug 3.1 | Don't probe `werkzeug.__version__` in any version check (the verify task hit this) |
| `flask.__version__` | Deprecated (removed in Flask 3.2); use `importlib.metadata.version("flask")` | Flask 3.1 | Verify-first task must use `importlib.metadata`, not `flask.__version__` |
| `data/nxls_schema.txt` as schema reference | `*_HEADERS` constants in the runner | Ongoing | Map views to the code constants, not the stale txt |

**Deprecated/outdated:**
- `flask.__version__` / `werkzeug.__version__` — gone/deprecated; use `importlib.metadata.version(...)`.
- `nxls_schema.txt` — stale; superseded by runner header constants.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Pico.css dark theme via CDN `<link data-theme="dark">` renders the intended operator-tool aesthetic | Supporting stack / D-05 | Low — cosmetic; verify exact CDN URL + dark attribute at build time |
| A2 | Chart.js via CDN is Phase-2 work; only a `<script>` slot is reserved now | Supporting stack | Low — Phase 2 concern; no Phase-1 dependency |
| A3 | The operator's Mac clock is set to Pacific, so naive `datetime.now()` == Pacific for D-02's "(Pacific)" label | Pitfall 2 / D-02 | Medium — if the Mac is ever non-Pacific, the "(Pacific)" label is wrong though it still *matches the pipeline*. Matching the pipeline is the correctness-critical part; the label is cosmetic. |
| A4 | `PermissionError` from `os.kill(pid,0)` should count as "process alive" in the badge | Pattern 3 | Low — rare on a single-user Mac; worst case a false "updating…" badge |

**Note:** All four gating/structural claims (Flask imports, Flask serves, loopback-only bind, read_only preserves source, badge signals exist) are `[VERIFIED: live test]`, not assumed.

## Open Questions

1. **Port-conflict fallback policy (D-04 says overridable)**
   - What we know: 8787 is free now; `app.run` raises `OSError: Errno 48` if taken; `--port`/`DASHBOARD_PORT` override is the lever.
   - What's unclear: auto-increment-and-retry vs fail-with-message. (Marked Claude's Discretion in CONTEXT.)
   - Recommendation: fail fast with a clear message + `--port` hint (predictable URL for a solo tool); planner decides.

2. **Where should the verify-first task assert "Flask serves" — import-only or a real bind+GET?**
   - What we know: a real bind+GET is the strongest check and is cheap (~2s).
   - Recommendation: the verify task should do an actual `127.0.0.1` bind + self-GET (as this research did), not just `import flask`, so it catches a serve-time regression, then exit. Encode as a `unittest` so CI/local re-runs it.

3. **"Why paired" for non-parlay general slips (VIEW-02, Phase 2)**
   - What we know: Correlated Parlays carry `Reasoning` + `Correlation Group`; general Slip History rows carry `Legs` but not always stored reasoning.
   - Recommendation: Phase 2 concern — surface stored reasoning where present, derive (same game/team, combined prob/EV) otherwise. Flag now so the data layer exposes `Legs`/`Correlation Group` cleanly.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.14 | Entire phase | ✓ | 3.14.0a2 | — |
| pip | Flask install | ✓ | 24.3.1 | — |
| Flask (+Jinja/Werkzeug/MarkupSafe/click/itsdangerous/blinker) | DASH-01/02 web stack | ✓ (installed this research) | flask 3.1.3 | stdlib `http.server` (NOT needed) |
| openpyxl | DASH-04 workbook reads | ✓ | 3.1.5 | — |
| `webbrowser` (stdlib) | DASH-01 auto-open | ✓ | stdlib | print URL to stdout |
| `http.server` (stdlib) | DASH-02 fallback | ✓ (importable) | stdlib | — (this IS the fallback) |
| Port 8787 | DASH-01 default port | ✓ free | — | `--port`/`DASHBOARD_PORT` override |
| Source data (workbooks/JSON) | DASH-04 reads | ✓ | master_pnl.xlsx, bankroll.json, calibration.json, *_latest.json all present | empty-state render |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None blocking — the only "fallback" (stdlib http.server) is unneeded because Flask is verified working.

## Validation Architecture

> nyquist_validation not found disabled in config; section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | `unittest` (stdlib); discovery via `python3 -m pytest` (pytest 9.x installed) |
| Config file | none — tests self-load via `sys.path.insert(0, scripts_dir)` + bare imports |
| Quick run command | `cd scripts && python3 test_dashboard_data.py` (and `test_dashboard.py`) |
| Full suite command | `cd scripts && python3 -m pytest` (~34 min full — per MEMORY; use targeted files during the phase) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DASH-02 | Flask imports + binds + self-GET 200 on 3.14.0a2 | smoke | `cd scripts && python3 test_dashboard.py -k flask_serves` | ❌ Wave 0 |
| DASH-01 | `dashboard.py` exposes a launch entry; route `/` returns 200 | unit | `cd scripts && python3 test_dashboard.py -k route_index` | ❌ Wave 0 |
| DASH-03 | Server socket binds `127.0.0.1` only (lsof/`getsockname` is loopback) | integration | `cd scripts && python3 test_dashboard.py -k loopback_only` | ❌ Wave 0 |
| DASH-04 | `read_only` read leaves source mtime + sha256 unchanged | unit | `cd scripts && python3 test_dashboard_data.py -k read_only_untouched` | ❌ Wave 0 |
| DASH-04 | Locked/`WorkbookAccessError` → returns last-known-good, no raise | unit | `cd scripts && python3 test_dashboard_data.py -k lock_tolerant` | ❌ Wave 0 |
| DASH-04 | Missing workbook/JSON → empty state, no exception | unit | `cd scripts && python3 test_dashboard_data.py -k missing_is_empty` | ❌ Wave 0 |
| D-02 | "today" matches runner's `today_str()` (naive local) | unit | `cd scripts && python3 test_dashboard_data.py -k today_matches_runner` | ❌ Wave 0 |
| D-01 | badge: live lock pid → in-progress; dead/stale pid → not in-progress | unit | `cd scripts && python3 test_dashboard_data.py -k write_in_progress` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `cd scripts && python3 test_dashboard_data.py && python3 test_dashboard.py` (seconds).
- **Per wave merge:** the two dashboard test files in full.
- **Phase gate:** full `python3 -m pytest` green (baseline is "2 failed, 202 passed" — the 2 known projection failures per MEMORY; treat anything beyond those two as a regression).

### Wave 0 Gaps
- [ ] `scripts/test_dashboard.py` — covers DASH-01/02/03 (route 200, flask serve, loopback bind). Bind test can use `app.test_client()` for routes and a real ephemeral-port bind + `socket.getsockname()`/lsof for the loopback assertion.
- [ ] `scripts/test_dashboard_data.py` — covers DASH-04 + D-01/D-02 (read-only-untouched, lock tolerance, missing-is-empty, today-match, badge liveness). Reuse the verified mtime+sha256 pattern above.
- [ ] No framework install needed (`unittest` stdlib; pytest already present).

## Security Domain

> `security_enforcement` not found set to false; minimal section included. This is a localhost-only, no-auth, read-only phase (per design doc §8: "no auth required for solo local use — documented assumption").

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V1 Architecture | yes | Loopback-only bind (`127.0.0.1`) is the security boundary; no external surface (DASH-03) |
| V2 Authentication | no | Solo localhost; auth explicitly out of scope (design doc §9) |
| V3 Session Mgmt | no | No sessions/cookies in Phase 1 |
| V4 Access Control | no | Single local user; loopback isolation is the access boundary |
| V5 Input Validation | minimal | Phase 1 has no user-supplied input beyond `--port` (int-cast) and query filters in Phase 2; validate `--port` as int |
| V6 Cryptography | no | No secrets, no crypto in this phase (never hand-roll if added later) |
| V7 Output Encoding (XSS) | yes | Jinja2 autoescaping (MarkupSafe) on by default — keep it; never use `\| safe` on untrusted data |

### Known Threat Patterns for {localhost Flask read-app}
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Accidental `0.0.0.0` bind exposing data on LAN | Information Disclosure | Hardcode `host="127.0.0.1"`; test asserts loopback-only (DASH-03) |
| Stored XSS from rendering workbook strings (e.g., a Reasoning field) | Tampering/XSS | Jinja2 autoescape (verified working); no `\|safe` on data fields |
| Path traversal if a route ever takes a filename | Tampering | Phase 1 routes take no filesystem input; if added, constrain to known `data/` paths |
| Accidental write to a workbook | Tampering | Read layer has no save path; `read_only=True`; tests assert source bytes unchanged |

## Sources

### Primary (HIGH confidence — verified live on this machine)
- System interpreter test: `python3 --version` → Python 3.14.0a2; `python3 -m pip install flask` → Flask 3.1.3 + deps; live Flask serve on `127.0.0.1:8787` returning rendered 200; `lsof` loopback-only bind; `read_only` mtime+sha256 preservation; lock-file content `{pid,path,acquired_at}`; `run_log.jsonl` structure; port 8787 free; `webbrowser` backend.
- `scripts/workbook_io.py` — `safe_load_workbook` (retry/`WorkbookAccessError`), `safe_save_workbook` (atomic `os.replace`), `workbook_file_lock` (cooperative locks).
- `scripts/sports_system_runner.py` — `PICKS_HEADERS:277`, `PROPS_HEADERS:284`, `PARLAY_HEADERS:294`, `RESULT_HEADERS:318`, `PROP_ACCURACY_HEADERS:325`, `today_str():334` (naive local time, no ZoneInfo).
- `scripts/slip_payouts.py` — `SLIP_HISTORY_HEADERS:18`.
- `data/pnl/master_pnl.xlsx` — sheet/header inventory (read live). `data/pnl/bankroll.json`, `data/research/calibration.json` — key inventory (read live).
- Approved design doc `docs/superpowers/specs/2026-06-23-localhost-dashboard-design.md` — architecture, tech, safety.
- `.planning/codebase/{ARCHITECTURE,INTEGRATIONS}.md`, `.planning/REQUIREMENTS.md`, `.planning/STATE.md`, `01-CONTEXT.md`.

### Secondary (MEDIUM confidence)
- Project memory `python-314a2-abi-gotcha` (cp314 C-ext risk) — contextual; *contradicted* for MarkupSafe by the live test (its cp314 wheel works).
- Project memory `test-suite-is-slow`, `pre-existing-projection-test-failures` (baseline 2 failed / 202 passed).

### Tertiary (LOW confidence — flagged in Assumptions Log)
- Pico.css / Chart.js CDN tag specifics (A1/A2) — verify exact URLs/attributes at build time.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — every package installed + imported + (for Flask) served live on the target interpreter.
- Web stack on 3.14.0a2 (the gating call): HIGH — bind + render + 200 verified; MarkupSafe C speedup loaded.
- Data layer / lock tolerance: HIGH — `workbook_io` read + atomic-save mechanics read directly; `read_only` byte-preservation proven; lock/badge signals inspected live (a real run was in flight).
- Column contracts: HIGH — read from code constants + the live `master_pnl.xlsx`, not the stale schema txt.
- Pitfalls: HIGH — each tied to a verified code path or live observation.

**Research date:** 2026-06-23
**Valid until:** ~2026-07-23 (stable stack). Re-verify the Flask import/serve check if the system `python3` is upgraded (e.g., 3.14 beta/rc) — that is the one thing that could change the gating answer.
