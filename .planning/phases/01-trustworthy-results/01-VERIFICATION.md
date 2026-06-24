---
phase: 01-trustworthy-results
verified: 2026-06-24
status: passed
score: 5/5 success criteria verified
re_verification:
  previous_status: passed
  previous_doc: 01-GAP-VERIFICATION.md
  note: "Top-level goal-backward verification (complements the gap-closure doc, which only covered the 4 verify-work gaps)."
requirements_covered: [RESULTS-01, RESULTS-02, RESULTS-03, RESULTS-04, RESULTS-05, RESULTS-06, RESULTS-07]
---

# Phase 1: Trustworthy Results — Verification Report

**Phase Goal:** Every prop grade resolves correctly — name and stat mismatches no longer produce MANUAL REVIEW for recoverable stats, every graded row carries provenance, and the June 8–21 MANUAL REVIEW backlog is reduced to only the genuinely unresolvable residue.
**Verified:** 2026-06-24
**Status:** passed
**Re-verification:** This is the top-level goal-backward verification. The pre-existing `01-GAP-VERIFICATION.md` (status: passed) only certified the 4 verify-work gap-closures; this doc independently confirms all 5 ROADMAP success criteria against the live code + data.

## Goal Achievement — 5 Success Criteria

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| 1 | June 8 dry-run gate: ≥80% of non-Fantasy-Score MANUAL REVIEW prop rows resolve to WIN/LOSS/PUSH after Layer-1 | ✅ TRUE | `test_june8_dryrun_gate.py` PASSES (2 tests). Pinned to fixed snapshot `testdata/june8_manual_review_snapshot.json` (37 documented rows, 35 non-DNP denominator). Asserts `rate >= 0.80` (line 336). DNP rows excluded as defense-in-depth. 01-UAT Test 1 = pass at 94.6% (35/37). Live data: June 8 MLB Results now has **0 MANUAL REVIEW** rows. |
| 2 | Every graded prop row carries `Result Source` (api/scraped/manual) + numeric `Result Confidence`; spread/total/parlay/VOID rows carry api/1.0 | ✅ TRUE | `RESULT_HEADERS` includes both columns (runner:324). Grading path sets them on every write: PROP `res_src,res_conf` (runner:6335-6392), SPREAD/TOTAL/VOID `api/1.0` (runner:6314), PARLAY `api/1.0` (runner:6476). Live data: all **84 rows written by the new path (Graded At 2026-06-22)** carry provenance (48 scraped, 36 api) — **100% coverage**. (60 legacy rows Graded At 2026-06-09 predate the phase and have no provenance — see Notes; they are settled rows the idempotency guard intentionally preserves, not rows "written by grading" in this phase.) |
| 3 | Re-grading overwrites MANUAL REVIEW/PENDING in place with terminal grades; settled WIN/LOSS/PUSH/VOID (any casing) untouched; no duplicate Results/Pick History rows | ✅ TRUE | Value-aware guard `(already.get(ref) or "").strip().upper() in TERMINAL_RESULTS: continue` on all 3 loops (runner:6298, 6328, 6406) — casing/whitespace-robust, skips only terminal rows. `upsert_result_row` updates in place keyed on (Date, Sport, Pick Ref) (runner:5317-5331). `sync_master_and_bankroll` calls `remove_master_pick_history_ref` before append (runner:5348) → no Pick History duplicates. Live data: 144 distinct Pick Refs / 144 graded rows = **0 duplicates**. |
| 4 | A parlay never mis-grades against a partial leg set: abstains (stays at prior result) when any constituent leg is not yet terminal | ✅ TRUE | Full-leg-set merge (runner:6412-6471): assembles complete leg set from persisted-terminal (`already`) + this-run `graded`, parses declared legs from `Legs` column, grades only if `all(lr in merged_leg_results for lr in declared_leg_refs)`, else `continue` (abstain, no upsert) with a `PARLAY ABSTAIN` log (runner:6470). Tests: `test_parlay_leg_backfill.py` + provenance tests green (34 passed). |
| 5 | Firecrawl fallback (flag `ENABLE_FIRECRAWL_RESULT_FALLBACK`, default off) degrades to MANUAL REVIEW on any failure/timeout/missing-binary/offline/429; grading never crashes; daily run stays under 660s budget | ✅ TRUE | Flag default `False` (runner:250). `verify_results.py` degrades to `skip`+`sys.exit(0)` on TimeoutExpired (552), FileNotFoundError/missing npx (555), generic exception (558), non-zero exit (562), 429/rate-limit (566), empty output (574). Caller guards `ENABLE_FIRECRAWL_RESULT_FALLBACK and _scrape_run_count < RESULT_SCRAPE_MAX_PER_RUN` (runner:6342); per-run budget 8 scrapes × 45s = 360s worst case. Task budgets pinned to 660s with SIGALRM clean self-termination (runner:111-161). DNP tri-state never auto-LOSS: `test_dnp_void.py` green. |

