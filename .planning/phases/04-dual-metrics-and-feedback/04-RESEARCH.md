# Phase 04: Dual Metrics and Feedback — Research

**Researched:** 2026-06-22
**Domain:** Python stdlib calibration math, openpyxl workbook aggregation, Telegram/Obsidian digest wiring
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Deliver the report to both Telegram (compact digest) and Obsidian (persistent note).
- **D-02:** Run via a standalone weekly runner task with its own cron entry (Monday morning). Wire into `run_task` `:7261`, `task_workbook_paths` `:7200`, `TASK_TIMEOUTS`. Cron entry lives in `~/.hermes` outside the repo — operator must add it; document in plan/summary.
- **D-03:** Each week×sport row shows slip ROI + prop hit-rate + WoW delta + ↑/→/↓ arrow. Optionally a rolling 3–4 week average to smooth samples. No auto "improving/stagnant" verdict line.
- **D-04:** Slip ROI / win-rate computed over staked slips only (`stake > 0`). Zero-stake slips shown as a separate informational count, never blended into money metrics.
- **D-05:** Slip ROI = Σ Net PnL / Σ Stake (dollar-weighted) over staked slips. Prop hit-rate = wins/(wins+losses), PUSH excluded — already computed by `refresh_prop_accuracy`.
- **D-06:** Sport attribution derived from slip's legs. No cross-sport slips exist today. Future mixed-sport slip → "MIXED" bucket (Claude's discretion to refine).
- **D-07:** Single tunable parameter = projection probability calibration via sigma path. factor >1.0 widens sigma (less confident); <1.0 narrows (more confident).
- **D-08:** Per-sport granularity: two factors — NBA and MLB. Not per-stat-type, not global.
- **D-09:** Auto-apply ON by default. No feature flag. Hard bounds are the safety net.
- **D-10:** Hard bounds: factor stays 1.0 until ≥30 graded outcomes (cumulative); moves at most ±0.05/week; clamped to [0.85, 1.20].
- **D-11:** Cumulative since inception (2026-06-08) measurement window.
- **D-12:** Recompute cadence = weekly. Whether report + calibration are one task or two is Claude's discretion.
- **D-13:** Feedback loop structurally prevented from touching graded verdicts or gate logic. Calibration written to `data/research/calibration.json`, read by `generate_projections.py` at projection time. Every update is logged (old→new factor, sample count, computed target). A test asserts the guarantee.

### Claude's Discretion

- Exact task name(s) and whether report + calibration recompute are one task or two (D-12).
- Module placement: new `metrics_report.py` / `calibration.py` vs functions in runner.
- Precise calibration formula: realized-hit-rate-vs-predicted-probability → sigma scaler.
- Exact Telegram digest wording and Obsidian markdown layout.
- "MIXED" sport bucket handling (D-06), test file names, whether report adds a new sheet (keep additive).

### Deferred Ideas (OUT OF SCOPE)

- Rolling-window calibration (deferred from D-11).
- Per-stat-type calibration granularity (deferred from D-08).
- Auto-computed "improving/stagnant" verdict line (deferred from D-03).
- Additional feedback knobs (hit-rate confidence-adjustment thresholds, confidence→stake mapping).
- Daily/append report cadence (deferred from D-02).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| METRICS-01 | Report surfaces slip ROI and prop hit-rate over time (by week and sport) so "improving vs stagnant" is answerable from data. | `Prop Accuracy` sheet already aggregates ISO-week × sport. Slip ROI requires reading `Slip History` from master_pnl.xlsx. Sport attribution is feasible via per-sport workbooks (proven below). |
| METRICS-02 | Realized slip/prop outcomes feed back into projection/gate tuning via a bounded feedback loop. | `Pick History` stores `Model Over Probability` (col 20, confirmed present for dates 2026-06-09 onward). `estimate_sigma:277` / `model_over_probability:289` in `generate_projections.py` are the confirmed injection points. |
| METRICS-03 | The feedback loop cannot retroactively change graded verdicts and preserves integrity of no-bet gates. | Structural isolation via `calibration.json` + a test asserting NO Results change and NO gate output change are the recommended approach (see Validation Architecture). |
</phase_requirements>

---

## Summary

Phase 4 delivers two cooperating capabilities on top of the P1–P3 data infrastructure: a weekly dual-metrics report (slip ROI + prop hit-rate by week × sport, pushed to Telegram + Obsidian), and a bounded probability-calibration feedback loop that updates a per-sport sigma scaler in `data/research/calibration.json`, read by `generate_projections.py` at projection time.

The critical feasibility question — "is `Model Over Probability` recoverable for already-graded outcomes?" — is CONFIRMED. Column 20 of `Pick History` in `master_pnl.xlsx` is `Model Over Probability`, and it is populated for all dates from 2026-06-09 onward (42 terminal PROP rows with MOP out of 222 total terminal rows). The sole gap is 2026-06-08 (inception day), where projection generation did not write MOP to workbook rows; these rows count toward outcome totals but contribute 0.0 weight in the calibration formula (their MOP is missing, so they are excluded from the MOP-weighted calculation, only their binary result is used for the raw hit-rate count).

The sport attribution for Slip History slip ROI is also confirmed feasible via the per-sport per-day workbooks (which `grade_slips` already routes by sport), without requiring a new `Sport` column in the master Slip History. The `Legs` free-text column cannot reliably be parsed for sport — instead the report reads per-sport workbook Slip History sheets.

**Primary recommendation:** Implement calibration as a single new `calibration.py` module + a `weekly_metrics` task in the runner, using the smoothed-ratio formula with a ±0.05 step clamp and [0.85, 1.20] bound. Keep one task (D-12 resolution: one task, two logical phases — first report, then calibration update).

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Slip ROI aggregation | Script (calibration.py) | master_pnl.xlsx read | Report reads `Slip History` per-sport workbooks for sport-bucketed ROI |
| Prop hit-rate aggregation | Script (metrics_report.py) | `Prop Accuracy` sheet (already done by `refresh_prop_accuracy`) | Direct read from existing `Prop Accuracy` sheet rows — no new math |
| WoW delta + arrow computation | Script (metrics_report.py) | — | Pure in-memory sort by ISO-week key, compute delta |
| Telegram digest | Script (sports_system_runner.py `send_telegram`) | — | Reuse existing `send_telegram` function |
| Obsidian note | `obsidian_create_weekly_recap:1034` scaffold | `obsidian_sync` trigger | Fill the blank scaffold, reuse `obsidian_sync` pattern |
| Calibration formula + update | Script (calibration.py) | `data/research/calibration.json` | Reads Pick History, writes JSON only; never touches Results or gate code |
| Sigma factor injection | `generate_projections.py` `estimate_sigma:277` | `calibration.json` read | Multiply `sigma_eff = sigma * factor` at the point sigma is used |
| Task wiring | `run_task:7261` + `task_workbook_paths:7200` + `TASK_TIMEOUTS` | — | Mirrors `grade_slips` / `rebuild_bankroll` pattern |
| Integrity test | `test_weekly_metrics.py` | — | Runs calibration loop on synthetic data, asserts no Results change, no gate change |

