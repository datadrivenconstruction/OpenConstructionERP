# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The project handbook service and the data room against PostgreSQL.

Chapters come from the pinned catalogue, approval is four-eyes and freezes an immutable version, the
organisation chapter reads stakeholders and staffing live, and the governance folder tree materialises
into the documents module idempotently. Each test builds its own throwaway database.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.project_handbook import data_room
from app.modules.project_handbook.errors import HandbookError
from app.modules.project_handbook.permissions import register_project_handbook_permissions
from app.modules.project_handbook.service import ProjectHandbookService
from tests._pg import isolated_engine
from tests.pg.project_handbook_fixtures import actor, add_document, build_world, call

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def factory():
    register_project_handbook_permissions()
    async with isolated_engine() as engine:
        yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def test_the_handbook_lays_out_every_chapter_of_its_catalogue(factory) -> None:
    w = await build_world(factory)
    chapters = await call(w, "list_chapters", locale="de")
    assert len(chapters) == 15
    assert chapters[0]["code"] == "principles"
    assert chapters[0]["title"] == "Grundsätze und Ziele"
    assert {c["status"] for c in chapters} == {"draft"}
    assert all(c["owner_id"] == str(w.owner) for c in chapters)


async def test_laying_the_chapters_out_twice_changes_nothing(factory) -> None:
    w = await build_world(factory)
    first = await call(w, "sync_chapters")
    assert first == {"created": 0, "updated": 0}
    assert len(await call(w, "list_chapters")) == 15


async def test_an_empty_chapter_cannot_be_submitted_and_names_what_is_missing(factory) -> None:
    w = await build_world(factory)
    with pytest.raises(HandbookError) as err:
        await call(w, "submit", "principles", actor(w.owner))
    assert err.value.status_code == 422
    assert {v["code"] for v in err.value.violations} == {"chapter_empty"}


async def test_a_chapter_is_approved_by_someone_other_than_the_submitter(factory) -> None:
    w = await build_world(factory)
    await call(w, "patch_chapter", "principles", {"content": "Ziele des Projekts."}, actor(w.owner))
    await call(w, "submit", "principles", actor(w.owner))
    with pytest.raises(HandbookError) as same:
        await call(w, "approve", "principles", actor(w.owner, manage=True))
    assert same.value.status_code == 403
    assert same.value.code == "approver_is_submitter"
    row = await call(w, "approve", "principles", actor(w.decider, manage=True))
    assert (row.status, row.approved_version) == ("approved", 1)
    versions = await call(w, "versions", "principles")
    assert [v["version"] for v in versions] == [1]
    assert versions[0]["content"] == "Ziele des Projekts."


async def test_without_the_manage_right_nobody_approves(factory) -> None:
    w = await build_world(factory)
    await call(w, "patch_chapter", "principles", {"content": "Text"}, actor(w.owner))
    await call(w, "submit", "principles", actor(w.owner))
    with pytest.raises(HandbookError) as err:
        await call(w, "approve", "principles", actor(w.decider, manage=False))
    assert err.value.status_code == 403


async def test_editing_an_approved_chapter_opens_a_revision_and_keeps_the_approved_text(factory) -> None:
    w = await build_world(factory)
    await call(w, "patch_chapter", "principles", {"content": "Fassung eins"}, actor(w.owner))
    await call(w, "submit", "principles", actor(w.owner))
    await call(w, "approve", "principles", actor(w.decider, manage=True))
    row = await call(w, "patch_chapter", "principles", {"content": "Fassung zwei"}, actor(w.owner))
    assert (row.status, row.draft_version, row.approved_version) == ("revising", 2, 1)
    versions = await call(w, "versions", "principles")
    assert versions[0]["content"] == "Fassung eins"
    await call(w, "submit", "principles", actor(w.owner))
    await call(w, "approve", "principles", actor(w.decider, manage=True))
    assert [v["version"] for v in await call(w, "versions", "principles")] == [2, 1]


async def test_handing_an_approved_chapter_to_someone_else_opens_no_revision(factory) -> None:
    w = await build_world(factory)
    await call(w, "patch_chapter", "principles", {"content": "Fassung eins"}, actor(w.owner))
    await call(w, "submit", "principles", actor(w.owner))
    await call(w, "approve", "principles", actor(w.decider, manage=True))
    row = await call(w, "patch_chapter", "principles", {"owner_id": w.decider}, actor(w.owner))
    assert (row.status, row.draft_version, row.approved_version, row.owner_id) == ("approved", 1, 1, w.decider)
    with pytest.raises(HandbookError) as err:
        await call(w, "patch_chapter", "principles", {"owner_id": uuid.uuid4()}, actor(w.owner))
    assert (err.value.status_code, err.value.code) == (422, "owner_not_found")


async def test_a_chapter_in_review_cannot_be_edited_until_it_is_returned(factory) -> None:
    w = await build_world(factory)
    await call(w, "patch_chapter", "principles", {"content": "Text"}, actor(w.owner))
    await call(w, "submit", "principles", actor(w.owner))
    with pytest.raises(HandbookError) as err:
        await call(w, "patch_chapter", "principles", {"content": "Anderer Text"}, actor(w.owner))
    assert err.value.status_code == 409
    row = await call(w, "return_chapter", "principles", actor(w.decider, manage=True))
    assert row.status == "draft"


