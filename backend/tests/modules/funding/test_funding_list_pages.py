# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The four registers under an application answer with a page, and say so.

These endpoints used to answer with a bare array, which cannot tell a reader
it was cut short. The envelope they answer with now can, and the only thing
that makes it worth having is that ``total`` counts the rows the scope
matched rather than the rows on the page. Those two numbers are equal on
every application small enough to fit in one page, so a test that builds a
short register and checks the shape of the reply would pass just as happily
against ``total=len(items)`` - which is the one defect the envelope exists to
rule out.

So every register here is built longer than the page asked for, and every
test asserts the total against a number it knows independently. The slice is
checked too: a total that is right while the page repeats or skips rows is a
different way of losing the same information.

The routes are called rather than the repository, because the total is
assembled in the route. A repository that returns the right count still ships
the defect if the function building the envelope ignores it.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.funding.models import FundingApplication, FundingProgramme
from app.modules.funding.router import (
    get_application,
    list_allocations,
    list_disbursements,
    list_obligations,
    list_proofs,
)
from app.modules.funding.service import FundingService
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.users.models import User
from tests._pg import transactional_session

#: Rows built per register, and the page asked for. The register is longer
#: than the page on purpose: an envelope whose total merely echoes the page
#: is indistinguishable from a correct one until it is asked for less than
#: there is.
ROWS = 5
PAGE = 2


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    async with transactional_session() as s:
        yield s


async def make_owner_and_project(session: AsyncSession) -> tuple[str, uuid.UUID]:
    """A project and the id of the user who owns it."""
    user = User(
        email=f"funding-page-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Funding",
        role="admin",
    )
    session.add(user)
    await session.flush()
    project = Project(name=f"Funding {uuid.uuid4().hex[:6]}", owner_id=user.id, currency="EUR")
    session.add(project)
    await session.flush()
    return str(user.id), project.id


async def make_programme(service: FundingService) -> FundingProgramme:
    return await service.programmes.create(
        code=f"PROG-{uuid.uuid4().hex[:6]}",
        name="Energy efficient refurbishment",
        authority_name="Federal funding bank",
        country="DE",
        instrument="grant",
        status="open",
    )


async def make_application(
    service: FundingService,
    project_id: uuid.UUID,
    programme: FundingProgramme,
) -> FundingApplication:
    return await service.applications.create(
        project_id=project_id,
        programme_id=programme.id,
        code=f"A-{uuid.uuid4().hex[:6]}",
        title="Envelope and heating",
        eligible_cost_base=Decimal("1000000"),
        requested_amount=Decimal("400000"),
        own_share_amount=Decimal("200000"),
        currency="EUR",
        status="submitted",
    )


async def setup(session: AsyncSession) -> tuple[str, FundingService, FundingApplication]:
    service = FundingService(session)
    user_id, project_id = await make_owner_and_project(session)
    programme = await make_programme(service)
    application = await make_application(service, project_id, programme)
    return user_id, service, application


def day(n: int) -> str:
    """A distinct calendar date per row, so the sort order is knowable."""
    return f"2027-01-{n + 1:02d}"


# ── Disbursements ──────────────────────────────────────────────────────────


async def test_a_page_of_draws_reports_how_many_draws_there_are(session: AsyncSession) -> None:
    user_id, service, application = await setup(session)
    for n in range(ROWS):
        await service.disbursements.create(
            application_id=application.id,
            sequence=n + 1,
            code=f"MA-{n + 1}",
            status="submitted",
            amount_requested=Decimal("100000"),
        )

    page = await list_disbursements(
        application.id, session, user_id=user_id, offset=0, limit=PAGE, _perm=None, service=service
    )

    assert len(page.items) == PAGE
    # The number the bare array could not carry. Asserted against ROWS and
    # not against len(page.items), which would hold for any implementation.
    assert page.total == ROWS
    assert page.total > len(page.items)
    assert page.offset == 0
    assert page.limit == PAGE
    assert [row.sequence for row in page.items] == [1, 2]


async def test_the_second_page_of_draws_carries_on_where_the_first_stopped(session: AsyncSession) -> None:
    """A slice that repeats or skips a row loses the same information a bare array did."""
    user_id, service, application = await setup(session)
    for n in range(ROWS):
        await service.disbursements.create(
            application_id=application.id,
            sequence=n + 1,
            status="submitted",
            amount_requested=Decimal("100000"),
        )

    first = await list_disbursements(
        application.id, session, user_id=user_id, offset=0, limit=PAGE, _perm=None, service=service
    )
    second = await list_disbursements(
        application.id, session, user_id=user_id, offset=PAGE, limit=PAGE, _perm=None, service=service
    )
    last = await list_disbursements(
        application.id, session, user_id=user_id, offset=2 * PAGE, limit=PAGE, _perm=None, service=service
    )

    assert [row.sequence for row in second.items] == [3, 4]
    assert [row.sequence for row in last.items] == [5]
    # Every row exactly once, and the total unchanged by where the reader is.
    seen = [row.id for page in (first, second, last) for row in page.items]
    assert len(seen) == len(set(seen)) == ROWS
    assert {first.total, second.total, last.total} == {ROWS}


async def test_a_register_that_fits_in_one_page_reports_its_own_length(session: AsyncSession) -> None:
    """The other direction: a total permanently larger than the set is equally wrong.

    A reader told there is more when there is not pages forever into empty
    replies, so the total has to come down to the page when the page holds
    everything.
    """
    user_id, service, application = await setup(session)
    for n in range(2):
        await service.disbursements.create(application_id=application.id, sequence=n + 1, status="submitted")

    page = await list_disbursements(
        application.id, session, user_id=user_id, offset=0, limit=50, _perm=None, service=service
    )

    assert page.total == len(page.items) == 2


