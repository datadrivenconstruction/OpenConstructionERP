# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A tender package reaches ``awarded`` only through ``apply_winner``.

``apply_winner`` names the winning bid, writes its rates into the BOQ, rejects
the other bids and announces the award. ``PATCH /packages/{id}`` could set the
status to ``awarded`` directly, from ``evaluating``, which did none of that:
the package read as awarded with no winner and no rates in the bill, and
``apply_winner`` then refused it for good because it only awards collecting or
evaluating packages. It also skipped the ``tendering.award`` permission.

Now a PATCH to ``awarded`` from a package that could still be awarded is
refused with a 409 that points at apply-winner, before anything is written.
Every refusal has a control: the other exits from evaluation still work, an
already awarded package can be sent its own status back, and the transitions
the lifecycle never allowed keep their own answer. The checks read the stored
package from the repository's own rows.

Run:
    cd backend
    python -m pytest tests/modules/tendering/test_a_package_is_awarded_only_by_applying_the_winner.py -v
"""

from __future__ import annotations

import copy
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.tendering.schemas import PackageCreate, PackageUpdate
from app.modules.tendering.service import TenderingService

PROJECT_ID = uuid.uuid4()

_APPLY_WINNER_DETAIL = (
    "A package is awarded by applying the winning bid, which records the winner "
    "and writes its rates into the BOQ. Use apply-winner instead of changing the status."
)


class _StubRepo:
    """In-memory rows for the repository calls ``update_package`` makes."""

    def __init__(self) -> None:
        self.packages: dict[uuid.UUID, Any] = {}

    async def create_package(self, package: Any) -> Any:
        package.id = uuid.uuid4()
        package.created_at = package.updated_at = datetime.now(UTC)
        package.bids = []
        self.packages[package.id] = package
        return package

    async def get_package_by_id(self, package_id: uuid.UUID) -> Any:
        return self.packages.get(package_id)

    async def update_package_fields(self, package_id: uuid.UUID, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self.packages[package_id], key, value)


def _service() -> TenderingService:
    svc = TenderingService.__new__(TenderingService)
    svc.session = SimpleNamespace()
    svc.repo = _StubRepo()
    return svc


async def _package_in(svc: TenderingService, package_status: str) -> Any:
    package = await svc.create_package(PackageCreate(project_id=PROJECT_ID, name="Concrete works"))
    package.status = package_status
    return package


def _stored(svc: TenderingService, package_id: uuid.UUID) -> tuple[Any, ...]:
    """(status, name, metadata) as the repository holds them."""
    row = svc.repo.packages[package_id]
    return row.status, row.name, copy.deepcopy(row.metadata_)


@pytest.mark.asyncio
@pytest.mark.parametrize("package_status", ["collecting", "evaluating"])
async def test_a_patch_to_awarded_is_refused_and_writes_nothing(package_status: str) -> None:
    svc = _service()
    package = await _package_in(svc, package_status)
    before = _stored(svc, package.id)

    with pytest.raises(HTTPException) as exc:
        await svc.update_package(package.id, PackageUpdate(status="awarded", name="Concrete works, awarded"))

    assert exc.value.status_code == 409
    assert exc.value.detail == _APPLY_WINNER_DETAIL
    assert _stored(svc, package.id) == before


@pytest.mark.asyncio
async def test_evaluation_can_still_be_closed() -> None:
    """The control: the other exit from evaluation is untouched."""
    svc = _service()
    package = await _package_in(svc, "evaluating")

    await svc.update_package(package.id, PackageUpdate(status="closed"))

    status, _name, meta = _stored(svc, package.id)
    assert status == "closed"
    assert "closed_at" in meta
    assert "awarded_at" not in meta


@pytest.mark.asyncio
async def test_an_awarded_package_can_be_sent_its_own_status() -> None:
    """A client that echoes ``awarded`` back while renaming is not refused."""
    svc = _service()
    package = await _package_in(svc, "awarded")

    await svc.update_package(package.id, PackageUpdate(status="awarded", name="Concrete works, lot 1"))

    assert _stored(svc, package.id)[:2] == ("awarded", "Concrete works, lot 1")


@pytest.mark.asyncio
@pytest.mark.parametrize("package_status", ["draft", "issued", "closed"])
async def test_a_package_that_could_never_be_awarded_keeps_its_own_answer(package_status: str) -> None:
    """apply_winner refuses these too, so pointing at it would mislead."""
    svc = _service()
    package = await _package_in(svc, package_status)
    before = _stored(svc, package.id)

    with pytest.raises(HTTPException) as exc:
        await svc.update_package(package.id, PackageUpdate(status="awarded"))

    assert exc.value.status_code == 409
    assert exc.value.detail == f"Illegal package transition: {package_status!r} → 'awarded'"
    assert _stored(svc, package.id) == before
