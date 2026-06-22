#!/usr/bin/env python3
"""Analyze correlation between generated SportsEdge prop projections."""
from __future__ import annotations

import argparse
import itertools
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
PROJECTION_DIR = ROOT / "data" / "research" / "projections"
SLIP_DIR = ROOT / "data" / "research" / "slips"

POSITIVE_COMBO_TOKENS = (
    ("points", "points rebounds assists"),
    ("rebounds", "points rebounds assists"),
    ("assists", "points rebounds assists"),
    ("points rebounds", "points rebounds assists"),
    ("points assists", "points rebounds assists"),
    ("rebounds assists", "points rebounds assists"),
    ("hits", "hits runs rbis"),
    ("runs", "hits runs rbis"),
    ("rbis", "hits runs rbis"),
)
NEGATIVE_STAT_PAIRS = (
    ("pitcher strikeouts", "hits runs rbis"),
    ("strikeouts", "hits runs rbis"),
)
POSITIVE_MLB_PITCHER_DAMAGE_PAIRS = (
    ("hits allowed", "hits runs rbis"),
    ("pitcher hits allowed", "hits runs rbis"),
    ("earned runs", "hits runs rbis"),
    ("earned runs allowed", "hits runs rbis"),
)


def resolve_date(value: str | None) -> str:
    if not value or value == "today":
        return datetime.now().strftime("%Y-%m-%d")
    return value


def prop_id(prop: dict[str, Any]) -> str:
    sport = str(prop.get("sport") or "").upper()
    player = str(prop.get("player_name") or "").strip()
    stat = str(prop.get("stat_type") or "").strip()
    line = prop.get("pp_line")
    return f"{sport}:{player}:{stat}:{line}"


def stat_tokens(stat: str) -> set[str]:
    words = {w for w in stat.lower().replace("_", " ").split() if w not in {"player", "pitcher", "hitter", "total", "allowed", "over", "under"}}
    return words


def load_projection_file(sport: str, date: str) -> list[dict[str, Any]]:
    path = PROJECTION_DIR / sport.lower() / f"{sport}_projections_{date}.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text())
    rows = payload.get("projections", payload if isinstance(payload, list) else [])
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        enriched = dict(row)
        enriched.setdefault("sport", sport.upper())
        enriched["prop_id"] = prop_id(enriched)
        out.append(enriched)
    return out


def load_all_projections(date: str) -> list[dict[str, Any]]:
    return load_projection_file("nba", date) + load_projection_file("mlb", date)


def line_game_key(prop: dict[str, Any]) -> str:
    for key in ("game_id", "group_key", "event_id", "game", "matchup"):
        val = prop.get(key)
        if val:
            return str(val)
    return ""


def analyze_pair(a: dict[str, Any], b: dict[str, Any]) -> dict[str, Any]:
    same_player = (a.get("player_name") or "").lower() == (b.get("player_name") or "").lower()
    same_team = bool(a.get("team")) and str(a.get("team")) == str(b.get("team"))
    game_a, game_b = line_game_key(a), line_game_key(b)
    same_game = bool(game_a and game_b and game_a == game_b)
    stat_a = str(a.get("stat_type") or "").lower().replace("+", " ").replace("_", " ")
    stat_b = str(b.get("stat_type") or "").lower().replace("+", " ").replace("_", " ")
    tokens_a, tokens_b = stat_tokens(stat_a), stat_tokens(stat_b)
    overlapping_stat_categories = bool(tokens_a & tokens_b)

    reasons: list[str] = []
    score = 0
    label = "unknown correlation"
    risky = False

    if same_player:
        score += 4
        reasons.append("same player overlap")
    if overlapping_stat_categories:
        score += 2
        reasons.append("overlapping stat categories")
    if same_team:
        score += 1
        reasons.append("same team correlation")
    if same_game:
        score += 1
        reasons.append("same game correlation")

    for left, right in NEGATIVE_STAT_PAIRS:
        if (left in stat_a and right in stat_b) or (right in stat_a and left in stat_b):
            risky = True
            score -= 4
            reasons.append("negative/risky correlation by stat matchup")

    for left, right in POSITIVE_MLB_PITCHER_DAMAGE_PAIRS:
        if (left in stat_a and right in stat_b) or (right in stat_a and left in stat_b):
            score += 3
            reasons.append("positive MLB pitcher damage correlation")

    # Component-to-combo props are strongly related (e.g. hits vs HRR), but two distinct
    # hitters with the same combo stat should stay moderate rather than becoming a strong
    # same-stat stack.
    if stat_a != stat_b and any((x in stat_a and y in stat_b) or (y in stat_a and x in stat_b) for x, y in POSITIVE_COMBO_TOKENS):
        score += 2
        reasons.append("strong positive correlation via component/combo stat")

    if risky:
        label = "negative/risky correlation"
    elif score >= 6:
        label = "strong positive correlation"
    elif score >= 3:
        label = "moderate positive correlation"
    elif score >= 1:
        label = "weak/no correlation"
    else:
        label = "unknown correlation"

    return {
        "prop_a": a.get("prop_id") or prop_id(a),
        "prop_b": b.get("prop_id") or prop_id(b),
        "player_a": a.get("player_name"),
        "player_b": b.get("player_name"),
        "same_player_overlap": same_player,
        "same_team_correlation": same_team,
        "same_game_correlation": same_game,
        "overlapping_stat_categories": overlapping_stat_categories,
        "correlation_label": label,
        "correlation_score": score,
        "explanation": "; ".join(reasons) if reasons else "no reliable team/game/stat relationship available",
    }


def analyze(projections: list[dict[str, Any]], date: str) -> dict[str, Any]:
    pairs = [analyze_pair(a, b) for a, b in itertools.combinations(projections, 2)]
    counts: dict[str, int] = {}
    for pair in pairs:
        counts[pair["correlation_label"]] = counts.get(pair["correlation_label"], 0) + 1
    return {
        "date": date,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "projection_count": len(projections),
        "pair_count": len(pairs),
        "counts": counts,
        "pairs": pairs,
    }


def write_output(payload: dict[str, Any], date: str) -> Path:
    SLIP_DIR.mkdir(parents=True, exist_ok=True)
    path = SLIP_DIR / f"prop_correlations_{date}.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="today")
    args = parser.parse_args()
    date = resolve_date(args.date)
    projections = load_all_projections(date)
    payload = analyze(projections, date)
    path = write_output(payload, date)
    print(json.dumps({"status": "ok", "date": date, "output": str(path), "projection_count": len(projections), "pair_count": payload["pair_count"], "counts": payload["counts"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
