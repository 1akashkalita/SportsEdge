# Phase 2: Read Views - Research

**Researched:** 2026-06-24
**Domain:** Flask server-rendered pages reading Excel workbooks + JSON over the Phase 1 data layer
**Confidence:** HIGH — all data-source mappings confirmed by direct inspection of live workbooks and runner source constants

## Summary

Phase 2 is almost entirely a data-contract lock + rendering exercise over an already-working foundation. The Flask app (`dashboard.py`), the read layer (`dashboard_data.py`), and the dark Pico shell (`base.html`) are all in place from Phase 1. The `/slips` and `/history` routes do not exist yet; `index.html` renders a placeholder. This phase fills the three page bodies, wires the routes, and adds view-shaping accessor functions to `dashboard_data.py`.

The single most important research finding is the **per-view data-source mapping**: every column needed by all three views exists in verified live workbooks, with exact header strings confirmed against the runner's module-level constants (`PICKS_HEADERS`, `SKIPPED_PICK_HEADERS`, `PARLAY_HEADERS`, `SLIP_HISTORY_HEADERS`) and the actual files. Two subtle contract points must not be guessed: (1) the Picks sheet has no `Stat` column — stat must be derived from `Selection` string or omitted; (2) the authoritative Slip History source for the Slips page is `master_pnl.xlsx` (88 slips), not the per-sport workbooks (82 slips, 6 short), because the master receives slips from both sports and the entire history regardless of date.

The History page data is split across two sources: `master_pnl.xlsx:Bankroll Chart Data` for the daily bankroll time series (12 date points, `Date/Bankroll/ROI/Updated At`), and `master_pnl.xlsx:Pick History` for per-sport W/L and per-confidence-tier breakdown (`Confidence Tier` values A/B/C/UNKNOWN; `Result` values WIN/LOSS/PUSH/PENDING/VOID/MANUAL REVIEW). The Daily Log sheet is slip-only (Sport='SLIPS') and not suitable for sport-level W/L; only Pick History carries `Sport=NBA|MLB` at row level.

The `metrics_report.py` ISO-week aggregation (`aggregate_slip_roi_by_week_sport`) reads per-sport dated workbooks, not the master. For the weekly chart toggle, the simpler approach is to aggregate the Bankroll Chart Data by ISO week (last point per week) directly in the read layer — this avoids importing `metrics_report.py` into the dashboard and keeps the read layer self-contained.

**Primary recommendation:** Add three view accessor functions to `dashboard_data.py` (`get_today_board`, `get_all_slips`, `get_history_data`), add three routes to `dashboard.py`, create three Jinja templates (`today.html`, `slips.html`, `history.html`), and use client-side vanilla JS for filter/sort/expand — no new server-side state needed for a dataset this small (max ~200 rows/day, 88 slips all-time).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** The Today page is a **model-transparency board**. It shows the **evaluated set** = approved picks + skipped/no-bet candidates, each skip tagged with the **gate that rejected it** (from `Skipped Picks` sheet column `Gate Failed`).
- **D-02:** "Whole board" = evaluated set only (props scored by the model). Does NOT include raw Props-sheet dump. Every rendered row carries meaningful EV/prob/edge/confidence numbers.
- **D-03:** **One dense, sortable master table** (not visually grouped sections). Columns include Platform, Sport, Status alongside player/stat/line, projection, edge, +EV, model probability, confidence. Top filter bar (platform / sport / approved-vs-skipped). Click-to-sort headers. Default sort: EV descending.
- **D-04:** `✓ Approved` or `Skip: <Gate>` in the **Status column**; skipped rows visually dimmed/muted.
- **D-05:** Default view is **all slips, grouped by date descending**. Date/status filter narrows it. Not paginated.
- **D-06:** Each slip renders as an **expandable row**: compact summary row that expands on click to reveal legs + "why paired" insight.
- **D-07:** "Why paired" insight is **two-tier**: stored Correlated Parlays `Reasoning` + `Correlation Group` when present; derived rationale (same game/team, combined prob/EV) for general slips.
- **D-08:** Bankroll/ROI time-series chart supports **daily (default) and ISO-week** views via toggle. Daily is the default. Weekly mirrors existing `metrics_report` weekly framing. Chart.js via CDN.
- **D-09:** Per-confidence-tier breakdown shows per tier: **record (W-L)**, **hit-rate %**, **ROI %**, **sample count**.

### Claude's Discretion
- Filter/sort implementation — client-side vanilla JS vs server-side query-params. Recommendation: client-side (see section below).
- Empty / no-games-today states — graceful messaging rather than blank pages.
- Number formatting — EV/probability/hit-rate/ROI as `%`, edge native unit; optional color cue for +EV vs −EV.
- Derived "why paired" fallback for truly independent legs.
- Route/template/partial structure, sortable-table mechanism, expandable-row mechanism — within existing `base.html` shell.
- **Exact source-sheet/column mapping** — locked in this research document.

