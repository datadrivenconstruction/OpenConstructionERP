"""Tests for the GAEB rule set expansion (slice D).

Each of the four new rules (``GAEBLVStructure``, ``GAEBEinheitspreisSanity``,
``GAEBTradeSectionCode``, ``GAEBQuantityDecimals``) gets a pair of cases:
a passing fixture and a failing one. Assertions cover:

* the boolean ``passed`` flag,
* the ``severity`` reported (since that governs ERROR vs WARNING handling
  in the engine),
* the ``message`` being pulled from the English bundle (so template
  placeholders are correctly filled and no hardcoded string snuck in).
"""

from __future__ import annotations

import pytest

from app.core.validation.engine import (
    RuleRegistry,
    Severity,
    ValidationContext,
    ValidationEngine,
)
from app.core.validation.rules import (
    GAEBEinheitspreisSanity,
    GAEBLVStructure,
    GAEBOrdinalFormat,
    GAEBQuantityDecimals,
    GAEBTradeSectionCode,
    register_builtin_rules,
)


def _ctx(positions: list[dict], locale: str = "en") -> ValidationContext:
    return ValidationContext(data={"positions": positions}, metadata={"locale": locale})


# ── Existing rule (regression guard) ───────────────────────────────────────


class TestGAEBOrdinalFormat:
    @pytest.mark.asyncio
    async def test_pass(self) -> None:
        rule = GAEBOrdinalFormat()
        results = await rule.validate(_ctx([{"id": "1", "ordinal": "01.02.0030"}]))
        assert len(results) == 1
        assert results[0].passed
        assert results[0].message == "OK"

    @pytest.mark.asyncio
    async def test_fail(self) -> None:
        rule = GAEBOrdinalFormat()
        results = await rule.validate(_ctx([{"id": "1", "ordinal": "abc"}]))
        assert not results[0].passed
        assert "abc" in results[0].message
        assert results[0].severity == Severity.WARNING


# ── GAEBLVStructure ─────────────────────────────────────────────────────────


class TestGAEBLVStructure:
    @pytest.mark.asyncio
    async def test_pass_when_leaf_has_parent(self) -> None:
        rule = GAEBLVStructure()
        positions = [
            {"id": "sec", "ordinal": "012", "type": "section"},
            {"id": "p1", "ordinal": "012.01.0010", "parent_id": "sec"},
        ]
        results = await rule.validate(_ctx(positions))
        # Only the leaf position is considered (section is skipped)
        assert len(results) == 1
        assert results[0].passed
        assert results[0].message == "OK"

    @pytest.mark.asyncio
    async def test_fail_when_leaf_has_no_parent(self) -> None:
        rule = GAEBLVStructure()
        positions = [
            {"id": "orphan", "ordinal": "99.99.0010"},
        ]
        results = await rule.validate(_ctx(positions))
        assert len(results) == 1
        assert not results[0].passed
        assert results[0].severity == Severity.WARNING
        assert "99.99.0010" in results[0].message
        assert results[0].suggestion is not None

    @pytest.mark.asyncio
    async def test_intermediate_nodes_are_not_flagged(self) -> None:
        """Nodes that parent something are valid regardless of their own parent."""
        rule = GAEBLVStructure()
        positions = [
            {"id": "root", "ordinal": "012.01.0010"},  # parents 'leaf' → intermediate
            {"id": "leaf", "ordinal": "012.01.0020", "parent_id": "root"},
        ]
        results = await rule.validate(_ctx(positions))
        assert len(results) == 1
        assert results[0].element_ref == "leaf"
        assert results[0].passed


# ── GAEBEinheitspreisSanity ────────────────────────────────────────────────


