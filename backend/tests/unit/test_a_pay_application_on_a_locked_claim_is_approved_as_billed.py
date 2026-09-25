# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Finance approval does not move what a locked GC claim already billed.

The GC claim rollup bills each pay application line's approved amount, and
the claim's retention follows the pay application's accrual. Rejecting or
excluding a pay application under a claim past editing was already refused,
but finance approval still rewrote the line amounts and the retention under
it, so an issued claim no longer added up to what it said it contained.

Once the claim is locked, approval that confirms the billed figures goes
through, and one that changes them is refused with 409 before anything is
written.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from tests.unit.test_subcontractors import _make_service  # type: ignore[import-not-found]

pytestmark = pytest.mark.asyncio


class _Reader:
    def __init__(self, claim_status: str) -> None:
        self.claim = SimpleNamespace(status=claim_status)

    async def get_claim(self, _claim_id: uuid.UUID) -> Any:
        return self.claim


async def _billed_pay_app(svc: Any) -> tuple[Any, Any]:
    """A 36,000 pay application at 5%, its line approved as claimed, billed on a GC claim."""
    from app.modules.subcontractors.schemas import (
        AgreementCreate,
        AgreementUpdate,
        CertificateCreate,
        PaymentApplicationCreate,
        PaymentApplicationLineCreate,
        SubcontractorCreate,
    )

    sub = await svc.create_subcontractor(SubcontractorCreate(legal_name="Suhi zid d.o.o."))
    for cert_type in ("insurance", "license"):
        await svc.record_certificate(
            CertificateCreate(
                subcontractor_id=sub.id, cert_type=cert_type, valid_until=date.today() + timedelta(days=180)
            )
        )
    agreement = await svc.create_agreement(
        AgreementCreate(
            subcontractor_id=sub.id,
            project_id=uuid.uuid4(),
            title="Drywall, block B",
            total_value=Decimal("120000"),
            currency="EUR",
            retention_percent=Decimal("5"),
        )
    )
    await svc.update_agreement(agreement.id, AgreementUpdate(status="active"))
    pa = await svc.submit_payment_application(
        PaymentApplicationCreate(
            agreement_id=agreement.id,
            gross_amount=Decimal("36000"),
            currency="EUR",
            lines=[
                PaymentApplicationLineCreate(
                    work_package_id=uuid.uuid4(),
                    claimed_amount=Decimal("36000"),
                    approved_amount=Decimal("36000"),
                )
            ],
        ),
        user_id="u1",
    )
    await svc.approve_payment_application_foreman(pa.id, user_id="foreman-1")
    svc.payments.rows[pa.id].progress_claim_id = uuid.uuid4()
    [line] = await svc.payment_lines.list_for_application(pa.id)
    return pa, line


@pytest.fixture
def quiet():
    with (
        patch("app.modules.subcontractors.service.event_bus.publish_detached"),
        patch("app.modules.subcontractors.finance_bridge.raise_payable_for_pay_app", AsyncMock()),
        patch("app.modules.subcontractors.finance_bridge.settle_payable", AsyncMock()),
    ):
        yield


@pytest.mark.parametrize("claim_status", ["approved", "certified", "paid"])
async def test_a_changed_amount_under_a_locked_claim_is_refused(quiet, claim_status: str) -> None:
    from app.modules.subcontractors.schemas import ApprovedLineAmount

    svc = _make_service()
    pa, line = await _billed_pay_app(svc)

    with patch("app.modules.subcontractors.service.PrimeContractReader", lambda _s: _Reader(claim_status)):
        with pytest.raises(HTTPException) as exc:
            await svc.approve_payment_application_finance(
                pa.id,
                user_id="finance-1",
                lines=[ApprovedLineAmount(line_id=line.id, approved_amount=Decimal("30000"))],
            )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "claim_not_editable"
    assert "no longer change" in exc.value.detail["message"]
    # Nothing was written: the line, the retention and the status are as billed.
    assert line.approved_amount == Decimal("36000")
    assert await svc.retention_balance(pa.agreement_id) == Decimal("1800")
    assert svc.payments.rows[pa.id].status == "foreman_approved"


@pytest.mark.parametrize("claim_status", ["approved", "certified", "paid"])
async def test_approving_as_billed_under_a_locked_claim_goes_through(quiet, claim_status: str) -> None:
    svc = _make_service()
    pa, line = await _billed_pay_app(svc)

    with patch("app.modules.subcontractors.service.PrimeContractReader", lambda _s: _Reader(claim_status)):
        approved = await svc.approve_payment_application_finance(pa.id, user_id="finance-1")

    assert approved.status == "finance_approved"
    assert (approved.approved_gross_amount, approved.approved_retention_amount, approved.approved_net_amount) == (
        Decimal("36000"),
        Decimal("1800"),
        Decimal("34200"),
    )
    assert line.approved_amount == Decimal("36000")


@pytest.mark.parametrize("claim_status", ["draft", "submitted"])
async def test_an_open_claim_still_takes_a_changed_amount(quiet, claim_status: str) -> None:
    from app.modules.subcontractors.schemas import ApprovedLineAmount

    svc = _make_service()
    pa, line = await _billed_pay_app(svc)

    with patch("app.modules.subcontractors.service.PrimeContractReader", lambda _s: _Reader(claim_status)):
        approved = await svc.approve_payment_application_finance(
            pa.id,
            user_id="finance-1",
            lines=[ApprovedLineAmount(line_id=line.id, approved_amount=Decimal("30000"))],
        )

    assert approved.approved_gross_amount == Decimal("30000")
    assert await svc.retention_balance(pa.agreement_id) == Decimal("1500")
