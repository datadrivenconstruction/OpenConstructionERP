# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Shared builders for the Work Requests suite. Neutral names only."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.projects.models import Project
from app.modules.users.models import User
from app.modules.work_requests import service
from app.modules.work_requests.models import WorkDepartment, WorkRequest
from app.modules.work_requests.seeds import seed_departments_if_empty

TODAY = date.today()


def day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


async def make_user(session: AsyncSession, *, name: str = "Alex Example", role: str = "editor") -> User:
    user = User(
        email=f"wr-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name=name,
        role=role,
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user


async def make_project(
    session: AsyncSession,
    *,
    owner: User,
    code: str = "25406",
    name: str = "Example Client Pty Ltd - MCC upgrade",
) -> Project:
    proj = Project(name=name, owner_id=owner.id, currency="AUD", project_code=code, client_id="Acme Holdings")
    session.add(proj)
    await session.flush()
    return proj


async def seeded(session: AsyncSession) -> dict[str, WorkDepartment]:
    await seed_departments_if_empty(session)
    return {d.key: d for d in await service.list_departments(session)}


async def raise_request(
    session: AsyncSession,
    *,
    project: Project,
    user: User,
    department: str = "workshop",
    request_type: str = "switchboard",
    title: str = "MSB-01 main switchboard",
    **kw,
) -> WorkRequest:
    await seeded(session)
    return await service.create_request(
        session,
        project_id=project.id,
        department=department,
        request_type=request_type,
        title=title,
        user_id=str(user.id),
        **kw,
    )
