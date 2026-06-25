---
phase: 02-reliability-fixes-defect-removal
plan: "01"
subsystem: sports_system_runner
tags: [fix, reliability, broken-pipe, telegram, obsidian, circuit-breaker]
dependency_graph:
  requires: [01-diagnosis/DIAGNOSIS.md]
  provides: [safe-print-sweep, telegram-circuit-breaker, obsidian-decouple]
  affects: [scripts/sports_system_runner.py]
tech_stack:
  added: []
  patterns: [circuit-breaker, accumulator-reset, safe-print-wrapper]
key_files:
  created: []
  modified:
    - scripts/sports_system_runner.py
decisions:
  - "Use N=3 consecutive-failures threshold and timeout=10s per plan D-02 parameters"
  - "Place Obsidian summary sync in main() finally (not dispatch_alerts) so it fires on both success and failure paths"
  - "Log accumulator capped at last 50 lines for the summary excerpt — keeps notes lean"
  - "sports_run_log trigger completely removed; sports_run_summary is the single replacement"
metrics:
  duration: "~25 minutes"
  completed: "2026-06-20"
  tasks: 3
  files: 1
---

# Phase 02 Plan 01: Reliability Fixes — stdout/Telegram/Obsidian Summary

One-liner: Pipe-safe stdout via safe_print sweep + Telegram circuit-breaker (10s timeout, N=3, single suppressed-count log line) + Obsidian decoupled from per-log()-line to one task-end summary sync.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Sweep all bare stdout prints into safe_print | fca90b0 | sports_system_runner.py |
| 2 | Telegram circuit-breaker + short timeout | 6099898 | sports_system_runner.py |
| 3 | Decouple Obsidian from hot log() path | 540da68 | sports_system_runner.py |

## What Was Built

### Task 1 — safe_print sweep (FIX-01, D-05/D-07)

Five bare stdout `print()` calls replaced with `safe_print()`:
- `run_fetch_prizepicks`: `print(cp.stdout.rstrip())` → `safe_print(cp.stdout.rstrip())`
- `run_fetch_dfs_props`: `print(cp.stdout.rstrip())` → `safe_print(cp.stdout.rstrip())`
- `main()` --test-telegram path: `print("JSON_RESULT=" ...)` → `safe_print(...)`
- `main()` success path: `print("JSON_RESULT=" ...)` → `safe_print(...)`
- `main()` except path: `print("JSON_RESULT=" ...)` → `safe_print(...)`

The one permitted bare `print()` inside `safe_print` itself was left untouched. The two `print(..., file=sys.stderr)` calls were left untouched (stderr, not the broken-pipe surface). AST check confirms zero unswept bare stdout prints remain.

### Task 2 — Telegram circuit-breaker (FIX-02, D-02/D-03)

Added module-level `_telegram_breaker` dict: `{"consecutive_failures": 0, "tripped": False, "suppressed": 0}`.

Modified `send_telegram`:
- `timeout=30` → `timeout=10` (single short per-call timeout, no long 2x30s stall)
- At the top (after creds check): if `_telegram_breaker["tripped"]` increment `suppressed` and return `False` immediately — no network call
- On successful send: reset `consecutive_failures = 0`
- After retry loop exhausts: increment `consecutive_failures`; if `>= 3` and not already tripped, set `tripped = True` and write exactly ONE log line containing `"alerts suppressed — Telegram unreachable"` with the suppressed count — only on the False→True transition

Breaker resets at the top of `main()`'s `try` block (alongside `_task_log_lines.clear()`) so it is strictly per-invocation.

### Task 3 — Obsidian decouple (FIX-02, D-04)

Added module-level `_task_log_lines: list[str] = []` accumulator.

Modified `log()`:
- Removed the `try/except` block that called `obsidian_sync({"trigger": "sports_run_log", ...})` per line
- Added `_task_log_lines.append(line)` after the file write

Added single `sports_run_summary` obsidian_sync call in `main()`'s `finally` block:
- Fires on BOTH success and failure (task-end hook)
- Payload: task name, elapsed_s, log_excerpt (last 50 lines)
- Wrapped in `try/except Exception: pass` (never-crash invariant)
- `sports_run_log` trigger is completely gone (grep count = 0)

## Vault Section Confirmation (Task 3 Scope Check)

The seven retained obsidian_sync call sites each feed a distinct vault section:

| Call Site | Trigger | Vault Section |
|-----------|---------|---------------|
| `obsidian_create_daily_pick_note` (~line 635) | `{sport}_daily_picks` | Picks / Dashboard (daily pick note + active picks + sportsbook market check) |
| `obsidian_append_injury_changes` (~line 664) | `{sport}_injury_monitor` | Intel (injury status changes) |
| `obsidian_append_line_moves` (~line 686) | `{sport}_prop_monitor` | Intel (intraday line moves) |
| `obsidian_update_results_section` (~line 719) | `game_completion_monitor` | Picks / Results section update |
| `obsidian_update_bankroll_files` (~line 768) | `game_completion_monitor` | Dashboard / Bankroll.md + Home.md |
| `obsidian_update_player_research` (~line 827) | `check_results` | Research / Players (A-tier player notes) |
| `obsidian_create_weekly_recap` (~line 893) | `check_results` | Recaps / Weekly |

**Conclusion:** No vault section depended solely on the removed per-line `sports_run_log` sync. The line-210 call was raw operational log mirroring — useful for debugging but not the source of any Dashboard / Picks / Research / Recaps / Intel / Meta vault content. Removing it is safe. The new `sports_run_summary` sync at task-end captures the meaningful operational summary in a leaner form.

## Deviations from Plan

None — plan executed exactly as written.

The plan's `_task_log_lines` accumulator was added in Task 2's commit (alongside `_telegram_breaker`) as both module-level state dicts belong together. The accumulator was used and reset in Task 3.

## Verification Results

All task AST/behavioral verify commands passed:

1. `UNSWEPT_STDOUT_PRINTS= []` — zero bare stdout prints remain outside safe_print
2. `OK breaker trips and short-circuits` — breaker trips after 3 consecutive failures; tripped breaker returns in < 0.2s with no network call
3. `OK summary sync is in main finally, not dispatch_alerts, and log() has no per-line obsidian_sync`

Test suite: 120 tests passed (same as pre-edit baseline — no gate/pick/schema regression).

## Known Stubs

None. No placeholder values or unconnected data flows introduced.

## Threat Flags

None. No new network endpoints, auth paths, file access patterns, or schema changes introduced. The `_telegram_breaker` summary log line was verified to contain only an integer count + fixed text — no secrets, no `TELEGRAM_BOT_TOKEN`, no `chat_id`, no message bodies.

## Self-Check: PASSED

- scripts/sports_system_runner.py modified and committed ✓
- Commit fca90b0 exists ✓
- Commit 6099898 exists ✓
- Commit 540da68 exists ✓
- 120 tests passing ✓
- All AST/behavioral verify commands pass ✓
