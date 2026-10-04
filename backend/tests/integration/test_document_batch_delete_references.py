# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The bulk document delete says what it severs, and asks before it does.

Deleting one document already warns about the rows elsewhere that still point
at it (``GET /documents/{id}/references``). The batch path did not: it removed
every selected row without looking. These tests hold the batch to the same
standard.

``POST /documents/batch/references/`` must answer, per document, exactly what
the single endpoint answers. That is checked by asking both and comparing, on
a seed that carries every shape the single endpoint's own test uses plus the
two decoys that catch a name-matching implementation, and one case only a
batch has: a meeting whose array holds TWO of the selected documents, which
must count once against each.

``POST /documents/batch/delete/`` then refuses (409, nothing deleted) while
anything would be stranded or unlinked, until the caller acknowledges. A
batch that only touches retaining rows, and a batch nothing points at, delete
without the acknowledgement, so existing callers see no change.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import create_app

_MEETING_DATE = "2026-10-04"


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


async def _login(client: AsyncClient, *, admin: bool) -> dict[str, str]:
    from sqlalchemy import update as sa_update

    from app.database import async_session_factory
    from app.modules.users.models import User

    unique = uuid.uuid4().hex[:8]
    email = f"docbatch-{unique}@smoke.io"
    password = f"DocBatch{unique}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Doc Batch Tester"},
    )
    assert reg.status_code == 201, reg.text
    async with async_session_factory() as session:
        await session.execute(
            sa_update(User)
            .where(User.email == email.lower())
            .values(role="admin" if admin else "editor", is_active=True)
        )
        await session.commit()

    token = ""
    for attempt in range(3):
        resp = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
        token = resp.json().get("access_token", "")
        if token:
            break
        await asyncio.sleep(3 * (attempt + 1))
    assert token, resp.text
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def auth_headers(client: AsyncClient) -> dict[str, str]:
    return await _login(client, admin=True)


