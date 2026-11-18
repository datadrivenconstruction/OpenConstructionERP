# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The neutral pieces under the Chinese VAT work.

The project tax profile (lock, history, derived edition), the tax-inclusive
exclusion in the bill's markup cascade, the per-edition markup stacks, the
project reference and site address on an EN 16931 invoice, and the core
GB 50500 code rules.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.boq.markup_templates import DEFAULT_MARKUP_TEMPLATES, EDITION_REGIONS, REGION_VARIANTS
from app.modules.boq.models import BOQMarkup, Position
from app.modules.boq.service import _calculate_markup_amounts, _calculate_markup_amounts_scoped
from app.modules.project_tax import service
from app.modules.project_tax.models import ProjectTaxProfile
from app.modules.project_tax.schemas import ProfileUpdate
from app.modules.project_tax.validators import evaluate_profile

# ── Profile ──────────────────────────────────────────────────────────────────


def _project(created: date, *, country: str = "CN", standard: str = "gb50500") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        country_code=country,
        classification_standard=standard,
        created_at=datetime(created.year, created.month, created.day, 9, 0),
    )


def test_an_unsaved_profile_proposes_the_edition_in_force_on_creation() -> None:
    old = service.to_response(_project(date(2024, 5, 1)), None)
    new = service.to_response(_project(date(2026, 2, 1)), None)
    assert (old.stored, old.edition_source, old.standard_edition) == (False, "derived", "gb50500@2013")
    assert new.standard_edition == "gb50500@2024"
    assert [e.key for e in new.editions] == ["gb50500@2013", "gb50500@2024"]


def test_a_market_without_editions_proposes_nothing() -> None:
    response = service.to_response(_project(date(2026, 2, 1), country="DE", standard="din276"), None)
    assert (response.standard_edition, response.edition_source, response.editions) == (None, "none", [])


def test_a_method_change_inside_the_lock_is_refused() -> None:
    row = ProjectTaxProfile(project_id=uuid.uuid4(), method_history=[])
    service.apply_update(
        row,
        ProfileUpdate(tax_method="simplified", election_date=date(2026, 1, 31), lock_months=36),
        today=date(2026, 1, 31),
        is_new=True,
    )
    with pytest.raises(service.ProfileLockedError) as exc:
        service.apply_update(row, ProfileUpdate(tax_method="general"), today=date(2027, 6, 1), is_new=False)
    assert exc.value.ends_on == date(2029, 1, 31)
    assert row.tax_method == "simplified"


def test_a_method_change_after_the_lock_keeps_the_history() -> None:
    row = ProjectTaxProfile(project_id=uuid.uuid4(), method_history=[])
    service.apply_update(
        row,
        ProfileUpdate(tax_method="simplified", election_date=date(2019, 5, 1), lock_months=36),
        today=date(2019, 5, 1),
        is_new=True,
    )
    service.apply_update(row, ProfileUpdate(tax_method="general"), today=date(2026, 3, 1), is_new=False)
    assert row.tax_method == "general"
    assert row.election_date == date(2026, 3, 1)
    assert row.method_history == [{"method": "simplified", "election_date": "2019-05-01", "changed_on": "2026-03-01"}]


def test_a_stored_profile_reports_its_lock_and_region() -> None:
    project = _project(date(2026, 2, 1))
    row = ProjectTaxProfile(
        project_id=project.id,
        tax_method="simplified",
        election_date=date(2026, 2, 1),
        lock_months=36,
        standard_edition="gb50500@2024",
        site_city="Hefei",
        home_city="Shanghai",
        method_history=[],
        grandfathered=False,
        employer_supplied=False,
        taxpayer_size="general",
        notes="",
    )
    response = service.to_response(project, row)
    assert response.stored and response.edition_source == "stored"
    assert response.lock_ends_on == date(2029, 2, 1)
    assert response.cross_region is True


async def test_profile_rules() -> None:
    project = _project(date(2026, 2, 1))
    unsaved = service.to_response(project, None)
    unsaved.tax_method = "simplified"
    ids = {r.rule_id for r in await evaluate_profile(service.record_for_rules(project, unsaved))}
    assert {"project_tax.election_dated", "project_tax.edition_stated"} <= ids


# ── Markup cascade ───────────────────────────────────────────────────────────


def _markup(name: str, category: str, pct: str, apply_to: str, order: int) -> BOQMarkup:
    return BOQMarkup(
        name=name,
        category=category,
        markup_type="percentage",
        percentage=Decimal(pct),
        apply_to=apply_to,
        sort_order=order,
        is_active=True,
    )


def test_a_tax_line_does_not_tax_a_tax_inclusive_cost_again() -> None:
    vat = _markup("VAT", "tax", "9", "cumulative", 0)
    ((_, plain),) = _calculate_markup_amounts(Decimal("9464000"), [vat])
    ((_, kept_out),) = _calculate_markup_amounts(Decimal("9464000"), [vat], None, Decimal("436000"))
    assert plain == Decimal("851760")
    assert kept_out == Decimal("812520")


