# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Drawing traceability of BOQ lines.

* A takeoff measurement records the sheet number, title and revision it was taken on.
* A position derives its source drawings from the measurements linked to it.
* Registering a newer revision of that sheet flags the position, with a compare pair.
* The ``boq.drawing.*`` validation rules, the export line, and the access guard of the routes.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException

from app.database import async_session_factory


@pytest_asyncio.fixture(scope="module", autouse=True)
async def _schema():
    import app.modules.boq.models  # noqa: F401
    import app.modules.documents.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.takeoff.models  # noqa: F401
    import app.modules.users.models  # noqa: F401
    from app.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


async def _seed_user(session) -> uuid.UUID:
    from app.modules.users.models import User

    user = User(
        email=f"drw-{uuid.uuid4().hex[:10]}@test.io",
        hashed_password="x",
        full_name="Drawing Tester",
        role="manager",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    return user.id


async def _seed(session):
    """Project, a sheet A-101 rev A opened in takeoff, a bill with two positions."""
    from app.modules.boq.models import BOQ, Position
    from app.modules.documents.models import Document, Sheet
    from app.modules.projects.models import Project
    from app.modules.takeoff.models import TakeoffDocument

    owner = await _seed_user(session)
    project = Project(name="Drawing refs", region="", currency="EUR", owner_id=owner)
    session.add(project)
    await session.flush()
    doc = Document(project_id=project.id, name="Ground floor slab", category="drawing", revision_code="A")
    session.add(doc)
    await session.flush()
    sheet = Sheet(
        project_id=project.id,
        document_id=str(doc.id),
        page_number=1,
        sheet_number="A-101",
        sheet_title="Ground floor slab",
        revision="A",
        is_current=True,
    )
    tdoc = TakeoffDocument(filename="a101.pdf", project_id=project.id, owner_id=owner, source_document_id=str(doc.id))
    boq = BOQ(project_id=project.id, name="RCC works", status="draft")
    session.add_all([sheet, tdoc, boq])
    await session.flush()
    slab = Position(boq_id=boq.id, ordinal="01.001", description="RCC slab", unit="m3", quantity="0", unit_rate="0")
    manual = Position(
        boq_id=boq.id,
        ordinal="01.002",
        description="Lintels",
        unit="m",
        quantity="0",
        unit_rate="0",
        metadata_={"drawing_ref": "S-200"},
    )
    session.add_all([slab, manual])
    await session.flush()
    return {
        "owner": owner,
        "project": project.id,
        "doc": doc,
        "sheet": sheet,
        "tdoc": tdoc,
        "boq": boq.id,
        "slab": slab.id,
        "manual": manual.id,
    }


async def _measure(session, seed):
    from app.modules.takeoff.schemas import TakeoffMeasurementCreate
    from app.modules.takeoff.service import TakeoffService

    return await TakeoffService(session).create_measurement(
        TakeoffMeasurementCreate(
            project_id=seed["project"],
            document_id=str(seed["tdoc"].id),
            page=1,
            type="count",
            count_value=4,
            measurement_unit="pcs",
            points=[{"x": 1, "y": 1}],
            linked_boq_position_id=str(seed["slab"]),
        )
    )


@pytest.mark.asyncio
async def test_measurement_records_sheet_and_revision():
    async with async_session_factory() as session:
        seed = await _seed(session)
        m = await _measure(session, seed)
        assert m.drawing_document_id == str(seed["doc"].id)
        assert m.drawing_sheet_id == str(seed["sheet"].id)
        assert (m.drawing_number, m.drawing_title, m.drawing_revision) == ("A-101", "Ground floor slab", "A")
        await session.rollback()


@pytest.mark.asyncio
async def test_position_derives_refs_and_flags_a_newer_revision():
    from app.modules.boq.drawing_refs import drawing_refs_for_boq
    from app.modules.documents.models import Document, Sheet
    from app.modules.takeoff.models import TakeoffDocument

    async with async_session_factory() as session:
        seed = await _seed(session)
        await _measure(session, seed)
        await _measure(session, seed)
        refs = await drawing_refs_for_boq(session, seed["boq"], seed["project"])
        slab = refs[str(seed["slab"])]
        assert len(slab.refs) == 1
        assert slab.refs[0].measurement_count == 2
        assert slab.refs[0].revision == "A"
        assert not slab.outdated
        assert slab.export_text() == "A-101 rev A"
        manual = refs[str(seed["manual"])]
        assert manual.manual == {"drawing_ref": "S-200", "drawing_revision": None}

        # The register stacks rev B of A-101 on top of rev A.
        new_doc = Document(project_id=seed["project"], name="Ground floor slab", category="drawing", revision_code="B")
        session.add(new_doc)
        await session.flush()
        seed["sheet"].is_current = False
        new_sheet = Sheet(
            project_id=seed["project"],
            document_id=str(new_doc.id),
            page_number=1,
            sheet_number="A-101",
            revision="B",
            is_current=True,
            previous_version_id=seed["sheet"].id,
        )
        new_tdoc = TakeoffDocument(
            filename="a101b.pdf", project_id=seed["project"], owner_id=seed["owner"], source_document_id=str(new_doc.id)
        )
        session.add_all([new_sheet, new_tdoc])
        await session.flush()

        refs = await drawing_refs_for_boq(session, seed["boq"], seed["project"])
        ref = refs[str(seed["slab"])].refs[0]
        assert ref.outdated
        assert ref.current_revision == "B"
        assert ref.compare == {"from_document_id": str(seed["tdoc"].id), "to_document_id": str(new_tdoc.id)}
        assert refs[str(seed["slab"])].outdated
        await session.rollback()


@pytest.mark.asyncio
async def test_gaeb_and_export_rows_carry_the_drawing_line():
    from app.modules.boq.drawing_refs import drawing_refs_for_boq, stamp_export_text
    from app.modules.boq.router import build_gaeb_xml
    from app.modules.boq.service import BOQService

    async with async_session_factory() as session:
        seed = await _seed(session)
        await _measure(session, seed)
        data = await BOQService(session).get_boq_structured_for_export(seed["boq"])
        stamp_export_text(data, await drawing_refs_for_boq(session, seed["boq"], seed["project"]))
        xml = build_gaeb_xml(data, project_name="Drawing refs", project_currency="EUR", gaeb_format="x83")
        assert "Drawing: A-101 rev A" in xml
        assert "Drawing: S-200" in xml
        await session.rollback()


@pytest.mark.asyncio
async def test_routes_refuse_a_foreign_bill():
    from app.modules.takeoff.router import ManualDrawingRefRequest, boq_drawing_refs, set_position_drawing_ref

    async with async_session_factory() as session:
        seed = await _seed(session)
        stranger = await _seed_user(session)
        await session.commit()
    # Each call in its own session, as each request has one.
    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as read_exc:
            await boq_drawing_refs(seed["boq"], outdated_only=False, user_id=str(stranger), session=session)
        assert read_exc.value.status_code == 404
    async with async_session_factory() as session:
        with pytest.raises(HTTPException) as write_exc:
            await set_position_drawing_ref(
                seed["boq"],
                seed["slab"],
                ManualDrawingRefRequest(drawing_ref="X-1", drawing_revision="1"),
                user_id=str(stranger),
                session=session,
            )
        assert write_exc.value.status_code == 404
    async with async_session_factory() as session:
        own = await boq_drawing_refs(seed["boq"], outdated_only=False, user_id=str(seed["owner"]), session=session)
        assert [i["ordinal"] for i in own["items"]] == ["01.002"]
        entry = await set_position_drawing_ref(
            seed["boq"],
            seed["slab"],
            ManualDrawingRefRequest(drawing_ref="S-300", drawing_revision="2"),
            user_id=str(seed["owner"]),
            session=session,
        )
        assert entry["manual"] == {"drawing_ref": "S-300", "drawing_revision": "2"}


def _ctx(refs: dict) -> object:
    from app.core.validation.engine import ValidationContext

    positions = [{"id": pid, "ordinal": f"0{i}", "type": "position"} for i, pid in enumerate(refs, 1)]
    return ValidationContext(data={"positions": positions, "drawing_refs": refs})


@pytest.mark.asyncio
async def test_drawing_validation_rules():
    from app.modules.boq.validators import (
        ManualDrawingRefWithoutRevision,
        PositionOnSupersededDrawing,
        TakeoffQuantityWithoutDrawingRevision,
    )

    refs = {
        "p1": {"unrevised_measurements": 2, "refs": [], "manual": None},
        "p2": {
            "unrevised_measurements": 0,
            "refs": [{"drawing_number": "A-101", "revision": "A", "current_revision": "B", "outdated": True}],
        },
        "p3": {"unrevised_measurements": 0, "refs": [], "manual": {"drawing_ref": "S-200", "drawing_revision": None}},
        "p4": {"unrevised_measurements": 0, "refs": [], "manual": {"drawing_ref": "S-200", "drawing_revision": "2"}},
    }
    ctx = _ctx(refs)
    assert [r.element_ref for r in await TakeoffQuantityWithoutDrawingRevision().validate(ctx)] == ["p1"]
    superseded = await PositionOnSupersededDrawing().validate(ctx)
    assert [r.element_ref for r in superseded] == ["p2"]
    assert "A-101" in superseded[0].message
    assert [r.element_ref for r in await ManualDrawingRefWithoutRevision().validate(ctx)] == ["p3"]
