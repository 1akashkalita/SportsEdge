# Roadmap: Hermes Sports Automation

## Milestones

- ✅ **v1.0 Stability Hardening** — Phases 1–5 (shipped 2026-06-22) — see [milestones/v1.0-ROADMAP.md](./milestones/v1.0-ROADMAP.md)
- 🚧 **v2.0 Slips & Props Tracking** — Phases 1–4 (in progress)

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

### 🚧 v2.0 Slips & Props Tracking (In Progress)

**Milestone Goal:** Make the bankroll reflect actual DFS slips, track and grade both slips and props, backfill from inception (2026-06-08), and feed realized outcomes back into selection — so the operator can finally tell whether the model is improving.

**Phase Numbering:** Reset for this milestone — phases 1–4 are v2.0 work (prior milestone phases archived).

- [ ] **Phase 1: Trustworthy Results** — Harden prop grading (name/stat matching), attach provenance, backfill June 8–21 MANUAL-REVIEW rows
- [ ] **Phase 2: Slip Reconstruction and Grading** — Reconstruct model-recommended slips per day, grade against P1 results, populate Slip History, backfill June 8–21
- [ ] **Phase 3: Slips-Only Bankroll** — Rebase bankroll to slip Net PnL; confidence-scaled stakes; props become accuracy-only
- [ ] **Phase 4: Dual Metrics and Feedback** — Slip ROI + prop hit-rate reports; bounded outcome-to-selection feedback loop

## Phase Details

