"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: a full-BOQ read loads the bill's positions once, and answers as before.

``get_boq_with_positions`` backs the BOQ editor's GET and a dozen exports. It
used to load the positions three times per request: ``session.get(BOQ)``
pulled them (and the markups) through the ``selectin`` relationships, the
sorted read pulled them again, and ``compute_boq_totals`` a third time. On a
2100-line bill each pass decodes about 2 MB of jsonb on the event loop.

Now the header is a plain column select and the one sorted read is handed to
the totals. These tests pin the statement count, prove the counter sees the
old three-pass shape, and check the answer is the one the old path gave, field
by field, on a bill whose totals are not trivial (a markup, an inactive markup,
a section header and a foreign-currency line).

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect

from app.modules.boq.models import BOQ, BOQMarkup, Position
from app.modules.boq.schemas import BOQWithPositions
from app.modules.boq.service import (
    BOQService,
    _is_section,
    _round_currency,
    build_position_response,
    is_empty_position,
)
from app.modules.projects.models import Project
from app.modules.users.models import User

_FROM_POSITION = re.compile(r"\bFROM\s+oe_boq_position\b", re.IGNORECASE)
_FROM_MARKUP = re.compile(r"\bFROM\s+oe_boq_markup\b", re.IGNORECASE)


async def _priced_bill(session) -> dict[str, Any]:
    """A EUR project with a USD rate, one section, four lines and two markups."""
    owner = User(email=f"fullread-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x", full_name="Full read")
    session.add(owner)
    await session.flush()
    project = Project(
        name="Full read",
        owner_id=owner.id,
        currency="EUR",
        fx_rates=[{"code": "USD", "rate": "0.9"}],
    )
    session.add(project)
    await session.flush()
    boq = BOQ(
        project_id=project.id,
        name="Priced bill",
        description="Header under test",
        metadata_={"source": "test", "nested": {"k": [1, 2]}},
        estimate_type="detailed",
        base_date="2026-01-01",
    )
    session.add(boq)
    await session.flush()

    section = Position(
        boq_id=boq.id, ordinal="01", description="Earthworks", unit="", quantity="0", unit_rate="0", sort_order=0
    )
    session.add(section)
    await session.flush()
    lines = [
        Position(
            boq_id=boq.id,
            parent_id=section.id,
            ordinal="01.002",
            description="Excavation",
            unit="m3",
            quantity="10",
            unit_rate="25",
            total="250",
            sort_order=2,
        ),
        # Same sort_order as the next one: the ordinal breaks the tie.
        Position(
            boq_id=boq.id,
            parent_id=section.id,
            ordinal="01.001",
            description="Imported pump, priced in USD",
            unit="pcs",
            quantity="2",
            unit_rate="500",
            total="1000",
            metadata_={"currency": "USD"},
            sort_order=1,
        ),
        Position(
            boq_id=boq.id,
            parent_id=section.id,
            ordinal="01.003",
            description="Backfill",
            unit="m3",
            quantity="4",
            unit_rate="12.5",
            total="50",
            sort_order=1,
        ),
        # A placeholder row: listed, not counted.
        Position(boq_id=boq.id, ordinal="02.001", description="", unit="m2", sort_order=3),
    ]
    session.add_all(lines)
    session.add_all(
        [
            BOQMarkup(boq_id=boq.id, name="Overhead", percentage="10", sort_order=1, is_active=True),
            BOQMarkup(boq_id=boq.id, name="Switched off", percentage="50", sort_order=2, is_active=False),
        ]
    )
    await session.flush()
    return {"boq_id": boq.id, "section_id": section.id, "line_ids": [p.id for p in lines]}


@contextmanager
def _statements(session) -> Iterator[list[str]]:
    """Every SQL statement the session's connection sends while the block runs."""
    seen: list[str] = []
    engine = session.bind.engine.sync_engine

    def _record(_conn, _cursor, statement, _params, _context, _many) -> None:
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", _record)


def _selects_from(statements: list[str], pattern: re.Pattern[str]) -> list[str]:
    return [s for s in statements if s.lstrip().upper().startswith("SELECT") and pattern.search(s)]


async def _old_path(service: BOQService, boq_id: uuid.UUID) -> BOQWithPositions:
    """The response exactly as ``get_boq_with_positions`` built it before the change."""
    boq = await service.get_boq(boq_id)
    positions = await service.position_repo.list_all_for_boq(boq_id)
    responses = [build_position_response(p) for p in positions]
    count = sum(1 for p in positions if not _is_section(p) and not is_empty_position(p))
    money = (await service.compute_boq_totals([boq_id]))[boq_id]
    return BOQWithPositions(
        id=boq.id,
        project_id=boq.project_id,
        name=boq.name,
        description=boq.description,
        status=boq.status,
        metadata_=boq.metadata_,
        created_at=boq.created_at,
        updated_at=boq.updated_at,
        is_locked=boq.is_locked,
        approved_by=boq.approved_by,
        approved_at=boq.approved_at,
        base_date=boq.base_date,
        estimate_type=boq.estimate_type,
        parent_estimate_id=boq.parent_estimate_id,
        variation_request_id=boq.variation_request_id,
        positions=responses,
        direct_cost_total=_round_currency(Decimal(str(money["direct_cost"]))),
        markups_total=_round_currency(Decimal(str(money["markups_total"]))),
        grand_total=_round_currency(Decimal(str(money["grand_total"]))),
        position_count=count,
    )