async def test_an_application_with_no_draws_answers_with_an_empty_page(session: AsyncSession) -> None:
    user_id, service, application = await setup(session)

    page = await list_disbursements(
        application.id, session, user_id=user_id, offset=0, limit=PAGE, _perm=None, service=service
    )

    assert page.items == []
    assert page.total == 0


# ── Proofs of use ──────────────────────────────────────────────────────────


async def test_a_page_of_proofs_reports_how_many_proofs_there_are(session: AsyncSession) -> None:
    user_id, service, application = await setup(session)
    for n in range(ROWS):
        await service.proofs.create(application_id=application.id, kind="interim", due_on=day(n))

    page = await list_proofs(
        application.id, session, user_id=user_id, offset=0, limit=PAGE, _perm=None, service=service
    )
    rest = await list_proofs(
        application.id, session, user_id=user_id, offset=PAGE, limit=PAGE, _perm=None, service=service
    )

    assert len(page.items) == PAGE
    assert page.total == ROWS
    assert page.total > len(page.items)
    assert [row.due_on for row in page.items] == [day(0), day(1)]
    assert [row.due_on for row in rest.items] == [day(2), day(3)]


# ── Obligations ────────────────────────────────────────────────────────────


async def test_a_page_of_obligations_reports_how_many_obligations_there_are(session: AsyncSession) -> None:
    user_id, service, application = await setup(session)
    for n in range(ROWS):
        await service.obligations.create(
            application_id=application.id,
            kind="condition",
            title=f"Condition {n}",
            due_on=day(n),
            source="manual",
            status="open",
        )

    page = await list_obligations(
        application.id, session, user_id=user_id, today="", offset=0, limit=PAGE, _perm=None, service=service
    )
    rest = await list_obligations(
        application.id, session, user_id=user_id, today="", offset=PAGE, limit=PAGE, _perm=None, service=service
    )

    assert len(page.items) == PAGE
    assert page.total == ROWS
    assert page.total > len(page.items)
    assert [row.due_on for row in page.items] == [day(0), day(1)]
    assert [row.due_on for row in rest.items] == [day(2), day(3)]


async def test_lateness_on_a_page_of_obligations_is_still_read_against_the_callers_date(
    session: AsyncSession,
) -> None:
    """Paging must not cost the reader the one thing this list is read for."""
    user_id, service, application = await setup(session)
    for n in range(ROWS):
        await service.obligations.create(
            application_id=application.id,
            kind="condition",
            title=f"Condition {n}",
            due_on=day(n),
            source="manual",
            status="open",
        )

    late = await list_obligations(
        application.id,
        session,
        user_id=user_id,
        today="2027-06-01",
        offset=0,
        limit=PAGE,
        _perm=None,
        service=service,
    )
    early = await list_obligations(
        application.id,
        session,
        user_id=user_id,
        today="2026-06-01",
        offset=0,
        limit=PAGE,
        _perm=None,
        service=service,
    )

    assert all(row.overdue for row in late.items)
    assert not any(row.overdue for row in early.items)


# ── Cost allocations ───────────────────────────────────────────────────────


async def test_a_page_of_allocations_reports_how_many_allocations_there_are(session: AsyncSession) -> None:
    user_id, service, application = await setup(session)
    for n in range(ROWS):
        await service.allocations.create(
            application_id=application.id,
            cost_group=f"{300 + n}",
            description=f"Cost group {300 + n}",
            amount=Decimal("1000"),
            eligible_amount=Decimal("800"),
        )

    page = await list_allocations(
        application.id, session, user_id=user_id, offset=0, limit=PAGE, _perm=None, service=service
    )
    rest = await list_allocations(
        application.id, session, user_id=user_id, offset=PAGE, limit=PAGE, _perm=None, service=service
    )

    assert len(page.items) == PAGE
    assert page.total == ROWS
    assert page.total > len(page.items)
    assert [row.cost_group for row in page.items] == ["300", "301"]
    assert [row.cost_group for row in rest.items] == ["302", "303"]


# ── What the page must not have cost anybody ───────────────────────────────


async def test_the_application_detail_still_carries_every_child_row(session: AsyncSession) -> None:
    """The readers that must keep seeing everything, checked from the outside.

    Four routes now take a limit, and the obvious way to give them one is to
    put a default on the repository method they share. Three other readers
    call that method - this detail response, the deadline the proof endpoint
    derives, and the project calendar - and a default would have cut all of
    them to a page with nobody asking. The failure is silent: the screen
    still renders, it is simply missing rows.
    """
    user_id, service, application = await setup(session)
    for n in range(ROWS):
        await service.disbursements.create(application_id=application.id, sequence=n + 1, status="submitted")
        await service.proofs.create(application_id=application.id, kind="interim", due_on=day(n))
        await service.obligations.create(
            application_id=application.id,
            kind="condition",
            title=f"Condition {n}",
            due_on=day(n),
            source="manual",
            status="open",
        )
        await service.allocations.create(
            application_id=application.id,
            cost_group=f"{300 + n}",
            amount=Decimal("1000"),
            eligible_amount=Decimal("800"),
        )

    detail: Any = await get_application(
        application.id, session, user_id=user_id, today="", locale="en", _perm=None, service=service
    )

    assert len(detail.disbursements) == ROWS
    assert len(detail.proofs_of_use) == ROWS
    assert len(detail.obligations) == ROWS
    assert len(detail.cost_allocations) == ROWS
