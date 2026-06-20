#!/usr/bin/env python3
"""Generate simple SportsEdge player prop projections from hit-rate DB.

Outputs:
- /Users/akashkalita/sports_picks/data/research/projections/{sport}/{sport}_projections_YYYY-MM-DD.json
- Enriches today's workbook Player Props sheet with Projection / Edge / Over% / EV / Model Tier.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from line_timing import LINE_TIMING_FIELDS
from workbook_io import safe_load_workbook, safe_save_workbook

BASE = Path.home() / "sports_picks"  # canonical ~/sports_picks install location per REQUIREMENTS.md DEF-02 / ROADMAP SC-5
DATA = BASE / "data"
HIT_RATE_DIR = DATA / "research" / "hit_rates"
PROJ_DIR = DATA / "research" / "projections"
NBA_DIR = DATA / "nba"
MLB_DIR = DATA / "mlb"
RUN_LOG = DATA / "pnl" / "logs" / "run_log.txt"
PT = ZoneInfo("America/Los_Angeles")

session = requests.Session()
session.headers.update({"User-Agent": "SportsEdge projection builder/1.0"})

TEAM_ENDPOINT = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}"

NBA_TEAM_IDS = {
    "ATL": "1", "BOS": "2", "BKN": "17", "CHA": "30", "CHI": "4", "CLE": "5", "DAL": "6", "DEN": "7",
    "DET": "8", "GS": "9", "GSW": "9", "HOU": "10", "IND": "11", "LAC": "12", "LAL": "13", "MEM": "29",
    "MIA": "14", "MIL": "15", "MIN": "16", "NO": "3", "NOP": "3", "NY": "18", "NYK": "18", "OKC": "25",
    "ORL": "19", "PHI": "20", "PHX": "21", "POR": "22", "SA": "24", "SAS": "24", "SAC": "23", "TOR": "28",
    "UTAH": "26", "UTA": "26", "WSH": "27",
}

MARKET_CONTEXT_FIELDS = [
    "game_total",
    "spread",
    "team_implied_total",
    "opponent_implied_total",
    "moneyline_implied_probability",
    "fd_total",
    "dk_total",
    "fd_spread",
    "dk_spread",
    "total_disagreement",
    "spread_disagreement",
    "market_movement_direction",
    "clv_baseline_total",
    "clv_baseline_spread",
    "market_context_available",
    "market_context_source",
]
BASE_HEADERS = ["Projection", "Edge", "Over%", "EV", "Model Tier", "Extended Reasoning"] + LINE_TIMING_FIELDS + MARKET_CONTEXT_FIELDS


def now_pt() -> str:
    return datetime.now(PT).strftime("%Y-%m-%d %H:%M:%S %Z")


def today_pt() -> str:
    return datetime.now(PT).strftime("%Y-%m-%d")


def resolve_date(value: str | None) -> str:
    """Resolve CLI date aliases used by the other SportsEdge scripts."""
    if value is None or str(value).strip().lower() in {"", "today"}:
        return today_pt()
    return str(value).strip()


def log(msg: str) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RUN_LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{now_pt()}] generate_projections — {msg}\n")


def normalize_player_name(value: Any) -> str:
    return " ".join(str(value or "").lower().replace(".", "").replace("'", "").split())


def normalize_prop_stat(value: Any) -> str:
    text = str(value or "").lower().replace("+", " ").replace("_", " ").replace("-", " ")
    compact = " ".join(text.split())
    aliases = [
        ("points rebounds assists", ["pts rebs asts", "pra"]),
        ("points rebounds", ["pts rebs"]),
        ("points assists", ["pts asts"]),
        ("rebounds assists", ["rebs asts"]),
        ("points", ["points", "pts"]),
        ("rebounds", ["rebounds", "rebs"]),
        ("assists", ["assists", "asts"]),
        ("threes", ["3 pt made", "3-pt made", "three pointers", "3pm"]),
        ("blocks", ["blocks", "blocked shots", "blks stls"]),
        ("steals", ["steals"]),
        ("turnovers", ["turnovers"]),
        ("strikeouts", ["strikeouts", "pitcher strikeouts", "hitter strikeouts"]),
        ("hits runs rbis", ["hits runs rbis", "h+r+rbi"]),
        ("total bases", ["total bases"]),
        ("hits", ["hits", "total hits"]),
        ("runs", ["runs", "runs scored"]),
        ("rbis", ["rbis", "runs batted in"]),
        ("earned runs", ["earned runs", "earned runs allowed"]),
        ("hits allowed", ["hits allowed"]),
        ("walks allowed", ["walks allowed", "pitcher walks allowed"]),
        ("outs", ["pitching outs", "outs"]),
        ("singles", ["singles"]),
        ("walks", ["walks", "hitter walks"]),
        ("pitcher fantasy score", ["pitcher fantasy score"]),
        ("hitter fantasy score", ["hitter fantasy score"]),
    ]
    for canon, vals in aliases:
        if compact == canon or compact in vals:
            return canon
    return compact


def to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        if isinstance(value, str):
            value = value.replace("%", "").strip()
        return float(value)
    except Exception:
        return None


def workbook_path(sport: str, date: str) -> Path:
    return (NBA_DIR if sport == "nba" else MLB_DIR) / f"{sport}_{date}.xlsx"


def sport_hit_rate_dir(sport: str) -> Path:
    return HIT_RATE_DIR / sport.lower()


def sport_projection_dir(sport: str) -> Path:
    return PROJ_DIR / sport.lower()


def ensure_headers(ws, headers: list[str]) -> dict[str, int]:
    current = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
    for header in headers:
        if header not in current:
            ws.cell(row=1, column=len(current) + 1, value=header)
            current.append(header)
    return {str(h): i + 1 for i, h in enumerate(current) if h}


def load_hit_rates(sport: str) -> dict[tuple[str, str], dict[str, Any]]:
    idx: dict[tuple[str, str], dict[str, Any]] = {}
    for path in sport_hit_rate_dir(sport).glob(f"{sport}_*.json"):
        try:
            doc = json.loads(path.read_text())
        except Exception:
            continue
        player = normalize_player_name(doc.get("player_name"))
        for stat, row in (doc.get("stats") or {}).items():
            rec = {"doc": doc, "stat": row, "file": str(path)}
            idx[(player, normalize_prop_stat(stat))] = rec
    return idx


def avg(values: list[float]) -> float:
    return round(sum(values) / len(values), 3) if values else 0.0


def avg_l20_from_sample(stat: dict[str, Any]) -> float:
    vals = [to_float(g.get("actual")) for g in stat.get("sample_games", [])[:20] if isinstance(g, dict)]
    vals = [v for v in vals if v is not None]
    return avg(vals)


def hit_count_l10(stat: dict[str, Any]) -> str:
    above = int(stat.get("games_above_line") or 0)
    sample = int(stat.get("sample_size") or 0)
    denom = min(10, sample) if sample else 10
    return f"{above}/{denom}"


def hit_count_against_line(stat: dict[str, Any], line: float, limit: int = 10) -> tuple[int, int, float | None]:
    vals = recent_actuals(stat, limit=limit)
    if not vals:
        return 0, 0, None
    hits = sum(1 for value in vals if value > line)
    return hits, len(vals), hits / len(vals)


def line_matches_today(hit_rate_line: float | None, pp_line: float, tolerance: float = 0.01) -> bool:
    return hit_rate_line is not None and abs(hit_rate_line - pp_line) <= tolerance


def effective_hit_rate_l10(stat: dict[str, Any], pp_line: float) -> dict[str, Any]:
    hit_rate_line = to_float(stat.get("line"))
    db_matches_today = line_matches_today(hit_rate_line, pp_line)
    if db_matches_today:
        above = int(stat.get("games_above_line") or 0)
        sample = int(stat.get("sample_size") or 0)
        denom = min(10, sample) if sample else 10
        rate = float(stat.get("hit_rate_l10") or 0)
        return {
            "rate": rate,
            "hits": above,
            "denom": denom,
            "source": "db_line_match",
            "db_line_matches_today": True,
            "hit_rate_db_line": hit_rate_line,
        }
    hits, denom, rate = hit_count_against_line(stat, pp_line)
    return {
        "rate": rate if rate is not None else 0.0,
        "hits": hits,
        "denom": denom,
        "source": "recomputed_today_line",
        "db_line_matches_today": False,
        "hit_rate_db_line": hit_rate_line,
    }


def normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def clamp_probability(probability: float) -> float:
    return max(0.05, min(0.95, probability))


def recent_actuals(stat: dict[str, Any], limit: int = 20) -> list[float]:
    vals = [to_float(g.get("actual")) for g in stat.get("sample_games", [])[:limit] if isinstance(g, dict)]
    return [v for v in vals if v is not None]


def fallback_sigma_for_stat(stat_name: str) -> float:
    stat = normalize_prop_stat(stat_name)
    fallback = {
        "points rebounds assists": 6.0,
        "points rebounds": 5.5,
        "points assists": 5.0,
        "rebounds assists": 4.0,
        "points": 4.5,
        "rebounds": 3.5,
        "assists": 3.0,
        "threes": 1.5,
        "blocks": 1.0,
        "steals": 1.0,
        "turnovers": 1.5,
        "strikeouts": 2.0,
        "hits runs rbis": 1.8,
        "total bases": 1.8,
        "hits": 1.0,
        "runs": 0.9,
        "rbis": 1.0,
        "earned runs": 1.8,
        "hits allowed": 2.0,
        "walks allowed": 1.2,
        "outs": 3.0,
        "singles": 0.9,
        "walks": 0.9,
        "pitcher fantasy score": 9.0,
        "hitter fantasy score": 4.0,
    }
    return fallback.get(stat, 2.5)


def estimate_sigma(stat: dict[str, Any], stat_name: str, sigma_floor: float = 0.75) -> tuple[float, str]:
    vals = recent_actuals(stat)
    if len(vals) >= 2:
        sigma = statistics.pstdev(vals)
        source = f"sample_games sigma n={len(vals)}"
    else:
        sigma = fallback_sigma_for_stat(stat_name)
        source = f"fallback {normalize_prop_stat(stat_name)} sigma"
    sigma = max(sigma_floor, sigma)
    return sigma, source


def model_over_probability(projection: float, line: float, sigma: float) -> float:
    safe_sigma = max(0.75, sigma)
    z = (line - projection) / safe_sigma
    return clamp_probability(1.0 - normal_cdf(z))


def calculate_ev(over_probability: float) -> float:
    return (over_probability * 0.909) - (1 - over_probability)


def parse_team_stat_value(obj: Any, wanted_names: set[str]) -> float | None:
    if isinstance(obj, dict):
        name = str(obj.get("name") or obj.get("shortDisplayName") or obj.get("displayName") or obj.get("label") or "").lower()
        if name in wanted_names or any(w in name for w in wanted_names):
            for key in ("value", "displayValue"):
                val = to_float(obj.get(key))
                if val is not None:
                    return val
        for v in obj.values():
            found = parse_team_stat_value(v, wanted_names)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = parse_team_stat_value(item, wanted_names)
            if found is not None:
                return found
    return None


def fetch_nba_pace_values() -> dict[str, float]:
    values: dict[str, float] = {}
    for abbr, team_id in NBA_TEAM_IDS.items():
        if abbr in values:
            continue
        try:
            r = session.get(TEAM_ENDPOINT.format(team_id=team_id), timeout=12)
            if r.status_code != 200:
                continue
            val = parse_team_stat_value(r.json(), {"pace", "possessions"})
            if val is not None and 80 <= val <= 120:
                values[abbr] = val
        except Exception:
            continue
    return values


def pace_factor_for(opponent: str, pace_values: dict[str, float]) -> tuple[float, str]:
    opp = str(opponent or "").upper().strip()
    if not pace_values or opp not in pace_values:
        return 1.0, "pace unavailable: neutral factor"
    league_avg = sum(pace_values.values()) / len(pace_values)
    opp_pace = pace_values[opp]
    if opp_pace > league_avg:
        return 1.05, f"opponent pace {opp_pace:.1f} > league avg {league_avg:.1f}"
    if opp_pace < league_avg:
        return 0.95, f"opponent pace {opp_pace:.1f} < league avg {league_avg:.1f}"
    return 1.0, f"opponent pace {opp_pace:.1f} near league avg {league_avg:.1f}"


def minutes_factor(trend: str) -> float:
    if trend == "up":
        return 1.03
    if trend == "down":
        return 0.94
    return 1.0


def confidence_tier(edge: float, over_prob: float, hit_rate_today: float, ev: float, flags: list[str], sample_size: int) -> str:
    if edge < 0.5 or over_prob < 0.52 or ev <= 0:
        return "SKIP"
    if sample_size < 2:
        return "SKIP"
    if hit_rate_today < 0.40:
        return "SKIP"
    if "MINUTES RISK" in flags:
        return "SKIP"
    if "SMALL SAMPLE" in flags and edge < 1.5:
        return "SKIP"
    if "BAD MATCHUP" in flags and edge < 1.0:
        return "SKIP"
    if edge >= 2.0 and over_prob >= 0.60 and hit_rate_today >= 0.60 and ev > 0.10 and sample_size >= 5:
        return "A"
    if edge >= 1.0 and over_prob >= 0.54 and hit_rate_today >= 0.50:
        return "B"
    if edge >= 0.5 and over_prob >= 0.52:
        return "C"
    return "SKIP"



def build_projection(player: str, team: str, stat_name: str, pp_line: float, hit_rec: dict[str, Any], sport: str, pace_values: dict[str, float], platform: str = "DFS") -> dict[str, Any]:
    doc = hit_rec["doc"]
    stat = hit_rec["stat"]
    avg_l5 = float(stat.get("avg_stat_l5") or 0)
    avg_l10 = float(stat.get("avg_stat_l10") or 0)
    avg_l20 = avg_l20_from_sample(stat)
    base = (avg_l5 * 0.45) + (avg_l10 * 0.35) + (avg_l20 * 0.20)
    pf, pace_reason = (pace_factor_for(doc.get("opponent") or "", pace_values) if sport == "nba" else (1.0, "MLB pace factor neutral"))
    trend = str(stat.get("minutes_trend") or "stable")
    mf = minutes_factor(trend)
    projection = base * pf * mf
    edge = projection - pp_line
    hr10 = float(stat.get("hit_rate_l10") or 0)
    sigma, sigma_source = estimate_sigma(stat, stat_name)
    over_prob = round(model_over_probability(projection, pp_line, sigma), 4)
    ev = calculate_ev(over_prob)
    flags: list[str] = []
    if float(stat.get("vs_opponent_hit_rate") or 0) <= 0.30:
        flags.append("BAD MATCHUP")
    if trend == "down":
        flags.append("MINUTES RISK")
    if int(stat.get("sample_size") or 0) < 5:
        flags.append("SMALL SAMPLE")
    sample_size = int(stat.get("sample_size") or 0)
    hit_rate_today_ctx = effective_hit_rate_l10(stat, pp_line)
    hit_rate_today = float(hit_rate_today_ctx["rate"] or 0)
    tier = confidence_tier(edge, over_prob, hit_rate_today, ev, flags, sample_size)
    hit_rate_line = to_float(stat.get("line"))
    hit_rate_line_text = f" at {hit_rate_line:.1f}" if hit_rate_line is not None else ""
    hit_rate_db_line_text = f"{hit_rate_line:.1f}" if hit_rate_line is not None else "n/a"
    hit_rate_today_text = f"{hit_rate_today_ctx['hits']}/{hit_rate_today_ctx['denom']}"
    reasoning = (
        f"Proj: {projection:.1f} vs Line: {pp_line:.1f} | Edge: {edge:+.1f} | "
        f"Model Over%: {over_prob:.0%} | Hit L10 Today Line: {hit_rate_today_text} at {pp_line:.1f} | "
        f"Historical Hit L10: {hit_count_l10(stat)}{hit_rate_line_text} | "
        f"Hit-rate DB line: {hit_rate_db_line_text} | Today {platform} line: {pp_line:.1f} | "
        f"EV: {ev:+.2f} | Tier hit-rate source: {hit_rate_today_ctx['source']} | "
        f"sigma={sigma:.2f} ({sigma_source}); base={base:.2f}; {pace_reason}; minutes_trend={trend}"
    )
    return {
        "player_name": player,
        "team": team,
        "stat_type": normalize_prop_stat(stat_name),
        "pp_line": round(pp_line, 3),
        "projection": round(projection, 3),
        "edge": round(edge, 3),
        "over_probability": round(over_prob, 4),
        "expected_value": round(ev, 4),
        "sigma": round(sigma, 4),
        "sigma_source": sigma_source,
        "confidence_tier": tier,
        "flags": flags,
        "reasoning": reasoning,
        "platform": platform,
        "hit_rate_l10": hr10,
        "hit_rate_l10_today_line": round(hit_rate_today, 4),
        "hit_rate_l10_today_count": f"{hit_rate_today_ctx['hits']}/{hit_rate_today_ctx['denom']}",
        "hit_rate_l10_tier_source": hit_rate_today_ctx["source"],
        "hit_rate_db_line": hit_rate_today_ctx["hit_rate_db_line"],
        "hit_rate_db_line_matches_today": hit_rate_today_ctx["db_line_matches_today"],
        "sport": sport.upper(),
        "position": doc.get("position", ""),
        "category": doc.get("category", ""),
        "hit_rate_l5": float(stat.get("hit_rate_l5") or 0),
        "avg_l5": avg_l5,
        "avg_l10": avg_l10,
        "avg_l20": avg_l20,
        "minutes_trend": trend,
        "sample_size": sample_size,
        "source_hit_rate_file": hit_rec.get("file"),
    }


def update_workbook_and_build(sport: str, date: str) -> dict[str, Any]:
    path = workbook_path(sport, date)
    if not path.exists():
        raise FileNotFoundError(f"Missing workbook: {path}")
    hit_idx = load_hit_rates(sport)
    pace_values = fetch_nba_pace_values() if sport == "nba" else {}
    wb = safe_load_workbook(path)
    if "Player Props" not in wb.sheetnames:
        raise RuntimeError(f"Workbook missing Player Props sheet: {path}")
    ws = wb["Player Props"]
    headers = ensure_headers(ws, BASE_HEADERS)
    projections: list[dict[str, Any]] = []
    rows_updated = 0
    rows_missing_hit_rate = 0
    seen_keys = set()
    for r in range(2, ws.max_row + 1):
        player = ws.cell(r, headers.get("Player Name", 0)).value if headers.get("Player Name") else None
        stat_name = ws.cell(r, headers.get("Stat", 0)).value if headers.get("Stat") else None
        line = ws.cell(r, headers.get("Line", 0)).value if headers.get("Line") else None
        odds_type = ws.cell(r, headers.get("Odds Type", 0)).value if headers.get("Odds Type") else None
        if str(odds_type or "").lower() not in {"standard", ""}:
            continue
        if not player or not stat_name:
            continue
        pp_line = to_float(line)
        if pp_line is None:
            continue
        hit_rec = hit_idx.get((normalize_player_name(player), normalize_prop_stat(stat_name)))
        if not hit_rec:
            rows_missing_hit_rate += 1
            continue
        platform = ws.cell(r, headers.get("Platform", 0)).value if headers.get("Platform") else "DFS"
        proj = build_projection(str(player), str(ws.cell(r, headers.get("Team", 0)).value or ""), str(stat_name), pp_line, hit_rec, sport, pace_values, str(platform or "DFS"))
        timing_ctx = {
            "line_timing": ws.cell(r, headers.get("Line Timing", 0)).value if headers.get("Line Timing") else "unknown",
            "line_timing_confidence": ws.cell(r, headers.get("Line Timing Confidence", 0)).value if headers.get("Line Timing Confidence") else "low",
            "line_timing_reason": ws.cell(r, headers.get("Line Timing Reason", 0)).value if headers.get("Line Timing Reason") else "not available in workbook",
            "source_timestamp": ws.cell(r, headers.get("Source Timestamp", 0)).value if headers.get("Source Timestamp") else None,
            "game_start_time": ws.cell(r, headers.get("Game Start Time", 0)).value if headers.get("Game Start Time") else None,
            "minutes_to_game_start": ws.cell(r, headers.get("Minutes To Start", 0)).value if headers.get("Minutes To Start") else None,
            "minutes_since_game_start": ws.cell(r, headers.get("Minutes Since Start", 0)).value if headers.get("Minutes Since Start") else None,
            "live_line_flag": ws.cell(r, headers.get("Live Line Flag", 0)).value if headers.get("Live Line Flag") else False,
            "stale_line_flag": ws.cell(r, headers.get("Stale Line Flag", 0)).value if headers.get("Stale Line Flag") else False,
        }
        market_ctx = {field: ws.cell(r, headers.get(field, 0)).value if headers.get(field) else None for field in MARKET_CONTEXT_FIELDS}
        proj.update(timing_ctx)
        proj.update(market_ctx)
        normalized_timing = str(proj.get("line_timing") or "unknown").strip().lower() or "unknown"
        proj["line_timing"] = normalized_timing
        if normalized_timing == "unknown" and not proj.get("line_timing_confidence"):
            proj["line_timing_confidence"] = "low"
        if normalized_timing == "unknown" and not proj.get("line_timing_reason"):
            proj["line_timing_reason"] = "line timing unavailable in workbook/current board"
        if normalized_timing != "pregame":
            proj["pregame_confidence_tier"] = proj.get("confidence_tier")
            proj["confidence_tier"] = "SKIP"
            proj.setdefault("flags", []).append("LINE TIMING NOT PREGAME")
            proj["diagnostic_only"] = True
            proj["reasoning"] += f" | Line timing {normalized_timing}: diagnostic only; do not use pregame confidence/hit-rate calibration."
        # Keep one projection per platform/player/stat/line in JSON, but update every matching sheet row.
        key = (str(platform or "DFS"), normalize_player_name(player), normalize_prop_stat(stat_name), pp_line)
        if key not in seen_keys:
            projections.append(proj)
            seen_keys.add(key)
        ws.cell(r, headers["Projection"], proj["projection"])
        ws.cell(r, headers["Edge"], proj["edge"])
        ws.cell(r, headers["Over%"], proj["over_probability"])
        ws.cell(r, headers["EV"], proj["expected_value"])
        ws.cell(r, headers["Model Tier"], proj["confidence_tier"])
        ws.cell(r, headers["Extended Reasoning"], proj["reasoning"])
        # If a current confidence column exists, override only when model differs by more than one level.
        if "Confidence Tier" in headers:
            current = str(ws.cell(r, headers["Confidence Tier"]).value or "").upper()
            order = {"SKIP": 0, "C": 1, "B": 2, "A": 3}
            model = proj["confidence_tier"]
            if current in order and model in order and abs(order[model] - order[current]) > 1:
                ws.cell(r, headers["Confidence Tier"], model)
        rows_updated += 1
    safe_save_workbook(wb, path)
    out_dir = sport_projection_dir(sport)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{sport}_projections_{date}.json"
    doc = {
        "sport": sport.upper(),
        "date": date,
        "last_updated": now_pt(),
        "source_workbook": str(path),
        "source_hit_rate_dir": str(sport_hit_rate_dir(sport)),
        "pace_records": len(pace_values),
        "projection_count": len(projections),
        "rows_updated": rows_updated,
        "rows_missing_hit_rate": rows_missing_hit_rate,
        "projections": projections,
    }
    out.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"{sport.upper()} projections complete: projections={len(projections)} rows_updated={rows_updated} output={out}")
    return {"sport": sport, "output": str(out), "projection_count": len(projections), "rows_updated": rows_updated, "rows_missing_hit_rate": rows_missing_hit_rate, "pace_records": len(pace_values), "first5": projections[:5]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", choices=["nba", "mlb", "both"], default="both")
    ap.add_argument("--date", default=today_pt())
    args = ap.parse_args()
    run_date = resolve_date(args.date)
    sports = ["nba", "mlb"] if args.sport == "both" else [args.sport]
    results = []
    status = "ok"
    for sport in sports:
        try:
            results.append(update_workbook_and_build(sport, run_date))
        except Exception as e:
            status = "partial_failed"
            results.append({"sport": sport, "status": "failed", "error": str(e)})
            log(f"{sport.upper()} projections failed: {e}")
    print(json.dumps({"status": status, "date": run_date, "output_dir": str(PROJ_DIR), "results": results}, indent=2, ensure_ascii=False))
    return 0 if status == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
