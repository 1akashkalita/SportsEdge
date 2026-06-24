# Roadmap: Hermes Sports Automation

## Milestones

- ✅ **v1.0 Stability Hardening** — Phases 1–5 (shipped 2026-06-22) — see [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)
- ✅ **v2.0 Slips & Props Tracking** — Phases 1–4 + 04.1 (shipped 2026-06-24) — see [milestones/v2.0-ROADMAP.md](./milestones/v2.0-ROADMAP.md)
- 🚧 **v3.0 Local Dashboard** — Phases 1–3 (in progress)

## Phases

<details>
<summary>✅ v1.0 Stability Hardening (Phases 1–5) — SHIPPED 2026-06-22</summary>

- [x] Phase 1: Diagnosis (3/3 plans) — completed 2026-06-15
- [x] Phase 2: Reliability Fixes + Defect Removal (5/5 plans) — completed 2026-06-20
- [x] Phase 3: Resilience (3/3 plans) — completed 2026-06-21
- [x] Phase 4: Observability (3/3 plans) — completed 2026-06-21
- [x] Phase 5: CI (3/3 plans) — completed 2026-06-21

Full phase details archived in [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md).
Audit: [milestones/v1.0-MILESTONE-AUDIT.md](./milestones/v1.0-MILESTONE-AUDIT.md) (status: tech_debt — no blockers, 16/16 requirements satisfied).

</details>

<details>
<summary>✅ v2.0 Slips & Props Tracking (Phases 1–4 + 04.1) — SHIPPED 2026-06-24</summary>

**Goal:** Make the bankroll reflect actual DFS slips, track and grade both slips and props, backfill from inception (2026-06-08), and feed realized outcomes back into selection — so the operator can finally tell whether the model is improving.

- [x] Phase 1: Trustworthy Results (11/11 plans) — verified 2026-06-24
- [x] Phase 2: Slip Reconstruction and Grading (3/3 plans) — verified 2026-06-24
- [x] Phase 3: Slips-Only Bankroll (4/4 plans) — completed 2026-06-22
- [x] Phase 4: Dual Metrics and Feedback (3/3 plans) — completed 2026-06-23
- [x] Phase 04.1: Close v2.0 Audit Gaps (3/3 plans) — completed 2026-06-23

Full phase details archived in [milestones/v2.0-ROADMAP.md](./milestones/v2.0-ROADMAP.md).
Audit: [milestones/v2.0-MILESTONE-AUDIT.md](./milestones/v2.0-MILESTONE-AUDIT.md) (status: resolved — all functional gaps closed; 18/18 requirements satisfied).
Deferred (acknowledged tech-debt): Nyquist VALIDATION across phases + 3 live human-UAT items (see STATE.md → Deferred Items).

</details>

### 🚧 v3.0 Local Dashboard (In Progress)

**Milestone Goal:** A `localhost` web dashboard so the operator can *see* the whole system at a glance — today's props/picks by platform & sport (with +EV, model probability, edge, confidence), all slips with why-they're-paired insight, and win/loss history overall + per sport — plus a few safe, additive-only actions, without touching any betting logic. Almost entirely a read-layer over already-persisted data; the only writes are three guarded, additive actions.

Design: `docs/superpowers/specs/2026-06-23-localhost-dashboard-design.md` (approved).

- [x] **Phase 1: Foundation & Data Layer** — One-command localhost launch (Flask verified on 3.14.0a2, stdlib fallback), 127.0.0.1-only, read-only data layer that tolerates a mid-write workbook lock (completed 2026-06-24)
- [ ] **Phase 2: Read Views** — Today (props/picks +EV/prob/edge/confidence), Slips (status/payout/legs + why-paired), History (W/L overall+per-sport, bankroll/ROI chart, per-tier breakdown)
- [ ] **Phase 3: Safe Actions** — Lock-aware async refresh/re-run, mark-slip-placed, add-note — all additive-only and atomic, betting pipeline untouched

## Phase Details

