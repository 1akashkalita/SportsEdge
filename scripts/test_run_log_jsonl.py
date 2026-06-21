#!/usr/bin/env python3
"""OBS-01 regression test: run_log.jsonl structured record shape and status derivation.

RED test — written before append_run_record / RUN_LOG_JSONL exist in the runner.
Will fail (AttributeError) until Tasks 2 and 3 land.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

MOD_PATH = SCRIPT_DIR / "sports_system_runner.py"
spec = importlib.util.spec_from_file_location("sports_system_runner", MOD_PATH)
runner = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
assert spec and spec.loader
spec.loader.exec_module(runner)  # type: ignore[union-attr]
# Stub side-effectful module-level calls that happen at import time.
runner.load_suppressed_edge_types = lambda: {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read all non-empty lines from a JSONL file and parse each as JSON."""
    records = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if line:
            records.append(json.loads(line))
    return records


CORE_KEYS = {"task", "status", "duration_s", "error", "timestamp", "exit_code", "sport"}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestAppendRunRecord(unittest.TestCase):
    """Unit tests for append_run_record() helper (OBS-01, D-02)."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = runner.RUN_LOG_JSONL
        # Redirect the module-level constant to a temp file so we never touch
        # the real data/pnl/logs/run_log.jsonl during tests.
        runner.RUN_LOG_JSONL = Path(self._tmpdir.name) / "run_log.jsonl"

    def tearDown(self) -> None:
        runner.RUN_LOG_JSONL = self._orig_path
        self._tmpdir.cleanup()

    def test_writes_valid_json_line(self) -> None:
        """append_run_record writes one valid-JSON line that round-trips."""
        record = {
            "task": "nba_daily_picks",
            "status": "ok",
            "duration_s": 12.3,
            "error": None,
            "timestamp": "2026-06-21T08:00:00+00:00",
            "exit_code": 0,
            "sport": "nba",
        }
        runner.append_run_record(record)
        records = _load_jsonl(runner.RUN_LOG_JSONL)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0], record)

    def test_append_only_two_calls_two_lines(self) -> None:
        """Two append_run_record() calls produce two distinct lines (append-only)."""
        r1 = {"task": "nba_daily_picks", "status": "ok", "duration_s": 5.0,
               "error": None, "timestamp": "2026-06-21T08:00:00+00:00",
               "exit_code": 0, "sport": "nba"}
        r2 = {"task": "mlb_prop_monitor", "status": "error", "duration_s": 3.1,
               "error": "boom", "timestamp": "2026-06-21T08:01:00+00:00",
               "exit_code": 1, "sport": "mlb"}
        runner.append_run_record(r1)
        runner.append_run_record(r2)
        records = _load_jsonl(runner.RUN_LOG_JSONL)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0], r1)
        self.assertEqual(records[1], r2)

    def test_defensive_no_raise_on_unwritable_dir(self) -> None:
        """append_run_record does not raise even if the target directory is unwritable."""
        runner.RUN_LOG_JSONL = Path("/nonexistent_dir/run_log.jsonl")
        # Must not raise:
        runner.append_run_record({"task": "verify", "status": "ok", "duration_s": 1.0,
                                   "error": None, "timestamp": "2026-06-21T08:00:00+00:00",
                                   "exit_code": 0, "sport": None})


class TestRecordShape(unittest.TestCase):
    """Tests for the Core+ record shape (D-02): all 7 fields present and correctly typed."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = runner.RUN_LOG_JSONL
        runner.RUN_LOG_JSONL = Path(self._tmpdir.name) / "run_log.jsonl"

    def tearDown(self) -> None:
        runner.RUN_LOG_JSONL = self._orig_path
        self._tmpdir.cleanup()

    def _run_main_stub(
        self,
        task: str,
        *,
        raise_exc: Exception | None = None,
        raise_timeout: bool = False,
    ) -> int:
        """Run main() with a patched run_task() and lockfile/fcntl bypassed."""
        import contextlib
        import fcntl as _fcntl

        def _noop_flock(fd: Any, op: Any) -> None:
            pass  # skip exclusive file lock in tests

        @contextlib.contextmanager
        def _fake_task_locks(task_name: str):  # type: ignore[misc]
            yield

        def _fake_run_task(task_name: str) -> dict[str, Any]:
            if raise_timeout:
                raise runner.TaskTimeoutError("fake timeout")
            if raise_exc is not None:
                raise raise_exc
            return {"status": "ok", "task": task_name}

        with (
            patch("sys.argv", ["sports_system_runner.py", "--task", task]),
            patch.object(_fcntl, "flock", _noop_flock),
            patch.object(runner, "run_task", _fake_run_task),
            patch.object(runner, "task_workbook_locks", _fake_task_locks),
            patch.object(runner, "dispatch_alerts", lambda t, r: None),
            patch.object(runner, "send_telegram", lambda *a, **k: True),
            patch.object(runner, "obsidian_sync", lambda *a, **k: None),
        ):
            return runner.main()

    def test_ok_record_shape(self) -> None:
        """A successful run emits status='ok', error=None, exit_code=0, all 7 keys."""
        self._run_main_stub("nba_daily_picks")
        records = _load_jsonl(runner.RUN_LOG_JSONL)
        self.assertGreater(len(records), 0)
        rec = records[-1]
        self.assertLessEqual(CORE_KEYS, set(rec.keys()), "Core+ keys missing from record")
        self.assertEqual(rec["status"], "ok")
        self.assertIsNone(rec["error"])
        self.assertEqual(rec["exit_code"], 0)
        self.assertEqual(rec["task"], "nba_daily_picks")
        self.assertEqual(rec["sport"], "nba")
        self.assertIsInstance(rec["duration_s"], (int, float))
        # timestamp must be a non-empty ISO string
        self.assertIsInstance(rec["timestamp"], str)
        self.assertTrue(rec["timestamp"])

    def test_error_record_shape(self) -> None:
        """A failed run emits status='error', non-None error, exit_code=1."""
        self._run_main_stub("mlb_daily_picks", raise_exc=RuntimeError("something broke"))
        records = _load_jsonl(runner.RUN_LOG_JSONL)
        self.assertGreater(len(records), 0)
        rec = records[-1]
        self.assertLessEqual(CORE_KEYS, set(rec.keys()))
        self.assertEqual(rec["status"], "error")
        self.assertIsNotNone(rec["error"])
        self.assertIn("something broke", rec["error"])
        self.assertEqual(rec["exit_code"], 1)
        self.assertEqual(rec["sport"], "mlb")

    def test_timeout_record_shape(self) -> None:
        """A timed-out run emits status='timeout', exit_code=1."""
        self._run_main_stub("nba_prop_monitor", raise_timeout=True)
        records = _load_jsonl(runner.RUN_LOG_JSONL)
        self.assertGreater(len(records), 0)
        rec = records[-1]
        self.assertLessEqual(CORE_KEYS, set(rec.keys()))
        self.assertEqual(rec["status"], "timeout")
        self.assertEqual(rec["exit_code"], 1)
        self.assertEqual(rec["sport"], "nba")


