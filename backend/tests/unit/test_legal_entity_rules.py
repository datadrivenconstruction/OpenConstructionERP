# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The validation rules and request schemas of the legal entities module.

Shape checks, not closed lists: a two-letter country, a three-letter currency,
an ISO 3166-2 subdivision under the same country. A branch abroad is allowed
and reported as a warning, because a foreign branch is a real thing with its
own duties there, not a typo.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.legal_entities.models import Branch, LegalEntity
from app.modules.legal_entities.schemas import BranchCreate, LegalEntityCreate
from app.modules.legal_entities.validators import errors, validate_branch, validate_entity


def _entity(**kw):
    base = {"code": "DE01", "country_code": "DE", "subdivision_code": None, "functional_currency": "EUR"}
    return validate_entity(**{**base, **kw})


def test_a_well_formed_entity_passes() -> None:
    assert _entity() == []
    assert _entity(country_code="CA", subdivision_code="CA-ON", functional_currency="CAD") == []


@pytest.mark.parametrize(
    ("override", "rule"),
    [
        ({"country_code": "DEU"}, "legal_entities.country_code_shape"),
        ({"functional_currency": "EURO"}, "legal_entities.currency_shape"),
        ({"subdivision_code": "US-CA"}, "legal_entities.subdivision_country"),
        ({"code": "has space"}, "legal_entities.code_shape"),
    ],
)
def test_each_rule_names_itself(override: dict, rule: str) -> None:
    assert [i.rule_id for i in errors(_entity(**override))] == [rule]


def test_a_branch_abroad_is_a_warning_not_an_error() -> None:
    issues = validate_branch(code="PL1", country_code="PL", subdivision_code=None, entity_country_code="DE")
    assert errors(issues) == []
    assert [i.rule_id for i in issues] == ["legal_entities.branch_abroad"]
    assert validate_branch(code="B1", country_code="DE", subdivision_code=None, entity_country_code="DE") == []


def test_the_schema_normalises_codes() -> None:
    entity = LegalEntityCreate(
        code=" DE01 ", name="Bau GmbH", country_code="de", functional_currency="eur", subdivision_code="de-by"
    )
    assert (entity.code, entity.country_code, entity.functional_currency, entity.subdivision_code) == (
        "DE01",
        "DE",
        "EUR",
        "DE-BY",
    )
    assert BranchCreate(code="B1", name="Site office").country_code is None


def test_the_schema_refuses_a_missing_currency() -> None:
    with pytest.raises(ValidationError):
        LegalEntityCreate(code="X", name="X", country_code="DE")


def test_relationships_declare_their_loading() -> None:
    assert LegalEntity.branches.property.lazy == "selectin"
    assert Branch.legal_entity.property.lazy == "raise_on_sql"
