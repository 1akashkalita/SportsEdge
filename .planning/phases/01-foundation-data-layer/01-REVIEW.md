---
phase: 01-foundation-data-layer
reviewed: 2026-06-23T00:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - scripts/dashboard.py
  - scripts/dashboard_data.py
  - scripts/templates/base.html
  - scripts/templates/index.html
  - scripts/test_dashboard.py
  - scripts/test_dashboard_data.py
findings:
  critical: 1
  critical_resolved: 1
  warning: 5
  info: 4
  total: 10
status: issues_found
notes: "CR-01 (blocker) resolved 2026-06-24; 5 warnings + 4 info deferred to Phase 2"
---

# Phase 01: Code Review Report

**Reviewed:** 2026-06-23
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Reviewed the Phase-1 read-only dashboard data layer (`dashboard_data.py`), the
loopback-bound Flask server (`dashboard.py`), two Jinja templates, and the two
test files. I verified the four hard constraints against the live codebase:

- **DASH-03 (loopback bind):** PASS. `HOST = "127.0.0.1"` is the sole bind
  address; `app.run(host=HOST, ...)` never uses `0.0.0.0`/`""`.
- **DASH-04 (read-only, byte-unchanged):** PASS in intent. Reads use
  `read_only=True, data_only=True` and there is no write/subprocess/runner-import
  path.
- **D-02 (today matches runner):** PASS. `dashboard_data.today_str()` is
  byte-for-byte the runner's `datetime.now().strftime("%Y-%m-%d")` (runner
  line 334); no `zoneinfo` import anywhere in the module.
- **Jinja autoescape:** PASS. No `| safe` and no `{% autoescape false %}`; Flask
  3.1.3 autoescapes `.html` by default, so workbook strings rendered in Phase 2
  will be escaped.

The cross-cutting facts also check out against ground truth: `run_log.jsonl`
exists and its last record carries `timestamp` as UTC `+00:00`; the lock dir is
`ROOT / "locks"` matching the runner's `WORKBOOK_LOCK_DIR`; live lock files are
named `<name>.xlsx.lock` and match the `*.xlsx.lock` glob.

However, the lock-tolerance contract (D-01) has a real correctness defect: the
catch-all in `read_sheet_rows` swallows **every** exception including bugs in
the reader itself, which can silently misreport a present-but-bug-triggering
workbook as "locked" (last-known-good None). There are also several robustness
and clarity issues described below.

## Critical Issues

### CR-01: `read_sheet_rows` swallows all exceptions (including its own bugs) as "locked"

> **RESOLVED 2026-06-24** — handler narrowed to `(WorkbookAccessError, FileNotFoundError, OSError, zipfile.BadZipFile)` in `dashboard_data.py:132`; the `finally`-close is preserved and all 5 data-layer tests stay green. Genuine reader bugs (KeyError/TypeError/schema regressions) now surface instead of being disguised as "locked".

**File:** `scripts/dashboard_data.py:131-133`
**Issue:** The handler is `except (WorkbookAccessError, FileNotFoundError, Exception):`.
Because `Exception` already subsumes both `WorkbookAccessError` and
`FileNotFoundError` (verified: both are `Exception` subclasses), the tuple is not
just redundant — it is a **bare catch-all that maps any failure to `None`**. The
D-01 contract is specifically "a workbook *locked mid-write* must yield
last-known-good (None) and never raise." This implementation goes much further:
a `KeyError`/`TypeError`/`AttributeError` introduced by a future edit to the
header/zip logic, an `openpyxl` schema regression, a `MemoryError`, or any
genuine bug in the reader body will all be silently reported as `None` — i.e.
indistinguishable from "locked." The dashboard would then render a correct-looking
"updating…/no data" state while masking a real defect, and the test suite's
`assertIn(result, (None, []))` would still pass. For a real-money system whose
whole Phase-1 purpose is trustworthy freshness signals, silently converting
programming errors into "looks locked" is a correctness/data-integrity risk: the
operator cannot distinguish "pipeline is writing" from "the reader is broken."

