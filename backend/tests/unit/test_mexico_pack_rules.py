"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the Mexican regional validation rules.

Covers the four rules the Mexico pack registers into the built-in rule
registry (``register_builtin_rules``): APU cost-component completeness, IVA
rate validity, subcontract retenciones, and CFDI 4.0 issuer data. Each rule
operates on a plain ``ValidationContext`` (no database), so these are pure
unit tests.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.validation.engine import RuleCategory, Severity, ValidationContext
from app.core.validation.rules import (
    APUCompletenessRule,
    CFDIIssuerDataRule,
    IVARateValidityRule,
    SubcontractRetencionRule,
)

pytestmark = pytest.mark.asyncio


def _ctx(positions: list[dict[str, Any]], **kwargs: Any) -> ValidationContext:
    return ValidationContext(data={"positions": positions}, **kwargs)


# ── APUCompletenessRule ──────────────────────────────────────────────────────


class TestAPUCompleteness:
    def test_metadata_locks_the_rule_contract(self) -> None:
        rule = APUCompletenessRule()
        assert rule.rule_id == "mexico.apu_completeness"
        assert rule.standard == "mexico"
        assert rule.severity == Severity.WARNING
        assert rule.category == RuleCategory.COMPLETENESS

    async def test_passes_when_labor_and_material_present(self) -> None:
        results = await APUCompletenessRule().validate(
            _ctx(
                [
                    {
                        "id": "p1",
                        "ordinal": "1.1",
                        "metadata": {"resources": [{"type": "labor"}, {"type": "material"}]},
                    }
                ]
            )
        )
        assert len(results) == 1
        assert results[0].passed is True
        assert results[0].element_ref == "p1"

    async def test_warns_when_labor_missing(self) -> None:
        results = await APUCompletenessRule().validate(
            _ctx([{"id": "p2", "ordinal": "2.1", "metadata": {"resources": [{"type": "material"}]}}])
        )
        assert len(results) == 1
        assert results[0].passed is False
        assert results[0].severity == Severity.WARNING
        assert "mano_de_obra" in results[0].details["missing"]

    async def test_recognizes_spanish_resource_aliases(self) -> None:
        results = await APUCompletenessRule().validate(
            _ctx(
                [
                    {
                        "id": "p3",
                        "ordinal": "3.1",
                        "metadata": {"resources": [{"type": "mano de obra"}, {"type": "materiales"}]},
                    }
                ]
            )
        )
        assert results[0].passed is True

    async def test_skips_positions_without_a_resource_breakdown(self) -> None:
        results = await APUCompletenessRule().validate(_ctx([{"id": "p4", "metadata": {}}]))
        assert results == []

    async def test_skips_supply_only_and_labor_only_concepts(self) -> None:
        results = await APUCompletenessRule().validate(
            _ctx(
                [
                    {
                        "id": "p5",
                        "metadata": {"resources": [{"type": "material"}], "apu_supply_only": True},
                    },
                    {
                        "id": "p6",
                        "metadata": {"resources": [{"type": "labor"}], "apu_labor_only": True},
                    },
                ]
            )
        )
        assert results == []

    async def test_skips_section_header_rows(self) -> None:
        results = await APUCompletenessRule().validate(
            _ctx(
                [
                    {
                        "id": "s1",
                        "type": "section",
                        "metadata": {"resources": [{"type": "material"}]},
                    }
                ]
            )
        )
        assert results == []


# ── IVARateValidityRule ──────────────────────────────────────────────────────


class TestIVARateValidity:
    def test_metadata_locks_the_rule_contract(self) -> None:
        rule = IVARateValidityRule()
        assert rule.rule_id == "mexico.iva_rate_valid"
        assert rule.severity == Severity.WARNING
        assert rule.category == RuleCategory.COMPLIANCE

    @pytest.mark.parametrize("rate", [16, "16", "16 %", 8, 0, 0.16])
    async def test_accepts_standard_border_and_zero_rates(self, rate: Any) -> None:
        results = await IVARateValidityRule().validate(_ctx([{"id": "i1", "ordinal": "1", "iva_rate": rate}]))
        assert len(results) == 1
        assert results[0].passed is True, f"rate {rate!r} should be accepted"

    async def test_flags_an_out_of_range_rate(self) -> None:
        results = await IVARateValidityRule().validate(_ctx([{"id": "i2", "ordinal": "2", "iva_rate": 15}]))
        assert results[0].passed is False

    async def test_reads_the_rate_from_metadata(self) -> None:
        results = await IVARateValidityRule().validate(
            _ctx([{"id": "i3", "ordinal": "3", "metadata": {"vat_rate": "0.16"}}])
        )
        assert results[0].passed is True

    async def test_skips_positions_that_declare_no_rate(self) -> None:
        results = await IVARateValidityRule().validate(_ctx([{"id": "i4", "ordinal": "4"}]))
        assert results == []


