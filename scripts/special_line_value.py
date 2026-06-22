#!/usr/bin/env python3
"""Gate 11 special-line value evaluation for Demon/Goblin PrizePicks props.

Unknown Demon/Goblin multipliers are not Gate 11 failures. They are actionable
Conditional Specials only when Gates 1-10 pass and the required threshold is
realistic; otherwise they are Special Line Rejections.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
PAYOUT_CONFIG_PATH = ROOT / "data" / "research" / "platform_payouts.json"
OVERRIDE_PATH = ROOT / "data" / "research" / "special_line_actual_multipliers.json"
SPECIAL_LINES_DIR = ROOT / "data" / "research" / "special_lines"
SPECIAL_EMOJIS = {"standard": "⚪", "demon": "😈", "goblin": "🟢", "unconfirmed": "⚪"}
SPECIAL_TYPE_UNCONFIRMED = "SPECIAL_TYPE_UNCONFIRMED"
ACTIONABLE_STATUSES = {
    "CONDITIONAL_DEMON_GOOD",
    "CONDITIONAL_DEMON_RISKY",
    "CONDITIONAL_GOBLIN_GOOD",
    "CONDITIONAL_GOBLIN_RISKY",
}
REJECTION_STATUSES = {
    "DEMON_TOO_RISKY",
    "GOBLIN_TOO_EXPENSIVE",
    "DEMON_SKIP_STANDARD_BETTER",
    "GOBLIN_SKIP_STANDARD_BETTER",
    "DEMON_REJECTED_MULTIPLIER_TOO_LOW",
    "GOBLIN_REJECTED_MULTIPLIER_TOO_LOW",
    "DEMON_REJECTED_NEGATIVE_EV",
    "GOBLIN_REJECTED_NEGATIVE_EV",
}
STATUS_PRIORITY = {
    "CONDITIONAL_GOBLIN_GOOD": 1,
    "CONDITIONAL_DEMON_GOOD": 2,
    "CONDITIONAL_GOBLIN_RISKY": 3,
    "CONDITIONAL_DEMON_RISKY": 4,
}
CONDITIONAL_SPECIALS_HEADERS = [
    "Date", "Sport", "Platform", "Emoji", "Line Type", "Player", "Stat", "Side", "Special Line",
    "Projection", "Probability", "Break-even Multiplier", "Required Use Multiplier",
    "Conditional Instruction", "Gate 11 Status", "Status", "Standard Line", "Standard EV",
    "Standard vs Special Recommendation", "Actual Multiplier", "Multiplier Known", "Notes",
]


def load_payout_config(path: Path | str = PAYOUT_CONFIG_PATH) -> dict[str, Any]:
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else {}


def special_policy(platform: str = "PrizePicks", config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = config if config is not None else load_payout_config()
    return (cfg.get(platform, {}) or {}).get("special_line_policy", {})


def _nested_get(record: dict[str, Any], dotted_field: str) -> Any:
    cur: Any = record
    for part in dotted_field.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _normalize_line_type_value(value: Any) -> str | None:
    text = str(value or "").strip().lower()
    return text if text in {"standard", "demon", "goblin"} else None


def classify_special_line_type(record: dict[str, Any] | None) -> dict[str, Any]:
    """Classify line type only from explicit source metadata.

    Demon/Goblin status must never be inferred from model probability, model edge,
    projection-vs-line movement, or standard-line comparisons. PrizePicks exposes
    this as projection.attributes.odds_type; flattened rows preserve it as
    odds_type. Missing or unrecognized metadata defaults to standard/unconfirmed,
    never Demon/Goblin.
    """
    record = record or {}
    for field in ("odds_type", "attributes.odds_type", "line_type"):
        raw = _nested_get(record, field)
        normalized = _normalize_line_type_value(raw)
        if normalized:
            return {
                "line_type": normalized,
                "special_type_confirmed": True,
                "line_type_source_field": field,
                "line_type_source_raw": raw,
                "line_type_classification_method": "explicit_source_metadata",
                "line_type_classification_status": "CONFIRMED_EXPLICIT",
            }
    return {
        "line_type": "standard",
        "special_type_confirmed": False,
        "line_type_source_field": None,
        "line_type_source_raw": None,
        "line_type_classification_method": "missing_or_unrecognized_metadata_default_standard",
        "line_type_classification_status": SPECIAL_TYPE_UNCONFIRMED,
    }


def canonical_line_type(value: Any) -> str:
    text = _normalize_line_type_value(value)
    return text or "standard"


def normalize_match_text(value: Any) -> str:
    """Normalize player/stat/matchup text for platform-neutral matching."""
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def standard_line_match(
    special_prop: dict[str, Any],
    props: Iterable[dict[str, Any]],
    projection_index: dict[Any, dict[str, Any]] | None = None,
    *,
    sport: str = "",
    date: str = "",
    platform: str = "PrizePicks",
) -> dict[str, Any]:
    """Find a true same-player/stat/side/date/game/platform standard-line match."""
    projection_index = projection_index or {}
    player = normalize_match_text(special_prop.get("player_name") or special_prop.get("player"))
    stat = normalize_match_text(special_prop.get("stat_name") or special_prop.get("stat") or special_prop.get("stat_type"))
    side = normalize_match_text(special_prop.get("side") or "Over") or "over"
    game_id = str(special_prop.get("game_id") or special_prop.get("event_id") or "").strip()
    matchup = normalize_match_text(special_prop.get("matchup") or special_prop.get("game") or special_prop.get("description"))

    def unavailable(reason: str) -> dict[str, Any]:
        confidence = "none" if reason.startswith("no_") else "ambiguous" if reason.startswith("ambiguous") else "invalid"
        return {
            "standard_line_available": False,
            "standard_line_match_confidence": confidence,
            "standard_line_match_reason": reason,
            "standard_line": None,
            "standard_line_probability": None,
            "standard_line_EV": None,
        }

    matches: list[dict[str, Any]] = []
    for prop in props:
        if canonical_line_type(prop.get("odds_type") or prop.get("line_type")) != "standard":
            continue
        prop_platform = str(prop.get("platform") or "PrizePicks")
        if prop_platform.lower() != platform.lower():
            continue
        if sport and str(prop.get("sport") or prop.get("league_name") or sport).upper() not in {sport.upper(), ""}:
            continue
        if date and prop.get("date") not in {None, "", date}:
            continue
        if normalize_match_text(prop.get("player_name") or prop.get("player")) != player:
            continue
        if normalize_match_text(prop.get("stat_name") or prop.get("stat") or prop.get("stat_type")) != stat:
            continue
        if (normalize_match_text(prop.get("side") or "Over") or "over") != side:
            continue
        prop_game_id = str(prop.get("game_id") or prop.get("event_id") or "").strip()
        if game_id and prop_game_id and prop_game_id != game_id:
            continue
        prop_matchup = normalize_match_text(prop.get("matchup") or prop.get("game") or prop.get("description"))
        if not game_id and matchup and prop_matchup and prop_matchup != matchup:
            continue
        line = prop.get("line_score") if prop.get("line_score") is not None else prop.get("line") if prop.get("line") is not None else prop.get("pp_line")
        if line is None:
            continue
        matches.append(prop)

    if not matches:
        return unavailable("no_matched_standard_line")
    unique_lines = {str(m.get("line_score") if m.get("line_score") is not None else m.get("line") if m.get("line") is not None else m.get("pp_line")) for m in matches}
    unique_games = {str(m.get("game_id") or m.get("event_id") or "") for m in matches}
    if len(unique_lines) != 1 or (game_id and len(unique_games - {""}) > 1):
        return unavailable("ambiguous_standard_line_match")

    match = matches[0]
    line = match.get("line_score") if match.get("line_score") is not None else match.get("line") if match.get("line") is not None else match.get("pp_line")
    proj = projection_index.get((player, stat)) or {}
    if not proj:
        for key, value in projection_index.items():
            if isinstance(key, tuple) and len(key) >= 2 and normalize_match_text(key[0]) == player and normalize_match_text(key[1]) == stat:
                proj = value or {}
                break
    probability = match.get("standard_line_probability") or match.get("over_probability") or match.get("probability") or proj.get("over_probability")
    ev = match.get("standard_line_EV") or match.get("standard_ev") or match.get("expected_value") or proj.get("expected_value")
    projection = match.get("projection") or proj.get("projection")
    if probability is None or ev is None or projection is None:
        return unavailable("matched_standard_line_missing_model_values")
    return {
        "standard_line_available": True,
        "standard_line_match_confidence": "high",
        "standard_line_match_reason": "matched_same_player_stat_side_game_platform",
        "standard_line": line,
        "standard_line_probability": float(probability),
        "standard_line_EV": float(ev),
    }


def break_even_multiplier(probability: float) -> float:
    probability = float(probability)
    if probability <= 0:
        return math.inf
    return 1.0 / probability


def required_use_multiplier(probability: float, line_type: str, platform: str = "PrizePicks", config: dict[str, Any] | None = None) -> float:
    line_type = canonical_line_type(line_type)
    policy = special_policy(platform, config).get(line_type, {})
    margin = float(policy.get("safety_margin") or 0.0)
    return break_even_multiplier(probability) + margin


def manual_override_key(platform: str, player: str, stat: str, side: str, line: Any) -> str:
    return f"{platform}:{player}:{stat}:{side}:{line}"


def load_manual_multiplier_overrides(path: Path | str = OVERRIDE_PATH) -> dict[str, Any]:
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else {}


def lookup_manual_multiplier(date: str, platform: str, player: str, stat: str, side: str, line: Any, overrides: dict[str, Any] | None = None) -> dict[str, Any] | None:
    data = overrides if overrides is not None else load_manual_multiplier_overrides()
    key = manual_override_key(platform, player, stat, side, line)
    return (data.get(date, {}) or {}).get(key)


def _unknown_status(line_type: str, required: float, platform: str = "PrizePicks", config: dict[str, Any] | None = None) -> str:
    policy = special_policy(platform, config).get(line_type, {})
    good = float(policy.get("good_threshold_max") or 0)
    risky = float(policy.get("risky_threshold_max") or 0)
    prefix = "DEMON" if line_type == "demon" else "GOBLIN"
    if required <= good:
        return f"CONDITIONAL_{prefix}_GOOD"
    if required <= risky:
        return f"CONDITIONAL_{prefix}_RISKY"
    return "DEMON_TOO_RISKY" if line_type == "demon" else "GOBLIN_TOO_EXPENSIVE"


def _standard_better(line_type: str, special_ev: float | None, standard_ev: Any, standard_line_available: bool = False) -> bool:
    if not standard_line_available:
        return False
    try:
        std = float(standard_ev)
    except (TypeError, ValueError):
        return False
    if special_ev is None or not math.isfinite(special_ev):
        return False
    # Clear advantage only: avoid downgrading specials on rounding noise.
    return std > special_ev + 0.02


def evaluate_special_line(
    *,
    line_type: str,
    probability: float,
    platform: str = "PrizePicks",
    player: str = "",
    stat: str = "",
    side: str = "Over",
    line: Any = "",
    projection: Any = None,
    standard_line: Any = None,
    standard_probability: float | None = None,
    standard_ev: Any = None,
    standard_line_probability: float | None = None,
    standard_line_EV: Any = None,
    standard_line_available: bool = False,
    standard_line_match_confidence: str = "none",
    standard_line_match_reason: str = "no_matched_standard_line",
    actual_multiplier: float | None = None,
    normal_gates_pass: bool = True,
    gates_1_10_pass: bool | None = None,
    date: str | None = None,
    overrides: dict[str, Any] | None = None,
    config: dict[str, Any] | None = None,
    special_type_confirmed: bool = True,
    line_type_source_field: str | None = None,
    line_type_source_raw: Any = None,
    line_type_classification_method: str | None = None,
    line_type_classification_status: str | None = None,
) -> dict[str, Any]:
    """Evaluate Gate 11 and special-line status for one prop.

    ``normal_gates_pass``/``gates_1_10_pass`` represent Gates 1-10. Unknown
    multipliers return ``PENDING_MULTIPLIER_CONFIRMATION`` when otherwise
    actionable, never ``FAIL_SPECIAL_VALUE`` just because the multiplier is
    unknown.
    """
    if gates_1_10_pass is not None:
        normal_gates_pass = bool(gates_1_10_pass)
    probability = float(probability)
    if standard_probability is None and standard_line_probability is not None:
        standard_probability = standard_line_probability
    if standard_ev is None and standard_line_EV is not None:
        standard_ev = standard_line_EV
    line_type = canonical_line_type(line_type)
    emoji = SPECIAL_EMOJIS[line_type]
    if line_type == "standard":
        return {
            "emoji": emoji,
            "line_type": "standard",
            "gate11_status": "PASS_STANDARD",
            "gate11_pass": True,
            "final_approved": bool(normal_gates_pass),
            "conditional_special": False,
            "manual_review": False,
            "status": "PASS_STANDARD",
            "special_line_value_status": "PASS_STANDARD",
            "break_even_multiplier": None,
            "required_use_multiplier": None,
            "conditional_instruction": "⚪ Standard exact line; Gate 11 Status: PASS_STANDARD.",
            "actual_multiplier": actual_multiplier,
            "multiplier_known": actual_multiplier is not None,
            "exact_ev": None,
            "payout_confidence": "standard",
            "needs_payout_reconciliation": False,
            "standard_line_available": bool(standard_line_available),
            "standard_line_match_confidence": standard_line_match_confidence,
            "standard_line_match_reason": standard_line_match_reason,
            "standard_line": standard_line,
            "standard_line_probability": standard_probability,
            "standard_line_EV": standard_ev,
            "standard_ev": standard_ev,
            "standard_vs_special_recommendation": "Standard line eligible if Gates 1-10 pass.",
            "special_type_confirmed": special_type_confirmed,
            "line_type_source_field": line_type_source_field,
            "line_type_source_raw": line_type_source_raw,
            "line_type_classification_method": line_type_classification_method,
            "line_type_classification_status": line_type_classification_status or ("CONFIRMED_EXPLICIT" if special_type_confirmed else SPECIAL_TYPE_UNCONFIRMED),
        }

    override_source = None
    if actual_multiplier is None and date:
        override = lookup_manual_multiplier(date, platform, player, stat, side, line, overrides)
        if override:
            actual_multiplier = float(override.get("actual_multiplier"))
            override_source = override.get("source")

    be = break_even_multiplier(probability)
    req = required_use_multiplier(probability, line_type, platform, config)
    label = "Demon" if line_type == "demon" else "Goblin"
    verb = "Demon multiplier" if line_type == "demon" else "Goblin payout"
    instruction = f"{emoji} ONLY USE IF {verb} is at least {req:.2f}x"
    if line_type == "goblin":
        instruction += f". Do not use if below {req:.2f}x."
    prefix = "DEMON" if line_type == "demon" else "GOBLIN"
    special_ev_at_required = probability * req - 1.0 if math.isfinite(req) else None

    standard_line_available = bool(standard_line_available and standard_line is not None and standard_probability is not None and standard_ev is not None)
    if not standard_line_available:
        standard_line = None
        standard_probability = None
        standard_ev = None
        standard_line_match_confidence = standard_line_match_confidence or "none"
        standard_line_match_reason = standard_line_match_reason or "no_matched_standard_line"

    if actual_multiplier is None:
        status = _unknown_status(line_type, req, platform, config)
        if _standard_better(line_type, special_ev_at_required, standard_ev, standard_line_available):
            status = f"{prefix}_SKIP_STANDARD_BETTER"
        actionable = status in ACTIONABLE_STATUSES and bool(normal_gates_pass)
        gate11_status = "PENDING_MULTIPLIER_CONFIRMATION" if status in ACTIONABLE_STATUSES else "FAIL_SPECIAL_VALUE"
        return {
            "emoji": emoji,
            "line_type": line_type,
            "gate11_status": gate11_status,
            "gate11_pass": False,
            "final_approved": False,
            "conditional_special": actionable,
            "manual_review": False,
            "status": status,
            "special_line_value_status": status,
            "break_even_multiplier": round(be, 4) if math.isfinite(be) else math.inf,
            "required_use_multiplier": round(req, 4) if math.isfinite(req) else math.inf,
            "conditional_instruction": instruction,
            "actual_multiplier": None,
            "multiplier_known": False,
            "exact_ev": None,
            "payout_confidence": "pending_multiplier_confirmation",
            "needs_payout_reconciliation": True,
            "standard_line_available": standard_line_available,
            "standard_line_match_confidence": standard_line_match_confidence,
            "standard_line_match_reason": standard_line_match_reason,
            "standard_line": standard_line,
            "standard_line_probability": standard_probability,
            "standard_line_EV": standard_ev,
            "special_line_probability": probability,
            "probability_delta_vs_standard": (round(probability - float(standard_probability), 6) if standard_probability is not None else None),
            "edge_at_special_line": special_ev_at_required,
            "standard_ev": standard_ev,
            "standard_vs_special_recommendation": (
                "Prefer standard line; special threshold is not attractive enough."
                if status.endswith("SKIP_STANDARD_BETTER") else
                f"Pending Gate 11 multiplier confirmation; compare app multiplier to {req:.2f}x before use."
                if standard_line_available else
                "No matched standard line available; evaluate special only by required multiplier."
            ),
            "special_type_confirmed": special_type_confirmed,
            "line_type_source_field": line_type_source_field,
            "line_type_source_raw": line_type_source_raw,
            "line_type_classification_method": line_type_classification_method,
            "line_type_classification_status": line_type_classification_status or ("CONFIRMED_EXPLICIT" if special_type_confirmed else SPECIAL_TYPE_UNCONFIRMED),
        }

    exact_ev = probability * float(actual_multiplier) - 1.0
    if _standard_better(line_type, exact_ev, standard_ev, standard_line_available):
        status = f"{prefix}_SKIP_STANDARD_BETTER"
        final = False
    elif exact_ev <= 0:
        status = f"{prefix}_REJECTED_NEGATIVE_EV"
        final = False
    elif float(actual_multiplier) < req:
        status = f"{prefix}_REJECTED_MULTIPLIER_TOO_LOW"
        final = False
    elif not normal_gates_pass:
        status = "FAILED_GATES_1_10"
        final = False
    else:
        status = f"{prefix}_APPROVED_EXACT"
        final = True
    return {
        "emoji": emoji,
        "line_type": line_type,
        "gate11_status": "PASS_SPECIAL_EXACT" if final else "FAIL_SPECIAL_VALUE",
        "gate11_pass": final,
        "final_approved": final,
        "conditional_special": False,
        "manual_review": False,
        "status": status,
        "special_line_value_status": status,
        "break_even_multiplier": round(be, 4) if math.isfinite(be) else math.inf,
        "required_use_multiplier": round(req, 4) if math.isfinite(req) else math.inf,
        "conditional_instruction": instruction,
        "actual_multiplier": float(actual_multiplier),
        "multiplier_known": True,
        "exact_ev": round(exact_ev, 6),
        "payout_confidence": "exact_manual" if override_source or actual_multiplier is not None else "exact",
        "needs_payout_reconciliation": False,
        "override_source": override_source,
        "standard_line_available": standard_line_available,
        "standard_line_match_confidence": standard_line_match_confidence,
        "standard_line_match_reason": standard_line_match_reason,
        "standard_line": standard_line,
        "standard_line_probability": standard_probability,
        "standard_line_EV": standard_ev,
        "special_line_probability": probability,
        "probability_delta_vs_standard": (round(probability - float(standard_probability), 6) if standard_probability is not None else None),
        "edge_at_special_line": exact_ev,
        "standard_ev": standard_ev,
        "standard_vs_special_recommendation": "Use special exact multiplier." if final else "Skip special line; standard/threshold/EV/gate check failed.",
        "special_type_confirmed": special_type_confirmed,
        "line_type_source_field": line_type_source_field,
        "line_type_source_raw": line_type_source_raw,
        "line_type_classification_method": line_type_classification_method,
        "line_type_classification_status": line_type_classification_status or ("CONFIRMED_EXPLICIT" if special_type_confirmed else SPECIAL_TYPE_UNCONFIRMED),
    }


def conditional_special_row(date: str, sport: str, platform: str, evaluation: dict[str, Any], prop: dict[str, Any]) -> list[Any]:
    return [
        date, sport.upper(), platform, evaluation.get("emoji"), evaluation.get("line_type"),
        prop.get("player_name") or prop.get("player"), prop.get("stat_name") or prop.get("stat") or prop.get("stat_type"),
        prop.get("side") or "Over", prop.get("line_score") or prop.get("line") or prop.get("pp_line"),
        prop.get("projection"), prop.get("over_probability") or prop.get("probability"),
        evaluation.get("break_even_multiplier"), evaluation.get("required_use_multiplier"),
        evaluation.get("conditional_instruction"), evaluation.get("gate11_status"), evaluation.get("status"), prop.get("standard_line"),
        prop.get("standard_ev") or prop.get("expected_value"), evaluation.get("standard_vs_special_recommendation"),
        evaluation.get("actual_multiplier"), evaluation.get("multiplier_known"), prop.get("notes") or "",
    ]


def ensure_conditional_specials_sheet(wb: Any) -> Any:
    ws = wb["Conditional Specials"] if "Conditional Specials" in wb.sheetnames else wb.create_sheet("Conditional Specials")
    existing = [c.value for c in ws[1]] if ws.max_row else []
    if not any(existing) or ws.max_row == 1:
        for idx, header in enumerate(CONDITIONAL_SPECIALS_HEADERS, start=1):
            ws.cell(1, idx).value = header
        if ws.max_column > len(CONDITIONAL_SPECIALS_HEADERS):
            ws.delete_cols(len(CONDITIONAL_SPECIALS_HEADERS) + 1, ws.max_column - len(CONDITIONAL_SPECIALS_HEADERS))
    else:
        for header in CONDITIONAL_SPECIALS_HEADERS:
            if header not in existing:
                ws.cell(1, ws.max_column + 1).value = header
    return ws


def _candidate_record(candidate: dict[str, Any], evaluation: dict[str, Any]) -> dict[str, Any]:
    rec = dict(candidate)
    rec.update({
        "emoji": evaluation.get("emoji"),
        "line_type": evaluation.get("line_type"),
        "gate11_status": evaluation.get("gate11_status"),
        "status": evaluation.get("status"),
        "special_line_value_status": evaluation.get("special_line_value_status"),
        "break_even_multiplier": evaluation.get("break_even_multiplier"),
        "required_use_multiplier": evaluation.get("required_use_multiplier"),
        "conditional_instruction": evaluation.get("conditional_instruction"),
        "final_approved": evaluation.get("final_approved"),
        "actual_multiplier": evaluation.get("actual_multiplier"),
        "multiplier_known": evaluation.get("multiplier_known"),
        "exact_ev": evaluation.get("exact_ev"),
        "payout_confidence": evaluation.get("payout_confidence"),
        "needs_payout_reconciliation": evaluation.get("needs_payout_reconciliation"),
        "standard_line_available": evaluation.get("standard_line_available"),
        "standard_line_match_confidence": evaluation.get("standard_line_match_confidence"),
        "standard_line_match_reason": evaluation.get("standard_line_match_reason"),
        "standard_line": evaluation.get("standard_line"),
        "standard_line_probability": evaluation.get("standard_line_probability"),
        "standard_line_EV": evaluation.get("standard_line_EV"),
        "standard_ev": evaluation.get("standard_ev"),
        "standard_vs_special_recommendation": evaluation.get("standard_vs_special_recommendation"),
        "special_type_confirmed": evaluation.get("special_type_confirmed"),
        "line_type_source_field": evaluation.get("line_type_source_field"),
        "line_type_source_raw": evaluation.get("line_type_source_raw"),
        "line_type_classification_method": evaluation.get("line_type_classification_method"),
        "line_type_classification_status": evaluation.get("line_type_classification_status"),
    })
    return rec


def split_special_line_candidates(candidates: Iterable[dict[str, Any]], *, max_total: int = 10, max_per_sport: int = 5, max_per_player: int = 2) -> dict[str, Any]:
    actionable: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    total = 0
    for c in candidates:
        total += 1
        ev = c.get("evaluation") if isinstance(c.get("evaluation"), dict) else c
        rec = _candidate_record(c, ev)
        gates_pass = bool(c.get("gates_1_10_pass", c.get("normal_gates_pass", True)))
        timing = str(c.get("line_timing") or rec.get("line_timing") or "pregame").lower()
        timing_ok = timing == "pregame"
        if not timing_ok:
            rec["final_approved"] = False
            rec["conditional_special"] = False
            rec["live_model_required"] = timing in {"live", "in_game", "halftime"}
            rec["line_timing_special_note"] = "live model required; do not route to pregame Conditional Specials" if rec["live_model_required"] else "non-pregame timing; do not route to pregame Conditional Specials"
        confirmed = ev.get("special_type_confirmed", True) is True
        if confirmed and timing_ok and ev.get("status") in ACTIONABLE_STATUSES and ev.get("gate11_status") == "PENDING_MULTIPLIER_CONFIRMATION" and gates_pass:
            actionable.append(rec)
        else:
            rejected.append(rec)

    def sort_key(x: dict[str, Any]):
        return (
            STATUS_PRIORITY.get(str(x.get("status")), 99),
            float(x.get("required_use_multiplier") or math.inf),
            -float(x.get("probability") or x.get("over_probability") or 0),
            -float(x.get("edge") or x.get("model_edge") or x.get("expected_value") or 0),
        )

    actionable.sort(key=sort_key)
    shown: list[dict[str, Any]] = []
    per_sport: dict[str, int] = {}
    per_player: dict[str, int] = {}
    for rec in actionable:
        sport = str(rec.get("sport") or rec.get("Sport") or "").upper()
        player = str(rec.get("player") or rec.get("player_name") or rec.get("Player") or "")
        if len(shown) >= max_total:
            break
        if sport and per_sport.get(sport, 0) >= max_per_sport:
            continue
        if player and per_player.get(player, 0) >= max_per_player:
            continue
        shown.append(rec)
        if sport:
            per_sport[sport] = per_sport.get(sport, 0) + 1
        if player:
            per_player[player] = per_player.get(player, 0) + 1

    return {
        "actionable_conditional_specials": actionable,
        "special_line_rejections": rejected,
        "shown_conditional_specials": shown,
        "summary": {
            "total_special_candidates": total,
            "actionable_count": len(actionable),
            "rejected_count": len(rejected),
            "shown_in_telegram": len(shown),
        },
    }


def save_special_lines_json(date: str, payload: dict[str, Any], path: Path | None = None) -> Path:
    """Save date-level special-line JSON, merging NBA/MLB runs safely.

    Daily NBA and MLB runners execute separately but share the required
    ``special_lines_YYYY-MM-DD.json`` path.  Replace the current sport's prior
    rows and preserve the other sport so the final file remains date-level.
    """
    SPECIAL_LINES_DIR.mkdir(parents=True, exist_ok=True)
    target = path or (SPECIAL_LINES_DIR / f"special_lines_{date}.json")
    new_actionable = payload.get("actionable_conditional_specials", [])
    new_rejected = payload.get("special_line_rejections", [])
    sports = {str(x.get("sport") or x.get("Sport") or "").upper() for x in [*new_actionable, *new_rejected] if (x.get("sport") or x.get("Sport"))}
    existing = {}
    if target.exists():
        try:
            existing = json.loads(target.read_text())
        except Exception:
            existing = {}
    old_actionable = existing.get("actionable_conditional_specials", []) if isinstance(existing, dict) else []
    old_rejected = existing.get("special_line_rejections", []) if isinstance(existing, dict) else []
    if sports:
        old_actionable = [x for x in old_actionable if str(x.get("sport") or x.get("Sport") or "").upper() not in sports]
        old_rejected = [x for x in old_rejected if str(x.get("sport") or x.get("Sport") or "").upper() not in sports]
    combined_actionable = old_actionable + new_actionable
    combined_rejected = old_rejected + new_rejected
    serializable = {
        "actionable_conditional_specials": combined_actionable,
        "special_line_rejections": combined_rejected,
        "summary": {
            "total_special_candidates": len(combined_actionable) + len(combined_rejected),
            "actionable_count": len(combined_actionable),
            "rejected_count": len(combined_rejected),
            "shown_in_telegram": len(payload.get("shown_conditional_specials", [])),
        },
    }
    target.write_text(json.dumps(serializable, indent=2, sort_keys=True, default=str) + "\n")
    return target
