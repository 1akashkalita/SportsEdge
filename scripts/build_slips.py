#!/usr/bin/env python3
"""Build PrizePicks-style slips from SportsEdge projections and correlations."""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any

import analyze_prop_correlation as corr
from slip_payouts import payout_multiplier

ROOT = Path(__file__).resolve().parents[1]
SLIP_DIR = ROOT / "data" / "research" / "slips"

SAFE_FLAGS = {"BAD MATCHUP"}
KAT_NAMES = {"karl-anthony towns", "karl anthony towns"}


def resolve_date(value: str | None) -> str:
    return corr.resolve_date(value)


def load_correlations(date: str) -> dict[str, Any]:
    path = SLIP_DIR / f"prop_correlations_{date}.json"
    if not path.exists():
        projections = corr.load_all_projections(date)
        payload = corr.analyze(projections, date)
        corr.write_output(payload, date)
        return payload
    return json.loads(path.read_text())


def projection_key(row: dict[str, Any]) -> str:
    enriched = dict(row)
    enriched.setdefault("sport", str(row.get("sport") or "").upper())
    return row.get("prop_id") or corr.prop_id(enriched)


def is_eligible(prop: dict[str, Any], allow_skip: bool = False) -> bool:
    if str(prop.get("line_timing") or "pregame").lower() != "pregame":
        return False
    if prop.get("diagnostic_only"):
        return False
    if not allow_skip and str(prop.get("confidence_tier")) == "SKIP":
        return False
    if float(prop.get("edge") or 0) <= 0:
        return False
    if float(prop.get("expected_value") or 0) <= 0:
        return False
    if float(prop.get("over_probability") or 0) <= 0.5238:
        return False
    if int(prop.get("sample_size") or 0) < 2:
        return False
    flags = {str(f) for f in prop.get("flags") or []}
    if flags - SAFE_FLAGS:
        return False
    return True


def score_safety(prop: dict[str, Any]) -> float:
    p = float(prop.get("over_probability") or 0)
    ev = float(prop.get("expected_value") or 0)
    edge = float(prop.get("edge") or 0)
    sample = min(int(prop.get("sample_size") or 0), 20) / 20
    tier_bonus = {"A": 0.08, "B": 0.04, "C": 0.01}.get(str(prop.get("confidence_tier")), 0)
    return p * 2.0 + ev * 0.8 + min(edge / 10.0, 1.0) * 0.4 + sample * 0.2 + tier_bonus


def score_ev(prop: dict[str, Any]) -> float:
    return float(prop.get("expected_value") or 0) * 2 + float(prop.get("edge") or 0) / 10 + float(prop.get("over_probability") or 0)


def correlation_lookup(correlation_payload: dict[str, Any]) -> dict[frozenset[str], dict[str, Any]]:
    out: dict[frozenset[str], dict[str, Any]] = {}
    for pair in correlation_payload.get("pairs", []):
        out[frozenset([pair["prop_a"], pair["prop_b"]])] = pair
    return out


def get_pair(pair_map: dict[frozenset[str], dict[str, Any]], a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any] | None:
    return pair_map.get(frozenset([projection_key(a), projection_key(b)]))


def pair_label(pair_map: dict[frozenset[str], dict[str, Any]], a: dict[str, Any], b: dict[str, Any]) -> str:
    pair = get_pair(pair_map, a, b)
    return str(pair.get("correlation_label")) if pair else "unknown correlation"


def has_bad_pair(legs: list[dict[str, Any]], pair_map: dict[frozenset[str], dict[str, Any]], conservative: bool = False) -> bool:
    seen = set()
    for leg in legs:
        key = projection_key(leg)
        if key in seen:
            return True
        seen.add(key)
    for i, a in enumerate(legs):
        for b in legs[i + 1:]:
            label = pair_label(pair_map, a, b)
            if label == "negative/risky correlation":
                return True
            if conservative and (label in {"strong positive correlation", "moderate positive correlation"} or a.get("player_name") == b.get("player_name")):
                return True
    return False


