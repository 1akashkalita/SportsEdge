---
status: passed
phase: 01-trustworthy-results
type: gap_closure
verified: 2026-06-23
gaps_closed: 4
plans: [01-7, 01-8, 01-9, 01-10, 01-11]
---

# Phase 01 — Gap-Closure Verification

Closes the 4 fixes diagnosed during `/gsd-verify-work 1` (see `01-UAT.md`).

## Gaps closed

| Gap | Fix | Plan | Evidence |
|-----|-----|------|----------|
| GAP 4 — prop PnL ≠ slip-terms | Individual PROP and single-pick SPREAD/TOTAL rows now write `PnL=0`; parlay/slip PnL preserved (`odds_profit` untouched) | 01-7 | `test_prop_pnl_slip_terms.py` (7 tests) green; BANKROLL-01/D-09 |
| GAP 3 — non-idempotent gate test | `test_june8_dryrun_gate.py` rewired to a pinned pre-backfill 37-row snapshot fixture; DNP→VOID rows excluded; measures 35/35=100% | 01-8 | gate test now green + stable (was permanently red) |
| GAP 1 — DNP parked in MANUAL REVIEW | `player_appearance()` tri-state in `verify_results.py` + `resolve_player_appearance()`; confirmed DNP → VOID, ambiguous/unknown → MANUAL REVIEW, never auto-LOSS; behind `ENABLE_FIRECRAWL_RESULT_FALLBACK` (default OFF) | 01-9 | `test_dnp_void.py` green |
| GAP 2 — Fantasy Score unencoded | PrizePicks/Underdog hitter+pitcher scoring encoded in `stat_value_for_prop`; `_prop_platform()` recovery; money-safe abstain on platform ambiguity + divergent SB/W/QS, and on missing components | 01-10 | `test_fantasy_score.py` (27 tests) green |

## Full-suite regression gate (01-11)

`cd scripts && python3 -m pytest -q --timeout=120` → **5 failed, 773 passed, 5 skipped** (698s).

- 4 new gap-test files: **66 passed** (run isolated, 45s).
- `test_june8_dryrun_gate` — **now PASSES** (was the 4th pre-existing failure; fixed by GAP 3).
- 773 passed vs pre-gap 708 + the new gap tests — consistent, no lost coverage.

### Failure triage (no gap-closure regressions)

| Failed test | Class | Verdict |
|-------------|-------|---------|
| `test_generate_projections::test_castle_points_assists_case_has_negative_ev` | pre-existing baseline | not introduced here |
| `test_generate_projections::test_kat_pra_case_uses_projection_line_sigma_not_hit_rate` | pre-existing baseline | not introduced here |
| `test_grade_slips_legs::test_unrecognised_mlb_stat_returns_pending_not_loss` | pre-existing baseline | not introduced here |
| `test_stage2_obsidian_messages::test_recap_alert_includes_platform_breakdown_when_present` | **environmental timeout** | not a regression — see below |
| `test_stage3_results_clv::test_build_recap_alert_uses_platform_breakdown_from_check_results` | **environmental timeout** | not a regression — see below |

**Environmental timeouts (proven not gap-related):** both hang in `build_recap_alert` → `skipped_picks_summary_for_date(today_str())`, which loops `ws.cell(r,1)` on a **read-only** openpyxl sheet (each access re-parses the whole XML — O(n²)). Today's live `mlb_2026-06-23.xlsx` `Skipped Picks` sheet has **1,488 rows** (bloated by the running system through the day), so the read exceeds the 120s test timeout. The gap commits left `build_recap_alert` and `skipped_picks_summary_for_date` **byte-identical** (verified via `git diff`), so the behavior is independent of this phase. These tests passed in the pre-gap full run when the live workbook was smaller; they are not isolated from the real data dir.

## Follow-up finding (out of scope, flagged)

**Pre-existing O(n²) read in `skipped_picks_summary_for_date` (sports_system_runner.py:~1188).** Read-only `ws.cell()` per-row access re-parses the sheet each call; at 1,488 `Skipped Picks` rows it already exceeds 120s. This runs on the **live recap/alert path** and could threaten the 660s cron budget as workbooks grow. Recommend: iterate rows once (`ws.iter_rows`) instead of indexed `ws.cell()`, and/or investigate why the 2026-06-23 `Skipped Picks` sheet reached 1,488 rows (reruns appending without clearing). Not part of the 4 verify-work gaps; captured for a future quick fix.

## Verdict

All 4 verify-work gaps are encoded and tested green; no gate-logic or pick-selection-verdict changes; the previously-red RESULTS-07 gate now passes; no regressions introduced by the gap closure (the 2 new failures are a pre-existing environmental perf issue). **status: passed.**
