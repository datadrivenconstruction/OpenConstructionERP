# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The equipment list routes describe how much of themselves they return.

``GET /equipment/`` used to answer with a bare ``list[EquipmentResponse]``. The
repository had counted the yard on every call and the route discarded the count
with ``items, _ = ...``, so a fleet of 340 units answered with 50 rows and no
way for a dispatcher to tell there were 290 more.

Three tests, because there are three different ways to regress this:

#. :func:`test_the_fleet_register_answers_with_an_envelope` walks the router's
   registered routes. A route quietly reverted to ``list[...]`` fails here.

#. :func:`test_the_total_is_the_yards_size_not_the_pages` drives the route with
   a stub repository that returns two rows and a total of 340. That is the
   assertion the shape test cannot make: a route can carry an envelope and
   still fill ``total`` with ``len(items)``, which reads as an honest page and
   is the exact lie this programme exists to remove.

#. :func:`test_the_taxonomy_never_claims_to_be_truncated` pins the deliberate
   asymmetry next door. ``GET /types/`` is enveloped for uniformity but is read
   whole by a repository method that takes no offset or limit, so its ``total``
   must always equal its ``items``. A future edit that pages it without paging
   the type picker on the equipment form would silently shorten a dropdown.

No database: the repository is stubbed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel

from app.modules.equipment import router as equipment_router

ENVELOPE_FIELDS = {"items", "total", "offset", "limit"}


def _get_route(path: str) -> Any:
    """The registered GET route for ``path``, or fail naming what was found."""
    for route in equipment_router.router.routes:
        if getattr(route, "path", None) == path and "GET" in getattr(route, "methods", set()):
            return route
    available = sorted(str(getattr(r, "path", "")) for r in equipment_router.router.routes)
    raise AssertionError(f"no GET route registered at {path}; router has {available}")


@pytest.mark.parametrize("path", ["/equipment/", "/types/"])
def test_the_fleet_register_answers_with_an_envelope(path: str) -> None:
    """A page envelope, not a bare array, on both lists in the module."""
    model = _get_route(path).response_model

    assert model is not None, f"{path} declares no response_model"
    # A bare ``list[EquipmentResponse]`` is not a class, so this is the check
    # that actually distinguishes the two shapes.
    assert isinstance(model, type) and issubclass(model, BaseModel), (
        f"{path} still answers with {model!r}, which cannot carry a total"
    )
    assert set(model.model_fields) >= ENVELOPE_FIELDS, (
        f"{path} answers with {model.__name__}, missing {sorted(ENVELOPE_FIELDS - set(model.model_fields))}"
    )


def _unit(code: str) -> SimpleNamespace:
    """The attributes ``EquipmentResponse.model_validate`` requires, and no more."""
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid.uuid4(),
        code=code,
        name="Crawler excavator",
        type_code="EXC",
        manufacturer=None,
        model=None,
        serial=None,
        year=None,
        ownership="owned",
        status="active",
        location_lat=None,
        location_lng=None,
        last_telemetry_at=None,
        purchase_date=None,
        purchase_value=None,
        useful_life_years=None,
        residual_value=None,
        notes=None,
        metadata_={},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_the_total_is_the_yards_size_not_the_pages() -> None:
    """``total`` is what the repository counted, never the length of the page."""
    captured: dict[str, Any] = {}

    class _StubRepo:
        async def list_(
            self,
            *,
            offset: int,
            limit: int,
            status: str | None = None,
            type_code: str | None = None,
            ownership: str | None = None,
        ) -> tuple[list[Any], int]:
            captured.update(
                offset=offset,
                limit=limit,
                status=status,
                type_code=type_code,
                ownership=ownership,
            )
            # Two units out of a yard of 340: the case the whole programme is
            # about. A route filling `total` from `len(items)` returns 2.
            return [_unit("EX-01"), _unit("EX-02")], 340

    result = await equipment_router.list_equipment(
        _perm=None,
        offset=0,
        limit=50,
        status_filter="active",
        type_filter="EXC",
        ownership="owned",
        service=SimpleNamespace(equipment_repo=_StubRepo()),  # type: ignore[arg-type]
    )

    # The page is echoed back as asked for, so a client can tell where it is.
    assert result.offset == 0
    assert result.limit == 50
    assert len(result.items) == 2

    # The point of the wave.
    assert result.total == 340
    assert result.total != len(result.items)

    # Every filter reaches the repository, which counts over the same query it
    # pages. A total counted without them would describe the whole yard while
    # the screen shows one type, which is worse than no total at all.
    assert captured["status"] == "active"
    assert captured["type_code"] == "EXC"
    assert captured["ownership"] == "owned"


@pytest.mark.asyncio
async def test_the_taxonomy_never_claims_to_be_truncated() -> None:
    """``/types/`` is read whole, so its total can never exceed its page."""
    types = [
        SimpleNamespace(
            id=uuid.uuid4(),
            code=code,
            name=code,
            category="earthmoving",
            default_hourly_rate=None,
            default_daily_rate=None,
            currency="EUR",
            metadata_={},
        )
        for code in ("EXC", "CRN", "LDR")
    ]

    async def _list_types() -> list[Any]:
        return types

    result = await equipment_router.list_types(
        _perm=None,
        service=SimpleNamespace(list_types=_list_types),  # type: ignore[arg-type]
    )

    assert len(result.items) == 3
    assert result.total == 3
    # `limit` is the size of what was returned, not a page size the caller
    # could ask past. Anything smaller would make the picker look truncated.
    assert result.limit == len(result.items)
    assert result.offset == 0
