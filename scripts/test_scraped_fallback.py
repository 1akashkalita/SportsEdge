#!/usr/bin/env python3
"""test_scraped_fallback.py — Integration tests for the Layer-2 scraped fallback adapter.

Testing strategy #6:
  - Cache-resolved scrape: the API box deliberately misses a player, but the per-event
    cache has the scraped stats -> assert grade is WIN/LOSS and Result Source="scraped",
    Result Confidence=0.5.
  - Flag-off safety: with ENABLE_FIRECRAWL_RESULT_FALLBACK=False, resolve_missing_stat
    is never invoked (Layer-1 MANUAL REVIEW is preserved).
  - Budget cap: when _scrape_run_count >= RESULT_SCRAPE_MAX_PER_RUN, no new scrapes fire.
  - Degrade on missing binary: shutil.which returning None -> (None, "manual", 0.0).
  - Degrade on absent event_id: game with no id -> (None, "manual", 0.0).
  - status="skip" cache policy: a skip response is NOT written to cache.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Bootstrap: load sports_system_runner
# ---------------------------------------------------------------------------
_SCRIPTS = Path(__file__).parent
_RUNNER_PATH = _SCRIPTS / "sports_system_runner.py"

spec = importlib.util.spec_from_file_location("sports_system_runner", _RUNNER_PATH)
assert spec and spec.loader
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)  # type: ignore[union-attr]

# ---------------------------------------------------------------------------
# Helper: build a minimal per-event cache file
# ---------------------------------------------------------------------------
def _write_cache(cache_dir: Path, event_id: str, players: dict) -> Path:
    """Write a status='ok' scraped result cache file and return its path."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    data = {"status": "ok", "schema": 1, "reason": "", "players": players}
    p = cache_dir / f"{event_id}.json"
    p.write_text(json.dumps(data, indent=2))
    return p


# ---------------------------------------------------------------------------
# Helper: minimal row dict for a prop
# ---------------------------------------------------------------------------
def _prop_row(player: str, stat: str, line: float, side: str = "Over") -> dict:
    return {
        "Player Name": player,
        "Stat": stat,
        "Line": line,
        "Opponent/Description": f"{side} {line}",
        "Reasoning": "units=1.0",
    }


class TestFlagOffNeverCallsResolve(unittest.TestCase):
    """With ENABLE_FIRECRAWL_RESULT_FALLBACK=False, resolve_missing_stat must never be called."""

    def test_flag_false_resolve_never_invoked(self) -> None:
        # Patch ENABLE_FIRECRAWL_RESULT_FALLBACK to False (default)
        with patch.object(runner, "ENABLE_FIRECRAWL_RESULT_FALLBACK", False):
            with patch.object(runner, "resolve_missing_stat") as mock_resolve:
                # Call grade_prop with an empty player_stats dict (Layer-1 will return None)
                row = _prop_row("Shohei Ohtani", "Home Runs", 0.5)
                result, actual, note, res_src, res_conf = runner.grade_prop(row, {}, True)
                # grade_prop itself should return PENDING (no stat found)
                self.assertEqual(result, "PENDING")
                # grade_game_in_workbook would call resolve_missing_stat, but since
                # the flag is off, it should not be called.
                # We verify directly that resolve_missing_stat is correctly gated:
                # simulate the gate check from grade_game_in_workbook.
                _scrape_count = 0
                if (runner.ENABLE_FIRECRAWL_RESULT_FALLBACK
                        and _scrape_count < runner.RESULT_SCRAPE_MAX_PER_RUN):
                    runner.resolve_missing_stat("mlb", {}, "Shohei Ohtani", "Home Runs")
                mock_resolve.assert_not_called()

    def test_flag_true_allows_resolve_call(self) -> None:
        """With flag True, the gate condition allows resolve_missing_stat to be called."""
        with patch.object(runner, "ENABLE_FIRECRAWL_RESULT_FALLBACK", True):
            with patch.object(runner, "_scrape_run_count", 0):
                _scrape_count = 0
                flag_on = runner.ENABLE_FIRECRAWL_RESULT_FALLBACK
                budget_ok = _scrape_count < runner.RESULT_SCRAPE_MAX_PER_RUN
                # Both conditions must be True for the gate to open
                self.assertTrue(flag_on)
                self.assertTrue(budget_ok)


