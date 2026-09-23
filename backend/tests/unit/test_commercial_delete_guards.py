# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
#
# Two delete paths took the commercial record of a live job away in one call.
#
# ``ContractsService.delete_contract`` had no lifecycle check at all, so a
# signed, running contract could be deleted along with everything cascading off
# it: variations, progress claims, payment certificates, retention. Change
# orders already guard this correctly and are the template.
#
# ``SubcontractorService.delete_subcontractor`` had the same shape. Deleting a
# firm that is on a job took its subcontract agreements with it, and with them
# the payment applications, retention ledger and ratings hanging off those
# agreements: the record of work somebody actually performed and was paid for.
#
# Both are exercised against stub repositories. The defect is a missing decision
# rather than a query, so the test only has to observe whether the delete is
# refused and whether the repository was reached at all.

from __future__ import annotations

import uuid
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.contracts.service import ContractsService
from app.modules.subcontractors.service import SubcontractorService


class _StubSession:
    """Stands in for AsyncSession; the repositories built on it are replaced."""

    async def rollback(self) -> None:  # pragma: no cover - not exercised here
        return None


class _RecordingRepo:
    """Records whether the destructive call was actually reached."""

    def __init__(self) -> None:
        self.deleted: list[uuid.UUID] = []

    async def delete(self, entity_id: uuid.UUID) -> None:
        self.deleted.append(entity_id)


class _Contract:
    def __init__(self, status: str) -> None:
        self.id = uuid.uuid4()
        self.status = status
        self.code = "C-001"


class _NoLines:
    """A draft with no schedule lines, so nothing on it can have been billed."""

    async def list_for_contract(self, _contract_id: uuid.UUID) -> list[Any]:
        return []


class _NothingBilled:
    async def claims_billing_lines(self, _line_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
        return {}


def _contracts_service(contract: _Contract) -> tuple[ContractsService, _RecordingRepo]:
    service = ContractsService.__new__(ContractsService)
    service.session = _StubSession()
    repo = _RecordingRepo()
    service.contract_repo = repo
    # A draft's delete also asks whether a claim has billed on its lines; the
    # PG test for that lives in tests/pg, this file only pins the status rule.
    service.line_repo = _NoLines()
    service.claim_line_repo = _NothingBilled()

    async def _get(_contract_id: uuid.UUID) -> _Contract:
        return contract

    service.get_contract = _get  # type: ignore[method-assign]
    return service, repo


@pytest.mark.parametrize("live_status", ["active", "suspended", "completed", "terminated"])
@pytest.mark.asyncio
async def test_a_contract_that_left_draft_cannot_be_deleted(live_status: str) -> None:
    contract = _Contract(live_status)
    service, repo = _contracts_service(contract)

    with pytest.raises(HTTPException) as raised:
        await service.delete_contract(contract.id)

    assert raised.value.status_code == 400
    assert live_status in str(raised.value.detail), "the message should name the actual status"
    assert repo.deleted == [], "the delete must not have reached the repository"


@pytest.mark.asyncio
async def test_a_draft_contract_is_still_deletable() -> None:
    """The guard must not turn into a blanket refusal."""
    contract = _Contract("draft")
    service, repo = _contracts_service(contract)

    await service.delete_contract(contract.id)

    assert repo.deleted == [contract.id]


class _AgreementsRepo:
    def __init__(self, count: int) -> None:
        self._agreements = [object() for _ in range(count)]

    async def list_for_subcontractor(self, _sub_id: uuid.UUID, **_kw: Any) -> list[Any]:
        return self._agreements


def _sub_service(agreement_count: int) -> tuple[SubcontractorService, _RecordingRepo]:
    service = SubcontractorService.__new__(SubcontractorService)
    service.session = _StubSession()
    repo = _RecordingRepo()
    service.subs = repo
    service.agreements = _AgreementsRepo(agreement_count)

    async def _get(_sub_id: uuid.UUID) -> object:
        return object()

    service.get_subcontractor = _get  # type: ignore[method-assign]
    return service, repo


@pytest.mark.asyncio
async def test_a_subcontractor_holding_agreements_cannot_be_deleted() -> None:
    service, repo = _sub_service(agreement_count=3)

    with pytest.raises(HTTPException) as raised:
        await service.delete_subcontractor(uuid.uuid4())

    assert raised.value.status_code == 409
    assert "3" in str(raised.value.detail), "the message should say how many are in the way"
    assert repo.deleted == []


@pytest.mark.asyncio
async def test_a_subcontractor_with_no_agreements_is_still_deletable() -> None:
    """Records created in error must stay removable."""
    service, repo = _sub_service(agreement_count=0)
    sub_id = uuid.uuid4()

    await service.delete_subcontractor(sub_id)

    assert repo.deleted == [sub_id]
