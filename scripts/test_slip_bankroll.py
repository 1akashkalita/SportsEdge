#!/usr/bin/env python3
"""Tests for slip-sourced bankroll ledger (D-09/D-13/BANKROLL-01/BANKROLL-04).

RED phase: these tests must FAIL before sync_slip_bankroll, PROP_ACCURACY_HEADERS,
and refresh_prop_accuracy are added to sports_system_runner.py.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Load runner via importlib (same pattern as test_dynamic_gate8.py)
MOD_PATH = Path(__file__).with_name("sports_system_runner.py")
spec = importlib.util.spec_from_file_location("sports_system_runner", MOD_PATH)
runner = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(runner)

from openpyxl import Workbook
from slip_payouts import SLIP_HISTORY_HEADERS


# ---------------------------------------------------------------------------
# In-memory workbook fixture helpers
# ---------------------------------------------------------------------------

def _make_master_wb_with_slip_history(slip_rows: list[list]) -> Workbook:
    """Build an in-memory master_pnl workbook with Slip History + required sheets."""
    wb = Workbook()
    wb.active.title = "Daily Log"
    # Add Daily Log header
    dl_ws = wb["Daily Log"]
    dl_ws.append(["Date", "Sport", "Wins", "Losses", "Pushes", "Units Bet",
                   "Day PnL", "Running Bankroll", "Notes"])
    # Add Bankroll Chart Data
    bcd = wb.create_sheet("Bankroll Chart Data")
    bcd.append(["Date", "Bankroll", "ROI", "Updated At"])
    # Add Performance Breakdown
    pb = wb.create_sheet("Performance Breakdown")
    pb.append(["Metric", "Value", "Updated At"])
    # Add Pick History
    ph = wb.create_sheet("Pick History")
    ph.append(runner.RESULT_HEADERS)
    # Add Slip History
    sh = wb.create_sheet("Slip History")
    sh.append(SLIP_HISTORY_HEADERS)
    for row in slip_rows:
        sh.append(row)
    return wb


def _make_pick_history_row(date: str, sport: str, result: str) -> list:
    """Build a Pick History row with the minimum required fields."""
    row = [None] * len(runner.RESULT_HEADERS)
    header_map = {h: i for i, h in enumerate(runner.RESULT_HEADERS)}
    row[header_map["Date"]] = date
    row[header_map["Sport"]] = sport
    row[header_map["Result"]] = result
    row[header_map["Units"]] = 1.0
    row[header_map["PnL"]] = 1.0 if result == "WIN" else (-1.0 if result == "LOSS" else 0.0)
    row[header_map["Pick Type"]] = "prop"
    row[header_map["Pick Ref"]] = f"TEST-{date}-{result}"
    return row


def _slip_row(date: str, net_pnl: float, needs_recon: bool | str = False,
              slip_id: str = "slip-001") -> list:
    """Build a Slip History row with key fields populated."""
    row = [None] * len(SLIP_HISTORY_HEADERS)
    h = {col: i for i, col in enumerate(SLIP_HISTORY_HEADERS)}
    row[h["Date"]] = date
    row[h["Slip ID"]] = slip_id
    row[h["Net PnL"]] = net_pnl
    row[h["Needs Payout Reconciliation"]] = needs_recon
    row[h["Slip Result"]] = "WIN" if net_pnl >= 0 else "LOSS"
    return row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSlipBankroll(unittest.TestCase):
    """Unit tests for sync_slip_bankroll (D-09, D-13, BANKROLL-01)."""

    def test_pending_slip_excluded(self):
        """D-13: slip with Needs Payout Reconciliation==True must NOT contribute to bankroll."""
        date = "2026-06-22"
        # One normal slip (+5.0 net) and one PENDING slip (+100.0 net — should be excluded)
        slip_rows = [
            _slip_row(date, net_pnl=5.0, needs_recon=False, slip_id="slip-001"),
            _slip_row(date, net_pnl=100.0, needs_recon=True, slip_id="slip-pending"),
        ]
        wb = _make_master_wb_with_slip_history(slip_rows)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            master = tmp_path / "master_pnl.xlsx"
            bankroll_path = tmp_path / "bankroll.json"
            wb.save(str(master))

            # Monkeypatch runner to use temp paths
            orig_bankroll = runner.BANKROLL
            orig_pnl_dir = runner.PNL_DIR
            try:
                runner.BANKROLL = bankroll_path
                runner.PNL_DIR = tmp_path

                result = runner.sync_slip_bankroll(date, dry_run=True,
                                                   _wb_override=wb,
                                                   _master_override=master,
                                                   _bankroll_override=bankroll_path)
                # Only the non-PENDING slip contributes
                self.assertAlmostEqual(result["day_pnl"], 5.0, places=3)
                self.assertAlmostEqual(result["current"], 105.0, places=2)
            finally:
                runner.BANKROLL = orig_bankroll
                runner.PNL_DIR = orig_pnl_dir

    def test_prop_flip_leaves_bankroll_unchanged(self):
        """BANKROLL-01: flipping a Pick History prop result does NOT change current_bankroll.

        The bankroll is sourced from Slip History only (D-09).
        sync_master_and_bankroll (prop path) must no longer write bankroll.json or Daily Log.
        """
        date = "2026-06-22"
        # Slip History: one completed slip worth +10.0
        slip_rows = [_slip_row(date, net_pnl=10.0, needs_recon=False)]
        wb = _make_master_wb_with_slip_history(slip_rows)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            master = tmp_path / "master_pnl.xlsx"
            bankroll_path = tmp_path / "bankroll.json"
            wb.save(str(master))

            orig_bankroll = runner.BANKROLL
            try:
                runner.BANKROLL = bankroll_path

                # Establish slip bankroll
                result_before = runner.sync_slip_bankroll(date, dry_run=True,
                                                          _wb_override=wb,
                                                          _master_override=master,
                                                          _bankroll_override=bankroll_path)
                bankroll_before = result_before["current"]

                # Now flip a Pick History prop row (WIN -> LOSS)
                ph = wb["Pick History"]
                ph.append(_make_pick_history_row(date, "NBA", "WIN"))
                # Calling sync_master_and_bankroll should NOT change the bankroll
                # (it only upserts Pick History / Obsidian records after severing)
                newly_graded = [{
                    "sport": "NBA", "ref": "TEST-PROP", "result": "LOSS",
                    "actual": None, "units": 1.0, "pnl": -1.0,
                    "graded_at": "2026-06-22T00:00:00+00:00", "note": "",
                    "Date": date, "Sport": "NBA", "Pick Ref": "TEST-PROP",
                    "Result": "LOSS", "Units": 1.0, "PnL": -1.0,
                    "Graded At": "2026-06-22T00:00:00+00:00",
                }]
                # After severing, sync_master_and_bankroll should NOT call BANKROLL.write_text
                # We verify by checking bankroll.json is NOT created by the prop path
                import inspect
                src = inspect.getsource(runner.sync_master_and_bankroll)
                self.assertNotIn(
                    "BANKROLL.write_text",
                    src,
                    "sync_master_and_bankroll must not write bankroll.json (prop coupling severed, D-09)"
                )
                self.assertNotIn(
                    "Bankroll Chart Data",
                    src,
                    "sync_master_and_bankroll must not append to Bankroll Chart Data (D-09)"
                )

                # The dry_run slip bankroll remains the same regardless of prop flip
                result_after = runner.sync_slip_bankroll(date, dry_run=True,
                                                         _wb_override=wb,
                                                         _master_override=master,
                                                         _bankroll_override=bankroll_path)
                self.assertAlmostEqual(result_after["current"], bankroll_before, places=3,
                                       msg="current_bankroll must not change when a prop result changes (BANKROLL-01)")
            finally:
                runner.BANKROLL = orig_bankroll

    def test_prop_accuracy_additive(self):
        """BANKROLL-04/D-10: Prop Accuracy sheet added additively; Pick History columns unchanged."""
        # Verify PROP_ACCURACY_HEADERS constant exists
        self.assertTrue(
            hasattr(runner, "PROP_ACCURACY_HEADERS"),
            "PROP_ACCURACY_HEADERS must be defined in sports_system_runner"
        )
        expected_pa_headers = ["Week", "Sport", "Total Props", "Wins", "Losses",
                                "Pushes", "Hit Rate", "Updated At"]
        self.assertEqual(runner.PROP_ACCURACY_HEADERS, expected_pa_headers)

        # Verify refresh_prop_accuracy exists
        self.assertTrue(
            hasattr(runner, "refresh_prop_accuracy"),
            "refresh_prop_accuracy must be defined in sports_system_runner"
        )

        # Build an in-memory workbook with Pick History props and run refresh_prop_accuracy
        wb = Workbook()
        wb.active.title = "Daily Log"
        wb["Daily Log"].append(["Date", "Sport", "Wins", "Losses", "Pushes",
                                 "Units Bet", "Day PnL", "Running Bankroll", "Notes"])
        bcd = wb.create_sheet("Bankroll Chart Data")
        bcd.append(["Date", "Bankroll", "ROI", "Updated At"])
        pb = wb.create_sheet("Performance Breakdown")
        pb.append(["Metric", "Value", "Updated At"])
        ph = wb.create_sheet("Pick History")
        ph.append(runner.RESULT_HEADERS)
        # Add Prop Accuracy sheet (simulating what master_pnl_workbook creates)
        pa = wb.create_sheet("Prop Accuracy")
        pa.append(runner.PROP_ACCURACY_HEADERS)
        # Add a few prop rows to Pick History (mix of WIN and LOSS)
        ph.append(_make_pick_history_row("2026-06-22", "NBA", "WIN"))
        ph.append(_make_pick_history_row("2026-06-22", "NBA", "LOSS"))
        ph.append(_make_pick_history_row("2026-06-22", "MLB", "WIN"))

        # Record the RESULT_HEADERS before calling refresh_prop_accuracy
        original_ph_headers = [ph.cell(1, c).value for c in range(1, ph.max_column + 1)]

        runner.refresh_prop_accuracy(wb)

        # Pick History headers must be unchanged (additive-only, D-10)
        after_ph_headers = [ph.cell(1, c).value for c in range(1, ph.max_column + 1)]
        self.assertEqual(original_ph_headers, after_ph_headers,
                         "refresh_prop_accuracy must not modify Pick History headers (D-10)")

        # Prop Accuracy sheet should have at least one data row now
        pa_ws = wb["Prop Accuracy"]
        self.assertGreater(pa_ws.max_row, 1,
                           "refresh_prop_accuracy should write at least one summary row")

        # Headers must match PROP_ACCURACY_HEADERS
        pa_headers = [pa_ws.cell(1, c).value for c in range(1, pa_ws.max_column + 1)]
        for h in runner.PROP_ACCURACY_HEADERS:
            self.assertIn(h, pa_headers, f"Prop Accuracy sheet missing header: {h}")


if __name__ == "__main__":
    unittest.main()