### Phase 1: Trustworthy Results
**Goal**: Every prop grade resolves correctly — name and stat mismatches no longer produce MANUAL REVIEW for recoverable stats, every graded row carries provenance, and the June 8–21 MANUAL REVIEW backlog is reduced to only the genuinely unresolvable residue
**Depends on**: Nothing (first phase)
**Requirements**: RESULTS-01, RESULTS-02, RESULTS-03, RESULTS-04, RESULTS-05, RESULTS-06, RESULTS-07
**Success Criteria** (what must be TRUE):
  1. The June 8 dry-run gate passes: at least 80% of non-Fantasy-Score MANUAL REVIEW prop rows for that date resolve to WIN/LOSS/PUSH after Layer-1 hardening (the single pass/fail gate for Criterion #1 in the approved spec)
  2. Every prop row written by grading carries a populated `Result Source` (api / scraped / manual) and a numeric `Result Confidence` column; spread/total/parlay/VOID rows also carry these fields with api/1.0
  3. Re-grading a date with previously MANUAL REVIEW or PENDING rows overwrites them in place with terminal grades; rows already settled WIN/LOSS/PUSH/VOID (in any casing) are untouched, and no duplicate Results or Pick History rows appear
  4. A parlay is never mis-graded against a partial leg set: it abstains (stays at prior result) when any constituent leg is not yet terminal
  5. The firecrawl fallback (flag `ENABLE_FIRECRAWL_RESULT_FALLBACK`, default off) degrades to MANUAL REVIEW on any failure, timeout, missing binary, offline, or 429 — grading never crashes and every daily run stays under the 660s cron budget
**Plans**: 6 plans
Plans:
- [x] 01-1-PLAN.md — Component 0: ESPN summary fixtures + stat_corpus oracle (testdata only)
- [x] 01-2-PLAN.md — name_match + _canonical_name; batting/pitching namespace split + hit-type counts
- [x] 01-3-PLAN.md — stat_value_for_prop disposition table (3-tuple) + provenance columns end-to-end
- [ ] 01-4-PLAN.md — value-aware TERMINAL_RESULTS guard + parlay full-leg-set fix + side re-parser
- [ ] 01-5-PLAN.md — Layer 2: verify_results.py keyless firecrawl + resolve_missing_stat (flag default off)
- [ ] 01-6-PLAN.md — June 8 ≥80% dry-run gate + June 8–21 backfill execution (human-verified)

### Phase 2: Slip Reconstruction and Grading
**Goal**: The Slip History sheet is populated — the model's recommended slips are reconstructed per day, graded against trustworthy results from Phase 1, and backfilled across June 8–21 as a verifiable backtest
**Depends on**: Phase 1
**Requirements**: SLIPS-01, SLIPS-02, SLIPS-03, SLIPS-04
**Success Criteria** (what must be TRUE):
  1. Running the daily picks flow automatically produces slip records in Slip History (legs, slip result, payout multiplier, gross return, net PnL) — the sheet is no longer empty after a daily run
  2. Each slip's grade is derived from the trustworthy P1 prop results — a slip with all WIN legs is WIN and a slip with any LOSS leg is LOSS; slip success and individual-prop success are stored as distinct metrics
  3. The June 8–21 Slip History backfill completes without duplicate rows: re-running on a date that already has slip records for that date is idempotent
  4. An operator can distinguish slip ROI from prop win-rate at a glance from the persisted sheets (separate tracking is demonstrably present, not interleaved)
**Plans**: TBD

### Phase 3: Slips-Only Bankroll
**Goal**: The bankroll ledger reflects only what was actually staked and returned on DFS slips — individual prop outcomes are removed from the bankroll and preserved as a separate model-accuracy signal
**Depends on**: Phase 2
**Requirements**: BANKROLL-01, BANKROLL-02, BANKROLL-03, BANKROLL-04
**Success Criteria** (what must be TRUE):
  1. The current bankroll balance is computed exclusively from slip Net PnL; re-running the bankroll calculation with no new slips produces the same balance (individual prop W/L rows have no effect on the balance)
  2. Each slip's stake is sized by confidence score — a higher-confidence slip has a larger stake than a lower-confidence slip from the same day under the same bankroll
  3. The bankroll history is rebased from 2026-06-08: the historical P&L chart reflects slip-based outcomes from inception, not prior prop-based accounting
  4. Prop W/L outcomes remain readable as a model-accuracy signal in a separate report or sheet, not eliminated
**Plans**: TBD

### Phase 4: Dual Metrics and Feedback
**Goal**: The operator can answer "is the model improving?" from data — slip ROI and prop hit-rate are surfaced over time by week and sport, and realized outcomes flow back into projection/gate tuning through a bounded, integrity-safe feedback loop
**Depends on**: Phase 3
**Requirements**: METRICS-01, METRICS-02, METRICS-03
**Success Criteria** (what must be TRUE):
  1. A report (Telegram message or Obsidian note) shows slip ROI and prop hit-rate broken down by week and by sport (NBA / MLB), enabling "improving vs stagnant" as a data-driven answer
  2. Realized slip and prop outcomes feed back into the projection or gate configuration in a bounded, observable way — at least one tunable parameter is updated by outcomes
  3. The feedback loop cannot retroactively alter any graded verdict (WIN/LOSS/PUSH/VOID) and cannot modify no-bet gate logic or pick output verdicts — the integrity of grading and the gate gauntlet is preserved by design, confirmed by a test
**Plans**: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Diagnosis | v1.0 | 3/6 | In Progress|  |
| 2. Reliability Fixes + Defect Removal | v1.0 | 5/5 | Complete | 2026-06-20 |
| 3. Resilience | v1.0 | 3/3 | Complete | 2026-06-21 |
| 4. Observability | v1.0 | 3/3 | Complete | 2026-06-21 |
| 5. CI | v1.0 | 3/3 | Complete | 2026-06-21 |
| 1. Trustworthy Results | v2.0 | 0/6 | Planned | - |
| 2. Slip Reconstruction and Grading | v2.0 | 0/TBD | Not started | - |
| 3. Slips-Only Bankroll | v2.0 | 0/TBD | Not started | - |
| 4. Dual Metrics and Feedback | v2.0 | 0/TBD | Not started | - |
