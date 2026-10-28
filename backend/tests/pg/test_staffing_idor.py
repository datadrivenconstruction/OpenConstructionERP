# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Who may see what, over HTTP against PostgreSQL.

Identity is the variable under test: a stranger from another tenant, an editor
reaching for a personnel file, a manager with no relationship to the person,
the person themself, and a project member pointing at another project's
roster member. Plus the privacy contract: no full document number, no
document field in the file list, and an audit row for every file read.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.staffing.permissions import register_staffing_permissions
from app.modules.staffing.router import router
from tests._pg import isolated_engine
from tests.pg.governance_fixtures import World
from tests.pg.staffing_fixtures import build_world, confirm, fill, members, personnel_file, position

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

BASE = "/api/v1/staffing"


@pytest_asyncio.fixture
async def world():
    register_staffing_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory, governance=False)


@asynccontextmanager
async def client_as(w: World, user_id: uuid.UUID, role: str, permissions: list[str] | None = None):
    from app.dependencies import get_current_user_id, get_current_user_payload, get_session

    app = FastAPI()
    app.include_router(router, prefix=BASE)

    async def _session():
        async with w.factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": str(user_id),
        "role": role,
        "permissions": permissions or [],
        "tenant_id": str(user_id),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://staffing-test") as c:
        yield c


async def _file(w: World, *, self_user: uuid.UUID | None = None) -> tuple[uuid.UUID, uuid.UUID]:
    from app.modules.teams.models import RosterMember

    person = (await members(w))[0]
    if self_user is not None:
        async with w.factory() as s:
            (await s.get(RosterMember, person.id)).user_id = self_user
            await s.commit()
    return await personnel_file(w, person.id), person.id


async def test_a_stranger_from_another_tenant_sees_404_everywhere(world: World) -> None:
    file_id, _ = await _file(world)
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.outsider, "manager") as c:
        responses = [
            await c.get(f"{p}/plan"),
            await c.get(f"{p}/positions"),
            await c.get(f"{p}/compliance"),
            await c.get(f"{p}/personnel-files"),
            await c.get(f"{p}/personnel-files/{file_id}"),
            await c.post(f"{p}/positions", json={"role_code": "site_manager", "phase": "execution"}),
        ]
    assert [r.status_code for r in responses] == [404] * len(responses)


async def test_an_editor_reads_the_plan_but_not_a_personnel_file(world: World) -> None:
    file_id, _ = await _file(world)
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.editor, "editor") as c:
        assert (await c.get(f"{p}/plan")).status_code == 200
        r = await c.get(f"{p}/personnel-files/{file_id}")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "no_relationship_to_person"


async def test_a_manager_with_no_relationship_to_the_person_gets_403(world: World) -> None:
    file_id, _ = await _file(world)
    async with client_as(world, world.decider, "manager") as c:
        r = await c.get(f"{BASE}/projects/{world.project_id}/personnel-files/{file_id}")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "no_relationship_to_person"


async def test_the_line_manager_without_the_personnel_permission_gets_403(world: World) -> None:
    file_id, member_id = await _file(world)
    pid = await position(world, "site_manager", owner_user_id=world.editor, fte="0.50")
    await confirm(world, await fill(world, pid, member_id, "0.50"))
    async with client_as(world, world.editor, "editor") as c:
        r = await c.get(f"{BASE}/projects/{world.project_id}/personnel-files/{file_id}")
    assert r.status_code == 403
    assert r.json()["detail"]["code"] == "personnel_permission_missing"


async def test_the_position_owner_opens_the_file_and_the_read_is_audited(world: World) -> None:
    from app.core.audit_log import ActivityLog

    file_id, member_id = await _file(world)
    pid = await position(world, "site_manager", owner_user_id=world.owner, fte="0.50")
    await confirm(world, await fill(world, pid, member_id, "0.50"))
    async with client_as(world, world.owner, "manager") as c:
        r = await c.get(f"{BASE}/projects/{world.project_id}/personnel-files/{file_id}")
    assert r.status_code == 200
    async with world.factory() as s:
        rows = (
            (
                await s.execute(
                    select(ActivityLog).where(
                        ActivityLog.entity_id == str(file_id), ActivityLog.action == "personnel_file.read"
                    )
                )
            )
            .scalars()
            .all()
        )
    assert [r.actor_id for r in rows] == [world.owner]


