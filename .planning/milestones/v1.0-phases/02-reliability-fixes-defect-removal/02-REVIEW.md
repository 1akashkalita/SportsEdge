---
phase: 02-reliability-fixes-defect-removal
reviewed: 2026-06-20T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - scripts/sports_system_runner.py
  - scripts/generate_projections.py
  - scripts/repro_broken_pipe.py
  - scripts/run_all_tasks.py
  - scripts/test_def01_no_duplicate_defs.py
  - scripts/test_def02_path_resolution.py
  - scripts/test_fix01_broken_pipe.py
  - scripts/test_fix02_telegram_circuit_breaker.py
findings:
  critical: 1
  warning: 4
  info: 3
  total: 8
status: issues_found
resolution:
  resolved:
    - "CR-01 — finally-block Obsidian sync switched to the implemented `sports_run_log` trigger; trigger-contract regression test added (test_cr01_obsidian_trigger_contract.py). Commit e693d02."
    - "WR-01 — real suppressed-alert count now logged in one greppable end-of-run line; misleading trip-time `(suppressed so far: 0)` removed. Commit 03ca318."
  deferred:
    - "WR-02 — repro nonce-scan concurrent ERROR misattribution (CI robustness)"
    - "WR-03 — FIX-02 timeout test mocks requests.post (timeout=10 not exercised)"
    - "WR-04 — run_all_tasks.py opt-in guard for live production tasks"
    - "INFO-01/02/03 — see body"
  verified: "18/18 targeted tests pass post-fix (cr01 contract, fix01, fix02, def01, def02)"
---

# Phase 2: Code Review Report

**Reviewed:** 2026-06-20
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

This review targets the Phase-2 reliability-hardening diff (`c217d45..HEAD`), not the pre-existing 5,650-line runner. Scope: FIX-01 (`safe_print` stdout sweep), FIX-02 (Telegram circuit-breaker + Obsidian decouple), DEF-01 (duplicate-def removal), DEF-02 (portable BASE path), the hardened repro harness, the new run-all harness, and four regression tests.

The mechanically-verifiable parts are sound: the `safe_print` sweep covers every stdout write surface (only two intentional `sys.stderr` prints remain); the JSON_RESULT contract is preserved; DEF-01 correctly removed the genuinely-dead shadowed definitions (the surviving defs at lines 5003/5397 are the active supersets, confirmed against `c217d45`); DEF-02 is portable and tested; and all 13 fast regression tests pass.

However, **the FIX-02 Obsidian decouple introduced a silent functional regression**: the new `sports_run_summary` trigger is not implemented in the canonical `obsidian_sync.py` handler, so every end-of-task sync is rejected and swallowed. The Obsidian run-log output — one of the system's four documented output surfaces — is now a complete no-op. This is masked by the (correct) never-crash `try/except`, so it will not alert the operator. The never-crash invariant is intact; the output is silently dropped. This is the central BLOCKER. Remaining findings are circuit-breaker observability, test-isolation races, and a leaked file handle.

## Critical Issues

### CR-01: `sports_run_summary` Obsidian trigger is unimplemented — vault run-log sync silently dropped for every task

**File:** `scripts/sports_system_runner.py:5614-5629`
**Issue:** FIX-02 replaced the per-`log()`-line `obsidian_sync({"trigger": "sports_run_log", ...})` call with a single end-of-task `obsidian_sync({"trigger": "sports_run_summary", ...})` in `main()`'s `finally`. But the canonical handler at `~/.hermes/skills/delegation/obsidian_sync/scripts/obsidian_sync.py` has **no branch for `sports_run_summary`** — its `sync()` dispatcher ends with `else: raise SyncError(f"unknown trigger: {trigger}")`. The old `sports_run_log` trigger *was* implemented (`sync_sports_run_log` → `Meta/RunLog.md`); the new one is not.

Verified empirically:
```
$ python3 obsidian_sync.py --trigger sports_run_summary --payload '{...}'
{ "success": false, "errors": ["unknown trigger: sports_run_summary"] }   EXIT=1
```

