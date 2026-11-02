# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Subcontract changes: the checks, the state machine and the one-time agreement bump."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from app.modules.subcontractors import change_chain
from app.modules.subcontractors import validators as checks
from app.modules.subcontractors.change_chain import SubcontractChangeService
from app.modules.subcontractors.models import SubcontractAgreement, SubcontractChange


def test_back_to_back_without_owner_link_is_flagged() -> None:
    assert checks.check_change_owner_link({"code": "SCO-001", "back_to_back": True})[0].params == {"code": "SCO-001"}
    assert checks.check_change_owner_link({"code": "SCO-001", "back_to_back": False}) == []
    assert checks.check_change_owner_link({"back_to_back": True, "owner_change_id": str(uuid.uuid4())}) == []


def test_zero_amount_is_flagged() -> None:
    assert checks.check_change_amount_nonzero({"code": "SCO-002", "amount": "0"})
    assert checks.check_change_amount_nonzero({"code": "SCO-002", "amount": "-1500.00"}) == []


def test_sub_cost_above_owner_value_warns() -> None:
    linked = {"code": "SCO-003", "currency": "EUR", "owner_change_id": "x", "owner_change_value": "10000"}
    [finding] = checks.check_change_margin({**linked, "linked_sub_total": "12000"})
    assert finding.details == {"sub_total": "12000", "owner_value": "10000"}
    assert checks.check_change_margin({**linked, "linked_sub_total": "9000"}) == []


class _Session:
    """Just enough session for the approval path: get, add, flush."""

    def __init__(self, *rows: Any) -> None:
        self.rows = {row.id: row for row in rows}
        self.info: dict[str, Any] = {}

    async def get(self, _model: Any, key: uuid.UUID) -> Any:
        return self.rows.get(key)

    def add(self, row: Any) -> None:
        self.rows[row.id] = row

    async def flush(self) -> None:
        return None


@pytest.fixture
def quiet(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict]]:
    published: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        change_chain, "publish_after_commit", lambda _s, name, data, **_kw: published.append((name, data))
    )

    class _Finance:
        def __init__(self, _session: Any) -> None:
            pass

        async def sync_project_budget(self, project_id: uuid.UUID) -> None:
            published.append(("sync", {"project_id": project_id}))

    import app.modules.finance.service as finance_service

    monkeypatch.setattr(finance_service, "FinanceService", _Finance)
    return published


def _pair(amount: str = "2500.00") -> tuple[SubcontractAgreement, SubcontractChange]:
    agreement = SubcontractAgreement(
        id=uuid.uuid4(),
        subcontractor_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        title="Concrete",
        total_value=Decimal("100000.00"),
        currency="EUR",
        status="active",
    )
    change = SubcontractChange(
        id=uuid.uuid4(),
        agreement_id=agreement.id,
        project_id=agreement.project_id,
        code="SCO-001",
        title="Extra slab",
        amount=Decimal(amount),
        currency="EUR",
        status="submitted",
        back_to_back=True,
    )
    return agreement, change


@pytest.mark.asyncio
async def test_approval_moves_the_agreement_and_commitment_once(quiet: list[tuple[str, dict]]) -> None:
    agreement, change = _pair()
    svc = SubcontractChangeService(_Session(agreement, change))  # type: ignore[arg-type]

    await svc.transition(change.id, "approved", user_id="u1")
    await svc.transition(change.id, "approved", user_id="u1")  # replay

    assert agreement.total_value == Decimal("102500.00")
    assert change.applied_amount == Decimal("2500.00")
    assert [name for name, _ in quiet] == ["sync", "subcontractors.change.approved"]
    assert quiet[1][1]["agreement_total_value"] == "102500.00"


@pytest.mark.asyncio
async def test_an_omission_reduces_the_agreement(quiet: list[tuple[str, dict]]) -> None:
    agreement, change = _pair("-4000.00")
    await SubcontractChangeService(_Session(agreement, change)).transition(change.id, "approved")  # type: ignore[arg-type]
    assert agreement.total_value == Decimal("96000.00")


@pytest.mark.asyncio
async def test_a_draft_cannot_jump_to_approved_and_rejection_moves_nothing(quiet: list[tuple[str, dict]]) -> None:
    agreement, change = _pair()
    change.status = "draft"
    svc = SubcontractChangeService(_Session(agreement, change))  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as exc:
        await svc.transition(change.id, "approved")
    assert exc.value.status_code == 409

    await svc.transition(change.id, "submitted")
    await svc.transition(change.id, "rejected", note="price too high")
    assert agreement.total_value == Decimal("100000.00") and quiet == []
    assert SimpleNamespace(status=change.status).status == "rejected"
