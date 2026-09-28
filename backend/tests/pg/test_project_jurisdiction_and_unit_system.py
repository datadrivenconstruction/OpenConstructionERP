# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A project's stated jurisdiction and measurement system, end to end on PostgreSQL.

The two fields start empty and are never filled from the country. That is the
condition the whole change rests on: an empty field has to leave every consumer
on the answer it gave before the field existed, and a set one has to win.
Pinned here in both directions - through the service that writes the project,
and through the validation payload that reads it - because a field that is
stored and read by nobody looks configured and changes nothing.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.validation.engine import ValidationContext
from app.core.validation.project_context import (
    PROJECT_RECORD_KEY,
    UNIT_SYSTEM_FROM_PACK,
    UNIT_SYSTEM_FROM_PROJECT,
    with_project_context,
)
from app.core.validation.rules import BOQUnitSystemConsistencyRule
from app.modules.projects import service as project_service_module
from app.modules.projects.schemas import ProjectCreate, ProjectUpdate
from app.modules.projects.service import ProjectService
from app.modules.users.models import User
from tests._pg import transactional_session

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


@pytest.fixture(autouse=True)
def _clear_reservation_set():
    project_service_module._PROJECT_CODE_RESERVED.clear()
    yield
    project_service_module._PROJECT_CODE_RESERVED.clear()


@pytest_asyncio.fixture
async def owner_id(session: AsyncSession) -> uuid.UUID:
    user = User(email=f"juris-{uuid.uuid4().hex}@test.local", hashed_password="x", full_name="Owner")
    session.add(user)
    await session.flush()
    return user.id


def _service(session: AsyncSession) -> ProjectService:
    return ProjectService(session, Settings(_env_file=None))


async def test_a_project_created_with_a_country_states_neither_field(session, owner_id) -> None:
    project = await _service(session).create_project(ProjectCreate(name="Tower", country_code="US"), owner_id)
    assert project.country_code == "US"
    assert project.jurisdiction is None
    assert project.unit_system is None


async def test_the_stated_fields_are_stored_as_given(session, owner_id) -> None:
    project = await _service(session).create_project(
        ProjectCreate(name="Tower", country_code="US", jurisdiction="us-ca", unit_system="Metric"),
        owner_id,
    )
    assert (project.jurisdiction, project.unit_system) == ("US-CA", "metric")


async def test_a_jurisdiction_outside_the_country_is_refused_on_create(session, owner_id) -> None:
    with pytest.raises(HTTPException) as refused:
        await _service(session).create_project(
            ProjectCreate(name="Tower", country_code="DE", jurisdiction="US-CA"), owner_id
        )
    assert refused.value.status_code == 422
    assert refused.value.detail["error"] == "jurisdiction_outside_country"


async def test_a_patch_sets_keeps_and_clears(session, owner_id) -> None:
    service = _service(session)
    project = await service.create_project(ProjectCreate(name="Tower", country_code="US"), owner_id)

    await service.update_project(project.id, ProjectUpdate(jurisdiction="US-TX", unit_system="imperial"))
    project = await service.get_project(project.id)
    assert (project.jurisdiction, project.unit_system) == ("US-TX", "imperial")

    # A patch that does not name the fields leaves them where they are.
    await service.update_project(project.id, ProjectUpdate(name="Tower B"))
    project = await service.get_project(project.id)
    assert (project.jurisdiction, project.unit_system) == ("US-TX", "imperial")

    # An explicit null takes a value off again.
    await service.update_project(project.id, ProjectUpdate(jurisdiction=None, unit_system=None))
    project = await service.get_project(project.id)
    assert (project.jurisdiction, project.unit_system) == (None, None)


async def test_moving_the_country_away_from_a_stated_state_is_refused(session, owner_id) -> None:
    service = _service(session)
    project = await service.create_project(
        ProjectCreate(name="Tower", country_code="US", jurisdiction="US-CA"), owner_id
    )
    with pytest.raises(HTTPException) as refused:
        await service.update_project(project.id, ProjectUpdate(country_code="DE"))
    assert refused.value.status_code == 422
    # Moving both halves in one patch is a consistent pair and goes through.
    await service.update_project(project.id, ProjectUpdate(country_code="CA", jurisdiction="CA-ON"))
    project = await service.get_project(project.id)
    assert (project.country_code, project.jurisdiction) == ("CA", "CA-ON")


async def test_an_unset_measurement_system_is_still_derived_from_the_country(session, owner_id) -> None:
    project = await _service(session).create_project(ProjectCreate(name="Tower", country_code="US"), owner_id)
    payload = await with_project_context(session, project.id, {"positions": []})
    assert payload["project_unit_system"] == "imperial"
    assert payload["project_unit_system_source"] == UNIT_SYSTEM_FROM_PACK
    assert payload[PROJECT_RECORD_KEY]["unit_system"] is None
    assert payload[PROJECT_RECORD_KEY]["jurisdiction"] is None


