# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tests EacRuleDefinition JSON Schema against ≥30 valid + ≥30 invalid fixtures.

Acceptance per RFC 35 EAC-1.2:

* Schema must accept every fixture in ``valid_fixtures()`` (FR-1.4 / FR-1.5
  / FR-1.6 coverage — every selector kind, attribute kind, constraint
  operator).
* Schema must reject every fixture in ``invalid_fixtures()``.
"""

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from app.modules.eac.schema import load_rule_definition_schema

from ._fixtures import invalid_fixtures, valid_fixtures


@pytest.fixture(scope="module")
def schema() -> dict:
    return load_rule_definition_schema()


@pytest.fixture(scope="module")
def validator(schema: dict) -> Draft202012Validator:
    """Pre-built validator. Ensures the schema itself parses cleanly."""
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_schema_is_draft_2020_12(schema: dict) -> None:
    """The shipped schema must declare draft-2020-12."""
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_at_least_30_valid_fixtures() -> None:
    fixtures = valid_fixtures()
    assert len(fixtures) >= 30, f"got {len(fixtures)}"


def test_at_least_30_invalid_fixtures() -> None:
    fixtures = invalid_fixtures()
    assert len(fixtures) >= 30, f"got {len(fixtures)}"


@pytest.mark.parametrize(
    "label,body",
    valid_fixtures(),
    ids=[label for label, _ in valid_fixtures()],
)
def test_valid_fixture_passes_jsonschema(
    label: str,
    body: dict,
    validator: Draft202012Validator,
) -> None:
    """Each fixture in the valid set must validate without error."""
    errors = sorted(validator.iter_errors(body), key=lambda e: e.path)
    assert errors == [], (
        f"fixture {label} should validate but raised: "
        + "; ".join(f"{'/'.join(str(p) for p in e.path)}: {e.message}" for e in errors)
    )


@pytest.mark.parametrize(
    "label,body",
    invalid_fixtures(),
    ids=[label for label, _ in invalid_fixtures()],
)
def test_invalid_fixture_fails_jsonschema(
    label: str,
    body: dict,
    validator: Draft202012Validator,
) -> None:
    """Each fixture in the invalid set must raise at least one error."""
    errors = list(validator.iter_errors(body))
    assert errors, (
        f"fixture {label} should NOT validate but the schema accepted it"
    )


def test_schema_iter_errors_returns_validation_error_class(
    validator: Draft202012Validator,
) -> None:
    """Sanity-check the validator emits proper ValidationError objects.

    Catches accidental schema regressions where iter_errors returns
    ``None`` (e.g. when a buggy ``$ref`` short-circuits validation).
    """
    bogus = {"schema_version": "2.0"}  # missing name + output_mode + selector
    errors = list(validator.iter_errors(bogus))
    assert errors, "expected errors for an obviously-invalid body"
    assert all(isinstance(e, ValidationError) for e in errors)
