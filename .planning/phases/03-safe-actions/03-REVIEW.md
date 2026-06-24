---
phase: 03-safe-actions
reviewed: 2026-06-24T00:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - scripts/dashboard_writes.py
  - scripts/dashboard.py
  - scripts/dashboard_data.py
  - scripts/test_dashboard_actions.py
  - scripts/templates/base.html
  - scripts/templates/slips.html
findings:
  critical: 0
  warning: 5
  info: 6
  total: 11
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-06-24
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Reviewed the Phase 3 "safe-actions" write surface added to the localhost Flask
dashboard: two additive workbook writers (`mark_placed`, `add_note`), the
`/action/refresh` task-spawn route, the `/api/status` poll endpoint, and the
slips/base templates that drive the action forms and flash banner.

The five named invariants hold under verification:

- **ACTION-04 (additive-only):** `mark_placed`/`add_note` only ever write the new
  columns `Placed`, `Placed At`, `Operator Note`. They resolve target cells by
  name via `ensure_ws_columns`, and the runner's `write_slip_history_rows`
  upsert touches only canonical columns 1–23 by index, so the operator's
  columns 24+ survive a grading rewrite in place. The grading-owned `Notes`
  column (index 23) is never written by either helper. Confirmed by
  `test_dashboard_actions.py` (all 9 tests pass).
- **Locked write path:** both helpers acquire `workbook_file_lock(master_path)`
  and save through `safe_save_workbook` (atomic temp-swap + zip validation +
  dated backup). Correct.
- **Lock-aware refresh:** `_runner_is_locked()` probes with
  `LOCK_EX | LOCK_NB` against the runner's real lock file (path verified to
  match `LOG_DIR/sports_system_runner.lock`) using read-only mode (does not
  truncate), and `action_refresh` whitelists via `ALLOWED_TASKS` *before* any
  spawn.
- **Autoescaping:** no `|safe`, no `autoescape false`, no
  `render_template_string`, no `Markup()` anywhere. All workbook-derived values
  and operator notes render through `{{ }}` with Jinja autoescaping on.
- **No hardcoded secrets:** `secret_key` reads `DASHBOARD_SECRET_KEY` env or
  falls back to `os.urandom(16)`; no credentials in source.

Remaining findings are robustness/quality concerns. The most material are the
TOCTOU race in the refresh route (WR-01) and the orphaned `Popen` child
(WR-02), neither of which corrupts the workbook but both of which can leave the
operator with a stuck or zombie process — the exact "stop babysitting it" pain
this milestone targets.

## Warnings

### WR-01: TOCTOU race between `_runner_is_locked()` check and subprocess spawn

**File:** `scripts/dashboard.py:167-180`
**Issue:** `action_refresh` checks `_runner_is_locked()` and then spawns the
runner in a separate code path. The probe acquires the lock with
`LOCK_EX | LOCK_NB`, immediately releases it (`LOCK_UN`), and returns. Between
that release and the child actually acquiring `LOCK_EX` (inside
`sports_system_runner.py:7937-7938`) there is a wide window. Two near-
simultaneous POSTs — or one POST while a cron run is *about to* start — can both
see "not locked" and both spawn a runner. The runner's own `fcntl.LOCK_EX` then
serializes them, but the second process blocks up to `wait_seconds` (and may
emit a `WorkbookAccessError` on per-workbook lock timeout), producing exactly
the kind of stuck/failed run this milestone is trying to eliminate. The probe is
also fundamentally check-then-act: releasing the lock before spawning means it
can never actually prevent a concurrent acquisition, only observe a *currently*
held one.
**Fix:** Accept that the probe is best-effort (it cannot close the race because
the dashboard is not the lock holder), and harden the spawned side so a queued
second run degrades cleanly: pass a short, explicit non-blocking expectation, or
have the route record an in-process "spawn pending" flag (with a short TTL)
checked alongside `_runner_is_locked()` so two dashboard clicks within the same
second cannot both spawn. At minimum, document that the lock probe is advisory
and that the runner's `LOCK_EX` is the real serialization point.

### WR-02: Spawned runner subprocess is never reaped (zombie child)

