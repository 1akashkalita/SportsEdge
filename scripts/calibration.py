#!/usr/bin/env python3
"""Per-sport probability calibration for SportsEdge.

Computes a bounded sigma scaler from realized prop outcomes (wins/losses + Model Over
Probability from Pick History) and persists it to data/research/calibration.json.

Non-interference guarantee: Never touches graded verdicts, the Results/Pick History
sheets, or evaluate_no_bet_gates / gate logic. This module is standalone — it does
NOT import sports_system_runner, evaluate_no_bet_gates, grade_slips, or any grading
code. That structural isolation is the METRICS-03 / D-13 guarantee.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workbook_io import safe_load_workbook

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
CALIBRATION_PATH = DATA / "research" / "calibration.json"

INCEPTION_DATE = "2026-06-08"
N_GATE = 30
MAX_STEP = 0.05
CLAMP_LO = 0.85
CLAMP_HI = 1.20


def _now_iso() -> str:
    """Return current UTC timestamp in ISO-8601 format (seconds precision)."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def compute_calibration_target(
    wins: int,
    losses: int,
    mop_values: list[float],
    prev_factor: float,
    n_gate: int = N_GATE,
    max_step: float = MAX_STEP,
    clamp_lo: float = CLAMP_LO,
    clamp_hi: float = CLAMP_HI,
) -> tuple[float, dict[str, Any]]:
    """Compute a bounded per-sport sigma scaler from realized outcomes.

    Parameters
    ----------
    wins:       count of WIN outcomes (PUSH/VOID already excluded by caller)
    losses:     count of LOSS outcomes
    mop_values: Model Over Probability values for rows where MOP is non-null
    prev_factor: current factor stored in calibration.json (default 1.0)
    n_gate:     minimum MOP-backed outcomes required before factor moves (D-10)
    max_step:   maximum factor change per cycle (D-10)
    clamp_lo:   minimum factor value (D-10)
    clamp_hi:   maximum factor value (D-10)

    Returns
    -------
    (new_factor, audit_dict)

    audit_dict fields: empirical_hit_rate, model_implied, raw_ratio, target,
                       delta, new_factor, prev_factor, n_outcomes, n_with_mop, reason
    """
    n_outcomes = wins + losses
    n_with_mop = len(mop_values)

    # Gate not met: stays neutral
    if n_outcomes < n_gate:
        return prev_factor, {
            "reason": f"gate not met: n={n_outcomes} < {n_gate}",
            "new_factor": prev_factor,
            "prev_factor": prev_factor,
            "n_outcomes": n_outcomes,
            "n_with_mop": n_with_mop,
        }

    empirical = wins / max(1, wins + losses)

    if n_with_mop == 0:
        return prev_factor, {
            "reason": "no MOP data available",
            "new_factor": prev_factor,
            "prev_factor": prev_factor,
            "n_outcomes": n_outcomes,
            "n_with_mop": n_with_mop,
            "empirical_hit_rate": round(empirical, 4),
        }

    model_implied = sum(mop_values) / len(mop_values)

    if empirical <= 0.0:
        raw_ratio = clamp_hi
    else:
        raw_ratio = model_implied / empirical

    # Clamp raw_ratio before computing delta (avoids extreme step from noisy early data)
    target = max(clamp_lo, min(clamp_hi, raw_ratio))

    delta = target - prev_factor
    delta = max(-max_step, min(max_step, delta))
    new_factor = prev_factor + delta
    new_factor = max(clamp_lo, min(clamp_hi, new_factor))

    return new_factor, {
        "reason": "computed",
        "empirical_hit_rate": round(empirical, 4),
        "model_implied": round(model_implied, 4),
        "raw_ratio": round(raw_ratio, 4),
        "target": round(target, 4),
        "delta": round(delta, 5),
        "new_factor": round(new_factor, 4),
        "prev_factor": prev_factor,
        "n_outcomes": n_outcomes,
        "n_with_mop": n_with_mop,
    }


def read_graded_outcomes_for_sport(
    sport: str,
    path: Path | None = None,
    _wb_override: Any = None,
) -> dict[str, Any]:
    """Read graded PROP outcomes for a sport from master_pnl.xlsx Pick History.

    Counts only rows where:
    - Pick Type == "PROP"
    - Sport matches (case-insensitive)
    - Result in {WIN, LOSS}  (PUSH and VOID excluded)
    - Date >= INCEPTION_DATE

    Parameters
    ----------
    sport:        "NBA" or "MLB" (case-insensitive)
    path:         override master_pnl.xlsx path (default: DATA/pnl/master_pnl.xlsx)
    _wb_override: in-memory openpyxl Workbook for testing (skips file load)

    Returns
    -------
    {wins, losses, mop_values, n_outcomes, n_with_mop}
    """
    result: dict[str, Any] = {
        "wins": 0,
        "losses": 0,
        "mop_values": [],
        "n_outcomes": 0,
        "n_with_mop": 0,
    }

    if _wb_override is not None:
        wb = _wb_override
    else:
        master_path = path or (DATA / "pnl" / "master_pnl.xlsx")
        try:
            wb = safe_load_workbook(master_path, read_only=True, data_only=True)
        except Exception:
            return result

    if "Pick History" not in wb.sheetnames:
        return result

    ph = wb["Pick History"]
    # Build header → column-index map from first row (never hardcode offsets)
    ph_headers = [ph.cell(1, c).value for c in range(1, ph.max_column + 1)]
    h = {col: idx for idx, col in enumerate(ph_headers) if col}

    required = {"Date", "Sport", "Pick Type", "Result", "Model Over Probability"}
    if not required.issubset(h.keys()):
        return result

    target_sport = sport.upper()

    for row_vals in ph.iter_rows(min_row=2, values_only=True):
        date_val = str(row_vals[h["Date"]] or "")[:10]
        sport_val = str(row_vals[h["Sport"]] or "").upper().strip()
        pick_type_val = str(row_vals[h["Pick Type"]] or "").upper().strip()
        result_val = str(row_vals[h["Result"]] or "").upper().strip()
        mop_raw = row_vals[h["Model Over Probability"]]

        # Filter
        if sport_val != target_sport:
            continue
        if pick_type_val != "PROP":
            continue
        if result_val not in {"WIN", "LOSS"}:
            continue
        if not date_val or date_val < INCEPTION_DATE:
            continue

        if result_val == "WIN":
            result["wins"] += 1
        else:
            result["losses"] += 1

        # Collect MOP only when non-null and parseable
        if mop_raw is not None:
            try:
                mop_float = float(mop_raw)
                result["mop_values"].append(mop_float)
            except (ValueError, TypeError):
                pass

    result["n_outcomes"] = result["wins"] + result["losses"]
    result["n_with_mop"] = len(result["mop_values"])
    return result


