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

from pathlib import Path

import pytest

from app.core.validation.engine import (
    RuleRegistry,
    Severity,
    ValidationContext,
    ValidationEngine,
    rule_registry,
)
from app.core.validation.rules import (
    GAEBEinheitspreisSanity,
    GAEBLVStructure,
    GAEBOrdinalFormat,
    GAEBQuantityDecimals,
    GAEBTradeSectionCode,
    register_builtin_rules,
)
from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter

# Committed official GAEB DA XML 3.3 Pruefdateien (see fixtures README for
# provenance). X83 = unpriced tender request, X84 = priced bid.
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "gaeb"
_PRUEFDATEI_X83 = _FIXTURES / "pruefdatei_3.3_x83.x83"
_PRUEFDATEI_X84 = _FIXTURES / "bvbs_pruefdatei_3.3_x84.x84"


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

    @pytest.mark.asyncio
    async def test_pass_level3_pruefdatei_ordinal(self) -> None:
        """Real BVBS Pruefdatei OZ is 3.3.4 with an optional index - must pass."""
        rule = GAEBOrdinalFormat()
        for oz in ("001.001.0010", "001.001.0010.1", "001.001.0010.A"):
            results = await rule.validate(_ctx([{"id": "1", "ordinal": oz}]))
            assert results[0].passed, f"{oz} should be a valid GAEB OZ"

    @pytest.mark.asyncio
    async def test_mask_from_context_is_enforced(self) -> None:
        """When the OZ-Maske is threaded, level widths are checked exactly."""
        rule = GAEBOrdinalFormat()
        ctx = ValidationContext(
            data={"positions": [{"id": "1", "ordinal": "01.001.0010"}]},
            metadata={"locale": "en", "gaeb_oz_mask": [3, 3, 4]},
        )
        results = await rule.validate(ctx)
        # First level is 2 digits but the mask demands 3 - fails against the mask.
        assert not results[0].passed

    @pytest.mark.asyncio
    async def test_mask_from_position_metadata(self) -> None:
        rule = GAEBOrdinalFormat()
        pos = {"id": "1", "ordinal": "001.001.0010.A", "metadata": {"gaeb_oz_mask": [3, 3, 4]}}
        results = await rule.validate(_ctx([pos]))
        assert results[0].passed


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
        positions = [{"id": "p1", "ordinal": "012.01.0010", "unit": "m2", "unit_rate": 42.50}]
        results = await rule.validate(_ctx(positions))
        assert len(results) == 1
        assert results[0].passed
        assert results[0].severity == Severity.WARNING
        assert results[0].message == "OK"

    @pytest.mark.asyncio
    async def test_zero_rate_warns_not_errors(self) -> None:
        """A 0.00 on an ordinary position is a WARNING, never a blocking ERROR.

        GAEB transfers an offered 0.00 as a valid price; we only ask a human
        to confirm it was not a forgotten rate.
        """
        rule = GAEBEinheitspreisSanity()
        positions = [{"id": "p1", "ordinal": "012.01.0010", "unit": "m2", "unit_rate": 0}]
        results = await rule.validate(_ctx(positions))
        assert not results[0].passed
        assert results[0].severity == Severity.WARNING
        assert "012.01.0010" in results[0].message

    @pytest.mark.asyncio
    async def test_zero_rate_on_provisional_passes(self) -> None:
        """Bedarfs-/Eventualpositionen may be left unpriced - no finding."""
        rule = GAEBEinheitspreisSanity()
        positions = [
            {
                "id": "p1",
                "ordinal": "012.01.0010",
                "unit": "m2",
                "unit_rate": 0,
                "metadata": {"gaeb_provis": "WithTotal"},
            }
        ]
        results = await rule.validate(_ctx(positions))
        assert len(results) == 1
        assert results[0].passed
        assert results[0].message == "OK"

    @pytest.mark.asyncio
    async def test_fail_on_negative_rate(self) -> None:
        rule = GAEBEinheitspreisSanity()
        positions = [{"id": "p1", "ordinal": "012.01.0010", "unit": "m3", "unit_rate": -1.0}]
        results = await rule.validate(_ctx(positions))
        assert not results[0].passed
        assert results[0].severity == Severity.ERROR
        assert "negative" in results[0].message.lower()

    @pytest.mark.asyncio
    async def test_lump_sum_skipped(self) -> None:
        rule = GAEBEinheitspreisSanity()
        positions = [{"id": "p1", "ordinal": "012.01.0010", "unit": "lsum", "unit_rate": 0}]
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
                "unit_rate": -5,
            },
        ]
        report = await engine.validate(
            data={"positions": broken_positions},
            rule_sets=["gaeb"],
            metadata={"locale": "de"},
        )
        # The ordinal-format warning fires and the negative-price Einheitspreis
        # error fires (a negative rate is the only blocking pricing case).
        assert report.has_errors
        assert report.has_warnings
        error_messages = "\n".join(r.message for r in report.errors)
        assert "Einheitspreis" in error_messages, f"expected German Einheitspreis message, got: {error_messages}"