async def test_a_stated_measurement_system_outranks_the_country(session, owner_id) -> None:
    project = await _service(session).create_project(
        ProjectCreate(name="Tower", country_code="US", jurisdiction="US-CA", unit_system="metric"), owner_id
    )
    payload = await with_project_context(session, project.id, {"positions": [{"ordinal": "01", "unit": "m3"}]})
    assert payload["project_unit_system"] == "metric"
    assert payload["project_unit_system_source"] == UNIT_SYSTEM_FROM_PROJECT
    assert payload[PROJECT_RECORD_KEY]["jurisdiction"] == "US-CA"

    # A metric bill on a United States project that says it is measured in
    # metric: no warning, where the country alone would have warned.
    results = await BOQUnitSystemConsistencyRule().validate(ValidationContext(data=payload))
    assert [r.passed for r in results] == [True]


async def test_the_warning_names_the_setting_that_decided_it(session, owner_id) -> None:
    project = await _service(session).create_project(
        ProjectCreate(name="Tower", country_code="DE", unit_system="imperial"), owner_id
    )
    payload = await with_project_context(session, project.id, {"positions": [{"ordinal": "01", "unit": "m3"}]})
    results = await BOQUnitSystemConsistencyRule().validate(ValidationContext(data=payload))
    assert len(results) == 1 and results[0].passed is False
    suggestion = results[0].suggestion or ""
    assert "project settings" in suggestion
    assert "regional pack" not in suggestion
    assert "unit_system" not in suggestion
    assert results[0].details["project_unit_system_source"] == UNIT_SYSTEM_FROM_PROJECT


async def test_a_project_nobody_can_place_stays_unanswered(session, owner_id) -> None:
    project = await _service(session).create_project(ProjectCreate(name="Tower"), owner_id)
    payload = await with_project_context(session, project.id, {"positions": []})
    assert payload["project_unit_system"] is None
    assert payload["project_unit_system_source"] is None


async def _stored_unit_system(session, project_id: uuid.UUID) -> str | None:
    """Read the column, not the identity map: the repair writes with raw SQL."""
    from sqlalchemy import text

    return (
        await session.execute(
            text("SELECT unit_system FROM oe_projects_project WHERE id = :id"), {"id": str(project_id)}
        )
    ).scalar_one()


async def _live_default(session) -> str | None:
    from sqlalchemy import text

    return (
        await session.execute(
            text(
                "SELECT column_default FROM information_schema.columns WHERE table_schema = current_schema() "
                "AND table_name = 'oe_projects_project' AND column_name = 'unit_system'"
            )
        )
    ).scalar_one_or_none()


async def test_the_chain_default_is_cleared_once_and_a_later_choice_is_kept(session, owner_id) -> None:
    # A database that walked v3135 carries the column NOT NULL DEFAULT 'metric'
    # with 'metric' on every row, a value nobody chose. Rebuilt here by hand,
    # inside the test's transaction, on the create_all schema.
    from sqlalchemy import text

    from app.modules.projects.repairs import clear_chain_unit_system_default

    service = _service(session)
    project = await service.create_project(ProjectCreate(name="Chain", country_code="US"), owner_id)
    await session.execute(text("UPDATE oe_projects_project SET unit_system = 'metric'"))
    await session.execute(text("ALTER TABLE oe_projects_project ALTER COLUMN unit_system SET DEFAULT 'metric'"))
    await session.execute(text("ALTER TABLE oe_projects_project ALTER COLUMN unit_system SET NOT NULL"))

    changed = await clear_chain_unit_system_default(session)
    assert changed >= 1
    assert await _live_default(session) is None
    assert await _stored_unit_system(session, project.id) is None
    payload = await with_project_context(session, project.id, {"positions": []})
    assert (payload["project_unit_system"], payload["project_unit_system_source"]) == (
        "imperial",
        UNIT_SYSTEM_FROM_PACK,
    )

    # Somebody now chooses metric. The next boot must leave that alone.
    await service.update_project(project.id, ProjectUpdate(unit_system="metric"))
    assert await clear_chain_unit_system_default(session) == 0
    assert await _stored_unit_system(session, project.id) == "metric"


async def test_a_create_all_database_is_not_touched_by_the_chain_repair(session, owner_id) -> None:
    from app.modules.projects.repairs import clear_chain_unit_system_default

    service = _service(session)
    project = await service.create_project(
        ProjectCreate(name="Fresh", country_code="US", unit_system="metric"), owner_id
    )
    assert await _live_default(session) is None
    assert await clear_chain_unit_system_default(session) == 0
    assert (await service.get_project(project.id)).unit_system == "metric"
