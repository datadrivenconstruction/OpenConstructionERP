# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Legal entities and branches against PostgreSQL: the invariants the service holds."""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.modules.legal_entities.service import LegalEntityService

pytestmark = pytest.mark.asyncio


def _entity(code: str, **kw) -> dict:
    return {
        "code": code,
        "name": f"{code} Ltd",
        "country_code": "DE",
        "functional_currency": "EUR",
        **kw,
    }


async def test_only_one_entity_is_default(pg_session) -> None:
    service = LegalEntityService(pg_session)
    first = await service.create_entity(_entity("LE-A", is_default=True))
    second = await service.create_entity(_entity("LE-B", is_default=True, country_code="PL", functional_currency="PLN"))
    await pg_session.refresh(first)
    assert not first.is_default
    assert second.is_default
    assert (await service.default_entity()).id == second.id

    await service.update_entity(first.id, {"is_default": True})
    await pg_session.refresh(second)
    assert not second.is_default
    assert (await service.default_entity()).id == first.id


async def test_a_duplicate_code_is_a_conflict(pg_session) -> None:
    service = LegalEntityService(pg_session)
    await service.create_entity(_entity("LE-DUP"))
    with pytest.raises(HTTPException) as exc:
        await service.create_entity(_entity("LE-DUP"))
    assert exc.value.status_code == 409


async def test_an_invalid_currency_is_refused_on_update(pg_session) -> None:
    service = LegalEntityService(pg_session)
    entity = await service.create_entity(_entity("LE-CUR"))
    with pytest.raises(HTTPException) as exc:
        await service.update_entity(entity.id, {"functional_currency": "EURO"})
    assert exc.value.status_code == 422


async def test_branches_belong_to_their_entity_and_go_with_it(pg_session) -> None:
    service = LegalEntityService(pg_session)
    entity = await service.create_entity(_entity("LE-BR"))
    home, home_warnings = await service.create_branch(entity.id, {"code": "MUC", "name": "Munich"})
    abroad, abroad_warnings = await service.create_branch(
        entity.id, {"code": "WAW", "name": "Warsaw", "country_code": "PL"}
    )
    assert home.country_code == "DE" and home_warnings == []
    assert [w.rule_id for w in abroad_warnings] == ["legal_entities.branch_abroad"]
    assert sorted(b.code for b in entity.branches) == ["MUC", "WAW"]

    with pytest.raises(HTTPException) as exc:
        await service.create_branch(entity.id, {"code": "MUC", "name": "Again"})
    assert exc.value.status_code == 409

    other = await service.create_entity(_entity("LE-OTHER"))
    with pytest.raises(HTTPException) as exc:
        await service.update_branch(other.id, home.id, {"name": "Stolen"})
    assert exc.value.status_code == 404

    await service.delete_entity(entity.id)
    assert await service.branches.get(abroad.id) is None


async def _project(pg_session):
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    owner = User(email=f"le-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", full_name="LE Owner")
    pg_session.add(owner)
    await pg_session.flush()
    project = Project(name="LE project", owner_id=owner.id)
    pg_session.add(project)
    await pg_session.flush()
    return project


async def test_a_project_names_its_entity_or_falls_back_to_the_default(pg_session) -> None:
    service = LegalEntityService(pg_session)
    project = await _project(pg_session)
    assert await service.project_entity(project.id) == (None, "none")

    default = await service.create_entity(_entity("LE-HOME", is_default=True))
    assert await service.project_entity(project.id) == (default, "default")

    sub = await service.create_entity(_entity("LE-SUB", country_code="PL", functional_currency="PLN"))
    assert await service.assign_project(project.id, sub.id) == (sub, "assigned")
    assert project.legal_entity_id == sub.id

    with pytest.raises(HTTPException) as exc:
        await service.delete_entity(sub.id)
    assert exc.value.status_code == 409

    assert await service.assign_project(project.id, None) == (default, "default")
    await service.delete_entity(sub.id)


async def test_an_inactive_or_unknown_entity_cannot_take_a_project(pg_session) -> None:
    service = LegalEntityService(pg_session)
    project = await _project(pg_session)
    dormant = await service.create_entity(_entity("LE-DORM", is_active=False))
    with pytest.raises(HTTPException) as exc:
        await service.assign_project(project.id, dormant.id)
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await service.assign_project(project.id, uuid.uuid4())
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        await service.project_entity(uuid.uuid4())
    assert exc.value.status_code == 404


async def test_an_invoice_is_numbered_under_the_entity_the_project_names(pg_session) -> None:
    from app.modules.finance.repository import InvoiceRepository
    from app.modules.legal_entities.lookup import entity_country

    service = LegalEntityService(pg_session)
    project = await _project(pg_session)
    numbers = InvoiceRepository(pg_session)

    # The default entity does not stamp a number: a project naming none keeps the plain prefix.
    await service.create_entity(_entity("LE-DFLT", is_default=True, country_code="AT"))
    assert await numbers.next_invoice_number(project.id, "receivable") == "INV-R-001"
    assert await entity_country(pg_session, project.id) == "AT"

    sub = await service.create_entity(_entity("PL01", country_code="PL", functional_currency="PLN"))
    await service.assign_project(project.id, sub.id)
    assert await numbers.next_invoice_number(project.id, "receivable") == "PL01-INV-R-001"
    assert await numbers.next_invoice_number(project.id, "payable") == "PL01-INV-P-001"
    assert await entity_country(pg_session, project.id) == "PL"
