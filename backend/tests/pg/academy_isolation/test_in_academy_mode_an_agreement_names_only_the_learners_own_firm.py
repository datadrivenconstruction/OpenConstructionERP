# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode a subcontract agreement names only the learner's own firm.

``POST /agreements/`` checks that the caller can open the project, then takes
the subcontractor id from the body and only checks that it exists. The
subcontractor directory is per learner in academy mode (item I), so this was
a way to draw up an agreement, and from it payment applications, with another
learner's firm, and to learn from the answer whether an id was theirs. In
academy mode another learner's subcontractor reads like a missing one (404
``Subcontractor not found``). An admin is not limited, and nothing changes with
the flag off.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.modules.subcontractors.models import SubcontractAgreement, Subcontractor
from app.modules.subcontractors.schemas import AgreementCreate
from app.modules.subcontractors.service import SubcontractorService
from tests.pg.academy_isolation.rows import make_project, make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]


async def _setup(session, *, actor_role: str = "manager"):
    alice = await make_user(session, name="Alice", role=actor_role)
    bob = await make_user(session, name="Bob")
    project = await make_project(session, alice)
    mine = Subcontractor(legal_name="Alice Drywall", created_by=str(alice.id))
    theirs = Subcontractor(legal_name="Bob Drywall", created_by=str(bob.id))
    session.add_all([mine, theirs])
    await session.flush()
    return alice, project, mine, theirs


def _draft(project, sub) -> AgreementCreate:
    return AgreementCreate(subcontractor_id=sub.id, project_id=project.id, title="Drywall package", currency="EUR")


async def _count(session, project) -> int:
    stmt = select(func.count(SubcontractAgreement.id)).where(SubcontractAgreement.project_id == project.id)
    return (await session.execute(stmt)).scalar_one()


async def test_academy_on_an_agreement_cannot_name_another_learners_firm(pg_session, academy, events) -> None:
    academy(True)
    alice, project, _mine, theirs = await _setup(pg_session)
    svc = SubcontractorService(pg_session)

    with pytest.raises(HTTPException) as foreign:
        await svc.create_agreement(_draft(project, theirs), user_id=str(alice.id))
    missing = Subcontractor(legal_name="Nobody")
    missing.id = uuid.uuid4()
    with pytest.raises(HTTPException) as unknown:
        await svc.create_agreement(_draft(project, missing), user_id=str(alice.id))

    assert (foreign.value.status_code, foreign.value.detail) == (unknown.value.status_code, unknown.value.detail)
    assert foreign.value.status_code == 404
    assert await _count(pg_session, project) == 0


async def test_academy_on_an_agreement_with_the_learners_own_firm_works(pg_session, academy, events) -> None:
    academy(True)
    alice, project, mine, _theirs = await _setup(pg_session)

    agreement = await SubcontractorService(pg_session).create_agreement(_draft(project, mine), user_id=str(alice.id))

    assert agreement.subcontractor_id == mine.id


async def test_academy_on_an_admin_is_not_limited(pg_session, academy, events) -> None:
    academy(True)
    admin, project, _mine, theirs = await _setup(pg_session, actor_role="admin")

    agreement = await SubcontractorService(pg_session).create_agreement(_draft(project, theirs), user_id=str(admin.id))

    assert agreement.subcontractor_id == theirs.id


async def test_academy_off_unchanged(pg_session, academy, events) -> None:
    academy(False)
    alice, project, _mine, theirs = await _setup(pg_session)

    agreement = await SubcontractorService(pg_session).create_agreement(_draft(project, theirs), user_id=str(alice.id))

    assert agreement.subcontractor_id == theirs.id
