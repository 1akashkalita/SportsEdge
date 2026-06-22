#!/usr/bin/env python3
"""Slip-level DFS payout accounting for SportsEdge.

Historical bankroll/Pick History values are never rewritten by this module.  It
only computes slip-level return objects and workbook rows for audit/reporting.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
PAYOUT_CONFIG_PATH = ROOT / "data" / "research" / "platform_payouts.json"
MANUAL_REVIEW_STATUSES = {"PUSH", "VOID", "DNP", "UNCLEAR", "UNKNOWN", "", None}
SLIP_HISTORY_HEADERS = [
    "Date", "Slip ID", "Platform", "Slip Type", "Number of Legs", "Legs", "Stake Units",
    "Winning Legs", "Losing Legs", "Push/Void/DNP Legs", "Contains Demon", "Contains Goblin",
    "Special Line Count", "Slip Result", "Standard Payout Multiplier", "Estimated Payout Multiplier",
    "Actual Payout Multiplier", "Payout Confidence", "Gross Return", "Net PnL",
    "Needs Payout Reconciliation", "Graded At", "Notes",
]


def load_payout_config(path: Path | str = PAYOUT_CONFIG_PATH) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    return json.loads(p.read_text())


def _clean_slip_type(value: Any) -> str:
    text = str(value or "").strip().lower()
    if "power" in text:
        return "power"
    if "flex" in text:
        return "flex"
    return text


def _clean_status(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip().upper()
    if text in {"W", "WON"}:
        return "WIN"
    if text in {"L", "LOST"}:
        return "LOSS"
    if text in {"P", "PUSHED"}:
        return "PUSH"
    return text


def payout_multiplier(platform: str, slip_type: str, total_legs: int, winning_legs: int, config: dict[str, Any] | None = None) -> float | None:
    cfg = config if config is not None else load_payout_config()
    platform_cfg = cfg.get(platform or "") or cfg.get(str(platform or "").strip()) or {}
    table = platform_cfg.get(_clean_slip_type(slip_type), {})
    value = table.get(str(int(total_legs)), {}).get(str(int(winning_legs)))
    return float(value) if isinstance(value, (int, float)) else None


def calculate_slip_payout(
    *,
    platform: str,
    slip_type: str,
    total_legs: int,
    winning_legs: int,
    stake_units: float,
    leg_results: Iterable[Any] | None = None,
    contains_demon: bool = False,
    contains_goblin: bool = False,
    actual_payout_multiplier: float | None = None,
    estimated_payout_multiplier: float | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute true slip-level gross/net return.

    If any leg is push/void/DNP/unclear and no configured rule exists, the slip is
    MANUAL REVIEW and no bankroll-safe PnL is returned.
    """
    total_legs = int(total_legs)
    winning_legs = int(winning_legs)
    stake_units = float(stake_units)
    statuses = [_clean_status(x) for x in (leg_results or [])]
    ambiguous = [s for s in statuses if s in MANUAL_REVIEW_STATUSES or s not in {"WIN", "LOSS"}]
    losing_legs = max(0, total_legs - winning_legs - len(ambiguous)) if statuses else max(0, total_legs - winning_legs)
    push_void_dnp = len(ambiguous)
    if ambiguous:
        return {
            "slip_result": "MANUAL REVIEW",
            "manual_review": True,
            "needs_payout_reconciliation": True,
            "reason": "Push/void/DNP/unclear leg result requires configured payout rule or manual review.",
            "standard_payout_multiplier": None,
            "estimated_payout_multiplier": estimated_payout_multiplier,
            "actual_payout_multiplier": actual_payout_multiplier,
            "payout_confidence": "manual_review",
            "gross_return": None,
            "net_pnl": None,
            "winning_legs": winning_legs,
            "losing_legs": losing_legs,
            "push_void_dnp_legs": push_void_dnp,
        }

    slip_kind = _clean_slip_type(slip_type)
    standard = payout_multiplier(platform, slip_kind, total_legs, winning_legs, config)
    multiplier = actual_payout_multiplier if actual_payout_multiplier is not None else standard
    confidence = "exact_manual" if actual_payout_multiplier is not None else "standard_config"

    if contains_demon or contains_goblin:
        # Standard tables do not encode special-line combo multipliers. Unknown
        # actual specials remain unresolved, but estimated values may be reported.
        if actual_payout_multiplier is None:
            return {
                "slip_result": "MANUAL REVIEW",
                "manual_review": True,
                "needs_payout_reconciliation": True,
                "reason": "Special-line slip lacks actual multiplier override.",
                "standard_payout_multiplier": standard,
                "estimated_payout_multiplier": estimated_payout_multiplier,
                "actual_payout_multiplier": None,
                "payout_confidence": "unreconciled_special_line",
                "gross_return": None,
                "net_pnl": None,
                "winning_legs": winning_legs,
                "losing_legs": losing_legs,
                "push_void_dnp_legs": push_void_dnp,
            }

    if slip_kind == "power" and winning_legs != total_legs:
        gross = 0.0
        net = -stake_units
        multiplier = 0.0
    elif multiplier is None:
        return {
            "slip_result": "MANUAL REVIEW",
            "manual_review": True,
            "needs_payout_reconciliation": True,
            "reason": "Missing payout config for platform/slip type/leg count/win count.",
            "standard_payout_multiplier": standard,
            "estimated_payout_multiplier": estimated_payout_multiplier,
            "actual_payout_multiplier": actual_payout_multiplier,
            "payout_confidence": "missing_config",
            "gross_return": None,
            "net_pnl": None,
            "winning_legs": winning_legs,
            "losing_legs": losing_legs,
            "push_void_dnp_legs": push_void_dnp,
        }
    else:
        gross = stake_units * float(multiplier)
        net = gross - stake_units

    return {
        "slip_result": "GRADED",
        "manual_review": False,
        "needs_payout_reconciliation": False,
        "reason": "",
        "standard_payout_multiplier": standard,
        "estimated_payout_multiplier": estimated_payout_multiplier,
        "actual_payout_multiplier": actual_payout_multiplier,
        "payout_confidence": confidence,
        "gross_return": round(gross, 6),
        "net_pnl": round(net, 6),
        "winning_legs": winning_legs,
        "losing_legs": losing_legs,
        "push_void_dnp_legs": push_void_dnp,
    }


