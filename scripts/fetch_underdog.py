#!/usr/bin/env python3
"""Underdog Fantasy DFS prop fetcher and endpoint auditor.

Endpoint:
  GET https://api.underdogfantasy.com/v1/over_under_lines

Boundary:
  Underdog is a first-class DFS prop source alongside PrizePicks. Its standard
  higher/lower rows can feed gates, projections, approved picks, CLV, and prop
  monitors. Underdog prices are preserved separately and are not mapped to
  PrizePicks Demon/Goblin payout logic.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

try:
    from line_timing import apply_line_timing
except Exception:  # pragma: no cover
    def apply_line_timing(row: dict[str, Any], board_pull_time: Any = None) -> dict[str, Any]:
        return row

ROOT = Path.home() / "sports_picks"
DATA_DIR = ROOT / "data"
RESEARCH_DIR = DATA_DIR / "research" / "underdog"
LOG_FILE = DATA_DIR / "pnl" / "logs" / "run_log.txt"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
RESEARCH_DIR.mkdir(parents=True, exist_ok=True)

ENDPOINT = "https://api.underdogfantasy.com/v1/over_under_lines"
LEAGUE_TO_SPORT_ID = {"nba": "NBA", "mlb": "MLB"}
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.3.1 Safari/605.1.15",
    "Origin": "https://underdogfantasy.com",
    "Referer": "https://underdogfantasy.com/",
}

STAT_ALIASES = {
    "nba": {
        "points": "points", "point": "points", "pts": "points",
        "rebounds": "rebounds", "rebound": "rebounds", "rebs": "rebounds",
        "assists": "assists", "assist": "assists", "asts": "assists",
        "pts_rebs_asts": "pts+rebs+asts", "pts rebs asts": "pts+rebs+asts", "points rebounds assists": "pts+rebs+asts", "pra": "pts+rebs+asts",
        "pts_rebs": "pts+rebs", "pts rebs": "pts+rebs", "points rebounds": "pts+rebs",
        "pts_asts": "pts+asts", "pts asts": "pts+asts", "points assists": "pts+asts",
        "rebs_asts": "rebs+asts", "rebs asts": "rebs+asts", "rebounds assists": "rebs+asts",
        "3 pointers made": "3-pt made", "3 pointer made": "3-pt made", "3pt made": "3-pt made", "3 pt made": "3-pt made", "three pointers made": "3-pt made", "three points made": "3-pt made", "threes": "3-pt made",
        "blocks": "blocks", "blocked shots": "blocks",
        "steals": "steals",
        "blocks steals": "blks+stls", "blks stls": "blks+stls", "blk stl": "blks+stls", "blocks_steals": "blks+stls",
        "turnovers": "turnovers", "tos": "turnovers",
        "fantasy points": "fantasy score", "fantasy score": "fantasy score",
    },
    "mlb": {
        "hits": "hits", "hit": "hits",
        "runs": "runs", "run": "runs",
        "rbis": "rbis", "rbi": "rbis", "runs batted in": "rbis",
        "hits_runs_rbis": "hits+runs+rbis", "hits runs rbis": "hits+runs+rbis", "hrr": "hits+runs+rbis",
        "total bases": "total bases", "bases": "total bases",
        "singles": "singles", "single": "singles",
        "walks": "walks", "batter walks": "walks",
        "strikeouts": "strikeouts", "pitcher strikeouts": "pitcher strikeouts", "pitching strikeouts": "pitcher strikeouts",
        "hits allowed": "hits allowed",
        "earned runs allowed": "earned runs allowed", "earned runs": "earned runs allowed",
        "walks allowed": "walks allowed",
        "outs": "outs", "pitching outs": "outs", "pitch outs": "outs", "outs recorded": "outs",
        "fantasy points": "fantasy score", "fantasy score": "fantasy score",
    },
}
SUPPORTED_PROJECTION_STATS = {
    "nba": {"points", "rebounds", "assists", "pts+rebs+asts", "pts+rebs", "pts+asts", "rebs+asts", "3-pt made", "blocks", "steals", "blks+stls", "turnovers"},
    "mlb": {"hits", "runs", "rbis", "hits+runs+rbis", "total bases", "singles", "walks", "strikeouts", "pitcher strikeouts", "hits allowed", "earned runs allowed", "walks allowed", "outs"},
}


def log(message: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] fetch_underdog — {message}"
    print(line)
    with LOG_FILE.open("a") as f:
        f.write(line + "\n")


def norm_text(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    return re.sub(r"\s+", " ", text)


def normalize_player_name(value: Any) -> str:
    return norm_text(re.sub(r"\b(jr|sr|ii|iii|iv)\.?\b", "", str(value or ""), flags=re.I))


def normalize_stat_type(value: Any, league: str) -> str:
    raw = norm_text(value).replace(" + ", " ")
    raw = raw.replace("_", " ")
    return STAT_ALIASES.get(league.lower(), {}).get(raw, raw)


def to_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def fetch_raw() -> dict[str, Any]:
    log(f"Fetching Underdog props from {ENDPOINT}")
    resp = requests.get(ENDPOINT, headers=HEADERS, timeout=30)
    if resp.status_code != 200:
        log(f"ERROR — HTTP {resp.status_code}: {resp.text[:500]}")
        sys.exit(1)
    data = resp.json()
    log(
        "Raw response: "
        f"{len(data.get('over_under_lines', []))} lines, "
        f"{len(data.get('appearances', []))} appearances, "
        f"{len(data.get('players', []))} players, "
        f"{len(data.get('games', []))} games, "
        f"{len(data.get('solo_games', []))} solo_games"
    )
    return data


def option_summary(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    keys = ["id", "choice", "choice_display", "american_price", "decimal_price", "payout_multiplier", "status", "updated_at"]
    return [{k: opt.get(k) for k in keys if k in opt} for opt in options if isinstance(opt, dict)]


def raw_sample(raw: dict[str, Any], league: str, limit: int = 5) -> dict[str, Any]:
    sport = LEAGUE_TO_SPORT_ID[league]
    players = {str(p.get("id")): p for p in raw.get("players", [])}
    appearances = {str(a.get("id")): a for a in raw.get("appearances", [])}
    games = {str(g.get("id")): g for g in raw.get("games", [])}
    solo_games = {str(g.get("id")): g for g in raw.get("solo_games", [])}
    line_samples = []
    for line in raw.get("over_under_lines", []):
        app_id = ((line.get("over_under") or {}).get("appearance_stat") or {}).get("appearance_id")
        app = appearances.get(str(app_id), {})
        player = players.get(str(app.get("player_id")), {})
        match = games.get(str(app.get("match_id"))) or solo_games.get(str(app.get("match_id"))) or {}
        if str(player.get("sport_id") or match.get("sport_id") or "").upper() != sport:
            continue
        line_samples.append({
            "line": line,
            "appearance": app,
            "player": player,
            "match": match,
        })
        if len(line_samples) >= limit:
            break
    top = {}
    for key, value in raw.items():
        if isinstance(value, list):
            first = value[0] if value else {}
            top[key] = {"count": len(value), "important_fields": sorted(first.keys()) if isinstance(first, dict) else [], "sample": first}
        else:
            top[key] = {"type": type(value).__name__, "value": value}
    return {"endpoint": ENDPOINT, "auth_required": False, "league": sport, "top_level": top, "joined_line_samples": line_samples}


def audit_joins(raw: dict[str, Any], league: str) -> dict[str, Any]:
    sport = LEAGUE_TO_SPORT_ID[league]
    players = {str(p.get("id")): p for p in raw.get("players", [])}
    appearances = {str(a.get("id")): a for a in raw.get("appearances", [])}
    games = {str(g.get("id")): g for g in raw.get("games", [])}
    solo_games = {str(g.get("id")): g for g in raw.get("solo_games", [])}
    failures = []
    missing_player = []
    missing_game = []
    success = 0
    sport_lines = 0
    for line in raw.get("over_under_lines", []):
        ou = line.get("over_under") or {}
        astat = ou.get("appearance_stat") or {}
        app_id = astat.get("appearance_id")
        app = appearances.get(str(app_id))
        if not app:
            failures.append({"line_id": line.get("id"), "reason": "missing_appearance", "appearance_id": app_id})
            continue
        player = players.get(str(app.get("player_id")))
        match = games.get(str(app.get("match_id"))) or solo_games.get(str(app.get("match_id")))
        inferred_sport = str((player or {}).get("sport_id") or (match or {}).get("sport_id") or "").upper()
        if inferred_sport != sport:
            continue
        sport_lines += 1
        if not player:
            missing_player.append({"line_id": line.get("id"), "appearance_id": app_id, "player_id": app.get("player_id")})
        if not match:
            missing_game.append({"line_id": line.get("id"), "appearance_id": app_id, "match_id": app.get("match_id"), "match_type": app.get("match_type")})
        if player and match:
            success += 1
        else:
            failures.append({"line_id": line.get("id"), "reason": "missing_player_or_game", "appearance_id": app_id, "player_id": app.get("player_id"), "match_id": app.get("match_id")})
    return {
        "league": sport,
        "total_over_under_lines": len(raw.get("over_under_lines", [])),
        "league_over_under_lines": sport_lines,
        "successfully_joined_lines": success,
        "failed_joins": len(failures),
        "failed_join_examples": failures[:10],
        "missing_player_count": len(missing_player),
        "missing_player_examples": missing_player[:10],
        "missing_game_count": len(missing_game),
        "missing_game_examples": missing_game[:10],
        "join_path": [
            "over_under_lines[].over_under.appearance_stat.appearance_id -> appearances[].id",
            "appearances[].player_id -> players[].id",
            "appearances[].match_id -> games[].id or solo_games[].id",
        ],
    }


def flatten(raw: dict[str, Any], league: str) -> list[dict[str, Any]]:
    sport_id = LEAGUE_TO_SPORT_ID[league]
    players = {str(p.get("id")): p for p in raw.get("players", [])}
    appearances = {str(a.get("id")): a for a in raw.get("appearances", [])}
    games = {str(g.get("id")): g for g in raw.get("games", [])}
    solo_games = {str(g.get("id")): g for g in raw.get("solo_games", [])}
    board_scrape_time = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows: list[dict[str, Any]] = []
    for line in raw.get("over_under_lines", []):
        ou = line.get("over_under") or {}
        astat = ou.get("appearance_stat") or {}
        appearance_id = astat.get("appearance_id")
        appearance = appearances.get(str(appearance_id), {})
        player = players.get(str(appearance.get("player_id")), {})
        match_id = appearance.get("match_id")
        game = games.get(str(match_id)) or solo_games.get(str(match_id)) or {}
        if not player:
            continue
        if str(player.get("sport_id") or game.get("sport_id") or "").upper() != sport_id:
            continue
        if ou.get("category") and ou.get("category") != "player_prop":
            continue
        if appearance.get("type") and appearance.get("type") != "Player":
            continue
        options = [o for o in (line.get("options") or []) if isinstance(o, dict)]
        higher = next((o for o in options if o.get("choice") == "higher"), {})
        lower = next((o for o in options if o.get("choice") == "lower"), {})
        player_name = f"{player.get('first_name') or ''} {player.get('last_name') or ''}".strip() or higher.get("selection_header")
        stat_name = astat.get("display_stat") or ou.get("grid_display_title") or astat.get("stat")
        normalized_stat = normalize_stat_type(astat.get("stat") or stat_name, league)
        home = game.get("home_team_id")
        away = game.get("away_team_id")
        team = appearance.get("team_id") or player.get("team_id")
        opponent = home if team == away else away if team == home else None
        source_updated = line.get("updated_at")
        row = {
            "platform": "Underdog",
            "league_id": sport_id,
            "league_name": sport_id,
            "sport": sport_id,
            "projection_id": line.get("id"),
            "source_id": line.get("id"),
            "player_id": player.get("id"),
            "appearance_id": appearance_id,
            "match_id": match_id,
            "player_name": player_name,
            "normalized_player_name": normalize_player_name(player_name),
            "team": team,
            "opponent": opponent,
            "position": player.get("position_name"),
            "stat_type_id": astat.get("pickem_stat_id"),
            "stat_name": stat_name,
            "stat_display_name": stat_name,
            "stat_type": astat.get("stat") or stat_name,
            "normalized_stat_type": normalized_stat,
            "projection_supported": normalized_stat in SUPPORTED_PROJECTION_STATS.get(league, set()) and normalized_stat != "fantasy score",
            "line_score": to_float(line.get("stat_value")),
            "odds_type": None,
            "underdog_line_type": line.get("line_type"),
            "projection_type": ou.get("category") or "player_prop",
            "duration": "full_game",
            "event_type": None,
            "rank": line.get("rank"),
            "trending_count": None,
            "status": line.get("status"),
            "side_options_available": sorted([str(o.get("choice")) for o in options if o.get("choice")]),
            "in_game": bool(line.get("live_event")),
            "is_live": bool(line.get("live_event")),
            "live": bool(line.get("live_event")),
            "game_status": game.get("status"),
            "is_promo": False,
            "group_key": line.get("stable_id") or line.get("over_under_id"),
            "game_id": game.get("id") or match_id,
            "away_team": away,
            "home_team": home,
            "game_start_time": game.get("scheduled_at"),
            "start_time": game.get("scheduled_at"),
            "source_updated_at": source_updated,
            "source_created_at": line.get("created_at"),
            "updated_at": source_updated,
            "source_timestamp": source_updated,
            "source_timestamp_role": "underdog_line_updated_at" if source_updated else None,
            "board_scrape_time": board_scrape_time,
            "line_freshness_timestamp": board_scrape_time,
            "line_freshness_reason": "prop observed in current Underdog over_under_lines board pull",
            "source_game_status": game.get("status") or line.get("status"),
            "description": game.get("title") or game.get("full_title") or ou.get("title"),
            "higher_option_id": higher.get("id"),
            "lower_option_id": lower.get("id"),
            "higher_american_price": higher.get("american_price"),
            "lower_american_price": lower.get("american_price"),
            "higher_decimal_price": higher.get("decimal_price"),
            "lower_decimal_price": lower.get("decimal_price"),
            "higher_payout_multiplier": higher.get("payout_multiplier") or ((higher.get("odds") or {}).get("fantasy") or {}).get("multiplier"),
            "lower_payout_multiplier": lower.get("payout_multiplier") or ((lower.get("odds") or {}).get("fantasy") or {}).get("multiplier"),
            "options_raw_summary": option_summary(options),
            "raw_over_under_id": line.get("over_under_id"),
        }
        apply_line_timing(row, board_pull_time=board_scrape_time)
        rows.append(row)
    log(f"Flattened {len(rows)} {sport_id} player-prop rows")
    return rows


def coverage_audit(raw: dict[str, Any], rows: list[dict[str, Any]], league: str) -> dict[str, Any]:
    prices = [r for r in rows if r.get("higher_american_price") or r.get("lower_american_price") or r.get("higher_decimal_price") or r.get("lower_decimal_price")]
    return {
        "league": LEAGUE_TO_SPORT_ID[league],
        "total_raw_over_under_lines": len(raw.get("over_under_lines", [])),
        "flattened_rows": len(rows),
        "unique_players": len({r.get("normalized_player_name") for r in rows}),
        "unique_games": len({r.get("game_id") for r in rows if r.get("game_id") is not None}),
        "stat_type_counts": dict(Counter(r.get("normalized_stat_type") or r.get("stat_type") for r in rows)),
        "active_rows": sum(1 for r in rows if str(r.get("status") or "").lower() == "active"),
        "inactive_or_suspended_rows": sum(1 for r in rows if str(r.get("status") or "").lower() != "active"),
        "missing_line_rows": sum(1 for r in rows if r.get("line_score") is None),
        "rows_with_higher_lower_prices": len(prices),
        "rows_without_price_data": len(rows) - len(prices),
        "unsupported_stat_counts": dict(Counter(r.get("normalized_stat_type") for r in rows if not r.get("projection_supported"))),
    }


def stat_normalization_audit(rows: list[dict[str, Any]], league: str) -> dict[str, Any]:
    by_stat: dict[str, dict[str, Any]] = {}
    for row in rows:
        original = str(row.get("stat_type") or row.get("stat_name") or "")
        normalized = row.get("normalized_stat_type")
        bucket = by_stat.setdefault(original, {"count": 0, "normalized_stat_type": normalized, "example_players": [], "projection_support_exists": False, "recommendation": ""})
        bucket["count"] += 1
        if row.get("player_name") and len(bucket["example_players"]) < 5:
            bucket["example_players"].append(row.get("player_name"))
        bucket["projection_support_exists"] = bool(row.get("projection_supported"))
    for original, item in by_stat.items():
        if item["projection_support_exists"]:
            item["recommendation"] = f"safe canonical mapping: {item['normalized_stat_type']}"
        elif item["normalized_stat_type"] == "fantasy score":
            item["recommendation"] = "leave unsupported; fantasy score not modeled"
        else:
            item["recommendation"] = "leave unsupported until projection support is added/verified"
    return {"league": LEAGUE_TO_SPORT_ID[league], "stats": by_stat}


def save_json(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, default=str))
    log(f"Saved JSON → {path}")


def save_csv(rows: list[dict[str, Any]], path: Path) -> None:
    if not rows:
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    log(f"Saved CSV → {path}")


def run(league: str, output: str = "json") -> dict[str, Any]:
    league = league.lower()
    today = datetime.now().strftime("%Y-%m-%d")
    raw = fetch_raw()
    rows = flatten(raw, league)
    output_dir = DATA_DIR / league
    latest_json = output_dir / f"underdog_{league}_latest.json"
    dated_json = output_dir / f"underdog_{league}_{today}.json"
    latest_csv = output_dir / f"underdog_{league}_latest.csv"
    dated_csv = output_dir / f"underdog_{league}_{today}.csv"
    raw_sample_path = RESEARCH_DIR / f"underdog_raw_sample_{league}_{today}.json"
    join_audit_path = RESEARCH_DIR / f"underdog_join_audit_{league}_{today}.json"
    coverage_path = RESEARCH_DIR / f"underdog_coverage_{league}_{today}.json"
    stat_audit_path = RESEARCH_DIR / f"underdog_stat_normalization_{league}_{today}.json"
    if output in ("json", "both"):
        save_json(rows, dated_json)
        save_json(rows, latest_json)
    if output in ("csv", "both"):
        save_csv(rows, dated_csv)
        save_csv(rows, latest_csv)
    save_json(raw_sample(raw, league), raw_sample_path)
    join_audit = audit_joins(raw, league)
    coverage = coverage_audit(raw, rows, league)
    stat_audit = stat_normalization_audit(rows, league)
    save_json(join_audit, join_audit_path)
    save_json(coverage, coverage_path)
    save_json(stat_audit, stat_audit_path)
    summary = {
        "platform": "Underdog",
        "league": league.upper(),
        "endpoint": ENDPOINT,
        "auth_required": False,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total_raw_over_under_lines": len(raw.get("over_under_lines", [])),
        "total_props": len(rows),
        "unique_players": coverage["unique_players"],
        "unique_games": coverage["unique_games"],
        "active_rows": coverage["active_rows"],
        "inactive_or_suspended_rows": coverage["inactive_or_suspended_rows"],
        "rows_with_higher_lower_prices": coverage["rows_with_higher_lower_prices"],
        "rows_without_price_data": coverage["rows_without_price_data"],
        "output_files": {"latest_json": str(latest_json), "dated_json": str(dated_json)},
        "audit_files": {"raw_sample": str(raw_sample_path), "join_audit": str(join_audit_path), "coverage": str(coverage_path), "stat_normalization": str(stat_audit_path)},
    }
    print("\n── SUMMARY ──────────────────────────────")
    print(json.dumps(summary, indent=2))
    log("fetch_underdog completed successfully")
    return summary


def main() -> dict[str, Any]:
    parser = argparse.ArgumentParser(description="Fetch and audit Underdog Fantasy DFS props")
    parser.add_argument("--league", choices=sorted(LEAGUE_TO_SPORT_ID), default="nba")
    parser.add_argument("--output", choices=["json", "csv", "both"], default="json")
    args = parser.parse_args()
    return run(args.league, args.output)


if __name__ == "__main__":
    main()
