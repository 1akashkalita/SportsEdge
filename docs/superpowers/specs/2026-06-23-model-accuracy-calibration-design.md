# Design: Model Accuracy & Calibration

**Date:** 2026-06-23
**Status:** Approved (design); pending milestone planning via `/gsd-new-milestone`
**Author:** brainstormed with operator
**Supersedes/builds on:** v2.0 "Slips & Props Tracking" (shipped 2026-06-24) — which delivered trustworthy results, slip/prop grading, and the live `calibration.json` feedback loop this design extends.

---

## 1. Problem & framing

The operator's stated goal is to "fine-tune the model's accuracy and improve calibration." Investigation showed the request points at the wrong constraint:

- **"The model" is already simple and self-calibrating.** A projection is a weighted recency average
  `base = avg_L5·0.45 + avg_L10·0.35 + avg_L20·0.20`, nudged by an NBA pace factor and a minutes-trend
  factor, converted to an over-probability via a Normal CDF using a sigma estimated from recent
  game-to-game variance (`scripts/generate_projections.py:381–458`). A per-sport calibration factor
  already runs weekly (`scripts/calibration.py` → `data/research/calibration.json`), widening/narrowing
  sigma when the model proves over/under-confident.

- **The binding constraint is data starvation, not model math.** As of 2026-06-23 the live calibration
  loop has **1 usable graded NBA prediction and 33 MLB** (the gate to even *start* stepping is 30). Worse,
  **~76% of graded props (98.8% for NBA) carry no stored model probability at all**, so they are invisible
  to calibration. Grading was dormant June 10–22 (fixed three days ago), so live outcomes have barely begun
  to flow. Tuning against this much data would be fitting noise.

- **The unlock:** measuring *projection calibration* does not require the slow real-money grading loop. It
  requires `(predicted_distribution, actual_stat)` pairs — and a full ESPN gamelog history is already on disk.
  A walk-forward backtest can generate **~1k NBA and 10k+ MLB** prediction points immediately, three orders
  of magnitude more signal than the live loop.

### Data feasibility (verified)

- Stored gamelogs: `data/research/hit_rates/{nba,mlb}/` — **18 NBA players, 626 MLB players**.
- Each player-stat carries `sample_games`: up to 20 per-game records of
  `{actual, date, opponent, minutes, home_away}` — directly walk-forward-able.
- Caveat: NBA history is thin (finals, 18 players, ~20-game depth, mid-June snapshots). NBA conclusions will
  be weaker than MLB's; the harness must report N per slice rather than only aggregate.

---

## 2. Decisions locked during brainstorming

1. **Foundation = offline backtest harness** over the ESPN gamelog history (not "wait for live data," not
   "tune blind").
2. **End state = measure + tune + ship, gated.** Build the harness, establish a baseline, retune
   sigma/distribution + recency weights, prove improvement on held-out data, and ship the better params into
   live generation behind a reversible, default-off flag. Not a full model rebuild.
3. **Include the live-loop fix.** Repair the missing-probability-logging gap so the production
   `calibration.json` loop and future backtests both see real data going forward.

### Rejected approaches

- *Extend `calibration.py` to ingest backtest outcomes.* It can only move one global per-sport sigma knob —
  cannot tune recency weights or per-stat distribution width, and conflates offline model-quality signal with
  live betting signal. Retained only as a possible *consumer* of harness output later.
- *Throwaway exploratory tuning, hand-edit constants.* Fast to insight, but no reproducible harness, no
  validation gate, no regression protection on a real-money model. Discards the durable asset the project's
  core value ("tell whether the model is improving") requires.

---

## 3. Components

### A. Backtest harness — `scripts/backtest_projections.py`

Read-only over `data/`. For each player-stat history (chronological), walk forward: at game *i* (require ≥ N
prior games, default 5), build a projection **using only games < i**, then compare the predicted distribution
to the actual at game *i*. No look-ahead.

Emits metrics sliced by **sport / stat-type / confidence-tier / sample-size bucket / home-away**, each slice
reporting its N (thin NBA slices stay honest, not hidden):

