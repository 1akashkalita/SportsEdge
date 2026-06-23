---
quick_id: 260622-p7x
slug: slips-vetted-per-platform
status: complete
money_safe: true
date: 2026-06-22
commits:
  - 3a1bc6a  test(260622-p7x): failing tests (RED)
  - 13e7484  fix(260622-p7x): vetted-only, per-platform, real-labeled, dedup'd slips (GREEN)
  - 0d6fded  fix(260622-p7x): drop cross-platform self-pair dup legs (Rule 1 bug found via trace-verify)
tests: "17 passed (13 build_slips + 4 audit_slips), 0 failed"
---

# Quick Task 260622-p7x: Trustworthy, platform-specific slip generation — Summary

One-liner: `build_slips.py` now restricts slips to the gauntlet-vetted universe
(APPROVED + Gate-8 cap-held workbook rows) via a fail-safe filter, partitions the
pool by platform and builds within each platform — guaranteeing single-platform,
real-labeled, duplicate-free slips, with Underdog payouts rendered `n/a` (never
fabricated).

## What changed

- `scripts/build_slips.py`
  - `load_vetted_keys(date)` — loads each sport workbook for the date; collects
    vetted rows = `Picks` Status==APPROVED + `Skipped Picks` Gate Failed containing
    `GATE 8 — DYNAMIC EXPOSURE CAP` or `GATE 8 — CONCENTRATION CAP`. Returns
    `None` when no workbook exists (fallback to legacy `is_eligible` for backfill).
  - `filter_to_vetted(projections, vetted)` — keeps a projection iff a vetted pick
    of the same sport shares its `(canonical player, line, platform)` AND the
    projection's stat tokens are the **largest subset** of that pick's stat tokens.
    Unmatched/ambiguous projections are EXCLUDED (fail-safe). Best-subset matching
    means a bare `hits` projection is NOT vetted by a "Hits + Runs + RBIs" pick
    when the combo projection exists.
  - Canonical helpers: `canonical_name` (casefold + strip accents/punct),
    `stat_token_set`, `pick_stat_tokens` (drop player-name words, numbers,
    stopwords like over/under/inn/1st/pitcher/total/allowed/home).
  - `make_slip` — derives the real platform from `legs` (`slip_platform`), passes
    it to `payout_multiplier`, sets `slip["platform"]`. Underdog → `None`
    multiplier kept as-is (rendered `n/a`). Defensive dedup drops exact-duplicate
    prop_id legs.
  - `build_slips` — partitions the eligible pool by platform (`platform_groups`)
    and runs the existing per-category combo logic WITHIN each platform via
    `_build_category_slips`, merging per-category lists (preserves
    `payload['slips'][category]` list structure). Skips groups with <2 props and
    drops any slip that dedup collapsed below 2 legs. Adds `platform_breakdown` +
    `vetted_source` to the payload and `JSON_RESULT`.
  - `render_markdown` — shows `Platform: <name>` on each slip header; renders
    `None` payout as `n/a`.
  - `main` — applies the vetted filter when a workbook exists.
- `scripts/test_build_slips.py` — added `VettedPerPlatformTests` (5 new tests) and
  a `platform` param to the `projection()` helper (default `None` = single legacy
  group, so the 8 existing tests are unchanged).

Unchanged (money-safety constraints honored): `sports_system_runner.py`, Gate 8,
`allocate_eligible_candidates`, Picks output, bankroll ledger, Slip History
grading, workbook schema. No Underdog payout numbers invented. No change to
`send_slips_telegram.py` (it reads the markdown verbatim — still valid).

## Test results (final run)

```
$ cd scripts && python3 -m unittest test_build_slips test_audit_slips -v
test_conservative_slips_prioritize_hit_probability ... ok
test_correlated_estimates_are_clearly_marked_approximate ... ok
test_diversified_slips_avoid_same_player_overlap ... ok
test_highest_ev_slips_prioritize_ev_and_pass_audit ... ok
test_independent_2_leg_probability_is_product ... ok
test_kat_overlapping_props_allowed_only_in_kat_or_correlated_categories ... ok
test_negative_correlation_reduces_combined_probability ... ok
test_strongly_correlated_same_player_does_not_exceed_weakest_leg ... ok
test_filter_to_vetted_excludes_unmatched ... ok
test_make_slip_uses_real_leg_platform ... ok
test_no_slip_mixes_platforms ... ok
test_platform_with_fewer_than_two_legs_emits_no_slip ... ok
test_slip_has_no_duplicate_legs ... ok
test_audit_catches_duplicate_legs ... ok
test_audit_catches_impossible_combined_probability ... ok
test_audit_catches_missing_projection_reference ... ok
test_audit_catches_unexplained_negative_correlation ... ok
----------------------------------------------------------------------
Ran 17 tests in 0.034s
OK
```

8 pre-existing tests unchanged + 5 new tests + 4 audit tests = 17 passed, 0 failed.
`test_grade_slips_backfill.py` also re-run: 12 passed (no regression).

