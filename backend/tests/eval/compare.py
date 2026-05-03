# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Baseline comparison + human-readable regression diff."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.eval.runner import EvalReport


@dataclass
class MetricDelta:
    """One metric's change vs baseline."""

    name: str
    baseline: float
    current: float
    delta: float  # current - baseline
    regressed: bool  # delta < -threshold


@dataclass
class ComparisonResult:
    """Outcome of comparing the current run to a baseline."""

    passed: bool
    threshold: float
    deltas: list[MetricDelta] = field(default_factory=list)
    new_metrics: list[str] = field(default_factory=list)  # in current, not baseline
    missing_metrics: list[str] = field(default_factory=list)  # in baseline, not current


def compare_to_baseline(
    report: EvalReport,
    baseline: dict[str, float],
    threshold: float = 0.05,
) -> ComparisonResult:
    """Compare a fresh report to a baseline metric dict.

    Args:
        report: The :class:`EvalReport` from a fresh run.
        baseline: Flat ``{metric_name: float}`` dict from ``baseline.json``.
        threshold: A metric is considered regressed when its current
            value is more than ``threshold`` lower than baseline. The
            comparison is *absolute*: ``current - baseline < -threshold``.

    Returns:
        :class:`ComparisonResult` with ``passed=True`` iff no metric
        regressed > ``threshold`` (and no metric is missing from the
        current report that was present in baseline).
    """

    # Underscore-prefixed keys (``_comment``, ``_updated``,
    # ``_match_service_version``) are metadata and never participate in
    # the regression check.
    baseline_metrics = {k: v for k, v in baseline.items() if not k.startswith("_")}

    current = report.metrics
    deltas: list[MetricDelta] = []
    regressed = False

    common = sorted(set(baseline_metrics) & set(current))
    for name in common:
        try:
            b = float(baseline_metrics[name])
            c = float(current[name])
        except (TypeError, ValueError):
            continue
        d = c - b
        is_regression = d < -threshold
        deltas.append(MetricDelta(name=name, baseline=b, current=c, delta=d, regressed=is_regression))
        if is_regression:
            regressed = True

    new_metrics = sorted(set(current) - set(baseline_metrics))
    missing_metrics = sorted(set(baseline_metrics) - set(current))
    if missing_metrics:
        regressed = True  # treat removed metrics as a regression

    return ComparisonResult(
        passed=not regressed,
        threshold=threshold,
        deltas=deltas,
        new_metrics=new_metrics,
        missing_metrics=missing_metrics,
    )


def format_comparison(result: ComparisonResult) -> str:
    """Render a comparison result for human eyes (CI logs, terminal)."""

    lines: list[str] = []
    lines.append("")
    lines.append("=" * 72)
    lines.append(f"Baseline comparison (threshold={result.threshold:+.2%})")
    lines.append("=" * 72)
    lines.append(f"{'Metric':36s} {'Baseline':>10s} {'Current':>10s} {'Delta':>10s}")
    lines.append("-" * 72)

    for d in result.deltas:
        marker = " !! REGRESSION" if d.regressed else ""
        lines.append(f"{d.name:36s} {d.baseline:10.4f} {d.current:10.4f} {d.delta:+10.4f}{marker}")

    if result.new_metrics:
        lines.append("")
        lines.append(f"New metrics (not in baseline): {', '.join(result.new_metrics)}")
    if result.missing_metrics:
        lines.append("")
        lines.append(f"Missing metrics (in baseline, absent from current): {', '.join(result.missing_metrics)}")

    lines.append("")
    lines.append("PASSED" if result.passed else "FAILED")
    lines.append("=" * 72)
    return "\n".join(lines)
