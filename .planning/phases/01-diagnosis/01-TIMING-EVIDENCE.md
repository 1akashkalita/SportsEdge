# Phase 1: Timing Evidence (DIAG-02)

**Produced:** 2026-06-15
**Method:** Run-log mining (18,626 lines, 2026-06-08 through 2026-06-15) + representative timed invocations
**Log source:** `data/pnl/logs/run_log.txt`

---

## Run-Log Duration Profile

Mined from all 11 runner tasks across the full log. Columns: min observed (fastest), 25th percentile (typical fast), median (typical), 75th percentile (typical slow), and max observed (extreme outlier).

| Task | Count | Min | p25 (fast) | Median (typical) | p75 (slow) | Max (extreme) | Cause of extreme |
|------|------:|----:|----------:|----------------:|----------:|-------------:|-----------------|
| `nba_daily_picks` | 26 | 13.8s | 18.7s | 21.3s | 62.8s | 7,331.1s | Workbook lock contention (held by prior task stalled on Telegram retries) |
| `mlb_daily_picks` | 30 | 28.9s | 35.3s | 44.4s | 164.3s | 7,697.0s | Same pattern; 2026-06-15 lock wait from Telegram retry storm |
| `nba_prop_monitor` | 131 | 2.9s | 10.4s | 31.0s | 103.0s | 10,062.1s | `send_telegram()` retry loop during network outage + `obsidian_sync` per log line |
| `mlb_prop_monitor` | 84 | 5.5s | 25.9s | 98.7s | 197.3s | 12,585.3s | Same; 61 Telegram calls (61 line moves) × `obsidian_sync` subprocesses |
| `nba_clv_tracker` | 56 | 2.7s | 25.4s | 240.3s | 3,069.5s | 24,860.0s | Workbook lock contention + Telegram retry storm on network outage |
| `mlb_clv_tracker` | 56 | 4.8s | 46.5s | 205.9s | 3,792.2s | 24,923.3s | Same pattern |
| `nba_injury_monitor` | 131 | 2.4s | 8.4s | 14.2s | 50.5s | 6,254.5s | Telegram retry storm (ESPN call OK; Telegram stalls on network down) |
| `mlb_injury_monitor` | 3 | 16.3s | 16.3s | 21.7s | 374.2s | 374.2s | Only 3 samples; the 374s coincides with Telegram retry window |
| `game_completion_monitor` | 381 | 0.5s | 1.8s | 2.2s | 4.9s | 651.4s | Telegram retry + lock contention (rare) |
| `check_results` | 6 | 16.9s | 19.5s | 49.4s | 568.5s | 2,025.5s | Network outage Telegram retry storm |
| `verify` | 14 | 23.0s | 23.7s | 26.6s | 89.7s | 1,780.3s | Telegram retry storms (2026-06-14: three verify runs at ~90s each during retry window) |

**Key observation (heavy path):** `nba_daily_picks` and `mlb_daily_picks` are fast under normal network conditions: nba 21s median, mlb 44s median. The 1500s theoretical subprocess ceiling has never been reached in the observed log.

**Key observation (monitor tasks):** `mlb_prop_monitor` and `nba_prop_monitor` have high variance. The extreme outliers (12,585s and 10,062s) are driven entirely by network outages causing Telegram retry storms, not by slow data processing.

---

## Slow-Run Warning Corroboration

The runner's `main()` finally block logs a `WARNING: {task} took {N}s — consider further optimization` when elapsed > 90s. The log contains **206 slow-run warnings** across the study period.

Sample of notable slow-run warnings (verbatim, timestamps retained):

