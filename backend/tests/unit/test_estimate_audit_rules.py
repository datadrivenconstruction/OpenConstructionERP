# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests - the four estimate_audit validation rules.

Covers the curated estimate-audit rule set: work-type unit sanity,
near-duplicate line detection, companion-item completeness (driven by the
Assembly recipe shapes), and the catalogue-benchmarked rate outlier check
that reuses the CWICR matcher. Pure-Python, no database - the rate rule is
exercised through an injected fake matcher.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.core.validation.engine import RuleCategory, Severity, ValidationContext, rule_registry
from app.core.validation.rules import (
    CatalogueRateOutlier,
    MissingCompanionItem,
    NearDuplicateLine,
    WrongUnitOfMeasure,
    _dedup_tokens,
    _detect_work_type,
    _is_assembly_priced,
    _unit_dimension,
    _word_jaccard,
    register_builtin_rules,
)


def _ctx(positions: list[dict[str, Any]], **metadata: Any) -> ValidationContext:
    return ValidationContext(data={"positions": positions}, metadata=metadata)


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestUnitDimension:
    def test_volume_spellings_are_equivalent(self) -> None:
        assert _unit_dimension("m3") == "volume"
        assert _unit_dimension("m³") == "volume"
        assert _unit_dimension("CBM") == "volume"

    def test_length_area_mass_count(self) -> None:
        assert _unit_dimension("m") == "length"
        assert _unit_dimension("m2") == "area"
        assert _unit_dimension("kg") == "mass"
        assert _unit_dimension("pcs") == "count"

    def test_lump_and_unknown(self) -> None:
        assert _unit_dimension("lsum") == "lump"
        assert _unit_dimension("wibble") is None
        assert _unit_dimension("") is None


class TestDetectWorkType:
    def test_concrete_and_multilingual(self) -> None:
        assert _detect_work_type("Ready-mix concrete C30/37") == "concrete"
        assert _detect_work_type("Stahlbetonwand aus Beton") == "concrete"

    def test_companion_wins_over_bulk(self) -> None:
        # "concrete formwork" must read as formwork, not concrete.
        assert _detect_work_type("Concrete wall formwork plywood") == "formwork"
        assert _detect_work_type("Rebar reinforcement in concrete") == "reinforcement"

    def test_unclassified_returns_none(self) -> None:
        assert _detect_work_type("General site management") is None
        assert _detect_work_type("") is None


class TestDedupAndJaccard:
    def test_numeric_tokens_split_out(self) -> None:
        words, nums = _dedup_tokens("Interior wood door 90x210cm")
        assert "door" in words
        assert "wood" in words
        assert "90x210cm" in nums
        # Stop words dropped.
        assert "the" not in words

    def test_jaccard_bounds(self) -> None:
        assert _word_jaccard(frozenset({"a", "b"}), frozenset({"a", "b"})) == 1.0
        assert _word_jaccard(frozenset({"a", "b"}), frozenset({"a", "b", "c", "d"})) == 0.5
        assert _word_jaccard(frozenset(), frozenset()) == 0.0


class TestIsAssemblyPriced:
    def test_assembly_id_and_lump(self) -> None:
        assert _is_assembly_priced({"assembly_id": "abc"}) is True
        assert _is_assembly_priced({"unit": "lsum"}) is True
        assert _is_assembly_priced({"metadata": {"components": [{"x": 1}]}}) is True

    def test_plain_line_is_not_assembly(self) -> None:
        assert _is_assembly_priced({"unit": "m3", "description": "concrete"}) is False


# ---------------------------------------------------------------------------
# Wrong unit of measure
# ---------------------------------------------------------------------------