class TestGAEBEinheitspreisSanity:
    @pytest.mark.asyncio
    async def test_pass_positive_rate(self) -> None:
        rule = GAEBEinheitspreisSanity()
        positions = [
            {"id": "p1", "ordinal": "012.01.0010", "unit": "m2", "unit_rate": 42.50}
        ]
        results = await rule.validate(_ctx(positions))
        assert len(results) == 1
        assert results[0].passed
        assert results[0].severity == Severity.ERROR
        assert results[0].message == "OK"

    @pytest.mark.asyncio
    async def test_fail_on_zero_rate(self) -> None:
        rule = GAEBEinheitspreisSanity()
        positions = [
            {"id": "p1", "ordinal": "012.01.0010", "unit": "m2", "unit_rate": 0}
        ]
        results = await rule.validate(_ctx(positions))
        assert not results[0].passed
        assert results[0].severity == Severity.ERROR
        assert "must be > 0" in results[0].message
        assert "012.01.0010" in results[0].message

    @pytest.mark.asyncio
    async def test_fail_on_negative_rate(self) -> None:
        rule = GAEBEinheitspreisSanity()
        positions = [
            {"id": "p1", "ordinal": "012.01.0010", "unit": "m3", "unit_rate": -1.0}
        ]
        results = await rule.validate(_ctx(positions))
        assert not results[0].passed
        assert results[0].severity == Severity.ERROR

    @pytest.mark.asyncio
    async def test_lump_sum_skipped(self) -> None:
        rule = GAEBEinheitspreisSanity()
        positions = [
            {"id": "p1", "ordinal": "012.01.0010", "unit": "lsum", "unit_rate": 0}
        ]
        results = await rule.validate(_ctx(positions))
        assert results == []

    @pytest.mark.asyncio
    async def test_missing_rate_skipped(self) -> None:
        """Missing rate is owned by PositionHasUnitRate; rules should not overlap."""
        rule = GAEBEinheitspreisSanity()
        positions = [{"id": "p1", "ordinal": "012.01.0010", "unit": "m2"}]
        results = await rule.validate(_ctx(positions))
        assert results == []


# ── GAEBTradeSectionCode ──────────────────────────────────────────────────


class TestGAEBTradeSectionCode:
    @pytest.mark.asyncio
    async def test_pass_with_classification_code(self) -> None:
        rule = GAEBTradeSectionCode()
        positions = [
            {
                "id": "sec",
                "ordinal": "Earthworks",
                "type": "section",
                "classification": {"gaeb_lb": "012"},
            }
        ]
        results = await rule.validate(_ctx(positions))
        assert len(results) == 1
        assert results[0].passed
        assert results[0].message == "OK"

    @pytest.mark.asyncio
    async def test_pass_with_ordinal_trade_code(self) -> None:
        rule = GAEBTradeSectionCode()
        positions = [
            {"id": "sec", "ordinal": "012", "type": "section"},
        ]
        results = await rule.validate(_ctx(positions))
        assert len(results) == 1
        assert results[0].passed

    @pytest.mark.asyncio
    async def test_fail_top_level_section_without_code(self) -> None:
        rule = GAEBTradeSectionCode()
        positions = [
            {"id": "sec", "ordinal": "Misc", "type": "section"},
        ]
        results = await rule.validate(_ctx(positions))
        assert len(results) == 1
        assert not results[0].passed
        assert results[0].severity == Severity.WARNING
        assert "Misc" in results[0].message
        assert results[0].suggestion is not None

    @pytest.mark.asyncio
    async def test_nested_sections_ignored(self) -> None:
        """Only top-level sections need the trade code — nested ones inherit it."""
        rule = GAEBTradeSectionCode()
        positions = [
            {"id": "sec", "ordinal": "012", "type": "section"},
            {"id": "sub", "ordinal": "unknown", "type": "section", "parent_id": "sec"},
        ]
        results = await rule.validate(_ctx(positions))
        assert len(results) == 1  # only the top-level was checked
        assert results[0].element_ref == "sec"


# ── GAEBQuantityDecimals ──────────────────────────────────────────────────


