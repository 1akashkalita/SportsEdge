# Phase 2 Regression Test Audit — D-10

**Audit date:** 2026-06-21
**Auditor:** Phase-3 Plan-03 executor
**Scope:** All four Phase-2 regression test files; confirm fail-before / pass-after rigor (D-10)
**Method:** Read each test file, document the specific fail-before mechanism, then run the
four tests against the current post-fix runner and record the result.

---

## Per-Test Fail-Before / Pass-After Table

| Test file | Phase-2 fix | Fail-before mechanism (specific assertion/injection) | Passes-after pytest result | Gap? |
|-----------|-------------|------------------------------------------------------|---------------------------|------|
| `test_fix01_broken_pipe.py` | FIX-01: `safe_print()` sweep — replaced bare `print("JSON_RESULT=...")` in `main()` with `safe_print()` which absorbs BrokenPipeError | Spawns the runner with stdout piped; reader thread closes pipe at the "verification complete" sentinel. Pre-fix: `print("JSON_RESULT=...")` raises BrokenPipeError → main()'s except block fires `send_telegram("TASK FAILED")` and exits 1. Test asserts `returncode == 0` and zero broken-pipe signals in log → RED pre-fix (both assertions fail). Post-fix: `safe_print()` absorbs EPIPE → runner exits 0 with zero signals → PASS. | PASSED (1 test, 14 total with siblings) | None — WR-03 nonce-fence hardening applied; see WR-03 section below |
| `test_fix02_telegram_circuit_breaker.py` | FIX-02: Telegram circuit-breaker (`_telegram_breaker` dict + trip threshold) — added bounded 10-second timeout per retry and a 3-failure trip threshold that short-circuits subsequent calls | Loads runner via importlib; patches `requests.post` with ConnectionError side-effect; calls `send_telegram()` 5 times and asserts: (1) `_telegram_breaker["tripped"]` is True, (2) all 5 calls complete in < 30 s, (3) a log line containing "alerts suppressed" or "unreachable" was written. Pre-fix: no `_telegram_breaker` attribute → AttributeError on attribute access; or infinite retry stall > 30 s. Test (1) raises AttributeError → RED; test (2) would stall > 30 s → RED. Post-fix: breaker trips after 3 failures, 5 calls complete in < 10 s total → PASS. | PASSED (3 tests) | None |
| `test_def01_no_duplicate_defs.py` | DEF-01: Remove duplicate `injury_monitor` and `clv_tracker` definitions — the pre-fix runner had two `def` statements for each; Python uses the last, but the first (stub) definition was dead code causing confusion | Uses `ast.parse()` to walk the entire runner source and count `FunctionDef` nodes named `injury_monitor` and `clv_tracker`. Pre-fix: `names.count("injury_monitor") == 2` → `assertEqual(count, 1)` fails (2 != 1) → RED. Also asserts the surviving definitions call `espn_injury_rows`, `record_morning_clv_row`, `weekly_clv_summary` (proves the CORRECT definition was kept, not the stub). Post-fix: exactly 1 of each → PASS. | PASSED (5 tests) | None |
| `test_def02_path_resolution.py` | DEF-02: Replace hardcoded `Path("/Users/akashkalita/sports_picks")` in `generate_projections.py` with `Path.home() / "sports_picks"` | Reads `generate_projections.py` source text directly and asserts: (1) source does NOT contain the literal string `"akashkalita"`, (2) source does NOT contain `'Path("/Users'`, (3) `gp.BASE == Path.home() / "sports_picks"`, (4) `gp.BASE` is absolute and exists, (5) `str(gp.DATA).startswith(str(gp.BASE))`. Pre-fix: source contains `Path("/Users/akashkalita/sports_picks")` → `assertNotIn("akashkalita", source_text)` fails → RED. Post-fix: `Path.home() / "sports_picks"` in source → all assertions pass → PASS. | PASSED (5 tests) | None |

---

## pytest Pass Confirmation

Command run from `scripts/`:

```
python3 -m pytest test_fix01_broken_pipe.py test_fix02_telegram_circuit_breaker.py test_def01_no_duplicate_defs.py test_def02_path_resolution.py -v
```

Result:

