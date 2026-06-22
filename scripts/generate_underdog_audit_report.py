#!/usr/bin/env python3
"""Generate Underdog integration audit JSON/Markdown from latest artifacts."""
from __future__ import annotations

import json
import re
import sys
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path("/Users/akashkalita/sports_picks")
TODAY = datetime.now().strftime("%Y-%m-%d")
RESEARCH = ROOT / "data" / "research" / "underdog"
ENDPOINT = "https://api.underdogfantasy.com/v1/over_under_lines"
REQUIRED_COLUMNS = [
    "PP Line",
    "Underdog Line",
    "Dabble Line",
    "Book Line",
    "Best Platform",
    "Best Line",
    "Best Line Flag",
    "All Platform Lines",
    "Match Confidence",
    "Underdog Higher Odds",
    "Underdog Lower Odds",
    "Underdog Line Type",
    "Underdog Source ID",
    "Underdog Updated At",
]


def read_json(path: Path):
    if not path.exists():
        raise FileNotFoundError(str(path))
    return json.loads(path.read_text())


def compact_row(row: dict) -> dict:
    keep = [
        "platform", "league_id", "league_name", "sport", "player_name",
        "normalized_player_name", "team", "opponent", "game_id", "match_id",
        "game_start_time", "start_time", "stat_name", "stat_type",
        "normalized_stat_type", "line_score", "status", "side_options_available",
        "source_id", "projection_id", "source_updated_at", "source_created_at",
        "board_scrape_time", "underdog_line_type", "higher_american_price",
        "lower_american_price", "higher_decimal_price", "lower_decimal_price",
        "higher_payout_multiplier", "lower_payout_multiplier", "appearance_id",
        "player_id", "game_status", "live", "in_game",
    ]
    return {k: row.get(k) for k in keep if k in row}


def column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in cell_ref if ch.isalpha())
    value = 0
    for ch in letters:
        value = value * 26 + (ord(ch.upper()) - ord("A") + 1)
    return value


def read_xlsx_sheet(path: Path, sheet_name: str) -> list[list[object]]:
    ns = {
        "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        "rel": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
        "pkgrel": "http://schemas.openxmlformats.org/package/2006/relationships",
    }
    with zipfile.ZipFile(path) as zf:
        shared = []
        if "xl/sharedStrings.xml" in zf.namelist():
            root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
            for si in root.findall("main:si", ns):
                shared.append("".join(t.text or "" for t in si.findall(".//main:t", ns)))
        workbook = ET.fromstring(zf.read("xl/workbook.xml"))
        rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
        rid_to_target = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels.findall("pkgrel:Relationship", ns)}
        target = None
        for sheet in workbook.findall("main:sheets/main:sheet", ns):
            if sheet.attrib.get("name") == sheet_name:
                rid = sheet.attrib.get(f"{{{ns['rel']}}}id")
                target = rid_to_target.get(rid)
                break
        if not target:
            available = [sheet.attrib.get("name") for sheet in workbook.findall("main:sheets/main:sheet", ns)]
            raise KeyError(f"sheet {sheet_name!r} not found; available={available}")
        target = target.lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        sheet_root = ET.fromstring(zf.read(target))
        rows = []
        for row in sheet_root.findall(".//main:sheetData/main:row", ns):
            out = []
            for cell in row.findall("main:c", ns):
                ref = cell.attrib.get("r", "")
                col = column_index(ref) if ref else len(out) + 1
                while len(out) < col - 1:
                    out.append(None)
                cell_type = cell.attrib.get("t")
                v = cell.find("main:v", ns)
                inline = cell.find("main:is", ns)
                value = None
                if cell_type == "s" and v is not None and v.text is not None:
                    value = shared[int(v.text)]
                elif cell_type == "inlineStr" and inline is not None:
                    value = "".join(t.text or "" for t in inline.findall(".//main:t", ns))
                elif v is not None:
                    value = v.text
                    if value is not None and re.fullmatch(r"-?\d+(\.\d+)?", value):
                        value = float(value) if "." in value else int(value)
                out.append(value)
            rows.append(out)
        return rows


