# Phase 2: Reliability Fixes + Defect Removal - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-15
**Phase:** 2-Reliability Fixes + Defect Removal
**Areas discussed:** Timeout fix reach, Broken-pipe breadth, Done / verify

---

## Gray-area selection

| Option | Description | Selected |
|--------|-------------|----------|
| Timeout fix reach | How far Phase 2 bounds the timeout (FIX-02) | ✓ |
| Broken-pipe breadth | How broadly safe_print() is applied (FIX-01) | ✓ |
| Test strategy | Ship per-fix tests now vs. defer to Phase 3 | (resolved implicitly via Done/verify) |
| Done / verify | How to prove FIX-03 + fault conditions | ✓ |

**User's choice:** Timeout fix reach, Broken-pipe breadth, Done / verify
**Notes:** Test strategy was left to Claude's discretion but got effectively resolved by the
"Extend repro harness" choice in the Done/verify area (each fix ships with a regression test).

---

## Timeout fix reach (FIX-02)

### Q1 — How far to reach

| Option | Description | Selected |
|--------|-------------|----------|
| Bound both offenders | Cap + circuit-break Telegram AND decouple obsidian_sync; no Phase-3 re-scope | ✓ |
| Telegram only | Just bound the Rank-1 Telegram retry loop | |
| Pull hard timeout in | Also add a hard per-task self-timeout now (pulls RES-03 forward) | |

**User's choice:** Bound both offenders
**Notes:** Keeps the hard self-timeout (RES-03) in Phase 3; Phase 2 bounds the two named
contributors (Rank 1 Telegram, Rank 2 obsidian_sync).

### Q2 — Telegram circuit-breaker trip behavior

| Option | Description | Selected |
|--------|-------------|----------|
| Drop + log summary | Skip remaining Telegram calls; write one 'N alerts suppressed' run-log line | ✓ |
| Drop silently | Skip with no summary line | |
| Persist for later flush | Queue missed alerts and re-send on recovery | |

**User's choice:** Drop + log summary
**Notes:** Breaker resets per task run. No retry storm, nothing silently lost. Persist-and-flush
rejected as Phase-4 observability scope.

### Q3 — Obsidian decoupling (what/when to write)

| Option | Description | Selected |
|--------|-------------|----------|
| Batch all, flush at end | One obsidian_sync call at task end with the full log | |
| Sync summary only | Obsidian gets the end-of-task summary, not every raw line | ✓ |
| Async per line | Keep real-time but non-blocking background calls | |

**User's choice:** Sync summary only
**Notes:** Deliberate, opted-in behavior change to Obsidian content (leaner vault). Research must
first confirm the current per-section payload so no relied-on section is dropped.

---

## Broken-pipe breadth (FIX-01)

### Q1 — How broad to apply safe_print()

| Option | Description | Selected |
|--------|-------------|----------|
| Sweep all bare prints | Wrap main() prints (5634/5640) + line 1274 + any others in safe_print() | ✓ |
| Narrow — main() only | Wrap just the 2 main() prints | |
| Sweep + reclassify now | Sweep prints AND make except not fire spurious TASK FAILED (pulls RES-02 forward) | |

**User's choice:** Sweep all bare prints
**Notes:** except-reclassification stays Phase 3 (RES-02). Verification must confirm no spurious
TASK FAILED fires under the pipe-close condition.

---

## Done / verify (FIX-03 + fault proof)

### Q1 — Clean end-to-end pass

| Option | Description | Selected |
|--------|-------------|----------|
| Scripted run-all | Repeatable script runs all 11 tasks, asserts exit 0 / no uncaught exc | ✓ |
| Scripted + real cron | Add a real Hermes cron cycle as final confirmation | |
| Real cron only | Prove purely on an actual scheduled run | |

**User's choice:** Scripted run-all
**Notes:** Deterministic, no cron wait, seeds Phase-5 CI.

### Q2 — Fault-condition proof

| Option | Description | Selected |
|--------|-------------|----------|
| Extend repro harness | Pipe-close → no spurious alert; forced-Telegram-fail → bounded + suppressed-count | ✓ |
| Mock at HTTP boundary | Inject failures into the requests layer more generally | |
| Observe next real outage | Ship and confirm against the next real outage in the run-log | |

**User's choice:** Extend repro harness
**Notes:** Becomes the FIX-01/FIX-02 regression tests and the RES-04 seed. Heed Phase-1 WR-03 —
harden the repro's run-log scan before it becomes the standing test.

---

## Claude's Discretion

- **DEF-01:** Remove dead earlier `injury_monitor` (~3610) / `clv_tracker` (~3651) defs; diff
  vs. the active later defs (~5049/~5443) before deleting, surface any divergence, confirm via
  existing tests.
- **DEF-02:** `Path.home()`-based base path in `generate_projections.py` + a path-resolution test.
- Circuit-breaker threshold N, shortened Telegram timeout value, Obsidian batching mechanism,
  run-all script structure, and the exact wording of the suppressed-alerts summary line.

## Deferred Ideas

- Hard per-task self-timeout → Phase 3 (RES-03)
- except-branch broken-pipe reclassification → Phase 3 (RES-02)
- Retry-with-backoff on all outbound network calls → Phase 3 (RES-01)
- Persist-and-flush queue for suppressed alerts → Phase 4 (observability)
- Full RES-04 regression sweep across all network calls → Phase 3
