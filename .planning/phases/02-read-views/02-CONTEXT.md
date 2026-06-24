# Phase 2: Read Views - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Three **rendered, read-only pages** served by the Phase 1 Flask shell over the Phase 1 read-only data layer (`scripts/dashboard_data.py`) — **Today**, **Slips**, and **History**. Delivers VIEW-01..03. No new persistence, no writes, no betting-logic touch; this phase only *reads and renders* already-persisted workbook + JSON data. The routes (`/`, `/slips`, `/history`) and nav are already wired in `scripts/templates/base.html`; this phase fills the three page bodies plus any small template partials and the read-layer accessor functions they need.

**Explicitly NOT this phase:** the safe write actions (refresh/re-run, mark-placed, add-note) are Phase 3 (ACTION-*); the foundation/app-shell/data-layer is Phase 1 (DASH-*, done); future Calibration/Line-change/Live tabs are later milestones (TAB-*).

</domain>

<decisions>
## Implementation Decisions

### Today page — scope (VIEW-01)
- **D-01:** The Today page is a **model-transparency board, not a betting slip.** It shows the **evaluated set** = approved picks **plus** skipped/no-bet candidates, each skip tagged with the **gate that rejected it** (from the Skipped Picks sheet's gate/reason field). Rationale: directly serves the project's core value — "can I tell whether the model is improving" — by exposing what the gauntlet saw and why it rejected near-misses.
- **D-02:** "Whole board" means the **evaluated set only** — props the model actually scored (have a projection → became an approved pick or a skipped pick). It does **NOT** include the full raw Props-sheet dump (hundreds of unscored props with no EV). Every rendered row carries meaningful EV/prob/edge/confidence numbers.

### Today page — layout (VIEW-01)
- **D-03:** **One dense, sortable master table** (not visually grouped sections). Columns include Platform, Sport, and Status alongside player/stat/line, projection, edge, **+EV**, **model probability**, confidence. A **top filter bar** (platform / sport / approved-vs-skipped) plus **click-to-sort headers**, default sort **EV descending**. This resolves VIEW-01's internal tension ("grouped by platform & sport" *and* "filter/sort by EV") by making **grouping = filtering** while preserving a true global sort. Fits the locked dark dense-table aesthetic (Phase 1 D-05).
- **D-04:** Approved vs skipped distinguished by a **Status column** (`✓ Approved` or `Skip: <Gate>`) with **skipped rows visually dimmed/muted** so approved picks pop. Gate reason is shown inline in the Status column.

### Slips page (VIEW-02)
- **D-05:** Default view is **all slips, grouped by date descending** (today at top) — "see every slip" taken literally. A date/status filter narrows it. (Not paginated/recent-only for v1; the slip count is small enough — ~88 across 12+ dates — to list all.)
- **D-06:** Each slip renders as an **expandable row**: a compact summary row (date, sport, status, payout, # legs, combined prob/EV) that **expands on click** to reveal the legs + the "why paired" insight. Keeps an all-time list scannable with detail on demand.
- **D-07:** "Why paired" insight is **two-tier** (locked by the design doc, restated): show the **stored Correlated Parlays `Reasoning` + `Correlation Group`** when present; otherwise show a **derived rationale** (same game/team, combined prob/EV) for general slips. Richer/quantified correlation modeling is explicitly a later enhancement, not v1 (design doc §10).

### History page (VIEW-03)
- **D-08:** The bankroll/ROI time-series chart supports **both daily and weekly** views via a toggle. **Daily bankroll line is the default** (one point/day since inception 2026-06-08, sourced from the persisted "Bankroll Chart Data" / Daily Log), with a toggle to an **ISO-week aggregated** view that mirrors the existing `metrics_report` weekly framing. Chart.js via CDN (Phase 1 D-06).
- **D-09:** The **per-confidence-tier breakdown** shows, per tier: **record (W-L)**, **hit-rate %**, **ROI %**, and **sample count**. This is the calibration signal — "do higher-confidence tiers actually win/profit more." Plus the required **W/L overall and per sport**.

### Claude's Discretion
- **Filter/sort implementation** — client-side vanilla JS (no build toolchain, daily data is small) vs server-side query-params. Leaning client-side to keep it snappy and dependency-free, but planner/executor decide. No new JS bundler either way.
- **Empty / no-games-today states** — graceful "no evaluated picks for {today}" / "no slips yet" messaging rather than blank pages. Exact copy is discretion.
- **Number formatting** — EV/probability/hit-rate/ROI as `%`, edge in its native unit; optional subtle color cue for +EV vs −EV. Keep glanceable; exact treatment is discretion.
- **Derived "why paired" fallback for truly independent legs** (no stored reasoning, not same-game/team) — surface combined prob/EV and note "independent legs / no correlation flagged" rather than inventing a rationale.
- **Exact source-sheet/column mapping** for each view (which sheet, which header constant) — the researcher confirms against `data/nxls_schema.txt` and the runner's header constants; planner locks it.
- **Route/template/partial structure**, sortable-table mechanism, expandable-row mechanism — discretion within the existing `base.html` shell.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Design & requirements (read first)
- `docs/superpowers/specs/2026-06-23-localhost-dashboard-design.md` §5 (Pages), §1 "Data already persisted (verified)" table, §10 (Risks — "why paired" depth is v1-bounded) — the APPROVED authoritative spec for these three pages.
- `.planning/REQUIREMENTS.md` — VIEW-01, VIEW-02, VIEW-03 (this phase) and the v3.0 Out-of-Scope table (no control panel, no auth, no websockets, no mobile).
- `.planning/ROADMAP.md` → "Phase 2: Read Views" — goal + 5 success criteria (the verification bar).

### Prior-phase context (the foundation this phase renders through)
- `.planning/phases/01-foundation-data-layer/01-CONTEXT.md` — locked decisions carried forward: dark dense tables + Pico.css (D-05), Chart.js via CDN (D-06), fresh-read-every-load + JSON-first (D-03), freshness badge / "last updated HH:MM" already in nav (D-01/D-02), run from `scripts/` with `python3`.

### Key source to read / reuse
- `scripts/dashboard_data.py` — the **Phase 1 read layer** the views consume: `read_json` (lock-free JSON), `read_sheet_rows(xlsx, sheet)` (lock-tolerant, returns `None` on lock = serve last-known-good), `today_str()` (pipeline-matching naive-local date), `write_in_progress()`, `last_updated_hhmm()`. Phase 2 adds view-shaping accessors here, keeping it strictly read-only.
- `scripts/dashboard.py` — the Flask app; add the `/`, `/slips`, `/history` route bodies (nav already points at them).
- `scripts/templates/base.html` — the dark Pico shell + nav + freshness badges + reserved Chart.js `{% block scripts %}` slot. Extend, don't replace.
- `scripts/sports_system_runner.py` — sheet header constants (`PICKS_HEADERS`, `PROPS_HEADERS`, `PARLAY_HEADERS`, Skipped-Picks/Slip-History headers) = the column contract the views map against; gate names emitted into skip records (for the Status column); `confidence_tier` semantics.
- `scripts/workbook_io.py` — `safe_load_workbook(read_only=True)` underpins `read_sheet_rows`; tolerate `WorkbookAccessError`.
- `data/nxls_schema.txt` — canonical sheet/column contract; confirm exact sheet names (Picks, Props, Skipped Picks, Slip History, Correlated Parlays) and columns before mapping.

### Data sources per view (confirm exact columns during research)
- **Today:** per-sport workbooks `data/{nba,mlb}/{sport}_{date}.xlsx` → Picks (approved) + Skipped Picks (no-bet + gate) sheets; columns `Model Over Probability`, `EV`, `Edge`, `Confidence`.
- **Slips:** Slip History sheet (master + per-day) + Correlated Parlays sheet (`Reasoning`, `Correlation Group`).
- **History:** `data/pnl/master_pnl.xlsx` (Pick History / Daily Log / Performance Breakdown), `data/pnl/bankroll.json`, the "Bankroll Chart Data" series; `metrics_report.py` for the ISO-week × sport framing.

### Codebase maps (background)
- `.planning/codebase/ARCHITECTURE.md` (persistence + atomic-save model), `.planning/codebase/STRUCTURE.md` (where `data/` artifacts live), `.planning/codebase/CONVENTIONS.md` (naming/type/style to match).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Phase 1 read layer (`dashboard_data.py`)** is the whole data substrate — `read_json` for the lock-free JSON fast path, `read_sheet_rows` for lock-tolerant sheet reads (returns `None` → render last-known-good, never crash), `today_str()` to match the pipeline's "today", and the freshness signals already surfaced in the nav. Phase 2 should add view accessors here rather than reading workbooks from route handlers.
- **`base.html` shell** already provides the dark Pico theme, density CSS, the Today/Slips/History nav links, the updating/last-updated badges, and a reserved `{% block scripts %}` for Chart.js. Pages extend it.
- **Runner sheet-header constants** are the source-of-truth column contracts; map view columns against them, not hardcoded strings.

### Established Patterns
- **JSON-first, workbook-fallback, lock-tolerant** reads (Phase 1 D-01/D-03): prefer `bankroll.json` / latest props JSON; hit workbooks `read_only=True`; on a mid-write lock, serve last-known-good + the "updating…" badge already in the nav.
- **Pacific/naive-local `today_str()`** defines the Today page's "today" — reuse the Phase 1 function, don't reintroduce a timezone import.
- **Dark dense tables over cards** (Phase 1 D-05) — the data-heavy aesthetic the three views inherit.

### Integration Points
- Pages are **GET-only routes** on the existing standalone `scripts/dashboard.py` process — no cron path, no runner import, zero betting-pipeline impact. Reads only.
- The History chart loads **Chart.js via CDN** into the reserved `{% block scripts %}`; data is passed from the route (server-computed series) to the client chart.

</code_context>

<specifics>
## Specific Ideas

- The operator explicitly wants the Today page to expose **why the gauntlet rejected things**, not just what to bet — the skipped picks + their gate are a first-class part of the view (D-01/D-04). This is the dashboard's contribution to "can I tell whether the model is improving."
- The per-tier breakdown should make **calibration legible** (does confidence predict outcome) — hence W/L + hit-rate + ROI + count together (D-09), not just one metric.
- "See *every* slip" was taken literally for v1 (all, newest-first) — the operator values completeness over a trimmed recent view at this scale (D-05).

</specifics>

<deferred>
## Deferred Ideas

- **Quantified leg-correlation modeling** for the "why paired" insight (variance/correlation coefficients) — design doc §10 marks it a later enhancement, not v1.
- **Calibration / Line-changes / Live tabs** (TAB-01..03) — later milestones M2–M4; the nav already has inert stubs from Phase 1.
- **Safe write actions** (refresh/re-run, mark-placed, add-note) — Phase 3 (ACTION-*); the Slips/Today rows this phase renders are where Phase 3 will attach those buttons, but no writes here.
- **Pagination / recent-window default** for Slips — not needed at ~88 slips; revisit if the all-time list grows unwieldy over months.
- None of these are scope creep into Phase 2 — discussion stayed within the read-views boundary.

</deferred>

---

*Phase: 2-Read Views*
*Context gathered: 2026-06-24*
