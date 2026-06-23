# Phase 3: Slips-Only Bankroll - Context

**Gathered:** 2026-06-22
**Status:** Ready for planning
**Source:** Interactive discuss-phase (operator decisions, default mode)

<domain>
## Phase Boundary

P3 re-sources the bankroll ledger so it reflects **only DFS slips**, not individual props:
- Bankroll balance is computed strictly from slip Net PnL (BANKROLL-01).
- Each slip is staked by a confidence-scaled, tiered % of the running bankroll (BANKROLL-02).
- Bankroll history is rebuilt once from inception (2026-06-08) onto the slips-only basis (BANKROLL-03).
- Prop W/L is decoupled from the bankroll and retained as a separate model-accuracy signal (BANKROLL-04).

This phase clarifies HOW to do the above. It does NOT add the dual-metrics report or the
outcome→selection feedback loop (P4 / METRICS-01..03), and it does not rebuild the projection
model. The ONE sanctioned change to pick selection is removing the Gate-8 exposure caps (D-07);
all other no-bet gates stay intact.
</domain>

<decisions>
## Implementation Decisions

> Every decision below is trackable as **D-NN**. The planner MUST reference the relevant D-IDs in
> plan `must_haves` / `truths` so the decision-coverage gate passes. BANKROLL-01..04 map onto these.

### Bet universe — which slips count (BANKROLL-01)
- **D-01:** Every model-recommended slip is a candidate bet. **All 6 categories** (safest_2_leg,
  safest_3_leg, highest_ev, correlated_upside, diversified, kat_based) and **all per-day variants**
  (e.g. all 3 correlated_upside pairs, highest_ev×2) count. Curation happens through stake sizing +
  the zero-floor, NOT by excluding categories. This is the P3 answer to the universe question P2
  explicitly deferred. Matches the 88 already-graded slip rows across Jun 8–21.

### Confidence-scaled staking (BANKROLL-02)
- **D-02:** Stake signal = `combined_probability` (primary — sets the tier) **gated by**
  `combined_ev_score`. Both signals matter; probability is the monotone axis.
- **D-03:** Tiered stake as **% of the CURRENT (running) bankroll**:
  - `combined_probability ≥ 0.75` → **2.5%**
  - `0.65 ≤ combined_probability < 0.75` → **1.5%**
  - `0.58 ≤ combined_probability < 0.65` → **0.75%**
- **D-04:** Zero-floor — `combined_probability < 0.58` → **stake 0** (slip recorded, not bet).
- **D-05:** EV gate — `combined_ev_score ≤ 0` → **stake 0** (recorded, not bet), regardless of
  probability. Among +EV slips, probability alone sets the tier. (`combined_ev_score` is a model
  score on an un-normalized scale (~1.47 in samples), so the gate is a positivity/sign test, not a
  tuned numeric cutoff.)
- **D-06:** Monotonicity guarantee — because probability sets the tier and EV only gates downward to
  zero, a higher-confidence slip never receives a *smaller* stake than a lower-confidence slip on the
  same day under the same bankroll. This is exactly success-criterion #2 — verify it explicitly.