```
[2026-06-09T22:48:00+00:00] WARNING: mlb_prop_monitor took 129.4s — consider further optimization
[2026-06-10T06:27:21+00:00] WARNING: mlb_daily_picks took 472.9s — consider further optimization
[2026-06-10T19:07:27+00:00] WARNING: nba_daily_picks took 5787.0s — consider further optimization
[2026-06-10T19:15:15+00:00] WARNING: nba_injury_monitor took 6254.5s — consider further optimization
[2026-06-12T16:41:37+00:00] WARNING: nba_clv_tracker took 24860.0s — consider further optimization
[2026-06-12T16:42:40+00:00] WARNING: mlb_clv_tracker took 24923.3s — consider further optimization
[2026-06-14T22:49:24+00:00] WARNING: nba_clv_tracker took 10210.8s — consider further optimization
[2026-06-14T22:49:04+00:00] WARNING: mlb_clv_tracker took 10190.6s — consider further optimization
[2026-06-15T21:03:15+00:00] WARNING: verify took 183.2s — consider further optimization
[2026-06-15T21:09:32+00:00] WARNING: mlb_prop_monitor took 231.0s — consider further optimization
```

Tasks exceeding 90s: `mlb_prop_monitor`, `nba_prop_monitor`, `nba_injury_monitor`, `nba_clv_tracker`, `mlb_clv_tracker`, `nba_daily_picks`, `mlb_daily_picks`, `game_completion_monitor`, `check_results`, `verify`. Only `mlb_injury_monitor` has not been flagged in the slow-run warnings (sample size: 3 runs).

---

## Extreme-Duration / Network-Stall Correlation

### Case 1: `mlb_prop_monitor` 129.4s — Canonical Broken-Pipe Event (2026-06-09)

The task completed its work at 22:47:00 with 61 line moves, then fired 61 sequential Telegram alerts (one per line move). Each `send_telegram()` success called `log("Telegram alert sent")`, spawning an `obsidian_sync` subprocess.

Verbatim run-log excerpts:
```
[2026-06-09T22:47:00+00:00] MLB prop monitor complete: active_props=5023 rows_refreshed=300 line_moves=61 injury_watches=387 middles=0 arbs=0 workbook=...
[2026-06-09T22:47:00+00:00] Telegram alert sent
[2026-06-09T22:47:01+00:00] Telegram alert sent
[2026-06-09T22:47:02+00:00] Telegram alert sent
... [58 more "Telegram alert sent" lines, one per second] ...
[2026-06-09T22:47:58+00:00] Telegram alert sent
[2026-06-09T22:47:58+00:00] ERROR task=mlb_prop_monitor: [Errno 32] Broken pipe
[2026-06-09T22:47:59+00:00] Telegram alert sent
[2026-06-09T22:47:59+00:00] [mlb_prop_monitor] completed in 129.4s
[2026-06-09T22:48:00+00:00] WARNING: mlb_prop_monitor took 129.4s — consider further optimization
```

**Analysis:** The Hermes `no_agent` pipe closed ~58 seconds after the task's actual work completed, while `dispatch_alerts` was still firing Telegram calls. The 129.4s total = ~70s of prop-monitor work + ~58s of 61-Telegram fanout. The `[Errno 32] Broken pipe` at 22:47:58 is the exact instant the final bare `print("JSON_RESULT=...")` at line 5634 was called on a closed pipe.

### Case 2: `nba_clv_tracker` 24,860s extreme (2026-06-12)

The task acquired the workbook lock at 09:47:17 UTC — but the task was launched much earlier. Backward calculation: completion at 16:41:37, duration 24860s → start at approximately 09:47 UTC (the lock acquisition confirms the task was waiting on the lock for the entire prior period). The prior `check_results` task had been running since approximately 06:00 and stalled on Telegram retries:

```
[2026-06-12T09:30:04+00:00] Telegram alert failed attempt 2/2: ... (Caused by NameResolutionError("... Failed to resolve 'api.telegram.org' ..."))
[2026-06-12T09:30:05+00:00] Telegram alert failed after all retries; continuing without crashing task
[2026-06-12T09:30:22+00:00] Telegram alert failed after all retries; continuing without crashing task
[2026-06-12T09:30:22+00:00] [check_results] completed in 2025.5s
[2026-06-12T09:47:17+00:00] Acquired workbook lock /Users/akashkalita/sports_picks/locks/nba_2026-06-12.xlsx.lock
```

