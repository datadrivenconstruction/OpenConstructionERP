"""PG: ​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠a spreadsheet-mode sheet edit writes every row or none.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.boq.models import BOQ, BOQMarkup, Position
from app.modules.boq.schemas import SheetEditRequest
from app.modules.boq.service import BOQService
from app.modules.projects.models import Project
from app.modules.users.models import User


async def _bill(session) -> dict:
    owner = User(email=f"sheet-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x", full_name="Sheet")
    session.add(owner)
    await session.flush()
    project = Project(name="Sheet", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="Sheet bill")
    session.add(boq)
    await session.flush()
    rows = [
        Position(
            boq_id=boq.id,
            ordinal="01.001",
            description="Concrete",
            unit="m3",
            quantity="10",
            unit_rate="100",
            total="1000",
            sort_order=1,
        ),
        Position(
            boq_id=boq.id,
            ordinal="01.002",
            description="Rebar",
            unit="kg",
            quantity="3",
            unit_rate="1.10",
            total="3.30",
            sort_order=2,
        ),
    ]
    session.add_all(rows)
    session.add(BOQMarkup(boq_id=boq.id, name="Overhead", percentage="10", sort_order=1, is_active=True))
    await session.flush()
    return {"owner": owner.id, "boq": boq.id, "ids": [r.id for r in rows]}


@pytest.mark.asyncio
async def test_sheet_edit_writes_every_row_and_totals_stay_exact(pg_session) -> None:
    bill = await _bill(pg_session)
    service = BOQService(pg_session)
    a, b = bill["ids"]
    req = SheetEditRequest(
        edits=[
            {"id": a, "version": 0, "fields": {"quantity": "12.5", "metadata": {"formula": "=10+2.5"}}},
            {"id": b, "version": 0, "fields": {"unit_rate": "0.1", "description": "Rebar B500"}},
        ]
    )
    rows, log_id = await service.apply_sheet_edits(bill["boq"], req, actor_id=bill["owner"])
    assert [r.id for r in rows] == [a, b]
    assert all(int(r.version) == 1 for r in rows)
    assert log_id is not None
    totals = await service.get_boq_with_positions(bill["boq"])
    # 12.5 * 100 + 3 * 0.1 = 1250.3, plus 10 % overhead, with no float drift.
    assert totals.direct_cost_total == Decimal("1250.30")
    assert totals.grand_total == Decimal("1375.33")
    first = next(p for p in totals.positions if p.id == a)
    assert first.metadata.get("formula") == "=10+2.5"


@pytest.mark.asyncio
async def test_one_stale_row_refuses_the_whole_batch(pg_session) -> None:
    bill = await _bill(pg_session)
    service = BOQService(pg_session)
    a, b = bill["ids"]
    req = SheetEditRequest(
        edits=[
            {"id": a, "version": 0, "fields": {"quantity": "99"}},
            {"id": b, "version": 7, "fields": {"quantity": "99"}},
        ]
    )
    with pytest.raises(HTTPException) as err:
        await service.apply_sheet_edits(bill["boq"], req, actor_id=bill["owner"])
    assert err.value.status_code == 409
    assert err.value.detail["ids"] == [str(b)]
    untouched = await pg_session.get(Position, a)
    assert Decimal(str(untouched.quantity)) == Decimal("10")


@pytest.mark.asyncio
async def test_the_endpoint_answers_with_versions_exact_totals_and_a_validation_verdict(pg_session) -> None:
    from app.modules.boq.router import sheet_edit_positions

    bill = await _bill(pg_session)
    service = BOQService(pg_session)
    a, _ = bill["ids"]
    owner = str(bill["owner"])
    result = await sheet_edit_positions(
        bill["boq"],
        SheetEditRequest(edits=[{"id": a, "version": 0, "fields": {"unit_rate": "100.10"}}]),
        owner,
        {"sub": owner, "role": "user"},
        pg_session,
        service,
    )
    assert result.rows[0].version == 1
    assert result.rows[0].total == Decimal("1001")
    assert result.direct_cost_total == Decimal("1004.30")
    assert result.grand_total == Decimal("1104.73")
    assert result.validation_status is not None
