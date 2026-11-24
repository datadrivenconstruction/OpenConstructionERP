# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Revision control across documents, plan room, transmittals and record publishing.

Worked examples
~~~~~~~~~~~~~~~
* A drawing chain R (Rev A) -> B (Rev B): making B current supersedes A, and a
  chain never holds two current revisions.
* A transmittal "for review" refuses Rev A once Rev B is current; "for record"
  accepts it. The snapshot on the item is the register's revision, not the
  caller's text.
* A draft built while Rev A was current cannot be sent after Rev B replaced it.
* Only a published drawing goes "for construction".
* The Plan Room lists the issued, current drawings; earlier revisions are
  counted, not shown, until asked for.
* An RFI, NCR and change order that point at a drawing are listed on it, and
  flagged when the drawing is superseded.
* An open diary and draft minutes are not distributed as records.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import HTTPException


@pytest_asyncio.fixture(scope="module")
async def db_session():
    """An :class:`AsyncSession` backed by a freshly ``create_all``'d PostgreSQL."""
    from app.config import get_settings

    get_settings.cache_clear()
    import importlib
    import pkgutil

    import app.modules as _modules_pkg

    for _m in pkgutil.iter_modules(_modules_pkg.__path__):
        if not _m.ispkg:
            continue
        try:
            importlib.import_module(f"app.modules.{_m.name}.models")
        except ModuleNotFoundError:
            continue

    from app.database import Base, async_session_factory, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with async_session_factory() as session:
        yield session


async def _project(session) -> tuple[uuid.UUID, uuid.UUID]:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(email=f"rev-{uuid.uuid4().hex[:8]}@test.io", hashed_password="x", full_name="Rev Tester")
    session.add(user)
    await session.flush()
    project = Project(name="Revision Project", owner_id=user.id)
    session.add(project)
    await session.flush()
    return project.id, user.id


async def _doc(session, project_id, name="A-101.pdf", **fields):
    from app.modules.documents.models import Document

    fields.setdefault("mime_type", "application/pdf")
    doc = Document(project_id=project_id, name=name, **fields)
    session.add(doc)
    await session.flush()
    return doc


async def _chain(session, project_id):
    """Rev A (root, superseded) and Rev B (child of A, current)."""
    a = await _doc(session, project_id, "A-101 Rev A.pdf", revision_code="A", is_current_revision=False)
    b = await _doc(
        session, project_id, "A-101 Rev B.pdf", revision_code="B", is_current_revision=True, parent_document_id=a.id
    )
    return a, b


# ── documents: revision chain ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_make_current_supersedes_every_other_revision(db_session):
    from app.modules.documents import revisions

    project_id, _ = await _project(db_session)
    a, b = await _chain(db_session, project_id)

    demoted = await revisions.make_current(db_session, a)
    assert demoted == [b.id]
    assert a.is_current_revision is True
    assert b.is_current_revision is False
    members = await revisions.chain_members(db_session, b)
    assert [m.id for m in members if not revisions.is_superseded(m)] == [a.id]
    current = await revisions.current_revision(db_session, b)
    assert current is not None
    assert current.id == a.id


@pytest.mark.asyncio
async def test_legacy_null_flag_reads_as_current(db_session):
    from app.modules.documents import revisions

    project_id, _ = await _project(db_session)
    legacy = await _doc(db_session, project_id, is_current_revision=None)
    assert revisions.is_superseded(legacy) is False


@pytest.mark.asyncio
async def test_patch_guard_counts_the_chain_root(db_session):
    """Promoting a child while the root is still current is refused."""
    from app.modules.documents.schemas import DocumentUpdate
    from app.modules.documents.service import DocumentService

    project_id, _ = await _project(db_session)
    root = await _doc(db_session, project_id, "root.pdf", revision_code="A", is_current_revision=True)
    child = await _doc(
        db_session, project_id, "child.pdf", revision_code="B", is_current_revision=False, parent_document_id=root.id
    )
    with pytest.raises(HTTPException) as exc:
        await DocumentService(db_session).update_document(child.id, DocumentUpdate(is_current_revision=True))
    assert exc.value.status_code == 409