def combined_probability_details(legs: list[dict[str, Any]], pair_map: dict[frozenset[str], dict[str, Any]], correlated: bool = False) -> dict[str, Any]:
    """Return a documented combined probability estimate.

    Independent slips use the exact independence assumption: product(p_i).
    Correlated slips do not have a real joint distribution model here, so they are
    explicitly marked approximate. Positive correlation moves the product toward,
    but never above, the weakest individual leg probability. Negative/risky
    correlation reduces the product.
    """
    probs = [float(leg.get("over_probability") or 0) for leg in legs]
    product = 1.0
    for prob in probs:
        product *= prob
    weakest = min(probs) if probs else 0.0
    labels: list[str] = []
    strong_pos = 0
    moderate_pos = 0
    negative = 0
    weak_or_unknown = 0
    for i, a in enumerate(legs):
        for b in legs[i + 1:]:
            label = pair_label(pair_map, a, b)
            labels.append(label)
            if label == "strong positive correlation":
                strong_pos += 1
            elif label == "moderate positive correlation":
                moderate_pos += 1
            elif label == "negative/risky correlation":
                negative += 1
            else:
                weak_or_unknown += 1

    is_approximate = correlated or strong_pos > 0 or moderate_pos > 0 or negative > 0
    adjusted = product
    formula = "product(p_i)"
    method = "exact_independent_product"
    note = "Exact only under the independent-leg assumption."

    if strong_pos or moderate_pos:
        # Heuristic: move product toward the weakest leg by a bounded correlation
        # factor. This keeps P(A and B) <= min(P(A), P(B)) for positive correlation.
        rho = min(strong_pos * 0.35 + moderate_pos * 0.20, 0.75)
        adjusted = product + rho * max(0.0, weakest - product)
        formula = "product(p_i) + rho * (min(p_i) - product(p_i)); rho=min(0.35*strong_pairs + 0.20*moderate_pairs, 0.75)"
        method = "approximate_positive_correlation_adjustment"
        note = "Approximate correlation estimate, not a real joint probability model; capped at weakest individual leg."
    if negative:
        adjusted *= max(0.40, 1 - 0.25 * negative)
        formula += "; then * max(0.40, 1 - 0.25*negative_pairs)"
        method = "approximate_negative_correlation_adjustment" if not (strong_pos or moderate_pos) else method
        note = "Approximate correlation estimate with negative/risky-pair penalty, not a real joint probability model."

    adjusted = round(max(0.0, min(adjusted, weakest if (strong_pos or moderate_pos) else 0.99)), 4)
    return {
        "combined_probability": adjusted,
        "independent_probability_product": round(product, 4),
        "combined_probability_method": method,
        "combined_probability_formula": formula,
        "combined_probability_is_exact": not is_approximate,
        "combined_probability_is_approximate": is_approximate,
        "combined_probability_note": note,
        "correlation_pair_labels": labels,
    }


def combined_probability(legs: list[dict[str, Any]], pair_map: dict[frozenset[str], dict[str, Any]], correlated: bool = False) -> float:
    return float(combined_probability_details(legs, pair_map, correlated)["combined_probability"])


def leg_summary(prop: dict[str, Any]) -> dict[str, Any]:
    return {
        "prop_id": projection_key(prop),
        "sport": prop.get("sport"),
        "player_name": prop.get("player_name"),
        "team": prop.get("team"),
        "stat_type": prop.get("stat_type"),
        "side": "OVER",
        "line": prop.get("pp_line"),
        "projection": prop.get("projection"),
        "edge": prop.get("edge"),
        "over_probability": prop.get("over_probability"),
        "expected_value": prop.get("expected_value"),
        "confidence_tier": prop.get("confidence_tier"),
        "flags": prop.get("flags", []),
    }


def make_slip(category: str, name: str, legs: list[dict[str, Any]], pair_map: dict[frozenset[str], dict[str, Any]], correlated: bool = False, explanation: str = "") -> dict[str, Any]:
    probability = combined_probability_details(legs, pair_map, correlated)
    leg_count = len(legs)
    slip_type = "power" if leg_count == 2 else "flex"
    if "power" in name.lower():
        slip_type = "power"
    standard_payout_multiplier = payout_multiplier("PrizePicks", slip_type, leg_count, leg_count)
    return {
        "category": category,
        "name": name,
        "platform": "PrizePicks",
        "slip_type": slip_type,
        "stake_units": 1.0,
        "is_correlated": correlated,
        "legs": [leg_summary(x) for x in legs],
        "leg_count": leg_count,
        "standard_payout_multiplier_if_perfect": standard_payout_multiplier,
        **probability,
        "combined_ev_score": round(sum(float(x.get("expected_value") or 0) for x in legs), 4),
        "explanation": explanation,
    }


