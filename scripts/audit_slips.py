#!/usr/bin/env python3
"""Audit SportsEdge generated slips."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import analyze_prop_correlation as corr
import build_slips
from slip_payouts import payout_multiplier

ROOT = Path(__file__).resolve().parents[1]
SLIP_DIR = ROOT / "data" / "research" / "slips"


def resolve_date(value: str | None) -> str:
    return corr.resolve_date(value)


def load_slips(date: str) -> dict[str, Any]:
    path = SLIP_DIR / f"slips_{date}.json"
    if not path.exists():
        raise FileNotFoundError(f"Missing slips file: {path}")
    return json.loads(path.read_text())


def load_correlation_map(date: str) -> dict[frozenset[str], dict[str, Any]]:
    path = SLIP_DIR / f"prop_correlations_{date}.json"
    if not path.exists():
        return {}
    return build_slips.correlation_lookup(json.loads(path.read_text()))


def has_stale_hit_rate_text(obj: Any) -> bool:
    if isinstance(obj, str):
        lowered = obj.lower()
        return "over_prob = hit_rate_l10" in lowered or "stale hit_rate" in lowered or "edge-based fixed nudge" in lowered
    if isinstance(obj, dict):
        return any(has_stale_hit_rate_text(v) for v in obj.values())
    if isinstance(obj, list):
        return any(has_stale_hit_rate_text(v) for v in obj)
    return False


def audit(payload: dict[str, Any], projections: list[dict[str, Any]], pair_map: dict[frozenset[str], dict[str, Any]]) -> dict[str, Any]:
    by_id = {build_slips.projection_key(p): p for p in projections}
    errors: list[str] = []
    warnings: list[str] = []
    slip_count = 0

    if has_stale_hit_rate_text(payload):
        errors.append("Slip output references stale hit-rate probability logic.")

    for category, slips in payload.get("slips", {}).items():
        for slip in slips:
            slip_count += 1
            legs = slip.get("legs") or []
            ids = [leg.get("prop_id") for leg in legs]
            if len(ids) != len(set(ids)):
                errors.append(f"{category}/{slip.get('name')}: duplicate exact prop appears in one slip")
            combined = slip.get("combined_probability")
            if not isinstance(combined, (int, float)) or not (0 < float(combined) <= 1):
                errors.append(f"{category}/{slip.get('name')}: combined probability is missing or impossible: {combined}")
            method = str(slip.get("combined_probability_method") or "")
            formula = str(slip.get("combined_probability_formula") or "")
            note = str(slip.get("combined_probability_note") or "")
            marked_approximate = bool(slip.get("combined_probability_is_approximate"))
            if not method or not formula:
                errors.append(f"{category}/{slip.get('name')}: combined probability method/formula missing")
            platform = slip.get("platform") or "PrizePicks"
            slip_type = slip.get("slip_type") or ("power" if len(legs) == 2 else "flex")
            if payout_multiplier(platform, slip_type, len(legs), len(legs)) is None:
                warnings.append(f"{category}/{slip.get('name')}: missing payout config for {platform} {slip_type} {len(legs)} legs")
            for leg in legs:
                pid = leg.get("prop_id")
                if pid not in by_id:
                    errors.append(f"{category}/{slip.get('name')}: prop does not exist in today's projections: {pid}")
                    continue
                src = by_id[pid]
                if str(src.get("confidence_tier")) == "SKIP" and "skip" not in str(slip.get("explanation", "")).lower():
                    errors.append(f"{category}/{slip.get('name')}: SKIP prop used without explanation: {pid}")
            for i, a in enumerate(ids):
                for b in ids[i + 1:]:
                    pair = pair_map.get(frozenset([a, b]))
                    label = pair.get("correlation_label") if pair else "unknown correlation"
                    if label == "negative/risky correlation" and "negative" not in str(slip.get("explanation", "")).lower():
                        errors.append(f"{category}/{slip.get('name')}: negative correlation included without explanation: {a} + {b}")
                    if label in {"strong positive correlation", "moderate positive correlation", "negative/risky correlation"} and not marked_approximate:
                        errors.append(f"{category}/{slip.get('name')}: correlated/negative pair probability is not marked approximate: {a} + {b}")
                    if label in {"strong positive correlation", "moderate positive correlation", "negative/risky correlation"} and "approx" not in note.lower() and "approx" not in method.lower():
                        errors.append(f"{category}/{slip.get('name')}: approximate correlated probability is not clearly labeled")
                    if label in {"strong positive correlation", "moderate positive correlation"} and not slip.get("is_correlated") and category in {"correlated_upside"}:
                        errors.append(f"{category}/{slip.get('name')}: correlated slip is not labeled correlated")
                    if category == "correlated_upside" and not slip.get("is_correlated"):
                        errors.append(f"{category}/{slip.get('name')}: correlated slip is not labeled correlated")

    if slip_count == 0:
        warnings.append("No slips generated; check projection eligibility thresholds.")
    return {"ok": not errors, "errors": errors, "warnings": warnings, "slip_count": slip_count}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="today")
    args = parser.parse_args()
    date = resolve_date(args.date)
    payload = load_slips(date)
    projections = corr.load_all_projections(date)
    pair_map = load_correlation_map(date)
    result = audit(payload, projections, pair_map)
    result.update({"date": date, "generated_at": datetime.now().isoformat(timespec="seconds")})
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