**File:** `scripts/dashboard.py:172-180`
**Issue:** The refresh thread's target is `lambda: subprocess.Popen([...])`.
`Popen` returns immediately, the lambda returns, and the daemon thread exits —
nothing ever calls `.wait()`/`.poll()` on the child. The runner takes minutes
(timeouts are 300–600 s). For the entire interval after the child exits and
before the Flask process itself exits, the child is a zombie (defunct) reaped
only when the dashboard terminates. A long-lived dashboard that triggers several
refreshes a day accumulates defunct entries. The `Popen` handle is also
discarded, so there is no way to observe failure (it goes to `DEVNULL`).
**Fix:** Reap the child in the worker thread instead of fire-and-forgetting it:
```python
def _run_task(task: str) -> None:
    proc = subprocess.Popen(
        [PYTHON3, "sports_system_runner.py", "--task", task],
        cwd=str(SCRIPTS_DIR),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    proc.wait()  # thread blocks here, not the Flask worker — child is reaped

threading.Thread(target=_run_task, args=(task,), daemon=True).start()
```
The Flask request still returns immediately (the wait happens on the daemon
thread), and the child is reaped on exit.

### WR-03: `ensure_ws_columns` resolves columns by name with last-write-wins on duplicates

**File:** `scripts/dashboard_writes.py:51-67`
**Issue:** The returned map is a dict comprehension keyed by `str(cell value)`.
If the Slip History header row ever contains a duplicate header (e.g. a legacy
sheet with two `Notes` columns, or a stray repeated `Operator Note` from a
partial prior migration), the comprehension silently keeps the *last* column
index for that name and the helper writes there — potentially a different column
than the one a human sees first. There is no guard asserting uniqueness, and no
guard that the three target columns landed at distinct indices. For a real-money
audit trail this is a quiet correctness hazard.
**Fix:** After building the map, assert the three target columns are present and
distinct, or build the map left-to-right with a `setdefault` so the *first*
occurrence wins and matches what `slip_payouts.SLIP_HISTORY_HEADERS` defines.
At minimum log a warning if a duplicate header is detected on the sheet.

### WR-04: Operator note length is unbounded — no input validation before workbook write

**File:** `scripts/dashboard.py:243-257`, `scripts/dashboard_writes.py:122-167`
**Issue:** `add_note` writes `str(note).strip()` straight into the cell with no
length cap. The form field (`slips.html:125`) is a free-text input with no
`maxlength`. Excel caps a cell at 32,767 characters; a paste larger than that
raises inside `openpyxl`/`safe_save_workbook`, which the route catches as a
generic `flash(f"Save failed: {exc}")` — but a near-cap note still bloats the
master workbook and every dated backup of it. While the dashboard is loopback-
only, the milestone goal is unattended reliability; an accidental large paste
should be rejected, not silently persisted.
**Fix:** Cap note length in `add_note` (e.g. `note = str(note).strip()[:2000]`)
and/or add `maxlength="2000"` to the input in `slips.html:125`. Reject
over-length input with a flash rather than truncating silently if exactness
matters.

### WR-05: State-changing POSTs have no CSRF token

**File:** `scripts/dashboard.py:208-257`, `scripts/templates/slips.html:108-129`
**Issue:** `/action/mark-placed`, `/action/add-note`, and `/action/refresh` are
unauthenticated state-changing POSTs with no CSRF token. The app binds to
127.0.0.1 (good), but loopback-only is not a complete CSRF defense: any web page
the operator visits in the same browser can POST to
`http://127.0.0.1:8787/action/refresh` (a simple form submit is not blocked by
CORS), silently triggering a runner spawn or flipping a slip's Placed flag /
note. The blast radius is bounded (writes are additive, tasks are whitelisted),
so this is a Warning rather than a Blocker, but `/action/refresh` spawning the
real pipeline from a cross-site form is undesirable.
**Fix:** Add a CSRF token to the three POST forms (Flask-WTF, or a minimal
per-session token compared in each handler), or require a custom header that a
cross-site form cannot set and reject requests lacking it. Given the
no-new-deps constraint, a hand-rolled `session`-stored token echoed as a hidden
field and compared server-side is sufficient.

