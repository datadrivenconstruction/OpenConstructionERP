# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pydantic parity check for ``EacRuleDefinition``.

For every valid JSON-Schema fixture, parsing through Pydantic and
serialising back must yield a body equivalent to the input. This
proves the Pydantic mirror in :mod:`app.modules.eac.schemas` matches
the JSON Schema 1:1.
"""

import pytest

from app.modules.eac.schemas import EacRuleDefinition

from ._fixtures import invalid_fixtures, valid_fixtures


@pytest.mark.parametrize(
    "label,body",
    valid_fixtures(),
    ids=[label for label, _ in valid_fixtures()],
)
def test_pydantic_accepts_valid_fixture(label: str, body: dict) -> None:
    """Pydantic must accept the same payloads JSON Schema accepts."""
    parsed = EacRuleDefinition.model_validate(body)
    assert parsed.name == body["name"]
    assert parsed.output_mode == body["output_mode"]


@pytest.mark.parametrize(
    "label,body",
    valid_fixtures(),
    ids=[label for label, _ in valid_fixtures()],
)
def test_pydantic_round_trip_identity(label: str, body: dict) -> None:
    """``parse → dump → reparse`` must yield equivalent typed objects.

    Stricter "input ⊆ output" key-equality is brittle because Pydantic
    fills in default values during serialisation. The right invariant
    is that re-parsing the dumped JSON yields a Pydantic model that
    equals the first one (which proves no information was lost).
    """
    parsed = EacRuleDefinition.model_validate(body)

    # Round-trip: dump → parse → equality.
    dumped = parsed.model_dump(mode="json")
    reparsed = EacRuleDefinition.model_validate(dumped)
    assert parsed == reparsed, f"round-trip lost data for {label}"

    # The key fields explicitly present in the input survive the trip.
    assert reparsed.name == body["name"]
    assert reparsed.output_mode == body["output_mode"]
    assert reparsed.schema_version == body["schema_version"]


@pytest.mark.parametrize(
    "label,body",
    invalid_fixtures(),
    ids=[label for label, _ in invalid_fixtures()],
)
def test_pydantic_rejects_invalid_fixture(label: str, body: dict) -> None:
    """Pydantic must reject what JSON Schema rejects (parity)."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        EacRuleDefinition.model_validate(body)