def pick_history_rows_count_for_bankroll(rows: Iterable[dict[str, Any]]) -> int:
    """Rows with Slip ID are leg-level only and must not feed bankroll PnL."""
    count = 0
    for row in rows:
        slip_id = row.get("Slip ID") if "Slip ID" in row else row.get("slip_id")
        if not str(slip_id or "").strip():
            count += 1
    return count


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_slip_history_sheet(wb: Any) -> Any:
    ws = wb["Slip History"] if "Slip History" in wb.sheetnames else wb.create_sheet("Slip History")
    existing = [c.value for c in ws[1]] if ws.max_row else []
    if not any(existing):
        for idx, header in enumerate(SLIP_HISTORY_HEADERS, start=1):
            ws.cell(1, idx).value = header
    else:
        for idx, header in enumerate(SLIP_HISTORY_HEADERS, start=1):
            if idx > ws.max_column or ws.cell(1, idx).value in (None, ""):
                ws.cell(1, idx).value = header
    return ws


def slip_history_row(date: str, slip_id: str, platform: str, slip_type: str, legs: list[dict[str, Any]], stake_units: float, payout: dict[str, Any], notes: str = "") -> list[Any]:
    contains_demon = any(str(x.get("line_type") or x.get("odds_type") or "").lower() == "demon" or x.get("demon_available") for x in legs)
    contains_goblin = any(str(x.get("line_type") or x.get("odds_type") or "").lower() == "goblin" or x.get("goblin_available") for x in legs)
    special_count = sum(1 for x in legs if str(x.get("line_type") or x.get("odds_type") or "standard").lower() in {"demon", "goblin"})
    leg_text = "; ".join(f"{x.get('player_name') or x.get('player') or ''} {x.get('stat_type') or x.get('stat') or ''} {x.get('side') or 'Over'} {x.get('line') or ''}".strip() for x in legs)
    return [
        date, slip_id, platform, slip_type, len(legs), leg_text, stake_units,
        payout.get("winning_legs"), payout.get("losing_legs"), payout.get("push_void_dnp_legs"),
        contains_demon, contains_goblin, special_count, payout.get("slip_result"),
        payout.get("standard_payout_multiplier"), payout.get("estimated_payout_multiplier"),
        payout.get("actual_payout_multiplier"), payout.get("payout_confidence"),
        payout.get("gross_return"), payout.get("net_pnl"), payout.get("needs_payout_reconciliation"),
        now_utc_iso(), notes or payout.get("reason", ""),
    ]


def summarize_slip_history_rows(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    exact = [r for r in rows if not r.get("Needs Payout Reconciliation") and r.get("Net PnL") not in (None, "")]
    unreconciled = [r for r in rows if r.get("Needs Payout Reconciliation")]
    units = sum(float(r.get("Stake Units") or 0) for r in exact)
    pnl = sum(float(r.get("Net PnL") or 0) for r in exact)
    return {
        "slips": len(rows),
        "exact_slips": len(exact),
        "unreconciled_slips": len(unreconciled),
        "exact_units": round(units, 3),
        "exact_net_pnl": round(pnl, 3),
        "exact_roi_pct": round(pnl / units * 100, 2) if units else None,
    }