# ── SubcontractRetencionRule ─────────────────────────────────────────────────


class TestSubcontractRetencion:
    def test_metadata_locks_the_rule_contract(self) -> None:
        rule = SubcontractRetencionRule()
        assert rule.rule_id == "mexico.subcontract_retencion"
        assert rule.severity == Severity.INFO
        assert rule.category == RuleCategory.COMPLIANCE

    async def test_passes_when_a_subcontract_records_a_retencion_decision(self) -> None:
        results = await SubcontractRetencionRule().validate(
            _ctx(
                [
                    {
                        "id": "r1",
                        "ordinal": "1",
                        "metadata": {"subcontracted": True, "retencion_iva": "6"},
                    }
                ]
            )
        )
        assert len(results) == 1
        assert results[0].passed is True

    async def test_nudges_when_a_subcontract_omits_retenciones(self) -> None:
        results = await SubcontractRetencionRule().validate(
            _ctx([{"id": "r2", "ordinal": "2", "metadata": {"subcontracted": True}}])
        )
        assert results[0].passed is False

    async def test_detects_subcontract_via_resource_type(self) -> None:
        results = await SubcontractRetencionRule().validate(
            _ctx([{"id": "r3", "ordinal": "3", "metadata": {"resources": [{"type": "subcontratista"}]}}])
        )
        assert len(results) == 1
        assert results[0].passed is False

    async def test_ignores_non_subcontract_lines(self) -> None:
        results = await SubcontractRetencionRule().validate(
            _ctx([{"id": "r4", "metadata": {"resources": [{"type": "labor"}]}}])
        )
        assert results == []


# ── CFDIIssuerDataRule ───────────────────────────────────────────────────────


class TestCFDIIssuerData:
    def test_metadata_locks_the_rule_contract(self) -> None:
        rule = CFDIIssuerDataRule()
        assert rule.rule_id == "mexico.cfdi_rfc_present"
        assert rule.severity == Severity.WARNING
        assert rule.category == RuleCategory.COMPLIANCE

    async def test_passes_with_a_valid_persona_moral_rfc_and_all_fields(self) -> None:
        ctx = ValidationContext(
            data={},
            project_id="proj1",
            metadata={"rfc": "OCE241231AB1", "regimen_fiscal": "601", "uso_cfdi": "I01"},
        )
        results = await CFDIIssuerDataRule().validate(ctx)
        assert len(results) == 1
        assert results[0].passed is True
        assert results[0].element_ref == "proj1"

    async def test_accepts_a_13_character_persona_fisica_rfc(self) -> None:
        ctx = ValidationContext(
            data={},
            metadata={"rfc": "VECJ880326AB1", "regimen_fiscal": "612", "uso_cfdi": "G03"},
        )
        results = await CFDIIssuerDataRule().validate(ctx)
        assert results[0].passed is True

    async def test_flags_missing_issuer_fields(self) -> None:
        ctx = ValidationContext(data={}, metadata={"rfc": "OCE241231AB1"})
        results = await CFDIIssuerDataRule().validate(ctx)
        assert results[0].passed is False
        assert results[0].details["missing"]  # regimen fiscal + uso CFDI

    async def test_flags_a_malformed_rfc(self) -> None:
        ctx = ValidationContext(
            data={},
            metadata={"rfc": "BADRFC", "regimen_fiscal": "601", "uso_cfdi": "I01"},
        )
        results = await CFDIIssuerDataRule().validate(ctx)
        assert results[0].passed is False

    async def test_collects_fields_from_a_nested_cfdi_block_in_data(self) -> None:
        ctx = ValidationContext(data={"cfdi": {"rfc": "OCE241231AB1", "regimen_fiscal": "601", "uso_cfdi": "I01"}})
        results = await CFDIIssuerDataRule().validate(ctx)
        assert results[0].passed is True
