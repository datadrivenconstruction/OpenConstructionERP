"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A row nobody has typed into is not a line of the bill.

"Add Position" in the editor creates the row on the server immediately and
opens its description cell, which is the behaviour the author built: the
create handler posts ``description=""``, ``unit="m2"``, ``quantity=0``,
``unit_rate=0`` and the grid then puts the cursor in that row. So a bill
legitimately holds rows carrying nothing yet, and the product's job is not to
stop creating them but to stop treating them as priced lines.

Two things must be true of such a row. It must not be counted - a blank line
inflates the position tally on a bill's card and in its detail. And it must
not reach an export - a delivered bill carrying a blank line is a defect its
recipient sees, and that is the half that leaves the building.

The assertions here carry a denominator on purpose. "The empty row is not
counted" is satisfied by a reader that counts nothing at all, so every bill
below holds one real priced line alongside the empty one and the expected
figure is exactly one. The export assertions name the ordinal that must be
present as well as the one that must be absent, for the same reason.

Run:
    cd backend
    python -m pytest tests/modules/boq/test_empty_position_not_counted.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.schemas import BOQWithSections
from app.modules.boq.service import SECTION_UNITS
from tests._pg import transactional_session

#: The payload ``handleAddPosition`` posts for a fresh row, field for field.
#: Pinned here so this test keeps describing the editor's real behaviour
#: rather than a convenient invention of one.
NEW_ROW_ORDINAL = "01.20"
PRICED_ROW_ORDINAL = "01.10"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # FK triggers off so a project can be seeded without standing up a user
    # row; these tests read counts and exports and never go through an
    # ownership check.
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _seed_bill(
    session: AsyncSession,
    *,
    section_unit: str = "section",
    section_description: str = "Earthworks",
) -> uuid.UUID:
    """One section holding one priced line and one untouched new row.

    Positions are built as ORM rows because that is how both the seeders and
    the importers write them, and because the empty row has to be stored
    exactly as ``add_position`` stores it - a zero quantity is persisted as a
    string, and which of its spellings lands there is not this test's business.
    """
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project

    project = Project(
        name=f"Empty row {uuid.uuid4().hex[:6]}",
        currency="EUR",
        region="DACH",
        owner_id=uuid.uuid4(),
    )
    session.add(project)
    await session.flush()

    boq = BOQ(project_id=project.id, name="Bill with a blank line", status="draft", metadata_={})
    session.add(boq)
    await session.flush()

    section = Position(
        boq_id=boq.id,
        ordinal="01",
        description=section_description,
        unit=section_unit,
        quantity="0",
        unit_rate="0",
        total="0",
        sort_order=0,
    )
    session.add(section)
    await session.flush()

    session.add(
        Position(
            boq_id=boq.id,
            parent_id=section.id,
            ordinal=PRICED_ROW_ORDINAL,
            description="Excavate to reduced level",
            unit="m3",
            quantity="120",
            unit_rate="18.50",
            total="2220.00",
            sort_order=1,
        )
    )
    # The untouched row, exactly as "Add Position" leaves it.
    session.add(
        Position(
            boq_id=boq.id,
            parent_id=section.id,
            ordinal=NEW_ROW_ORDINAL,
            description="",
            unit="m2",
            quantity="0",
            unit_rate="0",
            total="0",
            sort_order=2,
        )
    )
    await session.flush()
    return boq.id


def _ordinals(structured: BOQWithSections) -> set[str]:
    """Every position ordinal a structured payload would render, headers included."""
    found = {p.ordinal for p in structured.positions}
    for section in structured.sections:
        found.add(section.ordinal)
        found.update(p.ordinal for p in section.positions)
    return found


# ── Counted ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_untouched_row_is_not_counted_by_either_reader(session: AsyncSession) -> None:
    """One priced line and one blank line must count as one line, not two.

    Both readers are asserted because they are different implementations of
    one question - the card counts in SQL so it can answer for many bills at
    once, the bill itself counts in Python over rows it already holds - and a
    fix applied to one of them is the drift this module has shipped before.
    """
    from app.modules.boq.service import BOQService

    boq_id = await _seed_bill(session)
    service = BOQService(session)

    listed = (await service.count_line_items([boq_id])).get(boq_id, 0)
    detailed = (await service.get_boq_with_positions(boq_id)).position_count

    assert listed == 1, f"the bill's card counted {listed} line items, and only one is priced"
    assert detailed == 1, f"the bill itself counted {detailed} line items, and only one is priced"
    assert listed == detailed


@pytest.mark.asyncio
async def test_the_untouched_row_is_still_served_to_the_editor(session: AsyncSession) -> None:
    """Excluding it from the count must not hide it from the person filling it in.

    This is the assertion that keeps the chosen behaviour honest. The row is
    created on the server the moment the button is pressed, so the editor has
    to be served it - a fix that dropped it from the detail payload would look
    like a passing count test and read to the estimator as the button doing
    nothing at all.
    """
    from app.modules.boq.service import BOQService

    boq_id = await _seed_bill(session)
    service = BOQService(session)

    detail = await service.get_boq_with_positions(boq_id)
    editor_view = await service.get_boq_structured(boq_id)

    assert NEW_ROW_ORDINAL in {p.ordinal for p in detail.positions}
    assert NEW_ROW_ORDINAL in _ordinals(editor_view)


