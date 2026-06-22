#!/usr/bin/env python3
"""Calculate SportsEdge injury impact adjustments for NBA picks/props.

Maintains ~/sports_picks/data/research/injury_impact.json and applies impact
rules when nba_injury_monitor detects a key player OUT/DOUBTFUL.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from workbook_io import safe_load_workbook, safe_save_workbook

HOME = Path.home()
ROOT = HOME / "sports_picks"
DATA = ROOT / "data"
NBA_DIR = DATA / "nba"
RESEARCH_DIR = DATA / "research"
IMPACT_DB = RESEARCH_DIR / "injury_impact.json"
RUN_LOG = DATA / "pnl" / "logs" / "run_log.txt"
HERMES_ENV = HOME / ".hermes" / ".env"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

DEFAULT_IMPACTS = [
    {
        "player_out": "Anthony Davis",
        "team": "LAL",
        "source": "seed_default_until_historical_sample_built",
        "sample": {"games_out": 0, "normal_games": 0, "last_updated": None, "new_injury_impacted_games_since_update": 0},
        "impacted_players": [
            {
                "player": "LeBron James",
                "stat": "points",
                "usage_delta": 0.048,
                "projection_multiplier": 1.08,
                "confidence_delta": "+1 tier",
                "notes": "Primary usage absorber when AD out",
            },
            {
                "player": "Austin Reaves",
                "stat": "assists",
                "usage_delta": 0.071,
                "projection_multiplier": 1.12,
                "confidence_delta": "+1 tier",
                "notes": "Secondary ball-handler/playmaking lift when AD out",
            },
        ],
        "team_impacts": {"pace_delta": -1.2, "spread_impact": -2.5, "total_impact": -4.0},
    }
]

POSITION_DEFAULTS = {
    "star_pg": [
        {"target_position": "backup PG", "stat": "assists", "projection_multiplier": 1.15, "confidence_delta": "+1 tier", "notes": "Position default: Star PG out"},
        {"target_position": "SG", "stat": "points", "projection_multiplier": 1.08, "confidence_delta": "+1 tier", "notes": "Position default: Star PG out"},
    ],
    "star_c": [
        {"target_position": "PF", "stat": "rebounds", "projection_multiplier": 1.12, "confidence_delta": "+1 tier", "notes": "Position default: Star C out"},
        {"target_position": "SF", "stat": "points", "projection_multiplier": 1.06, "confidence_delta": "+1 tier", "notes": "Position default: Star C out"},
    ],
    "star_sf": [
        {"target_position": "PG", "stat": "assists", "projection_multiplier": 1.05, "confidence_delta": "+1 tier", "notes": "Position default: Star SF out"},
        {"target_position": "SG", "stat": "points", "projection_multiplier": 1.10, "confidence_delta": "+1 tier", "notes": "Position default: Star SF out"},
    ],
    "starting_pitcher": [
        {"target_position": "bullpen", "stat": "ERA exposure", "projection_multiplier": 1.00, "confidence_delta": "watch", "notes": "Starting pitcher out: bullpen ERA exposure flag"}
    ],
}

STAT_ALIASES = {
    "points": ["point", "points", "pts", "pts+rebs+asts", "fantasy score"],
    "assists": ["assist", "assists", "asts", "pts+rebs+asts", "fantasy score"],
    "rebounds": ["rebound", "rebounds", "rebs", "pts+rebs+asts", "fantasy score"],
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def log(message: str) -> None:
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"[{now_iso()}] calculate_injury_impact — {message}"
    with RUN_LOG.open("a") as f:
        f.write(line + "\n")
    print(line)


def env_value(key: str) -> str | None:
    value = os.environ.get(key)
    if value:
        return value.strip().strip('"').strip("'")
    if HERMES_ENV.exists():
        for line in HERMES_ENV.read_text().splitlines():
            if not line.strip() or line.strip().startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k.strip() == key:
                return v.strip().strip('"').strip("'") or None
    return None


def send_telegram(message: str) -> bool:
    token = env_value("TELEGRAM_BOT_TOKEN")
    chat_id = env_value("TELEGRAM_HOME_CHANNEL") or env_value("TELEGRAM_CHAT_ID")
    thread_id = env_value("TELEGRAM_CRON_THREAD_ID") or env_value("TELEGRAM_HOME_CHANNEL_THREAD_ID")
    if not token or not chat_id:
        log("Telegram skipped: missing TELEGRAM_BOT_TOKEN or TELEGRAM_HOME_CHANNEL")
        return False
    payload: dict[str, Any] = {"chat_id": chat_id, "text": message, "disable_web_page_preview": True}
    if thread_id:
        payload["message_thread_id"] = thread_id
    try:
        r = requests.post(TELEGRAM_API.format(token=token), json=payload, timeout=20)
        if r.status_code != 200:
            log(f"Telegram failed status={r.status_code} body={r.text[:250]}")
            return False
        log("Telegram sent")
        return True
    except Exception as exc:
        log(f"Telegram failed: {exc}")
        return False


def load_db() -> list[dict[str, Any]]:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    if not IMPACT_DB.exists():
        save_db(DEFAULT_IMPACTS)
        return list(DEFAULT_IMPACTS)
    try:
        data = json.loads(IMPACT_DB.read_text())
    except Exception:
        data = []
    if isinstance(data, dict):
        data = data.get("impacts", [])
    if not isinstance(data, list):
        data = []
    existing = {str(item.get("player_out", "")).lower() for item in data if isinstance(item, dict)}
    changed = False
    for item in DEFAULT_IMPACTS:
        if item["player_out"].lower() not in existing:
            data.append(item)
            changed = True
    if changed:
        save_db(data)
    return data


def save_db(data: list[dict[str, Any]]) -> None:
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    IMPACT_DB.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def find_impact(data: list[dict[str, Any]], player_out: str) -> dict[str, Any] | None:
    needle = player_out.strip().lower()
    for item in data:
        if str(item.get("player_out", "")).strip().lower() == needle:
            return item
    return None


def to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(str(value).replace("%", ""))
    except Exception:
        return None


def normal_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def over_probability(projection: float, line: float, stat: str) -> float:
    stat_l = stat.lower()
    if "assist" in stat_l:
        sigma = max(1.2, abs(line) * 0.22)
    elif "rebound" in stat_l:
        sigma = max(1.5, abs(line) * 0.20)
    elif "fantasy" in stat_l:
        sigma = max(5.0, abs(line) * 0.16)
    else:
        sigma = max(2.5, abs(line) * 0.18)
    return max(0.05, min(0.95, 1 - normal_cdf((line - projection) / sigma)))


def ev_from_probability(prob: float) -> float:
    return prob * 0.909 - (1 - prob)


BREAKEVEN_PROBABILITY = 1 / (1 + 0.909)
TIER_ORDER = ["A", "B", "C", "SKIP"]


def normalize_tier(tier: str | None) -> str:
    tier = str(tier or "C").strip().upper()
    if tier.startswith("A"):
        return "A"
    if tier.startswith("B"):
        return "B"
    if tier.startswith("C"):
        return "C"
    if tier.startswith("SKIP") or tier in {"NO PLAY", "PASS"}:
        return "SKIP"
    return "C"


def recalculate_base_tier(edge: float | None, prob: float | None, ev: float | None) -> str:
    """Rebuild the tier from adjusted betting metrics before injury delta.

    Injury impact can only enhance an already-valid betting profile. The base
    tier intentionally starts from the adjusted edge/probability/EV instead of
    preserving the old tier, so a mechanically positive injury note cannot turn
    a negative-EV or negative-edge row into a playable pick.
    """
    if edge is None or prob is None or ev is None:
        return "SKIP"
    if prob < 0.50:
        return "SKIP"
    if edge <= 0 or ev <= 0:
        return "SKIP"
    if edge >= 2.0 and prob >= 0.60 and ev > 0.10:
        return "A"
    if edge >= 1.0 and prob >= 0.54 and ev > 0:
        return "B"
    if prob >= BREAKEVEN_PROBABILITY:
        return "C"
    return "C"


def apply_tier_delta(tier: str, delta: str | None) -> str:
    tier = normalize_tier(tier)
    if tier == "SKIP":
        return "SKIP"
    idx = TIER_ORDER.index(tier)
    if delta == "+1 tier":
        idx = max(0, idx - 1)
    elif delta == "-1 tier":
        idx = min(TIER_ORDER.index("SKIP"), idx + 1)
    return TIER_ORDER[idx]


def guardrail_tier(tier: str, edge: float | None, prob: float | None, ev: float | None) -> tuple[str, bool, list[str]]:
    tier = normalize_tier(tier)
    reasons: list[str] = []
    if edge is None or prob is None or ev is None:
        return "SKIP", False, ["missing adjusted edge/probability/EV"]
    force_skip = False
    if prob < 0.50:
        reasons.append(f"probability {prob:.2%} below 50% hard skip")
        force_skip = True
    if edge <= 0:
        reasons.append(f"edge {edge:+.3f} <= 0")
    if ev <= 0:
        reasons.append(f"EV {ev:+.4f} <= 0")
    if prob < BREAKEVEN_PROBABILITY:
        reasons.append(f"probability {prob:.2%} below breakeven {BREAKEVEN_PROBABILITY:.2%}")
    if force_skip:
        return "SKIP", False, reasons
    if tier in {"A", "B"} and reasons:
        tier = "C"
    playable = tier in {"A", "B"} and not reasons
    return tier, playable, reasons


def injury_direction(multiplier: float) -> str:
    if multiplier > 1:
        return "positive"
    if multiplier < 1:
        return "negative"
    return "neutral"


def stat_matches(prop_stat: str, impact_stat: str) -> bool:
    prop = str(prop_stat or "").lower()
    impact = str(impact_stat or "").lower()
    if not impact:
        return True
    if impact in prop:
        return True
    return any(alias in prop for alias in STAT_ALIASES.get(impact, []))


def header_map(ws) -> dict[str, int]:
    return {str(ws.cell(1, c).value or "").strip(): c for c in range(1, ws.max_column + 1)}


def ensure_col(ws, headers: dict[str, int], name: str) -> int:
    if name in headers:
        return headers[name]
    col = ws.max_column + 1
    ws.cell(1, col).value = name
    headers[name] = col
    return col


def current_workbook(date_text: str) -> Path:
    return NBA_DIR / f"nba_{date_text}.xlsx"


def apply_to_workbook(impact: dict[str, Any], workbook: Path, dry_run: bool) -> dict[str, Any]:
    result: dict[str, Any] = {"workbook": str(workbook), "prop_adjustments": [], "team_adjustments": [], "rows_updated": 0}
    if not workbook.exists():
        result["warning"] = f"Workbook not found: {workbook}"
        return result
    wb = safe_load_workbook(workbook)
    try:
        for sheet_name in ["Player Props", "Props"]:
            if sheet_name not in wb.sheetnames:
                continue
            ws = wb[sheet_name]
            headers = header_map(ws)
            required = ["Player Name", "Stat", "Model Projection", "Line", "Edge", "Model Over Probability", "EV", "Confidence", "Reasoning", "Injury Flag"]
            if not all(h in headers for h in required if h not in {"Injury Flag"}):
                continue
            injury_adjusted_col = ensure_col(ws, headers, "Injury Adjusted")
            pre_injury_tier_col = ensure_col(ws, headers, "Pre Injury Tier")
            injury_direction_col = ensure_col(ws, headers, "Injury Direction")
            injury_delta_col = ensure_col(ws, headers, "Injury Suggested Tier Delta")
            final_tier_col = ensure_col(ws, headers, "Final Tier")
            playable_col = ensure_col(ws, headers, "Injury Adjusted Playable")
            adjustment_reason_col = ensure_col(ws, headers, "Injury Adjustment Reason")
            for r in range(2, ws.max_row + 1):
                player = str(ws.cell(r, headers["Player Name"]).value or "").strip()
                stat = str(ws.cell(r, headers["Stat"]).value or "").strip()
                if not player:
                    continue
                for impacted in impact.get("impacted_players", []) or []:
                    if player.lower() != str(impacted.get("player", "")).lower():
                        continue
                    if not stat_matches(stat, str(impacted.get("stat") or "")):
                        continue
                    old_projection = to_float(ws.cell(r, headers["Model Projection"]).value)
                    line = to_float(ws.cell(r, headers["Line"]).value)
                    multiplier = float(impacted.get("projection_multiplier") or 1.0)
                    if old_projection is None:
                        old_projection = line
                    if old_projection is None:
                        continue
                    new_projection = round(old_projection * multiplier, 3)
                    edge = round(new_projection - line, 3) if line is not None else None
                    prob = round(over_probability(new_projection, line, stat), 4) if line is not None else None
                    ev = round(ev_from_probability(prob), 4) if prob is not None else None
                    pre_injury_tier = str(ws.cell(r, headers["Confidence"]).value or "C")
                    base_tier = recalculate_base_tier(edge, prob, ev)
                    suggested_delta = str(impacted.get("confidence_delta") or "")
                    suggested_tier = apply_tier_delta(base_tier, suggested_delta)
                    final_tier, playable, guardrail_reasons = guardrail_tier(suggested_tier, edge, prob, ev)
                    direction = injury_direction(multiplier)
                    if guardrail_reasons:
                        adjustment_reason = "; ".join(guardrail_reasons)
                    elif playable:
                        adjustment_reason = "adjusted metrics support playable tier"
                    else:
                        adjustment_reason = "adjusted metrics support watchlist tier only"
                    adj = {
                        "sheet": sheet_name,
                        "row": r,
                        "player": player,
                        "stat": stat,
                        "old_projection": old_projection,
                        "new_projection": new_projection,
                        "projection_multiplier": multiplier,
                        "pre_injury_tier": pre_injury_tier,
                        "base_tier": base_tier,
                        "injury_direction": direction,
                        "injury_suggested_tier_delta": suggested_delta,
                        "suggested_tier": suggested_tier,
                        "final_tier": final_tier,
                        "injury_adjusted_playable": "YES" if playable else "NO",
                        "injury_adjustment_reason": adjustment_reason,
                        "old_tier": pre_injury_tier,
                        "new_tier": final_tier,
                        "edge": edge,
                        "over_probability": prob,
                        "breakeven_probability": round(BREAKEVEN_PROBABILITY, 4),
                        "ev": ev,
                        "notes": impacted.get("notes"),
                    }
                    result["prop_adjustments"].append(adj)
                    if not dry_run:
                        ws.cell(r, headers["Model Projection"]).value = new_projection
                        if edge is not None:
                            ws.cell(r, headers["Edge"]).value = edge
                        if prob is not None:
                            ws.cell(r, headers["Model Over Probability"]).value = prob
                        if ev is not None:
                            ws.cell(r, headers["EV"]).value = ev
                        ws.cell(r, headers["Confidence"]).value = final_tier
                        ws.cell(r, injury_adjusted_col).value = "YES"
                        ws.cell(r, pre_injury_tier_col).value = normalize_tier(pre_injury_tier)
                        ws.cell(r, injury_direction_col).value = direction
                        ws.cell(r, injury_delta_col).value = suggested_delta
                        ws.cell(r, final_tier_col).value = final_tier
                        ws.cell(r, playable_col).value = "YES" if playable else "NO"
                        ws.cell(r, adjustment_reason_col).value = adjustment_reason
                        if "Injury Flag" in headers:
                            ws.cell(r, headers["Injury Flag"]).value = f"Adjusted for {impact.get('player_out')} OUT"
                        reason = str(ws.cell(r, headers["Reasoning"]).value or "")
                        ws.cell(r, headers["Reasoning"]).value = (reason + f" | INJURY ADJUSTED {now_iso()}: {impact.get('player_out')} OUT, projection {old_projection} -> {new_projection}, pre tier {pre_injury_tier} -> base {base_tier} -> final {final_tier}, playable {'YES' if playable else 'NO'} ({adjustment_reason})").strip(" |")
                        result["rows_updated"] += 1
        if "Picks" in wb.sheetnames:
            ws = wb["Picks"]
            headers = header_map(ws)
            impacts = impact.get("team_impacts") or {}
            spread_impact = abs(float(impacts.get("spread_impact") or 0))
            total_impact = abs(float(impacts.get("total_impact") or 0))
            for r in range(2, ws.max_row + 1):
                pick_type = str(ws.cell(r, headers.get("Pick Type", 1)).value or "").lower()
                selection = str(ws.cell(r, headers.get("Selection", 1)).value or "")
                if "spread" in pick_type and spread_impact > 1.5:
                    result["team_adjustments"].append({"sheet": "Picks", "row": r, "type": "spread", "selection": selection, "spread_impact": impacts.get("spread_impact")})
                if "total" in pick_type and total_impact > 3.0:
                    result["team_adjustments"].append({"sheet": "Picks", "row": r, "type": "total", "selection": selection, "total_impact": impacts.get("total_impact")})
        if not dry_run:
            safe_save_workbook(wb, workbook)
    finally:
        wb.close()
    return result


def build_alert(player_out: str, team: str, applied: dict[str, Any], impact: dict[str, Any]) -> str:
    lines = ["🔄 INJURY ADJUSTMENT", f"{player_out} OUT → {team or impact.get('team') or 'team unknown'} impacts:"]
    if applied.get("prop_adjustments"):
        for adj in applied["prop_adjustments"][:10]:
            action = "upgraded" if str(adj.get("new_tier")) < str(adj.get("old_tier")) else "adjusted"
            lines.append(f"{adj['player']} {adj['stat']} {action}: proj {adj['old_projection']} → {adj['new_projection']} | tier {adj['old_tier']} → {adj['new_tier']}")
    else:
        for impacted in impact.get("impacted_players", []) or []:
            lines.append(f"{impacted.get('player')} {impacted.get('stat')} watch: multiplier {impacted.get('projection_multiplier')} ({impacted.get('notes', 'impact lookup')})")
        lines.append("No matching teammate props found in today's workbook, so no rows were changed.")
    for team_adj in applied.get("team_adjustments", [])[:5]:
        if team_adj.get("type") == "spread":
            lines.append(f"Spread adjusted/watch: impact {team_adj.get('spread_impact')} on {team_adj.get('selection')}")
        if team_adj.get("type") == "total":
            lines.append(f"Total adjusted/watch: impact {team_adj.get('total_impact')} on {team_adj.get('selection')}")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--player", required=True, help="Player ruled OUT/DOUBTFUL")
    p.add_argument("--team", default="", help="Team abbreviation")
    p.add_argument("--status", default="OUT", help="Current status")
    p.add_argument("--date", default="today", help="YYYY-MM-DD or today")
    p.add_argument("--workbook", default="", help="Override NBA workbook path")
    p.add_argument("--dry-run", action="store_true", help="Simulate without saving workbook or sending Telegram")
    p.add_argument("--send-telegram", action="store_true", help="Send Telegram alert; ignored in dry-run")
    p.add_argument("--position-default", choices=sorted(POSITION_DEFAULTS), default=None, help="Use position-based default if player is not in DB")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    date_text = today_str() if args.date == "today" else args.date
    db = load_db()
    impact = find_impact(db, args.player)
    source = "database"
    if impact is None:
        defaults = POSITION_DEFAULTS.get(args.position_default or "", [])
        impact = {"player_out": args.player, "team": args.team, "source": "position_default", "impacted_players": defaults, "team_impacts": {}, "sample": {"games_out": 0, "normal_games": 0}}
        source = "position_default" if defaults else "no_match"
    workbook = Path(args.workbook) if args.workbook else current_workbook(date_text)
    applied = apply_to_workbook(impact, workbook, dry_run=args.dry_run)
    alert = build_alert(args.player, args.team, applied, impact)
    telegram_sent = False
    if args.send_telegram and not args.dry_run:
        telegram_sent = send_telegram(alert)
    log(f"player={args.player} status={args.status} source={source} dry_run={args.dry_run} prop_adjustments={len(applied.get('prop_adjustments', []))} rows_updated={applied.get('rows_updated', 0)} workbook={workbook}")
    out = {
        "status": "ok",
        "player_out": args.player,
        "team": args.team or impact.get("team"),
        "date": date_text,
        "impact_database": str(IMPACT_DB),
        "impact_source": source,
        "dry_run": args.dry_run,
        "telegram_sent": telegram_sent,
        "alert": alert,
        "impact": impact,
        "applied": applied,
    }
    print(json.dumps(out, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
