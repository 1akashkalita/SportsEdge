#!/usr/bin/env python3
"""Build ESPN historical player prop hit-rate database for SportsEdge.

Inputs: PrizePicks latest JSON / today's workbook Player Props sheet.
Outputs:
- ~/sports_picks/data/research/hit_rates/{sport}/{sport}_{espn_id}_{player}.json
- Hit-rate columns on today's Player Props workbook sheet
- Obsidian Research/Players notes via obsidian_sync payload
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import math
import re
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from workbook_io import safe_load_workbook, safe_save_workbook

HOME = Path.home()
ROOT = HOME / "sports_picks"
DATA = ROOT / "data"
NBA_DIR = DATA / "nba"
MLB_DIR = DATA / "mlb"
RESEARCH_DIR = DATA / "research" / "hit_rates"
LOG_DIR = DATA / "pnl" / "logs"
RUN_LOG = LOG_DIR / "run_log.txt"
OBSIDIAN_SYNC = HOME / ".hermes" / "skills" / "delegation" / "obsidian_sync" / "scripts" / "obsidian_sync.py"
SEARCH_URL = "https://site.web.api.espn.com/apis/search/v2"
GAMELOG_URL = "https://site.web.api.espn.com/apis/common/v3/sports/{group}/{league}/athletes/{athlete_id}/gamelog"

HIT_RATE_COLUMNS = [
    "Hit Rate L5", "Hit Rate L10", "Avg L5", "Avg L10", "vs Opponent HR", "Minutes Trend", "Sample Size",
]
FLAG_COLUMN = "Hit Rate Flags"
ESPN_ID_COLUMN = "ESPN Athlete ID"

NBA_STATS = ["points", "rebounds", "assists", "threes", "blocks", "steals", "turnovers", "points rebounds assists", "points rebounds", "points assists", "rebounds assists", "blocks steals"]
MLB_STATS = ["hits", "total bases", "rbis", "runs", "hits runs rbis", "strikeouts", "hits allowed", "earned runs", "outs"]

NBA_POSITION_CATEGORIES = {
    "PG": ("PG", "Guard"),
    "SG": ("SG", "Guard"),
    "G": ("PG", "Guard"),
    "SF": ("SF", "Wing"),
    "PF": ("PF", "Forward"),
    "F": ("PF", "Forward"),
    "C": ("C", "Big"),
    "F-C": ("C", "Big"),
    "C-F": ("C", "Big"),
    "G-F": ("SF", "Wing"),
    "F-G": ("SF", "Wing"),
}
MLB_POSITION_CATEGORIES = {
    "SP": ("SP", "Starting Pitcher"),
    "RP": ("RP", "Relief Pitcher"),
    "P": ("SP", "Starting Pitcher"),
    "C": ("C", "Catcher"),
    "1B": ("1B", "Infield"),
    "2B": ("2B", "Infield"),
    "3B": ("3B", "Infield"),
    "SS": ("SS", "Infield"),
    "IF": ("IF", "Infield"),
    "OF": ("OF", "Outfield"),
    "DH": ("DH", "Designated Hitter"),
}
PITCHING_STATS = {"strikeouts", "hits allowed", "earned runs", "outs", "walks allowed", "pitcher fantasy score"}

STAT_ALIASES = [
    ("points rebounds assists", ["pra", "pts+rebs+asts", "pts rebs asts", "points rebounds assists"]),
    ("points rebounds", ["pts+rebs", "pts rebs", "points rebounds"]),
    ("points assists", ["pts+asts", "pts asts", "points assists"]),
    ("rebounds assists", ["rebs+asts", "rebs asts", "rebounds assists"]),
    ("blocks steals", ["stocks", "blocks+steals", "blocks steals", "blks stls"]),
    ("threes", ["3-pt", "3pt", "3 pointers", "three", "threes"]),
    ("points", ["points", "pts"]),
    ("rebounds", ["rebounds", "rebs"]),
    ("assists", ["assists", "asts"]),
    ("blocks", ["blocks", "blks"]),
    ("steals", ["steals", "stls"]),
    ("turnovers", ["turnovers", "tos"]),
    ("total bases", ["total bases"]),
    ("hits runs rbis", ["hits+runs+rbis", "hits runs rbis", "hrr"]),
    ("strikeouts", ["pitcher strikeouts", "strikeouts", "ks"]),
    ("hits allowed", ["hits allowed"]),
    ("earned runs", ["earned runs"]),
    ("outs", ["pitching outs", "outs"]),
    ("rbis", ["rbis", "runs batted in"]),
    ("runs", ["runs scored", "runs"]),
    ("hits", ["hits"]),
]

NBA_STAT_NAMES = {
    "minutes": "minutes", "points": "points", "rebounds": "totalRebounds", "assists": "assists",
    "threes": "threePointFieldGoalsMade-threePointFieldGoalsAttempted", "blocks": "blocks", "steals": "steals", "turnovers": "turnovers",
}
MLB_STAT_NAMES = {
    "strikeouts": "strikeouts", "hits allowed": "hits", "earned runs": "earnedRuns", "outs": "innings",
    "hits": "hits", "rbis": "RBIs", "runs": "runs", "total bases": "totalBases",
}

TEAM_ABBR = {
    "New York Knicks": "NYK", "New York Mets": "NYM", "San Antonio Spurs": "SAS", "Seattle Mariners": "SEA",
}

session = requests.Session()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def log(msg: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with RUN_LOG.open("a", encoding="utf-8") as f:
        f.write(f"[{now_iso()}] build_hit_rate_db — {msg}\n")


def safe_slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text.strip()).strip("_") or "unknown"


def sport_hit_rate_dir(sport: str) -> Path:
    return RESEARCH_DIR / sport.lower()


def categorize_position(sport: str, raw_position: Any, stats: dict[str, Any] | None = None) -> tuple[str, str]:
    raw = str(raw_position or "").upper().strip()
    if sport == "nba":
        return NBA_POSITION_CATEGORIES.get(raw, ("Unknown", "Unknown"))
    if sport == "mlb":
        if raw == "P" and stats and not (set(stats) & PITCHING_STATS):
            return "RP", "Relief Pitcher"
        return MLB_POSITION_CATEGORIES.get(raw, ("Unknown", "Unknown"))
    return "Unknown", "Unknown"


def to_float(v: Any) -> float | None:
    if v in (None, "", "-"):
        return None
    try:
        if isinstance(v, str) and ":" in v:
            m, s = v.split(":", 1)
            return float(m) + float(s) / 60.0
        if isinstance(v, str) and "-" in v and not re.fullmatch(r"-?\d+(\.\d+)?", v):
            v = v.split("-", 1)[0]
        return float(str(v).replace(",", ""))
    except Exception:
        return None


def innings_to_outs(v: Any) -> float | None:
    if v in (None, "", "-"):
        return None
    s = str(v)
    try:
        if "." in s:
            whole, frac = s.split(".", 1)
            return int(whole) * 3 + int(frac[:1])
        return float(s) * 3
    except Exception:
        return to_float(v)


def normalize_stat(value: Any) -> str:
    text = str(value or "").lower().replace("_", " ").replace("-", " ").replace("+", " + ")
    compact = " ".join(text.split())
    compact_plus = compact.replace(" + ", "+")
    for canonical, aliases in STAT_ALIASES:
        for alias in aliases:
            a = alias.lower()
            if a in compact or a in compact_plus:
                return canonical
    return compact


def prop_file(sport: str) -> Path:
    return (NBA_DIR if sport == "nba" else MLB_DIR) / f"prizepicks_{sport}_latest.json"


def workbook_path(sport: str, date: str) -> Path:
    return (NBA_DIR if sport == "nba" else MLB_DIR) / f"{sport}_{date}.xlsx"


def load_props(sport: str, date: str) -> list[dict[str, Any]]:
    props: list[dict[str, Any]] = []
    path = prop_file(sport)
    if path.exists():
        raw = json.loads(path.read_text())
        if isinstance(raw, list):
            props.extend(raw)
    # Also read workbook Player Props, because the user explicitly asked for today's props sheet.
    wb_path = workbook_path(sport, date)
    if wb_path.exists():
        wb = safe_load_workbook(wb_path, read_only=True, data_only=True)
        try:
            if "Player Props" in wb.sheetnames:
                ws = wb["Player Props"]
                headers = [c.value for c in next(ws.iter_rows(min_row=1, max_row=1))]
                for row in ws.iter_rows(min_row=2, values_only=True):
                    if not any(row):
                        continue
                    rec = dict(zip(headers, row))
                    if str(rec.get("Date") or "")[:10] == date:
                        props.append({
                            "projection_id": rec.get("Projection ID"),
                            "player_name": rec.get("Player Name"),
                            "team": rec.get("Team"),
                            "description": rec.get("Opponent/Description"),
                            "stat_name": rec.get("Stat"),
                            "line_score": rec.get("Line"),
                            "odds_type": rec.get("Odds Type") or "standard",
                            "position": None,
                            "status": rec.get("Status"),
                        })
        finally:
            wb.close()
    return [p for p in props if p.get("player_name") and p.get("line_score") is not None]


def group_player_props(props: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for p in props:
        if str(p.get("odds_type") or "").lower() not in {"standard", ""}:
            continue
        player = str(p.get("player_name") or "").strip()
        if not player or " + " in player:
            # PrizePicks combo props are not player-specific game logs; skip them here.
            continue
        key = player.lower()
        entry = grouped.setdefault(key, {
            "player_id": str(p.get("player_id") or ""), "player_name": player,
            "team": p.get("team") or p.get("team_name") or "", "position": p.get("position") or "",
            "props": {}, "opponent": p.get("description") or "",
        })
        stat = normalize_stat(p.get("stat_name") or p.get("stat_type"))
        line = to_float(p.get("line_score"))
        if stat and line is not None and stat not in entry["props"]:
            entry["props"][stat] = {"line": line, "projection_id": p.get("projection_id"), "raw_stat": p.get("stat_name") or p.get("stat_type")}
        if not entry.get("opponent") and p.get("description"):
            entry["opponent"] = p.get("description")
    return list(grouped.values())


def extract_espn_athlete_id(uid: str | None) -> str | None:
    if not uid:
        return None
    m = re.search(r"~a:(\d+)", uid)
    return m.group(1) if m else None


def resolve_espn_id(sport: str, player_name: str) -> tuple[str | None, dict[str, Any]]:
    aliases = {
        "vlad guerrero jr.": "Vladimir Guerrero Jr.",
        "vladdy guerrero jr.": "Vladimir Guerrero Jr.",
    }
    known_ids = {
        ("mlb", "spencer horwitz"): "4228472",
    }
    known = known_ids.get((sport, player_name.lower()))
    if known:
        return known, {"displayName": player_name, "uid": f"s:1~l:10~a:{known}", "source": "known_id_fallback"}
    queries = [player_name]
    alias = aliases.get(player_name.lower())
    if alias and alias not in queries:
        queries.append(alias)
    wanted = "NBA" if sport == "nba" else "MLB"
    last_error: dict[str, Any] = {}
    for query in queries:
        try:
            r = session.get(SEARCH_URL, params={"query": query, "limit": 10}, timeout=20)
            r.raise_for_status()
            data = r.json()
            for result in data.get("results", []):
                if result.get("type") != "player":
                    continue
                for c in result.get("contents", []):
                    if str(c.get("description") or "").upper() != wanted:
                        continue
                    display = str(c.get("displayName") or "")
                    if display.lower() == query.lower() or query.lower() in display.lower() or display.lower() in query.lower():
                        return extract_espn_athlete_id(c.get("uid")), c
            for result in data.get("results", []):
                if result.get("type") == "player":
                    for c in result.get("contents", []):
                        if str(c.get("description") or "").upper() == wanted:
                            return extract_espn_athlete_id(c.get("uid")), c
        except Exception as e:
            last_error = {"error": str(e)}
    return None, last_error


def fetch_gamelog(sport: str, athlete_id: str, props: dict[str, Any], position: str = "") -> dict[str, Any]:
    group, league = ("basketball", "nba") if sport == "nba" else ("baseball", "mlb")
    url = GAMELOG_URL.format(group=group, league=league, athlete_id=athlete_id)
    params: dict[str, Any] = {}
    if sport == "mlb":
        pos_is_pitcher = "P" in str(position or "").upper().split("-") or str(position or "").upper() == "P"
        raw_stats = " ".join(str(v.get("raw_stat") or "") for v in props.values() if isinstance(v, dict)).lower()
        stat_keys = set(props)
        pitching_without_k = {"hits allowed", "earned runs", "outs"}
        is_pitching = bool(stat_keys & pitching_without_k) or "pitcher" in raw_stats or pos_is_pitcher
        params["category"] = "pitching" if is_pitching else "batting"
    r = session.get(url, params=params, timeout=25)
    r.raise_for_status()
    return r.json()


def parse_game_rows(sport: str, gamelog: dict[str, Any]) -> list[dict[str, Any]]:
    names = gamelog.get("names") or []
    events_meta = gamelog.get("events") or {}
    rows = []
    seen = set()
    for season_type in gamelog.get("seasonTypes") or []:
        for cat in season_type.get("categories") or []:
            for ev in cat.get("events") or []:
                event_id = str(ev.get("eventId") or ev.get("id") or "")
                if not event_id or event_id in seen:
                    continue
                seen.add(event_id)
                stats = ev.get("stats") or []
                stat_map = {names[i]: stats[i] for i in range(min(len(names), len(stats)))}
                meta = events_meta.get(event_id, {}) if isinstance(events_meta, dict) else {}
                opp = meta.get("opponent") or {}
                row = {
                    "event_id": event_id,
                    "date": meta.get("gameDate"),
                    "home_away": "away" if meta.get("atVs") == "@" else "home" if meta.get("atVs") == "vs" else "unknown",
                    "opponent": opp.get("abbreviation") or opp.get("displayName") or "",
                    "opponent_name": opp.get("displayName") or "",
                    "result": meta.get("gameResult"),
                    "stats_raw": stat_map,
                }
                if sport == "nba":
                    row.update({
                        "minutes": to_float(stat_map.get(NBA_STAT_NAMES["minutes"])),
                        "points": to_float(stat_map.get(NBA_STAT_NAMES["points"])),
                        "rebounds": to_float(stat_map.get(NBA_STAT_NAMES["rebounds"])),
                        "assists": to_float(stat_map.get(NBA_STAT_NAMES["assists"])),
                        "blocks": to_float(stat_map.get(NBA_STAT_NAMES["blocks"])),
                        "steals": to_float(stat_map.get(NBA_STAT_NAMES["steals"])),
                        "turnovers": to_float(stat_map.get(NBA_STAT_NAMES["turnovers"])),
                    })
                    made3 = str(stat_map.get(NBA_STAT_NAMES["threes"], "0-0")).split("-", 1)[0]
                    row["threes"] = to_float(made3)
                    row["points rebounds assists"] = sum(x or 0 for x in [row.get("points"), row.get("rebounds"), row.get("assists")])
                    row["points rebounds"] = sum(x or 0 for x in [row.get("points"), row.get("rebounds")])
                    row["points assists"] = sum(x or 0 for x in [row.get("points"), row.get("assists")])
                    row["rebounds assists"] = sum(x or 0 for x in [row.get("rebounds"), row.get("assists")])
                    row["blocks steals"] = sum(x or 0 for x in [row.get("blocks"), row.get("steals")])
                else:
                    row.update({
                        "strikeouts": to_float(stat_map.get(MLB_STAT_NAMES["strikeouts"])),
                        "hits allowed": to_float(stat_map.get(MLB_STAT_NAMES["hits allowed"])),
                        "earned runs": to_float(stat_map.get(MLB_STAT_NAMES["earned runs"])),
                        "outs": innings_to_outs(stat_map.get(MLB_STAT_NAMES["outs"])),
                        "hits": to_float(stat_map.get(MLB_STAT_NAMES["hits"])),
                        "rbis": to_float(stat_map.get(MLB_STAT_NAMES["rbis"])),
                        "runs": to_float(stat_map.get(MLB_STAT_NAMES["runs"])),
                        "total bases": to_float(stat_map.get(MLB_STAT_NAMES["total bases"])),
                    })
                    row["hits runs rbis"] = sum(x or 0 for x in [row.get("hits"), row.get("runs"), row.get("rbis")])
                    row["minutes"] = row.get("outs")
                rows.append(row)
    rows.sort(key=lambda r: str(r.get("date") or ""), reverse=True)
    return rows


def mean(vals: list[float]) -> float:
    return round(sum(vals) / len(vals), 3) if vals else 0.0


def hit_rate(vals: list[float], line: float) -> float:
    return round(sum(1 for v in vals if v > line) / len(vals), 3) if vals else 0.0


def trend(vals: list[float]) -> str:
    vals = [v for v in vals if v is not None]
    if len(vals) < 4:
        return "stable"
    recent = mean(vals[:2])
    older = mean(vals[-2:])
    if recent > older + 1.0:
        return "up"
    if recent < older - 1.0:
        return "down"
    return "stable"


def calculate_stat(rows20: list[dict[str, Any]], stat: str, line: float, opponent: str) -> dict[str, Any]:
    vals20 = [to_float(r.get(stat)) for r in rows20]
    pairs = [(v, r) for v, r in zip(vals20, rows20) if v is not None]
    vals = [v for v, _r in pairs]
    l5, l10, l20 = vals[:5], vals[:10], vals[:20]
    home = [v for v, r in pairs if r.get("home_away") == "home"]
    away = [v for v, r in pairs if r.get("home_away") == "away"]
    opp_norm = str(opponent or "").upper()
    vs = [v for v, r in pairs if opp_norm and (opp_norm == str(r.get("opponent") or "").upper() or opp_norm in str(r.get("opponent_name") or "").upper())]
    minutes = [to_float(r.get("minutes")) for r in rows20[:5]]
    minutes = [m for m in minutes if m is not None]
    sample = [{"date": r.get("date"), "opponent": r.get("opponent"), "home_away": r.get("home_away"), "actual": v, "minutes": r.get("minutes")} for v, r in pairs[:20]]
    return {
        "line": line,
        "hit_rate_l5": hit_rate(l5, line),
        "hit_rate_l10": hit_rate(l10, line),
        "hit_rate_l20": hit_rate(l20, line),
        "hit_rate_home": hit_rate(home, line),
        "hit_rate_away": hit_rate(away, line),
        "avg_stat_l5": mean(l5),
        "avg_stat_l10": mean(l10),
        "median_stat_l20": round(statistics.median(l20), 3) if l20 else 0.0,
        "best_game_l10": max(l10) if l10 else 0.0,
        "worst_game_l10": min(l10) if l10 else 0.0,
        "games_above_line": sum(1 for v in l10 if v > line),
        "games_below_line": sum(1 for v in l10 if v <= line),
        "vs_opponent_hit_rate": hit_rate(vs, line),
        "vs_opponent_avg": mean(vs),
        "minutes_l5": mean(minutes),
        "minutes_trend": trend(minutes),
        "sample_size": len(l20),
        "sample_games": sample,
    }


def build_one(sport: str, player: dict[str, Any]) -> dict[str, Any]:
    time.sleep(0.02)
    espn_id, search_hit = resolve_espn_id(sport, player["player_name"])
    if not espn_id:
        return {"ok": False, "player_name": player["player_name"], "error": "ESPN athlete ID not resolved", "search": search_hit}
    try:
        gamelog = fetch_gamelog(sport, espn_id, player.get("props", {}), player.get("position", ""))
        rows20 = parse_game_rows(sport, gamelog)[:20]
    except Exception as e:
        return {"ok": False, "player_name": player["player_name"], "espn_id": espn_id, "error": str(e)}
    stat_names = NBA_STATS if sport == "nba" else MLB_STATS
    stats = {}
    for stat in stat_names:
        if stat in player.get("props", {}):
            line = float(player["props"][stat]["line"])
            stats[stat] = calculate_stat(rows20, stat, line, player.get("opponent") or "")
    raw_position = player.get("position", "")
    position, category = categorize_position(sport, raw_position, stats)
    doc = {
        "player_id": espn_id,
        "source_player_id": player.get("player_id"),
        "player_name": player["player_name"],
        "team": player.get("team", ""),
        "position": position,
        "category": category,
        "position_raw": raw_position,
        "sport": sport.upper(),
        "opponent": player.get("opponent") or "",
        "last_updated": now_iso(),
        "stats": stats,
    }
    out_dir = sport_hit_rate_dir(sport)
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{sport}_{espn_id}_{safe_slug(player['player_name'])}.json"
    out.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sync_player_to_obsidian(sport, doc)
    return {"ok": True, "player_name": player["player_name"], "espn_id": espn_id, "file": str(out), "stats": stats}


def player_markdown(doc: dict[str, Any]) -> str:
    rows = ["| Stat | Line | HR L5 | HR L10 | HR L20 | Avg L5 | Avg L10 | vs Opp HR | vs Opp Avg | Min L5 | Trend | Sample |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|"]
    for stat, s in sorted((doc.get("stats") or {}).items()):
        rows.append(f"| {stat} | {s.get('line', '')} | {s.get('hit_rate_l5', 0)} | {s.get('hit_rate_l10', 0)} | {s.get('hit_rate_l20', 0)} | {s.get('avg_stat_l5', 0)} | {s.get('avg_stat_l10', 0)} | {s.get('vs_opponent_hit_rate', 0)} | {s.get('vs_opponent_avg', 0)} | {s.get('minutes_l5', 0)} | {s.get('minutes_trend', '')} | {s.get('sample_size', 0)} |")
    return "\n".join(rows)


def sync_player_to_obsidian(sport: str, doc: dict[str, Any]) -> None:
    if not OBSIDIAN_SYNC.exists():
        return
    payload = {
        "trigger": "build_hit_rate_db",
        "sport": sport.upper(),
        "date": today_str(),
        "data": {
            "player": doc.get("player_name"),
            "player_name": doc.get("player_name"),
            "team": doc.get("team"),
            "position": doc.get("position"),
            "category": doc.get("category"),
            "markdown": player_markdown(doc),
            "hit_rate_json": doc,
        },
    }
    try:
        subprocess.run([sys.executable, str(OBSIDIAN_SYNC), json.dumps(payload)], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
    except Exception:
        pass


def ensure_workbook_columns(path: Path) -> None:
    if not path.exists():
        return
    wb = safe_load_workbook(path)
    try:
        if "Player Props" not in wb.sheetnames:
            return
        ws = wb["Player Props"]
        headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
        for col in [*HIT_RATE_COLUMNS, FLAG_COLUMN, ESPN_ID_COLUMN]:
            if col not in headers:
                ws.cell(1, ws.max_column + 1).value = col
                headers.append(col)
        safe_save_workbook(wb, path)
    finally:
        wb.close()


def load_hit_rate_index(sport: str) -> dict[tuple[str, str], dict[str, Any]]:
    idx = {}
    for path in sport_hit_rate_dir(sport).glob(f"{sport}_*.json"):
        try:
            doc = json.loads(path.read_text())
        except Exception:
            continue
        name = str(doc.get("player_name") or "").lower()
        for stat, s in (doc.get("stats") or {}).items():
            idx[(name, normalize_stat(stat))] = {"doc": doc, "stat": s}
    return idx


def flags_for(s: dict[str, Any] | None) -> str:
    if not s:
        return "NO HIT RATE DATA"
    flags = []
    if (s.get("vs_opponent_hit_rate") or 0) <= 0.30:
        flags.append("BAD MATCHUP")
    if s.get("minutes_trend") == "down":
        flags.append("MINUTES RISK")
    if (s.get("sample_size") or 0) < 5:
        flags.append("SMALL SAMPLE")
    return "; ".join(flags)


def update_workbook(sport: str, date: str) -> int:
    path = workbook_path(sport, date)
    if not path.exists():
        return 0
    ensure_workbook_columns(path)
    idx = load_hit_rate_index(sport)
    wb = safe_load_workbook(path)
    updated = 0
    try:
        ws = wb["Player Props"]
        headers = {ws.cell(1, c).value: c for c in range(1, ws.max_column + 1)}
        for r in range(2, ws.max_row + 1):
            player = str(ws.cell(r, headers.get("Player Name", 4)).value or "").lower()
            stat = normalize_stat(ws.cell(r, headers.get("Stat", 7)).value)
            rec = idx.get((player, stat))
            if not rec:
                continue
            s = rec["stat"]
            ws.cell(r, headers["Hit Rate L5"]).value = s.get("hit_rate_l5")
            ws.cell(r, headers["Hit Rate L10"]).value = s.get("hit_rate_l10")
            ws.cell(r, headers["Avg L5"]).value = s.get("avg_stat_l5")
            ws.cell(r, headers["Avg L10"]).value = s.get("avg_stat_l10")
            ws.cell(r, headers["vs Opponent HR"]).value = s.get("vs_opponent_hit_rate")
            ws.cell(r, headers["Minutes Trend"]).value = s.get("minutes_trend")
            ws.cell(r, headers["Sample Size"]).value = s.get("sample_size")
            ws.cell(r, headers[FLAG_COLUMN]).value = flags_for(s)
            ws.cell(r, headers[ESPN_ID_COLUMN]).value = rec["doc"].get("player_id")
            updated += 1
        safe_save_workbook(wb, path)
    finally:
        wb.close()
    return updated


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sport", choices=["nba", "mlb", "both"], default="both")
    ap.add_argument("--date", default=today_str())
    ap.add_argument("--max-players", type=int, default=0, help="0 = all")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--no-obsidian", action="store_true")
    args = ap.parse_args()

    sports = ["nba", "mlb"] if args.sport == "both" else [args.sport]
    all_results = []
    for sport in sports:
        props = load_props(sport, args.date)
        players = group_player_props(props)
        if args.max_players:
            players = players[: args.max_players]
        log(f"start sport={sport} players={len(players)} props={len(props)}")
        results = []
        with cf.ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            futs = [ex.submit(build_one, sport, p) for p in players]
            for fut in cf.as_completed(futs):
                results.append(fut.result())
        updated = update_workbook(sport, args.date)
        ok = sum(1 for r in results if r.get("ok"))
        log(f"complete sport={sport} ok={ok} failed={len(results)-ok} workbook_rows_updated={updated}")
        all_results.append({"sport": sport, "players": len(players), "ok": ok, "failed": len(results)-ok, "workbook_rows_updated": updated, "first5": [r for r in results if r.get("ok")][:5], "errors_first5": [r for r in results if not r.get("ok")][:5]})
    print(json.dumps({"status": "ok", "date": args.date, "output_dir": str(RESEARCH_DIR), "results": all_results}, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