def first_valid_combo(candidates: list[dict[str, Any]], n: int, pair_map: dict[frozenset[str], dict[str, Any]], conservative: bool = False) -> list[dict[str, Any]]:
    import itertools
    for combo in itertools.combinations(candidates, n):
        legs = list(combo)
        if not has_bad_pair(legs, pair_map, conservative=conservative):
            return legs
    return []


def build_slips(projections: list[dict[str, Any]], correlation_payload: dict[str, Any], date: str) -> dict[str, Any]:
    for row in projections:
        row["prop_id"] = projection_key(row)
    pair_map = correlation_lookup(correlation_payload)
    eligible = [p for p in projections if is_eligible(p)]
    by_safety = sorted(eligible, key=score_safety, reverse=True)
    by_ev = sorted(eligible, key=score_ev, reverse=True)
    slips: dict[str, Any] = {k: [] for k in ["safest_2_leg", "safest_3_leg", "highest_ev", "correlated_upside", "diversified", "kat_based"]}

    legs = first_valid_combo(by_safety, 2, pair_map, conservative=True)
    if legs:
        slips["safest_2_leg"].append(make_slip("safest_2_leg", "Safest 2-leg", legs, pair_map, False, "Highest model probability legs with positive EV and no strong overlap."))
    legs = first_valid_combo(by_safety, 3, pair_map, conservative=True)
    if legs:
        slips["safest_3_leg"].append(make_slip("safest_3_leg", "Safest 3-leg", legs, pair_map, False, "Three high-probability independent legs."))
    legs = first_valid_combo(by_ev, 2, pair_map, conservative=True)
    if legs:
        slips["highest_ev"].append(make_slip("highest_ev", "Highest EV 2-leg", legs, pair_map, False, "Highest EV independent legs that pass audit constraints."))
    legs = first_valid_combo(by_ev, 3, pair_map, conservative=True)
    if legs:
        slips["highest_ev"].append(make_slip("highest_ev", "Highest EV 3-leg", legs, pair_map, False, "Top EV independent 3-leg combination without strong overlap."))

    # Diversified: require unique players and avoid strong/moderate correlation.
    diversified = first_valid_combo(by_safety, 3, pair_map, conservative=True)
    if diversified:
        slips["diversified"].append(make_slip("diversified", "Diversified 3-leg", diversified, pair_map, False, "Avoids same-player overlap and strong positive correlation."))

    # Correlated upside: prefer explicitly positive pairs.
    correlated_pairs: list[tuple[float, dict[str, Any], dict[str, Any], dict[str, Any]]] = []
    by_id = {projection_key(p): p for p in eligible}
    for pair in correlation_payload.get("pairs", []):
        if pair.get("correlation_label") in {"strong positive correlation", "moderate positive correlation"}:
            a, b = by_id.get(pair.get("prop_a")), by_id.get(pair.get("prop_b"))
            if a and b:
                correlated_pairs.append((score_ev(a) + score_ev(b), pair, a, b))
    for _, pair, a, b in sorted(correlated_pairs, key=lambda x: x[0], reverse=True)[:3]:
        slips["correlated_upside"].append(make_slip("correlated_upside", "Correlated upside pair", [a, b], pair_map, True, f"Labeled correlated: {pair.get('explanation')}"))

    kats = [p for p in eligible if str(p.get("player_name", "")).lower() in KAT_NAMES]
    kats_by_ev = sorted(kats, key=score_ev, reverse=True)
    if len(kats_by_ev) >= 2:
        slips["kat_based"].append(make_slip("kat_based", "Best KAT-only stack", kats_by_ev[:2], pair_map, True, "Special KAT handling: overlapping KAT props intentionally allowed in KAT category."))
    if kats_by_ev:
        anchor = kats_by_ev[0]
        independent = [p for p in by_safety if p is not anchor and p.get("player_name") != anchor.get("player_name") and pair_label(pair_map, anchor, p) not in {"strong positive correlation", "moderate positive correlation", "negative/risky correlation"}]
        if independent:
            slips["kat_based"].append(make_slip("kat_based", "KAT anchor + safest independent leg", [anchor, independent[0]], pair_map, False, "KAT anchor paired with safest independent non-overlap leg."))
        pos = [p for p in by_ev if p is not anchor and pair_label(pair_map, anchor, p) in {"strong positive correlation", "moderate positive correlation"}]
        if pos:
            slips["kat_based"].append(make_slip("kat_based", "KAT anchor + positively correlated Knicks/game leg", [anchor, pos[0]], pair_map, True, "KAT anchor paired with positive correlation."))
        noncorr_ev = [p for p in by_ev if p is not anchor and p.get("player_name") != anchor.get("player_name") and pair_label(pair_map, anchor, p) not in {"strong positive correlation", "moderate positive correlation", "negative/risky correlation"}]
        if noncorr_ev:
            slips["kat_based"].append(make_slip("kat_based", "KAT anchor + highest-EV non-correlated leg", [anchor, noncorr_ev[0]], pair_map, False, "KAT anchor paired with highest-EV non-correlated leg."))

    avoid_pairing = [p for p in correlation_payload.get("pairs", []) if p.get("correlation_label") == "negative/risky correlation"][:25]
    return {
        "date": date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "projection_count": len(projections),
        "eligible_count": len(eligible),
        "slips": slips,
        "avoid_pairing": avoid_pairing,
        "warnings": [] if eligible else ["No eligible positive-EV props available."],
    }