# ── Acceptance: GAEB rule set over the official BVBS Pruefdateien ───────────


async def _import_and_validate(path: Path):
    """Import a GAEB Pruefdatei and run the GAEB rule set over it.

    Mirrors the import-to-validation path: each imported position becomes a
    validation dict carrying its ordinal, unit, rate and the importer's
    metadata (OZ-Maske, phase, section ref, Provis flag); the OZ-Maske is also
    threaded on the context. Returns the engine report.
    """
    content = path.read_bytes()
    imported = await GAEBXMLImporter.parse(content)
    positions = [
        {
            "id": p.ordinal,
            "ordinal": p.ordinal,
            "unit": p.unit,
            "quantity": p.quantity,
            "unit_rate": p.unit_rate,
            "classification": p.classification,
            "metadata": p.metadata,
            "type": "section" if p.metadata.get("gaeb_is_section") else "position",
        }
        for p in imported.positions
    ]
    register_builtin_rules()
    engine = ValidationEngine(rule_registry)
    return await engine.validate(
        data={"positions": positions, "metadata": imported.metadata},
        rule_sets=["gaeb"],
        metadata={"locale": "en", "gaeb_oz_mask": imported.metadata.get("gaeb_oz_mask")},
    )


class TestGAEBPruefdateiNoFalsePositives:
    """FA-STD-044/045/046: the official Pruefdatei must not drown in noise.

    Before this wave, importing the official Pruefdatei and running the GAEB
    rule set scored ~0.02 - 24 ERROR-level false positives (every 0.00 line and
    every level-3 OZ) buried the real money loss. After the validator fixes the
    file must score above 0.9 and the two previously-false-positive rules
    (ordinal_format, einheitspreis_sanity) must pass for every position.
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("fixture", [_PRUEFDATEI_X83, _PRUEFDATEI_X84])
    async def test_pruefdatei_scores_above_threshold(self, fixture: Path) -> None:
        if not fixture.exists():  # pragma: no cover - committed fixture
            pytest.skip(f"fixture missing: {fixture}")
        report = await _import_and_validate(fixture)

        assert report.score is not None
        assert report.score > 0.9, (
            f"{fixture.name} scored {report.score} with "
            f"{len(report.errors)} error(s): " + "; ".join(r.message for r in report.errors[:5])
        )
        # Zero ERROR-level findings - the engine caps the score hard on any
        # error, so > 0.9 already implies this, but assert it explicitly.
        assert not report.has_errors

    @pytest.mark.asyncio
    @pytest.mark.parametrize("fixture", [_PRUEFDATEI_X83, _PRUEFDATEI_X84])
    async def test_previously_false_positive_rules_now_pass(self, fixture: Path) -> None:
        if not fixture.exists():  # pragma: no cover - committed fixture
            pytest.skip(f"fixture missing: {fixture}")
        report = await _import_and_validate(fixture)

        # Every real Pruefdatei OZ (001.001.0010, 001.001.0010.A, the 1/2-level
        # section headers) must pass the OZ-Maske check.
        ordinal_results = [r for r in report.results if r.rule_id == "gaeb.ordinal_format"]
        assert ordinal_results, "ordinal_format rule did not run"
        assert all(r.passed for r in ordinal_results), [r.element_ref for r in ordinal_results if not r.passed]

        # No legitimate 0.00 / optional position is flagged as a pricing error.
        price_results = [r for r in report.results if r.rule_id == "gaeb.einheitspreis_sanity"]
        assert all(r.passed for r in price_results), [
            (r.element_ref, r.severity.value) for r in price_results if not r.passed
        ]