**Fix:** Catch only the lock/IO failure modes the contract names, and let
unexpected exceptions surface (or log + re-raise) so real bugs are visible. The
`finally` block already guarantees the handle is closed:
```python
    except (WorkbookAccessError, FileNotFoundError, OSError, zipfile.BadZipFile):
        # D-01 last-known-good: locked / missing / unreadable workbook → None
        return None
    # do NOT catch bare Exception — a KeyError/TypeError here is a real bug,
    # not a lock, and must not be silently reported as last-known-good.
    finally:
        if wb is not None and hasattr(wb, "close"):
            try:
                wb.close()
            except Exception:
                pass
```
(Add `import zipfile` if you choose to name `BadZipFile`; alternatively drop it
and rely on `OSError`.) If you must remain non-raising for cron safety, at
minimum split the handler: keep the narrow tuple returning `None`, and add a
separate `except Exception as exc:` that logs the unexpected error before
returning `None`, so the failure is observable rather than invisible.

## Warnings

### WR-01: `read_sheet_rows` collapses duplicate column headers, silently dropping data

**File:** `scripts/dashboard_data.py:128`
**Issue:** `result.append(dict(zip(headers, row)))` keys each row by header text.
If a sheet ever has two columns with the same header string, the later column
overwrites the earlier one in the dict and the first column's value is lost for
every row. Workbook schemas in this system are wide and migrated additively by
`ensure_workbook`, so duplicate/blank header cells are a realistic hazard (a
`None`/empty header from a trailing column also becomes a single `None` key that
collapses). Phase 2 consumers reading these dicts would get silently truncated
rows with no error.
**Fix:** Detect and disambiguate duplicate/blank headers, or at least make the
collision observable. For example, build keys defensively:
```python
seen: dict[Any, int] = {}
norm_headers = []
for h in headers:
    key = h if h not in (None, "") else "col"
    if key in seen:
        seen[key] += 1
        key = f"{key}.{seen[key]}"
    else:
        seen[key] = 0
    norm_headers.append(key)
# then dict(zip(norm_headers, row))
```

### WR-02: `last_updated_hhmm` mislabels naive timestamps via `.astimezone()`

**File:** `scripts/dashboard_data.py:241-243`
**Issue:** `datetime.fromisoformat(ts_str).astimezone()` is correct for the
runner's current output (`now_iso()` emits UTC with a `+00:00` offset, confirmed
in the live `run_log.jsonl`). But if any record's `timestamp` is ever written
*without* an offset (naive), `fromisoformat` returns a naive datetime and
`.astimezone()` assumes it is in **local** time — so a UTC-naive timestamp would
be displayed as if it were already local, producing a wrong "last updated" label
(off by the local UTC offset, e.g. 7-8h on Pacific). The docstring asserts the
input "is UTC ISO format with +00:00 offset" but the code does not enforce that
assumption. The "last updated" badge is one of only two signals this phase
ships, so a silently-wrong time undermines the phase's core value.
**Fix:** Treat a missing offset as UTC explicitly before converting:
```python
dt = datetime.fromisoformat(ts_str)
if dt.tzinfo is None:
    dt = dt.replace(tzinfo=timezone.utc)   # run_log timestamps are UTC
return dt.astimezone().strftime("%H:%M")
```
(Add `from datetime import timezone`.)

### WR-03: Stub tab `href="#"` will scroll/navigate instead of being inert

**File:** `scripts/templates/base.html:51-53`
**Issue:** The reserved Calibration/Line-changes/Live tabs use `href="#"` with
`aria-disabled="true"`. `aria-disabled` is advisory only — it does not stop the
click. Clicking these "inert" tabs will navigate to `#`, jump the page to the
top, and push a history entry, which is visibly not "inert" behavior and is
mildly confusing in an operator tool. `cursor: default` in the CSS hints at
non-interactivity but does not prevent activation (including keyboard Enter).
**Fix:** Make them genuinely non-navigating, e.g. render as `<span>` instead of
`<a href>`, or neutralize the click:
```html
<a class="stub-tab" aria-disabled="true"
   onclick="return false;" tabindex="-1"
   title="Coming in a future milestone">Calibration</a>
```
(Prefer `<span>` to fully remove it from the tab/keyboard order.)

### WR-04: Browser auto-open uses a fixed 1.0s timer — racy on slow start, opens even on bind failure

**File:** `scripts/dashboard.py:92`
**Issue:** `threading.Timer(1.0, lambda: webbrowser.open(url)).start()` is armed
*before* `app.run()`. If `app.run` fails immediately on the
address-already-in-use path (lines 101-110), the timer has already been
scheduled and will still fire ~1s later, opening a browser tab pointed at a URL
the dashboard is **not** serving (or worse, at another process that grabbed the
port). The fixed 1.0s delay is also a guess: on a cold/slow start the browser may
open before Werkzeug is listening and show a connection-refused page.
**Fix:** Cancel the timer in the `OSError` branch before returning, e.g. hold the
`Timer` in a variable and call `.cancel()` on the error path:
```python
opener = threading.Timer(1.0, lambda: webbrowser.open(url))
opener.start()
try:
    app.run(...)
except OSError as exc:
    opener.cancel()
    if exc.errno in (48, 98):
        ...
        return 1
    raise
```