def render_markdown(payload: dict[str, Any]) -> str:
    lines = [f"# SportsEdge Slips {payload['date']}", ""]
    for category, slips in payload["slips"].items():
        lines += [f"## {category}", ""]
        if not slips:
            lines += ["No slip generated.", ""]
            continue
        for slip in slips:
            lines.append(f"### {slip['name']}")
            prob_label = "Approx combined probability" if slip.get("combined_probability_is_approximate") else "Combined probability"
            lines.append(f"{prob_label}: {slip['combined_probability']:.1%} | EV score: {slip['combined_ev_score']:+.2f} | Type: {slip.get('slip_type')} | Perfect payout: {slip.get('standard_payout_multiplier_if_perfect')}x | Correlated: {slip['is_correlated']}")
            if slip.get("combined_probability_is_approximate"):
                lines.append(f"Probability note: {slip.get('combined_probability_note')} Formula: {slip.get('combined_probability_formula')}")
            lines.append(slip.get("explanation") or "")
            for leg in slip["legs"]:
                lines.append(f"- {leg['sport']} {leg['player_name']} {leg['stat_type']} OVER {leg['line']} | Proj {leg['projection']} | P {float(leg['over_probability']):.1%} | EV {float(leg['expected_value']):+.2f} | Tier {leg['confidence_tier']}")
            lines.append("")
    lines += ["## avoid_pairing", ""]
    for pair in payload.get("avoid_pairing", [])[:20]:
        lines.append(f"- {pair.get('player_a')} + {pair.get('player_b')}: {pair.get('explanation')}")
    return "\n".join(lines).rstrip() + "\n"


def write_outputs(payload: dict[str, Any], date: str) -> tuple[Path, Path]:
    SLIP_DIR.mkdir(parents=True, exist_ok=True)
    json_path = SLIP_DIR / f"slips_{date}.json"
    md_path = SLIP_DIR / f"slips_{date}.md"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    md_path.write_text(render_markdown(payload))
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="today")
    args = parser.parse_args()
    date = resolve_date(args.date)
    projections = corr.load_all_projections(date)
    correlation_payload = load_correlations(date)
    payload = build_slips(projections, correlation_payload, date)
    json_path, md_path = write_outputs(payload, date)
    print(json.dumps({"status": "ok", "date": date, "json": str(json_path), "markdown": str(md_path), "eligible_count": payload["eligible_count"], "slip_counts": {k: len(v) for k, v in payload["slips"].items()}, "avoid_pairing_count": len(payload.get("avoid_pairing", []))}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
