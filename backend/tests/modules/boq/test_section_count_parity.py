"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A bill's card and the bill itself must count the same line items.

A section header is stored with one of two spellings of ``Position.unit``:
``""`` is what the demo seeders write, ``"section"`` is what
``BOQService.create_section`` and every file importer write. The list of
bills counts line items with a SQL predicate, because it must answer for
many bills without loading their rows; the bill's own detail endpoint counts
them by calling ``_is_section`` on every row it has already loaded. Two
readers of one concept, so they have to agree on both spellings.

They did not. The SQL half read ``unit != ""`` and recognised only the empty
spelling, so every bill imported from a GAEB, Excel or BC3 file reported its
section headers as priced lines on its card while the bill itself did not
count them. The bug was invisible on seeded data, which is why the assertions
here are agreement between the two readers rather than an expected number: a
test pinning a count would have passed on a seeded bill and would never have
been written for an imported one.

Run:
    cd backend
    python -m pytest tests/modules/boq/test_section_count_parity.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.service import SECTION_UNITS
from tests._pg import transactional_session

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # FK triggers off so a project can be seeded without standing up a user
    # row; these tests read counts and never go through an ownership check.
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _seed_bill(
    session: AsyncSession,
    *,
    section_unit: str,
    sections: int = 3,
    items_per_section: int = 4,
) -> tuple[uuid.UUID, int]:
    """Create one bill whose section headers carry ``section_unit``.

    Positions are constructed as ORM rows rather than sent through
    ``PositionCreate``, which is how a section header is really written: the
    importers and the seeders build the row themselves, and the create schema
    never sees a header.

    Returns:
        The BOQ id and the number of priced line items it carries.
    """
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project

    project = Project(
        name=f"Parity {uuid.uuid4().hex[:6]}",
        currency="EUR",
        region="DACH",
        owner_id=uuid.uuid4(),
    )
    session.add(project)
    await session.flush()

    boq = BOQ(project_id=project.id, name="Parity BOQ", status="draft", metadata_={})
    session.add(boq)
    await session.flush()

    sort_order = 0
    for s in range(sections):
        session.add(
            Position(
                boq_id=boq.id,
                ordinal=f"{s + 1:02d}",
                description=f"Section {s + 1}",
                unit=section_unit,
                quantity="0",
                unit_rate="0",
                total="0",
                sort_order=sort_order,
            )
        )
        sort_order += 1
        for i in range(items_per_section):
            session.add(
                Position(
                    boq_id=boq.id,
                    ordinal=f"{s + 1:02d}.{i + 1:03d}",
                    description=f"Line {s + 1}.{i + 1}",
                    unit="m3",
                    quantity="10",
                    unit_rate="100",
                    total="1000",
                    sort_order=sort_order,
                )
            )
            sort_order += 1
    await session.flush()
    return boq.id, sections * items_per_section


# ── The parity the two endpoints owe each other ─────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("section_unit", SECTION_UNITS, ids=lambda u: f"unit={u or 'empty'}")
async def test_list_and_detail_count_the_same_line_items(session: AsyncSession, section_unit: str) -> None:
    """Whatever spelling the headers carry, both readers must return one figure.

    Parametrized over the spellings themselves rather than over two literals,
    so a third spelling added to ``SECTION_UNITS`` is tested by both readers
    the moment it exists instead of reaching only the one that was remembered.
    """
    from app.modules.boq.service import BOQService

    boq_id, line_items = await _seed_bill(session, section_unit=section_unit)
    service = BOQService(session)

    listed = (await service.count_line_items([boq_id])).get(boq_id, 0)
    detailed = (await service.get_boq_with_positions(boq_id)).position_count

    assert listed == detailed, (
        f"the card says {listed} and the bill says {detailed} for section headers spelled {section_unit!r}"
    )
    assert listed == line_items


# ── The vocabulary the SQL half and the Python half share ───────────────────


@pytest.mark.parametrize("section_unit", SECTION_UNITS, ids=lambda u: f"unit={u or 'empty'}")
def test_every_section_spelling_is_a_section_to_the_python_reader(section_unit: str) -> None:
    """The in-memory reader must recognise every spelling the SQL half excludes.

    This is the cheap half of the guard and the one that runs without a
    database: it fails the moment a spelling is added to ``SECTION_UNITS``
    for the SQL filter and not taught to ``_is_section``, which is exactly
    the drift that put the two endpoints out of step in the first place.
    """
    from app.modules.boq.models import Position
    from app.modules.boq.service import _is_section

    assert _is_section(Position(unit=section_unit, quantity="0", unit_rate="0")) is True


def test_a_priced_line_is_a_section_to_neither_reader() -> None:
    """The negative control: without it every assertion above passes on a
    reader that calls everything a section."""
    from app.modules.boq.models import Position
    from app.modules.boq.service import _is_section

    assert _is_section(Position(unit="m3", quantity="10", unit_rate="100")) is False