### Deferred Ideas (OUT OF SCOPE)
- Quantified leg-correlation modeling (variance/correlation coefficients) — later enhancement.
- Calibration / Line-changes / Live tabs (TAB-01..03) — later milestones M2–M4.
- Safe write actions (refresh/re-run, mark-placed, add-note) — Phase 3.
- Pagination for Slips at current volume (~88 slips total).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| VIEW-01 | Today's props/picks grouped by platform and sport, showing +EV, model probability, edge, and confidence, with platform/sport filtering and EV sorting | Picks sheet (PICKS_HEADERS confirmed) + Skipped Picks sheet (SKIPPED_PICK_HEADERS confirmed); both live workbooks read correctly via `read_sheet_rows` |
| VIEW-02 | All slips (status, payout, legs) with "why these legs are paired" insight (Correlated Parlays `Reasoning`/`Correlation Group`; derived rationale for general slips) | `master_pnl.xlsx:Slip History` (88 slips confirmed); Correlated Parlays sheet in per-sport workbooks (empty in current run — derived fallback is the normal path); legs are semicolon-delimited string |
| VIEW-03 | W/L history overall and per sport, bankroll/ROI time-series chart, per-confidence-tier breakdown | `master_pnl.xlsx:Bankroll Chart Data` (12 points confirmed); `master_pnl.xlsx:Pick History` (281 rows, Confidence Tier A/B/C/UNKNOWN, Sport=NBA|MLB); Chart.js CDN in reserved `{% block scripts %}` slot |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **Interpreter:** `/usr/local/bin/python3` (3.14.0a2). `python` (3.13) lacks deps. Always `python3`.
- **Working directory:** Run from `scripts/`; sibling imports by bare name. `dashboard.py`, `dashboard_data.py`, templates live in `scripts/`.
- **Read-only:** This phase writes nothing to workbooks. No gate logic, pick outputs, or workbook schema changes.
- **Tests:** `unittest` (not pytest fixtures), run from `scripts/`. Mirror `test_dashboard_data.py` + `test_dashboard.py` style.
- **No hardcoded secrets, no new external packages** — only stdlib + Flask + openpyxl (already installed).
- **GSD workflow:** File edits go through GSD commands.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Serve Today / Slips / History HTML | Frontend Server (`dashboard.py` routes) | Jinja2 templates | Server-renders all three views on GET; no client fetch calls |
| Read + shape Today board data | Data layer (`dashboard_data.py:get_today_board`) | `read_sheet_rows` | Reads Picks + Skipped Picks, merges, normalizes Status label; route passes dict to template |
| Read + shape Slips data | Data layer (`dashboard_data.py:get_all_slips`) | `master_pnl.xlsx:Slip History` | Reads master slip history; route passes list to template |
| "Why paired" insight derivation | Data layer (`get_all_slips` or inline in accessor) | Correlated Parlays sheet per-sport | Stored reasoning lookup first, derived fallback second |
| Read + shape History data | Data layer (`dashboard_data.py:get_history_data`) | `master_pnl.xlsx` three sheets | Aggregates Pick History for W/L + tier; reads Bankroll Chart Data for series |
| Filter / sort Today table | Browser (vanilla JS) | — | Dataset is small (≤200 rows/day); client-side is snappier, zero server round-trips |
| Expandable Slips rows | Browser (vanilla JS) | — | Simple DOM toggle; no server state |
| Chart rendering (History) | Browser (Chart.js CDN) | `{% block scripts %}` slot | Server serializes labels+datasets as JSON in template; Chart.js renders |
| Freshness badge (all pages) | All three route handlers | `dashboard_data.write_in_progress()`, `last_updated_hhmm()` | Already works for `/`; all three routes must pass these two context vars |

## Standard Stack

All packages already installed in Phase 1. No new installs for Phase 2.

### Core (inherited from Phase 1, no changes)
| Library | Version | Purpose | Status |
|---------|---------|---------|--------|
| Flask | 3.1.3 | Routing, request/response, Jinja render | Installed, verified on 3.14.0a2 |
| Jinja2 | 3.1.6 | Server-side HTML templating | Installed |
| openpyxl | 3.1.5 | Read `.xlsx` via `read_sheet_rows` | Installed |

### Supporting (CDN, no install)
| Library | Source | Purpose | Notes |
|---------|--------|---------|-------|
| Chart.js | CDN (`{% block scripts %}`) | History bankroll/ROI time-series chart | Slot already reserved in `base.html`; include only in `history.html` |
| Pico.css | CDN (`base.html`) | Dark dense-table theme | Already in `base.html`; add minimal inline CSS for dimmed/muted skipped rows |

### New additions required
None. Phase 2 is pure code — new Python functions, new routes, new Jinja templates.

## Package Legitimacy Audit

No new packages are installed in Phase 2. All libraries in use were verified in Phase 1.

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none

## Per-View Data-Source Mapping

### VIEW-01: Today Page

**Source workbooks:** `data/nba/nba_{today}.xlsx` and `data/mlb/mlb_{today}.xlsx`
**"today":** `dashboard_data.today_str()` — naive local date, matches runner exactly

#### Approved Picks (Picks sheet)

| Rendered Field | Sheet | Exact Column Header | Type | Notes |
|----------------|-------|---------------------|------|-------|
| Date filter | Picks | `Date` | str `YYYY-MM-DD` | Filter rows where `Date == today_str()` |
| Sport | Picks | `Sport` | str `"NBA"` or `"MLB"` | Filter dimension |
| Platform | Picks | `Platform` | str e.g. `"Underdog"` / `"PrizePicks"` | Filter dimension |
| Pick (display) | Picks | `Selection` | str e.g. `"Nasim Nuñez Over 0.5 Hits"` | Primary pick label |
| Player | Picks | `Player/Team` | str | Separate from stat; may be empty for game picks |
| Stat | (derived) | (none) | str | No `Stat` column in Picks. Parse from `Selection` string: text after `Over N.N` or `Under N.N` pattern. Empty for spreads/totals. **This is string parsing — flag as tech-debt.** |
| Line | Picks | `Line` | numeric | |
| Pick Type | Picks | `Pick Type` | str `"PROP"` / `"SPREAD"` / `"TOTAL"` | For display grouping |
| Projection | Picks | `Model Projection` | numeric or None | |
| Edge | Picks | `Edge` | numeric | |
| Model Prob (%) | Picks | `Model Over Probability` | float 0–1 | Render as `%` |
| EV | Picks | `EV` | float | Default sort column (descending). Render as `%` or display raw. |
| Confidence | Picks | `Confidence` | str `"A"` / `"B"` / `"C"` | Tier. A=score≥3, B=score≥2, C=score=1 |
| Units | Picks | `Units` | numeric | `A→3u, B→2u, C→1u` |
| Status | (computed) | — | str | Always `"✓ Approved"` for rows from Picks sheet |
| Injury Flag | Picks | `Injury Flag` | str or None | Display if non-null |

**Row filter:** `Status == "APPROVED"` (all approved picks have `Status = "APPROVED"` from the runner).

#### Skipped Picks (Skipped Picks sheet)