class TestWrongUnitOfMeasure:
    @pytest.mark.asyncio
    async def test_concrete_in_metres_is_flagged(self) -> None:
        rule = WrongUnitOfMeasure()
        results = await rule.validate(
            _ctx([{"id": "p1", "ordinal": "1.1", "description": "Ready-mix concrete C30/37", "unit": "m"}])
        )
        assert len(results) == 1
        assert results[0].passed is False
        assert results[0].severity == Severity.WARNING
        assert results[0].category == RuleCategory.CONSISTENCY
        assert results[0].element_ref == "p1"

    @pytest.mark.asyncio
    async def test_concrete_in_cubic_metres_passes(self) -> None:
        rule = WrongUnitOfMeasure()
        results = await rule.validate(
            _ctx([{"id": "p1", "ordinal": "1.1", "description": "Ready-mix concrete C30/37", "unit": "m3"}])
        )
        assert len(results) == 1
        assert results[0].passed is True

    @pytest.mark.asyncio
    async def test_formwork_area_passes_volume_fails(self) -> None:
        rule = WrongUnitOfMeasure()
        ok = await rule.validate(_ctx([{"id": "a", "ordinal": "2.1", "description": "Wall formwork", "unit": "m2"}]))
        bad = await rule.validate(_ctx([{"id": "b", "ordinal": "2.2", "description": "Wall formwork", "unit": "m3"}]))
        assert ok[0].passed is True
        assert bad[0].passed is False

    @pytest.mark.asyncio
    async def test_piping_length_ok_area_flagged(self) -> None:
        rule = WrongUnitOfMeasure()
        ok = await rule.validate(_ctx([{"id": "a", "ordinal": "3.1", "description": "PVC pipe DN100", "unit": "m"}]))
        bad = await rule.validate(_ctx([{"id": "b", "ordinal": "3.2", "description": "PVC pipe DN100", "unit": "m2"}]))
        assert ok[0].passed is True
        assert bad[0].passed is False

    @pytest.mark.asyncio
    async def test_unclassified_line_yields_no_finding(self) -> None:
        rule = WrongUnitOfMeasure()
        results = await rule.validate(
            _ctx([{"id": "p1", "ordinal": "9", "description": "Site management", "unit": "wk"}])
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_lump_sum_and_empty_unit_are_skipped(self) -> None:
        rule = WrongUnitOfMeasure()
        lump = await rule.validate(_ctx([{"id": "a", "ordinal": "1", "description": "Concrete works", "unit": "lsum"}]))
        empty = await rule.validate(_ctx([{"id": "b", "ordinal": "2", "description": "Concrete works", "unit": ""}]))
        assert lump == []
        assert empty == []


# ---------------------------------------------------------------------------
# Near-duplicate line
# ---------------------------------------------------------------------------


class TestNearDuplicateLine:
    @pytest.mark.asyncio
    async def test_same_scope_same_unit_different_ordinal_flagged(self) -> None:
        rule = NearDuplicateLine()
        results = await rule.validate(
            _ctx(
                [
                    {"id": "p1", "ordinal": "1.1", "description": "Excavation in trenches by machine", "unit": "m3"},
                    {"id": "p2", "ordinal": "4.7", "description": "Excavation in trenches by machine", "unit": "m3"},
                ]
            )
        )
        fails = [r for r in results if not r.passed]
        assert len(fails) == 2
        assert all(r.severity == Severity.WARNING for r in fails)
        # Each finding points at the other line.
        refs = {r.element_ref for r in fails}
        assert refs == {"p1", "p2"}

    @pytest.mark.asyncio
    async def test_different_dimensions_not_conflated(self) -> None:
        rule = NearDuplicateLine()
        results = await rule.validate(
            _ctx(
                [
                    {"id": "p1", "ordinal": "1.1", "description": "Interior wood door 90x210", "unit": "pcs"},
                    {"id": "p2", "ordinal": "1.2", "description": "Interior wood door 100x210", "unit": "pcs"},
                ]
            )
        )
        # Different numeric fingerprint -> not a duplicate -> one green summary row.
        assert len(results) == 1
        assert results[0].passed is True

    @pytest.mark.asyncio
    async def test_different_unit_not_conflated(self) -> None:
        rule = NearDuplicateLine()
        results = await rule.validate(
            _ctx(
                [
                    {"id": "p1", "ordinal": "1.1", "description": "Plaster to walls internal", "unit": "m2"},
                    {"id": "p2", "ordinal": "1.2", "description": "Plaster to walls internal", "unit": "m3"},
                ]
            )
        )
        assert len(results) == 1
        assert results[0].passed is True

    @pytest.mark.asyncio
    async def test_single_line_produces_no_finding(self) -> None:
        rule = NearDuplicateLine()
        results = await rule.validate(
            _ctx([{"id": "p1", "ordinal": "1.1", "description": "One line only", "unit": "m2"}])
        )
        assert results == []


# ---------------------------------------------------------------------------
# Missing companion item
# ---------------------------------------------------------------------------


class TestMissingCompanionItem:
    @pytest.mark.asyncio
    async def test_standalone_concrete_flags_formwork_and_rebar(self) -> None:
        rule = MissingCompanionItem()
        results = await rule.validate(
            _ctx([{"id": "p1", "ordinal": "1.1", "description": "Ready-mix concrete C25/30", "unit": "m3"}])
        )
        fails = [r for r in results if not r.passed]
        assert len(fails) == 1
        assert fails[0].severity == Severity.INFO
        assert fails[0].category == RuleCategory.COMPLETENESS
        assert fails[0].details["missing_companions"] == ["formwork", "reinforcement"]

    @pytest.mark.asyncio
    async def test_concrete_with_companions_present_passes(self) -> None:
        rule = MissingCompanionItem()
        results = await rule.validate(
            _ctx(
                [
                    {"id": "p1", "ordinal": "1.1", "description": "Ready-mix concrete C25/30", "unit": "m3"},
                    {"id": "p2", "ordinal": "1.2", "description": "Wall formwork plywood", "unit": "m2"},
                    {"id": "p3", "ordinal": "1.3", "description": "Rebar reinforcement steel", "unit": "kg"},
                ]
            )
        )
        assert len(results) == 1
        assert results[0].passed is True

    @pytest.mark.asyncio
    async def test_assembly_priced_concrete_is_skipped(self) -> None:
        rule = MissingCompanionItem()
        results = await rule.validate(
            _ctx(
                [
                    {
                        "id": "p1",
                        "ordinal": "1.1",
                        "description": "Ready-mix concrete C25/30",
                        "unit": "m3",
                        "assembly_id": "asm-1",
                    }
                ]
            )
        )
        # The recipe already bundles formwork + rebar -> not flagged.
        assert len(results) == 1
        assert results[0].passed is True

    @pytest.mark.asyncio
    async def test_paint_without_primer_flagged(self) -> None:
        rule = MissingCompanionItem()
        results = await rule.validate(
            _ctx([{"id": "p1", "ordinal": "5.1", "description": "Emulsion paint to walls", "unit": "m2"}])
        )
        fails = [r for r in results if not r.passed]
        assert len(fails) == 1
        assert fails[0].details["missing_companions"] == ["primer"]


# ---------------------------------------------------------------------------
# Catalogue rate outlier (injected matcher, DB-free)
# ---------------------------------------------------------------------------


def _match(**kwargs: Any) -> SimpleNamespace:
    base = {"score": 0.9, "unit_rate": 100.0, "currency": "EUR", "unit": "m3", "code": "CWICR-1"}
    base.update(kwargs)
    return SimpleNamespace(**base)


def _fake_matcher(matches: list[Any]):
    async def _call(query: str, unit: str | None) -> list[Any]:
        return matches

    return _call


class TestCatalogueRateOutlier:
    @pytest.mark.asyncio
    async def test_no_matcher_skips(self) -> None:
        rule = CatalogueRateOutlier()
        results = await rule.validate(
            _ctx([{"id": "p1", "ordinal": "1", "description": "Concrete C30/37", "unit": "m3", "unit_rate": "9999"}])
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_high_rate_flagged(self) -> None:
        rule = CatalogueRateOutlier()
        results = await rule.validate(
            _ctx(
                [
                    {
                        "id": "p1",
                        "ordinal": "1",
                        "description": "Concrete C30/37",
                        "unit": "m3",
                        "unit_rate": "500",
                        "currency": "EUR",
                    }
                ],
                cwicr_matcher=_fake_matcher([_match(unit_rate=100.0)]),
            )
        )
        assert len(results) == 1
        assert results[0].passed is False
        assert results[0].severity == Severity.WARNING
        assert results[0].category == RuleCategory.QUALITY
        assert results[0].details["ratio"] == pytest.approx(5.0)
        assert results[0].details["catalogue_code"] == "CWICR-1"

    @pytest.mark.asyncio
    async def test_in_band_passes(self) -> None:
        rule = CatalogueRateOutlier()
        results = await rule.validate(
            _ctx(
                [
                    {
                        "id": "p1",
                        "ordinal": "1",
                        "description": "Concrete C30/37",
                        "unit": "m3",
                        "unit_rate": "150",
                        "currency": "EUR",
                    }
                ],
                cwicr_matcher=_fake_matcher([_match(unit_rate=100.0)]),
            )
        )
        assert len(results) == 1
        assert results[0].passed is True

    @pytest.mark.asyncio
    async def test_low_rate_flagged(self) -> None:
        rule = CatalogueRateOutlier()
        results = await rule.validate(
            _ctx(
                [
                    {
                        "id": "p1",
                        "ordinal": "1",
                        "description": "Concrete C30/37",
                        "unit": "m3",
                        "unit_rate": "20",
                        "currency": "EUR",
                    }
                ],
                cwicr_matcher=_fake_matcher([_match(unit_rate=100.0)]),
            )
        )
        assert len(results) == 1
        assert results[0].passed is False

    @pytest.mark.asyncio
    async def test_no_match_skips(self) -> None:
        rule = CatalogueRateOutlier()
        results = await rule.validate(
            _ctx(
                [{"id": "p1", "ordinal": "1", "description": "Concrete C30/37", "unit": "m3", "unit_rate": "500"}],
                cwicr_matcher=_fake_matcher([]),
            )
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_currency_mismatch_skips(self) -> None:
        rule = CatalogueRateOutlier()
        results = await rule.validate(
            _ctx(
                [
                    {
                        "id": "p1",
                        "ordinal": "1",
                        "description": "Concrete C30/37",
                        "unit": "m3",
                        "unit_rate": "500",
                        "currency": "USD",
                    }
                ],
                cwicr_matcher=_fake_matcher([_match(currency="EUR", unit_rate=100.0)]),
            )
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_dimension_mismatch_skips(self) -> None:
        rule = CatalogueRateOutlier()
        results = await rule.validate(
            _ctx(
                [
                    {
                        "id": "p1",
                        "ordinal": "1",
                        "description": "Concrete C30/37",
                        "unit": "m2",
                        "unit_rate": "500",
                        "currency": "EUR",
                    }
                ],
                cwicr_matcher=_fake_matcher([_match(unit="m3", unit_rate=100.0)]),
            )
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_low_confidence_match_skips(self) -> None:
        rule = CatalogueRateOutlier()
        results = await rule.validate(
            _ctx(
                [
                    {
                        "id": "p1",
                        "ordinal": "1",
                        "description": "Concrete C30/37",
                        "unit": "m3",
                        "unit_rate": "500",
                        "currency": "EUR",
                    }
                ],
                cwicr_matcher=_fake_matcher([_match(score=0.3, unit_rate=100.0)]),
            )
        )
        assert results == []


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class TestRegistration:
    def test_four_rules_registered_under_estimate_audit(self) -> None:
        register_builtin_rules()
        rules = rule_registry.get_rules_for_sets(["estimate_audit"])
        ids = {r.rule_id for r in rules}
        assert {
            "estimate_audit.wrong_unit",
            "estimate_audit.near_duplicate",
            "estimate_audit.missing_companion",
            "estimate_audit.rate_outlier",
        }.issubset(ids)
        assert all(r.standard == "estimate_audit" for r in rules)
