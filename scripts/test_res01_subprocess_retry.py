#!/usr/bin/env python3
"""
RES-01 regression test — _subprocess_run_with_retry re-runs exactly once on hard
failure, never retries on exit 0 (D-02), and propagates after the single re-run fails.

D-11 fault-injection-by-construction:
  This test FAILS on pre-Plan-01 code because:
  - No ``_subprocess_run_with_retry`` helper exists — run_fetch_dfs_props uses
    ``subprocess.run`` directly (one call, no retry), so patching ``subprocess.Popen``
    records 0 constructions (not 2) and test_subprocess_retry_on_nonzero_exit fails.

  This test PASSES on the post-Plan-01 runner because:
  - ``_subprocess_run_with_retry`` constructs ``subprocess.Popen`` (so the SIGALRM
    handler can kill the in-flight child via _current_subprocess).
  - On non-zero exit, the helper retries once (exactly 2 Popen constructions).
  - On exit 0, the helper returns immediately (exactly 1 Popen construction — D-02).
  - After two consecutive hard failures, the helper raises (propagates error).

Patch target: ``subprocess.Popen`` — the symbol the helper actually constructs.
Do NOT patch ``subprocess.run``; that symbol is bypassed by the helper.

Run from scripts/:
    python3 test_res01_subprocess_retry.py
    python3 -m pytest test_res01_subprocess_retry.py
"""
from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Load the runner via importlib so we can access module-level state directly.
# Canonical pattern from test_fix02_telegram_circuit_breaker.py.
# ---------------------------------------------------------------------------
SCRIPT: Path = Path(__file__).resolve().with_name("sports_system_runner.py")
spec = importlib.util.spec_from_file_location("sports_system_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
assert spec and spec.loader
spec.loader.exec_module(runner)  # type: ignore[union-attr]


class _FakePopen:
    """Minimal stand-in for subprocess.Popen.

    Exposes exactly the attributes that ``_subprocess_run_with_retry`` reads:
      .wait(timeout=...)  — returns returncode (or raises TimeoutExpired for the timeout path)
      .returncode         — integer exit code
      .stdout             — file-like object whose .read() returns a string (text=True mode)
      .stderr             — file-like object whose .read() returns a string (text=True mode)
      .kill()             — no-op
    """

    def __init__(self, returncode: int, *, raise_timeout: bool = False) -> None:
        self.returncode = returncode
        self._raise_timeout = raise_timeout
        # The helper calls proc.stdout.read() after proc.wait(); text=True means str.
        self.stdout = io.StringIO("")
        self.stderr = io.StringIO("")

    def wait(self, timeout: float | None = None) -> int:
        if self._raise_timeout:
            raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout or 0)
        return self.returncode

    def communicate(self, timeout: float | None = None) -> tuple[str, str]:
        # Mirrors the real Popen.communicate the helper drains with: returns
        # (stdout, stderr) and raises TimeoutExpired on the timeout path.
        if self._raise_timeout:
            raise subprocess.TimeoutExpired(cmd="fake", timeout=timeout or 0)
        return self.stdout.read(), self.stderr.read()

    def kill(self) -> None:
        pass


