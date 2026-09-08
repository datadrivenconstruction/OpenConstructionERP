# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PG: the estimate basis quotes the freshest bill's price base, not the luckiest spelling.

The defect
----------
``BOQ.base_date`` is free text holding a day, a month, a quarter or a year, and
the basis-of-estimate picked the project's price base with
``SELECT max(base_date)``. That ranks the strings, and the strings do not sort
in the order their dates run: ``"Q"`` is above every digit, so ``"2026-Q1"``
outranks ``"2026-12-01"``, while ``"2026-01"`` sorts below both. A project
whose bills mix shapes therefore quoted the wrong bill, and the value goes into
a document the client reads as "prices are current as of ...".

Both readers of ``base_date`` now go through
``app.modules.boq.base_date``: :func:`price_base_day` for the tax point and
:func:`latest_base_date` for this. The ranking itself is asserted in
``tests/unit/test_a_price_base_stated_as_a_quarter_dated_the_bill_today``; what
this file adds is that the real query returns those rows from a real database,
which a pure test of the helper cannot show.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

from app.modules.boq.models import BOQ
from app.modules.estimate_basis.service import EstimateBasisService
from app.modules.projects.models import Project
from app.modules.users.models import User


async def _project_with_bills(session, base_dates: list[str]) -> Project:
    """A stored project carrying one bill per stated price base."""
    tag = uuid.uuid4().hex[:8]
    owner = User(email=f"basis-{tag}@example.test", hashed_password="x", full_name="Basis")
    session.add(owner)
    await session.flush()

    project = Project(name=f"Basis {tag}", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()

    for index, stated in enumerate(base_dates):
        session.add(BOQ(project_id=project.id, name=f"Bill {index}", base_date=stated))
    await session.flush()
    return project


async def test_a_quarter_label_does_not_outrank_a_later_dated_bill(pg_session) -> None:
    """The case the string comparison got wrong, read back through the service."""
    project = await _project_with_bills(pg_session, ["2026-Q1", "2026-12-01"])

    derived = await EstimateBasisService(pg_session)._derive_pricing_base_date(project.id, None)

    assert derived == "2026-12-01", (
        f"the basis quoted {derived!r} as the date the prices are current to. December is the "
        f"freshest bill; 2026-Q1 only wins a comparison of the two strings"
    )


async def test_the_freshest_of_three_shapes_is_the_one_quoted(pg_session) -> None:
    """A month, a quarter and a year in one project, which is what a long-running
    programme actually looks like once several bills have been priced."""
    project = await _project_with_bills(pg_session, ["2024", "2025-Q3", "2025-11"])

    derived = await EstimateBasisService(pg_session)._derive_pricing_base_date(project.id, None)

    assert derived == "2025-11", f"November 2025 is the latest of the three, got {derived!r}"


async def test_a_project_whose_bills_state_no_price_base_quotes_none(pg_session) -> None:
    """No basis stated is not the same as a basis nobody read, and the document
    leaves the assumption line out rather than inventing a date."""
    project = await _project_with_bills(pg_session, [])

    assert await EstimateBasisService(pg_session)._derive_pricing_base_date(project.id, None) is None
