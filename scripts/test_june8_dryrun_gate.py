#!/usr/bin/env python3
"""RESULTS-07 hard gate: ≥80% of non-Fantasy-Score MANUAL REVIEW prop rows for
data/mlb/mlb_2026-06-08.xlsx resolve to WIN/LOSS/PUSH after Layer-1 hardening.

Dry-run only — does NOT write to any workbook.

Strategy (Testing strategy #11 from the trustworthy-results spec):
  1. Read all MANUAL REVIEW prop rows from the June 8 MLB Results sheet.
  2. Exclude Fantasy Score composites (Hitter/Pitcher Fantasy Score, Fantasy Points) —
     these are the Layer-2 residue only recoverable via scraped fallback; they are
     excluded from the denominator by design, not failures.
  3. For each remaining non-Fantasy MANUAL REVIEW row:
       a. Parse player / stat / line from the PROP: Pick Ref using parse_prop_ref.
       b. Match the Game column to an ESPN game event_id (name-based matching).
       c. Load player stats via espn_player_stats_by_event (Layer-1 hardened).
       d. Call stat_value_for_prop — if it returns a non-None value, the stat is
          resolvable.  Grade using the default side ("Over" — the Props sheet rows
          store opponent abbreviation, not "Over"/"Under", so the original grading
          always defaulted to "Over").
  4. Assert resolved / denominator >= 0.80.
     On failure, print the measured numerator/denominator breakdown so the operator
     sees the real ceiling rather than a bare assertion failure.

Run from scripts/:
    cd scripts && python3 test_june8_dryrun_gate.py
"""

from __future__ import annotations

import importlib
import sys
import unittest
from pathlib import Path

# Ensure scripts/ is on sys.path for sibling imports (per CLAUDE.md)
SCRIPTS = Path(__file__).parent
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

runner = importlib.import_module("sports_system_runner")

DATE = "2026-06-08"
WORKBOOK = SCRIPTS.parent / "data" / "mlb" / f"mlb_{DATE}.xlsx"

# Fantasy Score stat keywords (exact stat strings that are Layer-2 residue only).
_FANTASY_STAT_KEYWORDS = frozenset(
    {
        "fantasy score",
        "fantasy points",
        "hitter fantasy score",
        "pitcher fantasy score",
        "nba fantasy score",
        "nba fantasy points",
    }
)


def _is_fantasy_stat(ref: str) -> bool:
    """Return True if the PROP: ref refers to a Fantasy Score composite stat."""
    ref_lower = ref.lower()
    return any(kw in ref_lower for kw in _FANTASY_STAT_KEYWORDS)


def _game_label_to_event_id(game_label: str, espn_games: list[dict]) -> str | None:
    """Match a Result-sheet Game label (e.g. 'Houston Astros @ Los Angeles Angels')
    to an ESPN game dict and return the event_id, or None if no match.

    Uses team_aliases for fuzzy matching so "Athletics" == "Oakland Athletics" etc.
    """
    if not game_label:
        return None
    parts = [p.strip() for p in str(game_label).split("@")]
    if len(parts) != 2:
        return None
    away_label, home_label = parts[0], parts[1]
    away_aliases = runner.team_aliases(away_label)
    home_aliases = runner.team_aliases(home_label)
    for g in espn_games:
        g_home_aliases = runner.team_aliases(g.get("home_team") or "")
        g_away_aliases = runner.team_aliases(g.get("away_team") or "")
        if away_aliases & g_away_aliases and home_aliases & g_home_aliases:
            return str(g.get("event_id") or "")
    return None


def _read_june8_manual_review_rows() -> list[dict]:
    """Read all MANUAL REVIEW prop rows from the June 8 Results sheet."""
    from openpyxl import load_workbook  # type: ignore[import]

    wb = load_workbook(str(WORKBOOK), read_only=True, data_only=True)
    ws = wb["Results"]
    headers = [c.value for c in ws[1]]
    rows = []
    for vals in ws.iter_rows(min_row=2, values_only=True):
        if not vals or vals[0] is None:
            continue
        rd = dict(zip(headers, vals))
        if (
            str(rd.get("Date") or "")[:10] == DATE
            and str(rd.get("Sport") or "").upper() == "MLB"
            and str(rd.get("Result") or "").upper() == "MANUAL REVIEW"
        ):
            ref = str(rd.get("Pick Ref") or "")
            if ref.startswith("PROP:"):
                rows.append(rd)
    wb.close()
    return rows


