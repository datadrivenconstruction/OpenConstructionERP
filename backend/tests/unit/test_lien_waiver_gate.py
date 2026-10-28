"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Lien-waiver payment gate (TOP-30 #9).

Two layers:

* pure-logic tests of :func:`lien_waiver_blocked` (no DB), covering the
  required / missing / short / covering / tax-form cases;
* a real-PostgreSQL test that a payment under an agreement which
  ``requires_lien_waiver`` cannot be finance-approved without a covering
  waiver, and can once one is on file.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.subcontractors.service import SubcontractorService, lien_waiver_blocked
from tests._pg import transactional_session


def _waiver(waiver_type: str, amount: str):
    """Lightweight stand-in carrying just the fields the helper reads."""
    from types import SimpleNamespace

    return SimpleNamespace(waiver_type=waiver_type, amount=Decimal(amount))


def test_not_required_is_never_blocked() -> None:
    result = lien_waiver_blocked(Decimal("1000"), [], required=False)
    assert result.blocked is False
    assert result.reasons == []


def test_required_but_missing_is_blocked() -> None:
    result = lien_waiver_blocked(Decimal("1000"), [], required=True)
    assert result.blocked is True
    assert result.reasons == ["missing_waiver"]


def test_tax_forms_do_not_satisfy_requirement() -> None:
    result = lien_waiver_blocked(Decimal("1000"), [_waiver("w9", "1000")], required=True)
    assert result.blocked is True
    assert result.reasons == ["missing_waiver"]


def test_short_waiver_is_amount_mismatch() -> None:
    result = lien_waiver_blocked(Decimal("1000"), [_waiver("conditional_partial", "600")], required=True)
    assert result.blocked is True
    assert result.reasons == ["waiver_amount_mismatch"]


def test_covering_waiver_releases_payment() -> None:
    # Uses the real ``_VALID_WAIVER_TYPES`` compound value the upload endpoint
    # actually stores, not a bare base - the gate must match production data.
    result = lien_waiver_blocked(Decimal("1000"), [_waiver("unconditional_final", "1000")], required=True)
    assert result.blocked is False
    assert result.reasons == []


def test_all_canonical_lien_types_release_payment() -> None:
    # Every non-tax waiver type the upload endpoint accepts must satisfy the
    # gate when it covers the amount. Guards against the base/compound mismatch.
    for wt in (
        "conditional_partial",
        "conditional_final",
        "unconditional_partial",
        "unconditional_final",
    ):
        result = lien_waiver_blocked(Decimal("1000"), [_waiver(wt, "1000")], required=True)
        assert result.blocked is False, wt


def test_w8_tax_form_does_not_satisfy_requirement() -> None:
    result = lien_waiver_blocked(Decimal("1000"), [_waiver("w8", "5000")], required=True)
    assert result.blocked is True
    assert result.reasons == ["missing_waiver"]


def test_largest_waiver_counts_when_several_present() -> None:
    waivers = [_waiver("conditional_partial", "400"), _waiver("unconditional_final", "1200")]
    result = lien_waiver_blocked(Decimal("1000"), waivers, required=True)
    assert result.blocked is False


# ── real-PostgreSQL gate ──────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _seed_payment(session: AsyncSession, *, requires_waiver: bool):
    from app.modules.subcontractors.models import (
        PaymentApplication,
        SubcontractAgreement,
        Subcontractor,
    )

    sub = Subcontractor(legal_name="Acme Trades")
    session.add(sub)
    await session.flush()
    agreement = SubcontractAgreement(
        subcontractor_id=sub.id,
        project_id=uuid.uuid4(),
        title="Drywall package",
        requires_lien_waiver=requires_waiver,
        status="active",
    )
    session.add(agreement)
    await session.flush()
    payment = PaymentApplication(
        agreement_id=agreement.id,
        application_number="PA-001",
        net_amount=Decimal("5000"),
        status="foreman_approved",
    )
    session.add(payment)
    await session.flush()
    return sub, payment


@pytest.mark.asyncio
async def test_finance_approval_blocked_without_waiver(session: AsyncSession) -> None:
    _sub, payment = await _seed_payment(session, requires_waiver=True)
    svc = SubcontractorService(session)

    with pytest.raises(HTTPException) as exc:
        await svc.approve_payment_application_finance(payment.id, user_id=str(uuid.uuid4()))
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "missing_waiver"


@pytest.mark.asyncio
async def test_finance_approval_allowed_with_covering_waiver(session: AsyncSession) -> None:
    from app.modules.subcontractors.models import LienWaiver

    sub, payment = await _seed_payment(session, requires_waiver=True)
    session.add(
        LienWaiver(
            subcontractor_id=sub.id,
            payment_application_id=payment.id,
            waiver_type="unconditional_final",
            document_url="uploads/waiver.pdf",
            amount=Decimal("5000"),
        )
    )
    await session.flush()

    svc = SubcontractorService(session)
    updated = await svc.approve_payment_application_finance(payment.id, user_id=str(uuid.uuid4()))
    assert updated.status == "finance_approved"


@pytest.mark.asyncio
async def test_finance_approval_unaffected_when_not_required(session: AsyncSession) -> None:
    _sub, payment = await _seed_payment(session, requires_waiver=False)
    svc = SubcontractorService(session)
    updated = await svc.approve_payment_application_finance(payment.id, user_id=str(uuid.uuid4()))
    assert updated.status == "finance_approved"
