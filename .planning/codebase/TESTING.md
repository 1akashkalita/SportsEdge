# Testing Patterns

**Analysis Date:** 2026-06-14

## Test Framework

**Runner:**
- stdlib `unittest` — all test classes inherit from `unittest.TestCase`
- pytest 9.x is installed and used as a test runner/discoverer, but NO pytest fixtures, conftest.py, or `@pytest.mark.*` decorators are used anywhere

**Assertion Library:**
- stdlib `unittest` assertions only: `assertEqual`, `assertAlmostEqual`, `assertTrue`, `assertFalse`, `assertIn`, `assertNotIn`, `assertIsNone`, `assertGreater`, `assertLess`, `assertRaises`
- Custom assertion helper pattern used in `test_slip_payouts.py`:
  ```python
  def assertPayout(self, *, slip_type, legs, wins, gross, net, stake=1.0):
      result = calculate_slip_payout(...)
      self.assertAlmostEqual(result["gross_return"], gross)
  ```

**Interpreter:** `python3` (the 3.14 interpreter at `/usr/local/bin/python3` that has `requests` and `openpyxl`). The default `python` (3.13) does NOT have these dependencies and will fail.

**Run Commands:**
```bash
# All commands must be run from scripts/ directory
cd /Users/akashkalita/sports_picks/scripts

python3 -m pytest                                        # Discover and run all tests
python3 -m pytest test_dynamic_gate8.py                  # Run one test file via pytest
python3 -m pytest test_dynamic_gate8.py -k spreads_totals  # Run single test by name
python3 test_slip_payouts.py                             # Run one test file directly (most have __main__)
python3 test_mlb_system_stress.py                        # Run stress/smoke tests directly
```

**Working directory requirement:** Tests MUST be run from `scripts/` because:
1. `importlib` loads `sports_system_runner.py` by relative path (`Path(__file__).with_name("sports_system_runner.py")`)
2. `sys.path.insert(0, str(Path(__file__).resolve().parent))` adds `scripts/` to the path so sibling modules (`slip_payouts`, `line_timing`, etc.) can be imported directly

## Test File Organization

**Location:** All test files live alongside the source they test in `scripts/`. No separate `tests/` directory.

**Naming:** `test_<module_name>.py` — 1:1 pairing with the script being tested:
- `test_slip_payouts.py` → `slip_payouts.py`
- `test_line_timing.py` → `line_timing.py`
- `test_sportsbook_comparison.py` → `sportsbook_comparison.py`
- `test_odds_api_io_client.py` → `odds_api_io_client.py`
- `test_fetch_dfs_props.py` → `fetch_dfs_props.py`
- `test_fetch_underdog.py` → `fetch_underdog.py`
- `test_special_line_value.py` → `special_line_value.py`
- `test_generate_projections.py` → `generate_projections.py`
- `test_dynamic_gate8.py` → gate logic in `sports_system_runner.py`

**Stage regression tests** (end-to-end pipeline stages, not tied to one module):
- `test_stage1_platform_outputs.py` — DFS platform fields throughout the pick pipeline
- `test_stage2_obsidian_messages.py` — Obsidian notes and messaging surface platform fields
- `test_stage3_results_clv.py` — Results/CLV sheets preserve platform
- `test_stage5_telegram_platform.py` — Telegram alerts include platform

**Stress/smoke tests** (require live data or are non-deterministic):
- `test_mlb_system_stress.py` — synthetic candidates against temp workbook copies
- `test_game_completion_monitor_smoke.py` — hits ESPN API to find a real completed game

**Structure:**
```
scripts/
├── <module>.py
├── test_<module>.py       # paired unit/integration tests
├── test_stage1_*.py       # end-to-end stage regression
├── test_stage2_*.py
├── test_stage3_*.py
├── test_stage5_*.py
└── test_*_smoke.py        # smoke tests (may hit real APIs)
```

## Test Structure

**Suite Organization:**

Most tests use `unittest.TestCase` classes:
```python
#!/usr/bin/env python3
from __future__ import annotations
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from slip_payouts import calculate_slip_payout

class TestSlipPayouts(unittest.TestCase):
    def test_2_pick_power_2_of_2(self):
        ...

if __name__ == "__main__":
    unittest.main()
```

