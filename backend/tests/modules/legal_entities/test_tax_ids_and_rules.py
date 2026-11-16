# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The entity.* rules on the worked examples: a German group, a US group. Pure, no database."""

from __future__ import annotations

import uuid

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.legal_entities import validators as v
from app.modules.legal_entities.rules import RULES
from app.modules.legal_entities.tax_ids import primary_tax_id, schemes_for

HB = {"scheme": "vat", "value": "DE123456789"}


def _ids(issues: list[v.Issue]) -> list[str]:
    return [i.rule_id for i in issues]


def test_a_german_company_carries_vat_id_and_tax_number_and_no_ein() -> None:
    schemes = [s.scheme for s in schemes_for("DE")]
    assert schemes == ["vat", "tax_number"]
    assert next(s for s in schemes_for("DE") if s.scheme == "vat").mandatory_on_invoice


def test_a_us_company_carries_an_ein_and_never_a_vat_id() -> None:
    schemes = schemes_for("US")
    assert [s.scheme for s in schemes] == ["ein"]
    assert not schemes[0].mandatory_on_invoice


def test_a_canadian_company_carries_a_business_number() -> None:
    assert [s.scheme for s in schemes_for("CA")] == ["bn"]


def test_a_country_without_data_gets_one_free_field_and_no_check() -> None:
    schemes = schemes_for("ZZ")
    assert [s.scheme for s in schemes] == ["other"]
    assert v.check_tax_ids("ZZ", [{"scheme": "other", "value": "anything at all"}]) == []


def test_the_worked_german_vat_ids_pass_and_a_short_one_only_warns() -> None:
    assert v.check_tax_ids("DE", [HB]) == []
    assert v.check_tax_ids("DE", [{"scheme": "vat", "value": "de 987 654 321"}]) == []
    short = v.check_tax_ids("DE", [{"scheme": "vat", "value": "DE12345"}])
    assert _ids(short) == ["entity.tax_id_format"]
    assert short[0].severity == "warning"


def test_the_worked_us_eins_pass() -> None:
    assert v.check_tax_ids("US", [{"scheme": "ein", "value": "12-3456789"}]) == []
    assert v.check_tax_ids("US", [{"scheme": "ein", "value": "98-7654321"}]) == []
    assert _ids(v.check_tax_ids("US", [{"scheme": "ein", "value": "1234"}])) == ["entity.tax_id_format"]


def test_the_table_shows_the_country_s_first_identifier() -> None:
    assert primary_tax_id("DE", [{"scheme": "tax_number", "value": "30/123/45678"}, HB]) == "DE123456789"
    assert primary_tax_id("US", [{"scheme": "ein", "value": "12-3456789"}]) == "12-3456789"
    assert primary_tax_id("DE", [], legacy="DE000000000") == "DE000000000"


def test_a_german_seller_without_vat_id_is_incomplete() -> None:
    seller = {"name": "Muster Hochbau GmbH", "line1": "Musterstraße 1", "city": "Berlin"}
    issues = v.check_seller_complete(seller, "DE", entity_code="HB")
    assert _ids(issues) == ["entity.invoice_seller_incomplete"]
    assert "vat_id" in issues[0].field
    assert v.check_seller_complete({**seller, "vat_id": "DE123456789"}, "DE") == []


def test_a_us_pay_application_needs_no_vat_id() -> None:
    seller = {"name": "Ridgeline Civil LLC", "line1": "200 Sample Rd", "city": "Austin", "tax_number": "98-7654321"}
    assert v.check_seller_complete(seller, "US") == []


def test_a_site_of_another_company_is_refused() -> None:
    hb, tb = uuid.uuid4(), uuid.uuid4()
    assert v.check_site_entity(site_entity_id=hb, entity_id=hb) == []
    assert _ids(v.check_site_entity(site_entity_id=hb, entity_id=tb)) == ["entity.site_wrong_entity"]


def test_an_inactive_company_takes_no_new_project() -> None:
    assert v.check_active_for_new_project(code="TB", is_active=True) == []
    assert _ids(v.check_active_for_new_project(code="TB", is_active=False)) == ["entity.inactive_on_new_project"]


def test_a_project_without_company_is_an_error_only_when_nothing_answers_for_it() -> None:
    # Single-company install that never set up entities: nothing changes.
    assert v.check_project_has_entity(assigned=False, default_exists=False, entities_exist=False) == []
    # The default company answers.
    assert v.check_project_has_entity(assigned=False, default_exists=True, entities_exist=True) == []
    assert _ids(v.check_project_has_entity(assigned=False, default_exists=False, entities_exist=True)) == [
        "entity.project_without_entity"
    ]


def test_records_of_two_companies_warn_about_intercompany() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    assert v.check_cross_entity([a, a, None]) == []
    issues = v.check_cross_entity([a, b])
    assert _ids(issues) == ["entity.cross_entity_reference"] and issues[0].severity == "warning"


def test_a_taken_code_is_a_duplicate() -> None:
    assert v.check_duplicate_code("HB", taken=False) == []
    assert _ids(v.check_duplicate_code("HB-BER", taken=True, site=True)) == ["entity.duplicate_code"]


@pytest.mark.asyncio
async def test_the_engine_rules_judge_the_german_example() -> None:
    hb_id = uuid.uuid4()
    data = {
        "entity": {"id": str(hb_id), "code": "HB", "country_code": "DE", "is_active": True, "tax_ids": [HB]},
        "project": {"id": "P-2026-014", "legal_entity_id": str(hb_id)},
        "site": {"legal_entity_id": str(hb_id)},
        "seller": {"name": "Muster Hochbau GmbH", "line1": "Musterstraße 1", "city": "Berlin", "vat_id": "DE123456789"},
        "default_entity_exists": True,
        "entities_exist": True,
        "linked_entity_ids": [str(hb_id)],
    }
    context = ValidationContext(data=data)
    failed = []
    for rule_class in RULES:
        failed += [r.rule_id for r in await rule_class().validate(context) if not r.passed]
    assert failed == []

    data["seller"] = {"name": "Muster Hochbau GmbH"}
    data["site"] = {"legal_entity_id": str(uuid.uuid4())}
    failed = []
    for rule_class in RULES:
        failed += [r.rule_id for r in await rule_class().validate(context) if not r.passed]
    assert sorted(failed) == ["entity.invoice_seller_incomplete", "entity.site_wrong_entity"]
