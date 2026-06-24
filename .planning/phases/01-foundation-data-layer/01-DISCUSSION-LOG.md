# Phase 1: Foundation & Data Layer - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-24
**Phase:** 1-Foundation & Data Layer
**Areas discussed:** Mid-write lock behavior (selected); Read freshness / Launch ergonomics / Visual baseline (offered, deferred to defaults)

---

## Gray-area selection

Four Phase-1 gray areas were offered (multi-select): Read freshness, Mid-write lock behavior, Launch ergonomics, Visual baseline. The operator selected **only Mid-write lock behavior** to discuss; the other three were explicitly delegated to Claude's sensible defaults.

---

## Mid-write lock behavior (DASH-04)

Grounding given before the question: saves use an atomic `os.replace` swap, so a reader always opens a complete file (old or new), never partial — true corruption can't happen on read; the decision is purely the freshness UX.

| Option | Description | Selected |
|--------|-------------|----------|
| Last-known-good + subtle hint | Always render freshest complete data; show a small "updating…" badge when a write/lock is detected. Never blocks, never errors. | ✓ |
| Brief retry, then serve | Retry a few times on a (rare) read error, then serve last good data; no visible indicator. | |
| Explicit "refreshing" notice | Replace the data area with a "data refreshing, reload shortly" message until the write completes. | |

**User's choice:** Last-known-good + subtle hint.
**Notes:** Paired (Claude's complement, accepted by default) with a per-page "last updated HH:MM" (Pacific) timestamp so freshness is glanceable. The view must never block.

---

## Claude's Discretion (operator deferred to defaults)

- **Read freshness:** fresh on every page load (no long-lived cache); JSON-first, workbooks via `read_only=True`.
- **Launch ergonomics:** fixed default port `8787` + auto-open browser on `python3 dashboard.py`; port overridable.
- **Visual baseline:** dark theme, dense data-tables (Pico.css dark base).
- Module layout, route names, port-conflict handling, exact write-in-progress detection mechanism, template structure.

## Deferred Ideas

- Later dashboard tabs (Calibration / Line-changes / Live) — v2 requirements TAB-01..03, future milestones M2–M4. Shell should leave room; do not build now.
- Full UI design contract via `/gsd-ui-phase 1` (all v3.0 phases carry `UI hint: yes`).