Some files in `test_dynamic_gate8.py` mix module-level test functions (for pytest-only discovery) with `unittest.TestCase` classes for flag-mutation tests:
```python
# Module-level functions — run by pytest but not by unittest.main()
def test_normal_board_stays_10u():
    res = allocate([...])
    assert res["board_quality"] == "Normal"

# TestCase classes — run by both pytest and __main__
class PropDataSourceBoundaryTests(unittest.TestCase):
    def setUp(self): ...
    def tearDown(self): ...
    def test_prizepicks_prop_gate5_passes(...): ...

# __main__ block runs only module-level test_ functions
if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"PASS {name}")
```

**Patterns:**
- `setUp`: Saves module-level flags before mutation, creates shared fixture objects
- `tearDown`: Restores flags to original values (always restore via tuple unpack, never reassign individually)
- `addCleanup(tmpdir.cleanup)`: Used alongside `tempfile.TemporaryDirectory()` to ensure temp files removed even on failure

## Loading `sports_system_runner` via importlib

**Standard pattern** (used in ~10 test files):
```python
import importlib.util
from pathlib import Path

MOD_PATH = Path(__file__).with_name("sports_system_runner.py")
# or:
SCRIPT = Path(__file__).resolve().with_name("sports_system_runner.py")

spec = importlib.util.spec_from_file_location("sports_system_runner", SCRIPT)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)
```

After loading, override any functions that would make external calls:
```python
runner.load_suppressed_edge_types = lambda: {}
```

The `runner` module object is then used directly: `runner.evaluate_no_bet_gates(pick, {})`, `runner.allocate_eligible_candidates(...)`, etc.

## Mocking

**Framework:** `unittest.mock` — `patch`, `patch.object`, `patch.dict`

**Primary patterns:**

`patch.object` on the loaded `runner` module to replace network calls and side effects:
```python
from unittest.mock import patch

with patch.object(runner, "ensure_dirs", return_value=None), \
     patch.object(runner, "run_fetch_dfs_props", return_value=None), \
     patch.object(runner, "first_class_dfs_props_latest", return_value=[underdog_prop(line=2.0)]), \
     patch.object(runner, "fetch_sportsbook_prop_lines", return_value=({}, {"credits_remaining": "DISABLED"})), \
     patch.object(runner, "ensure_workbook", return_value=wb_path), \
     patch.object(runner, "obsidian_append_line_moves", return_value=None), \
     patch.object(runner, "PROP_MONITOR_DIR", details_dir):
    result = runner.prop_monitor("mlb")
```

`patch.dict` for environment variables (used in `test_odds_api_io_client.py`):
```python
self.env = patch.dict(os.environ, {"ODDS_API_IO_KEY": self.secret, ...}, clear=False)
self.env.start()  # in setUp
self.env.stop()   # in tearDown
```

`side_effect` for capturing calls:
```python
captured = []
with patch.object(runner, "obsidian_sync", side_effect=lambda payload: captured.append(payload) or {"ok": True}):
    runner.obsidian_append_line_moves([...], sport="MLB", date="2026-06-10")
markdown = captured[0]["data"]["line_moves_markdown"]
```

**Fake session pattern** (used in `test_odds_api_io_client.py`) — inject a `FakeSession` to avoid HTTP:
```python
class FakeResponse:
    def __init__(self, status_code=200, data=None, headers=None):
        self.status_code = status_code
        self._data = data
        self.headers = headers or {"x-ratelimit-remaining": "4999", ...}
    def json(self):
        return self._data

class FakeSession:
    def __init__(self, responses=None):
        self.responses = list(responses or [])
        self.calls = []
    def request(self, method, url, params=None, timeout=None):
        self.calls.append({...})
        return self.responses.pop(0)

def client(self, responses=None):
    return OddsApiIoClient(session=FakeSession(responses), backoff=0)
```

**Monkey-patching module-level functions** (alternative to `patch.object` in some tests):
```python
old_fn = runner.odds_api_io_game_markets
runner.odds_api_io_game_markets = fake_game_markets
try:
    games, headers = runner.odds_api("nba")
finally:
    runner.odds_api_io_game_markets = old_fn
```

