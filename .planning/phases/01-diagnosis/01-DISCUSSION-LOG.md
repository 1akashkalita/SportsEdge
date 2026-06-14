# Phase 1: Diagnosis - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-13
**Phase:** 1-Diagnosis
**Areas discussed:** Repro strategy, Investigation breadth, Diagnosis doc (Timing evidence handled by Claude's default)

---

## Area selection

| Option | Description | Selected |
|--------|-------------|----------|
| Repro strategy | How to prove the broken pipe: local repro / real-run capture / both | ✓ |
| Timing evidence | In-runner instrumentation vs. external timed runs + log mining | |
| Diagnosis doc | What DIAGNOSIS.md must contain; how far toward fixes; offender framing | ✓ |
| Investigation breadth | 3 named leads only vs. broader profiling sweep; evidence bar | ✓ |

**User's choice:** Diagnosis doc, Investigation breadth, Repro strategy.
**Notes:** Timing evidence left to Claude's default (external timed runs + log mining first; temporary in-runner instrumentation only if needed).

---

## Repro strategy

### Q1 — Primary evidence path for the broken pipe

| Option | Description | Selected |
|--------|-------------|----------|
| Local repro script first | Deterministic forced BrokenPipeError; doubles as Phase-3 regression seed; add live capture only if it doesn't match | |
| Real cron-run capture | Traceback dump in main()'s except, wait for next natural failure; highest fidelity but slow | |
| Both, in parallel | Local repro + lightweight live traceback dump; strongest evidence | ✓ |

**User's choice:** Both, in parallel.

### Q2 — Disposition of the live instrumentation at end of Phase 1

| Option | Description | Selected |
|--------|-------------|----------|
| Keep as stepping stone | Leave additive traceback logging in place as a Phase-4 down payment | ✓ |
| Revert after capture | Throwaway scaffolding; Phase 1 ends with zero code change | |
| Log to file only, keep | Keep, but write trace to a dedicated diagnostics file so it can't self-broken-pipe | |

**User's choice:** Keep as stepping stone.
**Notes:** Claude folded in the safety nuance from the "log to file only" option — the kept trace lands in the run-log file under `data/pnl/logs/` (robust sink), not solely stdout, so the instrumentation can't trip the pipe it measures (CONTEXT D-04).

---

## Investigation breadth

### Q1 — How wide to cast the investigation

| Option | Description | Selected |
|--------|-------------|----------|
| Asymmetric | Broken pipe: 3 named leads only. Timeout: broad timing sweep across all stages | ✓ |
| Focused on the 3 leads | Only the three named suspects for both failures; fastest, risks missing a timeout contributor | |
| Full profiling sweep | Everything in CONCERNS.md across both sports; most thorough, heaviest | |

**User's choice:** Asymmetric.

### Q2 — Evidence bar for the timing sweep

| Option | Description | Selected |
|--------|-------------|----------|
| Multiple runs, worst-case focus | Several runs to capture typical vs. worst-case per-stage durations | |
| Single representative run | One timed run per task names the dominant stage; corroborate with existing >90s warnings | ✓ |
| Mine existing logs only | Reconstruct durations from existing logs only; zero new load | |

**User's choice:** Single representative run.

---

## Diagnosis doc

### Q1 — How prescriptive about fixes

| Option | Description | Selected |
|--------|-------------|----------|
| Cause + fix direction | Cause + evidence + recommended fix direction, implementation left open | ✓ |
| Cause only | Pure diagnosis; all fix decisions deferred to Phase 2 | |
| Cause + ranked fix options | Cause + 2-3 candidate fixes with tradeoffs; edges into Phase 2 territory | |

**User's choice:** Cause + fix direction.

### Q2 — How to present timeout findings

| Option | Description | Selected |
|--------|-------------|----------|
| Ranked contributors | Dominant offender + next-biggest stages with measured durations, vs. cron budget | ✓ |
| Single worst offender | Only the one stage that blows the budget | |

**User's choice:** Ranked contributors.

---

## Claude's Discretion

- Exact structure of the local repro script and how it wires the stdout-closure.
- Which specific tasks to time beyond `daily_picks` (nba + mlb) and `mlb_prop_monitor`.
- Precise DIAGNOSIS.md section ordering / formatting.
- **Timing-evidence method** (area not selected): external timed runs + log mining first; temporary in-runner per-stage instrumentation only if coarse numbers don't isolate the offender (CONTEXT D-11).

## Deferred Ideas

None — discussion stayed within phase scope.