| Rendered Field | Sheet | Exact Column Header | Type | Notes |
|----------------|-------|---------------------|------|-------|
| Date filter | Skipped Picks | `Date` | str `YYYY-MM-DD` | Filter rows where `Date == today_str()` |
| Sport | Skipped Picks | `Sport` | str | Filter dimension |
| Platform | Skipped Picks | `Platform` | str or None | Some skips (game-type) may have empty platform |
| Pick (display) | Skipped Picks | `Pick` | str | Full text e.g. `"Seattle -1.5"` |
| Player | Skipped Picks | `Player/Team` | str | Same as Pick text for game picks |
| Stat | (derived) | — | str | Same string-parse approach from `Pick` field |
| Line | Skipped Picks | `Line` | numeric | |
| Pick Type | Skipped Picks | `Pick Type` | str `"PROP"` / `"SPREAD"` / `"TOTAL"` | |
| Projection | (absent) | — | — | Skipped picks do not have Model Projection in their sheet |
| Edge | Skipped Picks | `What Edge Would Have Been` | numeric or None | Display as "would-have-been" edge |
| Model Prob (%) | Skipped Picks | `Probability` | float 0–1 or None | May be None or string `"unavailable"` — handle gracefully |
| EV | Skipped Picks | `EV` | float or str or None | May be string `"unavailable"` — cast to float or None |
| Confidence | (absent) | — | — | Skipped picks have no Confidence column |
| Status | (computed) | `Gate Failed` | str | Render as `"Skip: MINIMUM EDGE"` (strip `"GATE N — "` prefix for display) |
| Gate Reason | Skipped Picks | `Reason` | str | Show in expanded tooltip or secondary line |

**Row filter:** `Date == today_str()`. No additional filter needed — GATE-1 "projection unavailable" rows are already suppressed during the write phase and do not appear in the sheet.

**Status column rendering rule:**
- Approved pick row: `"✓ Approved"`
- Skipped pick row: `"Skip: " + gate_failed.split(" — ", 1)[1]` where the part after `" — "` is the human gate name (e.g. `"MINIMUM EDGE"`, `"CONCENTRATION CAP"`)
- Dimmed/muted CSS class on skipped rows (e.g. `class="skipped-row"` with `opacity: 0.55`)

**Note on `Stat` column:** The Picks sheet and Skipped Picks sheet have no dedicated `Stat` column. The `Selection` / `Pick` field is a free-text string like `"Nasim Nuñez Over 0.5 Hits"`. Extract stat with: `re.search(r'(?:over|under)\s+[\d.]+\s+(.*)', text, re.IGNORECASE)` — group 1 is the stat. Returns empty for game picks (spreads/totals). Flag this as string-parsing tech-debt; render `Selection` as the primary display label if the stat parse fails.

### VIEW-02: Slips Page

**Authoritative source:** `data/pnl/master_pnl.xlsx` — Slip History sheet.
**Per-sport workbooks also have Slip History** but are 6 slips short (82 vs 88). Use master exclusively.
**Correlated Parlays source:** per-sport dated workbooks (`data/{sport}/{sport}_{date}.xlsx`), Correlated Parlays sheet. The Slip ID field in both sheets enables the join. In practice, Correlated Parlays rows are currently empty in the most recent workbooks — the derived fallback is the normal rendering path for Phase 2.

#### Slip History fields (all from `master_pnl.xlsx:Slip History`)

| Rendered Field | Exact Column Header | Type | Notes |
|----------------|---------------------|------|-------|
| Date | `Date` | str `YYYY-MM-DD` | Group/sort descending |
| Slip ID | `Slip ID` | str | Format: `"2026-06-08:correlated_upside:53254fd0"` — key for Correlated Parlays join |
| Platform | `Platform` | str `"PrizePicks"` (all current slips) | Display in summary row |
| Slip Type | `Slip Type` | str `"power"` / `"flex"` | Display in summary row |
| Legs (count) | `Number of Legs` | int | Summary row |
| Legs (detail) | `Legs` | str | Semicolon-delimited: `"Player stat OVER line; Player stat OVER line; ..."` — split on `"; "` to render individual legs |
| Status / Result | `Slip Result` | str `"GRADED"` / `"MANUAL REVIEW"` | Display in summary row. (WIN/LOSS also valid values per schema, but current data is GRADED/MANUAL REVIEW) |
| Payout | `Standard Payout Multiplier` | float or None | Fallback: `Estimated Payout Multiplier`. Note: Underdog entries have None — render as "n/a" |
| Net PnL | `Net PnL` | float or None | |
| Gross Return | `Gross Return` | float or None | May be 0 for losing slips |
| Winning Legs | `Winning Legs` | int or None | |
| Losing Legs | `Losing Legs` | int or None | |
| Demon/Goblin | `Contains Demon`, `Contains Goblin` | bool | Optional badge |
| Notes | `Notes` | str or None | Pass through to expanded row |

#### "Why Paired" Insight (D-07, two-tier)

**Tier 1 — Stored reasoning (Correlated Parlays sheet):**
- Join key: `Slip History["Slip ID"]` == `Correlated Parlays["Slip ID"]` in the per-sport workbook for that date
- Displayed fields: `Reasoning` (str, e.g. `"Two high-confidence same-team Underdog props; 0.5u correlated parlay cap"`) and `Correlation Group` (str, e.g. `"team:PHI"`)
- Source workbook: `data/{sport}/{sport}_{date}.xlsx` where `date` is extracted from the Slip ID prefix
- **Current reality:** Correlated Parlays sheet is empty in all inspected workbooks. Tier 1 matches will be rare; Tier 2 is the normal path for Phase 2.

**Tier 2 — Derived fallback:**
- Read the Slip ID category from the middle segment: `"2026-06-08:correlated_upside:53254fd0"` → category `"correlated_upside"`
- Category → human rationale mapping (hardcoded in accessor or template):
  - `correlated_upside` → "Correlated upside pair — same team, high-confidence"
  - `diversified` → "Diversified portfolio — avoids same-player overlap"
  - `highest_ev` → "Highest EV combination — top expected value legs"
  - `safest_2_leg` → "Safest 2-leg — highest model probability, positive EV"
  - `safest_3_leg` → "Safest 3-leg — three high-probability independent legs"
  - `kat_based` → "KAT anchor stack — correlated same-player props allowed"
  - (unknown) → "Independent legs / no correlation flagged — combined prob/EV shown"
- Show combined payout info from `Standard Payout Multiplier` as supplemental

### VIEW-03: History Page

#### W/L Overall + Per Sport — Source: `master_pnl.xlsx:Pick History`

| Rendered Field | Source | Column | Notes |
|----------------|--------|--------|-------|
| Overall W | Pick History | `Result == "WIN"` count | All rows |
| Overall L | Pick History | `Result == "LOSS"` count | All rows |
| Overall hit-rate % | Pick History | W / (W+L) | Excludes PENDING/VOID/MANUAL REVIEW from denominator |
| Overall ROI % | Pick History | sum(`PnL`) / sum(`Units`) | For graded rows only (exclude PENDING) |
| NBA W | Pick History | `Sport == "NBA"` AND `Result == "WIN"` | |
| NBA L | Pick History | `Sport == "NBA"` AND `Result == "LOSS"` | |
| MLB W | Pick History | `Sport == "MLB"` AND `Result == "WIN"` | |
| MLB L | Pick History | `Sport == "MLB"` AND `Result == "LOSS"` | |
| Total graded rows | Pick History | count where Result in (WIN, LOSS, PUSH) | |

