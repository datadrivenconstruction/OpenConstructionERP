# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for PO retainage logic (Gap F).

Two layers:

* Pure-logic tests of the ``PurchaseOrder.retainage_amount`` /
  ``retainage_held`` computed methods and the schema validation. These need
  no database and run as fast assertions over plain model instances.
* Service-level workflow tests of ``ProcurementService.release_po_retainage``
  driven through stub repositories, mirroring the existing
  ``test_procurement.py`` stub style so the FSM/validation branches are
  exercised without a DB round-trip.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.modules.procurement.models import PORetainageRelease, PurchaseOrder
from app.modules.procurement.schemas import (
    PORetainageReleaseRequest,
    PORetainageReleaseResponse,
)
from app.modules.procurement.service import ProcurementService

# ── Pure-logic: computed retainage on the ORM model ────────────────────────


def _po(amount_total: str = "0", pct: str = "0", released: str = "0") -> PurchaseOrder:
    """Build a detached PurchaseOrder instance for math assertions."""
    return PurchaseOrder(
        project_id=uuid.uuid4(),
        po_number="PO-001",
        amount_total=amount_total,
        retention_percent=Decimal(pct),
        retainage_released_amount=released,
    )


def test_retainage_amount_basic() -> None:
    po = _po(amount_total="100000.00", pct="5.00")
    assert po.retainage_amount() == Decimal("5000.0000")


def test_retainage_amount_zero_percent() -> None:
    po = _po(amount_total="100000.00", pct="0.00")
    assert po.retainage_amount() == Decimal("0.0000")


def test_retainage_amount_handles_garbage_total() -> None:
    po = _po(amount_total="not-a-number", pct="5.00")
    # Bad amount_total must default to 0, never raise.
    assert po.retainage_amount() == Decimal("0.0000")


def test_retainage_held_nets_off_released() -> None:
    po = _po(amount_total="100000.00", pct="5.00", released="2000")
    assert po.retainage_amount() == Decimal("5000.0000")
    assert po.retainage_held() == Decimal("3000.0000")


def test_retainage_held_floored_at_zero() -> None:
    # Over-release (data drift) must never produce a negative held balance.
    po = _po(amount_total="100000.00", pct="5.00", released="9999")
    assert po.retainage_held() == Decimal("0")


def test_retainage_held_full_release() -> None:
    po = _po(amount_total="100000.00", pct="5.00", released="5000")
    assert po.retainage_held() == Decimal("0.0000")


def test_retainage_amount_fractional_percent() -> None:
    po = _po(amount_total="12345.67", pct="2.50")
    # 12345.67 * 2.5 / 100 = 308.64175 -> quantized to 4dp
    assert po.retainage_amount() == Decimal("308.6418")


# ── Schema validation ───────────────────────────────────────────────────────


def test_release_request_rejects_zero() -> None:
    with pytest.raises(ValueError):
        PORetainageReleaseRequest(amount="0")


def test_release_request_rejects_negative() -> None:
    with pytest.raises(ValueError):
        PORetainageReleaseRequest(amount="-100")


def test_release_request_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        PORetainageReleaseRequest(amount="abc")


def test_release_request_accepts_positive() -> None:
    req = PORetainageReleaseRequest(amount="1500.00", reason="Milestone 1 signed off")
    assert req.amount == "1500.00"
    assert req.reason == "Milestone 1 signed off"


def test_release_response_coerces_decimal_amount() -> None:
    rec = PORetainageRelease(
        po_id=uuid.uuid4(),
        release_date="2026-06-04T00:00:00+00:00",
        release_amount=Decimal("1500.0000"),
        release_reason=None,
    )
    # ORM-side fields the Base mixin would populate on a real flush.
    rec.id = uuid.uuid4()
    from datetime import UTC, datetime

    rec.created_at = datetime.now(UTC)
    resp = PORetainageReleaseResponse.model_validate(rec)
    assert resp.release_amount == "1500.0000"
    assert resp.po_id == rec.po_id


# ── Service workflow (stub repositories) ──────────────────────────────────


class _StubPORepo:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}
        self.lock_calls: list[uuid.UUID] = []

    async def get(self, po_id: uuid.UUID) -> Any:
        return self.rows.get(po_id)

    async def update(self, po_id: uuid.UUID, **fields: Any) -> None:
        po = self.rows.get(po_id)
        if po is not None:
            for k, v in fields.items():
                setattr(po, k, v)

    async def lock_for_update(self, po_id: uuid.UUID) -> None:
        # No-op in the stub (no real DB row to lock); record the call so a test
        # can assert the release path takes the lock before the cap check.
        self.lock_calls.append(po_id)


