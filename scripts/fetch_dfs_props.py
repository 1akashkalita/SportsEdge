#!/usr/bin/env python3
"""Run DFS prop fetchers and build a side-aware cross-platform research table.

Boundaries:
- PrizePicks and Underdog are first-class DFS prop sources for current board lines.
- Either platform can feed gates, projections, approved picks, CLV, and prop monitors.
- Dabble remains safe-disabled when blocked/unavailable.
- This script does not call sportsbook/Odds APIs for DFS/player props.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from workbook_io import safe_load_workbook, safe_save_workbook

ROOT = Path.home() / "sports_picks"
SCRIPTS = ROOT / "scripts"
DATA = ROOT / "data"
RESEARCH = DATA / "research" / "underdog"
LOG_FILE = DATA / "pnl" / "logs" / "run_log.txt"
LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
RESEARCH.mkdir(parents=True, exist_ok=True)
PLATFORMS = ["prizepicks", "dabble", "underdog"]

WORKBOOK_COMPARISON_HEADERS = [
    "PP Line", "Underdog Line", "Dabble Line", "Book Line", "Best Platform", "Best Line",
    "Best Line Flag", "All Platform Lines", "Match Confidence", "Underdog Higher Odds",
    "Underdog Lower Odds", "Underdog Line Type", "Underdog Source ID", "Underdog Updated At",
]

STAT_ALIASES = {
    "nba": {
        "points": "points", "point": "points", "pts": "points",
        "rebounds": "rebounds", "rebound": "rebounds", "rebs": "rebounds",
        "assists": "assists", "assist": "assists", "asts": "assists",
        "pts rebs asts": "pts+rebs+asts", "points rebounds assists": "pts+rebs+asts", "pra": "pts+rebs+asts",
        "pts rebs": "pts+rebs", "points rebounds": "pts+rebs",
        "pts asts": "pts+asts", "points assists": "pts+asts",
        "rebs asts": "rebs+asts", "rebounds assists": "rebs+asts",
        "3 pointers made": "3-pt made", "3 pointer made": "3-pt made", "3pt made": "3-pt made", "3 pt made": "3-pt made", "three pointers made": "3-pt made", "three points made": "3-pt made", "threes": "3-pt made",
        "blocks": "blocks", "steals": "steals", "blocks steals": "blks+stls", "blks stls": "blks+stls", "blk stl": "blks+stls",
        "turnovers": "turnovers", "tos": "turnovers", "fantasy points": "fantasy score", "fantasy score": "fantasy score",
    },
    "mlb": {
        "hits": "hits", "hit": "hits", "runs": "runs", "run": "runs", "rbis": "rbis", "rbi": "rbis", "runs batted in": "rbis",
        "hits runs rbis": "hits+runs+rbis", "hrr": "hits+runs+rbis", "total bases": "total bases", "bases": "total bases",
        "singles": "singles", "single": "singles", "walks": "walks", "batter walks": "walks",
        "strikeouts": "strikeouts", "pitcher strikeouts": "pitcher strikeouts", "pitching strikeouts": "pitcher strikeouts",
        "hits allowed": "hits allowed", "earned runs allowed": "earned runs allowed", "earned runs": "earned runs allowed",
        "walks allowed": "walks allowed", "outs": "outs", "pitching outs": "outs", "pitch outs": "outs", "outs recorded": "outs",
        "fantasy points": "fantasy score", "fantasy score": "fantasy score",
    },
}

HIGH_CONFIDENCE = {"exact_player_stat_game_match", "player_stat_time_match"}
LOW_CONFIDENCE = "player_stat_only_low_confidence"
REJECTED = {"rejected_stat_mismatch", "rejected_game_mismatch", "rejected_combo_market", "rejected_missing_required_key"}


def log(message: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] fetch_dfs_props — {message}"
    print(line)
    with LOG_FILE.open("a") as f:
        f.write(line + "\n")


def norm_text(value: Any) -> str:
    text = re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()
    return re.sub(r"\s+", " ", text)


def normalize_player_name(value: Any) -> str:
    return norm_text(re.sub(r"\b(jr|sr|ii|iii|iv)\.?\b", "", str(value or ""), flags=re.I))


def normalize_stat_type(value: Any, league: str) -> str:
    raw = norm_text(value)
    return STAT_ALIASES.get(league.lower(), {}).get(raw, raw)


def stat_key(row: dict[str, Any], league: str = "nba") -> str:
    return row.get("normalized_stat_type") or normalize_stat_type(row.get("stat_type") or row.get("stat_name") or row.get("stat_display_name"), league)


def player_key(row: dict[str, Any]) -> str:
    return row.get("normalized_player_name") or normalize_player_name(row.get("player_name"))


def to_float(value: Any) -> float | None:
    try:
        if value == "" or value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def as_platform(row: dict[str, Any], default: str) -> str:
    platform = norm_text(row.get("platform") or default).replace(" ", "")
    if platform in {"prizepicks", "pp"}:
        return "prizepicks"
    if platform == "underdog":
        return "underdog"
    if platform == "dabble":
        return "dabble"
    return platform


def side_key(row: dict[str, Any]) -> str | None:
    for key in ("side", "pick_side", "selection_side", "direction", "over_under", "choice"):
        value = norm_text(row.get(key))
        if value in {"over", "higher", "more"}:
            return "over"
        if value in {"under", "lower", "less"}:
            return "under"
    return None


def is_combo_market(row: dict[str, Any]) -> bool:
    name = str(row.get("player_name") or "")
    if " + " in name or " & " in name or "/" in name:
        return True
    if row.get("market_type") in {"combo", "player_pair"}:
        return True
    if row.get("appearance_type") and row.get("appearance_type") != "Player":
        return True
    return False


def include_row(platform: str, row: dict[str, Any]) -> bool:
    if not isinstance(row, dict):
        return False
    if is_combo_market(row):
        return False
    if row.get("is_promo") is True:
        return False
    if not row.get("player_name") or to_float(row.get("line_score")) is None:
        return False
    if platform == "prizepicks" and str(row.get("odds_type") or "").lower() != "standard":
        return False
    return True


def same_game_or_time(a: dict[str, Any], b: dict[str, Any]) -> tuple[bool, bool]:
    game_a = str(a.get("game_id") or a.get("match_id") or "").strip()
    game_b = str(b.get("game_id") or b.get("match_id") or "").strip()
    if game_a and game_b and game_a == game_b:
        return True, False
    # Cross-platform game IDs often use different namespaces. If IDs differ,
    # require an independent start-time or matchup confirmation before matching.
    time_a = str(a.get("start_time") or a.get("game_start_time") or "").strip()
    time_b = str(b.get("start_time") or b.get("game_start_time") or "").strip()
    if time_a and time_b and time_a[:16] == time_b[:16]:
        return True, True
    matchup_a = norm_text(a.get("description") or a.get("matchup") or a.get("game") or "")
    matchup_b = norm_text(b.get("description") or b.get("matchup") or b.get("game") or "")
    if matchup_a and matchup_b and matchup_a == matchup_b:
        return True, True
    team_a = norm_text(a.get("team"))
    team_b = norm_text(b.get("team"))
    # PrizePicks often stores only opponent/team shorthand while Underdog stores
    # a full matchup title. Treat this as a matchup confirmation only when the
    # row team plus the row matchup/description token both appear in the other
    # platform matchup title.
    if team_a and matchup_a and matchup_b and team_a in matchup_b.split() and matchup_a in matchup_b.split():
        return True, True
    if team_b and matchup_b and matchup_a and team_b in matchup_a.split() and matchup_b in matchup_a.split():
        return True, True
    return False, False


def match_rows(left: dict[str, Any], right: dict[str, Any], league: str) -> dict[str, Any]:
    if is_combo_market(left) or is_combo_market(right):
        return {"confidence": "rejected_combo_market", "reason": "combo/player-pair market cannot match single-player market"}
    if not player_key(left) or not player_key(right) or not stat_key(left, league) or not stat_key(right, league):
        return {"confidence": "rejected_missing_required_key", "reason": "missing normalized player/stat key"}
    if player_key(left) != player_key(right):
        return {"confidence": "rejected_missing_required_key", "reason": "normalized player mismatch"}
    if stat_key(left, league) != stat_key(right, league):
        return {"confidence": "rejected_stat_mismatch", "reason": f"{stat_key(left, league)} != {stat_key(right, league)}"}
    game_left = str(left.get("game_id") or left.get("match_id") or "").strip()
    game_right = str(right.get("game_id") or right.get("match_id") or "").strip()
    if game_left and game_right and game_left == game_right:
        return {"confidence": "exact_player_stat_game_match", "reason": "player/stat/game all match"}
    same, used_fallback = same_game_or_time(left, right)
    if same and used_fallback:
        return {"confidence": "player_stat_time_match", "reason": "player/stat match and start time or matchup matches; platform game IDs may use different namespaces"}
    if game_left and game_right and game_left != game_right:
        return {"confidence": "rejected_game_mismatch", "reason": f"{game_left} != {game_right} and no time/matchup fallback match"}
    if not game_left and not game_right:
        return {"confidence": LOW_CONFIDENCE, "reason": "player/stat match only; no game/start-time confirmation"}
    return {"confidence": "rejected_missing_required_key", "reason": "one side lacks game/start-time key"}


def pick_best_platform(lines: dict[str, float | None], book_line: float | None, side: str | None = None, confidence: str | None = None) -> tuple[str | None, float | None, str, float | None]:
    dfs_lines = {p: v for p, v in lines.items() if p in {"prizepicks", "underdog", "dabble"} and v is not None and not (p == "dabble" and v is None)}
    if not dfs_lines:
        return None, None, "NO_DFS_LINE", None
    if confidence == LOW_CONFIDENCE:
        return None, None, "DIAGNOSTIC_ONLY_LOW_CONFIDENCE_MATCH", None
    if confidence in REJECTED:
        return None, None, "NO_MATCH_REJECTED", None
    if side not in {"over", "under"}:
        return None, None, "NEEDS_SIDE_CONFIRMATION", None
    if side == "over":
        best_p, best_v = min(dfs_lines.items(), key=lambda kv: kv[1])
        distance = (book_line - best_v) if book_line is not None else None
    else:
        best_p, best_v = max(dfs_lines.items(), key=lambda kv: kv[1])
        distance = (best_v - book_line) if book_line is not None else None
    if book_line is None:
        return best_p, best_v, "BEST DFS LINE among DFS platforms", distance
    return best_p, best_v, "BEST LINE" if distance is not None and distance >= 0 else "BEST_DFS_LINE_BUT_WORSE_THAN_BOOK", distance


def choose_platform_line(platform: str, rows: list[dict[str, Any]], side: str | None) -> dict[str, Any] | None:
    valid = [r for r in rows if to_float(r.get("line_score")) is not None]
    if not valid:
        return None
    if side == "under":
        return max(valid, key=lambda r: to_float(r.get("line_score")) or float("-inf"))
    return min(valid, key=lambda r: to_float(r.get("line_score")) or float("inf"))


def line_display(lines: dict[str, float | None]) -> str:
    return f"PP: {lines.get('prizepicks') if lines.get('prizepicks') is not None else '—'} | Dabble: {lines.get('dabble') if lines.get('dabble') is not None else '—'} | Underdog: {lines.get('underdog') if lines.get('underdog') is not None else '—'} | Book: {lines.get('book') if lines.get('book') is not None else '—'}"


def build_record(league: str, rows: list[dict[str, Any]], confidence: str, reason: str, side: str | None) -> dict[str, Any]:
    by_platform: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_platform[as_platform(row, str(row.get("platform") or ""))].append(row)
    pp = choose_platform_line("prizepicks", by_platform.get("prizepicks", []), side)
    ud = choose_platform_line("underdog", by_platform.get("underdog", []), side)
    dabble = choose_platform_line("dabble", by_platform.get("dabble", []), side)
    sample = pp or ud or dabble or rows[0]
    lines = {
        "prizepicks": to_float((pp or {}).get("line_score")),
        "dabble": to_float((dabble or {}).get("line_score")) if dabble else None,
        "underdog": to_float((ud or {}).get("line_score")),
        "book": to_float(sample.get("book_line") or sample.get("sportsbook_line")),
    }
    best_platform, best_line, flag, distance = pick_best_platform(lines, lines.get("book"), side=side, confidence=confidence)
    platform_count = sum(1 for p in ("prizepicks", "underdog") if lines.get(p) is not None) + (1 if dabble and lines.get("dabble") is not None else 0)
    return {
        "league": league.upper(),
        "player_name": sample.get("player_name"),
        "normalized_player_name": player_key(sample),
        "stat_type": sample.get("stat_type") or sample.get("stat_name") or sample.get("stat_display_name"),
        "normalized_stat_type": stat_key(sample, league),
        "team": sample.get("team"),
        "opponent": sample.get("opponent"),
        "game_id": sample.get("game_id") or sample.get("match_id"),
        "start_time": sample.get("start_time") or sample.get("game_start_time"),
        "side": side,
        "pp_line": lines.get("prizepicks"),
        "dabble_line": lines.get("dabble"),
        "underdog_line": lines.get("underdog"),
        "book_line": lines.get("book"),
        "book_distance": distance,
        "line_display": line_display(lines),
        "best_platform": best_platform.title() if best_platform else None,
        "best_line": best_line,
        "best_line_flag": flag,
        "platform_count": platform_count,
        "match_confidence": confidence,
        "match_reason": reason,
        "underdog_higher_odds": (ud or {}).get("higher_american_price"),
        "underdog_lower_odds": (ud or {}).get("lower_american_price"),
        "underdog_higher_decimal_price": (ud or {}).get("higher_decimal_price"),
        "underdog_lower_decimal_price": (ud or {}).get("lower_decimal_price"),
        "underdog_line_type": (ud or {}).get("underdog_line_type"),
        "underdog_source_id": (ud or {}).get("source_id") or (ud or {}).get("projection_id"),
        "underdog_updated_at": (ud or {}).get("source_updated_at") or (ud or {}).get("updated_at"),
        "source_projection_ids": {p: r.get("projection_id") for p, r in (("prizepicks", pp), ("underdog", ud), ("dabble", dabble)) if r},
    }


def build_unified_from_rows(league: str, prizepicks_rows: list[dict[str, Any]], dabble_rows: list[dict[str, Any]], underdog_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pp_rows = [dict(r, platform="PrizePicks", normalized_player_name=player_key(r), normalized_stat_type=stat_key(r, league)) for r in prizepicks_rows if include_row("prizepicks", r)]
    ud_rows = [dict(r, platform="Underdog", normalized_player_name=player_key(r), normalized_stat_type=stat_key(r, league)) for r in underdog_rows if include_row("underdog", r)]
    dab_rows = [dict(r, platform="Dabble", normalized_player_name=player_key(r), normalized_stat_type=stat_key(r, league)) for r in dabble_rows if include_row("dabble", r)]
    used_ud: set[int] = set()
    records: list[dict[str, Any]] = []
    mismatch_examples = []
    ud_by_player_stat: dict[tuple[str, str], list[tuple[int, dict[str, Any]]]] = defaultdict(list)
    for i, row in enumerate(ud_rows):
        ud_by_player_stat[(player_key(row), stat_key(row, league))].append((i, row))
    dab_by_player_stat: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in dab_rows:
        dab_by_player_stat[(player_key(row), stat_key(row, league))].append(row)
    for pp in pp_rows:
        side = side_key(pp)
        candidates = ud_by_player_stat.get((player_key(pp), stat_key(pp, league)), [])
        best_match = None
        for idx, ud in candidates:
            result = match_rows(pp, ud, league)
            if result["confidence"] in HIGH_CONFIDENCE:
                best_match = (idx, ud, result)
                break
            if result["confidence"] == LOW_CONFIDENCE and best_match is None:
                best_match = (idx, ud, result)
        if best_match:
            idx, ud, result = best_match
            used_ud.add(idx)
            rows = [pp, ud] + dab_by_player_stat.get((player_key(pp), stat_key(pp, league)), [])
            records.append(build_record(league, rows, result["confidence"], result["reason"], side))
        else:
            for _idx, ud in candidates[:3]:
                res = match_rows(pp, ud, league)
                if res["confidence"] in REJECTED:
                    mismatch_examples.append({"pp_player": pp.get("player_name"), "pp_stat": stat_key(pp, league), "ud_player": ud.get("player_name"), "ud_stat": stat_key(ud, league), "confidence": res["confidence"], "reason": res["reason"]})
            rows = [pp] + dab_by_player_stat.get((player_key(pp), stat_key(pp, league)), [])
            records.append(build_record(league, rows, "prizepicks_only", "no Underdog match found", side))
    for idx, ud in enumerate(ud_rows):
        if idx in used_ud:
            continue
        records.append(build_record(league, [ud] + dab_by_player_stat.get((player_key(ud), stat_key(ud, league)), []), "underdog_only", "no PrizePicks match found", side_key(ud)))
    records.sort(key=lambda r: (r.get("normalized_player_name") or "", r.get("normalized_stat_type") or "", r.get("start_time") or ""))
    for r in records:
        if mismatch_examples and "rejected_mismatch_examples" not in r:
            r["rejected_mismatch_examples"] = mismatch_examples[:10]
            break
    return records


def run_fetcher(platform: str, league: str) -> dict[str, Any]:
    script = SCRIPTS / f"fetch_{platform}.py"
    if not script.exists():
        return {"platform": platform, "status": "missing_script", "script": str(script)}
    cmd = [sys.executable, str(script), "--league", league, "--output", "json"]
    timeout = 180 if platform == "prizepicks" else 240
    cp = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    if cp.stdout:
        print(cp.stdout.rstrip())
    if cp.stderr:
        print(cp.stderr.rstrip(), file=sys.stderr)
    return {"platform": platform, "status": "ok" if cp.returncode == 0 else "failed", "exit_code": cp.returncode}


def load_latest(platform: str, league: str) -> list[dict[str, Any]]:
    path = DATA / league / f"{platform}_{league}_latest.json"
    if not path.exists():
        return []
    try:
        rows = json.loads(path.read_text())
    except Exception as exc:
        log(f"Unable to read {path}: {exc}")
        return []
    return rows if isinstance(rows, list) else []


def build_unified(league: str) -> list[dict[str, Any]]:
    return build_unified_from_rows(league, load_latest("prizepicks", league), load_latest("dabble", league), load_latest("underdog", league))


def find_header(headers: dict[str, int], candidates: list[str]) -> int | None:
    lowered = {norm_text(k): v for k, v in headers.items()}
    for cand in candidates:
        if norm_text(cand) in lowered:
            return lowered[norm_text(cand)]
    return None


def update_player_props_sheet(league: str, unified: list[dict[str, Any]]) -> dict[str, Any]:
    today = datetime.now().strftime("%Y-%m-%d")
    path = DATA / league / f"{league}_{today}.xlsx"
    if not path.exists():
        return {"status": "skipped", "reason": "workbook_not_found", "workbook": str(path)}
    wb = safe_load_workbook(path)
    if "Player Props" not in wb.sheetnames:
        wb.close()
        return {"status": "skipped", "reason": "Player Props sheet missing", "workbook": str(path)}
    ws = wb["Player Props"]
    headers = {str(ws.cell(1, c).value or "").strip(): c for c in range(1, ws.max_column + 1)}
    for header in WORKBOOK_COMPARISON_HEADERS:
        if header not in headers:
            col = ws.max_column + 1
            ws.cell(1, col).value = header
            headers[header] = col
    player_col = find_header(headers, ["Player", "Player Name", "Name"]) or 4
    stat_col = find_header(headers, ["Stat Type", "Stat", "Market", "Prop Type"]) or 7
    game_col = find_header(headers, ["Game ID", "Game", "Match ID"])
    index = defaultdict(list)
    for rec in unified:
        index[(rec.get("normalized_player_name"), rec.get("normalized_stat_type"))].append(rec)
    updated = 0
    mismatch_rows = 0
    for row_idx in range(2, ws.max_row + 1):
        player = ws.cell(row_idx, player_col).value
        stat = ws.cell(row_idx, stat_col).value
        key = (normalize_player_name(player), normalize_stat_type(stat, league))
        candidates = index.get(key, [])
        if not candidates:
            continue
        rec = candidates[0]
        if game_col and rec.get("game_id") and ws.cell(row_idx, game_col).value and str(ws.cell(row_idx, game_col).value) != str(rec.get("game_id")):
            mismatch_rows += 1
            continue
        values = {
            "PP Line": rec.get("pp_line"),
            "Dabble Line": rec.get("dabble_line"),
            "Underdog Line": rec.get("underdog_line"),
            "Book Line": rec.get("book_line"),
            "Best Platform": rec.get("best_platform"),
            "Best Line": rec.get("best_line"),
            "Best Line Flag": rec.get("best_line_flag"),
            "All Platform Lines": rec.get("line_display"),
            "Match Confidence": rec.get("match_confidence"),
            "Underdog Higher Odds": rec.get("underdog_higher_odds"),
            "Underdog Lower Odds": rec.get("underdog_lower_odds"),
            "Underdog Line Type": rec.get("underdog_line_type"),
            "Underdog Source ID": rec.get("underdog_source_id"),
            "Underdog Updated At": rec.get("underdog_updated_at"),
        }
        for header, value in values.items():
            ws.cell(row_idx, headers[header]).value = value
        updated += 1
    safe_save_workbook(wb, path)
    wb.close()
    return {"status": "ok", "workbook": str(path), "rows_updated": updated, "mismatch_rows_skipped": mismatch_rows, "columns": WORKBOOK_COMPARISON_HEADERS}


def schema_audit(league: str, unified: list[dict[str, Any]]) -> dict[str, Any]:
    pp_rows = load_latest("prizepicks", league)
    ud_rows = load_latest("underdog", league)
    pp_fields = set().union(*(r.keys() for r in pp_rows if isinstance(r, dict))) if pp_rows else set()
    ud_fields = set().union(*(r.keys() for r in ud_rows if isinstance(r, dict))) if ud_rows else set()
    equivalent = sorted({"player_name", "stat_name", "stat_type", "line_score", "team", "opponent", "game_id", "start_time", "status", "projection_id"} & pp_fields & ud_fields)
    return {
        "league": league.upper(),
        "field_comparison": {
            "fields_equivalent_to_prizepicks": equivalent,
            "fields_missing_from_underdog": sorted(pp_fields - ud_fields),
            "fields_extra_in_underdog": sorted(ud_fields - pp_fields),
            "fields_different_semantics": ["odds_type", "underdog_line_type", "higher_american_price", "lower_american_price", "higher_decimal_price", "lower_decimal_price", "higher_payout_multiplier", "lower_payout_multiplier"],
            "fields_never_map_directly": ["PrizePicks Demon/Goblin odds_type", "PrizePicks payout/slip multipliers", "Underdog higher/lower American prices", "Underdog higher/lower decimal prices"],
        },
        "match_confidence_counts": dict(Counter(r.get("match_confidence") for r in unified)),
        "multi_platform_matched_rows": sum(1 for r in unified if r.get("platform_count", 0) >= 2 and r.get("match_confidence") in HIGH_CONFIDENCE),
        "low_confidence_rows": sum(1 for r in unified if r.get("match_confidence") == LOW_CONFIDENCE),
        "rejected_mismatch_examples": next((r.get("rejected_mismatch_examples") for r in unified if r.get("rejected_mismatch_examples")), []),
    }


def main() -> dict[str, Any]:
    parser = argparse.ArgumentParser(description="Fetch and unify DFS props across PrizePicks, safe-disabled Dabble, and Underdog")
    parser.add_argument("--league", choices=["nba", "mlb"], default="nba")
    parser.add_argument("--skip-fetch", action="store_true", help="Build unified table from existing latest JSON files")
    args = parser.parse_args()
    league = args.league.lower()
    DATA.joinpath(league).mkdir(parents=True, exist_ok=True)
    fetch_results = []
    if not args.skip_fetch:
        for platform in PLATFORMS:
            result = run_fetcher(platform, league)
            fetch_results.append(result)
            if platform in {"prizepicks", "underdog"} and result.get("status") != "ok":
                log(f"{platform.title()} first-class fetch failed; continuing with any available cached/current DFS source")
    unified = build_unified(league)
    today = datetime.now().strftime("%Y-%m-%d")
    latest_path = DATA / league / f"dfs_props_unified_{league}_latest.json"
    dated_path = DATA / league / f"dfs_props_unified_{league}_{today}.json"
    latest_path.write_text(json.dumps(unified, indent=2, default=str))
    dated_path.write_text(json.dumps(unified, indent=2, default=str))
    audit = schema_audit(league, unified)
    audit_path = RESEARCH / f"underdog_vs_prizepicks_schema_audit_{today}.json"
    existing = {}
    if audit_path.exists():
        try:
            existing = json.loads(audit_path.read_text())
        except Exception:
            existing = {}
    existing[league] = audit
    audit_path.write_text(json.dumps(existing, indent=2, default=str))
    workbook_update = update_player_props_sheet(league, unified)
    summary = {
        "league": league.upper(),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "fetch_results": fetch_results,
        "unified_rows": len(unified),
        "rows_with_multi_platform_lines": sum(1 for r in unified if r.get("platform_count", 0) >= 2),
        "high_confidence_multi_platform_rows": audit["multi_platform_matched_rows"],
        "workbook_update": workbook_update,
        "output_files": {"latest_json": str(latest_path), "dated_json": str(dated_path), "schema_audit": str(audit_path)},
        "boundaries": {"prizepicks_first_class_source": True, "underdog_first_class_source": True, "dabble_disabled_or_blank_when_blocked": True},
    }
    print("\n── SUMMARY ──────────────────────────────")
    print(json.dumps(summary, indent=2))
    log("fetch_dfs_props completed successfully")
    return summary


if __name__ == "__main__":
    main()