# ── documents: linked records ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_linked_records_reach_rfi_ncr_and_change_order(db_session):
    from app.modules.changeorders.models import ChangeOrder
    from app.modules.documents import revisions
    from app.modules.ncr.models import NCR
    from app.modules.rfi.models import RFI

    project_id, user_id = await _project(db_session)
    a, b = await _chain(db_session, project_id)

    rfi = RFI(
        project_id=project_id,
        rfi_number="RFI-001",
        subject="Beam depth at grid B4",
        question="Confirm depth",
        raised_by=user_id,
        linked_drawing_ids=[str(a.id)],
    )
    co = ChangeOrder(project_id=project_id, code="CO-001", title="Deeper beam", linked_rfi_ids=[])
    db_session.add_all([rfi, co])
    await db_session.flush()
    co.linked_rfi_ids = [str(rfi.id)]
    ncr = NCR(
        project_id=project_id,
        ncr_number="NCR-001",
        title="Wrong beam",
        description="d",
        ncr_type="workmanship",
        severity="minor",
        linked_document_ids=[str(a.id)],
    )
    db_session.add(ncr)
    await db_session.flush()

    old = await revisions.linked_records(db_session, a)
    assert [r["number"] for r in old["rfis"]] == ["RFI-001"]
    assert [r["number"] for r in old["ncrs"]] == ["NCR-001"]
    assert [r["number"] for r in old["change_orders"]] == ["CO-001"]
    # Rev A is superseded, so every record raised against it says so.
    assert all(r["on_superseded_revision"] for rows in old.values() for r in rows)

    # Nothing points at Rev B.
    new = await revisions.linked_records(db_session, b)
    assert new == {"rfis": [], "ncrs": [], "change_orders": []}


@pytest.mark.asyncio
async def test_ncr_refuses_a_document_of_another_project(db_session):
    from app.modules.ncr.service import NCRService

    mine, _ = await _project(db_session)
    other, _ = await _project(db_session)
    foreign = await _doc(db_session, other)
    own = await _doc(db_session, mine)
    svc = NCRService(db_session)

    assert await svc._check_documents(mine, [str(own.id), str(own.id)]) == [str(own.id)]
    with pytest.raises(HTTPException) as exc:
        await svc._check_documents(mine, [str(foreign.id)])
    assert exc.value.status_code == 400
    with pytest.raises(HTTPException):
        await svc._check_documents(mine, ["not-a-uuid"])


# ── file transmittals: exact revision ───────────────────────────────────


def _create(project_id, reason, *doc_ids, kind="document"):
    from app.modules.file_transmittals.schemas import TransmittalCreate, TransmittalItemCreate

    return TransmittalCreate(
        project_id=project_id,
        subject="Issue",
        reason_code=reason,
        items=[
            TransmittalItemCreate(
                file_kind=kind, file_id=i, canonical_name_snapshot="x.pdf", file_version_snapshot="client-says-9"
            )
            for i in doc_ids
        ],
    )


@pytest.mark.asyncio
async def test_transmittal_snapshot_is_the_registers_revision(db_session):
    from app.modules.file_transmittals.service import TransmittalService

    project_id, user_id = await _project(db_session)
    _, b = await _chain(db_session, project_id)
    draft = await TransmittalService(db_session).create_draft(
        _create(project_id, "for_review", str(b.id)), sender_id=str(user_id)
    )
    assert draft.items[0].file_version_snapshot == "B"


@pytest.mark.asyncio
async def test_superseded_revision_only_goes_for_record(db_session):
    from app.modules.file_transmittals.service import TransmittalService

    project_id, user_id = await _project(db_session)
    a, _ = await _chain(db_session, project_id)
    svc = TransmittalService(db_session)

    for reason in ("for_review", "for_approval", "for_information", "for_construction"):
        with pytest.raises(HTTPException) as exc:
            await svc.create_draft(_create(project_id, reason, str(a.id)), sender_id=str(user_id))
        assert exc.value.status_code == 409, reason

    kept = await svc.create_draft(_create(project_id, "for_record", str(a.id)), sender_id=str(user_id))
    assert kept.items[0].file_version_snapshot == "A"


