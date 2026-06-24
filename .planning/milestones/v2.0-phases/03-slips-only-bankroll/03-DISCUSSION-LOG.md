# Phase 3: Slips-Only Bankroll - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-22
**Phase:** 03-slips-only-bankroll
**Areas discussed:** Bet universe, Confidence→stake formula, Daily exposure & Gate 8, Prop split & rebase basis, Exact thresholds

---

## Bet universe — which slips are "the bet"

| Option | Description | Selected |
|--------|-------------|----------|
| Curated subset per day | Only categories you'd really play; excludes experimental | ✓ |
| All categories, each a stake | Every model slip is a separate bet (all 88 rows) | |
| One best slip per day | Single highest-confidence slip becomes the day's bet | |

Follow-up — categories: **All six categories** selected (over "Safest + highest-EV" and "Core + correlated upside").
Follow-up — variants: **All variants count** selected (over "One per category/day").

**User's choice:** Curated subset → resolved to all 6 categories + all variants.
**Notes:** Net effect = every graded slip is a candidate bet; curation happens via confidence-staking + zero-floor, not category exclusion. Captured as D-01.

---

## Confidence→stake formula (BANKROLL-02)

| Question | Options | Selected |
|----------|---------|----------|
| Signal | combined_probability / combined_ev_score / Leg-tier rollup | **first two** (combined_probability + combined_ev_score) |
| Mapping | Tiered buckets / Linear scaling / Fractional Kelly | **Tiered buckets** |
| Stake base | Fixed units / % of current bankroll | **% of current bankroll** |

**User's choice:** Tiered buckets on % of running bankroll, using both probability (primary) and EV (gate).
**Notes:** Probability set as the monotone tier axis to protect success-criterion #2 (D-06). Captured as D-02/D-03.

---

## Daily exposure & Gate 8

| Question | Options | Selected |
|----------|---------|----------|
| Gate 8 | Keep G8 + add slip budget / Remove G8 caps in P3 | **Remove G8 caps in P3** |
| Daily budget | 10% / 15% / No daily cap | **No daily cap** |
| Overflow | Proportional scale-down / Drop lowest-confidence | **Proportional scale-down** (moot under "no cap"; kept as deferred preference) |

**User's choice:** Remove Gate-8 exposure caps; rely solely on per-slip tiers + zero-floor (no daily budget).
**Notes:** Operator was shown that this means no exposure ceiling at all and that removing Gate 8 widens P3 beyond accounting (changes pick outputs). Accepted knowingly. Captured as D-07/D-08.

---

## Prop split & rebase basis (BANKROLL-01/03/04)

| Question | Options | Selected |
|----------|---------|----------|
| Prop home | Keep Pick History + summary / New Prop Accuracy sheet | **Keep Pick History + summary** |
| Rebase | One-time clean rebuild / Incremental layered | **One-time clean rebuild** |
| Re-stake | Recompute in place / Add new columns | **Recompute in place** |

**User's choice:** Prop W/L stays in Pick History (+ separate accuracy summary); bankroll rebuilt once from 2026-06-08; slip stakes recomputed in place. Captured as D-09..D-13.

---

## Exact thresholds (operator chose to pin now, not delegate)

| Question | Options | Selected |
|----------|---------|----------|
| Prob tiers | 0.75/0.65 / 0.70/0.60 / 0.80/0.68 | **0.75 / 0.65** |
| Floor | 0.58 / 0.55 / 0.60 | **0.58** |
| EV gate | EV>0 required to bet / EV≤0 caps at low tier / EV gates top tier only | **EV > 0 required to bet** |

**User's choice:** Top 2.5% ≥0.75, mid 1.5% 0.65–0.75, low 0.75% 0.58–0.65; <0.58 or EV≤0 → not bet. Captured as D-03/D-04/D-05.

---

## Claude's Discretion

- Module placement (modify `sync_master_and_bankroll` vs a dedicated slip-bankroll function/task).
- Form of the Prop Accuracy summary (new sheet vs markdown report).
- Location of the stake-sizing helper; test file names.
- Intra-day sizing basis locked to a start-of-day snapshot (D-14) as the deterministic default — flagged for operator correction at plan review.

## Deferred Ideas

- Daily slip-exposure budget / cap (none in P3; proportional scale-down if revisited).
- P4 dual-metrics report + outcome→selection feedback loop (METRICS-01..03).
- Intra-day compounding of stakes.
</content>