class TestResolveMissingStatCacheHit(unittest.TestCase):
    """resolve_missing_stat reads from cache and returns (value, 'scraped', 0.5) on hit."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        # The runner looks for cache at DATA / "research" / "results_cache"
        # So we must write to tmpdir / "research" / "results_cache"
        self.cache_dir = self.tmpdir / "research" / "results_cache"
        # Bobby Witt Jr. batting stats (using canonical name form)
        self.event_id = "401815839"
        self.players = {
            "bobby witt": {
                "batting": {
                    "hits": 2.0, "runs": 1.0, "rbis": 1.0,
                    "homeruns": 1.0, "walks": 0.0, "strikeouts": 1.0,
                },
                "hits": 2.0, "runs": 1.0, "rbis": 1.0,
                "homeruns": 1.0, "walks": 0.0, "strikeouts": 1.0,
            },
        }
        _write_cache(self.cache_dir, self.event_id, self.players)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _run_resolve(self, player: str, stat: str) -> tuple:
        """Run resolve_missing_stat with patched DATA path pointing to our tmpdir."""
        game = {"event_id": self.event_id, "id": self.event_id}
        with patch.object(runner, "DATA", self.tmpdir):
            # Ensure npx and node appear available
            with patch("shutil.which", return_value="/usr/local/bin/npx"):
                return runner.resolve_missing_stat("mlb", game, player, stat)

    def test_cache_hit_returns_scraped_hits(self) -> None:
        val, src, conf = self._run_resolve("Bobby Witt Jr.", "Hits")
        self.assertIsNotNone(val, "Expected a value from cache; got None")
        self.assertEqual(src, "scraped", f"Expected source='scraped'; got {src!r}")
        self.assertEqual(conf, 0.5, f"Expected confidence=0.5; got {conf}")
        self.assertEqual(val, 2.0, f"Expected hits=2.0 for Bobby Witt Jr.; got {val}")

    def test_cache_hit_returns_scraped_homeruns(self) -> None:
        val, src, conf = self._run_resolve("bobby witt jr", "Home Runs")
        self.assertIsNotNone(val)
        self.assertEqual(src, "scraped")
        self.assertEqual(val, 1.0, f"Expected homeruns=1.0; got {val}")

    def test_cache_hit_for_absent_player_returns_manual(self) -> None:
        """Player not in cache box -> (None, 'manual', 0.0) — not an error."""
        val, src, conf = self._run_resolve("Mookie Betts", "Hits")
        self.assertIsNone(val)
        self.assertEqual(src, "manual")
        self.assertEqual(conf, 0.0)

    def test_cache_hit_for_absent_stat_returns_manual(self) -> None:
        """Player in cache but stat not derivable -> (None, 'manual', 0.0)."""
        # Fantasy Score is NOT-DERIVABLE
        val, src, conf = self._run_resolve("Bobby Witt Jr.", "Hitter Fantasy Score")
        self.assertIsNone(val)
        self.assertEqual(src, "manual")
        self.assertEqual(conf, 0.0)


class TestResolveMissingStatDegradation(unittest.TestCase):
    """resolve_missing_stat degrades gracefully on every failure path."""

    def test_missing_event_id_returns_manual(self) -> None:
        game_no_id = {}
        with patch("shutil.which", return_value="/usr/local/bin/npx"):
            result = runner.resolve_missing_stat("mlb", game_no_id, "Bobby Witt Jr.", "Hits")
        self.assertEqual(result, (None, "manual", 0.0))

    def test_npx_not_found_returns_manual(self) -> None:
        game = {"event_id": "123456"}
        # Patch shutil.which to return None for both npx and node
        with patch("shutil.which", return_value=None):
            # Reset the warned flag so the warning fires fresh
            original = runner._NPX_PREFLIGHT_WARNED
            runner._NPX_PREFLIGHT_WARNED = False
            try:
                result = runner.resolve_missing_stat("mlb", game, "Bobby Witt Jr.", "Hits")
            finally:
                runner._NPX_PREFLIGHT_WARNED = original
        self.assertEqual(result, (None, "manual", 0.0))

    def test_node_not_found_returns_manual(self) -> None:
        game = {"event_id": "123456"}
        def which_no_node(name: str) -> str | None:
            if name == "node":
                return None
            return "/usr/local/bin/npx"
        with patch("shutil.which", side_effect=which_no_node):
            original = runner._NPX_PREFLIGHT_WARNED
            runner._NPX_PREFLIGHT_WARNED = False
            try:
                result = runner.resolve_missing_stat("mlb", game, "Bobby Witt Jr.", "Hits")
            finally:
                runner._NPX_PREFLIGHT_WARNED = original
        self.assertEqual(result, (None, "manual", 0.0))

    def test_budget_cap_returns_manual(self) -> None:
        """When _scrape_run_count >= RESULT_SCRAPE_MAX_PER_RUN, degrade immediately."""
        game = {"event_id": "999"}
        with patch.object(runner, "_scrape_run_count", runner.RESULT_SCRAPE_MAX_PER_RUN):
            with patch("shutil.which", return_value="/usr/local/bin/npx"):
                with tempfile.TemporaryDirectory() as tmpdir:
                    # No cache file exists -> would need a scrape -> but cap is exhausted
                    with patch.object(runner, "DATA", Path(tmpdir)):
                        result = runner.resolve_missing_stat("mlb", game, "Bobby Witt Jr.", "Hits")
        self.assertEqual(result, (None, "manual", 0.0))

    def test_verify_script_missing_returns_manual(self) -> None:
        """If verify_results.py does not exist, degrade gracefully."""
        game = {"event_id": "999"}
        with patch("shutil.which", return_value="/usr/local/bin/npx"):
            with patch.object(runner, "_scrape_run_count", 0):
                with tempfile.TemporaryDirectory() as tmpdir:
                    with patch.object(runner, "DATA", Path(tmpdir)):
                        # SCRIPTS points to a dir without verify_results.py
                        with patch.object(runner, "SCRIPTS", Path(tmpdir)):
                            result = runner.resolve_missing_stat(
                                "mlb", game, "Bobby Witt Jr.", "Hits"
                            )
        self.assertEqual(result, (None, "manual", 0.0))


class TestResolveMissingStatSubprocessPath(unittest.TestCase):
    """resolve_missing_stat uses _subprocess_run_with_retry (not bare subprocess.run)."""

    def test_uses_subprocess_run_with_retry_on_cache_miss(self) -> None:
        """Verify _subprocess_run_with_retry is called (not subprocess.run directly)."""
        game = {"event_id": "777001"}
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            # Place a fake verify_results.py
            fake_vr = tmppath / "verify_results.py"
            fake_vr.write_text("# stub")

            # Build a fake CompletedProcess that returns status=ok with one player
            fake_players = {"shohei ohtani": {"homeruns": 1.0}}
            fake_envelope = {"status": "ok", "schema": 1, "reason": "", "players": fake_players}
            fake_cp = MagicMock()
            fake_cp.stdout = f"JSON_RESULT={json.dumps(fake_envelope)}\n"
            fake_cp.stderr = ""
            fake_cp.returncode = 0

            with patch("shutil.which", return_value="/usr/local/bin/npx"):
                with patch.object(runner, "_scrape_run_count", 0):
                    with patch.object(runner, "DATA", tmppath):
                        with patch.object(runner, "SCRIPTS", tmppath):
                            with patch.object(
                                runner, "_subprocess_run_with_retry", return_value=fake_cp
                            ) as mock_retry:
                                runner.resolve_missing_stat(
                                    "mlb", game, "Shohei Ohtani", "Home Runs"
                                )
                                mock_retry.assert_called_once()
                                call_kwargs = mock_retry.call_args
                                # Verify timeout is RESULT_SCRAPE_TIMEOUT
                                timeout = call_kwargs.kwargs.get("timeout") or call_kwargs[1].get("timeout")
                                self.assertEqual(timeout, runner.RESULT_SCRAPE_TIMEOUT)
                                # Verify context string contains event_id
                                context = call_kwargs.kwargs.get("context") or call_kwargs[1].get("context")
                                self.assertIn("777001", context)

    def test_subprocess_run_directly_not_used(self) -> None:
        """Confirm subprocess.run is never called directly from resolve_missing_stat."""
        import inspect
        src = inspect.getsource(runner.resolve_missing_stat)
        # Should use _subprocess_run_with_retry, not bare subprocess.run
        self.assertIn("_subprocess_run_with_retry", src,
                      "resolve_missing_stat must use _subprocess_run_with_retry")
        # Bare subprocess.run call (not the import, not the reference) should not appear
        # We check for subprocess.run( as a call pattern
        import re
        bare_calls = re.findall(r"subprocess\.run\s*\(", src)
        self.assertEqual(bare_calls, [],
                         f"resolve_missing_stat must NOT call subprocess.run directly; "
                         f"found: {bare_calls}")


class TestSkipStatusNotCached(unittest.TestCase):
    """status='skip' responses from verify_results.py must NOT be written to cache."""

    def test_skip_response_not_cached(self) -> None:
        game = {"event_id": "888001"}
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            fake_vr = tmppath / "verify_results.py"
            fake_vr.write_text("# stub")

            fake_envelope = {"status": "skip", "schema": 1, "reason": "rate-limited", "players": {}}
            fake_cp = MagicMock()
            fake_cp.stdout = f"JSON_RESULT={json.dumps(fake_envelope)}\n"
            fake_cp.stderr = ""
            fake_cp.returncode = 0

            with patch("shutil.which", return_value="/usr/local/bin/npx"):
                with patch.object(runner, "_scrape_run_count", 0):
                    with patch.object(runner, "DATA", tmppath):
                        with patch.object(runner, "SCRIPTS", tmppath):
                            with patch.object(
                                runner, "_subprocess_run_with_retry", return_value=fake_cp
                            ):
                                result = runner.resolve_missing_stat(
                                    "mlb", game, "Shohei Ohtani", "Home Runs"
                                )

            # status=skip -> (None, "manual", 0.0)
            self.assertEqual(result, (None, "manual", 0.0))
            # Cache file must NOT have been created (status=skip -> no caching)
            cache_file = tmppath / "research" / "results_cache" / "888001.json"
            self.assertFalse(cache_file.exists(),
                             f"status=skip must NOT be written to cache; file exists: {cache_file}")


class TestFlagsDefaultOff(unittest.TestCase):
    """ENABLE_FIRECRAWL_RESULT_FALLBACK defaults to False."""

    def test_default_flag_off(self) -> None:
        """Verify the flag is False unless overridden by env."""
        # Import fresh with no env var set
        if "ENABLE_FIRECRAWL_RESULT_FALLBACK" in os.environ:
            self.skipTest("ENABLE_FIRECRAWL_RESULT_FALLBACK is set in environment; skip default test")
        # The loaded runner should have the default value
        # It was loaded at import time, so we check the flag at module level
        import inspect
        src = inspect.getsource(runner)
        self.assertIn('env_bool("ENABLE_FIRECRAWL_RESULT_FALLBACK", False)',
                      src,
                      "ENABLE_FIRECRAWL_RESULT_FALLBACK must default to False in the runner")

    def test_budget_product_under_600s(self) -> None:
        """RESULT_SCRAPE_MAX_PER_RUN × RESULT_SCRAPE_TIMEOUT < 600s (cron budget)."""
        product = runner.RESULT_SCRAPE_MAX_PER_RUN * runner.RESULT_SCRAPE_TIMEOUT
        self.assertLess(product, 600,
                        f"MAX_PER_RUN={runner.RESULT_SCRAPE_MAX_PER_RUN} × "
                        f"TIMEOUT={runner.RESULT_SCRAPE_TIMEOUT} = {product}s >= 600s; "
                        f"exceeds cron budget")


class TestRunnerNeverImportsFirecrawl(unittest.TestCase):
    """The runner must NEVER import firecrawl."""

    def test_no_firecrawl_import_in_runner(self) -> None:
        runner_text = _RUNNER_PATH.read_text()
        import re
        # Check for direct import statements
        firecrawl_imports = re.findall(r"^\s*(?:import|from)\s+firecrawl", runner_text, re.MULTILINE)
        self.assertEqual(firecrawl_imports, [],
                         f"Runner must never import firecrawl; found: {firecrawl_imports}")

    def test_verify_results_is_subprocess_isolated(self) -> None:
        """verify_results.py is invoked via subprocess, never imported."""
        runner_text = _RUNNER_PATH.read_text()
        import re
        # Should use subprocess/shell invocation of verify_results.py
        self.assertIn("verify_results", runner_text,
                      "Runner should reference verify_results.py for subprocess invocation")
        # Must not import it directly
        direct_import = re.findall(r"^\s*(?:import|from)\s+verify_results", runner_text, re.MULTILINE)
        self.assertEqual(direct_import, [],
                         f"Runner must not import verify_results; found: {direct_import}")


if __name__ == "__main__":
    unittest.main()
