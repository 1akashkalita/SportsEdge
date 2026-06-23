---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Slips & Props Tracking
status: executing
stopped_at: Phase 04.1 context gathered
last_updated: "2026-06-23T10:49:18.314Z"
last_activity: 2026-06-23 -- Phase 04.1 planning complete
progress:
  total_phases: 5
  completed_phases: 3
  total_plans: 19
  completed_plans: 16
  percent: 60
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-22)

**Core value:** Make the bankroll reflect actual DFS slips, track and grade both slips and props, and feed realized outcomes back into selection — so the operator can tell whether the model is improving.
**Current focus:** Phase 04.1 — close v2.0 audit gaps (forward staking, prop-accuracy refresh, calibration cleanup, P1/P2 verification debt)

## Current Position

Phase: 04.1
Plan: Not started
Status: Ready to execute
Last activity: 2026-06-23 -- Phase 04.1 planning complete

Progress: [█████████░] 94%

## Performance Metrics

**Velocity:**

- Total plans completed: 8 (v2.0); 17 (v1.0 historical)
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1. Trustworthy Results | TBD | - | - |
| 2. Slip Reconstruction and Grading | TBD | - | - |
| 3. Slips-Only Bankroll | TBD | - | - |
| 4. Dual Metrics and Feedback | TBD | - | - |
| 03 | 4 | - | - |
| 04 | 4 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 01-trustworthy-results P1 | 11 | 2 tasks | 4 files |
| Phase 01-trustworthy-results P01-3 | 10 | 2 tasks | 3 files |
| Phase 01-trustworthy-results P01-4 | 15 | 2 tasks | 4 files |
| Phase 01-trustworthy-results P01-5 | 11 | 2 tasks | 7 files |
| Phase 02-slip-reconstruction-and-grading P1 | 15 | 2 tasks | 2 files |
| Phase 02-slip-reconstruction-and-grading P2 | 12 | 3 tasks | 2 files |
| Phase 03-slips-only-bankroll P02 | 8 | 2 tasks | 2 files |
| Phase 03-slips-only-bankroll P03 | 20 | 2 tasks | 2 files |
| Phase 03-slips-only-bankroll P04 | ~90 | 3 tasks | 2 files |
| Phase 04-dual-metrics-and-feedback P01 | 20 | 3 tasks | 2 files |
| Phase 04-dual-metrics-and-feedback P02 | 320 | 2 tasks | 2 files |
| Phase 04-dual-metrics-and-feedback P03 | 30 | 3 tasks | 3 files |

## Accumulated Context

### Roadmap Evolution