# ── One read of the positions ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_full_boq_read_selects_the_positions_once(pg_session) -> None:
    bill = await _priced_bill(pg_session)
    pg_session.expunge_all()
    service = BOQService(pg_session)

    with _statements(pg_session) as sent:
        await service.get_boq_with_positions(bill["boq_id"])

    position_reads = _selects_from(sent, _FROM_POSITION)
    markup_reads = _selects_from(sent, _FROM_MARKUP)
    assert len(position_reads) == 1, f"{len(position_reads)} SELECTs read oe_boq_position: {position_reads}"
    assert len(markup_reads) <= 1, f"{len(markup_reads)} SELECTs read oe_boq_markup: {markup_reads}"

    # The counter is not blind: the old sequence reads the positions at least
    # three times (entity selectin, sorted read, totals) and the markups twice.
    pg_session.expunge_all()
    with _statements(pg_session) as old_sent:
        await _old_path(service, bill["boq_id"])
    assert len(_selects_from(old_sent, _FROM_POSITION)) >= 3
    assert len(_selects_from(old_sent, _FROM_MARKUP)) >= 2


# ── The same answer ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_header_columns_come_back_as_the_entity_carries_them(pg_session) -> None:
    """Keys are attribute names (``metadata_``, not the column ``metadata``), types unchanged."""
    bill = await _priced_bill(pg_session)
    pg_session.expunge_all()
    service = BOQService(pg_session)

    header = await service.boq_repo.get_header(bill["boq_id"])
    entity = await pg_session.get(BOQ, bill["boq_id"])

    assert header is not None
    assert "metadata_" in header
    assert "metadata" not in header
    for key in header:
        value = header[key]
        expected = getattr(entity, key)
        assert value == expected, key
        assert type(value) is type(expected), f"{key}: {type(value).__name__} vs {type(expected).__name__}"
    assert isinstance(header["id"], uuid.UUID)
    assert isinstance(header["project_id"], uuid.UUID)
    assert isinstance(header["metadata_"], dict)
    assert header["metadata_"] == {"source": "test", "nested": {"k": [1, 2]}}
    assert isinstance(header["created_at"], datetime)
    assert header["created_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_a_full_boq_read_answers_as_the_old_path_did(pg_session) -> None:
    bill = await _priced_bill(pg_session)
    pg_session.expunge_all()
    service = BOQService(pg_session)

    got = await service.get_boq_with_positions(bill["boq_id"])
    pg_session.expunge_all()
    want = await _old_path(service, bill["boq_id"])

    # The bill is not trivial: USD line converted, markup applied, inactive one ignored.
    # 250 + 50 EUR + 1000 USD * 0.9 = 1200; +10% overhead = 1320.
    assert got.direct_cost_total == Decimal("1200.00")
    assert got.markups_total == Decimal("120.00")
    assert got.grand_total == Decimal("1320.00")
    assert got.position_count == 3

    for field in BOQWithPositions.model_fields:
        if field == "positions":
            continue
        assert getattr(got, field) == getattr(want, field), field
    excavation, pump, backfill, placeholder = bill["line_ids"]
    assert [p.id for p in got.positions] == [bill["section_id"], pump, backfill, excavation, placeholder]
    assert [p.model_dump() for p in got.positions] == [p.model_dump() for p in want.positions]
    assert got.model_dump(mode="json") == want.model_dump(mode="json")


@pytest.mark.asyncio
async def test_an_unknown_bill_is_still_a_404(pg_session) -> None:
    with pytest.raises(HTTPException) as missing:
        await BOQService(pg_session).get_boq_with_positions(uuid.uuid4())

    assert missing.value.status_code == 404
    assert missing.value.detail == "BOQ not found"


# ── The caller's identity map ──────────────────────────────────────────────


#
# ``Position.children`` is deliberately not asserted here: the sorted read's
# ``noload`` leaves it ``[]`` on every position it touches, and it did exactly
# that on the old path too (measured), so it is not something this change moved.


def _loaded(entity: Any, *attrs: str) -> bool:
    """True when every named relationship is in memory, so reading it sends no SQL."""
    unloaded = inspect(entity).unloaded
    return not any(a in unloaded for a in attrs)


@pytest.mark.asyncio
async def test_a_bill_loaded_before_the_read_keeps_its_positions(pg_session) -> None:
    bill = await _priced_bill(pg_session)
    pg_session.expunge_all()

    boq = await pg_session.get(BOQ, bill["boq_id"])
    positions_before = boq.positions
    await BOQService(pg_session).get_boq_with_positions(bill["boq_id"])

    assert _loaded(boq, "positions", "markups")
    assert boq.positions is positions_before
    assert len(boq.positions) == 5
    assert len(boq.markups) == 2
    assert await pg_session.get(BOQ, bill["boq_id"]) is boq


@pytest.mark.asyncio
async def test_a_bill_loaded_after_the_read_sees_its_positions(pg_session) -> None:
    bill = await _priced_bill(pg_session)
    pg_session.expunge_all()

    await BOQService(pg_session).get_boq_with_positions(bill["boq_id"])
    boq = await pg_session.get(BOQ, bill["boq_id"])

    assert _loaded(boq, "positions", "markups"), "the header read left a half-loaded BOQ in the identity map"
    assert boq.positions[0].id == bill["section_id"]
    assert {p.id for p in boq.positions} == {bill["section_id"], *bill["line_ids"]}
    assert {m.name for m in boq.markups} == {"Overhead", "Switched off"}
