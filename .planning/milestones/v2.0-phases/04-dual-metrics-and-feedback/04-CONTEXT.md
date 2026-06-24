# Phase 4: Dual Metrics and Feedback - Context

**Gathered:** 2026-06-23
**Status:** Ready for planning
**Source:** Interactive discuss-phase (operator decisions, default mode)

<domain>
## Phase Boundary

P4 delivers two things on top of the now-trustworthy slip/prop data from P1–P3:

1. **A dual-metrics report** — slip ROI + prop hit-rate, broken down **by week and by sport
   (NBA / MLB)**, surfaced to Telegram + Obsidian so the operator can answer "is the model
   improving or stagnant?" from data (METRICS-01).
2. **A bounded, integrity-safe outcome→selection feedback loop** — realized outcomes update
   **one** tunable projection parameter (per-sport probability calibration) in a way that
   provably cannot rewrite graded verdicts or alter the no-bet gate logic (METRICS-02 / METRICS-03).

This phase clarifies HOW to build those. It does NOT rebuild the projection model, add new gates
or bet types, change pick verdicts, or make non-additive schema changes. Exactly **one** tunable
parameter is wired (METRICS-02 requires "at least one"); other knobs are explicitly deferred.
</domain>

<decisions>
## Implementation Decisions

> Every decision is trackable as **D-NN**. The planner MUST reference the relevant D-IDs in plan
> `must_haves` / `truths` so the decision-coverage gate passes. METRICS-01..03 map onto these.

### Report delivery (METRICS-01)
- **D-01:** Deliver the report to **both** surfaces — a compact **Telegram** digest (push, where every
  other alert lands) **and** a persistent **Obsidian** note (durable, browsable over time). The
  existing Obsidian weekly-recap scaffold (`obsidian_create_weekly_recap:1034`) is currently a blank
  template — this fills it.
- **D-02:** Run via a **standalone weekly runner task** with its own cron entry (e.g. Monday morning),
  independently re-runnable — NOT appended to each daily run, NOT on-demand-only. Matches the "by week"
  grain and keeps the 660s daily budget lean. Wire a new task into `run_task` mapping (`:7261`),
  `task_workbook_paths` (`:7200`), and `TASK_TIMEOUTS`, mirroring the `grade_slips` / `rebuild_bankroll`
  task pattern (`:7208`). *(The cron schedule itself lives in `~/.hermes` outside the repo — operator
  must add the schedule entry; note this in the plan/summary.)*

### Report content & "improving" signal (METRICS-01)
- **D-03:** Each **week × sport** row shows **slip ROI** and **prop hit-rate**, plus a **week-over-week
  delta and a ↑/→/↓ arrow** so direction is readable at a glance (optionally a rolling 3–4 week average
  to smooth small samples). NOT a plain table; NOT an auto-computed verdict line (that risks over-reading
  tiny samples — see Deferred).
- **D-04:** Headline **slip ROI and slip win-rate are computed over STAKED slips only** (`stake > 0`).
  Zero-stake "recorded-not-bet" slips (below the 0.58 confidence floor or EV≤0 per P3 D-04/D-05) are
  shown as a **separate informational count**, never blended into the money metric.
- **D-05:** **Slip ROI = Σ Net PnL / Σ Stake** (dollar-weighted) over staked slips; slip win-rate over
  the same staked set. Prop hit-rate reuses the existing P3 definition (`wins/(wins+losses)`, PUSH
  excluded) already computed by `refresh_prop_accuracy`.