---

## Standard Stack

### Core (all stdlib or already-imported)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `statistics` | stdlib | `mean()`, `stdev()` — calibration formula smoothing | Already imported in `generate_projections.py:16` |
| `math` | stdlib | `math.erf`, `math.sqrt` — `normal_cdf` used in calibration confidence | Already in `generate_projections.py:12` |
| `json` | stdlib | Read/write `calibration.json` | Used everywhere in this codebase |
| `openpyxl` (via `safe_load_workbook`) | 3.1.5 | Read `master_pnl.xlsx` Slip History + Pick History + Prop Accuracy sheets | Already the system's only persistence layer |
| `pathlib.Path` | stdlib | `DATA / "research" / "calibration.json"` | Already the system path convention |
| `datetime.date.isocalendar()` | stdlib | ISO-week key: `f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"` | Already used in `refresh_prop_accuracy:5332` |
| `collections.Counter` | stdlib | Leg-sport counting for attribution | Already imported in `grade_slips.py:605` |

**No new third-party packages are needed or permitted.**
[VERIFIED: codebase grep]

### Supporting
| Module | Role |
|--------|------|
| `workbook_io.safe_load_workbook` | Read-only workbook access |
| `workbook_io.save_workbook_atomic` | Only needed if adding a new workbook sheet (optional) |
| `slip_payouts.SLIP_HISTORY_HEADERS` | Column index lookup for Stake Units, Net PnL, Slip Result, Needs Payout Reconciliation |

---

## Package Legitimacy Audit

No new packages to install. This phase is stdlib-only.

---

## Research Focus Findings

### 1. Calibration Formula (The Open Question — RECOMMENDED)

**Context:** Given per-sport realized hit-rate (empirical) vs model-implied (predicted) probability from `Model Over Probability` in Pick History, find a principled, low-volume-robust mapping to a sigma scaler where factor >1.0 = model overconfident (widen sigma) and <1.0 = model underconfident (narrow sigma).

#### Options surveyed:

**Option A: Smoothed confidence ratio (RECOMMENDED)**

This is the formula hinted in CONTEXT.md "Specific Ideas" and is the most natural fit for the constraints.

```
# Per sport, over graded PROP outcomes with non-null Model Over Probability:
empirical_hit_rate = wins / (wins + losses)  # PUSH excluded — matches D-05 / refresh_prop_accuracy
model_implied = mean(mop_values_for_wins_and_losses)  # mean of Model Over Probability for W+L rows

# Calibration ratio: >1.0 when model is overconfident (model > empirical)
raw_ratio = model_implied / empirical_hit_rate  # safe_division below

# Shrink toward 1.0 proportionally to sample size (Bayesian-style damping)
# When n=30 (the gate), shrink_weight=0.0 (full effect); at n=30 exact no shrinkage if desired.
# Simple version: no explicit shrink at the gate boundary, but the ±0.05 step clamp absorbs noise.
target = raw_ratio

# Apply step limit and clamp (D-10)
delta = target - prev_factor
delta = max(-0.05, min(0.05, delta))
new_factor = prev_factor + delta
new_factor = max(0.85, min(1.20, new_factor))
```

**Monotonic behavior:** When model_implied > empirical (overconfident), raw_ratio > 1.0 → factor increases → sigma widens → future probabilities pulled toward 0.5 (less confident). Correct direction.

**Pitfalls and handling:**

| Pitfall | Handling |
|---------|----------|
| empirical_hit_rate = 0.0 (all losses) | `raw_ratio` = inf → cap target at 1.20 (the clamp upper bound), or equivalently `target = min(raw_ratio, 2.0)` then step-clamp naturally handles |
| empirical_hit_rate = 1.0 (all wins) | `raw_ratio` = model_implied (e.g. 0.7) < 1.0 → narrows sigma. Correct. |
| model_implied = 0 (all MOP missing) | Cannot compute — only rows with non-null MOP are included in the average. If zero valid MOP rows, fall back to factor = 1.0 (neutral, same as <30 gate). |
| PUSH handling | PUSH rows excluded from wins+losses denominator (per D-05 / `refresh_prop_accuracy` precedent). |
| n < 30 gate | factor = 1.0 exactly, no computation (D-10/D-11). |
| Division by zero | `empirical_hit_rate = wins / max(1, wins + losses)` — safe. |

**Low-volume robustness at n≈30:** The ±0.05 step clamp is the primary robustness mechanism. Even if raw_ratio is noisy at n=30, the factor moves at most 0.05 per week. An early outlier cannot cause a runaway shift. This is superior to Platt scaling (requires training/fitting infrastructure) and isotonic regression (requires ordered bins, not meaningful at n=30).

**Why NOT Brier Score / Platt / Isotonic:**
- **Brier score calibration** (expected calibration error) requires enough samples to form probability bins — not meaningful at n≈30 total outcomes.
- **Platt scaling** (logistic regression on model scores) requires fitting a model — needs `scikit-learn` or custom logistic implementation. Not stdlib-expressible cleanly, disproportionate for one scalar per sport.
- **Isotonic regression** requires enough calibration bins with ordering guarantees — useless at 30 total outcomes spread across all stat types.
- **Bayesian shrinkage** (explicit prior): `target = (n * raw_ratio + k * 1.0) / (n + k)` where k=30 is a conceptually clean option. At n=30 exactly this gives `target = (30 * raw_ratio + 30) / 60 = (raw_ratio + 1) / 2`, which is 50% shrinkage toward neutral. This is MORE conservative than the pure ratio. **Include as a variant** if the operator wants extra protection against early-data noise. The planner may offer both; operator chooses or defaults to pure ratio + step clamp.

**Exact formula for planner to encode (stdlib, zero new deps):**