- **Calibration:** reliability curve + Expected Calibration Error (ECE), Brier score, log-loss on over/under
  outcomes; and a **PIT (probability-integral-transform) histogram** — line-independent: are actuals
  uniformly spread across the predicted CDF? The cleanest "is sigma right" test.
- **Point accuracy:** MAE / RMSE of projected mean vs actual.

**The line question (explicit):** the gamelog stores only a *current* single `line`, not per-game historical
lines. So v1's primary metric is line-*independent* distribution calibration (PIT/coverage) plus a binary
check against a **synthetic rolling-median line**. *Optional enhancement (follow-on):* join real historical
lines from the dated workbooks (`data/{sport}/{sport}_{date}.xlsx`) for production-realistic betting
calibration. v1 stays clean and large-sample.

Output: a metrics report written under `data/research/` (e.g. `backtest_calibration_<date>.json` + a readable
summary), not into any live workbook.

### B. Parameterize the model

Lift today's hardcoded constants out of `scripts/generate_projections.py` into one config
(`data/research/model_params.json`, with the current values as the in-code default):

- L5/L10/L20 weights (0.45/0.35/0.20)
- sigma floor (0.75) and per-stat fallback sigmas (`fallback_sigma_for_stat`, lines ~246–275)
- minutes/pace factors (1.03/0.94; 1.05/0.95)

**Hard requirement:** a regression test proving that with default params the projections are **byte-for-byte
identical** to today. The refactor changes nothing until the flag is flipped.

### C. Tuner with held-out validation

A `tune` mode that searches params (coordinate/grid over a small, robust set — prefer few high-confidence
changes over many overfit ones) against the harness metric on a **train fold**, then reports final improvement
on an **untouched test fold**. Splits are **chronological** (tune earlier, validate later) to respect the
time series, with **per-player k-fold** to stabilize estimates given small N.

The calibration lever that matters most lives here: **sigma width** (floor, per-stat multipliers generalizing
the single per-sport factor) — that is what makes a stated 60% actually hit 60%.

**Out of scope (leading follow-up):** swapping the Normal distribution for count distributions
(Poisson/negative-binomial) on low-count stats (threes, strikeouts, steals, RBIs). If PIT histograms show
Normal is badly wrong for counts, that becomes the next milestone; per-stat sigma tuning only partially
compensates.

### D. Gated ship

`scripts/generate_projections.py` reads params via the config; a flag `USE_TUNED_MODEL_PARAMS` (`env_bool`,
**default off**) selects tuned vs baseline — same pattern as the existing calibration factor and feature flags.

**Ship gate:** tuned params must beat baseline on the held-out test fold by a set margin **with no per-stat
regression beyond tolerance**; operator reviews the evidence; then the flag is enabled. Reverting is flipping
the flag off.

### E. Live-loop probability-logging fix

Audit the three suspected MOP-blind paths:

1. game-market picks store `cover_probability`, not `over_probability`;
2. Gate-2 hit-rate-fallback picks pass with **no** model probability;
3. unprojectable markets get skipped (chronic stat-coverage gap).

Then ensure every pick **persists whatever probability it has** (over/cover) to Pick History with a **source
tag**, and where a model projection exists, **always store `model_over_probability` even for fallback-qualified
picks**. Additive columns only. Result: `calibration.json` sees real data going forward, and future backtests
can use live picks too.

---

## 4. Success criteria (the bar to "ship")

- Harness produces baseline calibration numbers per sport/stat with N reported. **(Phase 1 done.)**
- Parameterization is behavior-preserving (byte-identical projections with defaults) — proven by test.
- Tuned params **lower test-fold Brier/log-loss and ECE** vs baseline, **with no per-stat regression** beyond
  tolerance.
- Live picks log their probability + source going forward; production calibration is no longer blind to the
  majority of picks.

---

## 5. Constraints & safety

- `python3` (3.14), run from `scripts/`; sibling-import convention preserved.
- **Additive workbook schema only** — no dropped sheets/columns, no gate-logic or verdict changes except the
  deliberate, flag-gated projection-param change.
- New behavior behind a **default-off flag** so live picks stay byte-identical until the operator enables.
- Harness is **offline / read-only** over `data/` and **not** in the daily cron path → no cron-budget impact.
- Tests are `unittest`, run from `scripts/`, including the behavior-preservation regression test.