Chain: handler exits 1 → runner's `obsidian_sync()` wrapper raises `RuntimeError("obsidian_sync failed for sports_run_summary: ...")` → the `finally` block's `except Exception: pass` swallows it. Net effect: **the Obsidian run-log/summary output is now 100% non-functional on every single task run, on both success and failure paths, with zero operator visibility.** This is exactly the "did removing per-line obsidian_sync drop vault content?" risk — and it dropped all of it, because the replacement trigger was never wired into the handler. No test covers the trigger contract, so it slipped through.

**Fix:** Either (a) add a `sports_run_summary` handler to the canonical `obsidian_sync.py` (preferred — keeps the leaner one-note-per-run design), or (b) if the handler is out of this phase's scope, revert the trigger name to the implemented `sports_run_log` and send the summary as a single line so existing `Meta/RunLog.md` append logic still fires:
```python
obsidian_sync({
    "trigger": "sports_run_log",
    "date": today_str(),
    "data": {"line": f"[{task_name}] completed in {round(elapsed,1)}s\n" + log_excerpt},
})
```
Whichever path is chosen, add a regression test that asserts the runner's chosen trigger string is one the handler accepts (e.g., import the handler's accepted-trigger set, or invoke the handler subprocess and assert `success: true`), so a trigger-name drift cannot silently disable vault output again.

## Warnings

### WR-01: Circuit-breaker trip message always reports "suppressed so far: 0" and the final suppressed count is never logged

**File:** `scripts/sports_system_runner.py:248, 270-272`
**Issue:** `suppressed` is only incremented at line 248, which runs *after* `tripped` is already `True`. The trip itself happens at lines 270-272, at which point no call has yet been suppressed, so `_telegram_breaker['suppressed']` is still `0`. The trip log line therefore *always* reads `suppressed so far: 0`, making the interpolated counter useless. Worse, the `suppressed` total is never logged again after the run — there is no end-of-run summary that reports how many alerts the breaker actually dropped, so the field is effectively write-only dead state. An operator cannot tell from the logs whether 1 or 50 alerts were silently suppressed.
**Fix:** Drop the misleading `suppressed` interpolation from the trip message (it is structurally always 0), and log the final suppressed total once per run. In `main()`'s `finally` (or after `dispatch_alerts`), add:
```python
if _telegram_breaker["suppressed"]:
    log(f"Telegram breaker suppressed {_telegram_breaker['suppressed']} alert(s) this run")
```

### WR-02: Nonce-fence log scan still attributes concurrent-process signals to the repro run