class TestRes01SubprocessRetry(unittest.TestCase):
    """RES-01 regression: subprocess stage re-runs exactly once on hard failure."""

    def setUp(self) -> None:
        """Capture log output and stub out time.sleep so backoff does not slow tests."""
        self._log_lines: list[str] = []
        self._original_log = runner.log

        def _capture_log(msg: str) -> None:
            self._log_lines.append(msg)

        runner.log = _capture_log

        # Patch time.sleep so the 5-second retry backoff does not stall the suite.
        self._sleep_patcher = patch("time.sleep")
        self._mock_sleep = self._sleep_patcher.start()

    def tearDown(self) -> None:
        """Restore runner.log and time.sleep to original state."""
        runner.log = self._original_log
        self._sleep_patcher.stop()

    # ------------------------------------------------------------------
    # Test 1: non-zero exit on first attempt → retry → exit 0 on second
    # ------------------------------------------------------------------
    def test_subprocess_retry_on_nonzero_exit(self) -> None:
        """First Popen exits 1, second exits 0 → exactly 2 Popen constructions.

        Pre-fix: subprocess.run called once (no retry helper) → patch records 0
        Popen constructions → call_count == 1 (not 2) → assertion fails.
        Post-fix: helper constructs Popen twice (attempt 1 fails, attempt 2 succeeds).
        """
        call_count = 0

        def _fake_popen(cmd: list[str], *args: object, **kwargs: object) -> _FakePopen:
            nonlocal call_count
            call_count += 1
            # First call fails (exit 1); second call succeeds (exit 0).
            return _FakePopen(1 if call_count == 1 else 0)

        with patch("subprocess.Popen", side_effect=_fake_popen):
            # Should complete without raising (second attempt exits 0).
            runner.run_fetch_dfs_props("nba")

        self.assertEqual(
            call_count,
            2,
            f"RES-01 regression: expected exactly 2 Popen constructions (1 failure + 1 retry) "
            f"but got {call_count}. Pre-fix runner uses subprocess.run directly so Popen is "
            f"never constructed by the stage function.",
        )

    # ------------------------------------------------------------------
    # Test 2: exit 0 → no retry (D-02: empty board is not a failure)
    # ------------------------------------------------------------------
    def test_no_retry_on_clean_exit(self) -> None:
        """Exit 0 (including empty board) is NOT retried — exactly 1 Popen construction.

        D-02: a quiet day with no games exits 0 with empty output. Re-running would
        waste a fetch slot. The helper must return immediately on exit 0.
        Pre-fix: N/A (run is the call; still 1 call). Post-fix: still exactly 1
        Popen construction — confirms the retry condition is ``returncode != 0``.
        """
        call_count = 0

        def _fake_popen(cmd: list[str], *args: object, **kwargs: object) -> _FakePopen:
            nonlocal call_count
            call_count += 1
            return _FakePopen(0)  # clean exit, empty board

        with patch("subprocess.Popen", side_effect=_fake_popen):
            runner.run_fetch_dfs_props("nba")

        self.assertEqual(
            call_count,
            1,
            f"RES-01 / D-02 regression: expected exactly 1 Popen construction on exit 0 "
            f"(empty board must not be retried) but got {call_count}.",
        )

    # ------------------------------------------------------------------
    # Test 3: two consecutive failures → stage raises/propagates
    # ------------------------------------------------------------------
    def test_after_one_retry_fails_propagates(self) -> None:
        """Two consecutive hard failures → stage raises RuntimeError (propagates).

        Pre-fix: no retry helper — subprocess.run raises immediately on the first
        hard failure (returncode != 0 triggers RuntimeError in the caller), but the
        Popen patch means the real subprocess.run is not intercepted, so the assertion
        that ``assertRaises`` fires would still hold. The distinguishing test is
        test_subprocess_retry_on_nonzero_exit (call_count == 2) which fails pre-fix.
        Post-fix: helper exhausts 1 re-run; run_fetch_dfs_props sees final returncode
        != 0 and raises RuntimeError with the 'fetch_dfs_props failed' message.
        """
        def _fake_popen(cmd: list[str], *args: object, **kwargs: object) -> _FakePopen:
            return _FakePopen(1)  # always fail

        with patch("subprocess.Popen", side_effect=_fake_popen):
            with self.assertRaises(
                (RuntimeError, Exception),
                msg=(
                    "RES-01 regression: stage did not raise after two consecutive hard failures. "
                    "The helper must propagate when both attempts return non-zero exit."
                ),
            ):
                runner.run_fetch_dfs_props("nba")


class TestRes01RealChild(unittest.TestCase):
    """WR-04: drive ``_subprocess_run_with_retry`` against a REAL child process.

    The fake-Popen tests above assert retry *counting* but cannot catch the two
    production defects the standard fake masks:
      - CR-01: call sites pass ``capture_output=True``, which real ``subprocess.Popen``
        rejects (``TypeError``). The fake discards all kwargs, so it never validates
        the signature.
      - CR-02: ``wait()``-then-``read()`` deadlocks once a healthy child fills the OS
        pipe buffer. The fake backs stdout with an empty ``io.StringIO``, so the
        pipe-buffer path is never exercised.
    These tests run the helper exactly as the daily-picks stages do (real interpreter
    child, ``capture_output=True, text=True``) so a regression to either defect fails
    loudly. They do not patch ``time.sleep`` because a healthy child exits 0 and never
    reaches the retry/backoff path.
    """

    def setUp(self) -> None:
        self._original_log = runner.log
        runner.log = lambda msg: None  # silence stage warnings

    def tearDown(self) -> None:
        runner.log = self._original_log

    def test_capture_output_against_real_popen(self) -> None:
        """capture_output=True must be honored against the real Popen (CR-01 guard)."""
        cp = runner._subprocess_run_with_retry(
            [sys.executable, "-c", "print('hello-res01')"],
            timeout=30,
            context="real-child capture",
            text=True,
            capture_output=True,
        )
        self.assertEqual(cp.returncode, 0)
        self.assertIn("hello-res01", cp.stdout)

    def test_large_stdout_does_not_deadlock(self) -> None:
        """A healthy child writing >64KB must not deadlock the drain (CR-02 guard)."""
        cp = runner._subprocess_run_with_retry(
            [sys.executable, "-c", "import sys; sys.stdout.write('x' * 200000)"],
            timeout=30,
            context="real-child large-stdout",
            text=True,
            capture_output=True,
        )
        self.assertEqual(cp.returncode, 0)
        self.assertEqual(len(cp.stdout), 200000)


if __name__ == "__main__":
    unittest.main()
