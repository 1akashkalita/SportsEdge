# Roadmap: Hermes Sports Automation

## Milestones

- ✅ **v1.0 Stability Hardening** — Phases 1–5 (shipped 2026-06-22) — see [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)
- ✅ **v2.0 Slips & Props Tracking** — Phases 1–4 + 04.1 (shipped 2026-06-24) — see [milestones/v2.0-ROADMAP.md](./milestones/v2.0-ROADMAP.md)

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

## Next Milestone

📋 **Not yet defined.** Model / accuracy work is the planned next direction — the explicit "after stability + trustworthy measurement" goal: now that slips and props are graded and the bankroll is a trustworthy signal, improve the projections/calibration. Start with `/gsd-new-milestone`.