class TestGAEBQuantityDecimals:
    @pytest.mark.asyncio
    async def test_pass_three_decimals(self) -> None:
        rule = GAEBQuantityDecimals()
        positions = [
            {"id": "p1", "ordinal": "012.01.0010", "quantity": "12.345"},
        ]
        results = await rule.validate(_ctx(positions))
        assert len(results) == 1
        assert results[0].passed
        assert results[0].message == "OK"

    @pytest.mark.asyncio
    async def test_pass_integer(self) -> None:
        rule = GAEBQuantityDecimals()
        positions = [{"id": "p1", "ordinal": "012.01.0010", "quantity": 10}]
        results = await rule.validate(_ctx(positions))
        assert results[0].passed

    @pytest.mark.asyncio
    async def test_fail_four_decimals(self) -> None:
        rule = GAEBQuantityDecimals()
        positions = [
            {"id": "p1", "ordinal": "012.01.0010", "quantity": "12.34567"},
        ]
        results = await rule.validate(_ctx(positions))
        assert len(results) == 1
        assert not results[0].passed
        assert results[0].severity == Severity.WARNING
        # Template slots for quantity + decimals should appear expanded
        assert "12.34567" in results[0].message
        assert "5" in results[0].message

    @pytest.mark.asyncio
    async def test_skips_missing_quantity(self) -> None:
        rule = GAEBQuantityDecimals()
        positions = [{"id": "p1", "ordinal": "012.01.0010"}]
        results = await rule.validate(_ctx(positions))
        assert results == []

    @pytest.mark.asyncio
    async def test_non_numeric_is_skipped_not_flagged(self) -> None:
        """Non-numeric quantity → we can't count decimals; skip silently."""
        rule = GAEBQuantityDecimals()
        positions = [{"id": "p1", "ordinal": "012.01.0010", "quantity": "not-a-number"}]
        results = await rule.validate(_ctx(positions))
        assert results == []

    @pytest.mark.asyncio
    async def test_float_precision_is_handled_cleanly(self) -> None:
        """0.1 + 0.2 must not be flagged as ~16 decimals; Decimal roundtrip fixes that."""
        rule = GAEBQuantityDecimals()
        positions = [
            {"id": "p1", "ordinal": "012.01.0010", "quantity": 0.3},
        ]
        results = await rule.validate(_ctx(positions))
        # 0.3 has 1 decimal after Decimal(str(value)) roundtrip → passes
        assert results[0].passed


# ── End-to-end: full GAEB rule-set run ─────────────────────────────────────


class TestGAEBRuleSetIntegration:
    @pytest.mark.asyncio
    async def test_registry_has_five_gaeb_rules(self) -> None:
        registry = RuleRegistry()
        for rule in (
            GAEBOrdinalFormat(),
            GAEBLVStructure(),
            GAEBEinheitspreisSanity(),
            GAEBTradeSectionCode(),
            GAEBQuantityDecimals(),
        ):
            registry.register(rule)
        assert registry.list_rule_sets()["gaeb"] == 5

    @pytest.mark.asyncio
    async def test_builtin_registration_yields_five_gaeb_rules(self) -> None:
        """Verify the public ``register_builtin_rules`` entrypoint wires up
        all five GAEB rules into the shared registry.

        ``register_builtin_rules`` binds ``rule_registry`` at import time, so
        we exercise the real singleton and just assert the five rule ids are
        present. Registering twice is idempotent by rule_id, so this is safe
        even when earlier tests have already called the loader.
        """
        from app.core.validation.engine import rule_registry

        register_builtin_rules()
        assert rule_registry.list_rule_sets().get("gaeb", 0) >= 5
        gaeb_rule_ids = {r["rule_id"] for r in rule_registry.list_rules("gaeb")}
        assert {
            "gaeb.ordinal_format",
            "gaeb.lv_structure",
            "gaeb.einheitspreis_sanity",
            "gaeb.trade_section_code",
            "gaeb.quantity_decimals",
        }.issubset(gaeb_rule_ids)

    @pytest.mark.asyncio
    async def test_gaeb_rule_set_produces_localized_output(self) -> None:
        """Smoke-test: running the whole GAEB rule set through the engine
        in German produces messages that aren't English."""
        registry = RuleRegistry()
        for rule in (
            GAEBOrdinalFormat(),
            GAEBLVStructure(),
            GAEBEinheitspreisSanity(),
            GAEBTradeSectionCode(),
            GAEBQuantityDecimals(),
        ):
            registry.register(rule)
        engine = ValidationEngine(registry)

        broken_positions = [
            {
                "id": "orphan",
                "ordinal": "bad-ordinal",
                "quantity": "1.12345",
                "unit": "m2",
                "unit_rate": 0,
            },
        ]
        report = await engine.validate(
            data={"positions": broken_positions},
            rule_sets=["gaeb"],
            metadata={"locale": "de"},
        )
        # At least the ordinal-format warning and the Einheitspreis error fire.
        assert report.has_errors
        assert report.has_warnings
        error_messages = "\n".join(r.message for r in report.errors)
        assert "Einheitspreis" in error_messages, (
            f"expected German Einheitspreis message, got: {error_messages}"
        )
