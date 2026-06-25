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

# Source-level probability calibration stopgap (applied flag-gated in
# generate_projections via USE_CALIBRATED_PROBABILITIES). Derives a per-sport
# shrink factor s that pulls an overconfident over_probability SYMMETRICALLY
# toward 0.5: p' = 0.5 + (p - 0.5) * s. s in [SHRINK_FLOOR, 1.0]; s == 1.0 means
# "do not shrink". This is distinct from the sigma scaler above and the two are
# never applied together (see generate_projections.build_projection).
SHRINK_ANCHOR = 0.5
SHRINK_FLOOR = 0.40


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
    n_total_graded: int = 0,
) -> tuple[float, dict[str, Any]]:
    """Compute a bounded per-sport sigma scaler from realized outcomes.

    ``wins``, ``losses``, and ``mop_values`` MUST all be drawn from the same
    MOP-backed population (i.e. only rows where a parseable Model Over
    Probability is present).  ``empirical`` and ``model_implied`` therefore share
    the same denominator and are directly comparable.

    The gate fires on ``n_with_mop = len(mop_values)`` — the size of that
    shared population.  ``n_total_graded`` (optional, informational only) is the
    count of all WIN/LOSS rows including those without MOP; it is carried into
    the audit dict but does NOT affect gating or the computed factor.

    Parameters
    ----------
    wins:            count of MOP-backed WIN outcomes (PUSH/VOID excluded by caller)
    losses:          count of MOP-backed LOSS outcomes
    mop_values:      Model Over Probability values for those same rows
    prev_factor:     current factor stored in calibration.json (default 1.0)
    n_gate:          minimum MOP-backed outcomes required before factor moves (D-10)
    max_step:        maximum factor change per cycle (D-10)
    clamp_lo:        minimum factor value (D-10)
    clamp_hi:        maximum factor value (D-10)
    n_total_graded:  informational total WIN/LOSS count (including rows without MOP)

    Returns
    -------
    (new_factor, audit_dict)

    audit_dict fields: empirical_hit_rate, model_implied, raw_ratio, target,
                       delta, new_factor, prev_factor, n_outcomes, n_with_mop,
                       n_total_graded, reason
    """
    n_with_mop = len(mop_values)
    # n_outcomes is kept for audit/backward-compat; wins+losses == n_with_mop after WR-01 fix
    n_outcomes = wins + losses

    # Gate on the MOP-backed population (WR-01 fix: was n_outcomes)
    if n_with_mop < n_gate:
        return prev_factor, {
            "reason": f"gate not met: n={n_with_mop} < {n_gate}",
            "new_factor": prev_factor,
            "prev_factor": prev_factor,
            "n_outcomes": n_outcomes,
            "n_with_mop": n_with_mop,
            "n_total_graded": n_total_graded,
        }

    # empirical is over MOP-backed wins/losses — same denominator as model_implied (WR-01)
    empirical = wins / max(1, n_with_mop)

    if n_with_mop == 0:
        return prev_factor, {
            "reason": "no MOP data available",
            "new_factor": prev_factor,
            "prev_factor": prev_factor,
            "n_outcomes": n_outcomes,
            "n_with_mop": n_with_mop,
            "n_total_graded": n_total_graded,
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
        "n_total_graded": n_total_graded,
    }