# ── Exported ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_untouched_row_does_not_reach_an_export(session: AsyncSession) -> None:
    """The blank line must be absent from the payload every export renders.

    CSV, Excel, PDF, GAEB and BC3 all read the structured payload, so this is
    the one choke point they share. The priced ordinal is asserted present in
    the same breath: without it a filter that emptied the export entirely
    would pass.
    """
    from app.modules.boq.service import BOQService

    boq_id = await _seed_bill(session)
    service = BOQService(session)

    exported = _ordinals(await service.get_boq_structured_for_export(boq_id))

    assert PRICED_ROW_ORDINAL in exported, "the priced line must survive the export filter"
    assert NEW_ROW_ORDINAL not in exported, "a blank line reached a deliverable bill"


@pytest.mark.asyncio
async def test_the_export_still_carries_the_money_of_the_bill(session: AsyncSession) -> None:
    """Dropping the blank line must not move a single number.

    ``total`` is always ``quantity x unit_rate``, so a row with a zero
    quantity carries no money and removing it from the rendered set cannot
    change a subtotal or a grand total. Asserted rather than assumed, because
    an export whose lines no longer sum to its own footer is a worse defect
    than the blank line it set out to remove.
    """
    from app.modules.boq.service import BOQService

    boq_id = await _seed_bill(session)
    service = BOQService(session)

    full = await service.get_boq_structured(boq_id)
    exported = await service.get_boq_structured_for_export(boq_id)

    assert exported.direct_cost == full.direct_cost
    assert exported.grand_total == full.grand_total
    assert [s.subtotal for s in exported.sections] == [s.subtotal for s in full.sections]


# ── The header that must not be swept up ────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("section_unit", SECTION_UNITS, ids=lambda u: f"unit={u or 'empty'}")
async def test_a_section_header_survives_the_export_filter(session: AsyncSession, section_unit: str) -> None:
    """A header carries no quantity, and often no description, yet is not empty.

    Parametrized over ``SECTION_UNITS`` rather than a literal, so a third
    spelling added there is proven safe from this filter the moment it exists.
    The header is seeded with a blank description - the hardest case, and the
    one a two-term emptiness test gets wrong if it forgets to ask about
    sections first.
    """
    from app.modules.boq.service import BOQService

    boq_id = await _seed_bill(session, section_unit=section_unit, section_description="")
    service = BOQService(session)

    exported = await service.get_boq_structured_for_export(boq_id)

    assert "01" in _ordinals(exported), f"the section header spelled {section_unit!r} was dropped from the export"
    listed = (await service.count_line_items([boq_id])).get(boq_id, 0)
    assert listed == 1, f"a header spelled {section_unit!r} was counted as a priced line"


# ── The predicate itself, without a database ────────────────────────────────


def test_the_row_the_editor_creates_reads_as_empty() -> None:
    """The exact payload ``handleAddPosition`` posts, field for field."""
    from app.modules.boq.models import Position
    from app.modules.boq.service import is_empty_position

    assert is_empty_position(Position(description="", unit="m2", quantity="0", unit_rate="0", total="0"))


@pytest.mark.parametrize(
    ("description", "quantity"),
    [
        ("Excavate to reduced level", "0"),  # a description alone makes it real
        ("", "120"),  # so does a quantity alone
        ("Excavate to reduced level", "120"),
    ],
    ids=["described", "quantified", "both"],
)
def test_a_row_carrying_anything_is_not_empty(description: str, quantity: str) -> None:
    """The moment the estimator types into either field the row is a line.

    The quantity-only case is the one worth keeping: an estimator who measures
    before wording the item must not have that measurement dropped from the
    export they then send out.
    """
    from app.modules.boq.models import Position
    from app.modules.boq.service import is_empty_position

    assert not is_empty_position(
        Position(description=description, unit="m2", quantity=quantity, unit_rate="0", total="0")
    )


@pytest.mark.parametrize("zero", ["0", "0.00", "0.000", "", " ", "-0"])
def test_every_spelling_of_a_zero_quantity_reads_as_zero(zero: str) -> None:
    """``quantity`` is a String column, so one zero has many spellings.

    This is why the emptiness test is a Python predicate and the SQL half only
    narrows to candidates: no portable comparison against ``0`` catches all of
    these, and a filter that caught some of them would leave blank lines in
    the exports of exactly the bills whose importer wrote a different spelling.
    """
    from app.modules.boq.models import Position
    from app.modules.boq.service import is_empty_position

    assert is_empty_position(Position(description="", unit="m2", quantity=zero, unit_rate="0", total="0"))


@pytest.mark.parametrize("section_unit", SECTION_UNITS, ids=lambda u: f"unit={u or 'empty'}")
def test_a_blank_section_header_is_never_empty(section_unit: str) -> None:
    """The negative control for the guard the predicate opens with."""
    from app.modules.boq.models import Position
    from app.modules.boq.service import is_empty_position

    assert not is_empty_position(Position(description="", unit=section_unit, quantity="0", unit_rate="0", total="0"))
