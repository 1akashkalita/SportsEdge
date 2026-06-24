# Phase 3: Safe Actions - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-24
**Phase:** 3-Safe Actions
**Areas discussed:** Refresh scope & status, Action safety UX

---

## Gray-area selection

| Area | Offered | Selected |
|------|---------|----------|
| Refresh scope & status (ACTION-01) | Which task(s) triggerable + how run status is surfaced | ✓ |
| Mark-placed model (ACTION-02) | Persistence target, toggle vs one-way, informational-only | (deferred to default) |
| Note model (ACTION-03) | Reuse vs dedicated column, slips vs picks, single vs append-log, keying | (deferred to default) |
| Action safety UX (ACTION-04 surface) | Confirm step + error surfacing | ✓ |

**User's choice:** Discuss "Refresh scope & status" + "Action safety UX". Mark-placed and Note models left to recorded defaults.

---

## Refresh scope & status

### Q1 — Which task(s) should the refresh action trigger?

| Option | Description | Selected |
|--------|-------------|----------|
| Curated set | daily picks per sport + check_results + prop_monitor; same subprocess, different --task | ✓ |
| One 'Refresh today' | single button running nba+mlb daily_picks only | |
| Full task picker | dropdown of all 11 runner tasks | |

**User's choice:** Curated set → D-01.

### Q2 — How should the dashboard show the run's progress/result?

| Option | Description | Selected |
|--------|-------------|----------|
| run_log.jsonl + lock badge | poll status endpoint reusing Phase-1 lock badge + Phase-4 run_log.jsonl | ✓ |
| Dedicated status panel | bespoke panel showing started-at/live/✓✗ for the spawned run | |
| Fire-and-forget | confirm 'started', rely on freshness badge + manual reload | |

**User's choice:** run_log.jsonl + lock badge → D-04.

**Notes:** Async + lock-aware refusal of concurrent runs is locked by the design doc (D-02/D-03); spawn + lock-detection mechanisms left as discretion.

---

## Action safety UX

### Q1 — Which actions require a confirm step?

| Option | Description | Selected |
|--------|-------------|----------|
| Confirm refresh only | re-run gets a confirm (spawns subprocess + writes); mark-placed/add-note inline | ✓ |
| Confirm all writes | every action shows a confirm dialog | |
| No confirms | all fire immediately; rely on lock-aware + additive-only | |

**User's choice:** Confirm refresh only → D-05.

### Q2 — How should outcomes/failures surface?

| Option | Description | Selected |
|--------|-------------|----------|
| Inline flash banner | banner on same page via POST→redirect→render | ✓ |
| Fold into status area | surface near the nav freshness badge | |
| Dedicated outcomes panel | timestamped recent-results panel | |

**User's choice:** Inline flash banner → D-06.

---

## Claude's Discretion

- Async spawn mechanism + lock-detection mechanism for the refresh subprocess (runner `LOCK_EX` is the backstop).
- Refresh UI layout (buttons vs dropdown; sport-split vs combined controls); status-poll endpoint shape/cadence; flash-banner copy/styling.
- Mark-placed model (D-07 default: new `Placed`/`Placed At` columns on Slip History, toggle, informational-only, keyed by (Date, Slip ID)).
- Note model (D-08 default: dedicated `Operator Note` column — NOT the grading `Notes` — single editable note; slips-only fallback if a robust pick key can't be guaranteed).

## Deferred Ideas

- Append-only/timestamped note history (v1 is single editable note).
- Pick-level notes if a stable pick key can't be guaranteed → slips-only for v1.
- Full task picker (all 11 tasks) for refresh.
- Dedicated run-status / action-outcomes panel.
- Calibration / Line-changes / Live tabs (TAB-01..03, later milestones).
