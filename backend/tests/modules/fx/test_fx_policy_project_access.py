# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A project's currency policy is reachable only by people who can reach the project.

The four policy routes take the project id from the path and used to check the
caller's role and nothing else, so a viewer of one project could read the
policy of any other (its three currencies, the pinned rate set and the note),
and a manager could overwrite or delete it. Row level security is a no-op in
this product, so ``verify_project_access`` is the only boundary between
projects, and these routes did not call it.

The caller is a persisted non-admin, because the guard reads the role from the
database and an admin would pass the check whether or not it ran. Every
cross-project probe has an owner control, so a 404 cannot come from a route
that is simply not mounted.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.users.models import User
from tests.modules.fx.conftest import API_PREFIX, build_app, http_client, make_policy

_POLICY = {
    "estimating_currency": "EUR",
    "procurement_currency": "EUR",
    "reporting_currency": "EUR",
    "rate_mode": "live",
}


async def _user(session: AsyncSession, role: str) -> User:
    user = User(email=f"fx-{uuid.uuid4().hex[:10]}@example.com", hashed_password="x", role=role, is_active=True)
    session.add(user)
    await session.flush()
    return user


async def _project(session: AsyncSession, owner: User) -> Project:
    project = Project(name=f"FX {uuid.uuid4().hex[:6]}", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project


@pytest.mark.asyncio
async def test_a_manager_cannot_reach_another_projects_policy(session: AsyncSession) -> None:
    owner = await _user(session, "manager")
    outsider = await _user(session, "manager")
    project = await _project(session, owner)
    await make_policy(session, project_id=project.id, reporting_currency="USD")

    app = build_app(session, caller_id=outsider.id, role="manager")
    url = f"{API_PREFIX}/policies/{project.id}/"
    async with http_client(app) as client:
        read = await client.get(url)
        report = await client.get(f"{url}validation/")
        write = await client.put(url, json=_POLICY)
        delete = await client.delete(url)

    assert read.status_code == 404, read.text
    assert report.status_code == 404, report.text
    assert write.status_code == 404, write.text
    assert delete.status_code == 404, delete.text

    owner_app = build_app(session, caller_id=owner.id, role="manager")
    async with http_client(owner_app) as client:
        still = await client.get(url)
    assert still.status_code == 200, still.text
    assert still.json()["reporting_currency"] == "USD"


@pytest.mark.asyncio
async def test_the_owner_can_set_read_validate_and_delete_its_policy(session: AsyncSession) -> None:
    owner = await _user(session, "manager")
    project = await _project(session, owner)

    app = build_app(session, caller_id=owner.id, role="manager")
    url = f"{API_PREFIX}/policies/{project.id}/"
    async with http_client(app) as client:
        write = await client.put(url, json=_POLICY)
        read = await client.get(url)
        report = await client.get(f"{url}validation/")
        delete = await client.delete(url)

    assert write.status_code == 200, write.text
    assert read.status_code == 200, read.text
    assert report.status_code == 200, report.text
    assert delete.status_code == 204, delete.text