**File:** `scripts/repro_broken_pipe.py:131-150`, `scripts/test_fix01_broken_pipe.py:72-93`
**Issue:** The "WR-03 hardening" replaced a byte-offset snapshot with a nonce fence, which correctly fixes the *start-offset* race. But the scan still counts every `"Broken pipe"` / `"ERROR task="` / `"TRACEBACK task="` occurrence in *all* log content after the fence — `run_log.txt` is the shared production log written by every runner invocation. If a real cron task (e.g., `nba_daily_picks`) legitimately fails and writes `ERROR task=` to the log while the repro/test is running, those lines appear after the fence and are falsely attributed to the repro, flipping a genuine PASS into a spurious `FAIL (regression)`. The nonce isolates *when* but not *whose*. The docstring claims this "removes the byte-offset race" but overstates the isolation achieved.
**Fix:** Write to an isolated temp log for the repro subprocess (point the runner at a per-run `RUN_LOG` via env/arg if supported), or tighten the scan to only count signal lines that also reference `task=verify` (the repro's own task) so unrelated concurrent failures are excluded. At minimum, document the residual race so a flaky CI result is correctly diagnosed.

### WR-03: FIX-02 circuit-breaker test never exercises the real 10s network timeout it claims to bound

**File:** `scripts/test_fix02_telegram_circuit_breaker.py:81-109`
**Issue:** `test_breaker_trips_after_n_failures` patches `requests.post` with `side_effect=ConnectionError`, so each attempt raises *instantly* — the `timeout=10` path is never executed. The test's `< 30s` wall-clock assertion is satisfied almost entirely by the three real `time.sleep(5)` inter-retry sleeps (~15s), not by any timeout behavior. The docstring asserts the test "proves the timeout+breaker combination is bounded," but the actual `requests.post(..., timeout=10)` value is untested — a regression that changed `timeout=10` back to `timeout=30` (or removed it) would still pass this test, because the mock bypasses the timeout entirely. The real worst case before trip is ~75s (3 calls × [2 × 10s timeout + 5s sleep]), which exceeds the 90s slow-run warning threshold for any task that fires ≥1 alert while Telegram is down.
**Fix:** Add a test that asserts the literal timeout argument passed to `requests.post` is `10` (capture call kwargs via the mock), e.g.:
```python
with patch.object(requests, "post", side_effect=ConnectionError("x")) as m:
    runner.send_telegram("t")
assert all(c.kwargs.get("timeout") == 10 for c in m.call_args_list)
```
This makes the bound a contract the mock cannot accidentally satisfy.

### WR-04: `run_all_tasks.py` invokes real production tasks with real side effects and no `--dry-run` guard

**File:** `scripts/run_all_tasks.py:7-12, 44-56, 94-96`
**Issue:** The harness runs all 11 *real* tasks, including `nba_daily_picks`/`mlb_daily_picks`, which perform live DFS/Odds-API fetches, consume rate-limited API credits, send real operator Telegram alerts, and mutate production workbooks. The only safeguard is a docstring "OPERATIONAL CAUTION." A run during a trading window will fire spurious operator alerts and burn paid Odds-API credits. For a real-money system intended to seed CI, an accidental invocation is a non-trivial cost. There is no flag, env-guard, or confirmation prompt to prevent it, and the harness does not honor any "safe mode."
**Fix:** Add an explicit opt-in guard before running side-effecting tasks, e.g. require `RUN_ALL_TASKS_CONFIRM=1` in the environment or a `--i-understand-this-hits-production` flag, and/or split the task list into a default-safe subset (`verify`, monitors that SKIP cleanly) vs. an explicit `--include-daily-picks`. At minimum, abort early with a clear message unless the operator confirms.

## Info

### IN-01: `safe_print` BrokenPipeError fallback leaks a file handle and permanently mutates global `sys.stdout`

**File:** `scripts/sports_system_runner.py:200-208`
**Issue:** On EPIPE, `safe_print` does `sys.stdout = open(os.devnull, "w")` — opening a file that is never explicitly closed and reassigning the process-global stream. In practice the pipe closes once near process exit, so the leaked handle is reclaimed at exit and the impact is negligible. Flagged for completeness since this is the core defensive primitive.
**Fix:** Acceptable as-is for a short-lived cron process. If hardening further, guard the reassignment so it happens at most once and reference a module-level devnull handle rather than reopening.

### IN-02: Docstring/comment line-number references drift from actual source lines

**File:** `scripts/repro_broken_pipe.py` (refs to `5593`/`5607`), `scripts/test_fix01_broken_pipe.py:6,104` (refs to `5634`)
**Issue:** The repro docstrings now cite `sports_system_runner.py:5593`/`5607`, while the actual success-path `safe_print("JSON_RESULT=...")` is at line 5593 and the `--test-telegram` path at 5575 — close but already drifting; `test_fix01_broken_pipe.py` still references the stale pre-fix line `5634`. These comments will rot on the next edit to the 5,600-line runner and mislead future debugging.
**Fix:** Reference the function and sentinel by name (`the safe_print("JSON_RESULT=...") in main()'s try block`) rather than brittle line numbers, or drop the numbers entirely.

### IN-03: `generate_projections.py` newly tracked — large pre-existing body entered review scope but is out of Phase-2 change set

**File:** `scripts/generate_projections.py:24` (BASE) and full file
**Issue:** Per the phase scope, only the `BASE = Path.home() / "sports_picks"` line + docstring (DEF-02) is a Phase-2 change; the other 570 lines are pre-existing logic that newly entered git tracking. DEF-02 itself is correct and well-tested (`test_def02_path_resolution.py`, 5 assertions, all passing). Noting that the pre-existing projection math was not adversarially reviewed here because it is out of scope, and two known stale projection-math test failures in `test_generate_projections.py` are explicitly out of scope per the phase context.
**Fix:** None required for Phase 2. Recommend a dedicated review pass on `generate_projections.py` logic before relying on it, since this is the first time it is under version control.

---

_Reviewed: 2026-06-20_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
