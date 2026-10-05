# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A project's works survive the database and reach the contracts written on it.

The unit tests hold the law; these hold the column. A project created as
public keeps ``works`` through the service, an edit can change it or clear it
back to not recorded, and a contract created on the stored row reads the Code
de la commande publique (public) or loi 71-584 (private) from it.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.config import Settings
from app.core.events import event_bus
from app.modules.contracts.schemas import ContractCreate
from app.modules.contracts.service import ContractsService
from app.modules.contracts.validators import register_contracts_validation_rules
from app.modules.projects import service as project_service_module
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate
from app.modules.projects.service import ProjectService
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    monkeypatch.setattr(event_bus, "publish_detached", lambda *a, **k: None)
    register_contracts_validation_rules()
    project_service_module._PROJECT_CODE_RESERVED.clear()
    yield
    project_service_module._PROJECT_CODE_RESERVED.clear()


async def _owner(session) -> uuid.UUID:
    user = User(email=f"works-{uuid.uuid4().hex[:8]}@site.example", hashed_password="x", full_name="Owner")
    session.add(user)
    await session.flush()
    return user.id


def _projects(session) -> ProjectService:
    return ProjectService(session, Settings(_env_file=None))


async def _contract(session, project_id: uuid.UUID):
    return await ContractsService(session).create_contract(
        ContractCreate(
            code=f"C-{uuid.uuid4().hex[:8]}",
            contract_type="lump_sum",
            project_id=project_id,
            total_value=Decimal("100000"),
        )
    )


async def test_a_public_project_keeps_its_works_and_its_contract_reads_the_code(pg_session) -> None:
    owner = await _owner(pg_session)
    project = await _projects(pg_session).create_project(
        ProjectCreate(name="Lycée", country_code="FR", currency="EUR", works="public"), owner
    )
    await pg_session.refresh(project)
    assert project.works == "public"

    contract = await _contract(pg_session, project.id)

    stamp = contract.metadata_["country_defaults"]
    assert stamp["works"] == "public"
    assert "R2191-33" in stamp["sources"]["retention_percent"]["reference"]
    assert contract.retention_percent == Decimal("5")


async def test_an_edit_changes_the_works_and_clears_them(pg_session) -> None:
    owner = await _owner(pg_session)
    svc = _projects(pg_session)
    project = await svc.create_project(ProjectCreate(name="Villa", country_code="FR", currency="EUR"), owner)
    assert project.works is None

    project = await svc.update_project(project.id, ProjectUpdate(works="private"))
    await pg_session.refresh(project)
    assert project.works == "private"
    stamp = (await _contract(pg_session, project.id)).metadata_["country_defaults"]
    assert stamp["works"] == "private"
    assert stamp["sources"]["retention_percent"]["reference"] == "Loi n° 71-584 du 16 juillet 1971, art. 1"

    project = await svc.update_project(project.id, ProjectUpdate(works=None))
    await pg_session.refresh(project)
    assert project.works is None
    stamp = (await _contract(pg_session, project.id)).metadata_["country_defaults"]
    assert "works" not in stamp