```
collected 14 items

test_fix01_broken_pipe.py::TestFix01BrokenPipe::test_no_spurious_task_failed_after_pipe_close PASSED
test_fix02_telegram_circuit_breaker.py::TestFix02TelegramCircuitBreaker::test_breaker_tripped_suppresses_immediately PASSED
test_fix02_telegram_circuit_breaker.py::TestFix02TelegramCircuitBreaker::test_breaker_trips_after_n_failures PASSED
test_fix02_telegram_circuit_breaker.py::TestFix02TelegramCircuitBreaker::test_suppressed_count_logged PASSED
test_def01_no_duplicate_defs.py::TestDef01NoDuplicateDefs::test_ast_exactly_one_clv_tracker PASSED
test_def01_no_duplicate_defs.py::TestDef01NoDuplicateDefs::test_ast_exactly_one_injury_monitor PASSED
test_def01_no_duplicate_defs.py::TestDef01NoDuplicateDefs::test_run_task_dispatch_resolves_injury_and_clv_without_error PASSED
test_def01_no_duplicate_defs.py::TestDef01NoDuplicateDefs::test_surviving_clv_tracker_is_superset_implementation PASSED
test_def01_no_duplicate_defs.py::TestDef01NoDuplicateDefs::test_surviving_injury_monitor_is_superset_implementation PASSED
test_def02_path_resolution.py::TestDef02PathResolution::test_base_equals_home_sports_picks PASSED
test_def02_path_resolution.py::TestDef02PathResolution::test_base_is_absolute_and_exists PASSED
test_def02_path_resolution.py::TestDef02PathResolution::test_data_derives_from_base PASSED
test_def02_path_resolution.py::TestDef02PathResolution::test_source_does_not_contain_hardcoded_username PASSED
test_def02_path_resolution.py::TestDef02PathResolution::test_source_has_no_hardcoded_users_path PASSED

14 passed in 58.79s
```

---

## WR-03 Status — Nonce-Fence Hardening

**WR-03** addresses test pollution of the shared production `run_log.txt`.

**`repro_broken_pipe.py`** (the original broken-pipe reproduction script): confirmed to implement
nonce-fence isolation (lines 75-132 of the file). Key implementation:
- Generates `uuid.uuid4().hex` nonce before spawning
- Appends a fence line to `run_log.txt` containing the nonce
- After the subprocess exits, reads `run_log.txt`, finds the fence position, and counts
  signal occurrences ONLY in the post-fence content
- Returns `INFRA_FAILURE (-1)` sentinel when log is unreadable (not "zero signals")

**`test_fix01_broken_pipe.py`** (Phase-2 regression test): confirmed to implement the same
nonce-fence pattern (lines 72-93, 111-119). Uses `_count_nonce_signals(nonce)` helper that
returns `_INFRA_FAILURE` for infra failures, preventing false-negative log assertions.

**Conclusion:** Both files already have WR-03 hardening applied. No action required.

---

## Gap Analysis

| Potential gap | Status |
|---------------|--------|
| `test_fix01` fails pre-fix without _task_result guard (pre-safe_print code base) | **No gap.** The pre-safe_print runner's bare `print("JSON_RESULT=")` raises BrokenPipeError directly into main()'s except block → TASK FAILED + exit 1. `test_fix01` asserts `returncode == 0` → RED pre-fix, GREEN post-fix. |
| `test_fix02` could pass on pre-fix runner if `send_telegram` never raises AttributeError | **No gap.** Pre-fix runner has no `_telegram_breaker` dict; accessing `runner._telegram_breaker["tripped"]` in `test_breaker_trips_after_n_failures` raises `AttributeError` → test RED. Even if attribute access were removed, no-breaker 5 forced failures × retries > 30 s → `assertLess(elapsed, 30.0)` RED. |
| `test_def01` could pass if AST walk somehow found exactly 1 def on pre-fix code | **No gap.** Pre-fix runner had 2 `def injury_monitor` and 2 `def clv_tracker` entries (confirmed in CLAUDE.md: "Duplicate injury_monitor and clv_tracker definitions: Two definitions of each exist in the runner at lines 3610/5049"). AST walk counts 2 → `assertEqual(count, 1)` fails → RED. |
| `test_def02` uses machine-specific path check; might pass if PATH.home() contains "akashkalita" | **No gap.** The test asserts the SOURCE CODE does not contain `"akashkalita"` — not the runtime path. Pre-fix source had `Path("/Users/akashkalita/sports_picks")` hardcoded → `assertNotIn("akashkalita", source_text)` fails → RED regardless of runtime user. |

**Conclusion: No gaps found.** All four Phase-2 regression tests have genuine fail-before /
pass-after rigor. The specific assertion or injection in each test is directly tied to the
pre-fix behavior, and the post-fix code satisfies each assertion.

---

## Phase-2 Test Modification Confirmation

No Phase-2 test files were modified during this audit. All changes in Plan 03 are limited to:
- `scripts/test_res02_pipe_reclassify.py` (new file — Phase-3)
- `.planning/phases/03-resilience/03-PHASE2-AUDIT.md` (this document)

---

## Full-Suite Regression Sweep

*This section is appended by Task 3 after the full suite run.*
