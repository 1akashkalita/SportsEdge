#!/usr/bin/env python3
"""Backtest baseline report runner (M2 Phase 1, Component A).

Drives the production model through the walk-forward harness over every stored
gamelog, scores the predictions with backtest_metrics, and writes a baseline:
a machine-readable JSON and an operator-readable Markdown summary.

Read-only over data/research/hit_rates; writes ONLY under data/research/backtest
(never a live workbook, never the cron path).

    cd scripts
    python3 backtest_report.py --sport mlb
    python3 backtest_report.py --sport nba --limit 50      # quick sample
    python3 backtest_report.py --sport mlb --hit-rate-dir /path/to/hit_rates
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import backtest_metrics as bm
import backtest_projections as bt

ROOT = Path(__file__).resolve().parents[1]
HIT_RATE_DIR = ROOT / "data" / "research" / "hit_rates"
OUT_DIR = ROOT / "data" / "research" / "backtest"


# ---------------------------------------------------------------------------
# Collection (glue: disk gamelogs -> production model -> flat records)
# ---------------------------------------------------------------------------

def collect_records_for_sport(sport: str, hit_rate_dir: Path = HIT_RATE_DIR,
                              limit: int | None = None,
                              min_prior: int = 5) -> list[dict[str, Any]]:
    """Walk every gamelog for `sport` and return all walk-forward predictions.

    For each player file, every stat is walked forward independently. `limit`
    caps the number of player files scanned (for quick samples), not records.
    """
    sport_dir = Path(hit_rate_dir) / sport
    if not sport_dir.is_dir():
        return []
    files = sorted(sport_dir.glob("*.json"))
    if limit is not None:
        files = files[:limit]
    records: list[dict[str, Any]] = []
    for f in files:
        try:
            doc = json.loads(f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        for stat_name in (doc.get("stats") or {}):
            records.extend(
                bt.walk_forward_player_stat(doc, stat_name, sport, min_prior=min_prior)
            )
    return records


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _fmt(x: Any, places: int = 4) -> str:
    if x is None:
        return "—"
    if isinstance(x, float) and math.isnan(x):
        return "—"
    if isinstance(x, float):
        return f"{x:.{places}f}"
    return str(x)


def _pct(x: Any) -> str:
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    return f"{x * 100:.1f}%"


def _scalar_block(s: dict[str, Any]) -> list[str]:
    return [
        f"- Predictions: **{s['n']}**  (decided {s.get('n_decided')}, "
        f"pushes {_pct(s.get('push_rate'))} — voided)",
        f"- Over rate (decided): {_fmt(s.get('over_rate'))}  |  "
        f"Mean predicted P(over): {_fmt(s.get('mean_pred_prob'))}",
        f"- Brier: {_fmt(s.get('brier'))}  |  Log-loss: {_fmt(s.get('log_loss'))}  |  "
        f"ECE: {_fmt(s.get('ece'))}",
        f"- PIT tail mass: {_fmt(s.get('pit_tail_mass'))} "
        f"(calibrated ≈ 0.2000)",
        f"- MAE: {_fmt(s.get('mae'))}  |  Bias (proj−actual): {_fmt(s.get('bias'))}  |  "
        f"RMSE: {_fmt(s.get('rmse'))}",
    ]


def _reliability_table(curve: list[dict[str, Any]]) -> list[str]:
    rows = ["| prob bin | n | mean pred | observed | gap |",
            "|---|---:|---:|---:|---:|"]
    for b in curve:
        if not b["count"]:
            continue
        rows.append(f"| {b['bin_lo']:.1f}–{b['bin_hi']:.1f} | {b['count']} | "
                    f"{_fmt(b['mean_pred'])} | {_fmt(b['mean_obs'])} | {_fmt(b['gap'])} |")
    return rows


def _slice_table(slice_map: dict[str, dict[str, Any]], label: str,
                 order: list[str] | None = None,
                 max_rows: int | None = None) -> list[str]:
    keys = order if order is not None else sorted(
        slice_map, key=lambda k: -slice_map[k].get("n", 0))
    keys = [k for k in keys if k in slice_map]
    if max_rows is not None:
        keys = keys[:max_rows]
    rows = [f"#### By {label}", "",
            "| group | n | push | over rate | mean pred | brier | ECE | PIT tail | bias |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for k in keys:
        s = slice_map[k]
        rows.append(f"| {k} | {s.get('n')} | {_pct(s.get('push_rate'))} | "
                    f"{_fmt(s.get('over_rate'))} | "
                    f"{_fmt(s.get('mean_pred_prob'))} | {_fmt(s.get('brier'))} | "
                    f"{_fmt(s.get('ece'))} | {_fmt(s.get('pit_tail_mass'))} | "
                    f"{_fmt(s.get('bias'))} |")
    rows.append("")
    return rows


def render_markdown(report: dict[str, Any], sport: str, run_date: str) -> str:
    """Operator-readable baseline. The predicted-prob and confidence-tier slices
    are the betting-overconfidence diagnosis (mean pred ≫ observed == overconfident)."""
    overall = report.get("overall", {})
    lines = [f"# Backtest Calibration Baseline — {sport.upper()} ({run_date})", ""]
    if not overall.get("n"):
        lines.append("No predictions generated (no gamelogs met the min-prior threshold).")
        return "\n".join(lines) + "\n"

    lines += [
        "> **Method.** Walk-forward over stored gamelogs through the production "
        "`build_projection`. The line is synthetic (rolling median of priors); ties "
        "against it are **voided as pushes** (sportsbook semantics), so binary metrics "
        "use decided outcomes only. **PIT** and **point accuracy** are line-independent "
        "(trust these most); binary reliability is only as good as the synthetic line.",
        "",
    ]

    lines += ["## Overall", ""]
    lines += _scalar_block(overall)
    lines += ["", "### Reliability (predicted P(over) vs observed over-rate)", ""]
    lines += _reliability_table(overall.get("reliability_curve", []))
    lines += [""]

    slices = report.get("slices", {})
    # Predicted-prob bucket: the headline overconfidence view (sorted by band).
    if slices.get("prob_bucket"):
        lines += _slice_table(slices["prob_bucket"], "predicted-probability bucket",
                              order=sorted(slices["prob_bucket"]))
    if slices.get("confidence_tier"):
        lines += _slice_table(slices["confidence_tier"], "confidence tier")
    if slices.get("sample_size_bucket"):
        lines += _slice_table(slices["sample_size_bucket"], "sample-size bucket",
                              order=["<8", "8-15", "16-30", "31+"])
    if slices.get("stat"):
        lines += _slice_table(slices["stat"], "stat (top 15 by n)", max_rows=15)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

def write_report(report: dict[str, Any], sport: str, run_date: str,
                 out_dir: Path = OUT_DIR) -> dict[str, Path]:
    """Write JSON + Markdown (dated file + `_latest` pointer). Returns the paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md = render_markdown(report, sport, run_date)
    paths: dict[str, Path] = {}
    for label, name, payload in (
        ("json", f"baseline_{sport}_{run_date}.json", json.dumps(report, indent=2)),
        ("json_latest", f"baseline_{sport}_latest.json", json.dumps(report, indent=2)),
        ("md", f"baseline_{sport}_{run_date}.md", md),
        ("md_latest", f"baseline_{sport}_latest.md", md),
    ):
        p = out_dir / name
        p.write_text(payload)
        paths[label] = p
    return paths


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Backtest calibration baseline report")
    ap.add_argument("--sport", required=True, choices=["nba", "mlb"])
    ap.add_argument("--hit-rate-dir", default=str(HIT_RATE_DIR))
    ap.add_argument("--out-dir", default=str(OUT_DIR))
    ap.add_argument("--limit", type=int, default=None, help="cap player files scanned")
    ap.add_argument("--min-prior", type=int, default=5)
    ap.add_argument("--date", default="latest", help="run-date stamp for filenames")
    args = ap.parse_args(argv)

    records = collect_records_for_sport(
        args.sport, hit_rate_dir=Path(args.hit_rate_dir),
        limit=args.limit, min_prior=args.min_prior)
    report = bm.build_report(records)
    paths = write_report(report, args.sport, args.date, out_dir=Path(args.out_dir))
    overall = report["overall"]
    print(json.dumps({
        "JSON_RESULT": True, "sport": args.sport, "records": overall.get("n", 0),
        "brier": overall.get("brier"), "ece": overall.get("ece"),
        "pit_tail_mass": overall.get("pit_tail_mass"),
        "report_md": str(paths["md"]), "report_json": str(paths["json"]),
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