class TestJune8DryRunGate(unittest.TestCase):
    """RESULTS-07 gate: ≥80% non-Fantasy MANUAL REVIEW prop rows resolve after Layer-1."""

    def test_gate_eighty_percent_non_fantasy_resolve(self) -> None:
        # Step 1 — verify workbook exists
        self.assertTrue(
            WORKBOOK.exists(),
            f"June 8 workbook not found: {WORKBOOK}",
        )

        # Step 2 — read all MANUAL REVIEW rows
        all_mr_rows = _read_june8_manual_review_rows()
        self.assertGreater(
            len(all_mr_rows),
            0,
            "No MANUAL REVIEW PROP rows found in June 8 Results sheet — "
            "workbook may be missing or already fully graded",
        )

        # Step 3 — split into Fantasy and non-Fantasy
        fantasy_rows = [r for r in all_mr_rows if _is_fantasy_stat(str(r.get("Pick Ref") or ""))]
        non_fantasy_rows = [r for r in all_mr_rows if not _is_fantasy_stat(str(r.get("Pick Ref") or ""))]

        denominator = len(non_fantasy_rows)
        self.assertGreater(
            denominator,
            0,
            "No non-Fantasy MANUAL REVIEW PROP rows found — nothing to gate on",
        )

        print(f"\nJune 8 MANUAL REVIEW rows: {len(all_mr_rows)} total")
        print(f"  Fantasy Score (excluded from denominator): {len(fantasy_rows)}")
        print(f"  Non-Fantasy (denominator): {denominator}")

        # Step 4 — fetch June 8 ESPN games
        espn_games = runner.espn_scoreboard_games_for_date("mlb", DATE)
        self.assertGreater(len(espn_games), 0, "ESPN returned no June 8 MLB games")

        # Build event_id → player_stats cache (one ESPN call per game)
        event_stats_cache: dict[str, dict] = {}

        # Step 5 — grade each non-Fantasy row via Layer-1
        resolved: list[dict] = []         # WIN/LOSS/PUSH
        abstained: list[dict] = []        # side_unrecoverable (excluded from denom)
        still_manual: list[dict] = []     # stat_value returned None → still MANUAL REVIEW

        for row in non_fantasy_rows:
            ref = str(row.get("Pick Ref") or "")
            game_label = str(row.get("Game") or "")

            # Parse player / stat / line from PROP: ref using plan 01-4's parse_prop_ref
            player, stat, line = runner.parse_prop_ref(ref)

            if stat is None or line is None:
                # Ref unparseable — counts as still-manual
                still_manual.append({
                    "ref": ref,
                    "reason": "parse_prop_ref returned None stat or line",
                })
                continue

            # Find the ESPN event_id for this game
            event_id = _game_label_to_event_id(game_label, espn_games)
            if not event_id:
                still_manual.append({
                    "ref": ref,
                    "reason": f"game label not matched to ESPN event: '{game_label}'",
                })
                continue

            # Load player stats (cached per event_id)
            if event_id not in event_stats_cache:
                event_stats_cache[event_id] = runner.espn_player_stats_by_event(
                    "mlb", event_id
                )
            player_stats = event_stats_cache[event_id]

            # Call Layer-1 stat resolution
            # The original Props rows had Opponent/Description = opponent abbreviation (not
            # "Over"/"Under"), so grade_prop defaulted to "Over" for all of these rows.
            # We replicate that default here.
            actual_val, src, conf = runner.stat_value_for_prop(player_stats, player, stat)

            if actual_val is not None:
                # Stat resolved — grade with default "Over" side (matching original grading).
                side = "Over"
                diff = actual_val - line
                if diff == 0:
                    result = "PUSH"
                elif side == "Over":
                    result = "WIN" if diff > 0 else "LOSS"
                else:
                    result = "WIN" if diff < 0 else "LOSS"

                resolved.append({
                    "ref": ref,
                    "result": result,
                    "actual": actual_val,
                    "line": line,
                    "src": src,
                    "conf": conf,
                })
            else:
                still_manual.append({
                    "ref": ref,
                    "reason": f"stat_value_for_prop returned None for {player!r} {stat!r}",
                })

        numerator = len(resolved)
        rate = numerator / denominator if denominator else 0.0

        # Print detailed breakdown always so the operator can see it
        print(f"\n=== June 8 Layer-1 Dry-Run Resolution ===")
        print(f"Denominator (non-Fantasy MANUAL REVIEW): {denominator}")
        print(f"Resolved (WIN/LOSS/PUSH): {numerator}")
        print(f"Still MANUAL REVIEW: {len(still_manual)}")
        print(f"Resolution rate: {numerator}/{denominator} = {rate:.1%}")
        print()

        if resolved:
            print("Resolved rows (first 10):")
            for r in resolved[:10]:
                print(f"  {r['result']:6s}  {r['ref']}  (actual={r['actual']} vs Over {r['line']})")

        if still_manual:
            print(f"\nStill MANUAL REVIEW rows ({len(still_manual)}):")
            for r in still_manual[:20]:
                print(f"  {r['ref']}  — {r['reason']}")

        self.assertGreaterEqual(
            rate,
            0.80,
            f"RESULTS-07 gate FAILED: Layer-1 resolved {numerator}/{denominator} = {rate:.1%} "
            f"of non-Fantasy-Score MANUAL REVIEW prop rows for June 8 "
            f"(required ≥ 80%).\n"
            f"Still MANUAL REVIEW breakdown:\n"
            + "\n".join(f"  {r['ref']} — {r['reason']}" for r in still_manual),
        )

        print(
            f"\nRESULTS-07 gate PASSED: {numerator}/{denominator} = {rate:.1%} "
            f"non-Fantasy MANUAL REVIEW rows resolve after Layer-1 hardening."
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