- **D-06:** **Sport attribution is derived from the slip's legs** (legs carry `sport`; no top-level
  `sport` field exists, and **no cross-sport slips exist today** — verified across all slip files).
  Any future mixed-sport slip → a **"MIXED"** bucket. *(Operator did not pick this explicitly — it is
  the sane default for a case that does not currently occur; Claude's discretion to refine.)*

### Feedback target — what gets tuned (METRICS-02)
- **D-07:** The single tunable parameter is **projection probability calibration**: a per-sport factor
  applied to `model_over_probability` via the **sigma** path, recomputed from **realized hit-rate vs
  model-predicted probability**. If a sport's model is systematically overconfident, future
  probabilities are pulled toward reality. This reshapes future picks **through the SAME unchanged
  gates** — chosen over the hit-rate confidence-adjustment thresholds and the confidence→stake mapping
  because it is the most principled and the safest for METRICS-03 (it lives upstream of the gauntlet).
- **D-08:** **Granularity = per sport (NBA, MLB)** — two factors. Matches the report grain and pools
  enough outcomes to be meaningful at today's low volume. NOT per-stat-type (starves on samples), NOT a
  single global factor (blends NBA/MLB behavior). Per-stat granularity is deferred until volume grows.

### Feedback bounding, apply mode & window (METRICS-02 / METRICS-03)
- **D-09:** **Auto-apply, ON by default** — no feature flag. The operator chose a true closed loop from
  day one (deliberately deviating from the project's `ENABLE_*` default-off precedent, e.g.
  `ENABLE_FIRECRAWL_RESULT_FALLBACK`), trusting the hard bounds below as the safety net. The whole
  milestone goal is to stop babysitting; this is consistent with that.
- **D-10:** **Conservative hard bounds** (the entire safety net, since it auto-applies):
  - A sport's factor stays at neutral **1.0** until that sport has **≥ 30 graded outcomes** (cumulative,
    see D-11).
  - The factor moves **at most ±0.05 (±5%) per weekly cycle**.
  - The factor is **clamped to [0.85, 1.20]** at all times.
  - Semantics: **factor > 1.0 widens sigma** (less confident); **< 1.0 narrows** (more confident).
- **D-11:** **Cumulative since inception (2026-06-08)** measurement window — every graded outcome counts.
  Most samples (clears the 30-outcome gate fastest at low volume) and most stable. A **rolling window is
  deferred** until volume is plentiful (see Deferred).
- **D-12:** **Recompute cadence = weekly**, aligned with the report. *(Claude's discretion: whether the
  calibration recompute lives inside the same weekly report task or a sibling task, as long as both run
  weekly and stay under the 660s budget.)*

### Integrity safety — non-negotiable (METRICS-03)
- **D-13:** The feedback loop is **structurally prevented** from violating grading/gate integrity:
  - Calibration factors are written to a **separate, observable config artifact** (e.g.
    `data/research/calibration.json`), **read at projection time** by `generate_projections.py`. The
    loop **never** touches grading code, the `Results` / `Pick History` sheets, any graded verdict
    (WIN/LOSS/PUSH/VOID), or `evaluate_no_bet_gates` / gate thresholds.
  - Every update is **logged** (old → new factor, sample count, computed target) so it is auditable and
    reversible (revert = reset the config to 1.0).
  - A **test asserts** the guarantee: running the loop (a) changes **no** existing graded verdict, and
    (b) leaves `evaluate_no_bet_gates` logic/thresholds and its output verdicts unchanged.
  - The exact mechanism is the planner's discretion; the **guarantee is locked** by METRICS-03.

### Claude's Discretion
- Exact new task name(s) and whether the weekly report + the calibration recompute are one task or two
  (D-12).
- Module placement: a new `metrics_report.py` / `calibration.py` vs functions in the runner — keep
  reusable and testable, run from `scripts/` with `python3`.
- The precise calibration formula mapping realized-hit-rate-vs-predicted-probability → a sigma scaler
  (e.g. ratio of model-implied to empirical hit rate, smoothed), within the D-10 bounds.
- Exact Telegram digest wording and Obsidian markdown layout (reuse the weekly-recap scaffold shape).
- The "MIXED" sport bucket handling (D-06), test file names, and whether the report adds a new sheet or
  is markdown-only (keep additive if a sheet).
</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.** Every path is repo-relative.

### Phase contracts / requirements
- `.planning/REQUIREMENTS.md` — **METRICS-01, METRICS-02, METRICS-03** (lines 33–35); the success
  criteria for this phase.
