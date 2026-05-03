# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Meta-tests for the eval harness itself.

These tests do *not* measure match-quality — they verify the harness
plumbing (golden-set parses, judge prompt formats, fallback works,
runner aggregates metrics, compare detects regressions).

Run:

    cd backend
    python -m pytest tests/eval/test_eval_harness.py -v
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.eval.compare import compare_to_baseline, format_comparison
from tests.eval.judge import (
    _judge_rule_based,
    _validate_verdict_payload,
    build_judge_prompt,
    get_run_cost,
    judge_match,
    reset_run_cost,
)
from tests.eval.runner import (
    EvalReport,
    _aggregate_metrics,
    _stub_match_element,
    run_eval,
)

GOLDEN_PATH = Path(__file__).parent / "golden_set.yaml"


# ── Golden set parses ──────────────────────────────────────────────────────


class TestGoldenSet:
    def test_yaml_parses(self) -> None:
        with GOLDEN_PATH.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        assert isinstance(data, list), "golden_set.yaml must be a top-level list"
        assert len(data) >= 30, f"need >=30 entries, got {len(data)}"

    def test_required_fields(self) -> None:
        with GOLDEN_PATH.open("r", encoding="utf-8") as fh:
            entries = yaml.safe_load(fh)
        for e in entries:
            assert "id" in e
            assert e["source"] in ("bim", "pdf", "dwg", "photo"), e["id"]
            assert "element_info" in e, e["id"]
            assert isinstance(e["element_info"], dict), e["id"]
            assert "ground_truth" in e, e["id"]
            assert isinstance(e["ground_truth"], dict), e["id"]
            assert e["ground_truth"].get("cwicr_position_codes"), e["id"]
            # at least one acceptable rate range key must be present
            gt = e["ground_truth"]
            assert "acceptable_cost_range_eur_per_m2" in gt or "acceptable_cost_range_eur_per_unit" in gt, (
                f"{e['id']} has no rate range"
            )

    def test_source_distribution(self) -> None:
        """Brief asks for BIM x10, PDF x8, DWG x6, photo x6."""

        with GOLDEN_PATH.open("r", encoding="utf-8") as fh:
            entries = yaml.safe_load(fh)
        by_source: dict[str, int] = {}
        for e in entries:
            by_source[e["source"]] = by_source.get(e["source"], 0) + 1
        assert by_source.get("bim", 0) >= 10
        assert by_source.get("pdf", 0) >= 8
        assert by_source.get("dwg", 0) >= 6
        assert by_source.get("photo", 0) >= 6

    def test_ids_are_unique(self) -> None:
        with GOLDEN_PATH.open("r", encoding="utf-8") as fh:
            entries = yaml.safe_load(fh)
        ids = [e["id"] for e in entries]
        assert len(ids) == len(set(ids)), "duplicate ids in golden_set.yaml"


# ── Judge ──────────────────────────────────────────────────────────────────


class TestJudgePrompt:
    def test_prompt_contains_element_info(self) -> None:
        prompt = build_judge_prompt(
            element_info={"category": "wall", "material": "Concrete"},
            ground_truth={"cwicr_position_codes": ["330.10.020"]},
            candidate={"code": "330.10.020", "unit_rate": 120},
        )
        assert "wall" in prompt
        assert "Concrete" in prompt
        assert "330.10.020" in prompt
        assert "verdict" in prompt
        assert "JSON" in prompt

    def test_prompt_uses_strict_json_directive(self) -> None:
        prompt = build_judge_prompt({}, {}, {})
        assert "Return JSON only" in prompt