@pytest.mark.asyncio
async def test_item_must_belong_to_the_project(db_session):
    from app.modules.file_transmittals.service import TransmittalService

    mine, user_id = await _project(db_session)
    other, _ = await _project(db_session)
    foreign = await _doc(db_session, other)
    svc = TransmittalService(db_session)

    for bad in (str(foreign.id), str(uuid.uuid4()), "doc-001"):
        with pytest.raises(HTTPException) as exc:
            await svc.create_draft(_create(mine, "for_review", bad), sender_id=str(user_id))
        assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_draft_cannot_be_sent_after_its_revision_was_superseded(db_session):
    from app.modules.documents import revisions
    from app.modules.file_transmittals.schemas import TransmittalRecipientCreate
    from app.modules.file_transmittals.service import TransmittalService

    project_id, user_id = await _project(db_session)
    a, b = await _chain(db_session, project_id)
    await revisions.make_current(db_session, a)  # Rev A is current now
    svc = TransmittalService(db_session)
    draft = await svc.create_draft(_create(project_id, "for_review", str(a.id)), sender_id=str(user_id))
    await svc.add_recipient(draft.id, TransmittalRecipientCreate(email="x@test.io"))

    await revisions.make_current(db_session, b)  # Rev B replaces it while the draft sits open
    with pytest.raises(HTTPException) as exc:
        await svc.send(draft.id)
    assert exc.value.status_code == 409
    assert (await svc.get(draft.id)).status == "draft"


@pytest.mark.asyncio
async def test_for_construction_needs_a_published_document(db_session):
    from app.modules.file_transmittals.service import TransmittalService

    project_id, user_id = await _project(db_session)
    shared = await _doc(db_session, project_id, "s.pdf", cde_state="shared")
    wip = await _doc(db_session, project_id, "w.pdf", cde_state="wip")
    published = await _doc(db_session, project_id, "p.pdf", cde_state="published")
    unmanaged = await _doc(db_session, project_id, "u.pdf")
    svc = TransmittalService(db_session)

    for blocked in (shared, wip):
        with pytest.raises(HTTPException) as exc:
            await svc.create_draft(_create(project_id, "for_construction", str(blocked.id)), sender_id=str(user_id))
        assert exc.value.status_code == 409
    for ok in (published, unmanaged):
        await svc.create_draft(_create(project_id, "for_construction", str(ok.id)), sender_id=str(user_id))


@pytest.mark.asyncio
async def test_sheet_item_follows_the_sheet_stack(db_session):
    from app.modules.documents.models import Sheet
    from app.modules.file_transmittals.service import TransmittalService

    project_id, user_id = await _project(db_session)
    old = Sheet(project_id=project_id, page_number=1, sheet_number="A-101", revision="1", is_current=False)
    new = Sheet(project_id=project_id, page_number=2, sheet_number="A-101", revision="2", is_current=True)
    db_session.add_all([old, new])
    await db_session.flush()
    svc = TransmittalService(db_session)

    with pytest.raises(HTTPException) as exc:
        await svc.create_draft(_create(project_id, "for_review", str(old.id), kind="sheet"), sender_id=str(user_id))
    assert exc.value.status_code == 409
    draft = await svc.create_draft(_create(project_id, "for_review", str(new.id), kind="sheet"), sender_id=str(user_id))
    assert draft.items[0].file_version_snapshot == "2"


@pytest.mark.asyncio
async def test_other_kinds_keep_the_callers_snapshot(db_session):
    from app.modules.file_transmittals.service import TransmittalService

    project_id, user_id = await _project(db_session)
    draft = await TransmittalService(db_session).create_draft(
        _create(project_id, "for_review", "photo-1", kind="photo"), sender_id=str(user_id)
    )
    assert draft.items[0].file_version_snapshot == "client-says-9"


# ── plan room: issued, current drawings ─────────────────────────────────