class TestSportDerivation(unittest.TestCase):
    """Tests for the sport-prefix derivation rule embedded in the record."""

    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._orig_path = runner.RUN_LOG_JSONL
        runner.RUN_LOG_JSONL = Path(self._tmpdir.name) / "run_log.jsonl"

    def tearDown(self) -> None:
        runner.RUN_LOG_JSONL = self._orig_path
        self._tmpdir.cleanup()

    def _emit_record_for_task(self, task: str) -> dict[str, Any]:
        import contextlib
        import fcntl as _fcntl

        @contextlib.contextmanager
        def _fake_task_locks(task_name: str):  # type: ignore[misc]
            yield

        def _fake_run_task(task_name: str) -> dict[str, Any]:
            return {"status": "ok", "task": task_name}

        with (
            patch("sys.argv", ["sports_system_runner.py", "--task", task]),
            patch.object(_fcntl, "flock", lambda *a, **k: None),
            patch.object(runner, "run_task", _fake_run_task),
            patch.object(runner, "task_workbook_locks", _fake_task_locks),
            patch.object(runner, "dispatch_alerts", lambda t, r: None),
            patch.object(runner, "send_telegram", lambda *a, **k: True),
            patch.object(runner, "obsidian_sync", lambda *a, **k: None),
        ):
            runner.main()
        records = _load_jsonl(runner.RUN_LOG_JSONL)
        return records[-1]

    def test_nba_prefix_sport(self) -> None:
        rec = self._emit_record_for_task("nba_prop_monitor")
        self.assertEqual(rec["sport"], "nba")

    def test_mlb_prefix_sport(self) -> None:
        rec = self._emit_record_for_task("mlb_daily_picks")
        self.assertEqual(rec["sport"], "mlb")

    def test_check_results_sport_none(self) -> None:
        rec = self._emit_record_for_task("check_results")
        self.assertIsNone(rec["sport"])

    def test_verify_sport_none(self) -> None:
        rec = self._emit_record_for_task("verify")
        self.assertIsNone(rec["sport"])

    def test_game_completion_monitor_sport_none(self) -> None:
        rec = self._emit_record_for_task("game_completion_monitor")
        self.assertIsNone(rec["sport"])


if __name__ == "__main__":
    unittest.main()
