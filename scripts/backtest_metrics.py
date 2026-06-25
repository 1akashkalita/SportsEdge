#!/usr/bin/env python3
"""Backtest scoring & aggregation (M2 Phase 1, Component A).

Pure functions over the prediction records produced by
backtest_projections.predict_at. No disk I/O, no model — this layer only
scores. Two calibration lenses:

  * PIT (line-independent): PIT uniform on [0,1] iff sigma is right. Mass in the
    outer deciles above the calibrated 2/n_bins == overconfident spread.
  * Binary reliability (line-dependent, via the synthetic line): when the model
    says probability p, does the over actually land p of the time? Brier /
    log-loss / ECE / the reliability curve all measure this. Sliced by
    confidence tier and predicted-probability band, this is where the betting
    overconfidence localises.

The binary metrics depend on the synthetic line (rolling median of priors), so
they approximate "pick'em" lines; PIT and point-accuracy are line-free.
"""
from __future__ import annotations

import math
import statistics
from typing import Any, Callable

# Add a tiny epsilon before truncating so values that land exactly on a bin edge
# (e.g. 0.3*10 == 2.9999999999999996 in IEEE float) fall into the intended bin.
_BIN_EPS = 1e-9


def _bin_index(x: float, n_bins: int) -> int:
    """Index of the [k/n, (k+1)/n) bin containing x, clamped to [0, n_bins-1]."""
    idx = int(x * n_bins + _BIN_EPS)
    return min(n_bins - 1, max(0, idx))


