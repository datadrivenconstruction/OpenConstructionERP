"""PG: the editor's cost breakdown and classification panels read the bill once.

Both panels open with the BOQ editor. The cost breakdown proved the bill exists
with ``get_boq``, which loads every position and markup through the ``selectin``
relationships, and then read the positions and the markups again itself. The
classification did worse: ``get_boq``, dropped, so ``project_for_boq`` loaded
the bill and its lines a second time, then the project with its milestones and
WBS, to read one column, the project's country. Measured over HTTP on a
three-line bill: 11 statements for the breakdown, 15 for the classification.

Now the breakdown checks the bill's header and the classification reads the
bill's id and its project's country in one statement. These cases pin that, and
pin the answers:

* The breakdown on a bill whose figures are not trivial (an active and an
  inactive markup, a section, a foreign-currency line, a line with resources)
  answers exactly what it answers with the bill pre-loaded the way ``get_boq``
  used to leave it in the session, so dropping that load changed nothing the
  computation could see. Its grand total is also the full read's grand total.
* The classification still follows the project's country: a Canadian project
  is classed in the CCA letters, the same bill on a project with no country in
  AACE numbers.
* A bill that does not exist is still 404 "BOQ not found" on both.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from app.modules.boq.models import BOQ, BOQMarkup, Position
from app.modules.boq.service import BOQService
from app.modules.projects.models import Project
from app.modules.users.models import User

_FROM_POSITION = re.compile(r"\bFROM\s+oe_boq_position\b", re.IGNORECASE)
_FROM_MARKUP = re.compile(r"\bFROM\s+oe_boq_markup\b", re.IGNORECASE)
_FROM_PROJECT_CHILDREN = re.compile(r"\bFROM\s+oe_projects_(milestone|wbs)\b", re.IGNORECASE)


async def _priced_bill(session, *, country_code: str | None) -> dict[str, Any]:
    """A EUR project with a USD rate, one section, priced lines and two markups."""
    owner = User(email=f"panels-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x", full_name="Panels")
    session.add(owner)
    await session.flush()
    project = Project(
        name="Panels",
        owner_id=owner.id,
        currency="EUR",
        fx_rates=[{"code": "USD", "rate": "0.9"}],
        country_code=country_code,
    )
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="Priced bill", description="", metadata_={})
    session.add(boq)
    await session.flush()

    section = Position(
        boq_id=boq.id, ordinal="01", description="Earthworks", unit="", quantity="0", unit_rate="0", sort_order=0
    )
    session.add(section)
    await session.flush()
    session.add_all(
        [
            Position(
                boq_id=boq.id,
                parent_id=section.id,
                ordinal="01.001",
                description="Excavation by machine",
                unit="m3",
                quantity="10",
                unit_rate="25",
                total="250",
                sort_order=1,
                metadata_={
                    "resources": [
                        {"type": "labor", "name": "Operator", "unit": "h", "quantity": 0.5, "unit_rate": 30},
                        {"type": "equipment", "name": "Excavator", "unit": "h", "quantity": 0.5, "unit_rate": 20},
                    ]
                },
            ),
            Position(
                boq_id=boq.id,
                parent_id=section.id,
                ordinal="01.002",
                description="Imported pump, priced in USD",
                unit="pcs",
                quantity="2",
                unit_rate="500",
                total="1000",
                metadata_={"currency": "USD"},
                sort_order=2,
            ),
            Position(
                boq_id=boq.id,
                parent_id=section.id,
                ordinal="01.003",
                description="Concrete C30/37",
                unit="m3",
                quantity="4",
                unit_rate="120",
                total="480",
                sort_order=3,
            ),
        ]
    )
    session.add_all(
        [
            BOQMarkup(boq_id=boq.id, name="Overhead", percentage="10", sort_order=1, is_active=True),
            BOQMarkup(boq_id=boq.id, name="Switched off", percentage="50", sort_order=2, is_active=False),
        ]
    )
    await session.flush()
    return {"boq_id": boq.id, "project_id": project.id}


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


# ── Cost breakdown ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_breakdown_reads_positions_and_markups_once(pg_session) -> None:
    bill = await _priced_bill(pg_session, country_code="DE")
    pg_session.expunge_all()
    service = BOQService(pg_session)

    with _statements(pg_session) as sent:
        await service.get_cost_breakdown(bill["boq_id"])

    positions = _selects_from(sent, _FROM_POSITION)
    markups = _selects_from(sent, _FROM_MARKUP)
    assert len(positions) == 1, f"{len(positions)} SELECTs read oe_boq_position: {positions}"
    assert len(markups) == 1, f"{len(markups)} SELECTs read oe_boq_markup: {markups}"

    # The counter sees the old shape: ``get_boq`` reads both again.
    pg_session.expunge_all()
    with _statements(pg_session) as old_sent:
        await service.get_boq(bill["boq_id"])
    assert len(_selects_from(old_sent, _FROM_POSITION)) == 1
    assert len(_selects_from(old_sent, _FROM_MARKUP)) == 1


@pytest.mark.asyncio
async def test_the_breakdown_answers_what_it_did_with_the_bill_preloaded(pg_session) -> None:
    bill = await _priced_bill(pg_session, country_code="DE")
    service = BOQService(pg_session)

    pg_session.expunge_all()
    cold = await service.get_cost_breakdown(bill["boq_id"])

    # The old path: ``get_boq`` left the bill, its positions and its markups in
    # the session, held, before the computation read them.
    pg_session.expunge_all()
    preloaded = await service.get_boq(bill["boq_id"])
    warm = await service.get_cost_breakdown(bill["boq_id"])
    assert preloaded.positions, "the old-shape preload did not load the lines"

    assert cold.model_dump() == warm.model_dump()

    # Figures that tell right from wrong: the USD line is converted (1000 USD at
    # 0.9 is 900 EUR), the inactive 50% markup adds nothing, the active 10% does.
    direct = 250 + 900 + 480
    assert float(cold.grand_total) == pytest.approx(direct * 1.10, abs=0.01)
    assert [m.name for m in cold.markups] == ["Overhead"]

    # And the panel agrees with the bill's own total in the full read.
    pg_session.expunge_all()
    full = await service.get_boq_with_positions(bill["boq_id"])
    assert float(cold.grand_total) == pytest.approx(float(full.grand_total), abs=0.01)


@pytest.mark.asyncio
async def test_the_breakdown_of_a_missing_bill_is_404(pg_session) -> None:
    with pytest.raises(HTTPException) as exc:
        await BOQService(pg_session).get_cost_breakdown(uuid.uuid4())
    assert (exc.value.status_code, exc.value.detail) == (404, "BOQ not found")


# ── Classification ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_classification_reads_the_bill_once_and_not_the_project_children(pg_session) -> None:
    bill = await _priced_bill(pg_session, country_code="CA")
    pg_session.expunge_all()
    service = BOQService(pg_session)

    with _statements(pg_session) as sent:
        await service.get_estimate_classification(bill["boq_id"])

    assert len(sent) == 2, f"the classification ran {len(sent)} statements: {sent}"
    assert len(_selects_from(sent, _FROM_POSITION)) == 1
    assert not _selects_from(sent, _FROM_MARKUP)
    assert not _selects_from(sent, _FROM_PROJECT_CHILDREN)

    # The counter sees the old shape: the bill dropped and loaded again, then
    # the project with its children.
    pg_session.expunge_all()
    with _statements(pg_session) as old_sent:
        await service.get_boq(bill["boq_id"])
        await service.project_for_boq(bill["boq_id"])
    assert len(_selects_from(old_sent, _FROM_POSITION)) >= 1
    assert _selects_from(old_sent, _FROM_PROJECT_CHILDREN)


@pytest.mark.asyncio
async def test_the_classification_still_follows_the_projects_country(pg_session) -> None:
    canadian = await _priced_bill(pg_session, country_code="CA")
    nowhere = await _priced_bill(pg_session, country_code=None)
    pg_session.expunge_all()
    service = BOQService(pg_session)

    ca = await service.get_estimate_classification(canadian["boq_id"])
    aace = await service.get_estimate_classification(nowhere["boq_id"])

    assert ca.classification_system == "ca_cca", ca
    assert isinstance(ca.estimate_class, str)
    assert aace.classification_system == "aace", aace
    assert isinstance(aace.estimate_class, int)
    # Same lines, so the same metrics; only the system differs.
    assert ca.metrics == aace.metrics
    assert ca.metrics.total_positions == 3


@pytest.mark.asyncio
async def test_the_classification_of_a_missing_bill_is_404(pg_session) -> None:
    with pytest.raises(HTTPException) as exc:
        await BOQService(pg_session).get_estimate_classification(uuid.uuid4())
    assert (exc.value.status_code, exc.value.detail) == (404, "BOQ not found")
