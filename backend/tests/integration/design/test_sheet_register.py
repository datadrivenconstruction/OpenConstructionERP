"""Drawing sheet register: one ERP sheet row per design sheet and revision, chained, following the decision."""

from __future__ import annotations

import uuid

import pytest

from .ddcrev import example_rows, package
from .test_design_revisions import BASE, _linked_project, _upload
from .test_integration import PDF, _db, _documents
from .test_schedule import _rows_upper

pytestmark = pytest.mark.asyncio


async def _sheet_rows(pid):
    from sqlalchemy import select

    from app.modules.documents.models import Sheet

    async def read(s):
        return (await s.execute(select(Sheet).where(Sheet.project_id == uuid.UUID(str(pid))))).scalars().all()

    return await _db(read)


def _eg(rows):
    return sorted([s for s in rows if s.sheet_number == "EG"], key=lambda s: int(s.revision))


async def test_sheet_register_gets_a_row_per_sheet_and_revision_that_follows_the_decision(client):
    from sqlalchemy import select

    from app.modules.documents.models import DocumentBIMLink

    uid, h, pid, tok = await _linked_project(client)
    rows1 = example_rows()
    d1, m1 = package(pid, rows1, files={"sheets/EG.pdf": PDF, "sheets/Lageplan.pdf": PDF})
    r1 = (await _upload(client, pid, tok, d1)).json()["revision_id"]
    s1 = {s.sheet_number: s for s in await _sheet_rows(pid)}
    assert set(s1) == {"EG", "Lageplan"}
    eg = s1["EG"]
    # the number is the file name; nothing else is guessed
    assert (
        eg.revision == "1"
        and eg.is_current
        and eg.page_number == 1
        and eg.discipline is None
        and eg.sheet_title is None
    )
    assert eg.metadata_["design"]["status"] == "shared" and eg.metadata_["design"]["revision_id"] == r1
    docs = {d.metadata_["design"]["sheet"]: d for d in await _documents(pid)}
    assert eg.document_id == str(docs["sheets/EG.pdf"].id)

    async def links(doc_id):
        async def read(s):
            return (
                (await s.execute(select(DocumentBIMLink).where(DocumentBIMLink.document_id == doc_id))).scalars().all()
            )

        return await _db(read)

    # a sheet named like a storey is linked to that storey's elements; the other one is not
    lk = await links(docs["sheets/EG.pdf"].id)
    assert lk and {x.link_type for x in lk} == {"design_sheet"}
    assert await links(docs["sheets/Lageplan.pdf"].id) == []

    assert (await client.post(f"{BASE}/revisions/{r1}/accept", headers=h)).status_code == 200
    assert {s.metadata_["design"]["status"] for s in await _sheet_rows(pid)} == {"published"}

    d2, _ = package(
        pid, _rows_upper(), parent_id=m1["revision_id"], parent_rows=rows1, files={"sheets/EG.pdf": PDF + b"% R2\n"}
    )
    r2 = (await _upload(client, pid, tok, d2)).json()["revision_id"]
    a, b = _eg(await _sheet_rows(pid))
    assert (a.revision, b.revision) == ("1", "2")
    assert b.previous_version_id == a.id and b.is_current and not a.is_current
    assert a.document_id == b.document_id  # the same drawing, a new version of its file
    # rejected: the new sheet is not the drawing in force, the one before it is again
    assert (
        await client.post(f"{BASE}/revisions/{r2}/reject", json={"comment": "Too wide"}, headers=h)
    ).status_code == 200
    a, b = _eg(await _sheet_rows(pid))
    assert not b.is_current and a.is_current and b.metadata_["design"]["status"] == "rejected"