**Pick History full column set (verified):** Date, Sport, Pick Ref, Result, Units, PnL, Graded At, Notes, Game, Actual, Platform, Player/Team, Pick, Pick Type, Line, Odds, **Confidence Tier**, Model Projection, Edge, Model Over Probability, EV, Edge Type Tags, CLV, Opening Line, Closing Line, Line Movement, Favorable Line Move 0.5+, Demon Available, Goblin Available, Injury Flag, Correlation Group, Slip ID, [market context fields...], Result Source, Result Confidence

**Result values seen in live data:** `WIN`, `LOSS`, `PUSH`, `PENDING`, `VOID`, `MANUAL REVIEW`

#### Per-Confidence-Tier Breakdown — Source: `master_pnl.xlsx:Pick History`

Tiers: `A`, `B`, `C`, `UNKNOWN` (None in sheet → treat as UNKNOWN)
Columns: `Confidence Tier`, `Result`, `PnL`, `Units`

| Display Column | Computation |
|----------------|-------------|
| Tier | `Confidence Tier` value |
| W-L | count WIN / count LOSS (excluding PENDING/VOID) |
| Hit-rate % | W / (W + L) |
| ROI % | sum(PnL) / sum(Units) for W+L rows |
| Sample n | total row count for tier |

**Live data sample (for test fixture calibration):**
- A-tier: 42 rows, 23W-10L, 69.7% hit, 21.9% ROI, 126u staked
- B-tier: 4 rows, 1W-2L, 33.3% hit, −49.6% ROI, 8u staked
- C-tier: 11 rows, 6W-2L, 75.0% hit, 40.5% ROI, 11u staked
- UNKNOWN: 224 rows, 82W-91L, 47.4% hit, −7.7% ROI, 228u staked

#### Bankroll/ROI Time Series (daily) — Source: `master_pnl.xlsx:Bankroll Chart Data`

| Column | Type | Notes |
|--------|------|-------|
| `Date` | str `YYYY-MM-DD` | X-axis labels |
| `Bankroll` | numeric | Y-axis primary (bankroll in units) |
| `ROI` | numeric (%) | Y-axis secondary or tooltip |
| `Updated At` | str ISO timestamp | For display/debug only |

**Live data:** 12 date points from 2026-06-08 to 2026-06-21. Points are NOT daily-consecutive (some dates have no entry — days without graded results). Chart.js handles sparse dates on a category axis (not a time axis) correctly.

#### Bankroll/ROI Time Series (weekly toggle) — Derived from `Bankroll Chart Data`

No separate weekly sheet exists. Aggregate in the read layer accessor:
- Group `Bankroll Chart Data` rows by ISO week (use `date.fromisoformat(d).isocalendar()`)
- Take the LAST row in each week as the week's closing bankroll
- ISO week key format: `"2026-W24"` (matching `metrics_report.py` convention)

**Do NOT import `metrics_report.py`** into the dashboard — it also reads per-sport workbooks and is designed for the runner's subprocess model. Duplicate the simple aggregation in `dashboard_data.py`.

## Reusable Accessors vs New Accessors

### Existing accessors (no changes needed)

| Function | Signature | What It Returns | Used By |
|----------|-----------|-----------------|---------|
| `read_json(path)` | `(Path) → dict\|list\|None` | Parsed JSON or None | All views (if JSON fast-path ever needed) |
| `read_sheet_rows(xlsx, sheet)` | `(Path, str) → list[dict]\|None` | Header-mapped rows or None on lock | All view accessors |
| `today_str()` | `() → str` | `"YYYY-MM-DD"` naive local | Today page workbook path |
| `write_in_progress()` | `() → bool` | Live lock signal | All three route handlers |
| `last_updated_hhmm()` | `() → str\|None` | `"HH:MM"` local time | All three route handlers |

### New accessors to add to `dashboard_data.py`

All three are read-only, return dicts/lists, never raise.

```python
def get_today_board(
    date: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Return approved picks and skipped picks for today across both sports.

    Returns:
        {
          "approved": [row_dict, ...],   # from Picks sheets, Status=="APPROVED"
          "skipped": [row_dict, ...],    # from Skipped Picks sheets
          "date": "YYYY-MM-DD",
          "locked": bool,                # True if any workbook returned None
        }
    Each row_dict includes a synthetic "status_label" key ("✓ Approved" or "Skip: GATE-NAME")
    and an "ev_float" key (EV coerced to float or None).
    """
```

```python
def get_all_slips() -> dict[str, Any]:
    """Return all slip history rows from master_pnl.xlsx Slip History sheet.

    Returns:
        {
          "slips": [row_dict, ...],  # sorted date descending
          "locked": bool,
        }
    Each row_dict includes a "why_paired" key (str): stored reasoning from
    Correlated Parlays if found, else derived from Slip ID category segment.
    Legs is raw string from sheet; UI splits on '; '.
    """
```

```python
def get_history_data() -> dict[str, Any]:
    """Return W/L + tier breakdown + chart series from master_pnl.xlsx.

    Returns:
        {
          "overall": {"W": int, "L": int, "push": int, "hit_pct": float|None, "roi_pct": float|None, "n": int},
          "by_sport": {"NBA": {...}, "MLB": {...}},
          "by_tier": {"A": {...}, "B": {...}, "C": {...}, "UNKNOWN": {...}},
          "chart_daily": {"labels": ["2026-06-08", ...], "bankroll": [...], "roi": [...]},
          "chart_weekly": {"labels": ["2026-W24", ...], "bankroll": [...], "roi": [...]},
          "locked": bool,
        }
    Each tier/sport dict: {"W": int, "L": int, "hit_pct": float|None, "roi_pct": float|None, "n": int}.
    """
```

**Rule:** Route handlers call these accessors. Route handlers do NOT read workbooks directly. Route handlers pass the result dict to `render_template`.

## Architecture Patterns

### Recommended Project Structure additions

```
scripts/
├── dashboard.py          # add /slips and /history routes (3 new functions)
├── dashboard_data.py     # add 3 new accessor functions
├── templates/
│   ├── base.html         # unchanged
│   ├── index.html        # replace placeholder with Today content
│   ├── slips.html        # new
│   └── history.html      # new
```

