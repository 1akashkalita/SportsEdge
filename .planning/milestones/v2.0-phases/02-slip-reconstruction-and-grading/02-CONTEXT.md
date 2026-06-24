# Phase 2: Slip Reconstruction and Grading - Context

**Gathered:** 2026-06-22
**Status:** Ready for planning
**Source:** Orchestrator synthesis (slip infra already exists; P1 grading now trustworthy)

<domain>
## Phase Boundary

P2 turns the model's recommended SLIPS into a graded, recorded ledger — so slip success is tracked separately from prop success. It does NOT rebase the bankroll (P3) or add a feedback loop (P4); P2 only reconstructs/grades/records slips and backfills June 8–21.

Crucial existing state (discovered): `build_slips.py` ALREADY runs daily and writes slip definitions to `data/research/slips/slips_<date>.json` (+ `.md`). Today (2026-06-22) has 8 slips across categories (safest_2_leg, safest_3_leg, highest_ev×2, correlated_upside×3, diversified) from eligible_count=75. So "reconstruct slips" is largely already done for recent dates — the missing piece is GRADING them and POPULATING the always-empty Slip History sheet.
</domain>

<decisions>
## Implementation Decisions (LOCKED defaults — sensible, revisit in P3)

### What to grade
- Grade EVERY model-recommended slip category per day (safest_2/3_leg, highest_ev, correlated_upside, diversified, kat_based when present) and record each in Slip History tagged by category. This is the backtest of the model's slip recommendations. (P3 decides which categories feed the slips-only bankroll.)
- Slip definitions come from `data/research/slips/slips_<date>.json`. If a date in June 8–21 has no slip file, run `build_slips.py --date <date>` first (it needs that date's projections, which exist under data/research/projections / backtest_<date>.json).

### How to grade a slip (the key technical point)
- A slip's legs are drawn from the FULL projection board (~75 eligible), NOT just the ~4 props the system bet — so most legs have NO row in the per-day Results sheet. Therefore grade each leg DIRECTLY against box scores, reusing P1:
  1. Build a DATE-WIDE player_stats lookup by merging every final game's box score for that date (reuse `espn_player_stats_by_event` per game from `game_completion_monitor`'s scoreboard, or `espn_player_stats`).
  2. For each leg `{player_name, stat_type, line, side}`, call the P1-hardened `stat_value_for_prop` (name_match + disposition table + batting/pitching namespaces) against the merged lookup → leg result WIN/LOSS/PUSH, or abstain (None) if unresolved.
  3. A leg whose prop can't resolve (DNP/MANUAL REVIEW/Fantasy/absent) makes the slip PENDING / "Needs Payout Reconciliation" — NEVER assume a leg lost. Money-safety: do not fabricate a slip outcome from a partial leg set (mirror P1's parlay full-leg-set rule).
- Aggregate legs → winning_legs / losing_legs / push legs → `slip_payouts.payout_multiplier(platform, slip_type, total_legs, winning_legs)` / `calculate_slip_payout(...)` → slip result + gross return + net pnl. Power = all-or-nothing; flex = partial payout per the config.

### Stake / platform
- Stake = FLAT 1 unit per slip for P2. (Confidence-scaled stake is explicitly P3 — out of scope here.)
- Platform = PrizePicks; payout config `data/research/platform_payouts.json` via `slip_payouts.load_payout_config`. slip_type (power/flex) comes from the slip json.

### Recording
- Write each graded slip via `slip_payouts.slip_history_row(...)` into the Slip History sheet (already in `ensure_workbook`'s sheet set) of the per-day workbook AND a master Slip History (master_pnl.xlsx "Slip History"). Use a stable Slip ID (e.g. `<date>:<category>:<leg_count>` or a hash of legs) so re-running is IDEMPOTENT (no duplicate rows) — mirror the prop-grading replace-by-ref pattern.
- SLIPS-04: slip success (Slip History: slip result, payout multiplier, net pnl) stays SEPARATE from prop success (Results/Pick History). Do not merge them.

### Claude's Discretion
- Exact module placement (a new `grade_slips.py` vs functions in the runner), Slip ID scheme, how slip grading is invoked (new runner task `grade_slips` vs standalone), test file names — as long as the contracts + constraints below hold.
</decisions>

<canonical_refs>
## Canonical References (read before planning/implementing)
- `scripts/slip_payouts.py` — payout_multiplier:56, calculate_slip_payout:64, slip_history_row:200, ensure_slip_history_sheet:187, SLIP_HISTORY_HEADERS:18, load_payout_config:27 (config at data/research/platform_payouts.json).
- `scripts/build_slips.py` — produces the slip definitions; `scripts/send_slips_telegram.py` — slip notifier.
- `data/research/slips/slips_2026-06-22.json` — slip + leg structure (legs have player_name, stat_type, line, side, sport, prop_id, confidence_tier, over_probability).
- `scripts/sports_system_runner.py` — REUSE P1 grading: stat_value_for_prop ~4322, name_match ~3540, grade_prop ~4598, espn_player_stats_by_event ~5318, game_completion_monitor (scoreboard iteration) ~4684, espn_player_stats. Slip History sheet is created by ensure_workbook.
- `docs/superpowers/specs/2026-06-21-trustworthy-results-design.md` — P1 grading contracts the slip grader reuses.
</canonical_refs>

<scope_fence>
## Scope Fence
- Reuse P1 grading; do NOT change gate logic, pick verdicts, or prop grading. Slip History is additive (sheet already exists).
- Money-safety: a slip with any unresolved leg is PENDING/reconcile, never a fabricated WIN or LOSS. Idempotent backfill (no duplicate Slip History rows).
- No bankroll rebase (P3), no confidence-scaled stake (P3), no feedback loop (P4). Flat 1u stake here.
- Run from scripts/ with python3 (3.14); tasks under the 660s cron budget; stdlib unittest, targeted tests.
</scope_fence>

<deferred>
## Deferred (P3/P4)
- Slips-only bankroll + confidence-scaled stakes (P3).
- Choosing which slip category(ies) constitute "the bet" for the bankroll (P3).
- Feedback into selection (P4).
</deferred>

---

*Phase: 02-slip-reconstruction-and-grading*
*Context synthesized 2026-06-22*
