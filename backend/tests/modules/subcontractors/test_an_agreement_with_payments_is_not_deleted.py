# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The payment record under a subcontract cannot be deleted from one level down.

``delete_subcontractor`` refuses a firm that holds an agreement, because the
delete cascades and would take the payment applications and retention ledger
behind that agreement with it. The agreement itself had no such check, so the
same records went with one call to ``delete_agreement``: every payment
application (paid ones included), their lines, and the retention accrued and
released. A work package goes the same way one level further down: its delete
cascades to every payment application line billed against it, which changes
what an approved pay application, and the GC claim that bills it, says it
contained.

Stub repositories, as in ``tests/unit/test_commercial_delete_guards.py``: the
defect is a missing decision, so the tests observe whether the delete is
refused and whether the repository was reached.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.subcontractors.service import SubcontractorService


class _Rows:
    """A repository over a dict, recording what it was asked to delete."""

    def __init__(self, rows: list[Any] | None = None) -> None:
        self.rows = {row.id: row for row in rows or []}
        self.deleted: list[uuid.UUID] = []

    async def get_by_id(self, entity_id: uuid.UUID) -> Any:
        return self.rows.get(entity_id)

    async def delete(self, entity_id: uuid.UUID) -> None:
        self.deleted.append(entity_id)
        self.rows.pop(entity_id, None)

    async def list_for_agreement(self, agreement_id: uuid.UUID, **_kw: Any) -> list[Any]:
        return [row for row in self.rows.values() if getattr(row, "agreement_id", None) == agreement_id]

    async def list_for_subcontractor(self, sub_id: uuid.UUID, **_kw: Any) -> list[Any]:
        return [row for row in self.rows.values() if getattr(row, "subcontractor_id", None) == sub_id]

    async def count_for_work_package(self, work_package_id: uuid.UUID) -> int:
        return sum(1 for row in self.rows.values() if getattr(row, "work_package_id", None) == work_package_id)


def _service(
    *,
    agreements: list[Any] = (),  # type: ignore[assignment]
    payments: list[Any] = (),  # type: ignore[assignment]
    retention: list[Any] = (),  # type: ignore[assignment]
    work_packages: list[Any] = (),  # type: ignore[assignment]
    payment_lines: list[Any] = (),  # type: ignore[assignment]
) -> SubcontractorService:
    service = SubcontractorService.__new__(SubcontractorService)
    service.session = SimpleNamespace()
    service.agreements = _Rows(list(agreements))
    service.payments = _Rows(list(payments))
    service.retention = _Rows(list(retention))
    service.work_packages = _Rows(list(work_packages))
    service.payment_lines = _Rows(list(payment_lines))
    service.subs = _Rows([SimpleNamespace(id=uuid.uuid4())])
    return service


def _agreement(status: str = "active") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), subcontractor_id=uuid.uuid4(), status=status, project_id=uuid.uuid4())


def _payment(agreement: SimpleNamespace, status: str = "paid") -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), agreement_id=agreement.id, status=status)


# ── The guard that already held ─────────────────────────────────────────────


async def test_control_a_subcontractor_holding_an_agreement_is_not_deleted() -> None:
    agreement = _agreement()
    service = _service(agreements=[agreement])

    async def _get(_sub_id: uuid.UUID) -> Any:
        return SimpleNamespace(id=agreement.subcontractor_id)

    service.get_subcontractor = _get  # type: ignore[method-assign]
    with pytest.raises(HTTPException) as exc:
        await service.delete_subcontractor(agreement.subcontractor_id)
    assert exc.value.status_code == 409


# ── Agreement ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("payment_status", ["submitted", "finance_approved", "paid", "rejected"])
async def test_an_agreement_with_a_payment_application_is_not_deleted(payment_status: str) -> None:
    agreement = _agreement()
    service = _service(agreements=[agreement], payments=[_payment(agreement, payment_status)])
    with pytest.raises(HTTPException) as exc:
        await service.delete_agreement(agreement.id)
    assert exc.value.status_code == 409
    assert service.agreements.deleted == []


async def test_an_agreement_with_retention_on_its_ledger_is_not_deleted() -> None:
    agreement = _agreement()
    entry = SimpleNamespace(id=uuid.uuid4(), agreement_id=agreement.id, payment_application_id=None)
    service = _service(agreements=[agreement], retention=[entry])
    with pytest.raises(HTTPException) as exc:
        await service.delete_agreement(agreement.id)
    assert exc.value.status_code == 409
    assert service.agreements.deleted == []


async def test_an_agreement_nothing_was_paid_under_can_still_be_deleted() -> None:
    agreement = _agreement(status="draft")
    service = _service(agreements=[agreement])
    await service.delete_agreement(agreement.id)
    assert service.agreements.deleted == [agreement.id]


async def test_deleting_an_agreement_that_is_not_there_stays_a_no_op() -> None:
    service = _service()
    await service.delete_agreement(uuid.uuid4())
    assert service.agreements.deleted == []


# ── Work package ────────────────────────────────────────────────────────────


async def test_a_work_package_billed_on_a_payment_application_is_not_deleted() -> None:
    agreement = _agreement()
    package = SimpleNamespace(id=uuid.uuid4(), agreement_id=agreement.id)
    line = SimpleNamespace(id=uuid.uuid4(), work_package_id=package.id, payment_application_id=uuid.uuid4())
    service = _service(agreements=[agreement], work_packages=[package], payment_lines=[line])
    with pytest.raises(HTTPException) as exc:
        await service.delete_work_package(package.id)
    assert exc.value.status_code == 409
    assert service.work_packages.deleted == []


async def test_a_work_package_nothing_was_billed_against_can_still_be_deleted() -> None:
    agreement = _agreement()
    package = SimpleNamespace(id=uuid.uuid4(), agreement_id=agreement.id)
    service = _service(agreements=[agreement], work_packages=[package])
    await service.delete_work_package(package.id)
    assert service.work_packages.deleted == [package.id]