No new subdirectories. No new modules. No new static directory — CSS is inline in `base.html`; Chart.js is CDN.

### Pattern 1: Route handler structure (all three routes)

Every route must pass `write_in_progress` and `last_updated` because `base.html` renders the freshness badge in the nav. Currently only `/` does this; `/slips` and `/history` stubs do not exist.

```python
# Source: confirmed from dashboard.py and base.html (Phase 1)
@app.route("/")
def index() -> str:
    board = dashboard_data.get_today_board()
    return render_template(
        "index.html",
        board=board,
        write_in_progress=dashboard_data.write_in_progress(),
        last_updated=dashboard_data.last_updated_hhmm(),
    )

@app.route("/slips")
def slips() -> str:
    data = dashboard_data.get_all_slips()
    return render_template(
        "slips.html",
        data=data,
        write_in_progress=dashboard_data.write_in_progress(),
        last_updated=dashboard_data.last_updated_hhmm(),
    )

@app.route("/history")
def history() -> str:
    data = dashboard_data.get_history_data()
    return render_template(
        "history.html",
        data=data,
        write_in_progress=dashboard_data.write_in_progress(),
        last_updated=dashboard_data.last_updated_hhmm(),
    )
```

### Pattern 2: Passing Chart.js data from server to client

The `{% block scripts %}` slot in `base.html` is reserved exactly for this. Pass the series as JSON-serialized strings in the Jinja template, then initialize Chart.js from them.

```html
{# In history.html — Source: base.html {% block scripts %} slot #}
{% block scripts %}
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js"
        integrity="sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ"
        crossorigin="anonymous"></script>
<script>
  const dailyLabels = {{ data.chart_daily.labels | tojson }};
  const dailyBankroll = {{ data.chart_daily.bankroll | tojson }};
  const weeklyLabels = {{ data.chart_weekly.labels | tojson }};
  const weeklyBankroll = {{ data.chart_weekly.bankroll | tojson }};
  // ... Chart.js initialization
</script>
{% endblock %}
```

**Note:** `tojson` is Jinja2's built-in filter (Flask bundles Jinja2 with `tojson` already available — no additional config needed).

### Pattern 3: Client-side filter/sort (Today page)

**Recommendation: client-side vanilla JS.** Rationale: the daily dataset is bounded (≤~200 rows per day — approved + skipped picks), the filter state is ephemeral (not bookmarkable or shared), and server round-trips would require query-param parsing on a GET route. A simple JS function over `<tr>` elements with `data-` attributes is 20–30 lines and needs no library.

```html
<!-- Source: discretion (D-03 Today layout) -->
<input id="filter-platform" value="All">
<input id="filter-sport" value="All">
<input id="filter-status" value="All">
<table id="today-table">
  <thead><tr>
    <th data-col="ev" onclick="sortTable('ev')">EV ▼</th>
    <!-- ... -->
  </tr></thead>
  <tbody>
    {% for row in board.approved + board.skipped %}
    <tr data-platform="{{ row.Platform }}"
        data-sport="{{ row.Sport }}"
        data-status="{{ 'approved' if row.status_label.startswith('✓') else 'skipped' }}"
        {% if row.status_label.startswith('Skip') %}class="skipped-row"{% endif %}>
      <!-- cells -->
    </tr>
    {% endfor %}
  </tbody>
</table>
```

The JS reads `data-` attributes on `<tr>` elements and toggles `display:none` based on filter values. Sort mutates the `<tbody>` child order by comparing numeric data attributes.

### Pattern 4: Expandable rows (Slips page)

Use a sibling `<tr class="slip-detail">` that is hidden by default and revealed by a click on the summary row. No nested tables — use a `<td colspan="N">` for the detail content.

```html
<!-- For each slip: -->
<tr class="slip-summary" onclick="toggleSlip(this)">
  <td>{{ slip.Date }}</td>
  <td>{{ slip['Slip Result'] }}</td>
  <!-- ... compact fields ... -->
</tr>
<tr class="slip-detail" style="display:none">
  <td colspan="7">
    <div class="slip-legs">{% for leg in slip.legs_list %}...{% endfor %}</div>
    <div class="why-paired">{{ slip.why_paired }}</div>
  </td>
</tr>
```

### Anti-Patterns to Avoid

- **Reading workbooks from route handlers directly:** Always go through `dashboard_data` accessor functions. Route handlers must not call `read_sheet_rows` or `safe_load_workbook`.
- **Using Jinja to compute aggregations:** Data shaping (W/L counts, ROI %, tier bucketing, chart series) belongs in `dashboard_data.py` accessors, not in Jinja templates.
- **Importing `metrics_report.py` into the dashboard:** It uses `safe_load_workbook` in a subprocess model; its `aggregate_slip_roi_by_week_sport` reads per-sport workbooks. Keep the dashboard read layer self-contained.
- **Using `datetime.now(ZoneInfo(...))` in `dashboard_data.py`:** The module must never import `zoneinfo` (tested in `test_dashboard_data.py:TestTodayMatchesRunner`). Naive local time only.
- **Joining Picks to Props via Projection ID for stat:** Projection ID is not in the Picks sheet. Parse stat from `Selection` string or show `Selection` as the full pick label.
- **Reading Daily Log for per-sport W/L:** Daily Log `Sport` values are `"SLIPS"` not `"NBA"/"MLB"`. Use Pick History for sport-level W/L.
- **Reading per-sport workbooks for slip history:** Use `master_pnl.xlsx:Slip History` exclusively (it is the superset; 6 slips from early dates exist only in master).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON escaping in Jinja → JS | Manual string concatenation | `{{ value \| tojson }}` | Jinja2 built-in; handles Unicode, special chars, None |
| Chart rendering | Custom SVG/canvas drawing | Chart.js CDN | One `<script>` tag; handles responsive, tooltips, axes |
| HTML escaping in templates | Manual `str.replace` | Jinja2 autoescaping | Flask enables it by default; prevents XSS |
| ISO-week computation | Custom date math | `date.fromisoformat(d).isocalendar()` | stdlib; `.isocalendar().week` returns ISO week number |
| CSS dark theme | Custom CSS design system | Pico.css (CDN, already in `base.html`) | Already installed; `data-theme="dark"` |

## Lock-Tolerance / Empty-State Behavior

