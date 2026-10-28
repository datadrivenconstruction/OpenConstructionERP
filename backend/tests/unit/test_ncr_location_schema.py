# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure schema tests for the optional NCR location (no DB, no HTTP).

``location_lat`` / ``location_lon`` / ``location_accuracy_m`` are what make
"an inspector flags a non-conformity and a pin appears on the map" true
rather than aspirational, so the shapes that are and are not a location are
worth pinning down here:

* half a position is not a position - a latitude with no longitude stores a
  row that looks located and can never be drawn, which is the silent
  failure this rejects;
* no position at all is the ordinary case and must stay free of ceremony;
* out-of-range coordinates are refused at the edge rather than reaching the
  map as a pin in the wrong hemisphere.

The merged-PATCH half of the same rule lives in ``NCRService.update_ncr``
(it needs the stored row to see both halves) and is covered in
``tests/integration/test_ncr_geo_pin.py``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.modules.ncr.schemas import NCRCreate, NCRResponse, NCRUpdate


def _payload(**overrides: object) -> dict:
    payload: dict = {
        "project_id": uuid.uuid4(),
        "title": "Rebar cover below spec",
        "description": "Cover measured at 18mm against a specified 30mm.",
        "ncr_type": "workmanship",
        "severity": "major",
    }
    payload.update(overrides)
    return payload


def test_an_ncr_without_a_location_is_still_an_ncr() -> None:
    """Most NCRs are raised from a desk. Nothing about that changes."""
    ncr = NCRCreate(**_payload())
    assert ncr.location_lat is None
    assert ncr.location_lon is None
    assert ncr.location_accuracy_m is None


def test_a_located_ncr_keeps_full_coordinate_precision() -> None:
    ncr = NCRCreate(
        **_payload(
            location_lat=Decimal("52.5200066"),
            location_lon=Decimal("13.4049540"),
            location_accuracy_m=Decimal("4.50"),
        ),
    )
    assert ncr.location_lat == Decimal("52.5200066")
    assert ncr.location_lon == Decimal("13.4049540")


def test_a_latitude_without_a_longitude_is_rejected() -> None:
    """Storing half a position looks located and can never be drawn."""
    with pytest.raises(ValidationError, match="together"):
        NCRCreate(**_payload(location_lat=Decimal("52.52")))


def test_a_longitude_without_a_latitude_is_rejected() -> None:
    with pytest.raises(ValidationError, match="together"):
        NCRCreate(**_payload(location_lon=Decimal("13.405")))


def test_accuracy_without_a_position_is_rejected() -> None:
    """Accuracy describes a fix. With no fix it describes nothing."""
    with pytest.raises(ValidationError, match="accuracy"):
        NCRCreate(**_payload(location_accuracy_m=Decimal("4.5")))


@pytest.mark.parametrize(
    ("lat", "lon"),
    [
        (Decimal("91"), Decimal("13.405")),
        (Decimal("-91"), Decimal("13.405")),
        (Decimal("52.52"), Decimal("181")),
        (Decimal("52.52"), Decimal("-181")),
    ],
)
def test_coordinates_outside_the_world_are_rejected(lat: Decimal, lon: Decimal) -> None:
    with pytest.raises(ValidationError):
        NCRCreate(**_payload(location_lat=lat, location_lon=lon))


def test_negative_accuracy_is_rejected() -> None:
    with pytest.raises(ValidationError):
        NCRCreate(
            **_payload(
                location_lat=Decimal("52.52"),
                location_lon=Decimal("13.405"),
                location_accuracy_m=Decimal("-1"),
            ),
        )


def test_zero_zero_is_accepted_as_a_coordinate() -> None:
    """0/0 is a real place. The map layer, not the schema, decides whether a
    given 0/0 is a placeholder - a create that explicitly asks for it means it.
    """
    ncr = NCRCreate(**_payload(location_lat=Decimal("0"), location_lon=Decimal("0")))
    assert ncr.location_lat == Decimal("0")


def test_a_patch_may_carry_one_half_on_its_own() -> None:
    """Correcting a longitude on an already-located NCR is legitimate.

    The pair rule is applied against the merged row in the service, not here,
    because this schema cannot see what is already stored.
    """
    patch = NCRUpdate(location_lon=Decimal("13.41"))
    assert patch.model_dump(exclude_unset=True) == {"location_lon": Decimal("13.41")}


def test_a_patch_can_clear_a_position() -> None:
    patch = NCRUpdate(location_lat=None, location_lon=None)
    assert patch.model_dump(exclude_unset=True) == {"location_lat": None, "location_lon": None}


def test_the_response_carries_the_position_back() -> None:
    """A client that just posted a location has to be able to read it back."""
    fields = set(NCRResponse.model_fields)
    assert {"location_lat", "location_lon", "location_accuracy_m"} <= fields
