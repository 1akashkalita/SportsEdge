# Requirements — v2.0 Slips & Props Tracking

Scoped requirements for milestone v2.0. REQ-IDs are stable; traceability to phases is filled by the roadmap.

## v2.0 Requirements

### RESULTS — Trustworthy results (Phase 1 / P1)

- [x] **RESULTS-01**: Prop grading resolves player names robustly (accents, punctuation, suffixes, "F. Last" ↔ "First Last", last-name-unique-within-game), so name-format mismatches no longer fall to MANUAL REVIEW; ambiguous matches abstain rather than guess.
- [x] **RESULTS-02**: NBA + MLB stat derivation covers composite/pitcher stats (Total Bases, Hits+Runs+RBIs, Singles, Pitching Outs, Blks+Stls, FG made/attempted split, etc.) via an explicit disposition table, replacing the substring fallback that caused false positives.
- [x] **RESULTS-03**: Batting vs pitching stat namespaces are disambiguated so shared MLB labels (strikeouts, hits, runs, walks) grade against the correct group.
- [x] **RESULTS-04**: Every graded prop row records `Result Source` (api / scraped / manual) and a numeric `Result Confidence` (additive schema columns).
- [ ] **RESULTS-05**: A feature-flagged, keyless, subprocess-isolated firecrawl fallback resolves residual unresolved stats by scraping the box score, and degrades safely to MANUAL REVIEW on any failure/timeout/offline/rate-limit without crashing grading.
- [x] **RESULTS-06**: Backfill re-grading replaces MANUAL REVIEW / PENDING rows with terminal grades in place — no duplicate Results/Pick-History rows, settled WIN/LOSS/PUSH/VOID rows untouched, and no parlay mis-grade from partial leg sets.
- [ ] **RESULTS-07**: The June 8–21 MANUAL-REVIEW backlog is recovered to the measured achievable rate (hard gate: ≥80% of non-Fantasy-Score MANUAL-REVIEW prop rows resolve on the June 8 dry-run).

### SLIPS — Reconstruct, grade, record (Phase 2 / P2)

- [ ] **SLIPS-01**: The system reconstructs the model's recommended slips per day from saved projections/correlations (`build_slips.py` wired into the flow).
- [ ] **SLIPS-02**: Each slip's legs are graded against trustworthy (P1) results, and the Slip History sheet is populated (legs, slip result, payout multiplier, gross return, net PnL).
- [ ] **SLIPS-03**: Slips are backfilled across June 8–21 as a backtest of the model's slip recommendations.
- [ ] **SLIPS-04**: Slip success and individual-prop success are tracked separately (props = model accuracy, slips = money outcome).

### BANKROLL — Slips-only bankroll (Phase 3 / P3)

- [ ] **BANKROLL-01**: Bankroll is computed strictly from slip Net PnL; individual props are excluded from the bankroll.
- [ ] **BANKROLL-02**: Each slip is staked using confidence-scaled sizing.
- [ ] **BANKROLL-03**: The bankroll history is rebased onto the slips-only basis from inception (2026-06-08).
- [ ] **BANKROLL-04**: Prop-level W/L is retained as a model-accuracy signal, reported separately from the bankroll.

### METRICS — Dual metrics + feedback into selection (Phase 4 / P4)

- [ ] **METRICS-01**: A report surfaces slip ROI and prop hit-rate over time (by week and sport) so "improving vs stagnant" is answerable from data.
- [ ] **METRICS-02**: Realized slip/prop outcomes feed back into projection/gate tuning via a bounded feedback loop.
- [ ] **METRICS-03**: The feedback loop is safe — it cannot retroactively change graded verdicts and preserves the integrity of the no-bet gates.

## Future Requirements (deferred)

- Persist Player/Stat/Line/Side as real structured columns on prop rows (removes string-parsing fragility in future grading) — recommended, additive, deferred past P1.
- Exact PrizePicks/Underdog Fantasy-Score payout formulas (the 46-row residue class) as a first-class derivation rather than a scrape — higher-risk, separate workstream.
- Live/forward firecrawl board fetching as a DFS-API fallback (distinct from result verification).

## Out of Scope

- Full projection-model rebuild / new ML training pipeline — v2.0 delivers trustworthy measurement and a *bounded* feedback loop, not a ground-up model rewrite.
- New sports or new bet types.
- Changing gate logic or pick verdicts; non-additive workbook schema changes.
- Migrating off Excel persistence.
- Self-hosted firecrawl instance; `--browser`/`--format json` scrape modes; running firecrawl `init` on the cron host.

## Traceability

| REQ-ID | Phase | Status |
|--------|-------|--------|
| RESULTS-01 | Phase 1 | Complete |
| RESULTS-02 | Phase 1 | Complete |
| RESULTS-03 | Phase 1 | Complete |
| RESULTS-04 | Phase 1 | Complete |
| RESULTS-05 | Phase 1 | Pending |
| RESULTS-06 | Phase 1 | Complete |
| RESULTS-07 | Phase 1 | Pending |
| SLIPS-01 | Phase 2 | Pending |
| SLIPS-02 | Phase 2 | Pending |
| SLIPS-03 | Phase 2 | Pending |
| SLIPS-04 | Phase 2 | Pending |
| BANKROLL-01 | Phase 3 | Pending |
| BANKROLL-02 | Phase 3 | Pending |
| BANKROLL-03 | Phase 3 | Pending |
| BANKROLL-04 | Phase 3 | Pending |
| METRICS-01 | Phase 4 | Pending |
| METRICS-02 | Phase 4 | Pending |
| METRICS-03 | Phase 4 | Pending |