@pytest_asyncio.fixture
async def project_id(client: AsyncClient, auth_headers: dict[str, str]) -> uuid.UUID:
    resp = await client.post(
        "/api/v1/projects/",
        json={
            "name": "Document batch references",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return uuid.UUID(resp.json()["id"])


async def _documents(project_id: uuid.UUID, *names: str) -> list[uuid.UUID]:
    from app.database import async_session_factory
    from app.modules.documents.models import Document

    async with async_session_factory() as session:
        rows = [
            Document(
                project_id=project_id,
                name=name,
                category="drawing",
                file_path="",
                mime_type="application/pdf",
                uploaded_by="seed",
            )
            for name in names
        ]
        session.add_all(rows)
        await session.commit()
        return [row.id for row in rows]


async def _still_there(ids: list[uuid.UUID]) -> set[uuid.UUID]:
    from app.database import async_session_factory
    from app.modules.documents.models import Document

    async with async_session_factory() as session:
        rows = await session.execute(select(Document.id).where(Document.id.in_(ids)))
        return set(rows.scalars().all())


@pytest.mark.asyncio
async def test_batch_answer_matches_the_single_answer_for_every_document(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project_id: uuid.UUID,
) -> None:
    from app.database import async_session_factory
    from app.modules.documents.models import Sheet
    from app.modules.markups.models import ScaleConfig
    from app.modules.meetings.models import Meeting
    from app.modules.portal.models import PortalDocumentAccessLog, PortalUser
    from app.modules.punchlist.models import PunchItem
    from app.modules.temporary_works.models import TemporaryWorksItem

    first, second, lonely = await _documents(project_id, "A-101.pdf", "A-102.pdf", "A-103.pdf")
    outsider = uuid.uuid4()

    async with async_session_factory() as session:
        portal_user = PortalUser(email=f"portal-{uuid.uuid4().hex[:8]}@test.io", portal_role="client")
        session.add(portal_user)
        await session.flush()
        session.add_all(
            [
                Sheet(project_id=project_id, document_id=str(first), page_number=1),
                Sheet(project_id=project_id, document_id=str(first), page_number=2),
                ScaleConfig(document_id=str(second), pixels_per_unit=10.0, real_distance=1.0),
                PunchItem(project_id=project_id, title="Cracked screed", document_id=str(first)),
                TemporaryWorksItem(
                    project_id=project_id,
                    reference="TW-101",
                    title="Propping to slab",
                    tw_type="propping",
                    design_document_id=second,
                ),
                # One meeting holding BOTH selected documents: once each.
                Meeting(
                    project_id=project_id,
                    meeting_number="M-101",
                    meeting_type="progress",
                    title="Weekly progress",
                    meeting_date=_MEETING_DATE,
                    document_ids=[str(first), str(second)],
                ),
                PortalDocumentAccessLog(
                    portal_user_id=portal_user.id,
                    document_type="document",
                    document_id=second,
                    action="view",
                ),
                # Decoys: another document_type, and an array of a stranger.
                PortalDocumentAccessLog(
                    portal_user_id=portal_user.id,
                    document_type="invoice",
                    document_id=first,
                    action="view",
                ),
                Meeting(
                    project_id=project_id,
                    meeting_number="M-102",
                    meeting_type="progress",
                    title="Unrelated",
                    meeting_date=_MEETING_DATE,
                    document_ids=[str(outsider)],
                ),
            ]
        )
        await session.commit()

    resp = await client.post(
        "/api/v1/documents/batch/references/",
        json={"ids": [str(first), str(second), str(lonely), str(outsider)]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    batch = resp.json()

    # The outsider id names no document, so it is not even checked.
    assert batch["checked"] == 3
    assert batch["referenced_documents"] == 2

    per_doc = {d["document_id"]: d for d in batch["documents"]}
    assert set(per_doc) == {str(first), str(second)}, "a document nothing points at is not listed"

    for doc_id in (first, second):
        single = (await client.get(f"/api/v1/documents/{doc_id}/references", headers=auth_headers)).json()
        assert per_doc[str(doc_id)] == single, f"batch and single disagree for {doc_id}"

    # first: 2 sheets (strands), punch item + meeting (unlinks).
    assert per_doc[str(first)]["strands"] == 2
    assert per_doc[str(first)]["unlinks"] == 2
    assert per_doc[str(first)]["retains"] == 0
    # second: scale (strands), temporary works + meeting (unlinks), portal (retains).
    assert per_doc[str(second)]["strands"] == 1
    assert per_doc[str(second)]["unlinks"] == 2
    assert per_doc[str(second)]["retains"] == 1

    # The batch totals are the sum, and the shared meeting shows as two rows.
    assert (batch["strands"], batch["unlinks"], batch["retains"], batch["total"]) == (3, 4, 1, 8)
    summed = {item["key"]: item["count"] for item in batch["references"]}
    assert summed["Meeting.document_ids"] == 2
    assert summed["Sheet.document_id"] == 2
    assert [item["impact"] for item in batch["references"]][:2] == ["strands", "strands"]

    # The heaviest document leads.
    assert batch["documents"][0]["document_id"] == str(first)


@pytest.mark.asyncio
async def test_batch_delete_refuses_until_the_references_are_acknowledged(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project_id: uuid.UUID,
) -> None:
    from app.database import async_session_factory
    from app.modules.punchlist.models import PunchItem

    linked, free = await _documents(project_id, "S-201.pdf", "S-202.pdf")
    async with async_session_factory() as session:
        session.add(PunchItem(project_id=project_id, title="Missing fire stop", document_id=str(linked)))
        await session.commit()

    ids = [str(linked), str(free)]
    refused = await client.post("/api/v1/documents/batch/delete/", json={"ids": ids}, headers=auth_headers)
    assert refused.status_code == 409, refused.text
    detail = refused.json()["detail"]
    assert detail["error"] == "document_references"
    assert detail["message"]
    assert detail["references"]["unlinks"] == 1
    assert [d["document_id"] for d in detail["references"]["documents"]] == [str(linked)]
    # Refused means refused: neither document went, not even the free one.
    assert await _still_there([linked, free]) == {linked, free}

    done = await client.post(
        "/api/v1/documents/batch/delete/",
        json={"ids": ids, "acknowledge_references": True},
        headers=auth_headers,
    )
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["deleted"] == 2
    assert body["references"]["unlinks"] == 1
    assert await _still_there([linked, free]) == set()


@pytest.mark.asyncio
async def test_batch_delete_needs_no_acknowledgement_when_nothing_loses_anything(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project_id: uuid.UUID,
) -> None:
    from app.database import async_session_factory
    from app.modules.portal.models import PortalDocumentAccessLog, PortalUser

    plain, audited = await _documents(project_id, "M-301.pdf", "M-302.pdf")
    async with async_session_factory() as session:
        portal_user = PortalUser(email=f"portal-{uuid.uuid4().hex[:8]}@test.io", portal_role="client")
        session.add(portal_user)
        await session.flush()
        # Append-only audit retains the id; it loses nothing, so no prompt.
        session.add(
            PortalDocumentAccessLog(
                portal_user_id=portal_user.id,
                document_type="document",
                document_id=audited,
                action="download",
            )
        )
        await session.commit()

    resp = await client.post(
        "/api/v1/documents/batch/delete/",
        json={"ids": [str(plain), str(audited)]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["deleted"] == 2
    assert body["references"]["retains"] == 1
    assert body["references"]["strands"] + body["references"]["unlinks"] == 0


@pytest.mark.asyncio
async def test_batch_references_say_nothing_about_documents_the_caller_cannot_open(
    client: AsyncClient,
    auth_headers: dict[str, str],
    project_id: uuid.UUID,
) -> None:
    from app.database import async_session_factory
    from app.modules.punchlist.models import PunchItem

    (secret,) = await _documents(project_id, "Confidential.pdf")
    async with async_session_factory() as session:
        session.add(PunchItem(project_id=project_id, title="Hidden", document_id=str(secret)))
        await session.commit()

    stranger = await _login(client, admin=False)
    resp = await client.post(
        "/api/v1/documents/batch/references/",
        json={"ids": [str(secret)]},
        headers=stranger,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["checked"] == 0
    assert body["total"] == 0
    assert body["documents"] == []

    # And the empty request is a validation error, not an empty answer.
    empty = await client.post("/api/v1/documents/batch/references/", json={"ids": []}, headers=auth_headers)
    assert empty.status_code == 422, empty.text
