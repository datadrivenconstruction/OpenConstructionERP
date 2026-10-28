# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A BIM-LV container must not export a bill's section headers.

A section header is a ``Position`` carrying a sentinel unit, and the BOQ module
spells that sentinel two ways: ``""`` from the demo seeders, ``"section"`` from
``create_section`` and every file importer. ``export_container`` filtered on the
second spelling alone, so a seeded bill exported its headers as LV positions.

The damage was not a stray row. ``export_container`` writes ``pos.unit or
"pcs"``, and the empty spelling is falsy, so each header left the platform as a
DIN SPEC 91350 position measured in pieces, with the quantity and rate of zero
that made it a header in the first place. A consumer of the container has no way
to tell that back from a real, free-of-charge count position.

Run:
    cd backend
    python -m pytest tests/integration/test_bimlv_export_section_headers.py -v
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.service import SECTION_UNITS
from tests._pg import transactional_session

#: What the seeded priced lines are measured in. Deliberately not "pcs", so a
#: header leaking through as ``pos.unit or "pcs"`` is distinguishable from every
#: legitimate row rather than blending into the same vocabulary.
_LINE_UNIT = "m3"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # FK triggers off so a project can be seeded without standing up a user
    # row; nothing here goes through an ownership check.
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _seed_bill(
    session: AsyncSession,
    *,
    section_unit: str,
    sections: int = 3,
    items_per_section: int = 4,
) -> tuple[uuid.UUID, list[str]]:
    """Create one bill whose section headers carry ``section_unit``.

    Positions are built as ORM rows rather than through ``PositionCreate``,
    which is how a header is really written: the importers and the seeders
    construct the row themselves and the create schema never sees one.

    Returns:
        The BOQ id and the ordinals of the priced line items, in sheet order.
    """
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project

    project = Project(
        name=f"BIM-LV {uuid.uuid4().hex[:6]}",
        currency="EUR",
        region="DACH",
        owner_id=uuid.uuid4(),
    )
    session.add(project)
    await session.flush()

    boq = BOQ(project_id=project.id, name="Container BOQ", status="draft", metadata_={})
    session.add(boq)
    await session.flush()

    line_ordinals: list[str] = []
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
            ordinal = f"{s + 1:02d}.{i + 1:03d}"
            line_ordinals.append(ordinal)
            session.add(
                Position(
                    boq_id=boq.id,
                    ordinal=ordinal,
                    description=f"Line {s + 1}.{i + 1}",
                    unit=_LINE_UNIT,
                    quantity="10",
                    unit_rate="100",
                    total="1000",
                    sort_order=sort_order,
                )
            )
            sort_order += 1
    await session.flush()
    return boq.id, line_ordinals


@pytest.mark.asyncio
@pytest.mark.parametrize("section_unit", SECTION_UNITS, ids=lambda u: f"unit={u or 'empty'}")
async def test_export_carries_the_priced_lines_and_nothing_else(session: AsyncSession, section_unit: str) -> None:
    """However the headers spell their unit, none of them reaches the container.

    Parametrized over ``SECTION_UNITS`` rather than over two literals, so a
    third spelling added to the BOQ module is covered by this export the moment
    it exists instead of reaching only whichever spelling was remembered here.
    """
    from app.modules.bimlv.container import read_container
    from app.modules.bimlv.service import export_container

    boq_id, line_ordinals = await _seed_bill(session, section_unit=section_unit)

    export = await export_container(boq_id, session)
    parsed = read_container(export.data)

    exported = [p.ordinal for p in parsed.positions]
    assert exported == line_ordinals, f"headers spelled {section_unit!r} reached the container: {exported}"
    assert export.position_count == len(line_ordinals)


@pytest.mark.asyncio
@pytest.mark.parametrize("section_unit", SECTION_UNITS, ids=lambda u: f"unit={u or 'empty'}")
async def test_no_exported_position_is_measured_in_a_unit_the_bill_never_used(
    session: AsyncSession, section_unit: str
) -> None:
    """The sharp edge of the defect, asserted on its own.

    A header that survives the filter is not merely an extra line: because the
    writer substitutes "pcs" for a falsy unit, it is published as a countable
    position in a unit no row of the bill was ever priced in. Asserting the
    exported vocabulary is exactly the bill's own vocabulary catches that even
    if some future filter drops the ordinal check above.
    """
    from app.modules.bimlv.container import read_container
    from app.modules.bimlv.service import export_container

    boq_id, _ = await _seed_bill(session, section_unit=section_unit)

    export = await export_container(boq_id, session)
    parsed = read_container(export.data)

    assert {p.unit for p in parsed.positions} == {_LINE_UNIT}


@pytest.mark.asyncio
async def test_a_bill_of_headers_alone_exports_an_empty_container(session: AsyncSession) -> None:
    """The negative control: an export that returns everything would pass above.

    Both assertions above compare the export against the bill's own line items,
    so an export filtering nothing at all still has to be caught by a bill that
    has no line items to hide behind.
    """
    from app.modules.bimlv.service import export_container

    boq_id, line_ordinals = await _seed_bill(session, section_unit="section", sections=3, items_per_section=0)
    assert line_ordinals == []

    export = await export_container(boq_id, session)
    assert export.position_count == 0
