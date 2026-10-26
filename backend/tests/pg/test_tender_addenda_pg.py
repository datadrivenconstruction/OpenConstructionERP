# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG:​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ an addendum revises the tender BOQ, moves the deadline and flags bids.

Publishing an addendum with a BOQ change starts a new revision; a bid priced
before it and a firm that did not acknowledge show up in the comparison and in
the ``tendering_addenda`` payload. Questions are numbered per package, answered,
published and promoted into an addendum.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

from datetime import date

import pytest
from fastapi import HTTPException

from app.modules.guarantees.models import Guarantee
from app.modules.tendering.addenda import AddendaService
from app.modules.tendering.schemas import AddendumBOQChange, AddendumCreate, BidCreate
from app.modules.tendering.service import TenderingService
from tests.pg.tender_award_fixtures import _bid, _bill, _package, _project

pytestmark = pytest.mark.asyncio

_RECIPIENTS = [
    {"id": "r1", "company_name": "Alpha", "email": "bids@alpha.test", "status": "sent"},
    {"id": "r2", "company_name": "Beta", "email": "bids@beta.test", "status": "sent"},
]


async def _setup(pg_session):
    project = await _project(pg_session)
    project.country_code = "DE"
    boq, pos = await _bill(pg_session, project, [("a", "01", "Wall", "m3", None), ("b", "02", "Slab", "m2", None)])
    package = await _package(
        pg_session,
        project,
        boq,
        metadata={"recipients": _RECIPIENTS, "scope_position_ids": [str(pos["a"].id), str(pos["b"].id)]},
    )
    package.deadline = "2026-11-30"
    package.status = "collecting"
    await pg_session.flush()
    return project, package, pos


async def test_boq_addendum_revises_bill_and_flags_old_bids(pg_session) -> None:
    _project_row, package, pos = await _setup(pg_session)
    svc = TenderingService(pg_session)
    old = await _bid(pg_session, package, "Alpha", "1000", [])
    old.metadata_ = {"recipient_id": "r1", "boq_revision_no": 0}

    draft = await svc.create_addendum(
        package.id,
        AddendumCreate(
            title="Slab quantity",
            boq_changes=[AddendumBOQChange(op="delete", position_id=str(pos["b"].id), quantity_before="10")],
            new_deadline="2026-12-07",
        ),
    )
    pkg = await svc.get_package(package.id)
    published = await svc.publish_addendum(pkg, draft.id, None)

    assert published.boq_revision_no == 1
    assert published.previous_deadline == "2026-11-30"
    assert sorted(published.pending_recipient_ids) == ["r1", "r2"]
    pkg = await svc.get_package(package.id)
    assert pkg.deadline == "2026-12-07"
    assert str(pos["b"].id) not in pkg.metadata_["scope_position_ids"]

    fresh = await svc.create_bid(
        package.id,
        BidCreate(company_name="Beta", total_amount="900", metadata={"recipient_id": "r2"}),
    )
    assert fresh.metadata_["boq_revision_no"] == 1
    await svc.acknowledge_addendum(await svc.get_package(package.id), draft.id, "r2", None)

    comparison = await svc.compare_bids(package.id)
    rows = {t["company_name"]: t for t in comparison.bid_totals}
    assert comparison.current_boq_revision == 1
    assert rows["Alpha"]["revision_current"] is False and rows["Alpha"]["missing_addenda"] == [1]
    assert rows["Beta"]["compliant"] is True


async def test_questions_flow_and_promote(pg_session) -> None:
    _project_row, package, _pos = await _setup(pg_session)
    side = AddendaService(pg_session)
    q1 = await side.ask(package, "Which concrete grade?", "r1", "bids@alpha.test", None)
    q2 = await side.ask(package, "Crane provided?", "r2", "", None)
    assert (q1.number, q2.number) == (1, 2)

    with pytest.raises(HTTPException):
        await side.publish_answer(package, q1, None)
    await side.answer(q1, "C30/37", None)
    await side.publish_answer(package, q1, None)
    public = await side.public_clarifications(package.id)
    assert public == [
        {"number": 1, "question": "Which concrete grade?", "answer": "C30/37", "published_at": q1.published_at}
    ]
    assert "recipient_id" not in public[0]


async def test_validation_payload_reads_bid_bonds_and_country_validity(pg_session) -> None:
    project, package, _pos = await _setup(pg_session)
    bid = await _bid(pg_session, package, "Alpha", "1000", [])
    pg_session.add(
        Guarantee(
            project_id=project.id,
            reference="BB-1",
            guarantee_type="bid_bond",
            status="issued",
            tender_id=package.id,
            bid_id=bid.id,
            expiry_date=date(2026, 12, 15),
        )
    )
    await pg_session.flush()
    data = await AddendaService(pg_session).validation_data(package, [bid])
    assert data["rules"]["country_code"] == "DE"
    assert data["bid_validity_until"] == "2026-12-30"  # 30 days after closing (DE)
    assert data["bonds"][0]["expiry_date"] == "2026-12-15"
