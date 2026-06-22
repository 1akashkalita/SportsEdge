---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Slips & Props Tracking
status: planning
last_updated: "2026-06-21T00:00:00.000Z"
last_activity: 2026-06-21
progress:
  total_phases: 4
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-22)

**Core value:** Make the bankroll reflect actual DFS slips, track and grade both slips and props, and feed realized outcomes back into selection — so the operator can tell whether the model is improving.
**Current focus:** Phase 1 — Trustworthy Results

## Current Position

Phase: 1 of 4 (Trustworthy Results)
Plan: — of — (not yet planned)
Status: Ready to plan
Last activity: 2026-06-21 — v2.0 roadmap created; 4 phases mapped to 14 requirements

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**
- Total plans completed: 0 (v2.0); 17 (v1.0 historical)
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1. Trustworthy Results | TBD | - | - |
| 2. Slip Reconstruction and Grading | TBD | - | - |
| 3. Slips-Only Bankroll | TBD | - | - |
| 4. Dual Metrics and Feedback | TBD | - | - |

**Recent Trend:**
- Last 5 plans: —
- Trend: —

*Updated after each plan completion*

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- Roadmap: Strict P1→P2→P3→P4 dependency chain — slips (P2) cannot grade without trustworthy results (P1); bankroll rebase (P3) requires graded slips (P2); feedback loop (P4) requires the rebased bankroll signal (P3)
- Roadmap: Phase 1 scope fully captured in approved spec `docs/superpowers/specs/2026-06-21-trustworthy-results-design.md` — two layers (in-process name/stat hardening then flagged firecrawl subprocess for residue), provenance columns, money-safe June 8–21 backfill
- Constraint: Additive-only workbook schema changes; no gate logic or pick verdict changes; tasks must stay under 660s cron budget (cron kill at 720s)
- Constraint: `ENABLE_FIRECRAWL_RESULT_FALLBACK` default off — Layer-1 alone carries the milestone; Layer-2 is residue-only and flag-gated
- Hard gate for Phase 1 done: ≥ 80% of non-Fantasy-Score MANUAL REVIEW prop rows resolve on the June 8 dry-run

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

Last session: 2026-06-21
Stopped at: v2.0 roadmap created — 4 phases, 14 requirements mapped, ready to plan Phase 1
Resume file: None