def read_graded_outcomes_for_sport(
    sport: str,
    path: Path | None = None,
    _wb_override: Any = None,
) -> dict[str, Any]:
    """Read graded PROP outcomes for a sport from master_pnl.xlsx Pick History.

    ``wins``, ``losses``, and ``mop_values`` are all drawn from the SAME
    MOP-backed population: only WIN/LOSS PROP rows that ALSO carry a present,
    parseable Model Over Probability value are counted.  This ensures
    ``empirical`` and ``model_implied`` in ``compute_calibration_target`` share
    the same denominator (WR-01 fix).

    ``n_total_graded`` is an INFORMATIONAL counter of every WIN/LOSS PROP row
    for the sport since INCEPTION_DATE regardless of MOP presence.  It is
    carried through for audit visibility only and MUST NOT affect gating.

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
    {wins, losses, mop_values, n_outcomes, n_with_mop, n_total_graded}

    wins + losses == len(mop_values) == n_with_mop (all MOP-backed).
    n_total_graded >= n_with_mop (includes rows without MOP).
    """
    result: dict[str, Any] = {
        "wins": 0,
        "losses": 0,
        "mop_values": [],
        "n_outcomes": 0,
        "n_with_mop": 0,
        "n_total_graded": 0,
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

    # Component E: optional column recording the per-row shrink factor applied by the
    # source-level calibration stopgap. When present (>0 and != 1.0) the stored MOP is
    # un-shrunk back to the RAW model probability so model_implied reflects the model's
    # TRUE over-confidence — otherwise the stopgap would poison its own calibration.
    # Absent (legacy rows / pre-migration / blank) -> stored MOP used as-is.
    shrink_col = h.get("Prob Shrink Factor")

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

        # Count all graded rows for informational audit (WR-01: n_total_graded)
        result["n_total_graded"] += 1

        # Only count wins/losses when MOP is present and parseable (WR-01 fix).
        # This ensures wins+losses == len(mop_values) so empirical and
        # model_implied share the same denominator in compute_calibration_target.
        if mop_raw is not None:
            try:
                mop_float = float(mop_raw)
                # Un-shrink to the RAW model probability when a shrink factor is recorded.
                if shrink_col is not None:
                    s_raw = row_vals[shrink_col]
                    if s_raw is not None:
                        try:
                            s = float(s_raw)
                            if s > 0 and s != 1.0:
                                mop_float = max(0.0, min(1.0, 0.5 + (mop_float - 0.5) / s))
                        except (ValueError, TypeError):
                            pass
                result["mop_values"].append(mop_float)
                if result_val == "WIN":
                    result["wins"] += 1
                else:
                    result["losses"] += 1
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


def probability_shrink_factor_from_cfg(
    cfg: dict[str, Any], sport: str, n_gate: int = N_GATE
) -> float:
    """Derive a per-sport probability shrink factor from a loaded calibration config.

    Returns ``s`` in ``[SHRINK_FLOOR, 1.0]``::

        s = (empirical - 0.5) / (model_implied - 0.5)

    computed from the most recent audit entry for ``sport`` that carries both
    ``empirical_hit_rate`` and ``model_implied`` (a "computed" entry).  Applied as
    ``p' = 0.5 + (p - 0.5) * s`` it makes the model's average over-confidence match
    its realized hit rate while shrinking both sides symmetrically toward 0.5.

    Returns 1.0 (NO shrink) when:
    - no computed entry exists for the sport (e.g. NBA, gate never met),
    - that entry's ``n_with_mop`` < ``n_gate``,
    - the model is NOT overconfident (``empirical >= model_implied`` -> s would be >= 1),
    - ``model_implied`` <= 0.5 (no over-side confidence worth shrinking),
    - the config is empty/malformed.

    ``s`` never exceeds 1.0 (never amplifies confidence) and is floored at
    ``SHRINK_FLOOR`` (never collapses everything to 0.5).  Never raises.
    """
    try:
        target = str(sport or "").upper()
        empirical: float | None = None
        model_implied: float | None = None
        n_with_mop = 0
        for entry in reversed((cfg or {}).get("audit", []) or []):
            if not isinstance(entry, dict):
                continue
            if str(entry.get("sport") or "").upper() != target:
                continue
            if entry.get("empirical_hit_rate") is not None and entry.get("model_implied") is not None:
                empirical = float(entry["empirical_hit_rate"])
                model_implied = float(entry["model_implied"])
                n_with_mop = int(entry.get("n_with_mop") or 0)
                break
        if empirical is None or model_implied is None:
            return 1.0
        if n_with_mop < n_gate:
            return 1.0
        if model_implied <= SHRINK_ANCHOR:
            return 1.0
        s = (empirical - SHRINK_ANCHOR) / (model_implied - SHRINK_ANCHOR)
        if s >= 1.0:
            return 1.0  # model not overconfident — never amplify
        return max(SHRINK_FLOOR, s)
    except Exception:
        return 1.0


def load_probability_shrink_factor(
    sport: str, path: Path = CALIBRATION_PATH, n_gate: int = N_GATE
) -> float:
    """Read calibration.json and derive the per-sport probability shrink factor.

    Returns 1.0 (no shrink) if the file is absent, corrupt, or has no computed
    entry for the sport.  Never raises.
    """
    try:
        if Path(path).exists():
            cfg = json.loads(Path(path).read_text(encoding="utf-8"))
            return probability_shrink_factor_from_cfg(cfg, sport, n_gate=n_gate)
    except Exception:
        pass
    return 1.0


def write_calibration_json(
    factors: dict[str, float],
    audit_entry: dict[str, Any],
    path: Path = CALIBRATION_PATH,
    max_audit: int = 52,
    fingerprints: dict[str, dict[str, int]] | None = None,
) -> None:
    """Write calibration factors and one audit entry to calibration.json atomically.

    Uses .json.tmp + os.replace for atomic writes (mirrors save_workbook_atomic pattern).
    Trims audit log to the last max_audit entries (~1 year at weekly cadence).
    Creates data/research/ directory if absent.

    ``fingerprints`` (optional): per-sport {wins, losses, n_with_mop} dict written
    to the ``fingerprints`` key in calibration.json.  Used by
    ``compute_and_update_calibration`` to detect unchanged data and skip re-stepping
    (WR-02 idempotence guard).  Does not affect ``load_calibration_factor``, which
    reads only the ``factors`` key.

    Parameters
    ----------
    factors:      {sport_upper: float} map of current factors for all sports
    audit_entry:  dict with per-sport audit fields (old→new factor, sample count, etc.)
    path:         override path (default: CALIBRATION_PATH)
    max_audit:    maximum audit entries to retain (default: 52)
    fingerprints: {sport_upper: {wins, losses, n_with_mop}} — persisted for idempotence
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

    # Merge fingerprints: preserve existing per-sport entries and update with new ones
    existing_fps: dict[str, Any] = dict(existing.get("fingerprints", {}))
    if fingerprints:
        existing_fps.update(fingerprints)

    doc: dict[str, Any] = {
        "version": 1,
        "updated_at": _now_iso(),
        "inception_date": INCEPTION_DATE,
        "factors": factors,
        "fingerprints": existing_fps,
        "audit": audit,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # atomic rename — same pattern as save_workbook_atomic


def _load_last_fingerprint(sport: str, path: Path) -> tuple[int, int, int] | None:
    """Read the last persisted data fingerprint for a sport from calibration.json.

    Returns (wins, losses, n_with_mop) if available, else None.
    """
    try:
        if path.exists():
            cfg = json.loads(path.read_text(encoding="utf-8"))
            fp = cfg.get("fingerprints", {}).get(sport.upper())
            if fp is not None:
                return (int(fp["wins"]), int(fp["losses"]), int(fp["n_with_mop"]))
    except Exception:
        pass
    return None


def compute_and_update_calibration(
    path: Path = CALIBRATION_PATH,
    master_path: Path | None = None,
    _wb_override: Any = None,
) -> dict[str, Any]:
    """Compute per-sport sigma scalers and write to calibration.json.

    Reads Pick History from master_pnl.xlsx, computes calibration targets for both
    sports (NBA + MLB), and writes the updated factors + audit entries atomically.

    Idempotence via data-fingerprint guard (WR-02 fix): before stepping a sport's
    factor, the freshly read (wins, losses, n_with_mop) is compared against the
    last persisted fingerprint for that sport.  If identical (no new graded data
    since the last calibration), the existing factor is kept unchanged and the
    audit reason is "no new graded data since last calibration".  The factor only
    steps when the fingerprint differs (new data arrived), preserving gradual
    convergence as real outcomes accumulate week to week.

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
    new_fingerprints: dict[str, dict[str, int]] = {}

    for sport in sports:
        try:
            counts = read_graded_outcomes_for_sport(
                sport, path=master_path, _wb_override=_wb_override
            )
            prev_factor = load_calibration_factor(sport, path=path)

            # WR-02: data-fingerprint idempotence guard
            current_fp = (counts["wins"], counts["losses"], counts["n_with_mop"])
            last_fp = _load_last_fingerprint(sport, path)
            if last_fp is not None and last_fp == current_fp:
                # No new graded data — keep existing factor, record no-op audit
                new_factor = prev_factor
                audit: dict[str, Any] = {
                    "reason": "no new graded data since last calibration",
                    "new_factor": prev_factor,
                    "prev_factor": prev_factor,
                    "n_outcomes": counts["n_outcomes"],
                    "n_with_mop": counts["n_with_mop"],
                    "n_total_graded": counts.get("n_total_graded", 0),
                }
            else:
                new_factor, audit = compute_calibration_target(
                    wins=counts["wins"],
                    losses=counts["losses"],
                    mop_values=counts["mop_values"],
                    prev_factor=prev_factor,
                    n_total_graded=counts.get("n_total_graded", 0),
                )

            audit["sport"] = sport
            audit["updated_at"] = _now_iso()
            factors[sport] = new_factor
            audits.append(audit)
            per_sport_counts[sport] = counts
            # Persist fingerprint so next run can detect unchanged data
            new_fingerprints[sport] = {
                "wins": counts["wins"],
                "losses": counts["losses"],
                "n_with_mop": counts["n_with_mop"],
            }
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
            per_sport_counts[sport] = {
                "wins": 0, "losses": 0, "mop_values": [],
                "n_outcomes": 0, "n_with_mop": 0, "n_total_graded": 0,
            }

    # Write one calibration.json with all sports; one audit entry per sport
    for audit_entry in audits:
        write_calibration_json(
            factors, audit_entry, path=path, fingerprints=new_fingerprints
        )

    return {
        "factors": factors,
        "audits": audits,
        "per_sport_counts": per_sport_counts,
    }