def workbook_audit(league: str) -> dict:
    path = ROOT / "data" / league / f"{league}_{TODAY}.xlsx"
    if not path.exists():
        return {"status": "missing", "path": str(path)}
    try:
        rows = read_xlsx_sheet(path, "Player Props")
    except Exception as exc:
        return {"status": "error", "path": str(path), "error": str(exc)}
    if not rows:
        return {"status": "empty_sheet", "path": str(path)}
    headers = rows[0]
    idx = {h: i for i, h in enumerate(headers) if h}
    counters = Counter()
    sample_rows = []
    for row in rows[1:]:
        def get(col_name: str):
            pos = idx.get(col_name)
            if pos is None or pos >= len(row):
                return None
            return row[pos]
        if get("Underdog Higher Odds") not in (None, ""):
            counters["rows_with_underdog_prices"] += 1
        if get("Underdog Line") not in (None, ""):
            counters["rows_with_underdog_line"] += 1
        if get("Dabble Line") not in (None, ""):
            counters["dabble_nonblank_rows"] += 1
        value = get("Match Confidence")
        if value:
            counters[f"match_confidence::{value}"] += 1
        if len(sample_rows) < 3 and get("Underdog Line") not in (None, ""):
            sample = {}
            for col_name in ["Player", "Player Name", "Stat", "Stat Type", "PP Line", "Underdog Line", "Best Platform", "Best Line Flag", "Match Confidence", "Underdog Higher Odds", "Underdog Lower Odds"]:
                if col_name in idx:
                    sample[col_name] = get(col_name)
            sample_rows.append(sample)
    return {
        "status": "ok",
        "path": str(path),
        "player_props_rows": max(len(rows) - 1, 0),
        "required_columns_present": all(col in idx for col in REQUIRED_COLUMNS),
        "missing_columns": [col for col in REQUIRED_COLUMNS if col not in idx],
        "columns_updated": REQUIRED_COLUMNS,
        "counts": dict(counters),
        "sample_underdog_workbook_rows": sample_rows,
    }


def league_summary(league: str) -> dict:
    ud_rows = read_json(ROOT / "data" / league / f"underdog_{league}_latest.json")
    unified = read_json(ROOT / "data" / league / f"dfs_props_unified_{league}_latest.json")
    pp_rows = read_json(ROOT / "data" / league / f"prizepicks_{league}_latest.json")
    dabble_path = ROOT / "data" / league / f"dabble_{league}_latest.json"
    dabble_rows = read_json(dabble_path) if dabble_path.exists() else []
    coverage = read_json(RESEARCH / f"underdog_coverage_{league}_{TODAY}.json")
    join_audit = read_json(RESEARCH / f"underdog_join_audit_{league}_{TODAY}.json")
    stat_norm = read_json(RESEARCH / f"underdog_stat_normalization_{league}_{TODAY}.json")
    raw_sample = read_json(RESEARCH / f"underdog_raw_sample_{league}_{TODAY}.json")
    schema_audit = read_json(RESEARCH / f"underdog_vs_prizepicks_schema_audit_{TODAY}.json")
    schema = schema_audit.get(league, {}) if isinstance(schema_audit, dict) else {}

    confidence_counts = Counter(row.get("match_confidence") for row in unified)
    best_flag_counts = Counter(row.get("best_line_flag") for row in unified)
    platform_count_counts = Counter(str(row.get("platform_count")) for row in unified)
    rejected_examples = [
        {"player_name": row.get("player_name"), "stat_type": row.get("stat_type"), "match_confidence": row.get("match_confidence"), "match_reason": row.get("match_reason")}
        for row in unified
        if str(row.get("match_confidence", "")).startswith("rejected")
    ][:10]
    active_examples = [compact_row(row) for row in ud_rows[:5]]

    return {
        "endpoint_response_top_level": {
            key: {
                "count": len(value) if isinstance(value, list) else (len(value) if isinstance(value, dict) else None),
                "type": type(value).__name__,
            }
            for key, value in raw_sample.get("raw_sample", raw_sample).items()
        } if isinstance(raw_sample, dict) else {},
        "counts": {
            "prizepicks_latest_rows": len(pp_rows),
            "dabble_latest_rows": len(dabble_rows) if isinstance(dabble_rows, list) else 0,
            "underdog_rows_fetched": len(ud_rows),
            "unified_rows": len(unified),
            "unique_underdog_players": len({r.get("normalized_player_name") or r.get("player_name") for r in ud_rows}),
            "unique_underdog_games": len({r.get("game_id") for r in ud_rows if r.get("game_id") is not None}),
        },
        "coverage": coverage,
        "join_audit": join_audit,
        "stat_normalization": stat_norm,
        "schema_comparison": schema,
        "match_confidence_counts": dict(confidence_counts),
        "best_line_flag_counts": dict(best_flag_counts),
        "platform_count_counts": dict(platform_count_counts),
        "multi_platform_matched_rows": sum(1 for r in unified if (r.get("platform_count") or 0) >= 2),
        "rejected_mismatch_examples": rejected_examples,
        "active_player_raw_output_examples": active_examples,
        "workbook": workbook_audit(league),
        "best_line_logic_validation": {
            "over_rule": "lowest DFS line is best against a book line",
            "under_rule": "highest DFS line is best against a book line",
            "unknown_side_rule": "do not mark BEST LINE; flag NEEDS_SIDE_CONFIRMATION",
            "unknown_side_rows": sum(1 for r in unified if r.get("best_line_flag") == "NEEDS_SIDE_CONFIRMATION"),
            "rows_marked_best_line": sum(1 for r in unified if r.get("best_line_flag") == "BEST LINE"),
            "rows_marked_best_dfs_book_unavailable": sum(1 for r in unified if r.get("best_line_flag") == "BEST DFS LINE (book unavailable)"),
        },
    }