class TestJudgeFallback:
    """The rule-based fallback is deterministic — we test it directly
    (no LLM, no env vars required)."""

    def test_exact_code_match_in_range(self) -> None:
        v = _judge_rule_based(
            {},
            {"cwicr_position_codes": ["330.10.020"], "acceptable_cost_range_eur_per_m2": [80, 200]},
            {"code": "330.10.020", "unit_rate": 120.0},
        )
        assert v.verdict == "correct"
        assert v.used_fallback is True
        assert v.cost_usd == 0.0

    def test_exact_code_match_out_of_range(self) -> None:
        v = _judge_rule_based(
            {},
            {"cwicr_position_codes": ["330.10.020"], "acceptable_cost_range_eur_per_m2": [80, 200]},
            {"code": "330.10.020", "unit_rate": 9999.0},
        )
        assert v.verdict == "partial"
        assert "rate" in v.reason.lower()

    def test_prefix_match_partial(self) -> None:
        v = _judge_rule_based(
            {},
            {"cwicr_position_codes": ["330.10.020"]},
            {"code": "330.10.099", "unit_rate": 120.0},
        )
        assert v.verdict == "partial"

    def test_no_match_incorrect(self) -> None:
        v = _judge_rule_based(
            {},
            {"cwicr_position_codes": ["330.10.020"]},
            {"code": "999.99.999", "unit_rate": 50.0},
        )
        assert v.verdict == "incorrect"

    def test_empty_candidate_code(self) -> None:
        v = _judge_rule_based(
            {},
            {"cwicr_position_codes": ["330.10.020"]},
            {"code": "", "unit_rate": 120.0},
        )
        assert v.verdict == "incorrect"


class TestJudgePayloadValidation:
    def test_valid(self) -> None:
        out = _validate_verdict_payload({"verdict": "correct", "confidence": 0.9, "reason": "ok"})
        assert out is not None
        assert out["verdict"] == "correct"
        assert out["confidence"] == 0.9

    def test_invalid_verdict(self) -> None:
        assert _validate_verdict_payload({"verdict": "maybe", "confidence": 0.5, "reason": ""}) is None

    def test_clamps_confidence(self) -> None:
        out = _validate_verdict_payload({"verdict": "correct", "confidence": 5.0, "reason": ""})
        assert out is not None
        assert out["confidence"] == 1.0

    def test_non_dict_returns_none(self) -> None:
        assert _validate_verdict_payload("nope") is None
        assert _validate_verdict_payload(None) is None