def load_calibration_factor(sport: str, path: Path = CALIBRATION_PATH) -> float:
    """Read the per-sport sigma scaler from calibration.json.

    Returns 1.0 (neutral) if:
    - File is absent
    - JSON is corrupt or malformed
    - Key is missing
    - Value is out of range (also clamped before return — V5 input validation)

    Never raises.
    """
    try:
        if Path(path).exists():
            cfg = json.loads(Path(path).read_text(encoding="utf-8"))
            raw = float(cfg.get("factors", {}).get(sport.upper(), 1.0))
            # V5 input validation: clamp any read value into [CLAMP_LO, CLAMP_HI]
            return max(CLAMP_LO, min(CLAMP_HI, raw))
    except Exception:
        pass
    return 1.0


def write_calibration_json(
    factors: dict[str, float],
    audit_entry: dict[str, Any],
    path: Path = CALIBRATION_PATH,
    max_audit: int = 52,
) -> None:
    """Write calibration factors and one audit entry to calibration.json atomically.

    Uses .json.tmp + os.replace for atomic writes (mirrors save_workbook_atomic pattern).
    Trims audit log to the last max_audit entries (~1 year at weekly cadence).
    Creates data/research/ directory if absent.

    Parameters
    ----------
    factors:     {sport_upper: float} map of current factors for all sports
    audit_entry: dict with per-sport audit fields (old→new factor, sample count, etc.)
    path:        override path (default: CALIBRATION_PATH)
    max_audit:   maximum audit entries to retain (default: 52)
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    try:
        if path.exists():
            existing = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        pass

    audit: list[dict[str, Any]] = list(existing.get("audit", []))
    audit.append(audit_entry)
    audit = audit[-max_audit:]  # trim to last 52 entries (~1 year)

    doc: dict[str, Any] = {
        "version": 1,
        "updated_at": _now_iso(),
        "inception_date": INCEPTION_DATE,
        "factors": factors,
        "audit": audit,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # atomic rename — same pattern as save_workbook_atomic


def compute_and_update_calibration(
    path: Path = CALIBRATION_PATH,
    master_path: Path | None = None,
    _wb_override: Any = None,
) -> dict[str, Any]:
    """Compute per-sport sigma scalers and write to calibration.json.

    Reads Pick History from master_pnl.xlsx, computes calibration targets for both
    sports (NBA + MLB), and writes the updated factors + audit entries atomically.

    Running twice on unchanged data is idempotent (factors converge to the same value).

    Parameters
    ----------
    path:         calibration.json output path (default: CALIBRATION_PATH)
    master_path:  override master_pnl.xlsx path
    _wb_override: in-memory workbook for testing

    Returns
    -------
    summary dict: {factors, audits, per_sport_counts}
    """
    path = Path(path)
    sports = ("NBA", "MLB")
    factors: dict[str, float] = {}
    audits: list[dict[str, Any]] = []
    per_sport_counts: dict[str, dict[str, Any]] = {}

    for sport in sports:
        try:
            counts = read_graded_outcomes_for_sport(
                sport, path=master_path, _wb_override=_wb_override
            )
            prev_factor = load_calibration_factor(sport, path=path)
            new_factor, audit = compute_calibration_target(
                wins=counts["wins"],
                losses=counts["losses"],
                mop_values=counts["mop_values"],
                prev_factor=prev_factor,
            )
            audit["sport"] = sport
            audit["updated_at"] = _now_iso()
            factors[sport] = new_factor
            audits.append(audit)
            per_sport_counts[sport] = counts
        except Exception as exc:  # noqa: BLE001
            # SKIP to neutral on any unexpected failure — never crash the task
            factors[sport] = 1.0
            audits.append({
                "sport": sport,
                "updated_at": _now_iso(),
                "reason": f"error: {exc}",
                "new_factor": 1.0,
                "prev_factor": 1.0,
            })
            per_sport_counts[sport] = {"wins": 0, "losses": 0, "mop_values": [], "n_outcomes": 0, "n_with_mop": 0}

    # Write one calibration.json with all sports; one audit entry per sport
    for audit_entry in audits:
        write_calibration_json(factors, audit_entry, path=path)

    return {
        "factors": factors,
        "audits": audits,
        "per_sport_counts": per_sport_counts,
    }