**What to mock:**
- All network calls (`run_fetch_dfs_props`, `first_class_dfs_props_latest`, `fetch_sportsbook_prop_lines`, `send_telegram`, `obsidian_sync`, `obsidian_append_line_moves`)
- Filesystem side effects (`ensure_dirs`, `ensure_workbook`) when testing logic not I/O
- Module-level path constants (`PROP_MONITOR_DIR`, `ROOT`, `DATA`) to redirect to temp dirs

**What NOT to mock:**
- Business logic functions under test: gates, payout math, line classification, projections
- `tempfile.TemporaryDirectory` — use real temp dirs for workbook I/O tests
- `openpyxl` — real workbooks are written and read in integration tests

## Fixtures and Factories

**Test data:** Module-level factory functions, not pytest fixtures. Each test module defines its own factory:

`test_dynamic_gate8.py`:
```python
def cand(i, sport="NBA", tier="A", ev=0.4, prob=0.65, ...):
    return {
        "kind": "prop", "date": "2026-06-09", "sport": sport,
        "projection_id": f"proj-{sport}-{i}",
        "line": 10 + i + 0.5, "model_over_probability": prob,
        "ev": ev, "edge": edge, "hit_row": {"sample_size": 20, "hit_rate_l10": 0.7},
        ...
    }
```

`test_line_timing.py`:
```python
def prop_candidate(**overrides):
    row = {
        "kind": "prop", "line_timing": "pregame",
        "line_timing_confidence": "high", ...
    }
    row.update(overrides)
    return row
```

`test_fetch_dfs_props.py`:
```python
def pp(player="Victor Wembanyama", stat="Points", line=28.5, ...):
    return {"platform": "PrizePicks", "player_name": player, "line_score": line, ...}

def ud(player="Victor Wembanyama", stat="points", line=27.5, ...):
    return {"platform": "Underdog", "player_name": player, "line_score": line, ...}
```

**Workbook fixtures** — built in-process using openpyxl, saved to `tempfile.TemporaryDirectory`:
```python
def build_workbook(path: Path, existing_ids: list[str]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Player Props"
    ws.append(runner.PROPS_HEADERS)
    for pid in existing_ids:
        ws.append([runner.today_str(), "MLB", pid, ...] + ["" for _ in runner.LINE_TIMING_FIELDS])
    wb.save(path)
```

**Real data tests** (`test_generate_projections.py`): Some tests load actual JSON hit-rate files from `data/research/hit_rates/`:
```python
def real_hit_rec(filename: str, stat_name: str) -> dict:
    path = HIT_RATE_DIR / sport / filename
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {"doc": doc, "stat": doc["stats"][stat_name], "file": str(path)}
```
These tests require the hit-rate DB to exist on disk (populated by prior run of `build_hit_rate_db.py`).

**Location:** No shared fixture directory. Each test file is self-contained.

## Coverage

**Requirements:** None enforced (no coverage config, no CI pipeline).

**View Coverage:**
```bash
cd /Users/akashkalita/sports_picks/scripts
python3 -m pytest --tb=short -q        # Basic run with short tracebacks
```

No coverage reporting configured. Run specific test files to target areas:
```bash
python3 -m pytest test_dynamic_gate8.py test_line_timing.py test_slip_payouts.py -v
```

## Test Types

**Unit Tests (pure logic, no I/O):**
- `test_slip_payouts.py` — payout math for power/flex slips
- `test_special_line_value.py` — Demon/Goblin EV math and classification
- `test_special_line_filtering.py` — split_special_line_candidates logic
- `test_line_timing.py::LineTimingClassifierTests` — line timing classification
- `test_fetch_dfs_props.py` — player name normalization, stat matching, best-line selection
- `test_sportsbook_comparison.py` — cross-book comparison logic
- `test_prop_correlation.py`, `test_build_slips.py`, `test_audit_slips.py` — slip building pipeline