---

## 6. Risks & open questions

- **Thin NBA corpus** (18 players, ~20-game depth). The harness reports N honestly. **Phase-1 decision:**
  measure first; if NBA N is too thin to draw any conclusion, deepen history via `build_hit_rate_db`
  (full-season fetch) to enlarge the corpus. Disciplined order: measure → deepen only if needed.
- **Overfitting on small data** — mitigated by strict chronological train/test split and preferring few robust
  changes.
- **Normal-vs-count distribution mismatch** — the most likely "real" calibration culprit; scoped as the
  follow-up milestone if the data says so.
- **Selection of tracked players** — gamelogs exist only for players who appeared in DFS slates; calibration is
  therefore on the relevant population (acceptable/desirable, not a bias to fix).

---

## 7. Phases (becomes the roadmap)

1. **Measurement** — harness + baseline calibration report (+ decide whether to deepen NBA history).
2. **Tunable model** — parameter extraction (behavior-preserving) + tuner with held-out validation → candidate
   params + evidence.
3. **Ship & close the loop** — gated rollout of tuned params + live probability-logging fix.

---

## 8. Broader roadmap — this is milestone 1 of 3

During brainstorming the operator added two more capabilities. They are sequenced *after* this one because
both are EV/value judgments built on `model_over_probability` — only as trustworthy as the model's calibration,
which this milestone fixes. Bolting "recommend when value appears" onto a miscalibrated model surfaces *false*
value. The backtest harness built here is also what validates a future live model. Each milestone gets its own
GSD discuss → plan cycle; M2/M3 are captured here (not yet designed) so the investigation isn't lost.

**M1 — Model Accuracy & Calibration (this doc).** Offline backtest harness → tune → ship gated → live
probability-logging fix.

**M2 — Line-change re-evaluation + late-breaking pregame value (near-term).**
- *~80% already built, just not activated.* `prop_monitor` (`sports_system_runner.py:3789–3960`) already runs
  every 45 min during games and already detects favorable/unfavorable line moves (lines 3835–3857) — but it
  only *logs* them. The work: on a favorable move → re-run `evaluate_no_bet_gates` + the (pure, reusable) EV
  path → recommend if it now passes; append to Picks with a `line_improvement` source marker; respect Gate-8
  exposure caps for these mid-day adds.
- *Late-breaking pregame value:* injury news / starter ruled out / sharp move in the minutes before lock.
  Reuses the current model + gates.
- *Real gap to fill:* no intraday line *history* (only the latest line is stored per prop_id, overwritten each
  run) — add a Line History sheet / timestamped snapshots; this also enriches the backtest.
- *Calibration-independent early subset:* a *strictly-better* line on an already-vetted pick (e.g. wanted Over
  25.5, now 23.5) is better regardless of calibration — could ship before full tuning. Determining a
  *previously-skipped* prop is *now* +EV does need M1's calibration.

**M3 — True in-game / live picks (later, own milestone).**
- The system deliberately refuses live props today: Gate 12 blocks them (`line_timing.py:230–241`), and its own
  error says they "require a separate live projection model; live model unavailable." Live data already flows
  in (PrizePicks fetched with `in_game=true`) but is parked in the diagnostic-only Live Watchlist.
- The work: a **new in-game projection model** (remaining time, current pace, score state, foul trouble) — the
  pregame model can't price these; unblock Gate 12 (`enable_live_prop_betting`) behind that real model;
  possibly a tighter monitoring cadence (current floor is 5-min `game_completion_monitor`; sub-5-min needs new
  architecture). Validated against M1's backtest harness. Highest value-density, biggest effort, real-money
  policy change.

## 9. Process note

This repo runs on GSD (`.planning/`; STATE.md: "start the next milestone with `/gsd-new-milestone`"), and
CLAUDE.md mandates the GSD workflow. This design doc is the input artifact; the milestone will be planned and
executed through GSD (`/gsd-new-milestone`), not the default superpowers `writing-plans` hand-off. M2 and M3
will each get their own discuss → plan cycle when reached.