## Task 3 — trace-verification of today's (2026-06-22) regenerated slips

Regenerated `data/research/slips/slips_2026-06-22.{json,md}` with
`python3 build_slips.py --date 2026-06-22`. Result:
`vetted_source: workbook`, `eligible_count: 73` (vetted), `platform_breakdown:
{PrizePicks: 13, Underdog: 60}`.

An independent trace script re-derived the vetted universe directly from
`data/mlb/mlb_2026-06-22.xlsx` (4 APPROVED + 75 Gate-8 CONCENTRATION-CAP rows = 79
rows / 78 distinct keys) and checked every emitted leg:

| Check | Result |
|-------|--------|
| Every leg traces to an APPROVED or Gate-8 cap-held workbook row (player+line+platform key AND stat-token subset) | PASS — zero unvetted legs |
| No slip mixes platforms | PASS |
| Every slip carries a real platform label (Underdog / PrizePicks) | PASS |
| No slip has a duplicate leg (same player+stat+line) | PASS |

Per-platform slip counts: **Underdog 8, PrizePicks 5** (13 total).
Per-category: safest_2_leg 2, safest_3_leg 2, highest_ev 4, correlated_upside 3,
diversified 2, kat_based 0.

NBA emitted nothing for the date (no NBA projections/workbook — only `data/nba/
nba_2026-06-22.xlsx` exists with no vetted prop picks), consistent with the
"<2 vetted legs → no slips" rule. The 2 "1st Inn." APPROVED/Gate-8 picks (Hunter
Brown, Andre Pallante, Michael Wacha 1st-inning props) and "Walks Allowed" picks
correctly produced NO legs — there are no matching full-game projections at those
lines/stats, so fail-safe excluded them. Correct behavior.

`audit_slips.py --date 2026-06-22` on the regenerated file: `ok: true`, 0 errors,
13 slips, 8 warnings (the expected "missing payout config for Underdog" warnings).

Markdown spot-check: PrizePicks slips show `Perfect payout: 3.0x`; all 8 Underdog
slip headers show `Perfect payout: n/a` — no fabricated Underdog numbers.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Duplicate-leg slips in `correlated_upside`**
- Found during: Task 3 trace-verification of the first regeneration.
- Issue: `prop_id` (`SPORT:player:stat:line`) excludes platform, so the same
  player/stat/line on Underdog and PrizePicks shares a prop_id. The correlation
  file pairs that prop with itself (`prop_a == prop_b`, labeled "strong positive
  correlation"). Within a platform group, `by_id.get(prop_a)` and
  `by_id.get(prop_b)` resolved to the SAME object, producing a slip with two
  identical legs (e.g. `[Zebby Matthews outs 15.5, Zebby Matthews outs 15.5]`).
  This violated plan truth #3 ("no slip contains a duplicate leg"). First
  regeneration showed 4 such duplicate slips.
- Fix: skip self-pairs (`prop_a == prop_b`) and require two distinct objects
  (`a is not b`) in the `correlated_upside` loop; added a defensive exact-prop_id
  dedup in `make_slip`; drop any slip that dedup collapses below 2 legs.
- Files modified: `scripts/build_slips.py`
- Commit: 0d6fded
- After fix: correlated_upside 6 → 3 slips; trace-verify all-green.

## Money-safety verification (downstream)

`grade_slips.py` reads `slip.get("platform") or "PrizePicks"` and passes it to
`calculate_slip_payout`. With slips now carrying the real `Underdog` platform, an
Underdog slip resolves to `payout_multiplier("Underdog", …) == None` →
`calculate_slip_payout` returns `slip_result: MANUAL REVIEW`,
`needs_payout_reconciliation: True`, `gross_return: None`, `net_pnl: None`. It does
NOT fabricate a payout and does NOT feed bankroll PnL. This is strictly safer than
the prior behavior, where Underdog legs were mislabeled "PrizePicks" and would
have had a WRONG PrizePicks multiplier applied to real money.

## Known follow-up (Phase 3)

- **Underdog payout tables are empty** in `data/research/platform_payouts.json`
  (`payout_multiplier("Underdog", …) == None`). Today, 8 of 13 slips (all 8
  Underdog slips) render `n/a` payout and would grade as MANUAL REVIEW. Populating
  Underdog payout tables with verified multipliers is explicitly out of scope here
  and tracked as Phase 3 work (per the plan's "Out of scope" section). Until then,
  Underdog slips are recommendation-only with no automatic payout/PnL.
- Also Phase 3 (per plan): removing Gate-8 caps from recommended Picks; slip-level
  total-stake bankroll.

## Self-Check: PASSED

- `scripts/build_slips.py` — FOUND (modified)
- `scripts/test_build_slips.py` — FOUND (modified)
- `data/research/slips/slips_2026-06-22.json` — FOUND (regenerated, 13 slips)
- `data/research/slips/slips_2026-06-22.md` — FOUND (regenerated)
- Commit 3a1bc6a — FOUND
- Commit 13e7484 — FOUND
- Commit 0d6fded — FOUND
