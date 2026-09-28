"""Subcontract money billed on a locked GC claim is not moved by an edit.

``reject_payment_application`` and ``update_payment_application_line`` refuse
with ``claim_not_editable`` once the GC claim a pay application is billed on
has left draft/submitted. Two edits did not look at the claim:

* ``update_payment_application`` rewrote the period, gross, currency and the
  retention accrued on a pay application the locked claim already counted;
* ``update_work_package`` remapped the package's GC schedule-of-values line,
  and every billed line without its own mapping bills under the package's
  (``rollup.resolve_contract_line``), so the billed money moved with it.

Both now refuse the same way. While the claim is still draft or submitted,
and for lines that carry their own mapping, the edits go through.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from tests.unit.test_subcontractors import _make_service  # type: ignore[import-not-found]

pytestmark = pytest.mark.asyncio

LOCKED = ["approved", "certified", "paid"]
OPEN = ["draft", "submitted"]


class _Reader:
    def __init__(self, claim_status: str) -> None:
        self.claim = SimpleNamespace(status=claim_status)

    async def get_claim(self, _claim_id: uuid.UUID) -> Any:
        return self.claim


def _reading(claim_status: str) -> Any:
    reader = _Reader(claim_status)
    return patch("app.modules.subcontractors.service.PrimeContractReader", lambda _s: reader)


# ── update_payment_application ──────────────────────────────────────────────


def _billed_pay_app(svc: Any, *, claim_id: uuid.UUID | None) -> tuple[Any, Any]:
    agreement = SimpleNamespace(id=uuid.uuid4(), retention_percent=Decimal("10"))
    svc.agreements.rows[agreement.id] = agreement
    pay_app = SimpleNamespace(
        id=uuid.uuid4(),
        agreement_id=agreement.id,
        status="submitted",
        progress_claim_id=claim_id,
        gross_amount=Decimal("2000"),
        retention_amount=Decimal("200"),
        net_amount=Decimal("1800"),
        currency="USD",
    )
    svc.payments.rows[pay_app.id] = pay_app
    ledger = SimpleNamespace(
        id=uuid.uuid4(),
        payment_application_id=pay_app.id,
        accrued_amount=Decimal("200"),
        released_amount=Decimal("0"),
    )
    svc.retention.rows[ledger.id] = ledger
    return pay_app, ledger


@pytest.mark.parametrize("claim_status", LOCKED)
async def test_a_pay_application_on_a_locked_claim_keeps_what_it_billed(claim_status: str) -> None:
    from app.modules.subcontractors.schemas import PaymentApplicationUpdate

    svc = _make_service()
    pay_app, ledger = _billed_pay_app(svc, claim_id=uuid.uuid4())

    with _reading(claim_status), pytest.raises(HTTPException) as exc:
        await svc.update_payment_application(pay_app.id, PaymentApplicationUpdate(gross_amount=Decimal("3000")))

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "claim_not_editable"
    assert exc.value.detail["claim_status"] == claim_status
    assert (pay_app.gross_amount, pay_app.retention_amount) == (Decimal("2000"), Decimal("200"))
    assert ledger.accrued_amount == Decimal("200")


@pytest.mark.parametrize("claim_status", OPEN)
async def test_a_pay_application_on_an_open_claim_can_still_be_edited(claim_status: str) -> None:
    from app.modules.subcontractors.schemas import PaymentApplicationUpdate

    svc = _make_service()
    pay_app, ledger = _billed_pay_app(svc, claim_id=uuid.uuid4())

    with _reading(claim_status):
        await svc.update_payment_application(pay_app.id, PaymentApplicationUpdate(gross_amount=Decimal("3000")))

    assert (pay_app.gross_amount, pay_app.retention_amount) == (Decimal("3000"), Decimal("300.00"))
    assert ledger.accrued_amount == Decimal("300.00")


async def test_an_unbilled_pay_application_can_still_be_edited() -> None:
    from app.modules.subcontractors.schemas import PaymentApplicationUpdate

    svc = _make_service()
    pay_app, _ledger = _billed_pay_app(svc, claim_id=None)

    await svc.update_payment_application(pay_app.id, PaymentApplicationUpdate(gross_amount=Decimal("3000")))

    assert pay_app.gross_amount == Decimal("3000")


# ── update_work_package ─────────────────────────────────────────────────────


def _package(svc: Any, *, billed: list[tuple[uuid.UUID | None, uuid.UUID]]) -> Any:
    """A package mapped to one GC line, billed by lines given as (own contract line, claim id)."""
    package = SimpleNamespace(id=uuid.uuid4(), agreement_id=uuid.uuid4(), contract_line_id=uuid.uuid4())
    svc.work_packages.rows[package.id] = package
    svc.session.execute = AsyncMock(return_value=SimpleNamespace(all=lambda: list(billed)))
    return package


async def _remap(svc: Any, package: Any, target: uuid.UUID | None) -> Any:
    from app.modules.subcontractors.schemas import WorkPackageUpdate

    return await svc.update_work_package(package.id, WorkPackageUpdate(contract_line_id=target))


@pytest.mark.parametrize("claim_status", LOCKED)
@pytest.mark.parametrize("to_none", [False, True])
async def test_a_package_billed_on_a_locked_claim_keeps_its_line(claim_status: str, to_none: bool) -> None:
    svc = _make_service()
    package = _package(svc, billed=[(None, uuid.uuid4())])
    mapped = package.contract_line_id

    with _reading(claim_status), pytest.raises(HTTPException) as exc:
        await _remap(svc, package, None if to_none else uuid.uuid4())

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "claim_not_editable"
    assert package.contract_line_id == mapped


@pytest.mark.parametrize("claim_status", OPEN)
async def test_a_package_billed_on_an_open_claim_can_still_be_remapped(claim_status: str) -> None:
    svc = _make_service()
    package = _package(svc, billed=[(None, uuid.uuid4())])
    target = uuid.uuid4()

    with _reading(claim_status):
        await _remap(svc, package, target)

    assert package.contract_line_id == target


async def test_lines_with_their_own_mapping_do_not_hold_the_package() -> None:
    svc = _make_service()
    package = _package(svc, billed=[(uuid.uuid4(), uuid.uuid4())])
    target = uuid.uuid4()

    with _reading("approved"):
        await _remap(svc, package, target)

    assert package.contract_line_id == target


async def test_echoing_the_stored_line_is_not_a_remap() -> None:
    svc = _make_service()
    package = _package(svc, billed=[(None, uuid.uuid4())])
    mapped = package.contract_line_id

    with _reading("paid"):
        await _remap(svc, package, mapped)

    assert package.contract_line_id == mapped
    svc.session.execute.assert_not_awaited()
