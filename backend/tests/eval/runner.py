# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Orchestrator for the element-to-CWICR vector match evaluation.

Loads :file:`golden_set.yaml`, calls the match service for each entry,
feeds candidates through the judge, aggregates metrics, and (optionally)
compares to a baseline.

Entry points
============

* :func:`run_eval` — async, programmatic.
* ``python -m tests.eval.runner`` — CLI wrapper.

The match service itself lives at ``app.core.match_service.match_element``
and is being built by a parallel subagent. We try to import it and fall
back to a deterministic stub if it's not yet available — this lets the
harness CI workflow run independently of the match-service ship date.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import logging
import os
import sys
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tests.eval.judge import (
    JudgeVerdict,
    get_run_cost,
    judge_match,
    reset_run_cost,
)

logger = logging.getLogger(__name__)


# ── Match service adapter ──────────────────────────────────────────────────


MatchFn = Callable[[dict[str, Any], int], Awaitable[list[dict[str, Any]]]]
"""``async (element_info, top_k) -> list[candidate_dict]``."""


async def _stub_match_element(
    element_info: dict[str, Any],
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """Deterministic stub used when the real match service isn't shipped yet.

    Returns ``top_k`` plausible-looking but obviously-fake candidates so
    the runner can exercise the full pipeline. Designed so the
    rule-based judge will always return ``incorrect`` — the metric
    output is therefore floor-zero, which is the right baseline before
    the real service ships.
    """

    return [
        {
            "code": f"STUB.99.{i:03d}",
            "description": f"Stub candidate #{i} for {element_info.get('category') or element_info.get('description', '')[:40]}",
            "unit": element_info.get("estimated_unit") or "pcs",
            "unit_rate": 0.0,
            "currency": "EUR",
            "score": max(0.0, 1.0 - (i * 0.18)),
        }
        for i in range(top_k)
    ]


def _resolve_match_fn() -> MatchFn:
    """Try to import the real match service; fall back to stub on ImportError."""

    try:
        # Real service — built by the parallel subagent at
        # ``backend/app/core/match_service/``. The expected signature is
        # ``async match_element(element_info, top_k) -> list[dict]``.
        from app.core.match_service import match_element as real_match_element  # type: ignore[import-not-found]
    except ImportError:
        logger.info("match_service not available — using deterministic stub")
        return _stub_match_element

    return real_match_element  # type: ignore[no-any-return]


# ── Result types ───────────────────────────────────────────────────────────


@dataclass
class CandidateOutcome:
    """One candidate's judge verdict, plus rank in the top-k list."""

    rank: int  # 1-indexed
    candidate: dict[str, Any]
    verdict: JudgeVerdict


@dataclass
class EntryResult:
    """One golden-entry's full evaluation."""

    id: str
    source: str
    candidates: list[CandidateOutcome]
    top_1_correct: bool
    top_5_recall: bool  # any of the top 5 was 'correct'
    reciprocal_rank: float  # 1/rank of first 'correct', else 0.0
    took_ms: int
    error: str | None = None


@dataclass
class EvalReport:
    """Aggregate metrics over the whole golden set."""

    metrics: dict[str, float]
    per_entry_results: list[EntryResult]
    total_cost_usd: float
    took_ms: int
    timestamp_iso: str
    golden_set_size: int
    used_real_match_service: bool

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly dump (used for baseline file + CI artefact)."""

        def _coerce(obj: Any) -> Any:
            if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
                return {k: _coerce(v) for k, v in dataclasses.asdict(obj).items()}
            if isinstance(obj, list):
                return [_coerce(x) for x in obj]
            if isinstance(obj, dict):
                return {k: _coerce(v) for k, v in obj.items()}
            return obj

        return _coerce(self)


# ── Per-entry evaluation ───────────────────────────────────────────────────


async def _evaluate_entry(
    entry: dict[str, Any],
    *,
    match_fn: MatchFn,
    top_k: int,
    use_judge_llm: bool,
) -> EntryResult:
    """Run one golden entry through match service + judge."""

    started = time.perf_counter()

    try:
        candidates = await match_fn(entry["element_info"], top_k)
    except Exception as exc:
        logger.exception("match_fn failed for entry %s", entry["id"])
        return EntryResult(
            id=entry["id"],
            source=entry["source"],
            candidates=[],
            top_1_correct=False,
            top_5_recall=False,
            reciprocal_rank=0.0,
            took_ms=int((time.perf_counter() - started) * 1000),
            error=f"match_fn: {exc!s}",
        )

    candidates = candidates[:top_k]
    outcomes: list[CandidateOutcome] = []
    for rank, candidate in enumerate(candidates, start=1):
        verdict = await judge_match(
            element_info=entry["element_info"],
            ground_truth=entry["ground_truth"],
            candidate=candidate,
            use_llm=use_judge_llm,
        )
        outcomes.append(CandidateOutcome(rank=rank, candidate=candidate, verdict=verdict))

    # Metrics for this entry
    correct_ranks = [o.rank for o in outcomes if o.verdict.verdict == "correct"]
    top_1 = len(outcomes) > 0 and outcomes[0].verdict.verdict == "correct"
    top_5 = bool(correct_ranks)
    rr = (1.0 / correct_ranks[0]) if correct_ranks else 0.0

    return EntryResult(
        id=entry["id"],
        source=entry["source"],
        candidates=outcomes,
        top_1_correct=top_1,
        top_5_recall=top_5,
        reciprocal_rank=rr,
        took_ms=int((time.perf_counter() - started) * 1000),
    )


# ── Aggregation ────────────────────────────────────────────────────────────


def _aggregate_metrics(per_entry: list[EntryResult]) -> dict[str, float]:
    """Compute top-1 / top-5 / MRR globally and per source."""

    if not per_entry:
        return {"top_1_accuracy": 0.0, "top_5_recall": 0.0, "mrr": 0.0}

    metrics: dict[str, float] = {}
    metrics["top_1_accuracy"] = sum(1 for r in per_entry if r.top_1_correct) / len(per_entry)
    metrics["top_5_recall"] = sum(1 for r in per_entry if r.top_5_recall) / len(per_entry)
    metrics["mrr"] = sum(r.reciprocal_rank for r in per_entry) / len(per_entry)

    # Per-source breakdown
    by_source: dict[str, list[EntryResult]] = defaultdict(list)
    for r in per_entry:
        by_source[r.source].append(r)
    for source, rows in by_source.items():
        metrics[f"top_1_accuracy.{source}"] = sum(1 for r in rows if r.top_1_correct) / len(rows)
        metrics[f"top_5_recall.{source}"] = sum(1 for r in rows if r.top_5_recall) / len(rows)
        metrics[f"mrr.{source}"] = sum(r.reciprocal_rank for r in rows) / len(rows)

    return metrics


# ── Public runner ──────────────────────────────────────────────────────────


async def run_eval(
    golden_set_path: Path,
    *,
    top_k: int = 5,
    judge: bool = True,
    match_fn: MatchFn | None = None,
) -> EvalReport:
    """Full evaluation pipeline.

    Args:
        golden_set_path: Path to the YAML golden set.
        top_k: Number of candidates to fetch per element.
        judge: If ``False``, judge always uses the rule-based fallback
            (cheap CI mode).
        match_fn: Inject a custom match function (used by tests). If
            ``None``, resolves the real match service or stub.
    """

    started = time.perf_counter()
    reset_run_cost()

    with golden_set_path.open("r", encoding="utf-8") as fh:
        golden = yaml.safe_load(fh)
    if not isinstance(golden, list):
        msg = f"Expected a list of entries in {golden_set_path}, got {type(golden).__name__}"
        raise ValueError(msg)

    if match_fn is not None:
        # Caller injected a custom match function (typically a test) —
        # we make no claim about whether the real service is wired up.
        resolved_match_fn = match_fn
        used_real = False
    else:
        resolved_match_fn = _resolve_match_fn()
        used_real = resolved_match_fn is not _stub_match_element

    per_entry: list[EntryResult] = []
    for entry in golden:
        result = await _evaluate_entry(
            entry,
            match_fn=resolved_match_fn,
            top_k=top_k,
            use_judge_llm=judge,
        )
        per_entry.append(result)

    metrics = _aggregate_metrics(per_entry)

    return EvalReport(
        metrics=metrics,
        per_entry_results=per_entry,
        total_cost_usd=get_run_cost(),
        took_ms=int((time.perf_counter() - started) * 1000),
        timestamp_iso=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        golden_set_size=len(per_entry),
        used_real_match_service=used_real,
    )


# ── CLI ────────────────────────────────────────────────────────────────────


def _cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m tests.eval.runner",
        description="Run the element-to-CWICR vector match evaluation.",
    )
    parser.add_argument(
        "--golden",
        type=Path,
        default=Path(__file__).parent / "golden_set.yaml",
        help="Path to the golden-set YAML (default: tests/eval/golden_set.yaml)",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=Path(__file__).parent / "baseline.json",
        help="Path to the baseline JSON for regression checking",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Write the full report JSON here (default: stdout-only)",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of candidates to fetch per element (default: 5)",
    )
    parser.add_argument(
        "--judge",
        type=lambda v: str(v).lower() not in ("false", "0", "no", "off"),
        default=True,
        help="Use LLM judge (default: true). Set to false in CI for cost-free runs.",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Overwrite the baseline file with the current run's metrics. Use after a deliberate quality improvement.",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.05,
        help="Regression threshold (default: 0.05 = 5 percent absolute drop)",
    )
    return parser.parse_args()


def _print_summary(report: EvalReport) -> None:
    print(f"\nEval run @ {report.timestamp_iso}")
    print(f"  golden set:        {report.golden_set_size} entries")
    print(f"  real match svc:    {report.used_real_match_service}")
    print(f"  total cost:        ${report.total_cost_usd:.4f}")
    print(f"  took:              {report.took_ms} ms")
    print("\nMetrics:")
    for key in sorted(report.metrics):
        print(f"  {key:36s} {report.metrics[key]:.4f}")


async def _amain() -> int:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    args = _cli_args()

    report = await run_eval(args.golden, top_k=args.top_k, judge=args.judge)
    _print_summary(report)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        print(f"\nFull report written to {args.out}")

    if args.update_baseline:
        args.baseline.write_text(
            json.dumps(report.metrics, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        print(f"Baseline updated at {args.baseline}")
        return 0

    if args.baseline.exists():
        # Local import to avoid a circular dep when ``compare`` imports
        # types from this module.
        from tests.eval.compare import compare_to_baseline, format_comparison

        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        comparison = compare_to_baseline(report, baseline, threshold=args.threshold)
        print(format_comparison(comparison))
        return 0 if comparison.passed else 1

    print(f"\n(No baseline found at {args.baseline} — skipping regression check.)")
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    sys.exit(main())
