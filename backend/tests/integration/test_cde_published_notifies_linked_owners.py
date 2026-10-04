# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Publishing a CDE container tells the owners of records linked to it.

The chain under test is the real one, driven through HTTP: create a container,
link a revision to a Documents hub row, promote wip -> shared -> published.
``transition_state`` publishes ``cde.container.promoted``, the core handler
re-emits ``cde.container.published``, and ``app.modules.cde.events`` turns
that into notifications.

The chain is driven rather than the published event fired by hand on purpose.
Until this change the promoted payload carried ``to_state`` while the core
handler read ``new_state``, so the published event never fired at all. A test
that published ``cde.container.published`` directly would have passed against
that broken chain.

Who is seeded, and why each one is here:

``alice`` (member)
    Measured on a takeoff copy of the document (``TakeoffDocument.source_
    document_id``), the shape the takeoff viewer writes. She also measured on
    an unrelated document, which must not raise her count above one.
``bob`` (member)
    Linked a BOQ position to the document through ``oe_file_reference``.
``dora`` (member)
    Owns a schedule whose activity is planned on Bob's position. She never
    touched the document; the position is what ties her to it.
``carl`` (NOT a member)
    Measured directly on the document. Owning a record is not enough, he must
    also still be on the project.
``erin`` (member)
    Measured on the same document id inside ANOTHER project. Project scoping
    must keep her out.
the publisher (project owner)
    Measured on the document too, and is never told about their own publish.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import create_app

NOTICE_TYPE = "cde_linked_published"


@pytest_asyncio.fixture
async def client():
    """FastAPI test client with full app lifespan (modules + DDL)."""
    from contextlib import asynccontextmanager

    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture
async def publisher(client: AsyncClient) -> tuple[uuid.UUID, dict[str, str]]:
    """Register an admin who will own the project and publish the container."""
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    unique = uuid.uuid4().hex[:8]
    email = f"cdepub-{unique}@smoke.io"
    password = f"CdePub{unique}9!"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "CDE Publisher"},
    )
    assert reg.status_code == 201, reg.text

    async with async_session_factory() as session:
        await session.execute(sa_update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()
        user_id = (await session.execute(select(User.id).where(User.email == email.lower()))).scalar_one()

    token = ""
    for attempt in range(3):
        resp = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
        token = resp.json().get("access_token", "")
        if token:
            break
        await asyncio.sleep(3 * (attempt + 1))
    assert token, resp.text
    return user_id, {"Authorization": f"Bearer {token}"}


def _pending_publishes() -> list[asyncio.Task]:
    """Every in-flight ``EventBus.publish`` on this loop.

    The suite's conftest replaces ``publish_detached`` and keeps the tasks in a
    set of its own rather than in ``event_bus._background_tasks``, so the
    tasks are found by what they run instead of where they are held. The app's
    long-lived background loops are not publishes and are left alone.
    """
    current = asyncio.current_task()
    return [
        task
        for task in asyncio.all_tasks()
        if task is not current
        and not task.done()
        and getattr(task.get_coro(), "__qualname__", "") == "EventBus.publish"
    ]


async def _drain() -> None:
    """Let every detached handler (and the ones it spawns) finish."""
    for _ in range(100):
        await asyncio.sleep(0)
        pending = _pending_publishes()
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)
    raise AssertionError("event handlers did not settle")