### When `read_sheet_rows` returns None (mid-write lock)

Each view accessor must handle the `None` return:

```python
# In get_today_board():
rows = dashboard_data.read_sheet_rows(xlsx_path, "Picks")
if rows is None:
    # Workbook locked — serve last-known-good + set locked=True
    # For first load with no cache, return empty list (not an error)
    locked = True
    approved = []
```

The `locked=True` signal propagates to `render_template` context. The template checks `{% if board.locked %}` and shows "Data is updating..." alongside whatever data was returned (empty on first load or partial from prior read). The `write_in_progress` badge in `base.html` is the primary user-facing signal; the per-view lock state is a secondary fallback.

### Empty states per view

| View | Condition | Rendering |
|------|-----------|-----------|
| Today | No workbook for today's date | "No evaluated picks for {date} — the pipeline may not have run yet." |
| Today | Workbook exists but empty Picks + Skipped Picks | "No evaluated picks found for {date}." |
| Slips | `master_pnl.xlsx` missing or Slip History empty | "No slips recorded yet." |
| History | `master_pnl.xlsx` missing or Bankroll Chart Data empty | Show W/L tables if Pick History has data; omit chart with "No chart data yet." |
| Any view | `locked=True` AND empty data | Show "Data is updating..." prominently. |

### No-games-today state

If both sport workbooks exist but have no approved picks today (e.g. NBA off-season), show the Skipped Picks rows with a note "No approved picks today." The Today page still renders value by showing what was evaluated and why it was skipped.

## Common Pitfalls

### Pitfall 1: Naive date midnight mismatch
**What goes wrong:** `datetime.now(ZoneInfo("America/Los_Angeles"))` returns a different date from `datetime.now()` near midnight Pacific time. The Today view loads the wrong sport workbook.
**Why it happens:** The runner uses `datetime.now().strftime("%Y-%m-%d")` (naive local). The dashboard must use the same.
**How to avoid:** Import `dashboard_data.today_str()` — never re-derive the date in route handlers. Never import `zoneinfo` into `dashboard_data.py` (test `test_today_matches_runner` guards this).
**Warning signs:** Today page shows "no picks" even when the pipeline ran.

### Pitfall 2: EV field is not always numeric
**What goes wrong:** `Skipped Picks["EV"]` can be the string `"unavailable"` (set by `ev_display()` in the runner). Sorting by EV fails with a type error.
**Why it happens:** The runner writes `"unavailable"` for picks where EV cannot be computed.
**How to avoid:** Coerce EV to float in the accessor: `ev_float = float(row["EV"]) if row.get("EV") not in (None, "", "unavailable") else None`. Use `ev_float` for sort ordering (place `None` last). Tag this field as `ev_float` in the returned dict.
**Warning signs:** JS sort throws on non-numeric comparison, or the default EV sort silently breaks.

### Pitfall 3: `Probability` in Skipped Picks may be None or the string `"unavailable"`
**What goes wrong:** Similar to EV — `Probability` can be `None` or a string.
**How to avoid:** Same float-coercion pattern as EV.

### Pitfall 4: Slip History `Legs` is a semicolon-delimited string, not a list
**What goes wrong:** Trying to iterate over `slip["Legs"]` character by character.
**How to avoid:** In the accessor, split: `slip["legs_list"] = str(slip.get("Legs") or "").split("; ")`. Filter empty strings.

### Pitfall 5: `Confidence Tier` in Pick History is None for ~78% of historical rows
**What goes wrong:** Treating UNKNOWN tier as "no data" and hiding the tier row in the breakdown.
**Why it happens:** Pre-v2.0 picks did not record Confidence Tier. They are legitimately graded picks.
**How to avoid:** Coerce `None` → `"UNKNOWN"` explicitly. Show UNKNOWN tier in the breakdown as a fourth row labeled "Unknown / pre-v2.0". ROI for UNKNOWN tier is meaningful and should be shown.

### Pitfall 6: Master Slip History vs Per-Sport Slip History discrepancy
**What goes wrong:** Reading per-sport workbooks for the Slips page (82 unique IDs) instead of master (88). Six early NBA slips from 2026-06-08 and 2026-06-10 exist only in master.
**How to avoid:** Always use `data/pnl/master_pnl.xlsx:Slip History` for the Slips page. Do not aggregate per-sport workbook Slip History sheets.

### Pitfall 7: Correlated Parlays join currently returns empty
**What goes wrong:** Accessor tries to join Slip ID → Correlated Parlays and finds no match (all Correlated Parlays sheets in current workbooks are empty). If the accessor crashes on no-match, the Slips page breaks entirely.
**How to avoid:** Always fall through to Tier 2 derived reasoning when Tier 1 returns nothing. No exception on no-match.

### Pitfall 8: Chart.js data serialization with None values
**What goes wrong:** Python `None` serializes as JSON `null`, but Chart.js interprets `null` as "skip point" (gap in line). This is actually correct behavior — gaps in Bankroll Chart Data are real no-data days.
**How to avoid:** This is fine. Use `| tojson` filter in Jinja. Verify Chart.js `spanGaps: false` is the default for line charts (it is) — gaps will show correctly as breaks.

### Pitfall 9: `write_in_progress` and `last_updated` missing from /slips and /history routes
**What goes wrong:** `/slips` and `/history` route templates extend `base.html`, which renders `{% if write_in_progress %}` in the nav — but if the route handler doesn't pass this context var, Jinja raises `UndefinedError` in strict mode or silently renders nothing in lenient mode.
**How to avoid:** Every route handler that renders a template extending `base.html` must pass `write_in_progress=...` and `last_updated=...`.

### Pitfall 10: `data/nxls_schema.txt` is stale relative to actual schema
**What goes wrong:** `nxls_schema.txt` documents an early version of the workbook schema (6 sheets, simplified columns). The actual workbooks have 12 sheets and ~45 columns in Picks. Trusting `nxls_schema.txt` alone leads to wrong column names.
**How to avoid:** Always use the runner's module-level header constants (`PICKS_HEADERS`, `SKIPPED_PICK_HEADERS`, etc.) as the authoritative contract. The actual workbooks were verified against these constants and match (except three additive columns: `ESPN Spread`, `ESPN Total`, `Win Probability %` added after the constant was defined).