- `.planning/ROADMAP.md` §"Phase 4: Dual Metrics and Feedback" (lines 106–117) — goal + the 3 success
  criteria (esp. criterion #3: gate/grading integrity confirmed by a test).
- `.planning/phases/03-slips-only-bankroll/03-CONTEXT.md` — P3 contracts this phase builds on: the
  `Prop Accuracy` sheet (D-10), confidence-scaled stake tiers (D-02..D-05, the source of zero-stake
  "recorded-not-bet" slips), slips-only bankroll (`sync_slip_bankroll`).
- `.planning/phases/02-slip-reconstruction-and-grading/02-CONTEXT.md` — Slip History schema, slip
  grading contracts, Slip ID / idempotency patterns.

### Report data sources
- `scripts/sports_system_runner.py` — `refresh_prop_accuracy:5293` + `PROP_ACCURACY_HEADERS:299`
  (prop hit-rate by ISO-week × sport — **reuse directly for the prop side**); `sync_slip_bankroll:5126`
  and its slip W/L/P aggregation (~`:5254`); `master_pnl_workbook:4849` (master `Slip History` /
  `Pick History` location).
- `scripts/slip_payouts.py` — `SLIP_HISTORY_HEADERS:18` (incl. `Stake Units`, `Gross Return`,
  `Net PnL`, `Slip Result`), `calculate_slip_payout:64`, `slip_history_row:200` — slip ROI inputs.
- `data/pnl/master_pnl.xlsx` — sheets `Slip History` (per-slip Net PnL + Stake), `Prop Accuracy`,
  `Pick History`, `Daily Log`, `Bankroll Chart Data`.
- `data/pnl/bankroll.json` — current slips-only bankroll (context only; the report reads outcomes, not
  the balance).

### Report delivery surfaces
- `scripts/sports_system_runner.py` — `send_telegram:428`, `dispatch_alerts:1244`,
  `build_picks_alert:1100`, `build_recap_alert:1198` (Telegram digest patterns);
  `obsidian_create_weekly_recap:1034` (**the blank weekly-recap scaffold to fill**) + `obsidian_sync`
  trigger usage; `run_task` mapping `:7261`, `task_workbook_paths:7200`, `grade_slips` /
  `rebuild_bankroll` dispatch `:7208` (**template for wiring the new weekly task** + its cooperative
  workbook locks + 660s budget).

### Calibration target (projection) — METRICS-02/03
- `scripts/generate_projections.py` — `model_over_probability:289` (normal CDF; **the injection
  point**), `estimate_sigma:277` (sigma_floor=0.75 — multiply by the per-sport factor here),
  `fallback_sigma_for_stat:245`, `clamp_probability:236`, `calculate_ev:295`.
- `scripts/sports_system_runner.py` — `apply_hit_rate_adjustment:1648` (the alternative knob that was
  NOT chosen — leave unchanged); `evaluate_no_bet_gates` (the gate gauntlet — **MUST stay byte-for-byte
  unchanged**, Gate 2 reads probability; METRICS-03).
- `docs/superpowers/specs/2026-06-21-trustworthy-results-design.md` — P1 grading contracts (secondary;
  relevant only so the loop knows what NOT to touch).

### System map
- `.planning/codebase/ARCHITECTURE.md`, `.planning/codebase/CONCERNS.md`,
  `.planning/codebase/CONVENTIONS.md` — persistence, atomic saves, gate gauntlet, task/cron model,
  stdout contract.
</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`refresh_prop_accuracy:5293`** already aggregates prop hit-rate by ISO-week × sport — the report's
  prop side reads the `Prop Accuracy` sheet (or reuses this aggregation), no new prop math needed.
- **`sync_slip_bankroll:5126`** already iterates `Slip History` and computes slip W/L/P (~`:5254`); the
  slip ROI side reuses the same row-reading shape over `Stake Units` / `Net PnL`.
- **`obsidian_create_weekly_recap:1034`** is a ready (blank) Obsidian note scaffold + `obsidian_sync`
  trigger — fill it instead of inventing a new Obsidian flow.
- **`send_telegram:428` / `dispatch_alerts:1244` / `build_*_alert`** — Telegram digest plumbing.
- **`grade_slips` / `rebuild_bankroll` task wiring** (`run_task:7261`, `task_workbook_paths:7200`,
  `TASK_TIMEOUTS`, cooperative locks) — the exact template for adding the new weekly task safely.
- **`estimate_sigma:277` / `model_over_probability:289`** — the calibration injection point:
  `sigma_eff = estimate_sigma(...) * per_sport_factor` (factor read from the config artifact).

### Established Patterns
- 660s SIGALRM per-task wall-clock budget — add a `TASK_TIMEOUTS` entry for the new task; keep it fast.
- `save_workbook_atomic` / `workbook_io.safe_save_workbook` for any workbook write; **prefer read-only**
  for the report. Additive `ensure_workbook` migration if a new sheet is added (no drop/rename).
- `env_value` / `env_bool` for config; **default-off precedent exists** (`ENABLE_FIRECRAWL_RESULT_FALLBACK`)
  — **D-09 deliberately deviates** (calibration is on by default, bounded instead of flagged).
- `safe_print` stdout contract + `JSON_RESULT={...}` task output; defensive SKIP states (no uncaught
  exceptions — missing data → SKIP, not crash).

### Integration Points
- **Calibration config** (`data/research/calibration.json`) is the ONLY coupling between outcomes and
  selection — read in `generate_projections.py` at projection time; only the projection *input* changes,
  the gate gauntlet is untouched (D-13 / METRICS-03).
- **New weekly task** wired into `run_task` + `task_workbook_paths` + cron (cron entry is outside the
  repo, in `~/.hermes`).
- **Report inputs** = `master_pnl.xlsx` `Slip History` (ROI) + `Prop Accuracy` (hit-rate); **outputs** =
  Telegram message + Obsidian note.
</code_context>

<specifics>
## Specific Ideas

- Concrete calibration bound set (for the planner to encode + test directly):
  ```
  # per sport in {nba, mlb}; factor persisted in data/research/calibration.json, default 1.0
  n = graded_outcomes(sport, cumulative since 2026-06-08)
  if n < 30:
      factor = 1.0                                   # gate not met → neutral (D-10/D-11)
  else:
      target = calibrate(realized_hit_rate, model_implied_prob)   # >1 if overconfident (D-07)
      factor = clamp(step_toward(prev_factor, target, max_step=0.05), 0.85, 1.20)  # (D-10)
  # applied at projection time: sigma_eff = estimate_sigma(...) * factor   (>1 widens, <1 narrows)
  ```
- Verification anchors (success-criteria-aligned):
  1. **METRICS-03 / criterion #3:** a test runs the loop and asserts NO existing `Results` verdict
     (WIN/LOSS/PUSH/VOID) changes AND `evaluate_no_bet_gates` logic/output is unchanged.
  2. **D-10 bounds:** with ≥30 synthetic overconfident outcomes, the factor moves up but by ≤ +0.05 and
     never exceeds 1.20; with <30 outcomes the factor stays exactly 1.0.
  3. **METRICS-01 / criterion #1:** the report renders ROI + hit-rate **by week × sport** with WoW
     arrows; ROI excludes zero-stake slips (D-04) and equals Σ Net PnL / Σ Stake (D-05).
  4. The factor is observable and reversible — reset `calibration.json` to 1.0 restores prior behavior.
</specifics>

<deferred>
## Deferred Ideas

- **Rolling-window calibration** — revisit from cumulative (D-11) to a trailing ~4–6 week window once
  graded volume is plentiful, for responsiveness to a recently-improved model.
- **Per-stat-type calibration granularity** — deferred from D-08 until samples per stat bucket are
  sufficient.
- **Auto-computed "improving/stagnant" verdict line** in the report — operator chose deltas + arrows
  (D-03) to avoid over-reading tiny samples; revisit with more data.
- **Additional feedback knobs** — the hit-rate confidence-adjustment thresholds (`apply_hit_rate_adjustment`)
  and the confidence→stake mapping (P3 tiers) were considered as feedback targets and NOT chosen; one
  well-bounded knob for P4. Adding more is a future workstream.
- **Daily / append report cadence** — operator chose a standalone weekly task (D-02).

None of the above were folded into P4 scope.
</deferred>

---

*Phase: 04-dual-metrics-and-feedback*
*Context gathered: 2026-06-23*