```python
def compute_calibration_target(
    wins: int,
    losses: int,
    mop_values: list[float],  # Model Over Probability for W+L rows only
    prev_factor: float,
    n_gate: int = 30,
    max_step: float = 0.05,
    clamp_lo: float = 0.85,
    clamp_hi: float = 1.20,
) -> tuple[float, dict]:
    """
    Returns (new_factor, audit_dict).
    audit_dict contains: empirical_hit_rate, model_implied, raw_ratio, target,
                         delta, new_factor, n_outcomes, n_with_mop, reason.
    """
    n_outcomes = wins + losses  # PUSH excluded
    n_with_mop = len(mop_values)

    if n_outcomes < n_gate:
        return prev_factor, {"reason": f"gate not met: n={n_outcomes} < {n_gate}", "new_factor": prev_factor}

    empirical = wins / max(1, wins + losses)

    if n_with_mop == 0:
        # No MOP data available — cannot compute ratio, stay neutral
        return prev_factor, {"reason": "no MOP data available", "new_factor": prev_factor}

    model_implied = sum(mop_values) / len(mop_values)  # arithmetic mean; statistics.mean() equivalent

    if empirical <= 0.0:
        raw_ratio = clamp_hi  # model overconfident maximally
    else:
        raw_ratio = model_implied / empirical

    # Clamp raw_ratio before step (avoid extreme targets from tiny samples)
    target = max(clamp_lo, min(clamp_hi, raw_ratio))

    delta = target - prev_factor
    delta = max(-max_step, min(max_step, delta))
    new_factor = prev_factor + delta
    new_factor = max(clamp_lo, min(clamp_hi, new_factor))

    return new_factor, {
        "reason": "computed",
        "empirical_hit_rate": round(empirical, 4),
        "model_implied": round(model_implied, 4),
        "raw_ratio": round(raw_ratio, 4),
        "target": round(target, 4),
        "delta": round(delta, 5),
        "new_factor": round(new_factor, 4),
        "n_outcomes": n_outcomes,
        "n_with_mop": n_with_mop,
        "prev_factor": prev_factor,
    }
```

[ASSUMED] — The formula above is designed by research, not derived from official calibration literature for this exact domain. The ±0.05 step clamp is the operator's explicit bound (D-10); the smoothed-ratio approach is research-recommended.

---

### 2. Model-Implied Probability Recoverability (METRICS-02 Feasibility)

**VERIFIED: CONFIRMED — with one known gap.**

`Model Over Probability` is column 20 (0-indexed header index 19) in `Pick History` in `master_pnl.xlsx`. [VERIFIED: direct workbook inspection]

**Coverage audit (as of 2026-06-22):**

| Sport | Terminal PROP rows | With MOP | Without MOP | Dates |
|-------|-------------------|----------|-------------|-------|
| MLB | 76 total | 41 | 35 | MOP missing for 2026-06-08 only |
| NBA | 81 total | 1 | 80 | MOP missing for most rows (see below) |

**Root cause of NBA gap:**
- The lone NBA PROP row with MOP (`Date=2026-06-10, MOP=0.7412`) is the only one. All other 80 NBA terminal rows have `MOP=None`.
- These NBA rows are from 2026-06-08 through the season end. The NBA season effectively ended by June 2026 (NBA Finals concluded); most NBA outcomes in Pick History predate or coincide with the `generate_projections.py` MOP-write infrastructure being established.
- **This means the NBA sport will NOT reach the ≥30-outcome gate with MOP data at launch.** The gate stays at 1.0 for NBA until forward picks populate MOP. This is correct behavior — the gate protects against acting on incomplete data.

**MLB position:** 41 MLB PROP rows have MOP. The gate is ≥30. MLB ALREADY has enough MOP-backed outcomes for calibration to engage. The calibration loop will produce a non-neutral factor for MLB on first run if 41 ≥ 30 (it is). [VERIFIED: confirmed by direct count]

**Implication for planner:** The calibration loop must count ONLY rows where BOTH `Result` is terminal (WIN/LOSS) AND `Model Over Probability` is non-null. The gate check (`n < 30`) must be applied to the count of rows with MOP (not total graded rows), or the planner must document that MOP-absent rows count toward outcome totals but not toward the MOP-weighted mean. Recommendation: apply gate to `n_with_mop` (rows that have both a terminal result AND a non-null MOP), not to all graded outcomes. This is stricter but cleaner.

**Where to read MOP for calibration (code path):**
```python
# In calibration.py — read master_pnl Pick History
wb, _ = master_pnl_workbook()   # already defined in runner
ph = wb["Pick History"]
# headers from RESULT_HEADERS (runner constant)
# "Model Over Probability" is at RESULT_HEADERS index 12 (0-based) → col 13 (1-based) in the schema
# but actual column may differ after additive migrations — always look up by header name
```
[VERIFIED: `RESULT_HEADERS` at line 292–298 in runner; `Model Over Probability` at index 12 (0-based) confirmed by workbook inspection as col 20 1-based]

---

### 3. Sport Attribution for Slip ROI

**Issue:** The `Slip History` sheet in `master_pnl.xlsx` has NO `Sport` column (confirmed). The `Legs` column is free-text (e.g., `"Karl-Anthony Towns points rebounds assists OVER 24.5; ..."`) — no sport prefix, no parseable marker per leg.

**Confirmed approaches:**

**Approach A (RECOMMENDED): Read per-sport workbooks (already routed by `grade_slips`)**

`grade_slips.py` already routes slip records by predominant leg sport into per-sport workbooks (`data/nba/nba_YYYY-MM-DD.xlsx`, `data/mlb/mlb_YYYY-MM-DD.xlsx`) via the `slips_by_sport` dict at line 600–613. The per-sport `Slip History` sheets therefore contain only single-sport slips. The report aggregates Slip History by iterating each date's per-sport workbook rather than the master:

```python
# For each sport in ["nba", "mlb"]:
#   For each date >= inception:
#     wb = safe_load_workbook(workbook_path(sport, date))
#     read Slip History rows from that workbook (filtered rows are already sport-bucketed)
```

This avoids any string parsing, requires no schema change, and correctly handles mixed-sport slips (they land in master only, not in per-sport workbooks — already excluded per `master_only_slips`).

**Limitation:** This requires iterating all dated per-sport workbooks for the aggregation window. With ~15 dates and 2 sports that is 30 workbook opens — fast enough (each is a small file). Cache workbooks by date/sport tuple if needed.

