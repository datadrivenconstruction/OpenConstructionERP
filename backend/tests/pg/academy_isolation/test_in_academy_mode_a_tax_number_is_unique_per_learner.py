# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: in academy mode a tax number is unique per learner, not per install.

Registering a subcontractor, or changing its tax number, answers 409 when an
active subcontractor anywhere on the install already holds that number. On a
company install that is right: the directory is shared, and one tax number is
one firm. On an academy box every learner keeps their own directory, so the
409 told a learner that somebody else had registered that firm, and two
learners working the same course could not both register it. In academy mode
the duplicate check looks only at the caller's own subcontractors, on create
and on edit. An admin still checks the whole install, and nothing changes with
the flag off.

There is no unique index behind this check on any install; it is the
service's read of active rows (see ``SubcontractorRepository.find_by_tax_id``).

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.modules.subcontractors.schemas import SubcontractorCreate, SubcontractorUpdate
from app.modules.subcontractors.service import SubcontractorService
from tests.pg.academy_isolation.rows import make_user

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

NUMBER = "DE811111111"
OTHER = "DE822222222"


async def _register(session, user, name: str, tax_id: str):
    return await SubcontractorService(session).create_subcontractor(
        SubcontractorCreate(legal_name=name, tax_id=tax_id, country="DE"), user_id=str(user.id)
    )


def _conflict(caught) -> None:
    assert caught.value.status_code == 409


async def test_academy_on_two_learners_register_the_same_firm(pg_session, academy) -> None:
    academy(True)
    alice = await make_user(pg_session, name="Alice")
    bob = await make_user(pg_session, name="Bob")

    await _register(pg_session, alice, "Rheinbeton GmbH", NUMBER)
    theirs = await _register(pg_session, bob, "Rheinbeton GmbH", NUMBER)

    assert theirs.tax_id == NUMBER
    with pytest.raises(HTTPException) as again:
        await _register(pg_session, alice, "Rheinbeton (duplicate)", NUMBER)
    _conflict(again)


async def test_academy_on_an_edit_checks_only_the_learners_own_firms(pg_session, academy) -> None:
    academy(True)
    alice = await make_user(pg_session, name="Alice")
    bob = await make_user(pg_session, name="Bob")
    await _register(pg_session, alice, "Rheinbeton GmbH", NUMBER)
    bob_first = await _register(pg_session, bob, "Moselstahl GmbH", OTHER)
    bob_second = await _register(pg_session, bob, "Saarholz GmbH", "DE833333333")
    svc = SubcontractorService(pg_session)

    moved = await svc.update_subcontractor(bob_first.id, SubcontractorUpdate(tax_id=NUMBER), actor_id=str(bob.id))
    assert moved.tax_id == NUMBER
    with pytest.raises(HTTPException) as own_duplicate:
        await svc.update_subcontractor(bob_second.id, SubcontractorUpdate(tax_id=NUMBER), actor_id=str(bob.id))
    _conflict(own_duplicate)


async def test_academy_on_an_admin_still_checks_the_whole_install(pg_session, academy) -> None:
    academy(True)
    alice = await make_user(pg_session, name="Alice")
    admin = await make_user(pg_session, name="Admin", role="admin")
    await _register(pg_session, alice, "Rheinbeton GmbH", NUMBER)

    with pytest.raises(HTTPException) as caught:
        await _register(pg_session, admin, "Rheinbeton GmbH", NUMBER)
    _conflict(caught)


async def test_academy_off_unchanged(pg_session, academy) -> None:
    academy(False)
    alice = await make_user(pg_session, name="Alice")
    bob = await make_user(pg_session, name="Bob")
    await _register(pg_session, alice, "Rheinbeton GmbH", NUMBER)
    bob_own = await _register(pg_session, bob, "Moselstahl GmbH", OTHER)

    with pytest.raises(HTTPException) as on_create:
        await _register(pg_session, bob, "Rheinbeton GmbH", NUMBER)
    _conflict(on_create)
    with pytest.raises(HTTPException) as on_edit:
        await SubcontractorService(pg_session).update_subcontractor(
            bob_own.id, SubcontractorUpdate(tax_id=NUMBER), actor_id=str(bob.id)
        )
    _conflict(on_edit)
