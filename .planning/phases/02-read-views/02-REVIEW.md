---
phase: 02-read-views
reviewed: 2026-06-24T00:00:00Z
depth: standard
files_reviewed: 6
files_reviewed_list:
  - scripts/dashboard_data.py
  - scripts/dashboard.py
  - scripts/templates/index.html
  - scripts/templates/slips.html
  - scripts/templates/history.html
  - scripts/test_dashboard_views.py
findings:
  critical: 1
  warning: 6
  info: 4
  total: 11
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-06-24T00:00:00Z
**Depth:** standard
**Files Reviewed:** 6
**Status:** issues_found

## Summary

Reviewed the read-only Flask dashboard (`dashboard.py`, `dashboard_data.py`) and its
three Jinja templates (`index.html`, `slips.html`, `history.html`) plus the view test
suite. The XSS-defense invariant holds well: there are **no `| safe` filters on
workbook data**, chart series are serialized through `| tojson` (Flask's HTML-safe
JSON), all `data-*` attributes are double-quoted so Jinja autoescaping protects them,
and the host is correctly pinned to `127.0.0.1`. The view tests pass.

However, the review surfaced one blocker and several robustness/correctness defects:

1. **A blocking `/slips` route** — `get_all_slips()` calls `_lookup_correlated_parlays()`
   once per slip, and each call re-opens both per-sport workbooks. Every
   `safe_load_workbook` incurs an unconditional 1-second `wait_for_stable_file` sleep
   (measured: ~1.02s per read). For the documented 88-slip superset this is ~176
   synchronous workbook opens → the page takes minutes and re-parses the same files
   repeatedly. For a project whose entire mandate is "kill the cron timeouts," a
   multi-minute synchronous request handler is a correctness-grade robustness failure.

2. **Zero-value numeric fields silently disappear** in `index.html` because several
   `data-*` attributes and one `<td>` use truthiness (`if row.Edge`) instead of
   `is not none`. A legitimate `0.0` Edge or `0.0` model probability becomes blank,
   corrupting the client-side sort/filter and the displayed cell.

The remaining findings are smaller correctness and consistency issues plus dead output.

## Critical Issues

### CR-01: `/slips` performs O(N) blocking workbook opens — route is effectively unusable

**File:** `scripts/dashboard_data.py:416-428` (loop) and `:442-473` (`_lookup_correlated_parlays`)
**Issue:**
`get_all_slips()` iterates every slip and calls `_lookup_correlated_parlays(slip)` for
each one. That helper loops over both sport dirs and calls `read_sheet_rows(wb_path,
"Correlated Parlays")` — i.e. **2 full workbook opens per slip**. Each
`read_sheet_rows` → `safe_load_workbook` → `wait_for_stable_file` performs an
**unconditional `time.sleep(1.0)`** even on the happy path (verified empirically:
single happy-path `read_sheet_rows` = ~1.02s; `workbook_io.wait_for_stable_file`
line 72-76 sleeps before returning).

For the documented 88-slip superset (CLAUDE.md / Pitfall 6) that is ~176 sequential
workbook opens ≈ **~3 minutes of blocking I/O inside one Flask request**, re-parsing
the same one or two per-date workbooks over and over. The route handler is synchronous,
so the page is unusable. This directly contradicts the project's core mandate (eliminate
timeouts / blocking) and is a robustness/correctness failure, not a mere perf nit.

This is compounded by the design note in the docstring that Tier-1 lookups are "rarely
populated (Pitfall 7)" — meaning nearly all 176 reads do work only to fall through to
the cheap Tier-2 string derivation that needs no I/O at all.

**Fix:** Hoist the per-date Correlated Parlays reads out of the per-slip loop. Read each
needed `(sport, date)` workbook's "Correlated Parlays" sheet at most once, build a
`{slip_id: (reasoning, corr_group)}` index, then look slips up in that dict:

```python
def get_all_slips() -> dict[str, Any]:
    master_path = PNL_DIR / "master_pnl.xlsx"
    locked = False
    slip_rows = read_sheet_rows(master_path, "Slip History")
    if slip_rows is None:
        locked = True
        slip_rows = []

    # Collect the distinct dates we actually need, read each workbook once.
    dates = {str(s.get("Slip ID") or "").split(":")[0] for s in slip_rows}
    parlay_index: dict[str, str] = {}
    for date_part in dates:
        if len(date_part) != 10:
            continue
        for sport_dir, prefix in ((NBA_DIR, "nba"), (MLB_DIR, "mlb")):
            for pr in (read_sheet_rows(sport_dir / f"{prefix}_{date_part}.xlsx",
                                       "Correlated Parlays") or []):
                sid = pr.get("Slip ID")
                reasoning = str(pr.get("Reasoning") or "").strip()
                corr = str(pr.get("Correlation Group") or "").strip()
                if sid and reasoning:
                    parlay_index[sid] = f"{reasoning} — {corr}" if corr else reasoning

    for slip in slip_rows:
        slip["legs_list"] = [l for l in str(slip.get("Legs") or "").split("; ") if l.strip()]
        sid = str(slip.get("Slip ID") or "")
        slip["why_paired"] = parlay_index.get(sid) or _derive_why_paired(sid)

    slip_rows.sort(key=lambda s: str(s.get("Date") or ""), reverse=True)
    return {"slips": slip_rows, "locked": locked}
```