async def test_the_organisation_chapter_reads_staffing_live(factory) -> None:
    w = await build_world(factory)
    chapter = await call(w, "get_chapter", "organisation", locale="de")
    names = {s["source"] for s in chapter["linked"]}
    assert names == {"stakeholders", "staffing"}
    assert all(s["rows"] == [] for s in chapter["linked"])
    findings = await call(w, "findings")
    assert any(f["code"] == "linked_source_empty" and f["ref"] == "organisation" for f in findings)


async def test_the_readiness_counts_only_required_chapters(factory) -> None:
    w = await build_world(factory)
    ready = await call(w, "readiness")
    assert ready["required"] == 5
    assert ready["approved"] == 0
    await call(w, "patch_chapter", "principles", {"content": "Text"}, actor(w.owner))
    await call(w, "submit", "principles", actor(w.owner))
    await call(w, "approve", "principles", actor(w.decider, manage=True))
    ready = await call(w, "readiness")
    assert ready["approved"] == 1
    assert "principles" not in ready["open"]


async def test_the_data_room_needs_a_phase_model(factory) -> None:
    w = await build_world(factory)
    async with w.factory() as s:
        with pytest.raises(HandbookError) as err:
            await data_room.materialise(s, w.project_id)
    assert err.value.code == "no_governance_model"


async def test_materialising_the_data_room_is_idempotent(factory) -> None:
    from app.modules.documents.models import DocumentFolder

    w = await build_world(factory, governance=True)
    async with w.factory() as s:
        first = await data_room.materialise(s, w.project_id)
        await s.commit()
    # 174 catalogue folders plus one root folder for each of the eleven areas.
    assert first["created"] == 174 + 11
    assert first["folders"] == 185
    async with w.factory() as s:
        again = await data_room.materialise(s, w.project_id)
        await s.commit()
        total = (
            await s.execute(
                select(func.count()).select_from(DocumentFolder).where(DocumentFolder.project_id == w.project_id)
            )
        ).scalar_one()
    assert (again["created"], again["updated"]) == (0, 0)
    assert total == 185


async def test_a_hand_made_folder_is_never_rewritten_by_the_catalogue(factory) -> None:
    from app.modules.documents.models import DocumentFolder

    w = await build_world(factory, governance=True)
    async with w.factory() as s:
        s.add(
            DocumentFolder(
                project_id=w.project_id,
                code="m01_project_management/dev_data_room",
                name="Mein Ordner",
                source="manual",
                area_code="m01_project_management",
            )
        )
        await s.commit()
    async with w.factory() as s:
        await data_room.materialise(s, w.project_id)
        await s.commit()
        row = (
            await s.execute(
                select(DocumentFolder).where(
                    DocumentFolder.project_id == w.project_id,
                    DocumentFolder.code == "m01_project_management/dev_data_room",
                )
            )
        ).scalar_one()
    assert (row.name, row.source) == ("Mein Ordner", "manual")


async def test_a_document_lands_in_the_folder_of_the_area_that_hosts_its_subject(factory) -> None:
    w = await build_world(factory, governance=True)
    doc = await add_document(w, "Staffelplan.pdf")
    async with w.factory() as s:
        await data_room.materialise(s, w.project_id)
        folder = await data_room.place_document(s, w.project_id, doc, subject="staffing")
        await s.commit()
    assert folder.area_code == "m05_personnel"
    # The area's first chapter that names a folder decides: personnel files into the staffing needs folder.
    assert folder.code == "m05_personnel/dev_staffing_needs"
    async with w.factory() as s:
        tree = await ProjectHandbookService(s).data_room(w.project_id, w.manager)
    filed = {f["code"]: f for f in tree["folders"]}
    assert filed["m05_personnel/dev_staffing_needs"]["documents"] == 1
    assert filed["area/m05_personnel"]["documents_total"] == 1
    assert tree["unfiled"] == 0


async def test_placing_a_document_of_another_project_is_a_404(factory) -> None:
    w = await build_world(factory, governance=True)
    other = await build_world(factory, governance=True)
    stranger = await add_document(other, "Fremd.pdf")
    async with w.factory() as s:
        await data_room.materialise(s, w.project_id)
        with pytest.raises(HandbookError) as err:
            await data_room.place_document(
                s, w.project_id, stranger, folder_code="m01_project_management/dev_data_room"
            )
    assert err.value.status_code == 404


async def test_the_pdf_of_the_whole_handbook_is_a_pdf_in_the_readers_language(factory) -> None:
    from app.modules.project_handbook import export

    w = await build_world(factory)
    await call(w, "patch_chapter", "principles", {"content": "Ziele des Projekts."}, actor(w.owner))
    async with w.factory() as s:
        data = await ProjectHandbookService(s).export_data(w.project_id, "de")
    assert export.render(data, locale="de").startswith(b"%PDF")
    from app.core.register_export import record_text_lines

    lines = record_text_lines(export.handbook_document(data, locale="de"))
    assert "Projekthandbuch" in lines
    assert "Grundsätze und Ziele" in " ".join(lines)