@pytest.mark.asyncio
class TestJudgeMatch:
    async def test_use_llm_false_uses_fallback(self) -> None:
        # No env vars, use_llm=False → must use rule-based
        v = await judge_match(
            element_info={},
            ground_truth={"cwicr_position_codes": ["330.10.020"]},
            candidate={"code": "330.10.020", "unit_rate": 100, "rate": 100},
            use_llm=False,
        )
        assert v.used_fallback is True
        assert v.cost_usd == 0.0

    async def test_use_llm_no_key_falls_back(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Strip any real keys so the LLM path can't fire
        for var in (
            "EVAL_AI_PROVIDER",
            "EVAL_AI_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
        ):
            monkeypatch.delenv(var, raising=False)
        v = await judge_match(
            element_info={},
            ground_truth={"cwicr_position_codes": ["330.10.020"]},
            candidate={"code": "330.10.020", "unit_rate": 100},
            use_llm=True,
        )
        assert v.used_fallback is True


# ── Runner aggregation ─────────────────────────────────────────────────────


@pytest.mark.asyncio
class TestRunnerAggregation:
    """Use a mock match function that returns predictable candidates and
    then check the metrics math."""

    async def test_perfect_top_1(self, tmp_path: Path) -> None:
        """Every entry's top-1 candidate is correct → top-1 acc = 1.0, MRR = 1.0."""

        golden = tmp_path / "golden.yaml"
        golden.write_text(
            yaml.safe_dump(
                [
                    {
                        "id": "t-001",
                        "source": "bim",
                        "element_info": {"category": "wall"},
                        "ground_truth": {
                            "cwicr_position_codes": ["330.10.020"],
                            "acceptable_cost_range_eur_per_m2": [80, 200],
                        },
                    },
                    {
                        "id": "t-002",
                        "source": "pdf",
                        "element_info": {"description": "paint"},
                        "ground_truth": {
                            "cwicr_position_codes": ["363.10.010"],
                            "acceptable_cost_range_eur_per_m2": [4, 18],
                        },
                    },
                ]
            ),
            encoding="utf-8",
        )

        async def perfect_match(element_info: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
            if "wall" in str(element_info):
                return [
                    {"code": "330.10.020", "unit_rate": 120.0},
                    {"code": "999.99.999", "unit_rate": 50.0},
                ]
            return [
                {"code": "363.10.010", "unit_rate": 8.0},
                {"code": "999.99.999", "unit_rate": 50.0},
            ]

        report = await run_eval(golden, top_k=5, judge=False, match_fn=perfect_match)
        assert report.metrics["top_1_accuracy"] == 1.0
        assert report.metrics["top_5_recall"] == 1.0
        assert report.metrics["mrr"] == 1.0
        assert report.metrics["top_1_accuracy.bim"] == 1.0
        assert report.metrics["top_1_accuracy.pdf"] == 1.0
        assert report.golden_set_size == 2
        assert report.used_real_match_service is False

    async def test_correct_at_rank_3_gives_mrr_one_third(self, tmp_path: Path) -> None:
        golden = tmp_path / "golden.yaml"
        golden.write_text(
            yaml.safe_dump(
                [
                    {
                        "id": "t-001",
                        "source": "bim",
                        "element_info": {"category": "wall"},
                        "ground_truth": {
                            "cwicr_position_codes": ["330.10.020"],
                            "acceptable_cost_range_eur_per_m2": [80, 200],
                        },
                    },
                ]
            ),
            encoding="utf-8",
        )

        async def rank_3_match(element_info: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
            return [
                {"code": "999.99.001", "unit_rate": 50.0},
                {"code": "999.99.002", "unit_rate": 50.0},
                {"code": "330.10.020", "unit_rate": 120.0},
                {"code": "999.99.004", "unit_rate": 50.0},
                {"code": "999.99.005", "unit_rate": 50.0},
            ]

        report = await run_eval(golden, top_k=5, judge=False, match_fn=rank_3_match)
        assert report.metrics["top_1_accuracy"] == 0.0
        assert report.metrics["top_5_recall"] == 1.0
        assert abs(report.metrics["mrr"] - (1 / 3)) < 1e-9

    async def test_no_correct_match_zero_metrics(self, tmp_path: Path) -> None:
        golden = tmp_path / "golden.yaml"
        golden.write_text(
            yaml.safe_dump(
                [
                    {
                        "id": "t-001",
                        "source": "bim",
                        "element_info": {"category": "wall"},
                        "ground_truth": {
                            "cwicr_position_codes": ["330.10.020"],
                            "acceptable_cost_range_eur_per_m2": [80, 200],
                        },
                    },
                ]
            ),
            encoding="utf-8",
        )

        report = await run_eval(golden, top_k=5, judge=False, match_fn=_stub_match_element)
        assert report.metrics["top_1_accuracy"] == 0.0
        assert report.metrics["top_5_recall"] == 0.0
        assert report.metrics["mrr"] == 0.0

    async def test_match_fn_exception_recorded(self, tmp_path: Path) -> None:
        golden = tmp_path / "golden.yaml"
        golden.write_text(
            yaml.safe_dump(
                [
                    {
                        "id": "t-001",
                        "source": "bim",
                        "element_info": {"category": "wall"},
                        "ground_truth": {
                            "cwicr_position_codes": ["330.10.020"],
                            "acceptable_cost_range_eur_per_m2": [1, 2],
                        },
                    }
                ]
            ),
            encoding="utf-8",
        )

        async def boom(element_info: dict[str, Any], top_k: int) -> list[dict[str, Any]]:
            raise RuntimeError("match service down")

        report = await run_eval(golden, top_k=5, judge=False, match_fn=boom)
        assert len(report.per_entry_results) == 1
        assert report.per_entry_results[0].error
        assert "match service down" in report.per_entry_results[0].error


# ── Comparison ─────────────────────────────────────────────────────────────


class TestCompare:
    def _mk_report(self, metrics: dict[str, float]) -> EvalReport:
        return EvalReport(
            metrics=metrics,
            per_entry_results=[],
            total_cost_usd=0.0,
            took_ms=1,
            timestamp_iso="2026-05-03T00:00:00Z",
            golden_set_size=0,
            used_real_match_service=False,
        )

    def test_no_regression_passes(self) -> None:
        baseline = {"top_1_accuracy": 0.6, "top_5_recall": 0.85, "mrr": 0.7}
        report = self._mk_report({"top_1_accuracy": 0.62, "top_5_recall": 0.86, "mrr": 0.71})
        result = compare_to_baseline(report, baseline, threshold=0.05)
        assert result.passed is True

    def test_regression_above_threshold_fails(self) -> None:
        baseline = {"top_1_accuracy": 0.6, "top_5_recall": 0.85, "mrr": 0.7}
        report = self._mk_report(
            {"top_1_accuracy": 0.50, "top_5_recall": 0.85, "mrr": 0.7}
        )  # -0.10 on top-1 > 0.05 threshold
        result = compare_to_baseline(report, baseline, threshold=0.05)
        assert result.passed is False
        regressed = [d for d in result.deltas if d.regressed]
        assert any(d.name == "top_1_accuracy" for d in regressed)

    def test_regression_below_threshold_passes(self) -> None:
        baseline = {"top_1_accuracy": 0.6}
        report = self._mk_report({"top_1_accuracy": 0.57})  # -0.03 < 0.05
        result = compare_to_baseline(report, baseline, threshold=0.05)
        assert result.passed is True

    def test_missing_metric_is_regression(self) -> None:
        baseline = {"top_1_accuracy": 0.6, "extra_metric": 0.5}
        report = self._mk_report({"top_1_accuracy": 0.6})
        result = compare_to_baseline(report, baseline, threshold=0.05)
        assert result.passed is False
        assert "extra_metric" in result.missing_metrics

    def test_new_metric_is_not_a_regression(self) -> None:
        baseline = {"top_1_accuracy": 0.6}
        report = self._mk_report({"top_1_accuracy": 0.6, "new_metric": 0.9})
        result = compare_to_baseline(report, baseline, threshold=0.05)
        assert result.passed is True
        assert "new_metric" in result.new_metrics

    def test_format_comparison_returns_string(self) -> None:
        baseline = {"top_1_accuracy": 0.6}
        report = self._mk_report({"top_1_accuracy": 0.62})
        result = compare_to_baseline(report, baseline, threshold=0.05)
        out = format_comparison(result)
        assert "PASSED" in out
        assert "top_1_accuracy" in out


# ── Stub match service ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stub_match_returns_top_k() -> None:
    """The stub must return exactly top_k candidates with the documented shape."""

    candidates = await _stub_match_element({"category": "wall"}, top_k=5)
    assert len(candidates) == 5
    for c in candidates:
        assert "code" in c
        assert "unit_rate" in c
        assert "score" in c


# ── Cost-cap accumulator ───────────────────────────────────────────────────


def test_cost_cap_resets() -> None:
    reset_run_cost()
    assert get_run_cost() == 0.0


# ── Aggregation utility direct test ────────────────────────────────────────


def test_aggregate_metrics_empty_returns_zeroes() -> None:
    metrics = _aggregate_metrics([])
    assert metrics["top_1_accuracy"] == 0.0
    assert metrics["top_5_recall"] == 0.0
    assert metrics["mrr"] == 0.0


# ── End-to-end full golden set runs cleanly with rule-based judge ──────────


@pytest.mark.asyncio
async def test_full_golden_set_runs_with_stub() -> None:
    """Smoke test: load the real golden set, run with stub matcher and
    rule-based judge — every entry should produce an EntryResult with no
    exceptions, and metrics should all be 0 (the stub returns garbage).
    """

    report = await run_eval(GOLDEN_PATH, top_k=5, judge=False, match_fn=_stub_match_element)
    assert report.golden_set_size >= 30
    assert len(report.per_entry_results) == report.golden_set_size
    assert report.metrics["top_1_accuracy"] == 0.0
    assert report.metrics["top_5_recall"] == 0.0
    # Per-source breakdowns must be present for all 4 sources
    for source in ("bim", "pdf", "dwg", "photo"):
        assert f"top_1_accuracy.{source}" in report.metrics
    # to_dict round-trip
    payload = report.to_dict()
    assert json.loads(json.dumps(payload))  # serialisable
