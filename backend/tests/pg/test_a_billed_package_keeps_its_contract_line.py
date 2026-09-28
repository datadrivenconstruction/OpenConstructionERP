# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A work package billed on a locked GC claim keeps its schedule-of-values line, on PostgreSQL.

A pay-application line without its own ``contract_line_id`` bills under its
work package's line, so remapping the package moves that billed amount. Once
the claim the pay application is billed on has left draft/submitted the remap
is refused (409 ``claim_not_editable``). The unit test feeds the guard its
rows; this one runs the join that finds them against a real database.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException

from tests.pg.test_sub_rollup_include import _world  # type: ignore[import-not-found]

pytestmark = pytest.mark.asyncio


async def _billed(session: Any, *, claim_status: str, own_line: bool = False) -> dict[str, Any]:
    from sqlalchemy import update

    from app.modules.contracts.models import ContractLine, ProgressClaim
    from app.modules.subcontractors.models import PaymentApplication, PaymentApplicationLine

    world = await _world(session, suffix=uuid.uuid4().hex[:8])
    other = ContractLine(
        id=uuid.uuid4(),
        contract_id=world["contract"].id,
        code="03.20",
        description="Walls",
        total_value=Decimal("10000"),
    )
    session.add(other)
    await session.flush()
    await session.execute(
        update(PaymentApplication)
        .where(PaymentApplication.id == world["pay_app"].id)
        .values(progress_claim_id=world["claim"].id)
    )
    await session.execute(
        update(ProgressClaim).where(ProgressClaim.id == world["claim"].id).values(status=claim_status)
    )
    if own_line:
        await session.execute(
            update(PaymentApplicationLine)
            .where(PaymentApplicationLine.id == world["pa_line"].id)
            .values(contract_line_id=world["line"].id)
        )
    await session.flush()
    world["other"] = other
    return world


async def _package_line(session: Any, package_id: uuid.UUID) -> uuid.UUID | None:
    from sqlalchemy import select

    from app.modules.subcontractors.models import WorkPackage

    return (
        await session.execute(select(WorkPackage.contract_line_id).where(WorkPackage.id == package_id))
    ).scalar_one()


async def _remap(session: Any, world: dict[str, Any], target: uuid.UUID | None) -> None:
    from app.modules.subcontractors.schemas import WorkPackageUpdate
    from app.modules.subcontractors.service import SubcontractorService

    await SubcontractorService(session).update_work_package(
        world["package"].id, WorkPackageUpdate(contract_line_id=target)
    )


@pytest.mark.parametrize("claim_status", ["approved", "certified", "paid"])
async def test_a_package_billed_on_a_locked_claim_is_not_remapped(pg_session, claim_status: str) -> None:
    world = await _billed(pg_session, claim_status=claim_status)

    with pytest.raises(HTTPException) as exc:
        await _remap(pg_session, world, world["other"].id)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "claim_not_editable"
    assert await _package_line(pg_session, world["package"].id) == world["line"].id


async def test_a_package_billed_on_a_draft_claim_is_remapped(pg_session) -> None:
    world = await _billed(pg_session, claim_status="draft")

    await _remap(pg_session, world, world["other"].id)

    assert await _package_line(pg_session, world["package"].id) == world["other"].id


async def test_a_line_with_its_own_mapping_does_not_hold_the_package(pg_session) -> None:
    world = await _billed(pg_session, claim_status="approved", own_line=True)

    await _remap(pg_session, world, world["other"].id)

    assert await _package_line(pg_session, world["package"].id) == world["other"].id


async def test_echoing_the_stored_line_is_not_a_remap(pg_session) -> None:
    world = await _billed(pg_session, claim_status="paid")

    await _remap(pg_session, world, world["line"].id)

    assert await _package_line(pg_session, world["package"].id) == world["line"].id
