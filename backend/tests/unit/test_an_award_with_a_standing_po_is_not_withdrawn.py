"""An award whose purchase order still stands is not withdrawn.

``delete_award`` steps an awarded bid package back to closed so it can be
re-awarded, which is deliberate. But procurement raises a PO from the award,
and the delete never looked at it, so a re-award to another bidder left the
first supplier's order standing next to the new one.

The delete now refuses while that PO stands and says to cancel it first. For
that advice to lead anywhere, procurement's reconciliation must not treat the
cancelled PO as the award's PO, or the re-award would find it and raise none.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.modules.bid_management.service import BidManagementService
from app.modules.procurement.events import _find_existing_po

pytestmark = pytest.mark.asyncio


def _po(status: str, **metadata: str) -> SimpleNamespace:
    return SimpleNamespace(po_number="PO-0007", status=status, metadata_=dict(metadata))


class _Session:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.flush = AsyncMock()

    async def execute(self, _stmt: Any) -> Any:
        rows = self.rows
        return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: rows))


def _service(pos: list[Any]) -> tuple[BidManagementService, SimpleNamespace]:
    package = SimpleNamespace(id=uuid.uuid4(), project_id=uuid.uuid4(), status="awarded", awarded_at="x")
    award = SimpleNamespace(id=uuid.uuid4(), package_id=package.id)
    for po in pos:
        po.metadata_.setdefault("bid_package_id", str(package.id))
    svc = BidManagementService.__new__(BidManagementService)
    svc.session = _Session(pos)
    svc.award_repo = MagicMock()
    svc.award_repo.get_by_id = AsyncMock(return_value=award)
    svc.award_repo.delete = AsyncMock()
    svc.package_repo = MagicMock()
    svc.package_repo.get_by_id = AsyncMock(return_value=package)
    return svc, package


@pytest.mark.parametrize(
    ("po_status", "advice"), [("draft", "Cancel it"), ("issued", "Cancel it"), ("completed", "kept")]
)
async def test_an_award_with_a_standing_po_is_not_withdrawn(po_status: str, advice: str) -> None:
    svc, package = _service([_po(po_status)])

    with pytest.raises(HTTPException) as exc:
        await svc.delete_award(uuid.uuid4())

    assert exc.value.status_code == 409
    assert "PO-0007" in exc.value.detail
    assert advice in exc.value.detail
    svc.award_repo.delete.assert_not_called()
    assert package.status == "awarded"


async def test_an_award_whose_po_was_cancelled_is_withdrawn() -> None:
    svc, package = _service([_po("cancelled")])

    with patch("app.modules.bid_management.service.event_bus"):
        await svc.delete_award(uuid.uuid4())

    svc.award_repo.delete.assert_called_once()
    assert package.status == "closed"


async def test_a_po_of_another_package_does_not_hold_the_award() -> None:
    svc, package = _service([_po("issued", bid_package_id=str(uuid.uuid4()))])

    with patch("app.modules.bid_management.service.event_bus"):
        await svc.delete_award(uuid.uuid4())

    assert package.status == "closed"


async def test_reconciliation_does_not_count_a_cancelled_po() -> None:
    package_id = str(uuid.uuid4())
    keys = {"bid_package_id": package_id, "tender_package_id": None}

    cancelled_only = _Session([_po("cancelled", bid_package_id=package_id)])
    assert await _find_existing_po(cancelled_only, uuid.uuid4(), keys=keys) is None  # type: ignore[arg-type]

    live = _po("draft", bid_package_id=package_id)
    both = _Session([_po("cancelled", bid_package_id=package_id), live])
    assert await _find_existing_po(both, uuid.uuid4(), keys=keys) is live  # type: ignore[arg-type]