**Approach B (alternative): Add a `Sport` column to `Slip History` via additive `ensure_workbook` migration**

Requires a schema change: new `Sport` column populated by `grade_slips`. Additive, safe per codebase conventions, but changes `slip_history_row()` in `slip_payouts.py` (adds a parameter) which cascades to `write_slip_history_rows()` in `grade_slips.py`. More invasive than Approach A for a new phase. [ASSUMED] — defer unless Approach A proves too slow.

**RECOMMENDATION: Approach A.** Zero schema change, zero `slip_payouts.py` change, sport is already structurally separated by `grade_slips`.

---

### 4. Task Wiring + Cron (D-02 / D-12)

**One task vs two (D-12 — Claude's discretion):**

RECOMMENDATION: **one task** named `weekly_metrics`. Rationale:
- The report and calibration update share the same data reads (Pick History MOP + Prop Accuracy + Slip History). Running them in one task avoids reading the same workbook twice.
- Both are read-heavy (master_pnl.xlsx) with one small JSON write (calibration.json). The operation is fast (no ESPN API calls, no subprocess). Estimated wall-clock: <30 seconds, well within 660s.
- A single Monday-morning cron entry is simpler to wire and audit.
- If the operator ever wants to run calibration without the report, they can split later — this is additive.

**Integration points (all LOCKED in CONTEXT.md, confirmed by code inspection):**

| Point | Location | Change |
|-------|----------|--------|
| `TASK_TIMEOUTS` | `sports_system_runner.py:120` | Add `"weekly_metrics": 660` |
| `task_workbook_paths` | `sports_system_runner.py:7192` | Add `if task == "weekly_metrics": return [PNL_DIR / "master_pnl.xlsx"]` — read-only, but lock acquires cooperatively |
| `run_task` mapping | `sports_system_runner.py:7261` | Add `"weekly_metrics": lambda: weekly_metrics_task()` |
| cron entry | `~/.hermes` — outside repo | Operator must add; note in plan/summary per D-02 |

**Pattern to mirror** (from `grade_slips` and `rebuild_bankroll` at lines 7206–7213, 7276–7279):
```python
# In TASK_TIMEOUTS dict:
"weekly_metrics": 660,

# In task_workbook_paths:
if task == "weekly_metrics":
    return [PNL_DIR / "master_pnl.xlsx"]

# In run_task mapping:
"weekly_metrics": lambda: weekly_metrics_task(),
```

**Lock behavior:** `task_workbook_locks` acquires cooperative file locks on the listed paths (sorted by path string, same as other tasks). Since `weekly_metrics` only reads master_pnl (and writes calibration.json, not a workbook), the lock prevents races with `grade_slips` and `check_results` — correct.

**Idempotency:** Running `weekly_metrics` twice in a row must be safe. The report re-computes from current data (idempotent). The calibration update is idempotent by design — it recomputes the target from the same cumulative data and writes the same factor (the ±0.05 step clamp means two runs produce the same factor if data didn't change between runs).

**660s budget:** The task reads 2 workbooks + iterates ~30 small per-sport workbooks + writes 1 small JSON + makes 1 Telegram API call + 1 Obsidian sync subprocess (60s timeout). Total wall-clock estimate: 15–45 seconds. Well under budget.

---

### 5. ISO-Week × Sport Aggregation + Delivery

**Prop side (METRICS-01 — already solved):**

`refresh_prop_accuracy:5293` already produces the `Prop Accuracy` sheet with columns `["Week", "Sport", "Total Props", "Wins", "Losses", "Pushes", "Hit Rate", "Updated At"]` (PROP_ACCURACY_HEADERS, line 299). The report reads this sheet directly — no new prop math. [VERIFIED: workbook inspection confirms 4 rows of data covering 2026-W24 (NBA+MLB), 2026-W25 (MLB), 2026-W26 (MLB).]

**Slip ROI side (METRICS-01 — requires new aggregation):**

Using Approach A (per-sport workbooks):
```python
# Pseudo-code for slip ROI aggregation by ISO-week × sport
from datetime import date as _date_cls

def aggregate_slip_roi_by_week_sport(inception: str = "2026-06-08") -> dict[tuple[str, str], dict]:
    """Returns {(iso_week, sport): {staked_count, zero_stake_count, total_stake, total_pnl, wins, losses, pushes}}"""
    agg = {}
    for sport in ("nba", "mlb"):
        for wb_path in sorted(sport_dated_workbooks(sport, inception)):
            wb = safe_load_workbook(wb_path)
            if "Slip History" not in wb.sheetnames:
                continue
            sh = wb["Slip History"]
            for row_vals in sh.iter_rows(min_row=2, values_only=True):
                date_val = str(row_vals[SHH.index("Date")] or "")[:10]
                stake = to_float(row_vals[SHH.index("Stake Units")]) or 0.0
                net_pnl = to_float(row_vals[SHH.index("Net PnL")]) or 0.0
                result = str(row_vals[SHH.index("Slip Result")] or "").upper()
                recon = row_vals[SHH.index("Needs Payout Reconciliation")]
                if recon is True or str(recon or "").upper() == "TRUE":
                    continue  # exclude unresolvable slips
                try:
                    d = _date_cls.fromisoformat(date_val)
                    iso_week = f"{d.isocalendar().year}-W{d.isocalendar().week:02d}"
                except Exception:
                    continue
                key = (iso_week, sport.upper())
                rec = agg.setdefault(key, {"staked": 0, "zero_stake": 0, "total_stake": 0.0, "total_pnl": 0.0, "wins": 0, "losses": 0, "pushes": 0})
                if stake > 0:
                    rec["staked"] += 1
                    rec["total_stake"] += stake
                    rec["total_pnl"] += net_pnl
                    if result == "WIN":
                        rec["wins"] += 1
                    elif result in ("LOSS", "GRADED"):
                        rec["losses"] += 1  # note: old "GRADED" rows — handle both
                    elif result == "PUSH":
                        rec["pushes"] += 1
                else:
                    rec["zero_stake"] += 1
    return agg
```

**WoW delta + arrow rendering:**
```python
ARROW = {True: "↑", False: "↓", None: "→"}
def wow_arrow(current: float | None, prev: float | None, threshold: float = 0.005) -> str:
    if current is None or prev is None:
        return "→"
    diff = current - prev
    if diff > threshold:
        return "↑"
    if diff < -threshold:
        return "↓"
    return "→"
```

**Obsidian scaffold (`obsidian_create_weekly_recap:1034`):**

The existing scaffold is a blank template (Overview + By Sport + By Tier + By Pick Type + Notes sections). The P4 fill replaces:
- `## Overview` table: add "Slip ROI This Week" and "Prop Hit-Rate This Week" rows
- `## By Sport` table: fill NBA/MLB rows with ROI + hit-rate + WoW arrows
- `## Adjustments for Next Week`: add calibration factor change note (old→new factor)

The scaffold calls `obsidian_sync({"trigger": "check_results", "sport": "NBA", "date": date, "data": {"weekly_recap_date": date, "weekly_recap_markdown": markdown, ...}})` — the report fills `markdown` and passes it through the same trigger pattern, or calls `obsidian_create_weekly_recap` with the filled `summary` dict. [VERIFIED: `obsidian_create_weekly_recap:1034–1098`]

**Telegram digest format (D-03 compact):**
```
📊 Weekly Metrics — 2026-W26
NBA: Slip ROI −1.2% ↓ | Hits 47% →
MLB: Slip ROI +8.3% ↑ | Hits 52% ↑
Calibration: MLB 0.97 → 0.97 (n=41, no change; NBA 1.00 gate not met)
```
(Arrow based on WoW delta; no verdict line per D-03.)

---

### 6. Injection Point in `generate_projections.py`

**Confirmed injection point:** `estimate_sigma:277` returns `(sigma, source)`. The caller is `build_projection:393`, which then calls `model_over_probability(projection, pp_line, sigma)`.

The injection is:
```python
# In generate_projections.py — new function at module top:
def load_calibration_factor(sport: str) -> float:
    """Read per-sport sigma scaler from calibration.json; default 1.0 if absent."""
    path = DATA / "research" / "calibration.json"
    try:
        if path.exists():
            cfg = json.loads(path.read_text())
            return float(cfg.get("factors", {}).get(sport.upper(), 1.0))
    except Exception:
        pass
    return 1.0

# In build_projection (around line 393, after estimate_sigma call):
sigma, sigma_source = estimate_sigma(stat, stat_name)
cal_factor = load_calibration_factor(sport)
if cal_factor != 1.0:
    sigma = sigma * cal_factor
    sigma_source = f"{sigma_source} × cal_factor={cal_factor}"
over_prob = round(model_over_probability(projection, pp_line, sigma), 4)
```

**Why this exact point:** Injecting AFTER `estimate_sigma` and BEFORE `model_over_probability` means:
- The raw sigma from sample data is unchanged
- The factor is applied purely multiplicatively (factor >1 → wider sigma → lower over_probability → picks pulled toward 0.5)
- Gate 2 (`probability ≥ 0.52`) sees the adjusted probability — correct, as the calibration should affect pick selection
- Gate logic thresholds and `evaluate_no_bet_gates` code are byte-for-byte unchanged

**calibration.json schema:**
```json
{
  "version": 1,
  "updated_at": "2026-06-23T00:00:00+00:00",
  "inception_date": "2026-06-08",
  "factors": {
    "NBA": 1.0,
    "MLB": 0.97
  },
  "audit": [
    {
      "updated_at": "...",
      "sport": "MLB",
      "prev_factor": 1.0,
      "new_factor": 0.97,
      "n_outcomes": 41,
      "n_with_mop": 41,
      "empirical_hit_rate": 0.532,
      "model_implied": 0.781,
      "raw_ratio": 0.968,
      "delta": -0.03,
      "reason": "computed"
    }
  ]
}
```

The `audit` array is the observable log (D-13 requirement). It grows on each weekly run — keeping the last N entries is sufficient (e.g., last 52 = 1 year).

---

## Architecture Patterns

### System Architecture Diagram

```
master_pnl.xlsx ──────► calibration.py ──► calibration.json ──► generate_projections.py
 (Pick History:MOP)      compute_target()    {factors:{NBA,MLB}}    estimate_sigma × factor
 (Prop Accuracy)         update weekly                               model_over_probability
 (Slip History)         ─────────────────────────────────────────►
                              │
                              ▼
                        weekly_metrics_task()
                              │
                    ┌─────────┴──────────┐
                    ▼                    ▼
             Telegram digest        Obsidian note
             (send_telegram)   (obsidian_create_weekly_recap)
```

Per-sport workbooks (`data/nba/nba_*.xlsx`, `data/mlb/mlb_*.xlsx`) feed slip ROI aggregation via the existing `grade_slips` routing (no schema change).

### Recommended Project Structure
```
scripts/
├── calibration.py           # NEW: compute_calibration_target, load_calibration_factor,
│                            #       update_calibration_json, read_graded_outcomes_for_sport
├── metrics_report.py        # NEW: aggregate_slip_roi_by_week_sport, build_weekly_report,
│                            #       format_telegram_digest, fill_obsidian_recap
├── test_weekly_metrics.py   # NEW: METRICS-03 integrity test + D-10 bounds test + METRICS-01 ROI test
├── generate_projections.py  # MODIFIED: add load_calibration_factor(), inject into build_projection
├── sports_system_runner.py  # MODIFIED: TASK_TIMEOUTS, task_workbook_paths, run_task mapping
data/
├── research/
│   └── calibration.json     # NEW: created on first run; default {"factors":{"NBA":1.0,"MLB":1.0},"audit":[]}
```

### Pattern 1: Calibration JSON Read (fail-safe)
```python
# Source: design — matches env_value() fail-safe pattern in sports_system_runner.py:216
def load_calibration_factor(sport: str) -> float:
    path = DATA / "research" / "calibration.json"
    try:
        if path.exists():
            cfg = json.loads(path.read_text())
            return float(cfg.get("factors", {}).get(sport.upper(), 1.0))
    except Exception:
        pass
    return 1.0  # default neutral — never crashes projection generation
```

### Pattern 2: Calibration JSON Write (atomic, with audit log)
```python
# Source: design — mirrors save_workbook_atomic / atomic-rename pattern
import os, tempfile

def write_calibration_json(path: Path, factors: dict[str, float], audit_entry: dict, max_audit: int = 52) -> None:
    existing = {}
    try:
        if path.exists():
            existing = json.loads(path.read_text())
    except Exception:
        pass
    audit = list(existing.get("audit", []))
    audit.append(audit_entry)
    audit = audit[-max_audit:]  # keep last 52 entries (1 year)
    doc = {
        "version": 1,
        "updated_at": now_iso(),
        "inception_date": "2026-06-08",
        "factors": factors,
        "audit": audit,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    os.replace(tmp, path)  # atomic rename, same as save_workbook_atomic pattern
```

### Pattern 3: Task wiring (mirrors grade_slips)
```python
# sports_system_runner.py additions:

# In TASK_TIMEOUTS dict (around line 137):
"weekly_metrics": 660,

# In task_workbook_paths (around line 7213):
if task == "weekly_metrics":
    return [PNL_DIR / "master_pnl.xlsx"]

# In run_task mapping (around line 7280):
"weekly_metrics": lambda: weekly_metrics_task(),
```

### Anti-Patterns to Avoid

- **Anti-pattern: Parsing the `Legs` free-text column for sport.** The Legs column text (`"Karl-Anthony Towns points rebounds assists OVER 24.5; ..."`) has no sport prefix; parsing it would require player-name-to-sport lookups or fragile heuristics. Use per-sport workbooks instead (Approach A above).
- **Anti-pattern: Writing calibration factors directly into workbook sheets.** The factor must live in `data/research/calibration.json` — not in any workbook column — so it is observable, reversible, and structurally isolated from graded data (D-13).
- **Anti-pattern: Reading calibration factor at import time.** Read at call time inside `build_projection()` or in a `load_calibration_factor()` helper called from there. Import-time reads would cache a stale value across the subprocess lifetime.
- **Anti-pattern: Modifying `evaluate_no_bet_gates` or any gate threshold.** The sigma factor injection upstream of the gate gauntlet is the ONLY correct coupling point. Any change inside `evaluate_no_bet_gates` violates D-13 / METRICS-03.
- **Anti-pattern: Including VOID rows in calibration outcomes.** VOID rows should be excluded from wins+losses count (same as PUSH). Only WIN and LOSS terminal results are meaningful for the calibration hit-rate computation.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| ISO-week computation | Custom week-number math | `date.isocalendar()` | Already used in `refresh_prop_accuracy:5332`; correct ISO-8601 week |
| Workbook read safety | Direct `load_workbook()` | `workbook_io.safe_load_workbook` | Retry-on-stale, cooperative locks, backup-on-save already implemented |
| Telegram sending | Custom HTTP requests | `send_telegram:428` | Circuit-breaker, retry, credential lookup already implemented |
| Obsidian note delivery | Custom file write | `obsidian_create_weekly_recap:1034` + `obsidian_sync` | Scaffold + sync trigger already implemented |
| Atomic JSON write | Direct `path.write_text` | Write to `.json.tmp` then `os.replace` | Prevents partial writes from crashing calibration reads |
| Workbook column lookup | Hardcoded column offsets | Header-name lookup `{h.value: c for c in range(...)}` | Columns shift after additive migrations; always look up by name |

---

## Common Pitfalls

### Pitfall 1: Using `n_outcomes` (all graded) instead of `n_with_mop` for the ≥30 gate
**What goes wrong:** If the gate counts all terminal WIN/LOSS results regardless of whether MOP is available, the calibration activates based on n=222 total rows but only 42 have usable MOP. The mean model_implied is computed over 42 points but the gate thinks it has 222 — misleadingly confident.
**How to avoid:** Gate on `len(mop_values)` — the count of rows with both a terminal result (WIN/LOSS) and a non-null `Model Over Probability`. This is the correct population for the calibration ratio.

### Pitfall 2: NBA calibration activating with 1 MOP row
**What goes wrong:** NBA has 1 MOP row (Date=2026-06-10, MOP=0.7412). If the gate is set to `n_with_mop >= 30`, NBA factor stays 1.0 (correct). If someone sets the gate lower, NBA calibration runs on 1 data point — meaningless.
**How to avoid:** The ≥30 gate on `n_with_mop` is non-negotiable for NBA until the next season produces MOP-backed outcomes.

### Pitfall 3: `Slip Result` = "GRADED" in legacy rows
**What goes wrong:** Early Slip History rows (2026-06-08 backfill) may have `Slip Result = "GRADED"` rather than "WIN"/"LOSS"/"PUSH". Counting wins from only "WIN" rows would miss these.
**How to avoid:** Check the actual values: from workbook inspection, `Slip Result` for 2026-06-08 rows is `"GRADED"` (not WIN/LOSS/PUSH). The report's ROI calculation must handle this — either treat "GRADED" as an unknown result (exclude from win/loss rate) or check if `Net PnL > 0` as a proxy. Better: check `Needs Payout Reconciliation` first (exclude flagged rows), then use `Net PnL` for ROI regardless of the string result label.
**Warning signs:** ROI computation showing 0 slips with wins for some dates.

### Pitfall 4: Calibration `audit` array growing unbounded
**What goes wrong:** Each weekly run appends one entry per sport. Over years this grows large and slows JSON reads.
**How to avoid:** Trim to last 52 entries (1 year) on each write. `audit = audit[-52:]` before writing.

### Pitfall 5: `obsidian_create_weekly_recap` creates the file only if it doesn't exist
**What goes wrong:** `obsidian_create_weekly_recap:1038` guards with `if path.exists(): return path` — a second run of `weekly_metrics` for the same date won't overwrite the Obsidian note.
**How to avoid:** The report should either pass the filled content in `summary` before the guard executes, or use a `force=True` mode. Looking at the function signature: it accepts `summary: dict[str, Any]` — the plan should fill `summary` with the computed metrics data and call the function such that `markdown` is constructed from `summary`. Since the function currently ignores `summary` in its implementation (the scaffold ignores it), the planner needs to either: (a) modify `obsidian_create_weekly_recap` to accept and render the summary data, or (b) call `obsidian_sync` directly with the filled markdown, bypassing the `if path.exists()` guard. Option (b) is simpler and avoids touching the scaffold function.

### Pitfall 6: Per-sport workbook iteration for Slip ROI — 30 file opens
**What goes wrong:** Iterating `data/nba/nba_*.xlsx` (15 files) + `data/mlb/mlb_*.xlsx` (15 files) opens 30 workbooks. Each open acquires no lock (read-only). But if a daily task is running simultaneously, a half-written workbook could corrupt the read.
**How to avoid:** Use `safe_load_workbook` which has retry-on-stale logic. Alternatively, read only from `master_pnl.xlsx` Slip History (which has all slips) and derive sport from the `Slip ID` — the Slip ID is `"2026-06-08:correlated_upside:<hash>"` which doesn't contain sport. Confirmed: per-sport workbook Approach A is the right path.

---

## Runtime State Inventory

Not a rename/refactor/migration phase — this is additive new capability.

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | `data/research/calibration.json` — does not yet exist | Create on first `weekly_metrics` run with `{"factors":{"NBA":1.0,"MLB":1.0},"audit":[]}` |
| Live service config | None — cron entry in `~/.hermes` must be added by operator | Document in plan/summary per D-02 |
| OS-registered state | None | None |
| Secrets/env vars | None new — uses existing TELEGRAM_BOT_TOKEN, TELEGRAM_HOME_CHANNEL | None |
| Build artifacts | None | None |

---

## Validation Architecture

> `nyquist_validation` is enabled (config.json `workflow.nyquist_validation: true`).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 |
| Config file | None — uses pytest auto-discovery from `scripts/` |
| Quick run command | `cd scripts && python3 -m pytest test_weekly_metrics.py -x` |
| Full suite command | `cd scripts && python3 -m pytest -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| METRICS-01 | Report aggregates slip ROI by week×sport from per-sport workbooks, staked slips only (D-04/D-05) | unit | `python3 -m pytest test_weekly_metrics.py::TestSlipRoiAggregation -x` | ❌ Wave 0 |
| METRICS-01 | Report aggregates prop hit-rate from Prop Accuracy sheet (reuses `refresh_prop_accuracy` output) | unit | `python3 -m pytest test_weekly_metrics.py::TestPropHitRateAggregation -x` | ❌ Wave 0 |
| METRICS-01 | WoW delta + ↑/→/↓ arrow renders correctly for increasing, flat, decreasing ROI | unit | `python3 -m pytest test_weekly_metrics.py::TestWowArrow -x` | ❌ Wave 0 |
| METRICS-02 | Calibration formula: with ≥30 MOP-backed outcomes, factor moves toward target but ≤±0.05/step and stays in [0.85, 1.20] | unit | `python3 -m pytest test_weekly_metrics.py::TestCalibrationFormula -x` | ❌ Wave 0 |
| METRICS-02 | Calibration formula: with <30 MOP-backed outcomes, factor stays exactly 1.0 | unit | `python3 -m pytest test_weekly_metrics.py::TestCalibrationGateNotMet -x` | ❌ Wave 0 |
| METRICS-02 | `generate_projections.py` reads `calibration.json` factor and applies it as `sigma * factor` | unit | `python3 -m pytest test_weekly_metrics.py::TestSigmaInjection -x` | ❌ Wave 0 |
| METRICS-03 | Running the calibration loop changes NO existing `Result` value (WIN/LOSS/PUSH/VOID) in Pick History or Results sheets | unit | `python3 -m pytest test_weekly_metrics.py::TestIntegrityNoVerdictChange -x` | ❌ Wave 0 |
| METRICS-03 | Running the calibration loop leaves `evaluate_no_bet_gates` output unchanged for a fixed pick fixture | unit | `python3 -m pytest test_weekly_metrics.py::TestIntegrityGateOutput -x` | ❌ Wave 0 |
| D-10 bounds | Factor clamped to [0.85, 1.20] and moves ≤±0.05 even with extreme inputs (all wins or all losses) | unit | `python3 -m pytest test_weekly_metrics.py::TestCalibrationBounds -x` | ❌ Wave 0 |

### Detailed Test Designs for METRICS-03 (integrity guarantee)

**Design A: Snapshot/hash before+after (recommended)**

```python
def test_calibration_loop_does_not_change_verdicts():
    """METRICS-03 criterion #3: run the calibration loop on a live-like fixture,
    assert no Pick History Result values change."""
    wb = _make_master_wb_with_pick_history([
        # 40 terminal MLB PROP rows with known MOP values
        ("2026-06-09", "MLB", "PROP", "WIN", 0.76),
        # ... etc
    ])
    # Snapshot verdicts before
    verdicts_before = _snapshot_verdicts(wb)
    # Run calibration
    from calibration import compute_and_update_calibration
    compute_and_update_calibration(_wb_override=wb, calibration_path=Path(tmp_path / "cal.json"))
    # Assert verdicts unchanged
    verdicts_after = _snapshot_verdicts(wb)
    assert verdicts_before == verdicts_after
```

**Design B: Structural import assertion**

```python
def test_calibration_module_does_not_import_gate_or_grading():
    """METRICS-03: calibration.py must not import evaluate_no_bet_gates
    or any grading function — structural check."""
    import ast, pathlib
    src = (pathlib.Path(__file__).parent / "calibration.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [n.name for n in getattr(node, 'names', [])]
            module = getattr(node, 'module', '') or ''
            assert 'evaluate_no_bet_gates' not in str(names + [module])
            assert 'grade_slips' not in str(names + [module])
```

**Design C: Gate output unchanged with injected factor**

```python
def test_gate_output_unchanged_by_sigma_factor():
    """METRICS-03: with calibration factor in calibration.json, evaluate_no_bet_gates
    returns the same gate output for a fixed pick as it does without the file."""
    pick = {
        "kind": "prop", "edge": 1.5, "model_over_probability": 0.58,
        "injury_status": "ACTIVE", "platform": "PrizePicks",
        # ... other required fields
    }
    # Run gate without calibration factor (1.0)
    ok1, skipped1, passed1 = runner.evaluate_no_bet_gates(pick, {})
    # The factor only affects model_over_probability at PROJECTION time (in generate_projections.py),
    # not at gate evaluation time (gate reads the stored probability).
    # Therefore gate output MUST be identical regardless of calibration.json content.
    ok2, skipped2, passed2 = runner.evaluate_no_bet_gates(pick, {})
    assert ok1 == ok2
    assert skipped1 == skipped2
```

**RECOMMENDED combination:** Design A (verdict snapshot) + Design B (import check). Design B is cheap and provides structural proof. Design A is the runtime proof. Design C is redundant once the architecture is confirmed correct — the sigma factor only affects future projections, not stored probabilities already in Pick History.

### Sampling Rate
- **Per task commit:** `cd scripts && python3 -m pytest test_weekly_metrics.py -x`
- **Per wave merge:** `cd scripts && python3 -m pytest -x` (full suite, ~34 min — run at phase end)
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `scripts/test_weekly_metrics.py` — covers all METRICS-01/02/03 requirements
- [ ] `scripts/calibration.py` — new module (Wave 0 scaffold: stub functions + docstrings)
- [ ] `scripts/metrics_report.py` — new module (Wave 0 scaffold)
- [ ] `data/research/calibration.json` — created on first task run (not Wave 0)

---

## Security Domain

> `security_enforcement` not explicitly set to `false` in config — treat as enabled.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | No new auth surfaces |
| V3 Session Management | No | No sessions |
| V4 Access Control | No | Local-only file writes |
| V5 Input Validation | Yes — `calibration.json` read | `to_float()` + `max(clamp_lo, min(clamp_hi, ...))` — validate before use |
| V6 Cryptography | No | No secrets written |

### Known Threat Patterns

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Corrupt `calibration.json` crashes projection generation | Tampering | `load_calibration_factor` wraps in `try/except`, returns 1.0 on any failure — already designed |
| Calibration write partial-file leaves malformed JSON | Tampering | Atomic rename pattern (`os.replace` from `.tmp`) |
| Unbounded `audit` array in calibration.json | Denial of Service | Trim to last 52 entries on each write |

---

## Open Questions

1. **Should `n_with_mop` (rows with both terminal result AND non-null MOP) or `n_outcomes` (all terminal WIN/LOSS rows) gate the ≥30 check?**
   - What we know: 42 MLB rows have MOP; 222 rows are terminal overall. Using `n_with_mop` is stricter.
   - Recommendation: gate on `n_with_mop` — calibration is only meaningful with MOP values.

2. **Should `Slip Result = "GRADED"` rows be treated as resolved (use Net PnL sign as proxy) or excluded from the slip win-rate count?**
   - What we know: 2026-06-08 Slip History rows show `Slip Result = "GRADED"` (not WIN/LOSS/PUSH). Net PnL and Gross Return are populated.
   - Recommendation: exclude "GRADED" from W/L/P count (they are ambiguous), but INCLUDE them in ROI computation (`Σ Net PnL / Σ Stake`) as long as `Needs Payout Reconciliation` is false. This gives correct money ROI without requiring win/loss parsing on legacy rows.

3. **D-12: One task or two?**
   - RECOMMENDATION: one task (`weekly_metrics`). Rationale documented above (shared reads, fast, simpler cron wiring). Planner may split if test isolation requires it.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| python3 | All scripts | ✓ | 3.14.0a2 | — |
| openpyxl | Workbook reads | ✓ | 3.1.5 | — |
| requests | Telegram API | ✓ | 2.34.2 | Telegram degrades to no-op |
| `data/pnl/master_pnl.xlsx` | Report data source | ✓ | Exists, 7 sheets | — |
| `data/nba/nba_*.xlsx` (per-date) | Slip ROI by sport | ✓ | 15 files (06-08 to 06-22) | — |
| `data/mlb/mlb_*.xlsx` (per-date) | Slip ROI by sport | ✓ | 15 files | — |
| `~/.hermes/skills/delegation/obsidian_sync/scripts/obsidian_sync.py` | Obsidian note delivery | [ASSUMED] present | — | Degrades gracefully per existing pattern |
| `data/research/calibration.json` | Calibration state | ✗ — does not yet exist | — | Created on first task run (default all 1.0) |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:**
- `calibration.json` — created on first run; `generate_projections.py` defaults to factor=1.0 when absent (designed this way).

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `apply_hit_rate_adjustment:1648` adjusts confidence tier | Sigma-path factor in `generate_projections.py` | Phase 4 (this phase) | Upstream tuning, doesn't touch gate thresholds |
| No feedback loop | Bounded weekly sigma scaler from realized outcomes | Phase 4 | Closes the "is the model improving?" loop |
| Obsidian weekly recap is a blank scaffold | Filled with slip ROI + prop hit-rate + calibration audit | Phase 4 | Makes the weekly recap the source of truth for model performance |

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Smoothed confidence ratio is the right calibration formula for n≈30 | Calibration Formula | Could underfit/overfit; mitigated by ±0.05 step clamp |
| A2 | `obsidian_sync.py` skill exists at `~/.hermes/skills/...` | Environment Availability | Obsidian note delivery fails silently (task continues per existing pattern) |
| A3 | "GRADED" Slip Result rows should be excluded from W/L/P count but included in ROI | Open Questions #2 | ROI calculation would be correct; win-rate would be understated for Jun 8 |
| A4 | Per-sport workbook Slip History iteration (<30 file opens) is fast enough for the 660s budget | Task Wiring | Could be slow if workbooks are large; 30 small files should be <5s |

---

## Sources

### Primary (HIGH confidence)
- `scripts/sports_system_runner.py` — `TASK_TIMEOUTS:120`, `task_workbook_paths:7192`, `run_task:7261`, `RESULT_HEADERS:292`, `PROP_ACCURACY_HEADERS:299`, `refresh_prop_accuracy:5293`, `obsidian_create_weekly_recap:1034`, `apply_hit_rate_adjustment:1648`, `send_telegram:428` — all confirmed by direct code read
- `scripts/generate_projections.py` — `estimate_sigma:277`, `model_over_probability:289`, `build_projection:380` — injection point confirmed
- `scripts/slip_payouts.py` — `SLIP_HISTORY_HEADERS:18`, `slip_history_row:200` — schema confirmed; no Sport column confirmed
- `scripts/grade_slips.py` — `slips_by_sport` routing at lines 600–613 — per-sport bucketing confirmed
- `data/pnl/master_pnl.xlsx` — direct workbook inspection: 277 Pick History rows, 42 terminal PROP rows with MOP, `Prop Accuracy` sheet has 4 rows (2026-W24 NBA+MLB, 2026-W25 MLB, 2026-W26 MLB)

### Secondary (MEDIUM confidence)
- `.planning/phases/04-dual-metrics-and-feedback/04-CONTEXT.md` — all locked decisions D-01..D-13, canonical references with line numbers

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all stdlib + existing deps; no new packages
- Architecture: HIGH — all injection points verified by code inspection
- Calibration formula: MEDIUM — research-recommended, not from official literature; the step clamp is the operator's explicit safety net
- Feasibility (MOP recoverability): HIGH — directly confirmed by workbook inspection
- Sport attribution approach: HIGH — confirmed by grade_slips code + workbook structure
- Pitfalls: HIGH — all derived from actual code/data observation

**Research date:** 2026-06-22
**Valid until:** 2026-09-22 (stable stdlib; 90 days)