### Pitfall 11: CDN `<script>` tag without Subresource Integrity (SRI)
**What goes wrong:** Loading Chart.js from a CDN without an `integrity` hash means a compromised CDN could serve malicious JS that runs in the browser under the same origin as the dashboard. Even though this is a localhost tool, it is still good practice — and the SRI hash was computed during research.
**Why it happens:** Omitting `integrity=` and `crossorigin=` attributes (common in quick CDN snippets).
**How to avoid:** Always use the pinned URL with its verified SHA-384 hash:
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1/dist/chart.umd.min.js"
        integrity="sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ"
        crossorigin="anonymous"></script>
```
The hash was verified during research by computing `sha384(curl cdn_url) | base64`. Re-verify if Chart.js version is bumped.
**Warning signs:** Browser DevTools shows a "Failed Subresource Integrity check" error — this would mean the CDN file changed after the hash was computed (possible CDN tampering or version slip).

## Validation Architecture

`workflow.nyquist_validation` is `true` in `.planning/config.json` — this section is required.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 (test discovery) + `unittest.TestCase` (base class) |
| Config file | none — pytest discovers `test_*.py` from `scripts/` |
| Quick run command | `cd scripts && python3 -m pytest test_dashboard.py test_dashboard_data.py -x` |
| Full suite command | `cd scripts && python3 -m pytest test_dashboard.py test_dashboard_data.py test_dashboard_views.py -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| VIEW-01 | `get_today_board()` returns approved picks from Picks sheet, date-filtered | unit | `python3 -m pytest test_dashboard_views.py::TestTodayBoard::test_approved_picks -x` | ❌ Wave 0 |
| VIEW-01 | `get_today_board()` returns skipped picks with `status_label = "Skip: GATE-NAME"` | unit | `python3 -m pytest test_dashboard_views.py::TestTodayBoard::test_skipped_picks_gate_label -x` | ❌ Wave 0 |
| VIEW-01 | `get_today_board()` returns `locked=True` when `read_sheet_rows` returns None | unit | `python3 -m pytest test_dashboard_views.py::TestTodayBoard::test_locked_state -x` | ❌ Wave 0 |
| VIEW-01 | `GET /` returns 200 and HTML contains `EV` column header | route smoke | `python3 -m pytest test_dashboard_views.py::TestRoutes::test_index_200 -x` | ❌ Wave 0 |
| VIEW-01 | `ev_float` is None for skipped picks with EV="unavailable" | unit | `python3 -m pytest test_dashboard_views.py::TestTodayBoard::test_ev_coercion -x` | ❌ Wave 0 |
| VIEW-02 | `get_all_slips()` returns all slips from master_pnl sorted date-descending | unit | `python3 -m pytest test_dashboard_views.py::TestSlipsAccessor::test_slips_sorted -x` | ❌ Wave 0 |
| VIEW-02 | `get_all_slips()` populates `why_paired` from Slip ID category segment | unit | `python3 -m pytest test_dashboard_views.py::TestSlipsAccessor::test_why_paired_derived -x` | ❌ Wave 0 |
| VIEW-02 | `get_all_slips()` splits `Legs` string on `"; "` into `legs_list` | unit | `python3 -m pytest test_dashboard_views.py::TestSlipsAccessor::test_legs_parsed -x` | ❌ Wave 0 |
| VIEW-02 | `GET /slips` returns 200 and HTML contains at least one slip row | route smoke | `python3 -m pytest test_dashboard_views.py::TestRoutes::test_slips_200 -x` | ❌ Wave 0 |
| VIEW-03 | `get_history_data()` returns correct tier breakdown (A/B/C/UNKNOWN) from fixture | unit | `python3 -m pytest test_dashboard_views.py::TestHistoryAccessor::test_tier_breakdown -x` | ❌ Wave 0 |
| VIEW-03 | `get_history_data()` returns `chart_daily` with correct labels and bankroll series | unit | `python3 -m pytest test_dashboard_views.py::TestHistoryAccessor::test_chart_daily -x` | ❌ Wave 0 |
| VIEW-03 | `get_history_data()` aggregates `chart_weekly` by ISO week (last point) | unit | `python3 -m pytest test_dashboard_views.py::TestHistoryAccessor::test_chart_weekly -x` | ❌ Wave 0 |
| VIEW-03 | `GET /history` returns 200 and HTML contains Chart.js script tag | route smoke | `python3 -m pytest test_dashboard_views.py::TestRoutes::test_history_200 -x` | ❌ Wave 0 |
| VIEW-03 | `Confidence Tier = None` is treated as `UNKNOWN` tier in breakdown | unit | `python3 -m pytest test_dashboard_views.py::TestHistoryAccessor::test_none_tier_as_unknown -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `cd scripts && python3 -m pytest test_dashboard.py test_dashboard_data.py -x`
- **Per wave merge:** `cd scripts && python3 -m pytest test_dashboard.py test_dashboard_data.py test_dashboard_views.py -x`
- **Phase gate:** Full suite green: `cd scripts && python3 -m pytest -x` before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `scripts/test_dashboard_views.py` — new test file covering all VIEW-* requirements above
  - Class `TestTodayBoard` — unit tests for `get_today_board()` using synthetic in-memory workbooks (pattern from `test_dashboard_data.py:_make_picks_wb`)
  - Class `TestSlipsAccessor` — unit tests for `get_all_slips()` using in-memory workbook
  - Class `TestHistoryAccessor` — unit tests for `get_history_data()` using in-memory workbook
  - Class `TestRoutes` — route smoke tests using `dashboard.app.test_client()`

Existing test infrastructure (`test_dashboard.py`, `test_dashboard_data.py`) covers Phase 1 DASH-* requirements. Phase 2 adds `test_dashboard_views.py` to the same `scripts/` directory in the same `unittest.TestCase` style.

## Security Domain

`security_enforcement` is not explicitly set in `.planning/config.json` — treat as enabled.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | Localhost-only; no auth required (documented assumption per design doc §8) |
| V3 Session Management | No | No sessions; all pages are GET with no state |
| V4 Access Control | No | 127.0.0.1 bind is the only access control needed (DASH-03) |
| V5 Input Validation | Minimal | No user input in Phase 2 — pure GET rendering. Query params for future filter/sort if server-side, but Phase 2 uses client-side JS. |
| V6 Cryptography | No | No crypto in this phase |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| XSS via workbook content injected into HTML | Tampering | Jinja2 autoescaping (enabled by default in Flask) — all `{{ var }}` expressions are HTML-escaped |
| Path traversal in workbook path construction | Tampering | Paths are hardcoded: `DATA / "nba" / f"nba_{date}.xlsx"` — date is from `today_str()` (not user input), never from query params |
| Reading outside localhost | Information disclosure | `dashboard.HOST = "127.0.0.1"` — DASH-03 constraint; assertted in `test_loopback_only` |

The security posture is low-risk for a solo-operator localhost tool. No new attack surface is added in Phase 2 (GET-only routes, no writes, no user input).

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| `data/nxls_schema.txt` (early schema doc) | Runner module constants `PICKS_HEADERS`, `SKIPPED_PICK_HEADERS`, etc. | Schema doc is stale; always use constants as contract |
| Confidence Tier absent from old picks | `Confidence Tier` column in Pick History (A/B/C/UNKNOWN) | UNKNOWN covers pre-v2.0 picks; must be shown in breakdown, not hidden |
| Correlated Parlays populated during build_slips | Currently empty in all recent workbooks | Tier-2 derived reasoning is the normal path for Phase 2; Tier-1 is aspirational |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Correlated Parlays sheet is effectively empty in current workbooks; derived Tier-2 reasoning is the normal Slips page path | VIEW-02 mapping | If populated, Tier-1 join logic must be correct — but this only adds value, never breaks Tier-2 fallback |
| A2 | `master_pnl.xlsx:Slip History` is the superset of all per-sport Slip History sheets | VIEW-02 mapping | If master is ever out of sync (missing slips), Slips page would be incomplete |
| A3 | Chart.js v4 CDN URL is stable and resolves from the operator's Mac | VIEW-03 chart | CDN outage would break chart; CDN URL should be pinned to a specific version tag |

**If this table has only 3 entries:** All other claims in this research were verified or cited against live workbooks and source constants.

## Open Questions

1. **Stat column for Today page**
   - What we know: No `Stat` column in Picks or Skipped Picks sheets. `Selection`/`Pick` is a free-text string.
   - What's unclear: Whether the planner wants a parsed `Stat` column or prefers `Selection` as the complete display label.
   - Recommendation: Use `Selection` as the primary display label (always correct). Optionally show parsed stat in a tooltip. Mark stat parsing as tech-debt (D-01 evaluated set contains both prop and game picks; game picks have no stat).

2. **"Updating..." badge freshness on /slips and /history**
   - What we know: `write_in_progress()` and `last_updated_hhmm()` are called per-request on `/` today. They must be added to `/slips` and `/history`.
   - What's unclear: Whether to create a shared helper that returns both context vars (DRY) or inline the calls in each route.
   - Recommendation: Create a private `_freshness_context() → dict` helper in `dashboard.py` that returns `{"write_in_progress": ..., "last_updated": ...}`; call it in all three routes.

3. **Chart.js CDN version pinning and SRI**
   - What we know: `base.html` does not load Chart.js — the slot is reserved but empty. History.html will be the first to load it. The SHA-384 SRI hash for Chart.js 4.5.1 was verified during research: `sha384-jb8JQMbMoBUzgWatfe6COACi2ljcDdZQ2OxczGA3bGNeWe+6DChMTBJemed7ZnvJ` (jsDelivr resolves `@4` → `4.5.1` as of 2026-06-24; same hash for both URLs).
   - What's unclear: Nothing — version and hash are locked.
   - Recommendation: Pin to `chart.js@4.5.1` with the verified SRI hash (see Pitfall 11 and Pattern 2 for the exact `<script>` tag). Update hash if version is bumped.

## Environment Availability

No external dependencies beyond what Phase 1 verified. All tools available.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Flask | `/`, `/slips`, `/history` routes | ✓ | 3.1.3 | — (verified Phase 1) |
| Jinja2 | Template rendering | ✓ | 3.1.6 | — |
| openpyxl | Workbook reads | ✓ | 3.1.5 | — |
| Chart.js | History chart | CDN-only | v4.x | No chart if CDN down |
| `master_pnl.xlsx` | Slips + History data | ✓ | 12 bankroll points, 88 slips, 281 pick rows | "No data yet" empty state |
| per-sport xlsx files | Today board data | ✓ | nba_2026-06-08..23, mlb_2026-06-08..23 | "No picks for today" empty state |

## Sources

### Primary (HIGH confidence)
- Live workbook inspection via `openpyxl` — all header constants, all data values, all sheet names confirmed from actual files in `data/`
- `scripts/sports_system_runner.py` lines 277–295 — `PICKS_HEADERS`, `SKIPPED_PICK_HEADERS`, `PARLAY_HEADERS` constants (source of truth)
- `scripts/slip_payouts.py` lines 18–24 — `SLIP_HISTORY_HEADERS` constant
- `scripts/dashboard_data.py` — all existing accessor function signatures and return contracts
- `scripts/dashboard.py` — existing route structure and confirmed absence of `/slips`, `/history`
- `scripts/templates/base.html` — confirmed `{% block scripts %}` slot, `write_in_progress`/`last_updated` template vars, nav links
- `scripts/templates/index.html` — confirmed placeholder content (Phase 1 stub)
- `data/pnl/bankroll.json` — confirmed structure (`current_bankroll`, `roi_percentage_current`, etc.)
- `data/pnl/master_pnl.xlsx` — confirmed 7 sheets, all header rows, 88 slip rows, 281 pick history rows, 12 chart data points
- `scripts/metrics_report.py` — ISO-week aggregation pattern (reused logic for weekly chart)

### Secondary (MEDIUM confidence)
- `docs/superpowers/specs/2026-06-23-localhost-dashboard-design.md` §1, §5, §10 — approved design spec
- `.planning/phases/02-read-views/02-CONTEXT.md` — all D-* decisions (user-locked)
- `.planning/phases/01-foundation-data-layer/01-RESEARCH.md` — Phase 1 findings (no re-derivation needed)

### Tertiary (LOW confidence)
- None. All critical claims verified from source.

## Metadata

**Confidence breakdown:**
- Data-source mapping: HIGH — directly verified from live workbook reads and runner constants
- New accessor signatures: HIGH — derived from confirmed data shapes, mirror existing `dashboard_data.py` patterns
- Client-side JS recommendation: MEDIUM — based on dataset size analysis; planner may choose server-side
- Correlated Parlays join logic: MEDIUM — schema is confirmed but no live data in current workbooks to test against

**Research date:** 2026-06-24
**Valid until:** 2026-07-24 (stable schema; runner header constants are in version control)