- Phase 04.1 inserted after Phase 4: Close v2.0 audit gaps (BANKROLL-02 forward staking, daily prop-accuracy refresh, calibration dedup + WR-03, RESULTS-07/SLIPS-03 verification debt) (URGENT)
- Phase 04.1 edited: set real goal + BANKROLL-02 requirement + 5 success criteria; dropped RESULTS-07/SLIPS-03 verification-debt from title (routed to verify-work)

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Roadmap: Strict P1→P2→P3→P4 dependency chain — slips (P2) cannot grade without trustworthy results (P1); bankroll rebase (P3) requires graded slips (P2); feedback loop (P4) requires the rebased bankroll signal (P3)
- Roadmap: Phase 1 scope fully captured in approved spec `docs/superpowers/specs/2026-06-21-trustworthy-results-design.md` — two layers (in-process name/stat hardening then flagged firecrawl subprocess for residue), provenance columns, money-safe June 8–21 backfill
- Constraint: Additive-only workbook schema changes; no gate logic or pick verdict changes; tasks must stay under 660s cron budget (cron kill at 720s)
- Constraint: `ENABLE_FIRECRAWL_RESULT_FALLBACK` default off — Layer-1 alone carries the milestone; Layer-2 is residue-only and flag-gated
- Hard gate for Phase 1 done: ≥ 80% of non-Fantasy-Score MANUAL REVIEW prop rows resolve on the June 8 dry-run
- Plan 01-2: group_data.get("type") returns "batting"/"pitching" for MLB groups and None for NBA — the authoritative group identity field (NOT get("name") which is None for both sports in confirmed fixtures)
- Plan 01-2: MLB batting/pitching namespace split uses sub-dicts; NBA single-group path stays byte-identical flat dict
- Plan 01-2: Hit-type counts from plays[].type.type stored as batting._hit_counts; atBats top-level key absent (oracle RECLASSIFY #8)
- Plan 01-2: name_match abstains (returns None) on ambiguous Tier 3/4 matches — strictly no-guess for real-money grading
- [Phase ?]: Plan 01-5: Layer-2 flag default OFF; enable after smoke test confirms keyless firecrawl-cli@1.19.2
- [Phase 03, Plan 04]: Slips-only bankroll rebuilt from 2026-06-08 with starting_bankroll=100; live current_bankroll=126.778 (66 slips, 12 dates); 22 MANUAL REVIEW slips excluded (D-13); wipe-scope defect found+fixed (539cbdf) — wipe must cover full inception-onward range, not just slip-dates
- [Phase 03, Plan 04]: rebuild_bankroll task wired (660s budget, master_pnl.xlsx cooperative lock); one-time operator-authorized live write confirmed idempotent on second run

### Pending Todos

None yet.

### Blockers/Concerns

- ESPN summary availability for older dates (June 8–21) is unverified and may cap how many of the 86 MANUAL REVIEW rows are re-gradable — measure in dry-run, do not assume
- Keyless firecrawl end-to-end contract (keyless markdown scrape + parser) must be confirmed via the live smoke test before the flag is enabled in cron; until confirmed, flag stays off
- Fantasy Score formula (46-row residue): PrizePicks/Underdog weighting is unencoded; a subtly-wrong formula would mis-grade real money — scoped only to scraped fallback, not in-process derivation
- Side recovery for backfill: 86 MANUAL REVIEW rows have null Over/Under; re-parsed from Pick Ref and abstains on ambiguity — measure how many are recoverable in dry-run

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260621-ohh | fix send_slips_telegram urllib→requests SSL failure | 2026-06-22 | 2f245f5 | [260621-ohh-fix-send-slips-telegram-urllib-requests-](./quick/260621-ohh-fix-send-slips-telegram-urllib-requests-/) |
| 260622-p7x | Slip generation: vetted-only legs (APPROVED + Gate-8 cap-held), single-platform, real Underdog/PrizePicks labels, dedup | 2026-06-22 | 0d6fded | [260622-p7x-slips-vetted-per-platform](./quick/260622-p7x-slips-vetted-per-platform/) |

## Deferred Items

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| Human UAT | Phase 04: live run_log.jsonl accumulation · 🩺 health Telegram alert · 🔁 repeated-failure alert | Acknowledged | v1.0 close (2026-06-22) |
| Human UAT | Phase 05: real `git push` fires pre-push gate · `--no-verify` escape hatch | Acknowledged | v1.0 close (2026-06-22) |
| Verification | Phase 04 & 05 VERIFICATION.md status=human_needed (live-env confirmation only) | Acknowledged | v1.0 close (2026-06-22) |
| Nyquist | Validation incomplete: P1/P3 partial, P2/P4/P5 missing VALIDATION.md | Acknowledged | v1.0 close (2026-06-22) |
| Hardening | Phase 05 review WR-01…05 (WR-02: no pytest subprocess timeout in CI gate) — non-critical | Acknowledged | v1.0 close (2026-06-22) |
| Future req | Persist Player/Stat/Line/Side as real structured columns (removes string-parsing fragility) | Deferred past P1 | REQUIREMENTS.md |
| Future req | Exact PrizePicks/Underdog Fantasy Score payout formulas (46-row residue) as first-class derivation | Higher-risk, separate workstream | REQUIREMENTS.md |

## Session Continuity

Last session: 2026-06-23T10:09:09.838Z
Stopped at: Phase 04.1 context gathered
Resume file: .planning/phases/04.1-close-v2-0-audit-gaps-forward-confidence-staking-bankroll-02/04.1-CONTEXT.md
