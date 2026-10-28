# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Finding a cost line that sorts past the first page.

Every test here seeds more lines than one page holds, and that is the point
rather than an incidental detail. A search test over a handful of rows passes
whether the search reaches the database or not, because a handful of rows all
fit on the first page and any client-side filter would find them too. The only
assertion that distinguishes a working search from a broken one is that a line
which the unfiltered first page does NOT contain comes back when searched for,
so each test states the control first: not on page one, found by search.

The escaping tests exist because a bill of quantities is full of codes with
underscores in them, and an unescaped ``_`` is a single-character wildcard.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costmodel.models import CostLine
from app.modules.costmodel.repository import CostLineRepository
from tests._pg import transactional_session

# ``asyncio_mode = "auto"`` in pyproject collects these without a marker.

PAGE = 200
SEEDED = 250


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session(disable_fks=True) as s:
        yield s


@pytest_asyncio.fixture
def project_id() -> uuid.UUID:
    return uuid.uuid4()


def make_line(project_id: uuid.UUID, code: str, description: str, **overrides: object) -> CostLine:
    """One active cost line generated from a bill position unless told otherwise."""
    fields: dict[str, object] = {
        "project_id": project_id,
        "code": code,
        "description": description,
        "unit": "m3",
        "source": "boq",
        "boq_position_id": uuid.uuid4(),
        "boq_id": None,
        "estimate_quantity": "1",
        "estimate_unit_rate": "100.00",
        "estimate_amount": "100.00",
        "currency": "EUR",
        "status": "active",
    }
    fields.update(overrides)
    return CostLine(**fields)


async def seed_bill(session: AsyncSession, project_id: uuid.UUID) -> list[str]:
    """Seed a bill larger than one page. Returns the codes in sort order.

    Codes are zero padded so the database's ``ORDER BY code`` and the obvious
    reading of "the last one" agree; unpadded codes would sort CL-100 before
    CL-99 and the test would be asserting something other than it says.
    """
    codes = [f"CL-{n:04d}" for n in range(1, SEEDED + 1)]
    for index, code in enumerate(codes):
        session.add(make_line(project_id, code, f"Bill position number {index + 1}"))
    await session.flush()
    return codes