async def test_the_person_opens_and_exports_their_own_file(world: World) -> None:
    file_id, _ = await _file(world, self_user=world.editor)
    p = f"{BASE}/projects/{world.project_id}/personnel-files/{file_id}"
    async with client_as(world, world.editor, "editor") as c:
        assert (await c.get(p)).status_code == 200
        r = await c.get(f"{p}/export", params={"format": "xlsx"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("application/vnd.openxmlformats")


async def test_another_projects_roster_member_is_404(world: World) -> None:
    from app.modules.teams.models import RosterMember
    from tests.pg.governance_fixtures import add_project

    async with world.factory() as s:
        other = await add_project(s, world.manager, [])
        m = RosterMember(project_id=other, display_name="Other person")
        s.add(m)
        await s.commit()
        foreign = m.id
    pid = await position(world, "site_manager")
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.manager, "admin") as c:
        r1 = await c.post(
            f"{p}/positions/{pid}/fills", json={"roster_member_id": str(foreign), "from_date": "2026-11-02"}
        )
        r2 = await c.post(f"{p}/personnel-files", json={"roster_member_id": str(foreign)})
    assert (r1.status_code, r2.status_code) == (404, 404)
    assert r1.json()["detail"]["code"] == "roster_member_not_found"


async def test_a_full_document_number_is_rejected_and_never_stored(world: World) -> None:
    from app.modules.staffing.models import PersonnelDocument

    file_id, _ = await _file(world)
    p = f"{BASE}/projects/{world.project_id}/personnel-files/{file_id}/documents"
    async with client_as(world, world.manager, "admin") as c:
        r = await c.post(p, json={"document_kind": "work_permit", "number_last4": "X12345678"})
        ok = await c.post(p, json={"document_kind": "work_permit", "number_last4": "5678"})
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "full_number_rejected"
    assert ok.status_code == 200
    async with world.factory() as s:
        stored = (await s.execute(select(PersonnelDocument.number_last4))).scalars().all()
    assert stored == ["5678"]


async def test_a_plain_viewer_gets_no_document_state_from_the_compliance_matrix_or_its_export(world: World) -> None:
    file_id, _ = await _file(world)
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.manager, "manager") as c:
        ok = await c.post(f"{p}/personnel-files/{file_id}/documents", json={"document_kind": "employment_contract"})
        mine = await c.get(f"{p}/compliance")
    assert ok.status_code == 200
    assert any(row["cells"] for row in mine.json()["items"])
    async with client_as(world, world.editor, "viewer") as c:
        r = await c.get(f"{p}/compliance")
        export = await c.get(f"{p}/export", params={"what": "compliance", "format": "xlsx"})
        preview = await c.post(f"{p}/plan/catalogue/preview", json={"catalogue_id": "neutral"})
    assert r.status_code == 200
    body = r.json()
    assert body["items"] and all(row["cells"] == {} and row["file_id"] is None for row in body["items"])
    assert body["document_kinds"] == []
    assert all(row["can"]["see_documents"]["reason"] == "no_relationship_to_person" for row in body["items"])
    assert export.status_code == 200
    # The plan findings a reader gets are about the plan only: no finding there reads a personnel file.
    async with client_as(world, world.editor, "viewer") as c:
        findings = await c.get(f"{p}/plan/findings")
        own_export = await c.get(f"{p}/export", params={"what": "plan", "format": "pdf"})
    assert findings.status_code == 200 and findings.json()["restricted_people"] == 0
    plan_codes = {
        "key_role_missing",
        "commissioning_date_missing",
        "operation_role_late",
        "handover_missing",
        "person_overallocated",
        "fte_out_of_range",
        "fte_precision",
        "headcount_invalid",
        "exit_before_entry",
    }
    assert {f["code"] for f in findings.json()["items"]} <= plan_codes
    assert own_export.headers["content-language"] == "en"
    # The preview is an edit-tier route even though it writes nothing.
    assert preview.status_code == 403


async def test_the_file_list_carries_no_document_fields(world: World) -> None:
    await _file(world)
    async with client_as(world, world.manager, "admin") as c:
        r = await c.get(f"{BASE}/projects/{world.project_id}/personnel-files")
    assert r.status_code == 200
    item = r.json()["items"][0]
    forbidden = {"documents", "number_last4", "valid_until", "fit_for_role", "travel", "leave", "credential_id"}
    assert not forbidden & set(item)