async def _new_project(client: AsyncClient, headers: dict[str, str], name: str) -> uuid.UUID:
    resp = await client.post(
        "/api/v1/projects/",
        json={"name": name, "region": "DACH", "classification_standard": "din276", "currency": "EUR"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


async def _make_user(session, label: str):  # type: ignore[no-untyped-def]
    from app.modules.users.models import User

    user = User(
        email=f"{label}-{uuid.uuid4().hex[:8]}@smoke.io",
        hashed_password="x",
        full_name=label.title(),
        role="editor",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user.id


async def _create_container(client: AsyncClient, headers: dict[str, str], project_id: uuid.UUID) -> str:
    resp = await client.post(
        "/api/v1/cde/containers/",
        json={
            "project_id": str(project_id),
            "container_code": f"PUB-{uuid.uuid4().hex[:6]}",
            "title": "Ground floor plan",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return str(resp.json()["id"])


async def _publish(client: AsyncClient, headers: dict[str, str], container_id: str) -> None:
    resp = await client.post(
        f"/api/v1/cde/containers/{container_id}/transition/",
        json={"target_state": "shared"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        f"/api/v1/cde/containers/{container_id}/transition/",
        json={
            "target_state": "published",
            "approver_signature": "Lead Appointed Party",
            "approval_comments": "Issued for construction",
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["cde_state"] == "published"


async def _notices(container_id: str):  # type: ignore[no-untyped-def]
    from app.database import async_session_factory
    from app.modules.notifications.models import Notification

    async with async_session_factory() as session:
        rows = await session.execute(
            select(Notification).where(
                Notification.notification_type == NOTICE_TYPE,
                Notification.entity_id == container_id,
            )
        )
        return list(rows.scalars().all())


@pytest.mark.asyncio
async def test_publishing_notifies_exactly_the_member_owners_of_linked_records(
    client: AsyncClient,
    publisher: tuple[uuid.UUID, dict[str, str]],
) -> None:
    from app.database import async_session_factory
    from app.modules.documents.models import Document
    from app.modules.file_references.models import FileReference
    from app.modules.schedule.models import Activity, Schedule
    from app.modules.takeoff.models import TakeoffDocument, TakeoffMeasurement
    from app.modules.teams.models import Team, TeamMembership

    publisher_id, headers = publisher
    project_id = await _new_project(client, headers, "CDE publish notice")
    other_project_id = await _new_project(client, headers, "CDE publish notice, other project")
    position_id = str(uuid.uuid4())

    async with async_session_factory() as session:
        alice = await _make_user(session, "alice")
        bob = await _make_user(session, "bob")
        carl = await _make_user(session, "carl")
        dora = await _make_user(session, "dora")
        erin = await _make_user(session, "erin")

        team = Team(project_id=project_id, name="Delivery team", is_default=True)
        session.add(team)
        await session.flush()
        session.add_all([TeamMembership(team_id=team.id, user_id=uid) for uid in (alice, bob, dora, erin)])

        drawing = Document(
            project_id=project_id,
            name="A-101 Ground floor.pdf",
            category="drawing",
            file_path="/tmp/a-101.pdf",
            mime_type="application/pdf",
            uploaded_by=str(publisher_id),
        )
        unrelated = Document(
            project_id=project_id,
            name="A-201 First floor.pdf",
            category="drawing",
            file_path="/tmp/a-201.pdf",
            mime_type="application/pdf",
            uploaded_by=str(publisher_id),
        )
        session.add_all([drawing, unrelated])
        await session.flush()

        takeoff_copy = TakeoffDocument(
            filename="A-101 Ground floor.pdf",
            project_id=project_id,
            owner_id=alice,
            source_document_id=str(drawing.id),
        )
        session.add(takeoff_copy)
        await session.flush()

        schedule = Schedule(project_id=project_id, name="Master programme", created_by=dora)
        session.add(schedule)
        await session.flush()

        session.add_all(
            [
                # alice: on the takeoff copy of the drawing -> counted once.
                TakeoffMeasurement(
                    project_id=project_id,
                    document_id=str(takeoff_copy.id),
                    type="area",
                    created_by=str(alice),
                    linked_boq_position_id=position_id,
                ),
                # alice: on a document outside the container -> not counted.
                TakeoffMeasurement(
                    project_id=project_id,
                    document_id=str(unrelated.id),
                    type="distance",
                    created_by=str(alice),
                ),
                # carl: on the drawing itself, but not a project member.
                TakeoffMeasurement(
                    project_id=project_id,
                    document_id=str(drawing.id),
                    type="count",
                    created_by=str(carl),
                ),
                # the publisher: on the drawing, and never told about it.
                TakeoffMeasurement(
                    project_id=project_id,
                    document_id=str(drawing.id),
                    type="count",
                    created_by=str(publisher_id),
                ),
                # erin: same document id, other project -> out of scope.
                TakeoffMeasurement(
                    project_id=other_project_id,
                    document_id=str(drawing.id),
                    type="count",
                    created_by=str(erin),
                ),
                # bob: a deliberate drawing -> BOQ position link.
                FileReference(
                    project_id=project_id,
                    file_kind="document",
                    file_id=str(drawing.id),
                    target_type="boq_position",
                    target_id=position_id,
                    created_by_id=bob,
                ),
                # dora: an activity planned on that position.
                Activity(
                    schedule_id=schedule.id,
                    name="Ground floor slab",
                    start_date="2026-11-02",
                    end_date="2026-11-20",
                    boq_position_ids=[position_id],
                ),
                # A second activity on another position: dora still counts once.
                Activity(
                    schedule_id=schedule.id,
                    name="Roof",
                    start_date="2027-01-04",
                    end_date="2027-01-29",
                    boq_position_ids=[str(uuid.uuid4())],
                ),
            ]
        )
        await session.commit()

    container_id = await _create_container(client, headers, project_id)
    resp = await client.post(
        f"/api/v1/cde/containers/{container_id}/revisions/",
        json={"file_name": "A-101 Ground floor.pdf", "document_id": str(drawing.id)},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    revision_id = resp.json()["id"]

    await _publish(client, headers, container_id)
    await _drain()

    notices = await _notices(container_id)
    by_user = {n.user_id: n for n in notices}
    assert set(by_user) == {alice, bob, dora}, {str(k) for k in by_user}
    assert len(notices) == 3

    assert by_user[alice].metadata_["records_by_kind"] == {"takeoff_measurement": 1}
    assert by_user[bob].metadata_["records_by_kind"] == {"boq_position": 1}
    assert by_user[dora].metadata_["records_by_kind"] == {"schedule_activity": 1}
    for notice in notices:
        assert notice.metadata_["revision_id"] == revision_id
        assert notice.body_context["records"] == 1
        assert notice.title_key == "notifications.cde.linked_published.title"
        assert notice.action_url == f"/projects/{project_id}/cde?container={container_id}"

    # The same event delivered again writes nothing new.
    from app.core.events import event_bus

    await event_bus.publish(
        "cde.container.published",
        {"project_id": str(project_id), "container_id": container_id, "promoted_by": str(publisher_id)},
        source_module="test",
    )
    await _drain()
    assert len(await _notices(container_id)) == 3


@pytest.mark.asyncio
async def test_a_revision_added_to_a_published_container_tells_the_owners_again(
    client: AsyncClient,
    publisher: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """A container is published once; its later revisions still reach people.

    The state machine has no way back from ``published``, so Gate B is crossed
    exactly once per container. A revision added afterwards becomes the
    current one straight away, and that is the change that leaves a takeoff
    measured on the previous revision stale. Both exits of ``create_revision``
    are driven: link mode returns early, upload mode at the bottom.

    Without ``cde.revision.published`` the count below stays at one after
    each new revision.
    """
    from app.core.events import event_bus
    from app.database import async_session_factory
    from app.modules.documents.models import Document
    from app.modules.takeoff.models import TakeoffMeasurement
    from app.modules.teams.models import Team, TeamMembership

    publisher_id, headers = publisher
    project_id = await _new_project(client, headers, "CDE revision after publish")

    async with async_session_factory() as session:
        estimator = await _make_user(session, "estimator")
        team = Team(project_id=project_id, name="Estimating", is_default=True)
        session.add(team)
        await session.flush()
        session.add(TeamMembership(team_id=team.id, user_id=estimator))
        drawing = Document(
            project_id=project_id,
            name="A-101 Ground floor.pdf",
            category="drawing",
            file_path="/tmp/a-101-rev.pdf",
            mime_type="application/pdf",
            uploaded_by=str(publisher_id),
        )
        session.add(drawing)
        await session.flush()
        session.add_all(
            [
                TakeoffMeasurement(
                    project_id=project_id,
                    document_id=str(drawing.id),
                    type="area",
                    created_by=str(estimator),
                ),
                # The publisher measured too, and is never told about their own revision.
                TakeoffMeasurement(
                    project_id=project_id,
                    document_id=str(drawing.id),
                    type="count",
                    created_by=str(publisher_id),
                ),
            ]
        )
        await session.commit()
        drawing_id = drawing.id

    container_id = await _create_container(client, headers, project_id)

    # A revision on a container that is not published yet tells nobody.
    first = await client.post(
        f"/api/v1/cde/containers/{container_id}/revisions/",
        json={"file_name": "A-101 Ground floor.pdf", "document_id": str(drawing_id), "is_preliminary": False},
        headers=headers,
    )
    assert first.status_code == 201, first.text
    await _drain()
    assert await _notices(container_id) == []

    await _publish(client, headers, container_id)
    await _drain()
    notices = await _notices(container_id)
    assert [n.user_id for n in notices] == [estimator]
    assert notices[0].metadata_["revision_id"] == first.json()["id"]

    # Link mode on the published container: the early return.
    second = await client.post(
        f"/api/v1/cde/containers/{container_id}/revisions/",
        json={"file_name": "A-101 Ground floor.pdf", "document_id": str(drawing_id), "is_preliminary": False},
        headers=headers,
    )
    assert second.status_code == 201, second.text
    await _drain()

    # Upload mode on the published container: the return at the bottom.
    third = await client.post(
        f"/api/v1/cde/containers/{container_id}/revisions/",
        json={
            "file_name": "A-101 Ground floor rev C.pdf",
            "storage_key": f"cde/{uuid.uuid4().hex}.pdf",
            "is_preliminary": False,
        },
        headers=headers,
    )
    assert third.status_code == 201, third.text
    await _drain()

    notices = await _notices(container_id)
    assert {n.user_id for n in notices} == {estimator}, "the publisher must not be told"
    by_revision = {n.metadata_["revision_id"]: n for n in notices}
    assert set(by_revision) == {first.json()["id"], second.json()["id"], third.json()["id"]}
    assert by_revision[second.json()["id"]].metadata_["revision_code"] == second.json()["revision_code"]
    assert by_revision[third.json()["id"]].body_context["revision_code"] == third.json()["revision_code"]

    # The same revision event delivered twice still makes one notice.
    await event_bus.publish(
        "cde.revision.published",
        {
            "project_id": str(project_id),
            "container_id": container_id,
            "revision_id": third.json()["id"],
            "promoted_by": str(publisher_id),
        },
        source_module="test",
    )
    await _drain()
    assert len(await _notices(container_id)) == 3


@pytest.mark.asyncio
async def test_the_promoted_audit_row_records_the_real_states(
    client: AsyncClient,
    publisher: tuple[uuid.UUID, dict[str, str]],
) -> None:
    """The core handler used to audit every transition as "" -> ""."""
    from app.core.audit import AuditEntry
    from app.database import async_session_factory

    _, headers = publisher
    project_id = await _new_project(client, headers, "CDE audit states")
    container_id = await _create_container(client, headers, project_id)
    await _publish(client, headers, container_id)
    await _drain()

    async with async_session_factory() as session:
        rows = await session.execute(
            select(AuditEntry).where(
                AuditEntry.action == "cde_state_change",
                AuditEntry.entity_type == "cde_container",
                AuditEntry.entity_id == container_id,
            )
        )
        entries = list(rows.scalars().all())
    states = sorted((entry.details["old_state"], entry.details["new_state"]) for entry in entries)
    assert states == [("shared", "published"), ("wip", "shared")]


@pytest.mark.asyncio
async def test_service_is_idempotent_and_ignores_a_container_that_is_not_published(
    client: AsyncClient,
    publisher: tuple[uuid.UUID, dict[str, str]],
) -> None:
    from app.database import async_session_factory
    from app.modules.cde.models import DocumentContainer, DocumentRevision
    from app.modules.cde.published_notice import notify_linked_record_owners
    from app.modules.documents.models import Document
    from app.modules.takeoff.models import TakeoffMeasurement
    from app.modules.teams.models import Team, TeamMembership

    publisher_id, headers = publisher
    project_id = await _new_project(client, headers, "CDE publish notice, service")

    async with async_session_factory() as session:
        owner = await _make_user(session, "owner")
        team = Team(project_id=project_id, name="Team", is_default=True)
        session.add(team)
        await session.flush()
        session.add(TeamMembership(team_id=team.id, user_id=owner))
        doc = Document(project_id=project_id, name="S-001.pdf", category="drawing", uploaded_by="seed")
        session.add(doc)
        await session.flush()
        session.add(
            TakeoffMeasurement(
                project_id=project_id,
                document_id=str(doc.id),
                type="area",
                created_by=str(owner),
            )
        )
        container = DocumentContainer(
            project_id=project_id,
            container_code=f"SVC-{uuid.uuid4().hex[:6]}",
            title="Structural",
            cde_state="shared",
        )
        session.add(container)
        await session.flush()
        revision = DocumentRevision(
            container_id=container.id,
            revision_code="P.01.01",
            revision_number=1,
            file_name="S-001.pdf",
            document_id=str(doc.id),
        )
        session.add(revision)
        await session.flush()
        container.current_revision_id = str(revision.id)
        await session.commit()
        container_id = container.id

    async with async_session_factory() as session:
        # Still shared: the event is a claim, the row is the fact.
        assert await notify_linked_record_owners(session, container_id, promoted_by=publisher_id) == []

    async with async_session_factory() as session:
        row = await session.get(DocumentContainer, container_id)
        assert row is not None
        row.cde_state = "published"
        await session.commit()

    async with async_session_factory() as session:
        first = await notify_linked_record_owners(session, container_id, promoted_by=publisher_id)
        await session.commit()
    async with async_session_factory() as session:
        second = await notify_linked_record_owners(session, container_id, promoted_by=publisher_id)
        await session.commit()

    assert first == [owner]
    assert second == []
    assert len(await _notices(str(container_id))) == 1

    # A new revision is a new fact: the same owner is told again, once.
    async with async_session_factory() as session:
        rev2 = DocumentRevision(
            container_id=container_id,
            revision_code="C.02",
            revision_number=2,
            is_preliminary=False,
            file_name="S-001.pdf",
            document_id=str(doc.id),
        )
        session.add(rev2)
        await session.flush()
        row = await session.get(DocumentContainer, container_id)
        assert row is not None
        row.current_revision_id = str(rev2.id)
        await session.commit()
    async with async_session_factory() as session:
        third = await notify_linked_record_owners(session, container_id, promoted_by=publisher_id)
        await session.commit()
    assert third == [owner]
    notices = await _notices(str(container_id))
    assert sorted(n.metadata_["revision_code"] for n in notices) == ["C.02", "P.01.01"]