### Phase 1: Foundation & Data Layer
**Goal**: A one-command localhost dashboard process exists on the verified web stack, bound to 127.0.0.1 only, with a read-only data layer that surfaces persisted workbook + JSON data without ever modifying or corrupting it — even when a workbook is locked mid-write.
**Depends on**: Nothing (first phase of v3.0)
**Requirements**: DASH-01, DASH-02, DASH-03, DASH-04
**Success Criteria** (what must be TRUE):
  1. Running `python3 dashboard.py` from `scripts/` starts the server and the operator can open it at a `127.0.0.1` localhost URL (DASH-01).
  2. The web stack is confirmed before anything is built on it — Flask imports and serves on the system Python 3.14.0a2, or the stdlib `http.server` fallback is wired in and serving instead (DASH-02).
  3. The server is bound to `127.0.0.1` only and is unreachable from another machine on the network (DASH-03).
  4. The data layer reads existing workbooks (`read_only=True`) and JSON artifacts (`bankroll.json`, latest props JSON) and returns data without writing to them; the source files' contents and mtimes are unchanged after a read (DASH-04).
  5. When a workbook is locked / being atomically swapped mid-write, a read retries or skips gracefully and never raises an unhandled error or returns corrupt data (DASH-04).
**Plans**: 3 plans
  - [x] 01-01-PLAN.md — Wave-0 test scaffolds + verify-first Flask-serves gate (DASH-02)
  - [x] 01-02-PLAN.md — Read-only, lock-tolerant data layer + badge/freshness signals (DASH-04, D-01/D-02)
  - [x] 01-03-PLAN.md — Flask app shell + dark Pico templates + loopback-only launch (DASH-01, DASH-03)
**UI hint**: yes

### Phase 2: Read Views
**Goal**: The operator can see the whole board through three rendered pages — today's props/picks by platform & sport, all slips with why-they're-paired insight, and the running win/loss record with charts — all read-only over the Phase 1 data layer.
**Depends on**: Phase 1 (renders through its read-only data layer; no new persistence)
**Requirements**: VIEW-01, VIEW-02, VIEW-03
**Success Criteria** (what must be TRUE):
  1. The Today page shows today's props/picks grouped by platform and sport with player/stat/line, projection, edge, +EV, model probability, and confidence; the operator can filter by platform/sport and sort by EV (VIEW-01).
  2. The Slips page lists every slip with its status, payout, and legs (VIEW-02).
  3. Each slip shows a "why these legs are paired" insight — the stored Correlated Parlays `Reasoning`/`Correlation Group` where present, and a derived rationale (same game/team, combined prob/EV) for general slips (VIEW-02).
  4. The History page shows win/loss overall and per sport, with a per-confidence-tier breakdown (VIEW-03).
  5. The History page renders a bankroll/ROI time-series chart (Chart.js via CDN) from the persisted bankroll/master-P&L data (VIEW-03).
**Plans**: TBD
**UI hint**: yes

### Phase 3: Safe Actions
**Goal**: The operator can take three guarded actions from the dashboard — trigger a data refresh/task re-run, mark a slip placed, and add a note — with a hard guarantee that every write is additive-only and atomic and that no action ever changes gate logic, grades, EV, or exposure caps.
**Depends on**: Phase 2 (actions are issued from the rendered views; reuses Phase 1 read layer + `workbook_io` atomic save)
**Requirements**: ACTION-01, ACTION-02, ACTION-03, ACTION-04
**Success Criteria** (what must be TRUE):
  1. The operator can trigger a data refresh / task re-run that runs the runner as a subprocess (exactly as cron does, preserving the `fcntl` lock), never inline in the web process; it is async and reports status (ACTION-01).
  2. The refresh action is lock-aware — it refuses and surfaces a clear "run already in progress" status instead of starting a concurrent run (ACTION-01).
  3. The operator can mark a slip as placed, persisted via an additive column with an atomic `workbook_io` save (ACTION-02).
  4. The operator can add a note to a slip or pick, persisted additively with an atomic save (ACTION-03).
  5. No dashboard action changes gate logic, grades, EV, or exposure caps — all writes are additive-only, the betting pipeline is untouched, and this is proven by tests (ACTION-04).
**Plans**: TBD
**UI hint**: yes

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundation & Data Layer | v3.0 | 3/3 | Complete   | 2026-06-24 |
| 2. Read Views | v3.0 | 0/TBD | Not started | - |
| 3. Safe Actions | v3.0 | 0/TBD | Not started | - |

## Next Milestone

📋 **M2 Model Accuracy & Calibration** is the planned next direction (design: `docs/superpowers/specs/2026-06-23-model-accuracy-calibration-design.md`) — the second of the 4-milestone post-v2.0 arc (dashboard → calibration → line-change re-eval → live in-game). A **Calibration tab** (reliability curves / Brier / log-loss) is the natural dashboard extension once M2 lands (v2 requirement TAB-01).
