# Requirements: Hermes Sports Automation — v3.0 Local Dashboard

**Defined:** 2026-06-24
**Core Value:** A localhost dashboard that lets the operator see the whole system at a glance — today's props/picks (by platform & sport, with +EV and probabilities), all slips with why-they're-paired insight, and win/loss history overall + per sport — plus a few safe actions, without touching any betting logic.

## v1 Requirements

Requirements for this milestone (v3.0). Each maps to exactly one roadmap phase.

### Dashboard Foundation & Data Layer

- [x] **DASH-01**: Operator can launch the dashboard with one command (`python3 dashboard.py`) and open it at a localhost URL
- [x] **DASH-02**: The dashboard runs on the system Python 3.14 interpreter — Flask verified at setup, with a stdlib `http.server` fallback if Flask will not import on 3.14.0a2
- [x] **DASH-03**: The dashboard binds to `127.0.0.1` only and is not reachable from other machines
- [x] **DASH-04**: The dashboard reads existing persisted data (workbooks + JSON) without modifying or corrupting it, tolerating a workbook that is locked mid-write

### Read Views

- [ ] **VIEW-01**: Operator can view today's props/picks grouped by platform and sport, showing +EV, model probability, edge, and confidence, with platform/sport filtering and EV sorting
- [ ] **VIEW-02**: Operator can view all slips (status, payout, legs) with a "why these legs are paired" insight (Correlated Parlays `Reasoning`/`Correlation Group`; derived rationale for general slips)
- [ ] **VIEW-03**: Operator can view win/loss history overall and per sport, including a bankroll/ROI time-series chart and a per-confidence-tier breakdown

### Safe Actions (guarded writes)

- [ ] **ACTION-01**: Operator can trigger a data refresh / task re-run from the dashboard; it runs as a lock-aware subprocess (refuses if a run is already in progress), reports status, and never runs a task inline in the web process
- [ ] **ACTION-02**: Operator can mark a slip as placed from the dashboard (additive column, atomic save)
- [ ] **ACTION-03**: Operator can add a note to a slip or pick from the dashboard (additive, atomic save)
- [ ] **ACTION-04**: No dashboard action changes gate logic, grades, EV, or exposure caps — all writes are additive-only and the betting pipeline is untouched

## v2 Requirements

Deferred to a future milestone (the post-v2.0 roadmap continues after the dashboard).

### Later dashboard tabs (added as later milestones land)

- **TAB-01**: Calibration tab — reliability curves / Brier / log-loss from the M2 backtest harness
- **TAB-02**: Line-changes feed — favorable line moves and re-recommendations from M3
- **TAB-03**: Live tab — in-game picks from M4

## Out of Scope

Explicitly excluded for v3.0. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Full control panel (approve/override picks, edit slips, adjust exposure) | Can mutate real-money decisions from a browser; biggest risk and arguably defeats the unattended-automation design |
| Authentication / multi-user | Solo operator on localhost only; no external exposure |
| Real-time push / websockets | Page-load + manual refresh is sufficient for a solo local tool |
| Mobile layout | Web-first on the operator's Mac; not needed for v1 |
| Replacing Excel/JSON persistence with a database or API backend | The dashboard reads what exists; persistence stays as-is |

## Traceability

Which phases cover which requirements. Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DASH-01 | Phase 1 — Foundation & Data Layer | Complete |
| DASH-02 | Phase 1 — Foundation & Data Layer | Complete |
| DASH-03 | Phase 1 — Foundation & Data Layer | Complete |
| DASH-04 | Phase 1 — Foundation & Data Layer | Complete |
| VIEW-01 | Phase 2 — Read Views | Pending |
| VIEW-02 | Phase 2 — Read Views | Pending |
| VIEW-03 | Phase 2 — Read Views | Pending |
| ACTION-01 | Phase 3 — Safe Actions | Pending |
| ACTION-02 | Phase 3 — Safe Actions | Pending |
| ACTION-03 | Phase 3 — Safe Actions | Pending |
| ACTION-04 | Phase 3 — Safe Actions | Pending |

**Coverage:**
- v1 requirements: 11 total
- Mapped to phases: 11 (100%) ✓
- Unmapped: 0 ✓

---
*Requirements defined: 2026-06-24*
*Last updated: 2026-06-24 after roadmap creation (3 phases; 11/11 requirements mapped)*