class _StubRetainageRepo:
    def __init__(self) -> None:
        self.created: list[PORetainageRelease] = []

    async def create(self, record: PORetainageRelease) -> PORetainageRelease:
        record.id = uuid.uuid4()
        self.created.append(record)
        return record

    async def list_for_po(
        self,
        po_id: uuid.UUID,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[PORetainageRelease], int]:
        rows = [r for r in self.created if r.po_id == po_id]
        return rows[offset : offset + limit], len(rows)


def _service_with_po(po: PurchaseOrder) -> ProcurementService:
    svc = ProcurementService.__new__(ProcurementService)
    svc.session = SimpleNamespace()
    svc.po_repo = _StubPORepo()
    svc.po_repo.rows[po.id] = po
    svc.retainage_repo = _StubRetainageRepo()
    return svc


def _issued_po(
    *,
    amount_total: str = "100000.00",
    pct: str = "5.00",
    released: str = "0",
    status: str = "issued",
) -> PurchaseOrder:
    po = PurchaseOrder(
        project_id=uuid.uuid4(),
        po_number="PO-001",
        amount_total=amount_total,
        retention_percent=Decimal(pct),
        retainage_released_amount=released,
        status=status,
        currency_code="EUR",
    )
    po.id = uuid.uuid4()
    return po


@pytest.mark.asyncio
async def test_release_happy_path() -> None:
    po = _issued_po()  # held = 5000
    svc = _service_with_po(po)
    rec = await svc.release_po_retainage(po.id, Decimal("1000"), reason="Phase 1")
    assert rec.release_amount == Decimal("1000")
    assert rec.release_reason == "Phase 1"
    # Released total updated on the PO.
    assert po.retainage_released_amount == "1000"
    assert po.retainage_held() == Decimal("4000.0000")
    assert len(svc.retainage_repo.created) == 1


@pytest.mark.asyncio
async def test_release_404_when_po_missing() -> None:
    from fastapi import HTTPException

    svc = ProcurementService.__new__(ProcurementService)
    svc.session = SimpleNamespace()
    svc.po_repo = _StubPORepo()
    svc.retainage_repo = _StubRetainageRepo()
    with pytest.raises(HTTPException) as exc:
        await svc.release_po_retainage(uuid.uuid4(), Decimal("100"))
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_release_409_when_draft() -> None:
    from fastapi import HTTPException

    po = _issued_po(status="draft")
    svc = _service_with_po(po)
    with pytest.raises(HTTPException) as exc:
        await svc.release_po_retainage(po.id, Decimal("100"))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_release_409_when_cancelled() -> None:
    from fastapi import HTTPException

    po = _issued_po(status="cancelled")
    svc = _service_with_po(po)
    with pytest.raises(HTTPException) as exc:
        await svc.release_po_retainage(po.id, Decimal("100"))
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_release_400_when_exceeds_held() -> None:
    from fastapi import HTTPException

    po = _issued_po()  # held = 5000
    svc = _service_with_po(po)
    with pytest.raises(HTTPException) as exc:
        await svc.release_po_retainage(po.id, Decimal("5001"))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_release_400_when_non_positive() -> None:
    from fastapi import HTTPException

    po = _issued_po()
    svc = _service_with_po(po)
    with pytest.raises(HTTPException) as exc:
        await svc.release_po_retainage(po.id, Decimal("0"))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_release_sequence_drains_held_to_zero() -> None:
    po = _issued_po()  # held = 5000
    svc = _service_with_po(po)
    await svc.release_po_retainage(po.id, Decimal("2000"))
    assert po.retainage_held() == Decimal("3000.0000")
    await svc.release_po_retainage(po.id, Decimal("3000"))
    assert po.retainage_held() == Decimal("0.0000")
    assert po.retainage_released_amount == "5000"
    assert len(svc.retainage_repo.created) == 2

    # A third release of any positive amount now fails (nothing left to give).
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await svc.release_po_retainage(po.id, Decimal("1"))
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_release_completed_po_allowed() -> None:
    po = _issued_po(status="completed")  # held = 5000
    svc = _service_with_po(po)
    rec = await svc.release_po_retainage(po.id, Decimal("5000"))
    assert rec.release_amount == Decimal("5000")
    assert po.retainage_held() == Decimal("0.0000")