This caps the workbook opens at `O(distinct_dates × 2)` instead of `O(slips × 2)`.

## Warnings

### WR-01: Zero-valued Edge / probability silently dropped via truthiness in `index.html`

**File:** `scripts/templates/index.html:54-55`, `:62`, `:63`, `:74`
**Issue:**
Several attributes/cells gate on truthiness instead of `is not none`:
- `data-prob="{{ row['Model Over Probability'] if row['Model Over Probability'] else '' }}"` (line 54)
- `data-edge="{{ row.Edge if row.Edge else '' }}"` (line 55)
- `<td>{% if row['Model Over Probability'] %}...{% endif %}` (line 62)
- skipped row `data-edge="{{ row['What Edge Would Have Been'] if row['What Edge Would Have Been'] else '' }}"` (line 74)

A genuine value of `0.0` is falsy in Jinja (verified: `{% if row.Edge %}` renders
EMPTY for `Edge=0.0`). So a 0.0 edge / 0% probability becomes an empty sort key and a
blank/`&mdash;` cell. Worse, line 55 (`data-edge`) and line 63 (the Edge `<td>`, which
correctly uses `is not none`) **disagree** for `Edge=0.0`: the cell shows `0.0` but the
sort attribute is empty, so sorting silently mis-orders the row (NaN sinks to bottom).

**Fix:** Use `is not none` everywhere a numeric zero is a valid value:
```jinja
data-prob="{{ row['Model Over Probability'] if row['Model Over Probability'] is not none else '' }}"
data-edge="{{ row.Edge if row.Edge is not none else '' }}"
...
<td>{% if row['Model Over Probability'] is not none %}{{ "%.0f"|format(row['Model Over Probability'] * 100) }}%{% else %}&mdash;{% endif %}</td>
```
Apply the same to line 74 (`What Edge Would Have Been`).

### WR-02: `data-confidence`/`data-edge` truthiness also drops the literal string `"0"` and confidence `0`

**File:** `scripts/templates/index.html:56`, `:62-64`
**Issue:** Same class of bug as WR-01 but on the `Confidence`/`Edge` text columns: `{{ row.Confidence if row.Confidence else '' }}` (line 56) drops any falsy-but-present value. While Confidence is usually a letter tier, the inconsistency between the `data-*` attribute (truthiness) and the `<td>` (`is not none`, line 64) means the visible cell and the sort key can disagree, producing a sort that does not match what the operator sees. Keep the attribute and the cell using the **same** predicate.
**Fix:** Standardize on `is not none` for both the attribute and the cell, or derive the attribute from the same coerced field used for display.

### WR-03: Approved vs skipped rows feed the prob sort from different fields

**File:** `scripts/templates/index.html:54` vs `:73`; `scripts/dashboard_data.py:354-356` vs `:372-375`
**Issue:** Approved rows set `data-prob` from the raw workbook `row['Model Over Probability']` (a 0–1 float), while skipped rows set `data-prob` from `row.prob_float` (the coerced `Probability` column). The accessor adds `prob_float` only to skipped rows (line 374) and never adds it to approved rows. When the combined table is sorted by "prob", approved and skipped rows are compared on values that come from two different columns with potentially different semantics/scales. This produces a misleading mixed-population sort.
**Fix:** Have the accessor compute a single normalized `prob_float` for **both** approved and skipped rows (approved from `Model Over Probability`, skipped from `Probability`) and have the template read `row.prob_float` uniformly for both `data-prob` and the displayed cell.

### WR-04: `get_history_data` silently drops rows whose Sport is not exactly "NBA"/"MLB"

**File:** `scripts/dashboard_data.py:537`, `:546`
**Issue:** `sport = str(row.get("Sport") or "").strip().upper()` then `by_sport.get(sport, {})`. Any Pick History row with a Sport value other than the two literals `"NBA"`/`"MLB"` (e.g. blank, `"NBA "` with trailing chars already handled by strip, or a future sport) silently contributes to `overall` but to **no** `by_sport` bucket. The result: the per-sport rows do not reconcile to Overall, with no indication why. This is a quiet data-integrity gap on a results dashboard.
**Fix:** Either assert/log when a row's sport is unrecognized, or add an "OTHER" bucket and surface it, so per-sport W/L always sums to Overall. At minimum, document that Overall may exceed NBA+MLB.