**Score:** 5/5 success criteria verified.

## Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| RESULTS-01 (robust name match, abstain on ambiguity) | ✅ SATISFIED | `name_match` 4-tier + `_canonical_name` (runner:3540-3654), abstains on 0 or 2+ matches |
| RESULTS-02 (composite/pitcher stat disposition table) | ✅ SATISFIED | `stat_value_for_prop` disposition table + fantasy-score derivation (runner:4533-4897) |
| RESULTS-03 (batting vs pitching namespace split) | ✅ SATISFIED | `is_mlb`/`bat`/`pit` namespace split (runner:4573-4575), separate hitter/pitcher score fns |
| RESULTS-04 (Result Source + numeric Result Confidence) | ✅ SATISFIED | Criterion 2 above; columns in `RESULT_HEADERS` and written on every new-path grade |
| RESULTS-05 (keyless subprocess firecrawl fallback, safe degrade) | ✅ SATISFIED | Criterion 5 above; `verify_results.py` + `resolve_missing_stat`/`resolve_player_appearance` |
| RESULTS-06 (in-place re-grade, no dup, settled untouched, parlay safety) | ✅ SATISFIED | Criteria 3 & 4 above |
| RESULTS-07 (June 8 ≥80% gate + backfill) | ✅ SATISFIED (already marked Complete in REQUIREMENTS.md) | Criterion 1 above; gate test green at snapshot, 01-UAT 94.6% |

## Targeted Test Runs (executed during verification)

| Suite | Result |
|-------|--------|
| `test_june8_dryrun_gate.py` | 2 passed |
| `test_dnp_void.py` | (in combined run) |
| `test_fantasy_score.py` | (in combined run) |
| combined: june8 + dnp_void + fantasy_score | **59 passed in 9.20s** |
| `test_prop_pnl_slip_terms.py` + `test_slip_payouts.py` | 24 passed |
| `test_parlay_leg_backfill.py` + `test_provenance_plumbing.py` | 34 passed |
| `test_generate_projections.py` | 2 failed, 7 passed — **the 2 documented pre-existing baseline failures only** (per MEMORY.md; not Phase 1) |

## Live Data Verification (June 8 MLB workbook)

`data/mlb/mlb_2026-06-08.xlsx` Results sheet:
- 144 graded rows: 71 WIN / 70 LOSS / 1 PUSH / 2 VOID — **0 MANUAL REVIEW remaining** (backlog cleared).
- 84 new-path rows (Graded At 2026-06-22): 100% provenance (48 scraped, 36 api).
- 144 distinct Pick Refs / 144 rows → **0 duplicate Pick Refs** (idempotency confirmed in real data).

## Anti-Patterns Scanned

- No unreferenced `TBD`/`FIXME`/`XXX` debt markers in `sports_system_runner.py` or `verify_results.py` (clean).
- Money-safe abstain paths verified throughout: name ambiguity, platform ambiguity (PP/UD), divergent fantasy grades, missing components, DNP-unknown, partial parlay leg sets — all degrade to MANUAL REVIEW / abstain, never a real-money guess.

## Notes (distinguishing real gaps from baseline noise)

1. **60 legacy June 8 rows without provenance (NOT a Phase 1 gap).** These rows carry `Graded At = 2026-06-09` (two weeks before Phase 1 began on 2026-06-23), have an empty `Pick Type`, and are terminal (WIN/LOSS) from the old grading path. Criterion 2 governs rows "written by grading"; the value-aware TERMINAL_RESULTS guard correctly skips these already-settled rows on re-grade, which is exactly the behavior required by Criterion 3. Backfilling provenance onto pre-existing settled historical rows is out of scope for this phase's stated criteria. Flagged for transparency, not as a blocker.

2. **2 pre-existing `test_generate_projections.py` failures are baseline noise**, not Phase 1 regressions (documented in MEMORY.md; clean baseline = "2 failed, 202 passed"). The previously-red `test_june8_dryrun_gate` is now GREEN (fixed by GAP 3 / plan 01-8).

3. **Pre-existing O(n²) read in `skipped_picks_summary_for_date`** (noted in 01-GAP-VERIFICATION.md) was independently fixed post-phase in a quick task (commit 1a8384e) — not a Phase 1 gap, and now resolved.

## Verdict

**PASSED.** All 5 ROADMAP success criteria are verified TRUE against the actual code and live June 8 data — not merely against SUMMARY claims. The grading path writes provenance on every row it produces, the value-aware terminal guard makes re-grades idempotent with no duplicates, parlays abstain on incomplete leg sets, the firecrawl fallback degrades safely to MANUAL REVIEW on every failure mode and stays within the 660s budget, and the June 8 dry-run gate clears ≥80% (94.6% UAT / snapshot test green). All 7 RESULTS requirements are satisfied. No genuine gaps; the only non-passing tests are the 2 documented pre-existing projection-baseline failures.

---

_Verified: 2026-06-24_
_Verifier: Claude (gsd-verifier)_