def test_the_scoped_cascade_reads_the_flag_from_positions() -> None:
    boq_id = uuid.uuid4()
    works = Position(id=uuid.uuid4(), boq_id=boq_id, ordinal="1", unit="m3", total="9028000", metadata_={})
    pc_sum = Position(
        id=uuid.uuid4(), boq_id=boq_id, ordinal="2", unit="item", total="436000", metadata_={"tax_inclusive": True}
    )
    overhead = _markup("Overhead", "overhead", "10", "direct_cost", 0)
    vat = _markup("VAT", "tax", "9", "direct_cost", 1)
    result = {
        m.name: a
        for m, a in _calculate_markup_amounts_scoped(
            Decimal("9464000"), [overhead, vat], [works, pc_sum], lambda p: Decimal(str(p.total))
        )
    }
    assert result["Overhead"] == Decimal("946400")  # every other base keeps the sum
    assert result["VAT"] == Decimal("812520")


def test_china_has_a_stack_per_edition() -> None:
    new = [str(line["name"]) for line in DEFAULT_MARKUP_TEMPLATES["CN"]]
    old = [str(line["name"]) for line in DEFAULT_MARKUP_TEMPLATES["CN_GB50500_2013"]]
    assert not any("规费" in n or "规费" in n for n in new)
    assert any("规费" in n or "规费" in n for n in old)
    assert len(old) == len(new) + 1
    assert EDITION_REGIONS["CN"] == {"gb50500@2013": "CN_GB50500_2013", "gb50500@2024": "CN"}
    assert REGION_VARIANTS["CN_GB50500_2013"] == "CN"


# ── EN 16931: project reference and site ─────────────────────────────────────


def _party(**over: object) -> dict:
    party = {
        "name": "Bau GmbH",
        "vat_id": "DE123456789",
        "line1": "Baustrasse 1",
        "postcode": "10115",
        "city": "Berlin",
        "country_code": "DE",
    }
    party.update(over)
    return party


def _einvoice(profile: str = "zugferd", **ei_changes):
    from app.modules.einvoice import build_einvoice

    ei = {
        "seller": _party(),
        "buyer": _party(name="Stadt Beispiel", vat_id="DE987654321", city="Potsdam"),
        "buyer_reference": "PO-77",
        "project_reference": "P-42",
        "project_name": "Tower A",
        "site_address": {"line1": "Site Rd 5", "city": "Potsdam", "postcode": "14467", "country_code": "DE"},
    }
    ei.update(ei_changes)
    invoice = {
        "invoice_number": "RE-2026-0421",
        "invoice_date": "2026-08-21",
        "due_date": "2026-09-20",
        "currency_code": "EUR",
        "amount_subtotal": Decimal("100"),
        "tax_amount": Decimal("19"),
        "retention_amount": Decimal("0"),
        "metadata": {"einvoice": ei},
    }
    line = {
        "line_id": "1",
        "description": "Concrete C30/37",
        "unit": "m3",
        "quantity": Decimal("1"),
        "unit_rate": Decimal("100"),
        "amount": Decimal("100"),
        "vat_rate": Decimal("19"),
        "vat_category": "S",
    }
    return build_einvoice(invoice=invoice, line_items=[line], profile=profile)


def test_cii_carries_the_project_and_the_site() -> None:
    from app.modules.einvoice.cii import build_cii_xml

    text = build_cii_xml(_einvoice()).decode("utf-8")
    assert "SpecifiedProcuringProject" in text and ">P-42<" in text and ">Tower A<" in text
    assert "ShipToTradeParty" in text and ">Site Rd 5<" in text


def test_ubl_carries_the_project_and_the_site_and_skips_both_when_unset() -> None:
    from app.modules.einvoice.ubl import build_ubl_xml

    text = build_ubl_xml(_einvoice("ubl")).decode("utf-8")
    assert "ProjectReference" in text and ">P-42<" in text
    assert "DeliveryLocation" in text and ">Site Rd 5<" in text
    bare = build_ubl_xml(_einvoice("ubl", project_reference=None, site_address={"city": "Potsdam"})).decode("utf-8")
    assert "ProjectReference" not in bare and "DeliveryLocation" not in bare


# ── Core GB 50500 code rules ─────────────────────────────────────────────────


def _pos(pid: str, code: str, sub: str = "") -> dict:
    return {
        "id": pid,
        "ordinal": pid,
        "type": "item",
        "unit": "m3",
        "quantity": 1.0,
        "unit_rate": 1.0,
        "classification": {"gb50500": code},
        "metadata": {"sub_project": sub} if sub else {},
    }


async def test_core_rules_accept_supplementary_codes_and_catch_duplicates() -> None:
    from app.core.validation.rules import GBT50500CodeUnique, GBT50500ValidCode

    context = ValidationContext(
        data={
            "positions": [
                _pos("a", "01B001"),
                _pos("b", "010501001001", "S1"),
                _pos("c", "010501001001", "S1"),
                _pos("d", "010501001001", "S2"),
            ]
        },
        metadata={"locale": "en"},
    )
    valid = await GBT50500ValidCode().validate(context)
    assert all(r.passed for r in valid)
    unique = {r.element_ref: r.passed for r in await GBT50500CodeUnique().validate(context)}
    assert unique == {"a": True, "b": True, "c": False, "d": True}
