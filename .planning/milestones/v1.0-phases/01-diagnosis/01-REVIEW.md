---
phase: 01-diagnosis
reviewed: 2026-06-15T00:00:00Z
depth: standard
files_reviewed: 3
files_reviewed_list:
  - scripts/repro_broken_pipe.py
  - scripts/sports_system_runner.py
  - .gitignore
findings:
  critical: 0
  warning: 4
  info: 4
  total: 8
status: issues_found
---

# Phase 01: Code Review Report

**Reviewed:** 2026-06-15
**Depth:** standard
**Files Reviewed:** 3
**Status:** issues_found

## Summary

This phase brings `scripts/sports_system_runner.py` under version control and adds two
diagnostic artifacts for the recurring `[Errno 32] Broken pipe` failure: a new
deterministic repro script (`scripts/repro_broken_pipe.py`) and an additive
traceback dump in `main()`'s top-level `except` block. The review was scoped to the
phase changes only: the new repro file in full, the `main()` except-block
instrumentation (`sports_system_runner.py:5636-5649`), and `.gitignore`. The bulk
of the ~5,650-line runner is pre-existing and out of scope.

No BLOCKER-tier defects were found. The additive instrumentation is functionally
correct and the new code does not log raw env/secret *values* (the constraint
that mattered most). However, there are several WARNING-level issues worth fixing
before this is treated as the diagnostic baseline:

- The internal comment claims the traceback is written "never stdout," but the
  same traceback is simultaneously embedded in `err` and printed to stdout in the
  JSON_RESULT line — a self-contradiction that undermines the stated robustness goal.
- The repro's PASS/FAIL classification depends on the runner exiting with code 1,
  which the `finally` block can silently mask if a logging call in `finally` raises.
- The repro writes its evidence into the **production** run-log
  (`data/pnl/logs/run_log.txt`) and uses byte-offset scanning that is racy against
  concurrent writers.
- `.gitignore` does not ignore the `data/`, `outputs/`, `logs/`, `locks/`, or
  `__pycache__/` generated-artifact trees that the project explicitly treats as
  outputs, risking accidental commit of generated state (and the run-log this very
  phase writes to).

## Narrative Findings (AI reviewer)

### Warnings

#### WR-01: Traceback comment claims "never stdout" but the same traceback is printed to stdout

**File:** `scripts/sports_system_runner.py:5636-5648`
**Issue:** The new instrumentation comment on line 5638 reads
`# D-03/D-04: Additive traceback dump to robust file sink — never stdout.` The
intent is that the stack trace survives even when the cron stdout pipe is closed.
But line 5637 already builds `err` with `"traceback": traceback.format_exc()`, and
line 5648 does `print("JSON_RESULT=" + json.dumps(err, sort_keys=True))` — emitting
the full traceback **to stdout** anyway. So the traceback is not "never stdout"; it
is on stdout in the very same except path. This is both a documentation/code
contradiction and a partial defeat of the stated goal: in the broken-pipe scenario
the file-sink write (5640-5643) succeeds, but the JSON_RESULT print on 5648 will
itself raise `BrokenPipeError` (it is a bare `print`, not `safe_print`), so the
traceback that was put into `err` never actually reaches a consumer — making the
`err["traceback"]` field dead weight that only exists to bloat stdout when the pipe
*is* open. `traceback.format_exc()` is also evaluated 2-3 times in this path
(5637, 5642) for no benefit.
**Fix:** Pick one sink for the traceback. Either drop `"traceback"` from the `err`
dict (keep only the file-sink write) so the comment is truthful and the stack trace
lives solely in the run-log:
```python
err = {"status": "error", "task": args.task, "error": str(e)}
tb = traceback.format_exc()
try:
    with RUN_LOG.open("a") as _tb_file:
        _tb_file.write(f"[{now_iso()}] TRACEBACK task={args.task}:\n{tb}\n")
except Exception:
    pass
```
…or, if the JSON_RESULT traceback is intentional, correct the comment to say the
file sink is a *fallback* for the closed-pipe case rather than "never stdout".

#### WR-02: Repro PASS/FAIL logic is coupled to exit code 1, which the `finally` block can mask

**File:** `scripts/repro_broken_pipe.py:252-284` (depends on `sports_system_runner.py:5650-5654`)
**Issue:** The repro decides success by `returncode == 1 and new_signals > 0`
(line 252). The runner's `main()` returns 1 from the except block (5649), but the
`finally` block (5650-5654) calls `log(...)` twice. `log()` writes to `RUN_LOG`,
calls `obsidian_sync` (subprocess), and `safe_print()`. If any unhandled exception
escapes the `finally` block (e.g. `RUN_LOG.open("a")` raising on a full/locked disk,
since `log()` has no try/except around its file write at line 206), the process
exits with a traceback to stderr and a non-1 code — and the repro silently
misclassifies a genuine broken-pipe reproduction as `FAIL (unexpected)` (line 278).
The repro's own docstring (lines 78-84) acknowledges the except+finally path is
fragile and network-dependent, yet the classifier treats exit code as authoritative.
**Fix:** Make `new_signals > 0` the primary success signal and treat the exit code
as secondary corroboration, since the run-log evidence is what actually proves the
broken pipe was caught:
```python
if new_signals > 0:
    print(f"PASS: BrokenPipeError reproduced (returncode={returncode}, "
          f"new_signals={new_signals})")
    return 0
if returncode == 0 and new_signals == 0:
    return 2  # fix appears applied
return 2      # not reproduced as broken-pipe
```

#### WR-03: Repro writes evidence into the production run-log and scans it with a racy byte offset

