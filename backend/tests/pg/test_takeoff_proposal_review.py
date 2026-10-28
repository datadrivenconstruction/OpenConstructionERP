"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: the takeoff proposal review queue is durable and server-authoritative.

The offline detectors used to hand candidates to the canvas and keep nothing,
so a rejection was a local drop and a reload resurrected everything the
estimator had already dismissed. These tests run against a REAL PostgreSQL
cluster and pin the two properties that make the queue worth having:

* a review decision is a row, so it survives a reload and a colleague opening
  the same document sees it;
* the billed quantity is always re-derived from geometry on the server, so an
  edit-then-accept cannot talk the server into a number the shape does not
  support (Audit B8).

JSONB matters here: ``metadata_`` carries the reviewer stamp and the detector
provenance, and the grouped review-status count is a real SQL ``GROUP BY``.
Neither behaves identically on SQLite, which is why this sits in the PG lane.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.modules.projects.models import Project
from app.modules.takeoff.models import TakeoffDocument, TakeoffMeasurement
from app.modules.takeoff.service import TakeoffService
from app.modules.users.models import User

# A 10x10 pixel square at 1 pixel per unit: area 100, unambiguous by hand.
SQUARE = [{"x": 0.0, "y": 0.0}, {"x": 10.0, "y": 0.0}, {"x": 10.0, "y": 10.0}, {"x": 0.0, "y": 10.0}]
# Half the width, so the honest recomputed area is 50.
HALF_SQUARE = [{"x": 0.0, "y": 0.0}, {"x": 5.0, "y": 0.0}, {"x": 5.0, "y": 10.0}, {"x": 0.0, "y": 10.0}]


