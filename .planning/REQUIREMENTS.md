# Requirements: Hermes Sports Automation — Stability Hardening

**Defined:** 2026-06-14
**Core Value:** Every cron job and pipeline runs correctly on schedule — no timeouts, no task-failure alerts — so the operator can move on to model work.

## v1 Requirements

Requirements for this stability milestone. Each maps to a roadmap phase.

### Diagnosis

- [x] **DIAG-01**: Operator can point to the documented root cause of the `mlb_prop_monitor` `[Errno 32] Broken pipe` failure, supported by a reproduction or a captured real-run trace
- [x] **DIAG-02**: Operator can point to the documented source of cron-job timeouts (which task / stage / subprocess exceeds budget), supported by timing evidence

### Reliability Fixes

- [x] **FIX-01**: The `[Errno 32] Broken pipe` failure no longer occurs in `prop_monitor` or any task sharing its root cause
- [x] **FIX-02**: Cron jobs complete within a defined time budget instead of timing out
- [x] **FIX-03**: All 11 runner tasks run end-to-end without uncaught failures on a clean scheduled run

### Defect Removal

- [x] **DEF-01**: The duplicate `injury_monitor` / `clv_tracker` definitions are resolved — dead earlier definitions removed and the active behavior confirmed correct by tests
- [x] **DEF-02**: `generate_projections.py` resolves its base path via `Path.home()` (no hardcoded user path) so it runs regardless of path prefix

### Resilience

- [x] **RES-01**: Outbound network calls (Odds-API.io, ESPN, Telegram, DFS fetchers) retry with backoff on transient failures instead of failing the whole task
- [x] **RES-02**: Broken-pipe / `SIGPIPE` conditions are handled gracefully — logged and tolerated when non-fatal, never surfaced as a spurious `TASK FAILED`
- [x] **RES-03**: Each task enforces a hard internal time budget so a hung stage fails cleanly (and safely, mid-write) instead of being killed by the cron wrapper
- [ ] **RES-04**: Every reliability fix lands with a regression test that fails before the fix and passes after

### Observability

- [ ] **OBS-01**: Each task run emits a structured log record (task, status, duration, error) the operator can review after the fact
- [ ] **OBS-02**: A health / heartbeat check surfaces when a scheduled task has not run or last ended in failure
- [ ] **OBS-03**: Repeated or patterned failures produce a distinct alert rather than only per-occurrence noise

### Continuous Integration

- [ ] **CI-01**: The `unittest` suite runs automatically on each change and reports pass/fail
- [ ] **CI-02**: CI invokes tests from the correct working directory and interpreter (guards the run-from-`scripts/`-with-`python3` footgun)

## v2 Requirements

Deferred to a future release. Tracked but not in this roadmap.

### Observability

- **OBS-04**: Historical run analytics / dashboard of task durations and failure rates over time
- **OBS-05**: Per-stage timing breakdown persisted for trend analysis

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Model accuracy / projection-quality improvements | The explicit "after" goal; stability comes first |
| New sports or new bet types | Not part of stabilization |
| Broad refactor of the ~5,650-line runner monolith | Only stability-threatening defects are in-bounds, not restructuring |
| Migrating off Excel persistence to a database | Excel works today; harden it, don't replace it |

## Traceability

Which phases cover which requirements. Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DIAG-01 | Phase 1 | Complete |
| DIAG-02 | Phase 1 | Complete |
| FIX-01 | Phase 2 | Complete |
| FIX-02 | Phase 2 | Complete |
| FIX-03 | Phase 2 | Complete |
| DEF-01 | Phase 2 | Complete |
| DEF-02 | Phase 2 | Complete |
| RES-01 | Phase 3 | Complete |
| RES-02 | Phase 3 | Complete |
| RES-03 | Phase 3 | Complete |
| RES-04 | Phase 3 | Pending |
| OBS-01 | Phase 4 | Pending |
| OBS-02 | Phase 4 | Pending |
| OBS-03 | Phase 4 | Pending |
| CI-01 | Phase 5 | Pending |
| CI-02 | Phase 5 | Pending |

**Coverage:**
- v1 requirements: 16 total
- Mapped to phases: 16
- Unmapped: 0

---
*Requirements defined: 2026-06-14*
*Last updated: 2026-06-13 — traceability populated at roadmap creation*
