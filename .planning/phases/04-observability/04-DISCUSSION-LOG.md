# Phase 4: Observability - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-21
**Phase:** 4-Observability
**Areas discussed:** Run-log record (OBS-01), Shared source of truth, Health check (OBS-02), Streak alert (OBS-03)

---

## Run-log record (OBS-01)

### Record format / location

| Option | Description | Selected |
|--------|-------------|----------|
| JSONL file | Append-only `data/pnl/logs/run_log.jsonl`, one object per line; `run_log.txt` stays as-is | ✓ |
| Augment run_log.txt | Append a parseable marker line into the existing free-form log | |
| One JSON file per run | `data/pnl/logs/runs/<task>_<ts>.json` | |

**User's choice:** JSONL file
**Notes:** Cleanest to parse, trivial to tail, no schema migration; natural shared source for OBS-02/OBS-03.

### Record fields

| Option | Description | Selected |
|--------|-------------|----------|
| Core+ | task, status, duration_s, error, timestamp (ISO), exit_code, sport | ✓ |
| Minimal | The OBS-01 four + timestamp only | |
| Rich | Core+ plus skip reason, telegram-suppressed count, budget_s | |
| Let Claude decide | Field set chosen during planning | |

**User's choice:** Core+

---

## Shared source of truth

| Option | Description | Selected |
|--------|-------------|----------|
| Single source | Both OBS-02 and OBS-03 read the `run_log.jsonl` tail; no extra state files | ✓ |
| JSONL + small streak file | Health reads JSONL; OBS-03 keeps a separate per-task counter file | |
| Independent state | Each consumer maintains its own derived store | |

**User's choice:** Single source
**Notes:** Fewest moving parts, nothing to keep in sync — fits the minimal-invasive contract.

---

## Health check (OBS-02)

### Invocation surface

| Option | Description | Selected |
|--------|-------------|----------|
| Standalone script | `scripts/health_check.py`, read-only, no fcntl lock, runs any time, schedulable as heartbeat | ✓ |
| New runner task | `--task health` — consistent entrypoint but acquires the global lock | |
| Extend verify() | Fold health into the existing verify task | |

**User's choice:** Standalone script

### "Overdue" logic

| Option | Description | Selected |
|--------|-------------|----------|
| In-repo cadence map | task->max-staleness dict in code, sibling to `TASK_TIMEOUTS`; explicit, testable | ✓ |
| Read Hermes cron schedule | Parse `~/.hermes/config.yaml` to derive windows; couples to an external file | |
| Uniform staleness threshold | One "not seen in N hours" rule for all tasks | |
| Let Claude decide | Decide during planning | |

**User's choice:** In-repo cadence map

### Output

| Option | Description | Selected |
|--------|-------------|----------|
| Both | Always print stdout snapshot; ALSO Telegram alert when overdue/last-failed | ✓ |
| Print report only | stdout snapshot the operator reads | |
| Telegram only | Push snapshot/alert to Telegram | |

**User's choice:** Both

---

## Streak alert (OBS-03)

### Threshold

| Option | Description | Selected |
|--------|-------------|----------|
| Configurable, default 2 | Fire at >= N consecutive failures, env var defaulting to 2 | ✓ |
| Hardcoded at 2 | Fire on the 2nd consecutive failure, no knob | |
| Let Claude decide | Pick during planning | |

**User's choice:** Configurable, default 2

### What counts / resets

| Option | Description | Selected |
|--------|-------------|----------|
| Errors+timeouts; any clean run resets | Streak = trailing error/timeout records; first status=ok (incl. SKIP) clears it; no extra field | ✓ |
| Skip is neutral | Step over SKIP records; requires adding a `skipped` flag to the record | |
| Only hard errors count | Timeouts excluded from the streak | |
| Let Claude decide | Decide during planning | |

**User's choice:** Errors+timeouts; any clean run resets
**Notes:** Keeps the Core+ field set as-is (no `skipped` flag needed).

### Alert content & cadence

| Option | Description | Selected |
|--------|-------------|----------|
| Distinct, every failure at/after N | `🔁 REPEATED FAILURE` sibling, in addition to the per-occurrence alert; fires each failure once streak >= N, count grows | ✓ |
| Distinct, once when threshold crossed | Fire only on the run that first hits N; quiet thereafter until reset | |
| Let Claude decide | Pick wording/cadence during planning | |

**User's choice:** Distinct, every failure at/after N

---

## Claude's Discretion

- Exact JSONL field names/casing and serialization helper.
- Concrete cadence-map values for OBS-02.
- The OBS-03 env-var name and exact `🔁 REPEATED FAILURE` wording.
- Whether/how to bound `run_log.jsonl` growth (rotation / keep-last-N / size cap vs. accept unbounded — records are tiny).
- Health-check exit-code convention (e.g., non-zero when something is overdue/failed).

## Deferred Ideas

- OBS-04 (historical run analytics / dashboard) and OBS-05 (per-stage timing breakdown) → v2, already deferred in REQUIREMENTS.md.
- CI running the suite (CI-01/CI-02) → Phase 5.
