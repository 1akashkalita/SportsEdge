# Phase 1: Trustworthy Results - Context

**Gathered:** 2026-06-21
**Status:** Ready for planning
**Source:** Approved design spec (brainstorming → 10-agent investigate/draft/adversarial-review workflow)

<domain>
## Phase Boundary

P1 makes prop grading trustworthy so every downstream phase (slips, bankroll, feedback) rests on correct results. It drives the ~37% MANUAL-REVIEW prop rate toward zero, attaches provenance to every graded row, and recovers the June 8–21 backlog — money-safely. It does NOT build slips, rebase the bankroll, or add a feedback loop (P2–P4).

Two isolated layers, built in order:
1. **Layer 1 — in-process matching hardening (offline, ships first):** name matching + stat disposition table + batting/pitching namespace split + provenance plumbing + the value-aware re-grade guard and parlay full-leg-set money-safety fix. Recovers most of the backlog with zero external dependency.
2. **Layer 2 — flagged keyless firecrawl scrape (default OFF):** `verify_results.py` subprocess + `resolve_missing_stat` adapter + per-event cache for the residual Fantasy-Score class. Enabled only after a live smoke test confirms the keyless contract.
3. **Backfill execution:** re-grade June 8–21 through the reconciliation path.
</domain>

<decisions>
## Implementation Decisions (LOCKED — from the approved spec)

The full, authoritative design is the canonical spec below. Every decision in it is locked. Key points the planner MUST honor:

### Matching hardening (Layer 1)
- New grading-local `_canonical_name` (accents via NFKD, strip `.`/`'`/`-`, drop Jr/Sr/II–IV) and `name_match` (exact → canonical → "F. Last" initial bridge → last-name-unique fallback; ABSTAIN when ambiguous). Do NOT modify `normalize_player_name:3482` (used outside grading).
- Rewrite `stat_value_for_prop:4039` into an explicit DIRECT/DERIVED/NOT-DERIVABLE disposition table; DELETE the substring fallback (`:4064-4066`) that causes false positives. Return a 3-tuple `(value, source, confidence)`.
- Extend `espn_player_stats_by_event:5318` with a batting/pitching namespace split (shared MLB labels currently clobber at `:5337`) and per-player hit-type counts from `plays`/`atBats`. NBA single-group output must stay byte-identical.

### Provenance (Layer 1)
- Add `Result Source` + `Result Confidence` to `RESULT_HEADERS` (additive, name-keyed via `ensure_ws_columns`/`result_headers`). Thread end-to-end: `stat_value_for_prop` → `grade_prop:4070` (now 5-tuple) → call sites (`:4613-4620`) → `result_record_from_source:4229` (two new keys via `extra`). Non-prop rows (spread/total/parlay/VOID) get `api`/`1.0`.

### Backfill money-safety (Layer 1)
- Evolve (do NOT revert) the `if ref in already: continue` guard (added in commit aa69c3b) into a value-aware, normalization-robust guard: `existing_result_map` + `TERMINAL_RESULTS = {WIN,LOSS,PUSH,VOID}`, skip only when `(already.get(ref) or "").strip().upper() in TERMINAL_RESULTS`. MANUAL REVIEW/PENDING re-grade; settled rows skipped.
- Parlay legs must be sourced from the FULL persisted leg set (merge this-run `graded` with persisted terminal legs from `existing_result_map`); ABSTAIN if any leg is non-terminal. The looser guard otherwise activates a real-money parlay mis-grade (`:4638` reads only the in-process list).
- Side recovery from the `PROP:<Player> <Stat> <Line>` ref must handle multi-word stats and ABSTAIN to MANUAL REVIEW on ambiguity.

### Firecrawl (Layer 2)
- `verify_results.py` invokes the real `firecrawl` bin via `npx -y firecrawl-cli@1.19.2 firecrawl scrape <espn-boxscore-url> --format markdown` (KEYLESS — no API key required; `FIRECRAWL_API_KEY` only raises limits). NO `--browser`, NO `--format json`, NO `init` on the cron host, NO `@latest`.
- Runner never imports firecrawl; `resolve_missing_stat` routes the subprocess through the existing `_subprocess_run_with_retry` (SIGALRM). Degrade to MANUAL REVIEW on any failure/timeout/offline/429. Flag `ENABLE_FIRECRAWL_RESULT_FALLBACK` default OFF. Budget: `RESULT_SCRAPE_MAX_PER_RUN` (default 8) × `RESULT_SCRAPE_TIMEOUT` (45s) < 600s.

### Verification oracle
- Component 0: two checked-in ESPN summary fixtures (one MLB w/ a two-way/shared-label player + `plays`/`atBats`, one NBA) under `scripts/testdata/espn_summary/`, plus `scripts/testdata/stat_corpus.json`. Every DIRECT/DERIVED key is validated against the fixtures BEFORE it is trusted.

### Claude's Discretion
- Plan/wave decomposition (Layer 1 vs Layer 2 vs backfill), exact test file names, helper placement — as long as the spec's contracts and the constraints below hold.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### P1 design (authoritative — read in full)
- `docs/superpowers/specs/2026-06-21-trustworthy-results-design.md` — the complete, review-hardened P1 design: components 0–8, data flow, the exact backfill guard change, config/flags, error handling, performance budget, and the 11-test strategy. Every load-bearing line reference in it is code-verified.

### Code touch points (in `scripts/sports_system_runner.py` unless noted)
- `grade_prop:4070`, `stat_value_for_prop:4039`, `normalize_player_name:3482`, `espn_player_stats_by_event:5318`, `grade_game_in_workbook:4548`, `result_record_from_source:4229`, `existing_result_refs:4430`, `upsert_result_row:4439`, `remove_master_pick_history_ref:4456`, `sync_master_and_bankroll:4465`, `RESULT_HEADERS:271`, `ensure_workbook:1782`. `innings_to_outs` analog in `scripts/build_hit_rate_db.py`.
</canonical_refs>

<specifics>
## Specific Ideas
- Clean baseline for the test suite is "2 failed, 202 passed" (the 2 known projection failures). Run targeted test files, not the ~34-min full suite, until phase end.
- The backfill recovery the operator is waiting on (June 15–21 ungraded MLB picks + the 86 MANUAL REVIEW rows) is unblocked by this phase's guard fix + Layer 1.
</specifics>

<deferred>
## Deferred Ideas
- Exact PrizePicks/Underdog Fantasy-Score payout formula (the 46-row residue) as a first-class derivation — higher-risk, separate workstream; Layer 2 scrape covers it for now.
- Persisting Player/Stat/Line/Side as real structured columns (removes string-parsing fragility) — additive, recommended, out of scope for P1.
- Live/forward firecrawl board fetching — distinct concern, not P1.
</deferred>

<scope_fence>
## Scope Fence
- Do NOT change gate logic or pick verdicts; no MANUAL REVIEW→terminal flip without a real resolution.
- Workbook schema changes are additive ONLY (two new RESULT_HEADERS columns via the migrating ensure_workbook).
- Run from `scripts/` with `python3` (3.14); tasks stay under the 660s cron budget.
- Firecrawl is for RESULT verification only — never historical board fetching.
</scope_fence>

---

*Phase: 01-trustworthy-results*
*Context synthesized 2026-06-21 from the approved design spec (commit cfb1809)*