async def _seed_document(session) -> TakeoffDocument:
    """Insert an owner, a project and one takeoff document."""
    owner = User(email=f"takeoff-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(owner)
    await session.flush()

    project = Project(name="Proposal review", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()

    doc = TakeoffDocument(
        filename="sheet.pdf",
        pages=1,
        size_bytes=1024,
        project_id=project.id,
        owner_id=owner.id,
    )
    session.add(doc)
    await session.flush()
    return doc


def _candidate(points: list[dict], value: float, *, confidence: float = 0.7) -> dict:
    return {
        "type": "area",
        "points": points,
        "value": value,
        "dimension": "area",
        "confidence": confidence,
        "reason": "Closed polygon region in the vector layer",
    }


@pytest.mark.asyncio
async def test_detector_candidates_land_as_proposed_rows(pg_session) -> None:
    """Persisting stamps provenance and leaves the rows unreviewed."""
    doc = await _seed_document(pg_session)
    doc_id = str(doc.id)
    svc = TakeoffService(pg_session)

    out = await svc._persist_proposals(
        doc,
        1,
        [_candidate(SQUARE, 100.0), _candidate(HALF_SQUARE, 50.0, confidence=0.55)],
        detector="vector_recognize",
        scale_pixels_per_unit=1.0,
        user_id="tester",
    )

    assert [c["measurement_id"] for c in out], "every candidate carries its row id"
    rows = await svc.measurement_repo.list_proposals_for_document(doc_id)
    assert len(rows) == 2
    for row in rows:
        assert row.review_status == "proposed"
        assert row.source == "ai_takeoff"
        assert row.metadata_["detector"] == "vector_recognize"
        assert row.confidence is not None


@pytest.mark.asyncio
async def test_stored_value_is_derived_from_geometry_not_from_the_candidate(pg_session) -> None:
    """A detector claiming the wrong number does not get to keep it."""
    doc = await _seed_document(pg_session)
    doc_id = str(doc.id)
    svc = TakeoffService(pg_session)

    # The candidate claims 9999 over a shape that is honestly 100.
    await svc._persist_proposals(
        doc,
        1,
        [_candidate(SQUARE, 9999.0)],
        detector="vector_recognize",
        scale_pixels_per_unit=1.0,
        user_id="tester",
    )

    (row,) = await svc.measurement_repo.list_proposals_for_document(doc_id)
    assert float(row.measurement_value) == pytest.approx(100.0), "shoelace over the points, not the claim"


@pytest.mark.asyncio
async def test_rejection_is_kept_not_deleted(pg_session) -> None:
    """The record of what a human turned down is the point of the queue."""
    doc = await _seed_document(pg_session)
    doc_id = str(doc.id)
    svc = TakeoffService(pg_session)
    out = await svc._persist_proposals(
        doc,
        1,
        [_candidate(SQUARE, 100.0)],
        detector="vector_recognize",
        scale_pixels_per_unit=1.0,
        user_id="tester",
    )
    mid = uuid.UUID(out[0]["measurement_id"])

    updated = await svc.review_measurement(mid, action="reject", user_id="reviewer")

    assert updated.review_status == "rejected"
    assert updated.metadata_["reviewed_by"] == "reviewer"
    assert updated.metadata_["reviewed_at"], "the decision is timestamped"
    # Still in the database, just out of the pending queue.
    assert await svc.measurement_repo.get_by_id(mid) is not None
    assert await svc.measurement_repo.list_proposals_for_document(doc_id) == []


@pytest.mark.asyncio
async def test_edit_then_accept_recomputes_from_the_corrected_geometry(pg_session) -> None:
    """A correction cannot smuggle in a quantity the new shape does not support."""
    doc = await _seed_document(pg_session)
    doc_id = str(doc.id)
    svc = TakeoffService(pg_session)
    out = await svc._persist_proposals(
        doc,
        1,
        [_candidate(SQUARE, 100.0)],
        detector="vector_recognize",
        scale_pixels_per_unit=1.0,
        user_id="tester",
    )
    mid = uuid.UUID(out[0]["measurement_id"])

    updated = await svc.review_measurement(mid, action="accept", points=HALF_SQUARE, user_id="reviewer")

    assert updated.review_status == "confirmed"
    assert float(updated.measurement_value) == pytest.approx(50.0), "half the width is half the area"
    assert updated.metadata_["geometry_edited"] is True


@pytest.mark.asyncio
async def test_reviewing_twice_is_a_conflict(pg_session) -> None:
    """Two reviewers racing on one proposal must not silently overwrite."""
    doc = await _seed_document(pg_session)
    doc_id = str(doc.id)
    svc = TakeoffService(pg_session)
    out = await svc._persist_proposals(
        doc,
        1,
        [_candidate(SQUARE, 100.0)],
        detector="vector_recognize",
        scale_pixels_per_unit=1.0,
        user_id="tester",
    )
    mid = uuid.UUID(out[0]["measurement_id"])

    await svc.review_measurement(mid, action="accept", user_id="first")
    with pytest.raises(HTTPException) as exc:
        await svc.review_measurement(mid, action="reject", user_id="second")
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_queue_counts_cover_the_document_even_when_scoped_to_a_page(pg_session) -> None:
    """Progress must not change meaning when the reviewer filters to one page."""
    doc = await _seed_document(pg_session)
    doc_id = str(doc.id)
    svc = TakeoffService(pg_session)
    await svc._persist_proposals(
        doc,
        1,
        [_candidate(SQUARE, 100.0)],
        detector="vector_recognize",
        scale_pixels_per_unit=1.0,
        user_id="tester",
    )
    out2 = await svc._persist_proposals(
        doc,
        2,
        [_candidate(SQUARE, 100.0), _candidate(HALF_SQUARE, 50.0)],
        detector="vector_recognize",
        scale_pixels_per_unit=1.0,
        user_id="tester",
    )
    await svc.review_measurement(uuid.UUID(out2[0]["measurement_id"]), action="accept", user_id="reviewer")

    scoped = await svc.list_document_proposals(doc_id, page=2)

    assert len(scoped["proposals"]) == 1, "only the still-pending row on page 2"
    assert scoped["proposed_count"] == 2, "document-wide, not page-wide"
    assert scoped["confirmed_count"] == 1
    assert scoped["reviewed_count"] == 1
    assert scoped["total_count"] == 3


@pytest.mark.asyncio
async def test_a_manual_measurement_never_enters_the_queue(pg_session) -> None:
    """Hand-drawn work is confirmed by construction and must not need review."""
    doc = await _seed_document(pg_session)
    doc_id = str(doc.id)
    svc = TakeoffService(pg_session)
    pg_session.add(
        TakeoffMeasurement(
            project_id=doc.project_id,
            document_id=str(doc.id),
            page=1,
            type="area",
            group_name="Manual",
            points=SQUARE,
            measurement_value=100.0,
            created_by="tester",
        )
    )
    await pg_session.flush()

    assert await svc.measurement_repo.list_proposals_for_document(doc_id) == []
    counts = await svc.measurement_repo.count_by_review_status(doc_id)
    assert counts == {"confirmed": 1}