### WR-05: `_port()` ignores invalid `DASHBOARD_PORT` silently and accepts out-of-range/privileged ports

**File:** `scripts/dashboard.py:39-44`
**Issue:** A malformed `DASHBOARD_PORT` (e.g. `"abc"`) silently falls back to
8787 with no warning, so a misconfigured env var produces a server on an
unexpected port with no signal to the operator. Additionally neither `_port()`
nor the `--port` argparse path validates the range, so values like `0`,
negative numbers, or `>65535` are passed straight to `app.run`, where they
produce an opaque socket error rather than a clear message. For a single-operator
tool, a clear diagnostic beats a silent fallback or a cryptic traceback.
**Fix:** Validate and warn:
```python
def _port() -> int:
    raw = os.environ.get("DASHBOARD_PORT", "8787")
    try:
        p = int(raw)
        if not (1 <= p <= 65535):
            raise ValueError
        return p
    except (ValueError, TypeError):
        print(f"WARNING: invalid DASHBOARD_PORT={raw!r}; using 8787", file=sys.stderr)
        return 8787
```
Apply the same 1-65535 check to the `--port` value before `app.run`.

## Info

### IN-01: Redundant exception members in the `read_sheet_rows` handler

**File:** `scripts/dashboard_data.py:131`
**Issue:** Even after addressing CR-01, note that listing
`WorkbookAccessError, FileNotFoundError, Exception` together is dead/redundant —
`Exception` already covers the first two. Keeping all three signals confusion
about intent. (Folded into CR-01's fix, but called out separately as a code-clarity
item.)
**Fix:** Name only the specific exception types you intend to treat as
last-known-good.

### IN-02: `read_json` return type annotation omits `None` despite returning `None`

**File:** `scripts/dashboard_data.py:63`
**Issue:** The signature is `-> dict | list | None` in the source (correct), but
the module-level docstring/return description ("Returns: dict | list parsed from
the file, or None") and the function's own `Returns:` line are consistent — this
is fine. However the per-CLAUDE.md convention is PEP 604 unions with explicit
`Any` element typing; `dict`/`list` are unparameterized here while
`read_sheet_rows` uses `dict[str, Any]`. Minor inconsistency in type-annotation
granularity across the two readers.
**Fix:** For consistency, annotate as `dict[str, Any] | list[Any] | None`.

### IN-03: `STALE_SECONDS` duplicates `workbook_io`'s `stale_seconds=600` as a magic constant

**File:** `scripts/dashboard_data.py:43`
**Issue:** The 600s staleness threshold is hardcoded here and documented as
"mirrors workbook_io stale_seconds=600," but `workbook_io.workbook_file_lock`
defines `stale_seconds=600` as a default parameter independently. If the runner's
stale threshold is ever tuned, this copy will silently drift, causing
`write_in_progress()` to disagree with the lock reaper about what counts as
stale.
**Fix:** Acceptable for Phase 1 given the read/write module boundary, but add a
short comment pinning the source of truth (file+symbol) and a note to update both
together, or import the default if `workbook_io` is later refactored to expose it
as a module constant.

### IN-04: `index()` does a synchronous workbook-stable-wait sleep on every request via the freshness path

**File:** `scripts/dashboard.py:60-64` (calls `dashboard_data.write_in_progress` and `last_updated_hhmm`)
**Issue:** Not a bug today — `write_in_progress()` and `last_updated_hhmm()`
themselves do not call `safe_load_workbook`, so the per-request cost is only
small `stat`/`read_text` calls. Flagged as a forward-looking note: when Phase 2
wires `read_sheet_rows` into a per-request route, each call triggers
`workbook_io.wait_for_stable_file`'s `time.sleep(1.0)`, so a Today view reading
several sheets will add multiple seconds of latency per page load. Keep that in
mind when composing Phase-2 routes (e.g. read once and cache within the request).
**Fix:** No action required in Phase 1; consider a single batched read per
request in Phase 2 to avoid stacking the 1s stable-file sleeps.

---

_Reviewed: 2026-06-23_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
