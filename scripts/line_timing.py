#!/usr/bin/env python3
"""SportsEdge line timing classifier for DFS/player-prop rows.

Classifies rows as pregame/live/halftime/in_game/stale/unknown without approving
live lines by default. This module intentionally uses only source metadata and
time relationships; it does not infer betting value.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Any

MAX_BOARD_PULL_AGE_MINUTES = int(os.environ.get("MAX_BOARD_PULL_AGE_MINUTES", "10"))
MAX_UNKNOWN_TIMING_AGE_MINUTES = int(os.environ.get("MAX_UNKNOWN_TIMING_AGE_MINUTES", "60"))
DO_NOT_USE_PROJECTION_UPDATED_AT_AS_LINE_FRESHNESS = os.environ.get(
    "DO_NOT_USE_PROJECTION_UPDATED_AT_AS_LINE_FRESHNESS", "true"
).strip().lower() not in {"0", "false", "no", "off"}

LINE_TIMING_FIELDS = [
    "Line Timing", "Line Timing Confidence", "Line Timing Reason", "Source Timestamp",
    "Game Start Time", "Minutes To Start", "Minutes Since Start", "Live Line Flag", "Stale Line Flag",
]

LINE_TIMING_KEYS = [
    "line_timing", "line_timing_confidence", "line_timing_reason", "source_timestamp",
    "game_start_time", "minutes_to_game_start", "minutes_since_game_start",
    "source_game_status", "live_line_flag", "stale_line_flag",
    "projection_created_at", "projection_updated_at", "game_created_at", "game_updated_at",
    "board_scrape_time", "source_timestamp_role", "line_freshness_timestamp", "line_freshness_reason",
]

LIVE_TIMINGS = {"live", "in_game", "halftime"}
NON_PREGAME_TIMINGS = LIVE_TIMINGS | {"unknown", "stale"}
HALFTIME_TOKENS = {"halftime", "half-time", "intermission", "end of period", "end_period", "break"}
LIVE_TOKENS = {"live", "in_game", "ingame", "in progress", "in_progress", "active", "started", "1st", "2nd", "3rd", "4th", "inning", "period", "quarter"}
PREGAME_TOKENS = {"pre_game", "pre-game", "pregame", "scheduled", "not started", "not_started", "created", "open"}
FINAL_TOKENS = {"final", "completed", "closed", "settled", "postponed", "cancelled", "canceled"}


def parse_dt(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        # Fetcher also emits "YYYY-MM-DD HH:MM:SS UTC".
        if text.endswith(" UTC"):
            text = text[:-4] + "+00:00"
        text = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except Exception:
            for fmt in ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    dt = datetime.strptime(str(value).strip(), fmt)
                    break
                except Exception:
                    dt = None
            if dt is None:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_or_none(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds") if dt else None


def _first(row: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in row and row.get(name) not in (None, ""):
            return row.get(name)
    return None


def _boolish(value: Any) -> bool:
    if value is True:
        return True
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "live", "in_game", "ingame"}


def _infer_source_timestamp_role(row: dict[str, Any], source_dt: datetime | None) -> str | None:
    explicit = row.get("source_timestamp_role")
    if explicit:
        return str(explicit)
    if not source_dt:
        return None
    comparisons = [
        ("projection_updated_at", _first(row, ["projection_updated_at", "updated_at"])),
        ("projection_created_at", _first(row, ["projection_created_at", "created_at"])),
        ("game_updated_at", row.get("game_updated_at")),
        ("game_created_at", row.get("game_created_at")),
        ("board_scrape_time", _first(row, ["board_scrape_time", "board_pull_time", "fetched_at"])),
    ]
    for role, value in comparisons:
        dt = parse_dt(value)
        if dt and abs((dt - source_dt).total_seconds()) < 2:
            return role
    return "unknown"


def classify_line_timing(
    row: dict[str, Any],
    *,
    board_pull_time: Any = None,
    now: Any = None,
    stale_minutes: int | None = None,
) -> dict[str, Any]:
    """Classify one player-prop row.

    PrizePicks projection ``updated_at`` is projection metadata, not proof that the
    active board line is stale. Freshness is based on a known line freshness
    timestamp when available, otherwise the current board scrape/pull time. A prop
    seen on a fresh current board for a future scheduled game is pregame unless
    explicit live/in-game metadata says otherwise.
    """
    current = parse_dt(now) or datetime.now(timezone.utc)
    max_board_age = stale_minutes if stale_minutes is not None else MAX_BOARD_PULL_AGE_MINUTES
    board_dt = parse_dt(board_pull_time) or parse_dt(_first(row, ["board_scrape_time", "board_pull_time", "fetched_at"]))
    source_dt = parse_dt(_first(row, ["source_timestamp", "projection_updated_at", "updated_at", "projection_created_at", "created_at"]))
    source_role = _infer_source_timestamp_role(row, source_dt)
    game_dt = parse_dt(_first(row, ["game_start_time", "commence_time", "commence_time_utc", "scheduled_at", "start_time"]))
    status_raw = _first(row, ["source_game_status", "game_status", "status", "event_status", "state", "status_description"])
    status = str(status_raw or "").strip().lower()
    meta_text = " ".join(str(_first(row, [k]) or "") for k in [
        "event_type", "projection_type", "board_category", "duration", "description", "period", "quarter", "inning", "time_remaining"
    ]).lower()
    explicit_live = any(_boolish(_first(row, [k])) for k in ["is_live", "live", "in_game", "live_line_flag"])
    explicit_halftime = any(tok in status or tok in meta_text for tok in HALFTIME_TOKENS)
    active_status = any(tok in status or tok in meta_text for tok in LIVE_TOKENS) and not any(tok in status for tok in FINAL_TOKENS)
    scheduled_status = any(tok in status for tok in PREGAME_TOKENS)

    line_freshness_dt = parse_dt(row.get("line_freshness_timestamp"))
    line_freshness_reason = row.get("line_freshness_reason")
    if not line_freshness_dt and board_dt:
        line_freshness_dt = board_dt
        line_freshness_reason = line_freshness_reason or "prop observed in current DFS board pull"
    elif line_freshness_dt:
        line_freshness_reason = line_freshness_reason or "explicit line freshness timestamp"

    board_age = (current - board_dt).total_seconds() / 60 if board_dt else None
    line_age = (current - line_freshness_dt).total_seconds() / 60 if line_freshness_dt else None
    reference_dt = board_dt or current
    minutes_to = round((game_dt - reference_dt).total_seconds() / 60, 2) if game_dt else None
    minutes_since = round((reference_dt - game_dt).total_seconds() / 60, 2) if game_dt and reference_dt >= game_dt else None

    reason_parts: list[str] = []
    timing = "unknown"
    confidence = "low"

    if not board_dt:
        timing = "unknown"
        confidence = "low"
        reason_parts.append("board scrape time missing; cannot confirm current board freshness")
    elif board_age is not None and board_age > max_board_age:
        timing = "stale"
        confidence = "high"
        reason_parts.append(f"board pull is {board_age:.1f} minutes old (max {max_board_age})")
    elif not game_dt:
        timing = "unknown"
        confidence = "low"
        reason_parts.append("game start time missing")
    elif explicit_halftime:
        timing = "halftime"
        confidence = "high"
        reason_parts.append("source metadata indicates halftime/intermission")
    elif explicit_live:
        timing = "live"
        confidence = "high"
        reason_parts.append("source metadata explicitly indicates live/in_game")
    elif active_status:
        timing = "in_game"
        confidence = "high"
        reason_parts.append(f"source game status/period indicates active: {status_raw}")
    elif reference_dt >= game_dt and not any(tok in status for tok in FINAL_TOKENS):
        timing = "stale" if scheduled_status else "unknown"
        confidence = "medium"
        reason_parts.append("game has started/passed but row lacks clear live metadata")
    elif scheduled_status and not explicit_live and not active_status and reference_dt < game_dt:
        timing = "pregame"
        confidence = "high"
        reason_parts.append("fresh board pull shows future scheduled pregame line with no live metadata")
        if source_role in {"projection_updated_at", "projection_created_at"} and DO_NOT_USE_PROJECTION_UPDATED_AT_AS_LINE_FRESHNESS:
            reason_parts.append(f"{source_role} ignored for line freshness")
    elif reference_dt < game_dt and not explicit_live and not active_status:
        timing = "pregame"
        confidence = "medium"
        reason_parts.append("fresh board pull shows future game line with no live metadata")
    elif line_age is not None and line_age > max_board_age and source_role == "board_scrape_time":
        timing = "stale"
        confidence = "high"
        reason_parts.append(f"known line freshness timestamp is {line_age:.1f} minutes old")
    else:
        timing = "unknown"
        confidence = "low"
        reason_parts.append("conflicting or insufficient source timing metadata")

    return {
        "line_timing": timing,
        "line_timing_confidence": confidence,
        "line_timing_reason": "; ".join(reason_parts),
        "game_start_time": iso_or_none(game_dt),
        "source_timestamp": iso_or_none(source_dt),
        "minutes_to_game_start": minutes_to,
        "minutes_since_game_start": minutes_since,
        "source_game_status": status_raw,
        "live_line_flag": timing in LIVE_TIMINGS,
        "stale_line_flag": timing == "stale",
        "projection_created_at": _first(row, ["projection_created_at", "created_at"]),
        "projection_updated_at": _first(row, ["projection_updated_at", "updated_at"]),
        "game_created_at": row.get("game_created_at"),
        "game_updated_at": row.get("game_updated_at"),
        "board_scrape_time": iso_or_none(board_dt),
        "source_timestamp_role": source_role,
        "line_freshness_timestamp": iso_or_none(line_freshness_dt),
        "line_freshness_reason": line_freshness_reason,
    }


def apply_line_timing(row: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    row.update(classify_line_timing(row, **kwargs))
    return row


def gate12_line_timing(row: dict[str, Any], *, enable_live_prop_betting: bool = False, require_pregame_for_daily_picks: bool = True) -> tuple[bool, str]:
    timing = str(row.get("line_timing") or "unknown").lower()
    reason = row.get("line_timing_reason") or ""
    if timing == "pregame":
        return True, "pregame line cleared"
    if timing in LIVE_TIMINGS:
        if enable_live_prop_betting:
            return False, f"{timing} line requires separate live projection model; live model unavailable"
        return False, f"{timing} line routed to Live Watchlist; live prop betting disabled"
    if timing == "stale":
        return False, f"stale line timing: {reason}"
    return False, f"line timing unknown: {reason or 'insufficient metadata'}"


def line_timing_workbook_values(row: dict[str, Any]) -> list[Any]:
    return [
        row.get("line_timing"), row.get("line_timing_confidence"), row.get("line_timing_reason"),
        row.get("source_timestamp"), row.get("game_start_time"), row.get("minutes_to_game_start"),
        row.get("minutes_since_game_start"), row.get("live_line_flag"), row.get("stale_line_flag"),
    ]
