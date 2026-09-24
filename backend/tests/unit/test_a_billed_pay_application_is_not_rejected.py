"""Subcontract money after billing: a billed pay application stays, a waiverless release is flagged.

``exclude_payment_application`` refused to take a pay application out of a GC
claim once that claim was past editing, because the claim's make-up is then
part of the record. ``reject_payment_application`` did not look at the claim,
so the same pay application could be rejected under an approved claim, which
also reverses its retention accrual behind the claim's back. It now refuses the
same way, with the same ``claim_not_editable`` code.

``release_retention`` paid retention out with only a balance cap, although an
agreement can require lien waivers. The founder's call is to warn, not block:
the release goes ahead, and the ledger row, the event and the response say it
went ahead without a final waiver.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from tests.unit.test_subcontractors import _make_service, _Repo  # type: ignore[import-not-found]

pytestmark = pytest.mark.asyncio


class _Waivers(_Repo):
    async def list_for_payment_apps(self, ids: list[uuid.UUID]) -> list[Any]:
        wanted = set(ids)
        return [w for w in self.rows.values() if w.payment_application_id in wanted]


class _Reader:
    def __init__(self, claim: Any) -> None:
        self.claim = claim

    async def get_claim(self, _claim_id: uuid.UUID) -> Any:
        return self.claim


def _pay_app(svc: Any, *, status: str = "submitted", claim_id: uuid.UUID | None = None) -> SimpleNamespace:
    row = SimpleNamespace(
        id=uuid.uuid4(),
        agreement_id=uuid.uuid4(),
        application_number="PA-0001",
        status=status,
        progress_claim_id=claim_id,
        rejection_reason=None,
    )
    svc.payments.rows[row.id] = row
    return row


# ── C484: rejecting a billed pay application ────────────────────────────────


@pytest.mark.parametrize("claim_status", ["approved", "certified", "paid"])
async def test_a_pay_application_on_a_closed_claim_is_not_rejected(claim_status: str) -> None:
    svc = _make_service()
    pay_app = _pay_app(svc, claim_id=uuid.uuid4())
    reader = _Reader(SimpleNamespace(status=claim_status))
    with patch("app.modules.subcontractors.service.PrimeContractReader", lambda _s: reader):
        with pytest.raises(HTTPException) as exc:
            await svc.reject_payment_application(pay_app.id, reason="late")
    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "claim_not_editable"
    assert pay_app.status == "submitted"


@pytest.mark.parametrize("claim_status", ["draft", "submitted"])
async def test_a_pay_application_on_an_open_claim_can_still_be_rejected(claim_status: str) -> None:
    svc = _make_service()
    pay_app = _pay_app(svc, claim_id=uuid.uuid4())
    reader = _Reader(SimpleNamespace(status=claim_status))
    with patch("app.modules.subcontractors.service.PrimeContractReader", lambda _s: reader):
        await svc.reject_payment_application(pay_app.id, reason="late")
    assert pay_app.status == "rejected"


async def test_an_unbilled_pay_application_can_still_be_rejected() -> None:
    svc = _make_service()
    pay_app = _pay_app(svc)
    await svc.reject_payment_application(pay_app.id, reason="late")
    assert pay_app.status == "rejected"


# ── C469: releasing retention without a final lien waiver ───────────────────


async def _agreement_with_retention(svc: Any, *, requires_waiver: bool) -> tuple[Any, Any]:
    svc.lien_waivers = _Waivers()
    agreement = SimpleNamespace(id=uuid.uuid4(), requires_lien_waiver=requires_waiver)
    svc.agreements.rows[agreement.id] = agreement
    pay_app = SimpleNamespace(id=uuid.uuid4(), agreement_id=agreement.id)
    svc.payments.rows[pay_app.id] = pay_app
    svc.retention.rows[uuid.uuid4()] = SimpleNamespace(
        agreement_id=agreement.id, accrued_amount=Decimal("1000"), released_amount=Decimal("0")
    )
    return agreement, pay_app


def _waiver(svc: Any, payment_application_id: uuid.UUID, waiver_type: str) -> None:
    row = SimpleNamespace(id=uuid.uuid4(), payment_application_id=payment_application_id, waiver_type=waiver_type)
    svc.lien_waivers.rows[row.id] = row


async def _release(svc: Any, agreement_id: uuid.UUID) -> tuple[Any, dict[str, Any]]:
    with patch("app.modules.subcontractors.service.event_bus.publish_detached") as publish:
        entry = await svc.release_retention(agreement_id=agreement_id, amount=Decimal("400"), reason="PC")
    return entry, publish.call_args.args[1]


async def test_a_release_without_a_final_waiver_goes_ahead_and_says_so() -> None:
    svc = _make_service()
    agreement, pay_app = await _agreement_with_retention(svc, requires_waiver=True)
    _waiver(svc, pay_app.id, "unconditional_partial")

    entry, event = await _release(svc, agreement.id)

    assert entry.released_amount == Decimal("400")
    assert "final lien waiver" in entry.notes
    assert event["warnings"] == ["no_final_lien_waiver"]
    assert await svc.retention_release_warnings(agreement.id) == ["no_final_lien_waiver"]


async def test_a_final_waiver_on_another_agreement_does_not_count() -> None:
    svc = _make_service()
    agreement, _pay_app = await _agreement_with_retention(svc, requires_waiver=True)
    _waiver(svc, uuid.uuid4(), "unconditional_final")

    assert await svc.retention_release_warnings(agreement.id) == ["no_final_lien_waiver"]


@pytest.mark.parametrize("waiver_type", ["conditional_final", "unconditional_final"])
async def test_a_release_with_a_final_waiver_is_clean(waiver_type: str) -> None:
    svc = _make_service()
    agreement, pay_app = await _agreement_with_retention(svc, requires_waiver=True)
    _waiver(svc, pay_app.id, waiver_type)

    entry, event = await _release(svc, agreement.id)

    assert entry.notes is None
    assert event["warnings"] == []


async def test_an_agreement_without_the_waiver_rule_is_not_flagged() -> None:
    svc = _make_service()
    agreement, _pay_app = await _agreement_with_retention(svc, requires_waiver=False)

    entry, event = await _release(svc, agreement.id)

    assert entry.notes is None
    assert event["warnings"] == []


async def test_the_release_response_carries_the_warning_and_other_reads_do_not() -> None:
    from datetime import UTC, datetime

    from app.modules.subcontractors.schemas import RetentionLedgerEntryResponse

    now = datetime.now(UTC)
    entry = SimpleNamespace(
        id=uuid.uuid4(),
        agreement_id=uuid.uuid4(),
        payment_application_id=None,
        accrued_amount=Decimal("0"),
        released_amount=Decimal("400"),
        released_at=now,
        release_reason="PC",
        notes=None,
        created_at=now,
        updated_at=now,
    )
    plain = RetentionLedgerEntryResponse.model_validate(entry)
    flagged = plain.model_copy(update={"warnings": ["no_final_lien_waiver"]})

    assert plain.warnings == []
    assert flagged.model_dump()["warnings"] == ["no_final_lien_waiver"]