def _decided(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Records with a settled over/under outcome (pushes have over_outcome None)."""
    return [r for r in records if r.get("over_outcome") is not None]


# ---------------------------------------------------------------------------
# Binary calibration (over_probability vs over_outcome)
# ---------------------------------------------------------------------------

def brier_score(records: list[dict[str, Any]]) -> float:
    """Mean squared error of predicted P(over) vs the 0/1 over outcome (pushes skipped)."""
    decided = _decided(records)
    if not decided:
        return float("nan")
    return statistics.fmean(
        (float(r["over_probability"]) - float(r["over_outcome"])) ** 2 for r in decided
    )


def log_loss(records: list[dict[str, Any]], eps: float = 1e-15) -> float:
    """Mean binary cross-entropy (pushes skipped); predicted prob clamped to [eps, 1-eps]."""
    decided = _decided(records)
    if not decided:
        return float("nan")
    total = 0.0
    for r in decided:
        p = min(1.0 - eps, max(eps, float(r["over_probability"])))
        y = float(r["over_outcome"])
        total += -(y * math.log(p) + (1.0 - y) * math.log(1.0 - p))
    return total / len(decided)


def reliability_curve(records: list[dict[str, Any]], n_bins: int = 10) -> list[dict[str, Any]]:
    """Per-bin reliability data: mean predicted prob vs observed over-rate.

    Returns one entry per bin (including empties, count 0) so the curve has a
    stable shape. `gap` = |mean_pred - mean_obs| is the per-bin miscalibration.
    """
    preds: list[list[float]] = [[] for _ in range(n_bins)]
    obs: list[list[float]] = [[] for _ in range(n_bins)]
    for r in _decided(records):
        p = float(r["over_probability"])
        b = _bin_index(p, n_bins)
        preds[b].append(p)
        obs[b].append(float(r["over_outcome"]))
    curve = []
    for i in range(n_bins):
        count = len(preds[i])
        mean_pred = statistics.fmean(preds[i]) if count else None
        mean_obs = statistics.fmean(obs[i]) if count else None
        gap = abs(mean_pred - mean_obs) if count else None
        curve.append({
            "bin_lo": round(i / n_bins, 4),
            "bin_hi": round((i + 1) / n_bins, 4),
            "count": count,
            "mean_pred": mean_pred,
            "mean_obs": mean_obs,
            "gap": gap,
        })
    return curve


def expected_calibration_error(records: list[dict[str, Any]], n_bins: int = 10) -> float:
    """Count-weighted average per-bin gap between predicted prob and observed rate."""
    total = len(_decided(records))
    if not total:
        return float("nan")
    ece = 0.0
    for b in reliability_curve(records, n_bins):
        if b["count"]:
            ece += (b["count"] / total) * b["gap"]
    return ece


# ---------------------------------------------------------------------------
# PIT (line-independent distributional calibration)
# ---------------------------------------------------------------------------

def pit_histogram(records: list[dict[str, Any]], n_bins: int = 10) -> list[dict[str, Any]]:
    """Histogram of PIT values; uniform (frac == 1/n_bins) iff sigma is right."""
    counts = [0] * n_bins
    n = 0
    for r in records:
        pit = r.get("pit")
        if pit is None:
            continue
        counts[_bin_index(float(pit), n_bins)] += 1
        n += 1
    return [
        {"bin_lo": round(i / n_bins, 4), "bin_hi": round((i + 1) / n_bins, 4),
         "count": counts[i], "frac": (counts[i] / n) if n else 0.0}
        for i in range(n_bins)
    ]


def pit_tail_mass(records: list[dict[str, Any]], n_bins: int = 10) -> float:
    """Fraction of PIT mass in the outer two bins; calibrated == 2/n_bins."""
    hist = pit_histogram(records, n_bins)
    total = sum(b["count"] for b in hist)
    if not total:
        return float("nan")
    return (hist[0]["count"] + hist[-1]["count"]) / total


# ---------------------------------------------------------------------------
# Point accuracy (projection vs actual; error == projection - actual)
# ---------------------------------------------------------------------------

def point_accuracy(records: list[dict[str, Any]]) -> dict[str, Any]:
    """MAE, signed bias, and RMSE of the point projection."""
    errs = [float(r["error"]) for r in records if r.get("error") is not None]
    if not errs:
        return {"n": 0, "mae": float("nan"), "bias": float("nan"), "rmse": float("nan")}
    return {
        "n": len(errs),
        "mae": statistics.fmean(abs(e) for e in errs),
        "bias": statistics.fmean(errs),
        "rmse": math.sqrt(statistics.fmean(e * e for e in errs)),
    }


# ---------------------------------------------------------------------------
# Bucketing for slices
# ---------------------------------------------------------------------------

def sample_size_bucket(n: int) -> str:
    """Coarse sample-size band aligned to Gate 6 (sample < 8 is small-sample)."""
    n = int(n or 0)
    if n < 8:
        return "<8"
    if n <= 15:
        return "8-15"
    if n <= 30:
        return "16-30"
    return "31+"


def prob_bucket(p: float, n_bins: int = 10) -> str:
    """Decile label of a predicted probability, e.g. 0.85 -> '0.8-0.9'."""
    i = _bin_index(float(p), n_bins)
    return f"{i / n_bins:.1f}-{(i + 1) / n_bins:.1f}"


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def summarize(records: list[dict[str, Any]], n_bins: int = 10) -> dict[str, Any]:
    """Full metric bundle for one set of records. Empty -> {'n': 0}.

    Binary metrics (brier/log-loss/ece/over_rate/mean_pred_prob) are computed over
    DECIDED records only — pushes are voided, as a sportsbook does. PIT and point
    accuracy use every record (they don't depend on the over/under settling)."""
    if not records:
        return {"n": 0}
    decided = _decided(records)
    acc = point_accuracy(records)
    return {
        "n": len(records),
        "n_decided": len(decided),
        "push_rate": (len(records) - len(decided)) / len(records),
        "brier": brier_score(records),
        "log_loss": log_loss(records),
        "ece": expected_calibration_error(records, n_bins),
        "mae": acc["mae"],
        "bias": acc["bias"],
        "rmse": acc["rmse"],
        "over_rate": (statistics.fmean(float(r["over_outcome"]) for r in decided)
                      if decided else float("nan")),
        "mean_pred_prob": (statistics.fmean(float(r["over_probability"]) for r in decided)
                           if decided else float("nan")),
        "pit_tail_mass": pit_tail_mass(records, n_bins),
        "reliability_curve": reliability_curve(records, n_bins),
        "pit_histogram": pit_histogram(records, n_bins),
    }


# Slice dimensions: label -> key function over a record. The buckets are where
# the betting overconfidence is expected to surface (confidence tier + predicted
# probability band).
DEFAULT_SLICE_KEYS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "sport": lambda r: r.get("sport"),
    "stat": lambda r: r.get("stat"),
    "confidence_tier": lambda r: r.get("confidence_tier"),
    "sample_size_bucket": lambda r: sample_size_bucket(r.get("sample_size", 0)),
    "prob_bucket": lambda r: prob_bucket(r.get("over_probability", 0.5)),
}


def slice_summaries(records: list[dict[str, Any]],
                    key: Callable[[dict[str, Any]], Any],
                    n_bins: int = 10) -> dict[str, Any]:
    """Group records by key(record) and summarize each group (skips None keys)."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in records:
        k = key(r)
        if k is None:
            continue
        groups.setdefault(str(k), []).append(r)
    return {k: summarize(v, n_bins) for k, v in groups.items()}


def build_report(records: list[dict[str, Any]],
                 slice_keys: dict[str, Callable[[dict[str, Any]], Any]] | None = None,
                 n_bins: int = 10) -> dict[str, Any]:
    """Overall summary plus per-dimension sliced summaries."""
    slice_keys = slice_keys if slice_keys is not None else DEFAULT_SLICE_KEYS
    return {
        "overall": summarize(records, n_bins),
        "slices": {name: slice_summaries(records, key, n_bins)
                   for name, key in slice_keys.items()},
    }
