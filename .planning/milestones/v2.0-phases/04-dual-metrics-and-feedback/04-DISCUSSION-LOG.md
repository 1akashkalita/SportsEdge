# Phase 4: Dual Metrics and Feedback - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-23
**Phase:** 4-dual-metrics-and-feedback
**Areas discussed:** Report surface & cadence, Report shape & 'improving' signal, Feedback target, Feedback bounding & control

---

## Report surface & cadence

### Surface

| Option | Description | Selected |
|--------|-------------|----------|
| Both Telegram + Obsidian | Telegram push digest + persistent browsable Obsidian record; fills the blank weekly-recap scaffold | ✓ |
| Obsidian note only | Persistent markdown, no phone push — you must remember to look | |
| Telegram message only | Push digest, no persistent file; history = chat scrollback | |

**User's choice:** Both Telegram + Obsidian

### Cadence

| Option | Description | Selected |
|--------|-------------|----------|
| Standalone weekly task | New runner task on its own weekly cron entry; rebuilds Obsidian note + pushes Telegram digest; matches by-week grain, keeps daily runs lean | ✓ |
| On-demand task only | Same task invoked manually, no cron entry | |
| Append to each daily run | Regenerate + push every daily run; always current but daily Telegram noise + daily budget cost | |

**User's choice:** Standalone weekly task

---

## Report shape & 'improving' signal

### 'Improving vs stagnant' signal

| Option | Description | Selected |
|--------|-------------|----------|
| Metric + WoW delta + arrow | Each week×sport row shows ROI + hit-rate plus week-over-week change and ↑/→/↓ arrow; optional rolling avg | ✓ |
| Add a computed verdict line | Everything above plus a one-line auto-verdict per sport/metric; risks over-reading tiny samples | |
| Plain table, no trend math | Just ROI + hit-rate per week/sport, eyeball the trend | |

**User's choice:** Metric + WoW delta + arrow

### Slip ROI scope

| Option | Description | Selected |
|--------|-------------|----------|
| Staked slips only | ROI = Σ Net PnL / Σ Stake and win-rate over slips actually bet (stake>0); zero-stake slips shown as separate count | ✓ |
| All recorded slips | Include zero-stake slips in counts (dilutes win-rate, inflates volume) | |
| Show both side by side | Money metric AND all-recommendations accuracy metric as distinct rows | |

**User's choice:** Staked slips only

**Notes:** Sport attribution was resolved without a question — verified that no cross-sport slips exist
today and slips carry no top-level sport field, so sport is derived from legs; any future mixed slip →
"MIXED" bucket (Claude's discretion).

---

## Feedback target — what gets tuned

### Tunable parameter

| Option | Description | Selected |
|--------|-------------|----------|
| Projection probability calibration | Per-sport factor on model_over_probability (sigma scaler) from realized-vs-predicted; reshapes future picks via unchanged gates; safest for METRICS-03 | ✓ |
| Hit-rate confidence-adj thresholds | Tune apply_hit_rate_adjustment cutoffs from outcomes; coarser integer-score nudge | |
| Confidence→stake mapping | Adjust P3 stake tiers by which confidence bands win; affects money sizing (P3 territory) | |

**User's choice:** Projection probability calibration

### Granularity

| Option | Description | Selected |
|--------|-------------|----------|
| Per sport (NBA, MLB) | Two factors; matches report grain; pools enough outcomes at low volume | ✓ |
| Per sport × stat type | Finer but starves on samples today | |
| Single global factor | Most robust to small samples, blends NBA/MLB | |

**User's choice:** Per sport (NBA, MLB)

---

## Feedback bounding & control

### Apply mode

| Option | Description | Selected |
|--------|-------------|----------|
| Auto-apply bounded, flag default-off | Writes bounded factor when ENABLE_CALIBRATION_FEEDBACK on; ships off; mirrors firecrawl-flag precedent | |
| Propose in report, apply on approval | Loop computes + shows suggestion; takes effect only on operator approval | |
| Auto-apply bounded, on by default | Closed loop from day one within hard caps + logging, no flag | ✓ |

**User's choice:** Auto-apply bounded, on by default
**Notes:** Operator chose the most aggressive option over the recommended flag-default-off — a clear
signal they want a true closed loop and to stop babysitting, trusting the hard bounds as the safety net.

### Bounds

| Option | Description | Selected |
|--------|-------------|----------|
| Conservative | Min 30 outcomes/sport before moving off 1.0; ±5%/week; clamp [0.85, 1.20] | ✓ |
| Tighter / slower | Min 50; ±3%/week; clamp [0.90, 1.15] | |
| Looser / faster | Min 20; ±10%/week; clamp [0.75, 1.30] | |

**User's choice:** Conservative

### Measurement window

| Option | Description | Selected |
|--------|-------------|----------|
| Cumulative since inception | Every graded outcome since 2026-06-08; most samples, most stable, slow to reflect recent improvement | ✓ |
| Rolling trailing window | Last ~4–6 weeks; responsive but may rarely clear the 30-outcome gate at today's volume | |
| Rolling window + cumulative gate | Trailing window for responsiveness, cumulative gate before adjusting | |

**User's choice:** Cumulative since inception

---

## Claude's Discretion

- New task name(s) and whether weekly report + calibration recompute are one task or two (D-12).
- Module placement (new `metrics_report.py` / `calibration.py` vs runner functions).
- Precise calibration formula (realized-vs-predicted → sigma scaler) within the conservative bounds.
- Telegram digest wording + Obsidian markdown layout (reuse weekly-recap scaffold shape).
- "MIXED" sport bucket handling for any future cross-sport slip; test file names; report sheet-vs-markdown.
- The exact METRICS-03 integrity mechanism (the guarantee is locked; the implementation is open).

## Deferred Ideas

- Rolling-window calibration (revisit from cumulative once volume grows).
- Per-stat-type calibration granularity (until samples plentiful).
- Auto-computed "improving/stagnant" verdict line in the report.
- Additional feedback knobs (hit-rate confidence thresholds, confidence→stake mapping) — one knob for P4.
- Daily/append report cadence (chose weekly).