async def test_a_line_past_the_first_page_is_unreachable_without_search(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """The control. This is the state the picker was in before the search existed."""
    codes = await seed_bill(session, project_id)
    repo = CostLineRepository(session)

    lines, total = await repo.list_for_project(project_id, offset=0, limit=PAGE)

    assert total == SEEDED
    assert len(lines) == PAGE
    assert codes[-1] not in {line.code for line in lines}


async def test_search_finds_the_line_the_first_page_could_not_show(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """The assertion the whole change exists for."""
    codes = await seed_bill(session, project_id)
    repo = CostLineRepository(session)
    wanted = codes[-1]

    lines, total = await repo.list_for_project(project_id, search=wanted, offset=0, limit=PAGE)

    assert [line.code for line in lines] == [wanted]
    assert total == 1


async def test_search_matches_the_description_too(session: AsyncSession, project_id: uuid.UUID) -> None:
    """A buyer reads the wording on the drawing, not the code."""
    await seed_bill(session, project_id)
    repo = CostLineRepository(session)

    lines, total = await repo.list_for_project(project_id, search="number 250", offset=0, limit=PAGE)

    assert total == 1
    assert lines[0].description == "Bill position number 250"


async def test_search_ignores_case(session: AsyncSession, project_id: uuid.UUID) -> None:
    codes = await seed_bill(session, project_id)
    repo = CostLineRepository(session)

    lines, _ = await repo.list_for_project(project_id, search=codes[-1].lower(), offset=0, limit=PAGE)

    assert [line.code for line in lines] == [codes[-1]]


async def test_the_count_describes_the_search_not_the_page(session: AsyncSession, project_id: uuid.UUID) -> None:
    """``total`` has to follow the filter, or the caller cannot say what it dropped."""
    await seed_bill(session, project_id)
    repo = CostLineRepository(session)

    lines, total = await repo.list_for_project(project_id, search="Bill position number 1", offset=0, limit=5)

    # 1, 1x, 1xx and 25 of the 1xx range: the count is whatever matched, the page is five.
    assert len(lines) == 5
    assert total > 5
    assert total < SEEDED


async def test_a_typed_underscore_is_not_a_wildcard(session: AsyncSession, project_id: uuid.UUID) -> None:
    """An unescaped ``_`` matches any single character and quietly widens the search."""
    await seed_bill(session, project_id)
    session.add(make_line(project_id, "CL_0001", "Underscored code, a different line"))
    await session.flush()
    repo = CostLineRepository(session)

    lines, total = await repo.list_for_project(project_id, search="CL_0001", offset=0, limit=PAGE)

    assert total == 1
    assert [line.code for line in lines] == ["CL_0001"]


async def test_a_typed_percent_is_not_a_wildcard(session: AsyncSession, project_id: uuid.UUID) -> None:
    await seed_bill(session, project_id)
    session.add(make_line(project_id, "CL-PCT", "Wastage at 5% of the gross quantity"))
    await session.flush()
    repo = CostLineRepository(session)

    lines, total = await repo.list_for_project(project_id, search="5%", offset=0, limit=PAGE)

    assert total == 1
    assert lines[0].code == "CL-PCT"


async def test_a_search_matching_nothing_returns_nothing(session: AsyncSession, project_id: uuid.UUID) -> None:
    """An empty result is a real answer and must not fall back to the whole bill."""
    await seed_bill(session, project_id)
    repo = CostLineRepository(session)

    lines, total = await repo.list_for_project(project_id, search="no such position", offset=0, limit=PAGE)

    assert lines == []
    assert total == 0


async def test_blank_search_is_no_search(session: AsyncSession, project_id: uuid.UUID) -> None:
    """A cleared filter box must show everything, not match the empty string oddly."""
    await seed_bill(session, project_id)
    repo = CostLineRepository(session)

    for blank in ("", "   ", None):
        _, total = await repo.list_for_project(project_id, search=blank, offset=0, limit=PAGE)
        assert total == SEEDED, f"blank search {blank!r} changed the result set"


async def test_linked_to_position_narrows_before_the_page_is_cut(session: AsyncSession, project_id: uuid.UUID) -> None:
    """The filter has to run in the query, or the count and the rows disagree.

    A caller that fetches a page and then drops the unlinked rows itself reports
    a total covering rows it did not return, which is exactly the partial list
    presented as a whole that the picker must never show.
    """
    await seed_bill(session, project_id)
    for n in range(3):
        session.add(make_line(project_id, f"MAN-{n}", "Entered by hand", source="manual", boq_position_id=None))
    await session.flush()
    repo = CostLineRepository(session)

    linked, linked_total = await repo.list_for_project(project_id, linked_to_position=True, offset=0, limit=PAGE)
    unlinked, unlinked_total = await repo.list_for_project(project_id, linked_to_position=False, offset=0, limit=PAGE)
    _, everything = await repo.list_for_project(project_id, offset=0, limit=PAGE)

    assert linked_total == SEEDED
    assert unlinked_total == 3
    assert everything == SEEDED + 3
    assert all(line.boq_position_id is not None for line in linked)
    assert all(line.boq_position_id is None for line in unlinked)


async def test_search_and_link_filter_compose(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Typing must not resurrect a line the link filter excluded."""
    await seed_bill(session, project_id)
    session.add(
        make_line(project_id, "CL-9999", "Bill position number 250 by hand", source="manual", boq_position_id=None)
    )
    await session.flush()
    repo = CostLineRepository(session)

    lines, total = await repo.list_for_project(
        project_id, search="number 250", linked_to_position=True, offset=0, limit=PAGE
    )

    assert total == 1
    assert lines[0].code == "CL-0250"


async def test_search_respects_the_project_boundary(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Search widens the reach over one project, never across projects."""
    await seed_bill(session, project_id)
    other = uuid.uuid4()
    session.add(make_line(other, "CL-0250", "Someone else's bill position number 250"))
    await session.flush()
    repo = CostLineRepository(session)

    lines, total = await repo.list_for_project(project_id, search="CL-0250", offset=0, limit=PAGE)

    assert total == 1
    assert lines[0].project_id == project_id


async def test_one_position_resolves_even_when_it_sorts_past_the_page(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """A picker opened on an existing order must be able to name its selection.

    Without this the control loads its first page, fails to find the position
    the order was already attributed to, and falls back to showing "not linked"
    for a line that is linked. Saving that form would then write the fallback.
    """
    await seed_bill(session, project_id)
    repo = CostLineRepository(session)
    page, _ = await repo.list_for_project(project_id, offset=0, limit=PAGE)
    beyond, _ = await repo.list_for_project(project_id, offset=PAGE, limit=PAGE)
    wanted = beyond[-1]
    assert wanted.id not in {row.id for row in page}

    lines, total = await repo.list_for_project(project_id, boq_position_id=wanted.boq_position_id, offset=0, limit=PAGE)

    assert total == 1
    assert lines[0].id == wanted.id


async def test_an_unknown_position_resolves_to_nothing(session: AsyncSession, project_id: uuid.UUID) -> None:
    """A position with no cost line is off the spine, and the caller must see that."""
    await seed_bill(session, project_id)
    repo = CostLineRepository(session)

    lines, total = await repo.list_for_project(project_id, boq_position_id=uuid.uuid4(), offset=0, limit=PAGE)

    assert lines == []
    assert total == 0