**Integration Tests (load runner module, use temp workbooks):**
- `test_dynamic_gate8.py::PropDataSourceBoundaryTests` — gate evaluation with flag mutation
- `test_dynamic_gate8.py::MLBNormalizationGateTests` — MLB field alias normalization through gates
- `test_line_timing.py::Gate12AndDownstreamTimingTests` — gate 12 via `evaluate_no_bet_gates`
- `test_stage1_platform_outputs.py` — `prop_monitor()` end-to-end with mocked network
- `test_prop_monitor_full_board.py` — `prop_monitor()` with real openpyxl workbook I/O
- `test_prop_monitor_alert_aggregation.py` — `dispatch_alerts()` with mocked Telegram
- `test_generate_projections.py` — projection math against real hit-rate files

**Stage Regression Tests (platform-field contract across pipeline):**
- `test_stage2_obsidian_messages.py` — Obsidian daily note template rendering
- `test_stage3_results_clv.py` — result records, CLV preview, platform breakdown
- `test_stage5_telegram_platform.py` — pick text and picks alert Telegram rendering

**Smoke Tests (may hit real external APIs):**
- `test_game_completion_monitor_smoke.py` — calls ESPN scoreboard API to find a real completed game, grades it against a temp workbook
- `test_mlb_system_stress.py` — loads real MLB workbook, copies it, runs synthetic candidates through full pipeline; hashes workbook to verify it is not mutated

## Flag Mutation Pattern

For tests that need to verify gate behavior under different feature flag states, mutate module-level flags in `setUp`/`tearDown`:

```python
class PropDataSourceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.old_flags = (
            runner.ENABLE_ODDS_API_PLAYER_PROPS,
            runner.ENABLE_DABBLE_PROP_COMPARISON,
            runner.USE_PRIZEPICKS_FOR_PLAYER_PROPS,
            runner.USE_UNDERDOG_FOR_PLAYER_PROPS,
        )
        runner.ENABLE_ODDS_API_PLAYER_PROPS = False
        runner.ENABLE_DABBLE_PROP_COMPARISON = False

    def tearDown(self):
        (
            runner.ENABLE_ODDS_API_PLAYER_PROPS,
            runner.ENABLE_DABBLE_PROP_COMPARISON,
            runner.USE_PRIZEPICKS_FOR_PLAYER_PROPS,
            runner.USE_UNDERDOG_FOR_PLAYER_PROPS,
        ) = self.old_flags
```

Always restore via tuple unpack from `self.old_flags` — never restore individually (risk of partial restore if `tearDown` itself raises).

## Common Patterns

**Async Testing:**
Not used. All code is synchronous. No `asyncio`, no `async def` tests.

**Error/Exception Testing:**
```python
# assertRaises used for expected ValueError:
with self.assertRaises(ValueError):
    sc.validate_game_markets(["h2h", "player_points"])

# Gate failure tested by checking return tuple:
ok, skipped, passed = runner.evaluate_no_bet_gates(pick, {})
self.assertFalse(ok)
self.assertEqual(skipped["gate_failed"], "GATE 5 — PLATFORM LINE AVAILABILITY")
self.assertIn("primary platform line missing/malformed", skipped["reason"])
```

**Workbook state assertions** — read back from saved file, never trust in-memory state:
```python
wb2 = load_workbook(wb_path, read_only=True, data_only=True)
try:
    ws2 = wb2["Player Props"]
    headers = [c.value for c in next(ws2.iter_rows(min_row=1, max_row=1))]
    platform_col = headers.index("Platform") + 1
    self.assertEqual(ws2.cell(2, platform_col).value, "Underdog")
finally:
    wb2.close()
```

**Module-level test functions** (pytest-only, `test_dynamic_gate8.py`):
```python
def test_normal_board_stays_10u():
    res = allocate([cand(i, tier="B", ev=0.15, prob=0.55) for i in range(4)])
    assert res["board_quality"] == "Normal"      # bare assert, not self.assert*
    assert res["dynamic_daily_cap"] == 10.0
```
Use bare `assert` (not `self.assert*`) in module-level test functions — these are not `TestCase` methods.

**Isolation from production data:** Tests that touch workbooks always use `tempfile.TemporaryDirectory`. Smoke tests patch `runner.ROOT` and related path constants to redirect to an isolated temp tree. Never write to `data/nba/` or `data/mlb/` in tests.

---

*Testing analysis: 2026-06-14*
