"""Integration tests for ClassificationCountryMismatchRule (Wave 27, task #170).

Covers all spec scenarios:
    1. DE project + DIN-only classification → no nudge (passed=True).
    2. DE project + MasterFormat-only classification → INFO nudge, non-empty suggestion.
    3. DE project + both DIN + MasterFormat → no nudge (user has done both).
    4. US project + DIN-only → INFO nudge suggesting MasterFormat.
    5. UK project + DIN-only → INFO nudge suggesting NRM.
    6. No country_code in context → no nudge (false-positive guard).
    7. Unknown MasterFormat div → nudge fires but suggested_din276 is None.
    8. AT / CH also trigger DACH nudge.
    9. DE project + NRM-only → INFO nudge suggesting DIN 276.
    10. US project + NRM-only → INFO nudge suggesting MasterFormat.
    11. Position with all three standards set → no nudge.
    12. Position with no classification at all → no nudge (completeness rules own that).

These are pure unit-style tests: no database, no HTTP stack. The rule is
instantiated directly and executed with a handcrafted ValidationContext.
Placing them under tests/integration/ matches the existing convention for
property_dev_validation_rules tests that also do direct rule execution.
"""

from __future__ import annotations

import pytest

from app.core.validation.engine import (
    RuleCategory,
    Severity,
    ValidationContext,
)
from app.core.validation.rules import ClassificationCountryMismatchRule

# ── Context helpers ────────────────────────────────────────────────────────


def _ctx(
    positions: list[dict],
    country_code: str | None = None,
    region: str | None = None,
    locale: str = "en",
) -> ValidationContext:
    """Build a minimal ValidationContext for the nudge rule."""
    meta: dict = {"locale": locale}
    if country_code is not None:
        meta["country_code"] = country_code
    return ValidationContext(
        data={"positions": positions},
        region=region,
        metadata=meta,
    )


def _pos(
    ordinal: str = "01.01",
    din276: str | None = None,
    nrm: str | None = None,
    masterformat: str | None = None,
    pos_id: str = "p1",
) -> dict:
    """Build a minimal position dict."""
    classification: dict = {}
    if din276 is not None:
        classification["din276"] = din276
    if nrm is not None:
        classification["nrm"] = nrm
    if masterformat is not None:
        classification["masterformat"] = masterformat
    return {"id": pos_id, "ordinal": ordinal, "classification": classification}


# ── Test class ─────────────────────────────────────────────────────────────


