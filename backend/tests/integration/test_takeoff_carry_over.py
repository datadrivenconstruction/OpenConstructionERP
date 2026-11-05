"""Carry takeoff measurements onto a new drawing revision.

* Carry copies confirmed rows at the same coordinates, flagged ``needs_review``,
  with the scale re-checked against the new sheet; proposals are not carried.
* A second carry does not duplicate; an unrelated sheet is refused.
* Re-measure shows up in the compare as a per-position quantity delta.
* Unconfirmed copies raise the info rule; confirming releases the old link,
  so the superseded-revision warning clears.
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
    import app.modules.catalog.models  # noqa: F401
    import app.modules.documents.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.takeoff.models  # noqa: F401
    import app.modules.users.models  # noqa: F401
    from app.database import Base, engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


async def _seed(session):
    """Sheet A-101 rev A measured in takeoff; rev B registered and opened, calibrated at half the scale."""
    from app.modules.boq.models import BOQ, Position
    from app.modules.documents.models import Document, Sheet
    from app.modules.projects.models import Project
    from app.modules.takeoff.models import TakeoffDocument
    from app.modules.users.models import User

    user = User(email=f"carry-{uuid.uuid4().hex[:10]}@test.io", hashed_password="x", full_name="C", role="manager")
    session.add(user)
    await session.flush()
    project = Project(name="Carry", region="", currency="EUR", owner_id=user.id)
    session.add(project)
    await session.flush()
    doc_a = Document(project_id=project.id, name="Slab", category="drawing", revision_code="A")
    doc_b = Document(project_id=project.id, name="Slab", category="drawing", revision_code="B")
    session.add_all([doc_a, doc_b])
    await session.flush()
    sheet_a = Sheet(project_id=project.id, document_id=str(doc_a.id), page_number=1, sheet_number="A-101", revision="A")
    session.add(sheet_a)
    await session.flush()
    sheet_a.is_current = False
    sheet_b = Sheet(
        project_id=project.id,
        document_id=str(doc_b.id),
        page_number=1,
        sheet_number="A-101",
        revision="B",
        is_current=True,
        previous_version_id=sheet_a.id,
    )
    scales_a = {"byPage": {"1": {"pixelsPerUnit": 10.0, "unitLabel": "m"}}}
    scales_b = {"byPage": {"1": {"pixelsPerUnit": 20.0, "unitLabel": "m"}}}
    t_a = TakeoffDocument(
        filename="a.pdf",
        pages=1,
        project_id=project.id,
        owner_id=user.id,
        source_document_id=str(doc_a.id),
        page_scales=scales_a,
    )
    t_b = TakeoffDocument(
        filename="b.pdf",
        pages=1,
        project_id=project.id,
        owner_id=user.id,
        source_document_id=str(doc_b.id),
        page_scales=scales_b,
    )
    boq = BOQ(project_id=project.id, name="Carry bill", status="draft")
    session.add_all([sheet_b, t_a, t_b, boq])
    await session.flush()
    wall = Position(boq_id=boq.id, ordinal="01.001", description="Wall", unit="m", quantity="10", unit_rate="50")
    session.add(wall)
    await session.flush()
    return {
        "user": str(user.id),
        "project": project.id,
        "a": str(t_a.id),
        "b": str(t_b.id),
        "boq": boq.id,
        "wall": wall,
    }


async def _measure(service, seed, *, annotation: str, review_status: str = "confirmed"):
    from app.modules.takeoff.schemas import TakeoffMeasurementCreate

    m = await service.create_measurement(
        TakeoffMeasurementCreate(
            project_id=seed["project"],
            document_id=seed["a"],
            page=1,
            type="distance",
            annotation=annotation,
            points=[{"x": 0, "y": 0}, {"x": 100, "y": 0}],
            scale_pixels_per_unit=10.0,
            measurement_value=10.0,
            measurement_unit="m",
            linked_boq_position_id=str(seed["wall"].id),
        )
    )
    if review_status != "confirmed":
        await service.measurement_repo.update_fields(m.id, review_status=review_status, linked_boq_position_id=None)
    return m


@pytest.mark.asyncio
async def test_carry_review_compare_and_confirm():
    from app.modules.boq.drawing_refs import drawing_refs_for_boq
    from app.modules.takeoff.carry_over import NEEDS_REVIEW, carry_measurements, confirm_carried
    from app.modules.takeoff.service import TakeoffService

    async with async_session_factory() as session:
        seed = await _seed(session)
        service = TakeoffService(session)
        await _measure(service, seed, annotation="Wall W1")
        await _measure(service, seed, annotation="AI wall", review_status="proposed")

        refs = await drawing_refs_for_boq(session, seed["boq"], seed["project"])
        assert refs[str(seed["wall"].id)].outdated

        report = await carry_measurements(service, seed["project"], seed["a"], seed["b"], user_id=seed["user"])
        assert report["carried"] == 1
        assert report["skipped_unreviewed"] == 1
        assert report["revision_link"] == "register"
        assert report["scale_checks"] == {"changed": 1}

        copy = await service.measurement_repo.get_by_id(uuid.UUID(report["carried_ids"][0]))
        assert copy.document_id == seed["b"]
        assert copy.points == [{"x": 0, "y": 0}, {"x": 100, "y": 0}]
        assert float(copy.measurement_value) == pytest.approx(5.0)  # same points, the new sheet's scale
        assert copy.metadata_["carry_over"]["status"] == NEEDS_REVIEW
        assert copy.drawing_revision == "B"

        again = await carry_measurements(service, seed["project"], seed["a"], seed["b"], user_id=seed["user"])
        assert again["carried"] == 0 and again["already_carried"] == 1

        cmp = await service.compare_documents(seed["project"], seed["a"], seed["b"])
        row = next(r for r in cmp["measurement_rows"] if r["measurement_id"] == str(copy.id))
        assert row["carry_status"] == NEEDS_REVIEW and row["scale_check"] == "changed"
        delta = next(d for d in cmp["summary"]["position_deltas"] if d["position_id"] == str(seed["wall"].id))
        assert delta["delta_quantity"] == pytest.approx(-5.0)
        assert delta["boq_quantity"] == "10"
        assert cmp["summary"]["carried_needs_review"] == 1

        refs = await drawing_refs_for_boq(session, seed["boq"], seed["project"])
        assert refs[str(seed["wall"].id)].carried_unconfirmed == 1

        done = await confirm_carried(service, seed["project"], [str(copy.id)], user_id=seed["user"], push_quantity=True)
        assert done == {"confirmed": 1, "confirmed_ids": [str(copy.id)], "pushed": 1, "not_pending": 0}
        refs = await drawing_refs_for_boq(session, seed["boq"], seed["project"])
        entry = refs[str(seed["wall"].id)]
        assert entry.carried_unconfirmed == 0
        assert not entry.outdated  # the rev A original no longer feeds the position
        await session.refresh(seed["wall"])
        assert float(seed["wall"].quantity) == pytest.approx(5.0)
        await session.rollback()


@pytest.mark.asyncio
async def test_carry_refuses_same_document_and_foreign_project():
    from app.modules.takeoff.carry_over import carry_measurements
    from app.modules.takeoff.service import TakeoffService

    async with async_session_factory() as session:
        seed = await _seed(session)
        service = TakeoffService(session)
        with pytest.raises(HTTPException) as same:
            await carry_measurements(service, seed["project"], seed["a"], seed["a"], user_id=seed["user"])
        assert same.value.status_code == 422
        with pytest.raises(HTTPException) as foreign:
            await carry_measurements(service, uuid.uuid4(), seed["a"], seed["b"], user_id=seed["user"])
        assert foreign.value.status_code == 404
        await session.rollback()


@pytest.mark.asyncio
async def test_preview_writes_nothing_and_auto_carry_is_idempotent():
    from app.modules.takeoff.carry_over import CARRY_KEY, carry_measurements, preview_carry
    from app.modules.takeoff.service import TakeoffService

    async with async_session_factory() as session:
        seed = await _seed(session)
        service = TakeoffService(session)
        await _measure(service, seed, annotation="Wall W1")

        before = await service.measurement_repo.list_all_for_document(seed["project"], seed["b"], max_rows=100)
        preview = await preview_carry(service, seed["project"], seed["a"], seed["b"], align="auto")
        after = await service.measurement_repo.list_all_for_document(seed["project"], seed["b"], max_rows=100)
        assert len(before) == len(after) == 0
        assert preview["pages"][0]["new"] == 1 and preview["pages"][0]["method"] == "title"
        # No anchors on either sheet: geometry unverified, so never "high".
        assert preview["items"][0]["band"] == "review"

        first = await carry_measurements(
            service, seed["project"], seed["a"], seed["b"], user_id=seed["user"], align="auto", page_map={1: 1}
        )
        assert first["carried"] == 1
        copy = (await service.measurement_repo.list_all_for_document(seed["project"], seed["b"], max_rows=100))[0]
        carry = copy.metadata_[CARRY_KEY]
        assert carry["status"] == "needs_review" and carry["page_match"] == "manual"
        assert 0.6 <= carry["match_confidence"] < 0.85 and carry["from_page"] == 1

        again = await carry_measurements(
            service, seed["project"], seed["a"], seed["b"], user_id=seed["user"], align="auto"
        )
        assert again["carried"] == 0 and again["already_carried"] == 1