## Info

### IN-01: `os.urandom(16)` secret key rotates per process — flash messages drop across restarts

**File:** `scripts/dashboard.py:51`
**Issue:** When `DASHBOARD_SECRET_KEY` is unset, the key is regenerated every
launch. Any flash message in flight across a restart is silently dropped (signed
session cookie no longer validates). Harmless for a single short-lived session
but can confuse the operator if the dashboard is restarted mid-action.
**Fix:** Acceptable as-is for loopback single-operator use; optionally persist a
key under `~/.hermes/.env` (`DASHBOARD_SECRET_KEY`) for stable sessions.

### IN-02: `last_updated_hhmm()` label semantics don't match its docstring source

**File:** `scripts/dashboard_data.py:232-263` (vs `dashboard.py:196` docstring)
**Issue:** `api_status`'s docstring describes `last_updated` as "HH:MM of the
most recently touched workbook," but `last_updated_hhmm()` actually returns the
timestamp of the last line of `run_log.jsonl` — the last *task* run, not the
last *workbook write*. These usually coincide but can diverge (a task that
writes nothing still logs). Cosmetic, but the docstring overstates precision.
**Fix:** Align the docstring with the implementation ("HH:MM of the last logged
task run") or, if workbook-mtime semantics are wanted, derive from the newest
workbook mtime instead.

### IN-03: `write_in_progress()` has a broad `except Exception: continue` swallow

**File:** `scripts/dashboard_data.py:221-223`
**Issue:** The per-lock-file loop ends with a bare `except Exception: continue`.
The inner blocks already catch the expected errors (`OSError`,
`json.JSONDecodeError`, `ProcessLookupError`, `PermissionError`), so this outer
catch only masks genuinely unexpected bugs as "no lock," which would make the
"updating…" badge silently wrong. Read-only and non-fatal, hence Info.
**Fix:** Narrow or drop the outer `except Exception`; let an unexpected error
surface (the function is read-only, so a traceback in logs is preferable to a
silently wrong badge).

### IN-04: `get_all_slips` date sort is string-based and assumes ISO formatting

**File:** `scripts/dashboard_data.py:494-497`
**Issue:** `_date_key` sorts on `str(s.get("Date"))`. This is correct only while
every Date value is a `YYYY-MM-DD`-prefixed string. If openpyxl returns a
`datetime` for a date-typed cell, `str(datetime)` is `"2026-06-08 00:00:00"`,
which still sorts correctly relative to other datetimes but interleaves
inconsistently with bare string dates if the column is mixed-type. Low risk
given the runner writes string dates, but the assumption is undocumented.
**Fix:** Normalize to `str(...)[:10]` in the sort key to match the `[:10]`
normalization used everywhere else in the write path.

### IN-05: `read_json` includes `OSError` but the catch tuple lists it after subclasses

**File:** `scripts/dashboard_data.py:84`
**Issue:** `except (FileNotFoundError, json.JSONDecodeError, OSError)` lists
`FileNotFoundError` (an `OSError` subclass) before `OSError`. Functionally fine
(tuple membership, not ordered matching), but the redundant subclass entry is
noise.
**Fix:** Drop `FileNotFoundError` from the tuple (covered by `OSError`) or keep
for readability — purely stylistic.

### IN-06: Refresh-spawn test mocks `threading.Thread`, so the real `Popen` path is never exercised

**File:** `scripts/test_dashboard_actions.py:127-146`
**Issue:** `test_refresh_triggers_subprocess` patches `threading.Thread`
entirely, so the test asserts the route *intends* to spawn but never verifies
the actual `Popen` argv (`[PYTHON3, "sports_system_runner.py", "--task", task]`)
or that the child is reaped (WR-02). A regression that breaks the argv or the
reaping would pass this test. Test-quality note, not a runtime defect.
**Fix:** Add a test that patches `subprocess.Popen` directly and asserts the
argv and that `.wait()` is called (after applying the WR-02 fix), in addition to
the thread-start assertion.

---

_Reviewed: 2026-06-24_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