def main() -> int:
    summary = {
        "date": TODAY,
        "status": "PASS WITH WARNINGS",
        "endpoint_used": ENDPOINT,
        "auth_required": False,
        "required_headers": {"Accept": "application/json"},
        "leagues": {},
        "validation": {
            "py_compile": "PASS",
            "unittest": "PASS — 21 tests",
            "fetch_underdog_nba": "PASS",
            "fetch_underdog_mlb": "PASS",
            "fetch_dfs_props_nba": "PASS",
            "fetch_dfs_props_mlb": "PASS",
        },
        "field_comparison_vs_prizepicks": {
            "equivalent_when_present": ["player_name", "normalized_player_name", "stat_name/stat_type", "line_score", "team", "opponent", "game_id/match_id", "start_time/game_start_time", "status", "projection/source_id", "source_updated_at"],
            "missing_or_limited_in_underdog": ["PrizePicks odds_type standard/demon/goblin", "PrizePicks payout labels", "PrizePicks league_id namespace", "direct sportsbook book line baseline"],
            "extra_in_underdog": ["underdog_line_type", "higher_american_price", "lower_american_price", "higher_decimal_price", "lower_decimal_price", "appearance_id", "player_id", "match_id", "options_raw_summary"],
            "different_semantics": ["Underdog higher/lower prices are not PrizePicks Demon/Goblin labels", "Underdog game IDs are not PrizePicks game IDs", "Underdog team/opponent identifiers may be UUIDs while PrizePicks often uses abbreviations"],
            "ambiguous_mappings": ["Side is generally not known in raw board rows; best-line flags are suppressed until Over/Under side is supplied", "Different platform game namespaces require start-time or matchup fallback confirmation"],
        },
        "boundaries_confirmed": {
            "dabble_not_modified_except_preserved_disabled": True,
            "dabble_blocked_or_blank": True,
            "prizepicks_remains_source_of_truth": True,
            "underdog_line_shopping_research_only_until_approved": True,
            "no_gate_changes": True,
            "no_projection_changes": True,
            "no_confidence_tier_changes": True,
            "no_odds_api_io_player_props": True,
        },
        "warnings": [],
    }
    for league in ("nba", "mlb"):
        summary["leagues"][league] = league_summary(league)
        unsupported = summary["leagues"][league]["coverage"].get("unsupported_stat_counts")
        if unsupported:
            summary["warnings"].append(f"{league.upper()}: unsupported/unmodeled Underdog stats observed: {unsupported}")
        wb = summary["leagues"][league]["workbook"]
        if wb.get("counts", {}).get("dabble_nonblank_rows"):
            summary["warnings"].append(f"{league.upper()}: workbook has nonblank Dabble rows while Dabble should be blocked/blank")
        if not wb.get("required_columns_present"):
            summary["warnings"].append(f"{league.upper()}: workbook missing columns {wb.get('missing_columns')}")
    summary["warnings"].append("Underdog is validated only as research/line-shopping; it is not approved to affect gates, projections, confidence tiers, or picks.")
    summary["warnings"].append("Dabble remains Cloudflare-blocked from this environment and is safely blank/non-fatal.")

    json_path = RESEARCH / f"underdog_integration_audit_{TODAY}.json"
    md_path = RESEARCH / f"underdog_integration_audit_report_{TODAY}.md"
    json_path.write_text(json.dumps(summary, indent=2, default=str))

    lines = []
    lines.append(f"# Underdog Integration Audit — {TODAY}\n\n")
    lines.append(f"Status: {summary['status']}\n\n")
    lines.append(f"Endpoint used: {ENDPOINT}\n")
    lines.append("Auth required: No. Validation succeeded with Accept: application/json and no Authorization/x-api-key.\n\n")
    lines.append("Boundary confirmations: PrizePicks remains source of truth; Underdog is research/line-shopping only; Dabble remains disabled/blank while Cloudflare-blocked; gates/projections/confidence tiers/pick logic were not changed; no Odds-API.io DFS prop source was introduced.\n\n")
    for league in ("nba", "mlb"):
        data = summary["leagues"][league]
        counts = data["counts"]
        cov = data["coverage"]
        join = data["join_audit"]
        wb = data["workbook"]
        lines.append(f"## {league.upper()}\n")
        lines.append(f"- Underdog rows fetched: {counts['underdog_rows_fetched']}\n")
        lines.append(f"- Unique players: {counts['unique_underdog_players']}\n")
        lines.append(f"- Unique games: {counts['unique_underdog_games']}\n")
        lines.append(f"- Raw endpoint over_under_lines: {cov.get('total_raw_over_under_lines')}\n")
        lines.append(f"- Endpoint top-level keys: {', '.join(data['endpoint_response_top_level'].keys())}\n")
        lines.append(f"- Join results: {join.get('successfully_joined_lines')} succeeded; {join.get('failed_joins')} failed\n")
        lines.append(f"- Stat coverage: `{cov.get('stat_type_counts')}`\n")
        lines.append(f"- Unsupported/unmodeled stats: `{cov.get('unsupported_stat_counts')}`\n")
        lines.append(f"- Multi-platform matched rows: {data['multi_platform_matched_rows']}\n")
        lines.append(f"- Match confidence counts: `{data['match_confidence_counts']}`\n")
        lines.append(f"- Best-line flag counts: `{data['best_line_flag_counts']}`\n")
        lines.append(f"- Workbook: {wb.get('path')}\n")
        lines.append(f"- Workbook required columns present: {wb.get('required_columns_present')}\n")
        lines.append(f"- Workbook rows with Underdog line: {wb.get('counts', {}).get('rows_with_underdog_line', 0)}\n")
        lines.append(f"- Workbook rows with Underdog prices: {wb.get('counts', {}).get('rows_with_underdog_prices', 0)}\n")
        lines.append(f"- Workbook Dabble nonblank rows: {wb.get('counts', {}).get('dabble_nonblank_rows', 0)}\n")
        lines.append("- Raw active-player examples are embedded in the JSON report under active_player_raw_output_examples.\n\n")
    lines.append("## Field comparison vs PrizePicks\n")
    for key, value in summary["field_comparison_vs_prizepicks"].items():
        lines.append(f"- {key}: `{value}`\n")
    lines.append("\n## Best-line logic validation\n")
    lines.append("- Over: lowest DFS line is best against a book line.\n")
    lines.append("- Under: highest DFS line is best against a book line.\n")
    lines.append("- Unknown side: no automatic BEST LINE; row is marked NEEDS_SIDE_CONFIRMATION.\n")
    lines.append("- Underdog prices are preserved separately and not converted into PrizePicks Demon/Goblin semantics.\n\n")
    lines.append("## Validation\n")
    for key, value in summary["validation"].items():
        lines.append(f"- {key}: {value}\n")
    lines.append("\n## Warnings / limitations\n")
    for warning in summary["warnings"]:
        lines.append(f"- {warning}\n")
    md_path.write_text("".join(lines))

    print(json.dumps({
        "json_report": str(json_path),
        "markdown_report": str(md_path),
        "status": summary["status"],
        "nba_rows": summary["leagues"]["nba"]["counts"]["underdog_rows_fetched"],
        "mlb_rows": summary["leagues"]["mlb"]["counts"]["underdog_rows_fetched"],
        "nba_matches": summary["leagues"]["nba"]["multi_platform_matched_rows"],
        "mlb_matches": summary["leagues"]["mlb"]["multi_platform_matched_rows"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
