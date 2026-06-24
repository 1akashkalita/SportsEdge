# Phase 2: Read Views - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-24
**Phase:** 2-Read Views
**Areas discussed:** Today board scope, Today layout, Slips default scope, History detail & chart

---

## Today board scope

### What should the Today page actually show?

| Option | Description | Selected |
|--------|-------------|----------|
| Whole board + reasons | Approved picks plus skipped/no-bet candidates, each tagged with the gate that killed it (Skipped Picks sheet) | ✓ |
| Approved picks only | Only gate-passed bettable picks; cleanest but loses near-miss visibility | |
| Approved + skipped, toggle | Default approved, filter reveals skipped on demand | |

**User's choice:** Whole board + reasons
**Notes:** Page is a model-transparency board, not a betting slip — serves "can I tell whether the model is improving."

### How wide is "the whole board"?

| Option | Description | Selected |
|--------|-------------|----------|
| Evaluated set only | Only props the model actually scored — approved + skipped picks; every row has meaningful numbers | ✓ |
| Everything fetched | Include all raw Props-sheet props even with no projection/EV; noisy | |
| Evaluated + raw toggle | Default evaluated set, toggle reveals full raw universe | |

**User's choice:** Evaluated set only
**Notes:** Excludes the hundreds of unscored raw props; keeps every rendered row meaningful.

---

## Today layout

### How should the Today board be laid out?

| Option | Description | Selected |
|--------|-------------|----------|
| One sortable table | Single dense table with Platform/Sport/Status columns + filter bar + click-to-sort, default EV desc | ✓ |
| Grouped sections | Visual Platform → Sport sub-tables; awkward for global sort/filter | |
| Grouped + filter bar | Collapsible sections + filter bar; more work, no true global sort | |

**User's choice:** One sortable table
**Notes:** Resolves VIEW-01's "grouped AND filter/sort" tension by making grouping = filtering.

### Within the single table, how should approved vs. skipped rows be distinguished?

| Option | Description | Selected |
|--------|-------------|----------|
| Status column + dim skips | Status column (✓ Approved / Skip: <Gate>); skipped rows visually muted | ✓ |
| Status column only | Plain status column, no row styling | |
| Badge + color | Colored badges + gate reason as hover tooltip | |

**User's choice:** Status column + dim skips
**Notes:** Approved picks pop; gate reason inline in the Status column.

---

## Slips default scope

### What should the Slips page default to showing?

| Option | Description | Selected |
|--------|-------------|----------|
| All, newest-first | Every slip grouped by date descending; date/status filter narrows | ✓ |
| Recent + 'show all' | Today + last N days, load full history on demand | |
| Status-grouped | Open (pending/placed) pinned, then settled | |

**User's choice:** All, newest-first
**Notes:** "See every slip" taken literally; ~88 slips is small enough to list all.

### How should each slip present its legs and "why paired" insight?

| Option | Description | Selected |
|--------|-------------|----------|
| Expandable rows | Compact summary row → click to expand legs + why-paired | ✓ |
| Always-expanded cards | Every slip a card with legs + why-paired inline; long page | |
| Table + why-paired column | Flat table, legs as sub-line, why-paired as column | |

**User's choice:** Expandable rows
**Notes:** Scannable all-time list with detail on demand. Why-paired two-tier logic (stored reasoning else derived) locked by design doc — not re-litigated.

---

## History detail & chart

### What granularity should the bankroll/ROI time-series chart use?

| Option | Description | Selected |
|--------|-------------|----------|
| Daily bankroll line | Daily curve from Bankroll Chart Data / Daily Log + headline ROI% | |
| ISO-week aggregated | Aggregate to ISO-week × sport per metrics_report | |
| Both (daily + weekly toggle) | Daily default with toggle to weekly | ✓ |

**User's choice:** Both (daily + weekly toggle)
**Notes:** Daily is the default view; weekly mirrors the existing metrics_report framing.

### What should the per-confidence-tier breakdown show for each tier?

| Option | Description | Selected |
|--------|-------------|----------|
| W/L + hit-rate + ROI + count | Record, hit-rate %, ROI %, sample count per tier | ✓ |
| W/L + hit-rate only | Record + hit-rate %; accuracy not profitability | |
| W/L + ROI only | Record + ROI %; profitability not accuracy | |

**User's choice:** W/L + hit-rate + ROI + count
**Notes:** Makes calibration legible — does confidence predict outcome.

---

## Claude's Discretion

- Filter/sort implementation (client-side vanilla JS vs server-side query params) — leaning client-side, no JS bundler.
- Empty / no-games-today states (graceful messaging).
- Number formatting (% vs native units; optional +EV/−EV color cue).
- Derived "why paired" fallback for truly independent legs (note "independent legs / no correlation flagged").
- Exact source-sheet/column mapping per view — researcher confirms against `data/nxls_schema.txt` + runner header constants.
- Route/template/partial structure, sortable-table and expandable-row mechanisms.

## Deferred Ideas

- Quantified leg-correlation modeling for "why paired" (design doc §10 — later enhancement).
- Calibration / Line-changes / Live tabs (TAB-01..03; milestones M2–M4; nav stubs already present).
- Safe write actions (refresh/re-run, mark-placed, add-note) — Phase 3.
- Pagination / recent-window default for Slips — revisit if the all-time list grows unwieldy.