@pytest.mark.asyncio
async def test_plan_room_lists_issued_current_drawings(db_session):
    from app.modules.plan_room.service import PlanRoomService

    project_id, _ = await _project(db_session)
    old, new = await _chain(db_session, project_id)
    new.cde_state = "published"
    wip = await _doc(db_session, project_id, "wip.pdf", cde_state="wip")
    archived = await _doc(db_session, project_id, "arch.pdf", cde_state="archived")
    spreadsheet = await _doc(db_session, project_id, "boq.xlsx", mime_type="application/vnd.ms-excel")
    await db_session.flush()
    svc = PlanRoomService(db_session)

    res = await svc.list_drawings(project_id)
    ids = {d.id for d in res.items}
    assert ids == {str(new.id)}
    assert res.superseded_hidden == 1
    assert not ({str(wip.id), str(archived.id), str(spreadsheet.id), str(old.id)} & ids)

    with_old = await svc.list_drawings(project_id, include_superseded=True)
    by_id = {d.id: d for d in with_old.items}
    assert by_id[str(old.id)].is_current_revision is False
    assert by_id[str(old.id)].current_document_id == str(new.id)
    assert with_old.superseded_hidden == 0


@pytest.mark.asyncio
async def test_overlays_of_a_superseded_drawing_name_the_current_one(db_session):
    from app.modules.plan_room.service import PlanRoomService

    project_id, _ = await _project(db_session)
    old, new = await _chain(db_session, project_id)

    overlays = await PlanRoomService(db_session).get_overlays(old, 1)
    assert overlays.version.is_current_revision is False
    assert overlays.version.current_document_id == str(new.id)
    current = await PlanRoomService(db_session).get_overlays(new, 1)
    assert current.version.current_document_id is None


# ── record publishing: finished records only ────────────────────────────


@pytest.mark.asyncio
async def test_open_diary_is_not_published(monkeypatch):
    from app.modules.daily_diary import service as diary_module
    from app.modules.record_publishing import service as rp

    class _FakeDiary:
        def __init__(self, session):
            pass

        async def get_diary(self, diary_id):
            return SimpleNamespace(status="open", project_id=uuid.uuid4())

        async def generate_diary_pdf(self, diary_id):  # pragma: no cover - must not be reached
            raise AssertionError("an open diary must not be rendered")

    monkeypatch.setattr(diary_module, "DailyDiaryService", _FakeDiary)
    with pytest.raises(HTTPException) as exc:
        await rp._render_daily_diary(None, uuid.uuid4())
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_closed_diary_is_rendered(monkeypatch):
    from app.modules.daily_diary import service as diary_module
    from app.modules.record_publishing import service as rp

    project_id = uuid.uuid4()

    class _FakeDiary:
        def __init__(self, session):
            pass

        async def get_diary(self, diary_id):
            return SimpleNamespace(status="closed", project_id=project_id)

        async def generate_diary_pdf(self, diary_id):
            return b"%PDF-1.4 fake", "2026-11-24"

    monkeypatch.setattr(diary_module, "DailyDiaryService", _FakeDiary)
    rendered = await rp._render_daily_diary(None, uuid.uuid4())
    assert rendered.project_id == project_id
    assert rendered.pdf_bytes.startswith(b"%PDF")


@pytest.mark.asyncio
async def test_draft_minutes_are_not_published(monkeypatch):
    from app.modules.meetings import service as meetings_module
    from app.modules.record_publishing import service as rp

    class _FakeMeetings:
        def __init__(self, session):
            pass

        async def get_meeting(self, meeting_id):
            return SimpleNamespace(project_id=uuid.uuid4(), title="t", meeting_date="2026-11-24", meeting_number="1")

        async def get_minutes_row(self, meeting_id):
            return SimpleNamespace(status="draft", content={}, issued_at=None)

    monkeypatch.setattr(meetings_module, "MeetingService", _FakeMeetings)
    with pytest.raises(HTTPException) as exc:
        await rp._render_meeting_minutes(None, uuid.uuid4())
    assert exc.value.status_code == 409
