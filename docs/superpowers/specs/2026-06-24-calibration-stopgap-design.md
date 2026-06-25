# Design: Probability-Calibration Stopgap (interim, before M2)

**Date:** 2026-06-24
**Status:** Implemented behind a default-OFF flag; pending operator activation.
**Builds on:** `2026-06-23-model-accuracy-calibration-design.md` (M2). This is the *interim*
de-risking measure that milestone's offline backtest harness will later supersede.

---

## 1. Why this exists

As of 2026-06-24 the model is measured ~18 points overconfident (MLB implied per-leg ≈ 88.3%
vs realized ≈ 70.3%), and the live EV slip engine (`ENABLE_EV_SLIP_TYPE=true`) had gone 0-for-13
producing aggressive all-Power slips. The full M2 calibration milestone takes weeks; this stopgap
stops the bleeding now by applying the *already-measured* per-sport overconfidence to live
probabilities, reversibly, behind a default-OFF flag.

The proper fix (offline backtest → tune sigma/weights → ship) remains M2. This is explicitly a
stopgap, not the model rebuild.

## 2. Mechanism (decision side)

A new flag **`USE_CALIBRATED_PROBABILITIES`** (`env_bool`, default **OFF**).

When ON, at the single projection source (`generate_projections.build_projection`), the model's
over-probability is shrunk symmetrically toward 0.5 by a per-sport factor:

```
over_cal = 0.5 + (over_prob - 0.5) * s
s        = (empirical - 0.5) / (model_implied - 0.5)     # derived from calibration.json
```

- `s` is read from the latest "computed" audit entry in `calibration.json` via
  `calibration.load_probability_shrink_factor(sport)`. It is **mean-matching by construction**:
  plugging `p = model_implied` gives `p' = empirical` (live MLB: 0.883 → 0.703, s ≈ 0.529).
- `s` is bounded to `[SHRINK_FLOOR=0.40, 1.0]`: it **never amplifies** confidence (`s ≤ 1`) and
  never collapses everything to 0.5 (`s ≥ 0.40`).
- **NBA gets no shrink** (`s = 1.0`): only 1 graded MOP outcome < the N_GATE of 30, so it is
  untrusted. We do not guess NBA.

Because the shrink happens at the source, every downstream consumer sees the calibrated value
uniformly — Gate 2 (overconfident borderline picks now correctly fail the 0.52 floor), confidence
tier, EV, slip selection, and slip-type.

### No double-shrink

Two pre-existing mechanisms already touched overconfidence; the stopgap is coordinated so exactly
one calibration applies when the flag is ON:

1. The **sigma calibration factor** (`generate_projections`, widens sigma) is forced to 1.0 — the
   direct probability shrink replaces it.
2. The **slip-engine shrink** (`build_slips.choose_slip_type` / `_ev_annotations` /
   `_best_shrunk_ev`, via `calibration_ratio`) returns an identity ratio `(1.0, True)` for any
   sport already shrunk at source, so legs are not shrunk a second time. Sports not calibrated at
   source (NBA) fall through to the existing uncalibrated path unchanged.

## 3. Feedback-loop fix (Component E — learning side)

The shrunk over-probability is persisted to Pick History's `Model Over Probability` column, which
the weekly `calibration.py` recompute reads back as `model_implied`. Left uncorrected, the loop
would measure the *already-shrunk* distribution, prescribe a milder shrink, and converge to a
biased fixed point `s* = √s_correct` — leaving ~35–40% of the correction unapplied while reporting
"calibrated."

Fix (additive columns only, the M2 design's "live-loop probability-logging fix"):

- `generate_projections` records the applied factor as `projection["prob_shrink_factor"]` (only
  when a shrink was actually applied, so flag-OFF projection JSON stays byte-identical).
- The runner persists it as an additive **`Prob Shrink Factor`** column on the Picks, Player
  Props/Props, and Pick History sheets (schema-migrated by `ensure_workbook`/`ensure_ws_columns`).
- `calibration.read_graded_outcomes_for_sport` **un-shrinks** each stored MOP back to the RAW
  model probability before computing `model_implied`:
  `raw = 0.5 + (stored - 0.5) / s` (legacy/blank/`s==1.0` rows are read unchanged).

Result: `model_implied` always reflects the model's true over-confidence, so the shrink factor
converges to the correct one-shot value instead of self-attenuating.

## 4. Safety & reversibility

- **Default OFF.** Flag off ⇒ projections byte-identical; the only schema change is one blank,
  behavior-neutral additive column. Verified by differential harnesses (0 mismatches) + 413-test
  regression (no new failures vs the documented baseline).
- **Reversible** by flipping the flag off.
- **Additive workbook schema only** — no dropped/renamed sheets or columns; no gate-logic change
  beyond the deliberate, flag-gated probability change.
- Offline/read-only over `data/` except the additive column; no new cron-path cost beyond a cheap
  `calibration.json` read.

## 5. Expected behavior when activated (for the operator)

- Fewer MLB picks clear Gate 2 (overconfident-borderline picks correctly drop out); MLB
  board-quality tiers (`Exceptional/Strong`) become harder to reach. This is the intended
  bleeding-stopper, not a regression.
- NBA unaffected (untrusted, no shrink) until it accumulates ≥ 30 graded MOP outcomes.
- Slips are selected and typed on honest probabilities, so Power stops looking artificially
  attractive.

## 6. Tests

`scripts/test_probability_calibration.py` (28 cases): shrink-factor derivation + edge cases,
source application (flag on/off), Gate-2 threshold crossing, slip-engine no-double-shrink
coordination, the Component E un-shrink, producer emission of the factor, persistence threading,
and an end-to-end round-trip (shrink → persist → reread → raw recovered).

## 7. Out of scope / next

This stopgap is replaced by M2's offline backtest harness + held-out-validated tuning. The raw
`Prob Shrink Factor` column also feeds the harness's production-realistic calibration check.