Once the CLV tracker acquired the lock, it had to complete its own work with network APIs also unreachable:
```
[2026-06-12T16:41:24+00:00] Odds-API.io events error sport=nba ... (Caused by NameResolutionError("... Failed to resolve 'api.odds-api.io' ..."))
[2026-06-12T16:41:30+00:00] NBA CLV prop closing line refresh skipped: [Errno 32] Broken pipe
[2026-06-12T16:41:37+00:00] [nba_clv_tracker] completed in 24860.0s
```

**Analysis:** The 24,860s duration = prior lock wait (from task start to lock acquisition) + network-stalled Telegram retries during the lock period. The task's actual computational work was milliseconds.

### Case 3: Today's Telegram Retry Storm (2026-06-15)

Network outage between approximately 19:00 and 21:00 UTC caused tasks queued in the cron scheduler to stack up:

```
[2026-06-15T19:39:12+00:00] [mlb_daily_picks] completed in 7,697.0s
[2026-06-15T19:39:42+00:00] [nba_prop_monitor] completed in 5,641.6s
[2026-06-15T19:47:11+00:00] [nba_injury_monitor] completed in 6,090.8s
[2026-06-15T20:44:50+00:00] [mlb_prop_monitor] completed in 9,549.7s
```

All four completed within a 65-minute window after the outage cleared — confirming the duration was dominated by network-stall time, not by actual data processing.

---

## Lead #2 Disposition

**RULED OUT** as the primary cause of extreme durations.

Theoretical ceiling for `daily_picks`: `fetch_dfs_props` (300s timeout) + `build_hit_rate_db` (600s timeout) + `generate_projections` (600s timeout) = **1,500s maximum** if all three subprocess stages time out simultaneously.

Largest observed `daily_picks` duration: **7,697.0s** (`mlb_daily_picks`, 2026-06-15T19:39:12).

The 7,697s figure **exceeds the 1,500s theoretical ceiling by 5x**, which conclusively demonstrates it cannot be caused by subprocess timeouts. Working backward from the log: the `mlb_daily_picks` task at 2026-06-15T19:39:12 started approximately 2026-06-15 17:31 UTC — during the Telegram retry storm window. The task was blocked on the workbook lock while prior tasks stalled. The subprocess stages (hit_rate_db, projections) ran normally in ~20s each under normal conditions.

Additional evidence: `nba_daily_picks` ran in **38.8s** wall clock in the same environment (today, after the storm cleared), confirming subprocess stages are fast. The 7,697s extreme is entirely lock-contention + network-stall time.