- **D-14:** Intra-day sizing basis (disambiguation of D-03's "% of current bankroll"): all of a
  given day's slips size off the **same start-of-day bankroll snapshot** — stakes do NOT compound
  within a day; the day's aggregate Net PnL is applied once at day close. This keeps the chronological
  rebuild order-independent and reproducible (criterion #1). *Operator did not pick this explicitly —
  it is the sane deterministic default; flag at plan review if intra-day compounding is wanted instead.*

### Exposure / Gate 8 (risk control)
- **D-07:** **Remove the Gate-8 exposure caps in P3** — the `DAILY_EXPOSURE_CAP` constant
  (`sports_system_runner.py:91`), the dynamic-cap skip ("GATE 8 — DYNAMIC EXPOSURE CAP",
  `:2711`), and the global NBA+MLB cap enforced during pick generation (~`:2782`–`:3326`,
  `:3223`). This **changes pick outputs** (more picks get approved) and touches the selection path —
  treat it as its own task, preserve ALL other gates (G1–G7, G9, G12, MLB sub-gates), and confirm
  nothing else depends on the cap (e.g. rerun-clears-own-rows logic). This is the single sanctioned
  pick-selection change; P4/METRICS-03 still requires overall gate integrity.
- **D-08:** **No daily slip-exposure budget** — per-slip tiers (D-03) + the zero-floor (D-04/D-05)
  are the ONLY risk controls. A heavy +EV slate may stake 15%+ of bankroll in one day, by design.
  Deferred preference: if a daily cap is ever added, enforce via **proportional scale-down** of every
  slip (preserves the D-06 ordering), not by dropping slips.

### Prop / bankroll separation (BANKROLL-01, BANKROLL-04)
- **D-09:** Bankroll is computed **strictly from slip Net PnL**. Props are fully decoupled — prop
  grades no longer touch `bankroll.json`, the master `Daily Log` bankroll, or `Bankroll Chart Data`.
  The current prop→bankroll coupling in `sync_master_and_bankroll` (`:5070`) must be severed.
- **D-10:** Prop W/L **stays in place** in master `Pick History` / per-day `Results` (that data IS the
  accuracy record — do not move it). Add a **separate Prop Accuracy summary** (hit-rate by week &
  sport) that is distinct from every bankroll sheet. Keep it additive (new sheet or a markdown
  report — Claude's discretion).

### Rebase from inception (BANKROLL-03)
- **D-11:** **One-time clean rebuild** of bankroll history from **2026-06-08**: wipe the prop-based
  bankroll series (`Daily Log` bankroll column + `Bankroll Chart Data`) and recompute chronologically
  from slip Net PnL, `starting_bankroll = 100`. Deterministic — re-running with no new slips yields
  the same balance (criterion #1).
- **D-12:** **Recompute the graded slips' stakes IN PLACE** with confidence %-stakes — overwrite
  `Stake Units`, `Gross Return`, and `Net PnL` on the EXISTING Slip History columns (flat-1u was P2's
  explicit placeholder; same columns → not a schema change). Stake = tier% × start-of-day bankroll on
  that slip's date (D-14), processed in date order. Idempotent re-run (keyed by Slip ID).
- **D-13:** **Money-safety carried from P2** — slips with unresolved legs (`PENDING` / "Needs Payout
  Reconciliation") have no Net PnL and are **excluded** from the bankroll until they resolve; never
  fabricate a slip outcome. Mirror the existing `PENDING`/`MANUAL REVIEW` exclusion in
  `sync_master_and_bankroll`.

### Claude's Discretion
- Module placement: modify `sync_master_and_bankroll` vs add a dedicated slip-bankroll function / a
  new runner task that owns `bankroll.json` — as long as the contracts above hold.
- Exact form of the Prop Accuracy summary (new master sheet vs markdown report), the confidence-tier
  helper's location, and test file names.
- Where the staking function lives (e.g. `slip_payouts.py` vs a new `stake_sizing.py`) — keep it
  reusable by both the rebuild and the forward daily path.
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Bankroll computation (to re-source — BANKROLL-01/03)
- `scripts/sports_system_runner.py` — `sync_master_and_bankroll:5070` (current prop→bankroll funnel:
  Pick History → Daily Log → `current = starting + total_profit`), `bankroll_state:461`,
  `BANKROLL` const `:62`, `refresh_performance_breakdown:4690`, `DAILY_EXPOSURE_CAP:91`,
  Gate-8 dynamic cap skip `:2711`, pick-generation cap path `~:2782`–`:3326` (global cap `:3223`).
- `data/pnl/bankroll.json` — single bankroll source of truth (`starting_bankroll:100`,
  `current_bankroll`, `roi_percentage_current`, `last_graded_date`).
- `data/pnl/master_pnl.xlsx` — sheets: `Daily Log` (31r), `Pick History` (278r), `Performance
  Breakdown`, `Bankroll Chart Data` (16r), `Slip History` (**88 graded rows, Jun 8–21**),
  `Conditional Specials`.

### Slip staking & payouts (BANKROLL-02/03)
- `scripts/slip_payouts.py` — `SLIP_HISTORY_HEADERS:18` (incl. `Stake Units`, `Gross Return`,
  `Net PnL`, `Slip Result`, `Needs Payout Reconciliation`), `payout_multiplier:56`,
  `calculate_slip_payout:64`, `slip_history_row:200`, `load_payout_config:27`
  (config `data/research/platform_payouts.json`).
- `data/research/slips/slips_<date>.json` — per-slip `combined_probability`, `combined_ev_score`,
  `slip_type` (power/flex), `leg_count`, `category`, `stake_units` (currently flat 1.0); legs carry
  `confidence_tier`, `over_probability`, `expected_value`. **Source of the confidence signals for
  re-staking the historical slips.**

### Phase contracts / requirements
- `.planning/phases/02-slip-reconstruction-and-grading/02-CONTEXT.md` — P2 slip grading contracts:
  Slip ID scheme, idempotent replace-by-ref, money-safety (PENDING never fabricated), flat-1u = P3
  placeholder, "which categories are the bet" explicitly deferred to P3.
- `.planning/REQUIREMENTS.md` — BANKROLL-01..04 (lines 26–29); METRICS-03 (gate integrity, P4).
- `docs/superpowers/specs/2026-06-21-trustworthy-results-design.md` — P1 grading contracts P2 reused
  (secondary for P3).
- `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/CONCERNS.md` — system map (persistence,
  atomic saves, gate gauntlet).
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `slip_payouts.calculate_slip_payout` / `slip_history_row` — recompute Gross Return & Net PnL once a
  confidence stake replaces flat 1u (D-12). Payout multiplier is independent of stake size.
- `sync_master_and_bankroll` (`:5070`) is the template for the slips version: per-period aggregation →
  running balance → write `bankroll.json` + `Bankroll Chart Data` + `Performance Breakdown` + atomic
  save. Reuse the shape; swap the data source from prop Pick History to Slip History.

### Established Patterns
- Idempotent replace-by-ref (`remove_master_pick_history_ref`) — mirror for Slip History so the
  in-place re-stake (D-12) and rebuild (D-11) are safe to re-run.
- `save_workbook_atomic` / `workbook_io.safe_save_workbook` — all master_pnl writes go through it.
- Additive schema migration (`ensure_workbook`) — the Prop Accuracy summary sheet (D-10) must be added
  this way; do NOT drop/rename existing columns.
- PENDING / MANUAL REVIEW exclusion already in `sync_master_and_bankroll` — extend the same money-safety
  rule to unresolved slips (D-13).

### Integration Points
- `bankroll.json` stays the single bankroll source of truth (D-09) — only its *inputs* change.
- The forward daily path (`daily_picks` → grade → `sync_master_and_bankroll`) must now stake new slips
  by confidence (D-02..D-05) and update the bankroll from slips, while prop grading still runs but no
  longer writes the bankroll.
- Removing Gate 8 (D-07) lives in the pick-generation path, NOT in `evaluate_no_bet_gates`'s linear
  gauntlet body — the cap is enforced during generation (`~:2711`, `:2782`–`:3326`).
</code_context>

<specifics>
## Specific Ideas

- Complete staking rule (deterministic), for the planner to encode and test directly:
  ```
  if combined_ev_score <= 0:            stake = 0          # recorded, not bet (D-05)
  elif combined_probability < 0.58:     stake = 0          # recorded, not bet (D-04)
  elif combined_probability >= 0.75:    stake = 0.025 * start_of_day_bankroll   # (D-03)
  elif combined_probability >= 0.65:    stake = 0.015 * start_of_day_bankroll
  else:  # 0.58 <= prob < 0.65          stake = 0.0075 * start_of_day_bankroll
  # no daily exposure cap (D-08); chronological rebuild from 2026-06-08, starting=100 (D-11/D-14)
  ```
- Verification anchors: (1) re-run rebuild with no new slips → identical `current_bankroll`
  (criterion #1); (2) two same-day slips, higher `combined_probability` ⇒ stake ≥ the lower one
  (criterion #2 / D-06); (3) a prop W/L flip changes the Prop Accuracy summary but leaves
  `current_bankroll` unchanged (BANKROLL-01); (4) `bankroll.json` series starts 2026-06-08
  (criterion #3 / BANKROLL-03).
</specifics>

<deferred>
## Deferred Ideas

- Daily total-slip-exposure budget / cap (operator chose none for P3 — D-08); if revisited, use
  proportional scale-down.
- Dual-metrics report (slip ROI + prop hit-rate over time) and outcome→selection feedback loop — P4 /
  METRICS-01..03. The Prop Accuracy summary (D-10) is a minimal stepping stone, not the full P4 report.
- Intra-day compounding of stakes (rejected default D-14 in favor of start-of-day snapshot).
- Structured Player/Stat/Line/Side columns on prop rows — already deferred past P1.

</deferred>

---

*Phase: 03-slips-only-bankroll*
*Context gathered: 2026-06-22*
</content>
</invoke>