### WR-05: `last_updated_hhmm` trusts the last log line only — a partial/last-line-corrupt write yields None and hides a fresh run

**File:** `scripts/dashboard_data.py:240-253`
**Issue:** Only the single last non-empty line is parsed. If the pipeline is mid-write and the final line is a partial JSON fragment (a real possibility for an append-as-you-go JSONL during the exact "updating" window this badge exists to cover), `json.loads` fails and the function returns `None` — so the "last updated HH:MM" badge vanishes precisely when the operator most wants it. The preceding valid line is ignored.
**Fix:** Walk lines from the end and return the first one that parses successfully:
```python
for ln in reversed(lines):
    try:
        data = json.loads(ln)
        return datetime.fromisoformat(data["timestamp"]).astimezone().strftime("%H:%M")
    except (json.JSONDecodeError, KeyError, ValueError, TypeError):
        continue
return None
```

### WR-06: `_port()` does not validate range — a non-positive or >65535 port crashes `app.run` after the browser timer is already scheduled

**File:** `scripts/dashboard.py:39-44`, `:124-128`
**Issue:** `_port()` only guards `ValueError`/`TypeError` on the cast. `DASHBOARD_PORT=0`, `-1`, `99999`, or `--port 0` pass the cast and reach `app.run`, which raises `OverflowError`/`OSError` — but only **after** `threading.Timer(1.0, webbrowser.open)` was already scheduled (line 128), so a browser tab opens pointing at a server that never bound. The `except OSError` handler at line 137 also will not catch `OverflowError`.
**Fix:** Validate `1 <= port <= 65535` in `_port()` (and after `parse_args`) before scheduling the browser timer; fall back to 8787 or exit with a clear message on an out-of-range value.

## Info

### IN-01: `roi` chart series is computed but never consumed (dead output)

**File:** `scripts/dashboard_data.py:584` (`daily_roi`), `:599` (`roi_w`), `:605-606`
**Issue:** `get_history_data` builds `chart_daily.roi` and `chart_weekly.roi`, but `history.html` only ever reads `labels` and `bankroll` (lines 108-111). The ROI arrays are pure dead output — they cost a parse/serialize and imply a feature (ROI charting) that does not exist. Either wire an ROI dataset into the chart or drop the `roi`/`daily_roi`/`roi_w` plumbing.
**Fix:** Remove the unused `roi` series, or add a second Chart.js dataset / toggle that uses it.

### IN-02: Weekly chart "last row per week wins" depends on unsorted input order

**File:** `scripts/dashboard_data.py:586-595`
**Issue:** `weekly[week_key] = row` keeps whichever row is encountered **last in `chart_rows` iteration order**, not the chronologically latest date in the week. The comment says "last point in the week wins," which is only true if `Bankroll Chart Data` is already date-ascending. If the sheet is ever written out of order, the wrong day's bankroll represents the week. The test passes only because the fixture is pre-sorted.
**Fix:** Sort `chart_rows` by `Date` before the weekly fold, or compare dates explicitly and keep the max-date row per week.

### IN-03: `get_today_board` per-sport early-`continue` on missing file means an MLB-only lock cannot be distinguished from MLB-not-run

**File:** `scripts/dashboard_data.py:334-340`
**Issue:** When one sport's workbook is absent the loop `continue`s and `locked` stays driven only by the other sport. This is the intended "missing = empty, not locked" contract, but it means a day where NBA ran (and is mid-write/locked) while MLB simply has not run yet still reports `locked=True` globally with NBA rows suppressed — the banner says "updating" with no indication it is NBA-specific. Acceptable for v1, but worth a comment so a future reader does not mistake it for a bug.
**Fix:** Add a clarifying comment, or track lock state per sport if finer-grained messaging is wanted later.

### IN-04: `test_history_200` asserts a CDN string that can rot silently

**File:** `scripts/test_dashboard_views.py:602`; `scripts/templates/history.html:103-105`
**Issue:** The smoke test asserts `b"chart.js"` is in the body. The template pins Chart.js to a `cdn.jsdelivr.net` URL with an SRI hash. If the CDN URL or version is ever changed such that the literal substring `chart.js` no longer appears (e.g. a self-hosted `chart.umd.min.js` rename), the test breaks for reasons unrelated to the route's correctness. Low priority, but the test couples to a presentation detail rather than the view contract.
**Fix:** Assert on a stable marker the route owns (e.g. the canvas id `bankroll-chart` or an H3 heading) instead of the third-party library filename.

---

_Reviewed: 2026-06-24T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