**File:** `scripts/repro_broken_pipe.py:118,143-165,195`
**Issue:** `RUN_LOG` points at the real shared log
`<repo-root>/data/pnl/logs/run_log.txt` (line 118). `count_new_log_signals`
snapshots `st_size` before the run (line 195) and `seek()`s to that offset
afterward (line 157). Two correctness hazards: (1) The repro both *triggers* a real
runner task and *pollutes the production operational log* with deliberately-induced
TRACEBACK/ERROR lines that look identical to genuine production failures — a future
operator grepping the run-log for failures will see synthetic entries. (2) The
byte-offset diff is racy: the runner mirrors every `log()` line through
`obsidian_sync` and `safe_print`, and if any *other* process (a scheduled cron
task) appends to the same run-log between the size snapshot and the scan, the
offset arithmetic counts unrelated lines or, if the log is rotated/truncated,
`seek(before_size)` lands past EOF and silently returns 0 signals (misclassified as
"not reproduced"). The constraint "must not change... a real-money system in active
daily use" makes writing synthetic failure rows into the live log undesirable.
**Fix:** Point the repro at an isolated log path via env override or a temp file,
and assert against that instead of the shared production log. If the production
sink must be exercised, scan for a unique per-run nonce token rather than a raw
byte offset so concurrent writers and rotation cannot corrupt the count:
```python
import uuid
run_nonce = uuid.uuid4().hex
# pass nonce into the runner env so its TRACEBACK line includes it, then:
new_content = RUN_LOG.read_text(errors="replace")
signals = new_content.count(f"TRACEBACK task=... {run_nonce}")
```

#### WR-04: `.gitignore` omits the generated-artifact trees, risking commit of run-logs, locks, and pycache

**File:** `.gitignore:1-4`
**Issue:** `.gitignore` only excludes `.env`, `*.env`, and two secret research-file
globs. CLAUDE.md explicitly states `data/` and `outputs/` "hold generated
artifacts... treat them as outputs," and the working tree already shows untracked
`data/`, `outputs/`, `logs/`, `locks/`, and `scripts/__pycache__/`. None are
ignored. This phase's own instrumentation writes synthetic TRACEBACK lines into
`data/pnl/logs/run_log.txt`; without a gitignore entry, a future `git add -A` will
commit the live operational log (which can contain Telegram error text and pipeline
state), the `fcntl` lock file, and `.pyc` bytecode. That is both a repo-hygiene and
a potential data-exposure problem (the run-log can contain `str(e)` exception text
from third-party libraries).
**Fix:** Add the generated trees to `.gitignore`:
```gitignore
.env
*.env
data/research/*secret*
data/research/*key*

# Generated artifacts (outputs, not source)
data/
outputs/
logs/
locks/
__pycache__/
*.pyc
```
If selected `data/` subpaths must be tracked (e.g. `data/nxls_schema.txt`), add
negation entries (`!data/nxls_schema.txt`) rather than tracking the whole tree.

### Info

#### IN-01: Redundant `except Exception` branch in `send_telegram` reachable only by the new error path

**File:** `scripts/sports_system_runner.py:252-255`
**Issue:** (Adjacent to the changed code, exercised by the new except block's
`send_telegram` call at 5647.) `send_telegram` has two back-to-back handlers —
`except requests.exceptions.RequestException` (252) then `except Exception` (254) —
whose bodies are byte-for-byte identical. The first is fully subsumed by the
second. This is harmless but is dead-ish duplication that the new failure path now
depends on.
**Fix:** Collapse to a single `except Exception as e:` handler.

#### IN-02: Repro hardcodes runner line numbers in docstrings that will drift

**File:** `scripts/repro_broken_pipe.py:22,35,63,72,131` (and others)
**Issue:** The docstring and comments cite exact runner line numbers
(`line 5634`, `line 5621`, `line 5634/5640`). The runner is edited in subsequent
phases of this milestone; these references will silently become wrong and mislead
the next reader. As a Phase-3 regression seed (per the file header), the script will
outlive the current line layout.
**Fix:** Reference stable anchors (function names / sentinel strings) instead of
absolute line numbers, e.g. "the bare `print(\"JSON_RESULT=...\")` on the
success path of `main()`".

#### IN-03: Repro `_WAIT_TIMEOUT` magic number couples test timing to network failure budget

**File:** `scripts/repro_broken_pipe.py:140`
**Issue:** `_WAIT_TIMEOUT = 240.0` is justified in a comment as covering
"obsidian_sync (60s) + send_telegram (65s) + finally obsidian_sync (60s)." These
sub-budgets are derived from runner-internal subprocess timeouts that this script
cannot see; if a future phase changes the `obsidian_sync` 60s timeout or
`send_telegram` retry count, this number becomes wrong and the repro produces
false `FAIL (infra)` timeouts (line 231). The value is a brittle cross-module
magic number.
**Fix:** Derive the timeout from a named constant, or set it generously high
(e.g. 600s, matching the runner's own max subprocess timeout) with a comment that
it is a ceiling rather than a tuned value, since the repro already kills the process
on timeout.

#### IN-04: `count_new_log_signals` swallows all read errors and returns 0, conflating "no signals" with "couldn't read"

**File:** `scripts/repro_broken_pipe.py:155-165`
**Issue:** The bare `except Exception: return 0` (164-165) means a permissions
error, encoding failure, or missing log file is indistinguishable from a legitimate
"zero broken-pipe signals" result. Combined with the exit-code classifier
(WR-02), an unreadable log silently produces a "not reproduced" verdict (exit 2)
rather than an infra-failure verdict (exit 1), masking a real test-harness problem.
**Fix:** Let the caller distinguish the two: return a sentinel (e.g. `-1`) or
re-raise as an infra failure, and have `main()` map an unreadable log to `return 1`
(infra) rather than `return 2` (not reproduced).

---

_Reviewed: 2026-06-15_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
