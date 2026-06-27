#!/usr/bin/env python3
"""verify_results.py — Layer-2 scraped fallback for the trustworthy-results milestone.

Standalone script: NEVER imported by sports_system_runner.py.
All firecrawl risk is contained here; the runner invokes this via _subprocess_run_with_retry.

CLI:
    python3 verify_results.py --sport <mlb|nba> --game-id <id> [--date <YYYY-MM-DD>]

Output (stdout):
    JSON_RESULT={"status": "ok"|"skip", "schema": 1, "reason": "<str when skip>",
                 "players": {"<canonical_name>": {"<stat_key>": <float>}}}

    status="ok"   => scrape succeeded; player absent => legitimate "not in box"
    status="skip" => scrape could not run (missing binary/node/network/429/non-zero exit)

Version pin:
    FIRECRAWL_CLI = "firecrawl-cli@1.19.2"  — never @latest; enforced at runtime.

Keyless-first:
    Runs without FIRECRAWL_API_KEY by default; key is injected only when present (raises limits).
    A missing key does NOT disable the fallback.

Invocation contract (exact, no deviations):
    npx -y firecrawl-cli@1.19.2 firecrawl scrape <url> --format markdown
    FORBIDDEN: --browser, --format json, init, @latest
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any

# Pinned CLI version — never @latest.
# This constant is imported by tests to verify the version pin is enforced.
FIRECRAWL_CLI: str = "firecrawl-cli@1.19.2"

# ESPN box score URL template.
ESPN_BOX_URL_TEMPLATE: str = "https://www.espn.com/{sport}/boxscore/_/gameId/{game_id}"

# Per-scrape timeout guard (seconds) — subprocess caller also enforces RESULT_SCRAPE_TIMEOUT.
_SCRAPE_TIMEOUT_S: int = 60

# Stat key normalization: map ESPN box column headers to canonical stat keys.
# Batting table columns (MLB)
_MLB_BATTING_COL_MAP: dict[str, str] = {
    "ab": "ab",
    "r": "runs",
    "h": "hits",
    "rbi": "rbis",
    "hr": "homeruns",
    "bb": "walks",
    "k": "strikeouts",
    # Some ESPN renders use different header casing
    "so": "strikeouts",
    "2b": "doubles",
    "3b": "triples",
    "sb": "stolen_bases",
    "cs": "caught_stealing",
    "avg": "avg",
    "obp": "obp",
    "slg": "slg",
    "ops": "ops",
}

# Pitching table columns (MLB)
_MLB_PITCHING_COL_MAP: dict[str, str] = {
    "ip": "ip",
    "h": "hits_allowed",
    "r": "runs_allowed",
    "er": "earned_runs",
    "bb": "walks",
    "k": "strikeouts",
    "so": "strikeouts",
    "hr": "hr_allowed",
    "era": "era",
    "np": "pitches",
    "pitches": "pitches",
    # Some tables use "pc" for pitch count
    "pc": "pitches",
}

# NBA player box table columns
_NBA_COL_MAP: dict[str, str] = {
    "min": "minutes",
    "fg": "fg",         # field goals (made-attempted)
    "3pt": "3pt",       # three pointers (made-attempted)
    "ft": "ft",         # free throws (made-attempted)
    "oreb": "offensiverebounds",
    "dreb": "defensiverebounds",
    "reb": "rebounds",
    "ast": "assists",
    "stl": "steals",
    "blk": "blocks",
    "to": "turnovers",
    "pf": "fouls",
    "pts": "points",
    "+/-": "plus_minus",
}


def _canonical_name(name: Any) -> str:
    """Normalize a player name for fuzzy matching.

    Applies: coerce to str -> lowercase -> NFKD unicode normalize (drop combining marks) ->
    replace . ' ' - with spaces -> drop trailing suffix tokens (jr/sr/ii/iii/iv) ->
    collapse whitespace.
    """
    s = str(name or "").lower()
    # NFKD normalize and drop combining characters (handles accents: Jokić -> jokic)
    s = "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))
    # Replace punctuation with spaces
    s = re.sub(r"[.\'\'\-]", " ", s)
    # Drop trailing suffix tokens
    tokens = s.split()
    while tokens and tokens[-1] in {"jr", "sr", "ii", "iii", "iv"}:
        tokens.pop()
    return " ".join(tokens)


def player_appearance(players: dict[str, Any], player: Any, status: str) -> str:
    """Tri-state appearance signal from a scraped box score (GAP 1 / RESULTS-05).

    Returns:
        "played"  — player is present in the box score (status="ok" + name matched)
        "dnp"     — player is absent AND the box was fully read (status="ok")
                    A status="ok" with an empty players dict counts as "dnp" (box read,
                    player not listed).
        "unknown" — scrape status is "skip"/error, or player name is empty/ambiguous
                    -> ABSTAIN; do NOT grade anything from this signal alone.

    Money-safety contract:
        VOID grading requires "dnp" (confirmed absence).
        "unknown" must stay MANUAL REVIEW — never coerce to VOID or LOSS.
    """
    # Empty or missing player name — ambiguous, abstain.
    player_str = str(player or "").strip()
    if not player_str:
        return "unknown"

    # Non-ok status (skip, error, etc.) — transient failure, abstain.
    if status != "ok":
        return "unknown"

    # Box was fully read (status=ok). Check if the player appears.
    # Use _canonical_name to normalise both sides for comparison.
    canonical_player = _canonical_name(player_str)
    if not canonical_player:
        return "unknown"

    for box_name in players:
        if _canonical_name(box_name) == canonical_player:
            return "played"

    # status=ok, box fully read, player not found -> confirmed absent.
    return "dnp"


def _is_totals_row(cells: list[str]) -> bool:
    """Return True if this is a Totals/Team row (should be skipped)."""
    if not cells:
        return False
    first = cells[0].strip().lower()
    return first.startswith("total") or first == "team"


def _parse_ip(ip_str: str) -> float | None:
    """Parse innings pitched string like '5.2' -> fractional innings float.

    ESPN uses X.Y where Y is the outs count (0, 1, or 2), not tenths.
    So 5.2 = 5 full innings + 2 outs = 5.666... actual innings.
    We return the raw IP value as a float for storage; callers convert to outs.
    """
    try:
        return float(ip_str.strip())
    except (ValueError, AttributeError):
        return None


def _to_float(val: str) -> float | None:
    """Convert a string cell to float, returning None on failure."""
    s = str(val or "").strip()
    # Remove trailing letter suffixes from batting-average-style cells
    s = re.sub(r"[a-zA-Z]+$", "", s).strip()
    try:
        return float(s)
    except ValueError:
        return None


def _strip_player_suffix(name: str) -> str:
    """Remove position/status annotations from a player name cell.

    ESPN box tables often include position or game-status in the name column:
    'Bobby Witt Jr. SS', 'Pablo Lopez (W, 12-3)', 'Cole Ragans (L, 8-5)'
    We strip trailing position tokens and parenthetical annotations.
    """
    # Remove parenthetical (W, 12-3), (L, 8-5), (SV, 5), etc.
    s = re.sub(r"\s*\([^)]*\)", "", name).strip()
    # Remove trailing position abbreviations (1-4 uppercase letters at end)
    s = re.sub(r"\s+[A-Z]{1,4}$", "", s).strip()
    # Handle position codes that appear inline like "CF", "LF", "RF", "DH", "1B", etc.
    s = re.sub(r"\s+(C|P|1B|2B|3B|SS|LF|CF|RF|DH|PH|PR|BN|NA)$", "", s).strip()
    return s


def _parse_markdown_table(md_text: str) -> list[tuple[list[str], list[list[str]]]]:
    """Parse all markdown tables from text.

    Returns list of (headers, rows) where each entry is a table.
    Headers and rows are lists of stripped cell strings.
    """
    tables: list[tuple[list[str], list[list[str]]]] = []
    lines = md_text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Detect a markdown table header row: | col | col | ...
        if line.startswith("|") and "|" in line[1:]:
            # Parse header
            headers = [c.strip() for c in line.split("|") if c.strip()]
            # Check for separator row
            if i + 1 < len(lines):
                sep = lines[i + 1].strip()
                if re.match(r"^\|[-:| ]+\|$", sep):
                    rows: list[list[str]] = []
                    j = i + 2
                    while j < len(lines):
                        row_line = lines[j].strip()
                        if not row_line.startswith("|"):
                            break
                        cells = [c.strip() for c in row_line.split("|") if c.strip() != ""]
                        if cells:
                            rows.append(cells)
                        j += 1
                    if headers and rows:
                        tables.append((headers, rows))
                    i = j
                    continue
        i += 1
    return tables


def _detect_table_type(headers: list[str]) -> str | None:
    """Return 'mlb_batting', 'mlb_pitching', 'nba', or None."""
    header_lower = [h.lower() for h in headers]
    # MLB batting: has AB or H or R or RBI
    batting_markers = {"ab", "rbi"}
    if batting_markers & set(header_lower):
        return "mlb_batting"
    # MLB pitching: has IP or ER
    pitching_markers = {"ip", "er"}
    if pitching_markers & set(header_lower):
        return "mlb_pitching"
    # NBA: has pts or ast or reb
    nba_markers = {"pts", "ast", "reb"}
    if nba_markers & set(header_lower):
        return "nba"
    return None


def _parse_fg_split(value: str, kind: str) -> float | None:
    """Parse FG/3PT/FT 'made-attempted' strings.

    kind='made' or 'attempted'.
    '12-18' -> made=12, attempted=18
    """
    m = re.match(r"^(\d+)-(\d+)$", value.strip())
    if not m:
        return None
    if kind == "made":
        return float(m.group(1))
    if kind == "attempted":
        return float(m.group(2))
    return None


def _parse_mlb_batting_row(
    headers: list[str], cells: list[str]
) -> tuple[str | None, dict[str, float]]:
    """Parse one batting row. Returns (raw_name, stats_dict) or (None, {}) on failure."""
    if not cells or _is_totals_row(cells):
        return None, {}
    # First cell is the player name (+ position)
    raw_name = _strip_player_suffix(cells[0])
    if not raw_name:
        return None, {}
    stats: dict[str, float] = {}
    col_map = _MLB_BATTING_COL_MAP
    for i, hdr in enumerate(headers):
        if i >= len(cells):
            break
        h = hdr.lower().strip()
        key = col_map.get(h)
        if key is None:
            continue
        v = _to_float(cells[i])
        if v is not None:
            stats[key] = v
    # Ensure hits is present (required for many derived stats)
    if not stats:
        return None, {}
    return raw_name, stats


def _parse_mlb_pitching_row(
    headers: list[str], cells: list[str]
) -> tuple[str | None, dict[str, float]]:
    """Parse one pitching row. Returns (raw_name, stats_dict) or (None, {}) on failure."""
    if not cells or _is_totals_row(cells):
        return None, {}
    raw_name = _strip_player_suffix(cells[0])
    if not raw_name:
        return None, {}
    stats: dict[str, float] = {}
    col_map = _MLB_PITCHING_COL_MAP
    for i, hdr in enumerate(headers):
        if i >= len(cells):
            break
        h = hdr.lower().strip()
        key = col_map.get(h)
        if key is None:
            continue
        if key == "ip":
            v = _parse_ip(cells[i])
        else:
            v = _to_float(cells[i])
        if v is not None:
            stats[key] = v
    if not stats:
        return None, {}
    return raw_name, stats


def _parse_nba_row(
    headers: list[str], cells: list[str]
) -> tuple[str | None, dict[str, float]]:
    """Parse one NBA player row. Returns (raw_name, stats_dict) or (None, {}) on failure."""
    if not cells or _is_totals_row(cells):
        return None, {}
    raw_name = _strip_player_suffix(cells[0])
    if not raw_name or raw_name.lower() in {"dnp", "did not play"}:
        return None, {}
    stats: dict[str, float] = {}
    for i, hdr in enumerate(headers):
        if i >= len(cells):
            break
        h = hdr.lower().strip()
        key = _NBA_COL_MAP.get(h)
        if key is None:
            continue
        val_str = cells[i].strip()
        # FG, 3PT, FT are "made-attempted" splits
        if key in {"fg", "3pt", "ft"}:
            made = _parse_fg_split(val_str, "made")
            attempted = _parse_fg_split(val_str, "attempted")
            prefix = {"fg": "fieldgoals", "3pt": "threepoint", "ft": "freethrows"}[key]
            if made is not None:
                stats[f"{prefix}made"] = made
            if attempted is not None:
                stats[f"{prefix}attempted"] = attempted
            # Also store as "X-pt made" canonical forms used by disposition table
            if key == "3pt" and made is not None:
                stats["3-pt made"] = made
        else:
            v = _to_float(val_str)
            if v is not None:
                stats[key] = v
    if not stats:
        return None, {}
    return raw_name, stats


def parse_espn_box_markdown(md_text: str) -> dict[str, dict[str, Any]]:
    """Parse ESPN box score markdown into {canonical_name: {stat_key: float}}.

    For MLB, each player has sub-dicts:
        {"batting": {...}, "pitching": {...}}
    (whichever is present).

    For NBA, each player has a flat stat dict.

    Returns an empty dict on parse failure.
    """
    players: dict[str, dict[str, Any]] = {}
    tables = _parse_markdown_table(md_text)
    if not tables:
        return {}

    for hdrs, rows in tables:
        tbl_type = _detect_table_type(hdrs)
        if tbl_type == "mlb_batting":
            for cells in rows:
                name_raw, stats = _parse_mlb_batting_row(hdrs, cells)
                if name_raw:
                    cname = _canonical_name(name_raw)
                    if cname not in players:
                        players[cname] = {"batting": {}, "pitching": {}}
                    elif "batting" not in players[cname]:
                        players[cname]["batting"] = {}
                    players[cname]["batting"].update(stats)
                    # Also store hits/runs/rbis at top level for backward compat
                    players[cname].update({k: v for k, v in stats.items()
                                           if k not in {"batting", "pitching"}})

        elif tbl_type == "mlb_pitching":
            for cells in rows:
                name_raw, stats = _parse_mlb_pitching_row(hdrs, cells)
                if name_raw:
                    cname = _canonical_name(name_raw)
                    if cname not in players:
                        players[cname] = {"batting": {}, "pitching": {}}
                    elif "pitching" not in players[cname]:
                        players[cname]["pitching"] = {}
                    players[cname]["pitching"].update(stats)

        elif tbl_type == "nba":
            for cells in rows:
                name_raw, stats = _parse_nba_row(hdrs, cells)
                if name_raw:
                    cname = _canonical_name(name_raw)
                    if cname not in players:
                        players[cname] = {}
                    players[cname].update(stats)

    return players


def _emit_result(status: str, reason: str = "", players: dict[str, Any] | None = None) -> None:
    """Print the JSON_RESULT envelope to stdout and exit."""
    envelope: dict[str, Any] = {
        "status": status,
        "schema": 1,
        "reason": reason,
        "players": players if players is not None else {},
    }
    # JSON_RESULT must be on a single line so _subprocess_run_with_retry callers can parse it.
    print(f"JSON_RESULT={json.dumps(envelope, separators=(',', ':'))}")


def _env_value(key: str) -> str | None:
    """Read from os.environ first, then ~/.hermes/.env (mirrors runner's env_value)."""
    value = os.environ.get(key)
    if value:
        return value.strip().strip('"').strip("'")
    hermes_env = Path.home() / ".hermes" / ".env"
    if not hermes_env.exists():
        return None
    for line in hermes_env.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        k, v = stripped.split("=", 1)
        if k.strip() == key:
            return v.strip().strip('"').strip("'") or None
    return None


def scrape_and_parse(sport: str, game_id: str) -> None:
    """Main scrape + parse entry point. Emits JSON_RESULT and exits."""
    if sport not in {"mlb", "nba"}:
        _emit_result("skip", f"Unknown sport: {sport!r}; expected 'mlb' or 'nba'")
        sys.exit(0)

    url = ESPN_BOX_URL_TEMPLATE.format(sport=sport, game_id=game_id)

    # Build the exact firecrawl command — no deviations from this template.
    cmd = [
        "npx", "-y", FIRECRAWL_CLI,
        "firecrawl", "scrape",
        url,
        "--format", "markdown",
    ]
    # FORBIDDEN: --browser, --format json, init, @latest
    # These are explicitly excluded from the command construction above.

    # Build child environment: inherit everything (npx needs PATH/HOME/NODE_PATH)
    child_env = os.environ.copy()
    api_key = _env_value("FIRECRAWL_API_KEY")
    if api_key:
        child_env["FIRECRAWL_API_KEY"] = api_key
    # If no key, run keyless — this is intentional and correct per the spec.

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=_SCRAPE_TIMEOUT_S,
            env=child_env,
        )
    except subprocess.TimeoutExpired:
        _emit_result("skip", f"npx firecrawl scrape timed out after {_SCRAPE_TIMEOUT_S}s")
        sys.exit(0)
    except FileNotFoundError:
        _emit_result("skip", "npx not found on PATH; Node.js/npx required for firecrawl scrape")
        sys.exit(0)
    except Exception as exc:
        _emit_result("skip", f"subprocess error: {exc}")
        sys.exit(0)

    if proc.returncode != 0:
        stderr_excerpt = (proc.stderr or "")[:300]
        stdout_excerpt = (proc.stdout or "")[:200]
        # 429 rate-limit detection
        if "429" in stderr_excerpt or "rate limit" in stderr_excerpt.lower() or "429" in stdout_excerpt:
            _emit_result("skip", f"firecrawl rate-limited (429)")
        else:
            _emit_result("skip", f"npx exited {proc.returncode}: {stderr_excerpt or stdout_excerpt}")
        sys.exit(0)

    # Parse the markdown output from stdout
    md_text = proc.stdout or ""
    if not md_text.strip():
        _emit_result("skip", "firecrawl returned empty output")
        sys.exit(0)

    players = parse_espn_box_markdown(md_text)
    _emit_result("ok", "", players)
    sys.exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Scrape an ESPN box score via firecrawl-cli and emit a normalized stat dict."
    )
    parser.add_argument("--sport", required=True, choices=["mlb", "nba"],
                        help="Sport: mlb or nba")
    parser.add_argument("--game-id", required=True,
                        help="ESPN numeric game ID")
    parser.add_argument("--date", default=None,
                        help="Date YYYY-MM-DD (informational only; not used in scrape URL)")
    args = parser.parse_args()
    scrape_and_parse(sport=args.sport, game_id=args.game_id)


if __name__ == "__main__":
    main()