class TestClassificationCountryMismatchRule:
    """Unit-style tests exercising the nudge rule in isolation."""

    @pytest.mark.asyncio
    async def test_de_din_only_no_nudge(self) -> None:
        """DE project with DIN 276 only: preferred standard already present — no nudge."""
        rule = ClassificationCountryMismatchRule()
        results = await rule.validate(_ctx([_pos(din276="330")], country_code="DE"))
        assert len(results) == 1
        assert results[0].passed, "Should pass: DIN 276 is the preferred DACH standard"
        assert results[0].severity == Severity.INFO

    @pytest.mark.asyncio
    async def test_de_masterformat_only_nudge(self) -> None:
        """DE project with MasterFormat only: INFO nudge with non-empty suggested DIN 276."""
        rule = ClassificationCountryMismatchRule()
        results = await rule.validate(_ctx([_pos(masterformat="03 30 00")], country_code="DE"))
        assert len(results) == 1
        r = results[0]
        assert not r.passed, "Should fire nudge"
        assert r.severity == Severity.INFO
        assert "DIN 276" in r.message or "Germany" in r.message
        assert r.details["suggested_din276"] is not None, "Mapping for div 03 must exist"
        assert r.details["suggested_din276"] == "330"
        assert r.suggestion is not None

    @pytest.mark.asyncio
    async def test_de_both_din_and_mf_no_nudge(self) -> None:
        """DE project with both DIN 276 and MasterFormat: user has done both — no nudge."""
        rule = ClassificationCountryMismatchRule()
        results = await rule.validate(_ctx([_pos(din276="330", masterformat="03 30 00")], country_code="DE"))
        assert len(results) == 1
        assert results[0].passed

    @pytest.mark.asyncio
    async def test_us_din_only_nudge(self) -> None:
        """US project with DIN 276 only: INFO nudge suggesting MasterFormat."""
        rule = ClassificationCountryMismatchRule()
        results = await rule.validate(_ctx([_pos(din276="330")], country_code="US"))
        assert len(results) == 1
        r = results[0]
        assert not r.passed
        assert r.severity == Severity.INFO
        assert "MasterFormat" in r.message or "United States" in r.message
        assert r.details["suggested_masterformat"] is not None
        assert r.details["suggested_masterformat"] == "03"  # KG 3xx → MF 03

    @pytest.mark.asyncio
    async def test_uk_din_only_nudge(self) -> None:
        """UK project with DIN 276 only: INFO nudge suggesting NRM."""
        rule = ClassificationCountryMismatchRule()
        results = await rule.validate(_ctx([_pos(din276="330")], country_code="GB"))
        assert len(results) == 1
        r = results[0]
        assert not r.passed
        assert r.severity == Severity.INFO
        assert "NRM" in r.message or "United Kingdom" in r.message
        assert r.details["suggested_nrm"] is not None
        assert r.details["suggested_nrm"] == "2"  # KG 3xx → NRM 2 Superstructure

    @pytest.mark.asyncio
    async def test_no_country_code_no_nudge(self) -> None:
        """No country code in context: rule passes silently — avoids false positives."""
        rule = ClassificationCountryMismatchRule()
        results = await rule.validate(_ctx([_pos(masterformat="03 30 00")], country_code=None, region=None))
        assert len(results) == 1
        assert results[0].passed, "Must not fire nudge when country is unknown"

    @pytest.mark.asyncio
    async def test_unknown_mf_div_nudge_fires_without_crash(self) -> None:
        """Unknown MasterFormat division: nudge fires but suggested_din276 is None."""
        rule = ClassificationCountryMismatchRule()
        # Division "99" is not in the mapping table
        results = await rule.validate(_ctx([_pos(masterformat="99 00 00")], country_code="DE"))
        assert len(results) == 1
        r = results[0]
        assert not r.passed
        assert r.severity == Severity.INFO
        assert r.details["suggested_din276"] is None, "Unknown division must still fire nudge but with null suggestion"

    @pytest.mark.asyncio
    async def test_at_triggers_dach_nudge(self) -> None:
        """AT (Austria) is DACH — should also trigger the DIN 276 nudge."""
        rule = ClassificationCountryMismatchRule()
        results = await rule.validate(_ctx([_pos(masterformat="22 10 00")], country_code="AT"))
        r = results[0]
        assert not r.passed
        assert r.details["country"] == "AT"
        assert r.details["suggested_din276"] == "410"  # MF 22 → KG 410 plumbing

    @pytest.mark.asyncio
    async def test_ch_triggers_dach_nudge(self) -> None:
        """CH (Switzerland) is DACH — should also trigger the DIN 276 nudge."""
        rule = ClassificationCountryMismatchRule()
        results = await rule.validate(_ctx([_pos(masterformat="26 00 00")], country_code="CH"))
        r = results[0]
        assert not r.passed
        assert r.details["country"] == "CH"
        assert r.details["suggested_din276"] == "440"  # MF 26 → KG 440 electrical

    @pytest.mark.asyncio
    async def test_de_nrm_only_nudge(self) -> None:
        """DE project with NRM only: INFO nudge suggesting DIN 276."""
        rule = ClassificationCountryMismatchRule()
        results = await rule.validate(_ctx([_pos(nrm="2.6.1")], country_code="DE"))
        r = results[0]
        assert not r.passed
        assert r.severity == Severity.INFO
        assert r.details["suggested_din276"] is not None
        assert r.details["suggested_din276"] == "330"  # NRM elem 2 → KG 330

    @pytest.mark.asyncio
    async def test_us_nrm_only_nudge(self) -> None:
        """US project with NRM only: INFO nudge suggesting MasterFormat."""
        rule = ClassificationCountryMismatchRule()
        results = await rule.validate(_ctx([_pos(nrm="5.4")], country_code="US"))
        r = results[0]
        assert not r.passed
        assert r.severity == Severity.INFO
        assert r.details["suggested_masterformat"] is not None
        assert r.details["suggested_masterformat"] == "22"  # NRM elem 5 → MF 22

    @pytest.mark.asyncio
    async def test_all_three_no_nudge(self) -> None:
        """Position with DIN 276, NRM, and MasterFormat: user has done all — no nudge."""
        rule = ClassificationCountryMismatchRule()
        for country in ("DE", "GB", "US"):
            results = await rule.validate(
                _ctx(
                    [_pos(din276="330", nrm="2.6", masterformat="03 30 00")],
                    country_code=country,
                )
            )
            assert results[0].passed, f"No nudge expected for {country} with all standards"

    @pytest.mark.asyncio
    async def test_unclassified_position_no_nudge(self) -> None:
        """Position with no classification at all: rule skips it (completeness owns this)."""
        rule = ClassificationCountryMismatchRule()
        results = await rule.validate(
            _ctx([_pos()], country_code="DE")  # no din276, nrm, or masterformat
        )
        assert results[0].passed

    @pytest.mark.asyncio
    async def test_region_fallback_dach(self) -> None:
        """Region='DACH' with no country_code: fallback derives DE, nudge fires."""
        rule = ClassificationCountryMismatchRule()
        results = await rule.validate(_ctx([_pos(masterformat="03 30 00")], region="DACH"))
        assert not results[0].passed

    @pytest.mark.asyncio
    async def test_region_fallback_uk(self) -> None:
        """Region='UK' with no country_code: fallback derives GB, nudge fires."""
        rule = ClassificationCountryMismatchRule()
        results = await rule.validate(_ctx([_pos(din276="330")], region="UK"))
        assert not results[0].passed

    @pytest.mark.asyncio
    async def test_region_fallback_us(self) -> None:
        """Region='US' with no country_code: nudge fires for DIN-only position."""
        rule = ClassificationCountryMismatchRule()
        results = await rule.validate(_ctx([_pos(din276="330")], region="US"))
        assert not results[0].passed

    @pytest.mark.asyncio
    async def test_multiple_positions_mixed_nudge(self) -> None:
        """Multiple positions: only the MF-only one fires; DIN-only does not (DE project)."""
        rule = ClassificationCountryMismatchRule()
        positions = [
            _pos(ordinal="01", din276="330", pos_id="good"),
            _pos(ordinal="02", masterformat="09 00 00", pos_id="bad"),
        ]
        results = await rule.validate(_ctx(positions, country_code="DE"))
        assert len(results) == 1
        assert not results[0].passed
        assert results[0].element_ref == "bad"

    @pytest.mark.asyncio
    async def test_category_is_compliance(self) -> None:
        """Rule must belong to COMPLIANCE category per spec."""
        rule = ClassificationCountryMismatchRule()
        assert rule.category == RuleCategory.COMPLIANCE

    @pytest.mark.asyncio
    async def test_standard_is_classification_nudge(self) -> None:
        """Rule's standard must be 'classification_nudge' for rule-set routing."""
        rule = ClassificationCountryMismatchRule()
        assert rule.standard == "classification_nudge"

    @pytest.mark.asyncio
    async def test_uk_masterformat_only_nudge(self) -> None:
        """UK project with MasterFormat only: INFO nudge suggesting NRM."""
        rule = ClassificationCountryMismatchRule()
        results = await rule.validate(_ctx([_pos(masterformat="03 30 00")], country_code="GB"))
        r = results[0]
        assert not r.passed
        assert r.details["suggested_nrm"] is not None
        assert r.details["suggested_nrm"] == "2"  # MF 03 → NRM 2 Superstructure

    @pytest.mark.asyncio
    async def test_de_message_locale(self) -> None:
        """German locale: message contains German text."""
        rule = ClassificationCountryMismatchRule()
        results = await rule.validate(_ctx([_pos(masterformat="03 30 00")], country_code="DE", locale="de"))
        r = results[0]
        assert not r.passed
        # German message should contain 'MasterFormat' (proper noun stays)
        assert "MasterFormat" in r.message or "DIN" in r.message