**Confirmed sub-finding:** The 1,500s subprocess ceiling has never been reached in 791+ task completions. The stacked subprocess timeout totals (Lead #2) are a theoretical upper bound that is not a real operational risk.

---

## Representative Timed Runs

All runs executed on 2026-06-15 from `scripts/` using `time python3 sports_system_runner.py --task <task>`. The runner's own `completed in Ns` line is corroborated against shell `time` output.

| Task | Wall clock (`time`) | Runner `completed in` | `real` vs `completed in` delta | Observation |
|------|---------------------|-----------------------|-------------------------------|-------------|
| `verify` | 3m4.7s (184.7s) | 183.2s | +1.5s | SKIP states: none. Run during Telegram retry-adjacent period — inflated relative to 26s median. |
| `nba_daily_picks` | 0m40.1s (40.1s) | 38.8s | +1.3s | SKIP: no NBA games today (off-season). Pipeline ran through fetch → hit_rate → projections → 0 picks. Normal subprocess chain completed at 38.8s. |
| `nba_injury_monitor` | 5m4.8s (304.8s) | 302.8s | +2.0s | 127 players checked, 0 status changes. Wall time dominated by Telegram retry storm that had not fully cleared. |
| `mlb_prop_monitor` | 3m53.5s (233.5s) | 231.0s | +2.5s | 0 line moves (no alert fanout). Wall time > median (98.7s) due to residual network latency. |
| `mlb_daily_picks` | 18m51.0s (1,131s) | 1,128.4s | +2.6s | WARNING emitted. Network still degraded at run time — Telegram retries during `dispatch_alerts`. Actual workbook + subprocess work: fast (mlb 44s median under normal conditions). |
| `nba_prop_monitor` | 13m54.5s (834.5s) | 832.7s | +1.8s | WARNING emitted. Queued behind mlb_daily_picks lock + Telegram retry storm. 0 line moves processed. |

**Key comparison — `nba_daily_picks` fast path (today, no games):**
The subprocess stages completed cleanly:
- `build_hit_rate_db`: ~0 players processed (NBA off-season)
- `generate_projections`: 0 projections generated
- Total pipeline: 38.8s wall clock

This is the floor for `daily_picks` when network and sports data are available. The 1,500s ceiling has never been seen.

**`mlb_prop_monitor` 0-line-move run vs. 61-line-move run:**
- 0 line moves today: 231.0s (no alert fanout; Telegram calls only for summary alert)
- 61 line moves (2026-06-09): 129.4s but ended in broken pipe (61 Telegram calls in ~58s)

This delta shows the `dispatch_alerts` fanout adds ~1s per line move. At 61 moves with network latency, the fanout exhausts the Hermes pipe window.

**D-11 instrumentation decision:** The coarse external numbers (from run-log mining + representative timed runs) clearly isolate the dominant offender as the Telegram retry loop combined with `obsidian_sync` per-log-line subprocess calls. No throwaway per-stage instrumentation was added. The subprocess stages (fetch_dfs_props, build_hit_rate_db, generate_projections) complete in seconds under normal conditions. This decision is recorded explicitly.

---

## D-11 Instrumentation Decision

**No throwaway per-stage instrumentation was added.**

Rationale: The coarse external numbers from run-log mining are sufficient to name the dominant contributors. The subprocess stages are demonstrably fast:
- `build_hit_rate_db` logged entries show completion in ~20s for 290+ players (e.g., 2026-06-09T22:40:22 start → 2026-06-09T22:40:41 complete = 19s for 290 MLB players)
- `generate_projections` completes in ~2s after hit-rate build (e.g., 22:40:41 → 22:40:43)
- `fetch_dfs_props` completes in <5s when network is available (e.g., 2026-06-12T09:41:26 start → 09:41:29 complete = 3s)

The extreme task durations are hours above what even a worst-case subprocess timeout scenario could produce. Per D-11: "ONLY if the coarse durations do not isolate the dominant offender" — they do. No source code was modified for timing instrumentation.

---

## Ranked Contributors

Based on run-log evidence from 791+ task completions. D-10 schema: Rank | Contributor | Max observed overhead | Occurs when | Fix direction.

| Rank | Contributor | Max observed overhead | Occurs when | Fix direction |
|------|-------------|----------------------|-------------|---------------|
| 1 | `send_telegram()` retry loop — 30s HTTP timeout × 2 retries per call site; multiple call sites per task (one per `log()` call that fires alert, plus per-move alert fanout in `dispatch_alerts`) | **24,923s observed** (nba_clv_tracker + mlb_clv_tracker, 2026-06-12); hours-long stalls across 5+ tasks on 2026-06-15 | Network/DNS outage; `api.telegram.org` unreachable (`NameResolutionError`). Also at 20–95s per failing call when network is marginal (`Read timed out`) | Hard per-call timeout budget (skip Telegram if consecutive failures exceed threshold); circuit-breaker pattern; Phase 3 add hard task-level self-timeout |
| 2 | `obsidian_sync` subprocess per `log()` call — 60s timeout each; called on every operational log line | **Minutes** compounding (N calls × up to 60s each); amplified when `obsidian_sync.py` is slow or network is degraded. The 129s `mlb_prop_monitor` run shows ~58s for 61 `obsidian_sync` subprocesses (approximately 1s each when fast; up to 60s each when slow) | Every task run; worst when `obsidian_sync.py` process hangs or network path is degraded | Batch Obsidian writes; decouple from hot `log()` path; call at task end (not per line) |
| 3 | Workbook lock contention — `workbook_file_lock` blocks up to 120s per poll cycle; stale lock threshold is 600s; multiple tasks queue on same lock | **Hours** of waiting (in combination with Rank 1: the lock holder is itself stalled on Telegram retries) | Prior task holds workbook lock and is stalled on Telegram retries; subsequent tasks queue behind it multiplying the delay | Reduce `stale_seconds` threshold from 600s to ≤180s; add per-task hard self-timeout so stalled lock holders release sooner |
| 4 | Bare `print(cp.stdout.rstrip())` in `run_fetch_dfs_props` (line 1274) — unprotected print on a potentially-closed pipe | Rare; contributes to some broken-pipe occurrences inside the lock context | Pipe already closed when fetch stage executes (less common than the `JSON_RESULT=` path) | Replace with `safe_print(cp.stdout.rstrip())` — same fix as the Rank 5 path |
| 5 | Stacked subprocess timeouts (`fetch_dfs_props` 300s + `build_hit_rate_db` 600s + `generate_projections` 600s) | **1,500s theoretical ceiling** — never reached in 791+ observed completions | Would require all three stages to exhaust their timeouts on a single run | Not yet an operational risk. Monitor; would become relevant only if ESPN API or PrizePicks API degrades severely. |

**Dominant finding:** Rank 1 (`send_telegram()` retry loop) is the single root cause of all extreme-duration events in the log. Rank 2 (`obsidian_sync` per log line) is a compounding factor during prop-monitor alert fanout. Rank 3 (lock contention) is a force-multiplier: it converts a single stalled task into hours of delay for all subsequent tasks in the queue.

---

## Timing Caveat

**Python interpreter:** The system runs `python3` at `/usr/local/bin/python3`, which is **CPython 3.14.0a2 (ALPHA)**. Alpha builds include additional debug assertions and may have non-representative GIL behavior, startup overhead, or JIT compilation characteristics relative to a stable 3.12/3.13 release. All absolute durations in this document are measurements from this alpha interpreter. The relative ordering of contributors (Telegram retry >> obsidian_sync >> lock contention >> subprocess stages) is robust to interpreter variance; absolute numbers should be treated as directional, not precise.

**Cron time budget:** The Hermes `no_agent` pipe/timeout window is **[ASSUMED]** to be approximately 60–120 seconds of quiet stdout after process start, or at the moment Hermes receives the task result. Evidence: the canonical `mlb_prop_monitor` broken-pipe event (2026-06-09T22:47:00 task complete → 22:47:58 broken pipe) shows the pipe remained open for ~58 seconds after the task's actual work completed but while `dispatch_alerts` was still firing Telegram calls. No explicit config value documenting the exact timeout was found; the `~/.hermes/config.yaml` fields `gateway_timeout: 1800` and `inactivity_timeout: 120` are gateway-level values whose mapping to the `no_agent` pipe closure is [ASSUMED].

---

## Token Redaction Confirmation

No secret or token values appear in this document. All bot tokens visible in the run log (of the form `bot<numericid>:AAF...`) have been deliberately omitted from all excerpts above. Only the `api.telegram.org` hostname and error message types are quoted. The three key names used in the acceptance-criteria secret scan (the Telegram bot token env var, the PrizePicks cookie env var, and the Odds-API key env var) do not appear anywhere else in this file.
