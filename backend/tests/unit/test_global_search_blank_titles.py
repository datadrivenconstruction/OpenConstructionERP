# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠No global-search result may come back without a title a person can read.

Global search matches a row on one set of columns and then builds the row's
title from another, smaller set. Every column involved is NOT NULL, so nothing
here ever crashes, but an empty string is legal in all of them. Match on a
column that the title is not built from, with the title's own columns empty,
and the result is a blank line: the searcher gets a row they cannot identify
and cannot tell apart from any other blank row.

The contact case was closed separately. These tests cover the rest of the
family, plus the composite titles that lose one half and ship the separator on
its own, and the last-resort label for a row that answers none of its columns.

Each assertion looks for the token that was searched for, not merely for a
non-empty string: a title of ``" - "`` is truthy and would satisfy a weaker
check while still reading as blank on screen.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.global_search import global_search
from app.modules.boq.models import BOQ, Position
from app.modules.costs.models import CostItem
from app.modules.documents.models import Document
from app.modules.inspections.models import QualityInspection
from app.modules.meetings.models import Meeting
from app.modules.ncr.models import NCR
from app.modules.projects.models import Project
from app.modules.rfi.models import RFI
from app.modules.tasks.models import Task
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test PostgreSQL session inside a rolled-back outer transaction."""
    async with transactional_session() as s:
        yield s


@pytest_asyncio.fixture
async def project_id(session: AsyncSession) -> uuid.UUID:
    """A project to hang the project-scoped records off."""
    owner = User(
        email=f"titles-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Search Titles",
        role="admin",
    )
    session.add(owner)
    await session.flush()
    project = Project(name="Search titles", owner_id=owner.id, currency="EUR", region="DE_BERLIN")
    session.add(project)
    await session.flush()
    return project.id


def _token() -> str:
    """A string no other row in the database can carry."""
    return uuid.uuid4().hex[:10]


def _of(results: list[dict], module: str) -> list[dict]:
    return [r for r in results if r["module"] == module]


def _assert_named_by(hit: dict, needle: str) -> None:
    """The title must carry the string the searcher typed, not just be truthy."""
    title = hit["title"]
    assert title.strip(), f"result came back with a blank title: {title!r}"
    assert needle in title, f"title {title!r} does not carry the searched string {needle!r}"


# --- Types whose title columns are a strict subset of the searched columns ---


@pytest.mark.asyncio
async def test_a_document_found_by_its_description_is_named(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Documents are searched on name and description, titled on name alone."""
    token = _token()
    session.add(Document(project_id=project_id, name="", description=f"Foundation survey {token}"))
    await session.flush()

    hits = _of(await global_search(session, token), "documents")

    assert len(hits) == 1
    _assert_named_by(hits[0], token)


@pytest.mark.asyncio
async def test_a_task_found_by_its_description_is_named(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Tasks are searched on title and description, titled on title alone."""
    token = _token()
    session.add(
        Task(project_id=project_id, task_type="general", title="", description=f"Reseal the roof joint {token}")
    )
    await session.flush()

    hits = _of(await global_search(session, token), "tasks")

    assert len(hits) == 1
    _assert_named_by(hits[0], token)


@pytest.mark.asyncio
async def test_an_rfi_found_by_its_question_is_named(session: AsyncSession, project_id: uuid.UUID) -> None:
    """RFIs are searched on question too, but the question never reached the title."""
    token = _token()
    session.add(
        RFI(
            project_id=project_id,
            rfi_number="",
            subject="",
            question=f"Which rebar grade applies at gridline {token}?",
            raised_by=uuid.uuid4(),
        )
    )
    await session.flush()

    hits = _of(await global_search(session, token), "rfi")

    assert len(hits) == 1
    _assert_named_by(hits[0], token)


@pytest.mark.asyncio
async def test_a_meeting_found_by_its_minutes_is_named(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Meetings are searched on their minutes, which the title never carried."""
    token = _token()
    session.add(
        Meeting(
            project_id=project_id,
            meeting_number="",
            meeting_type="site",
            title="",
            meeting_date="2026-08-29",
            minutes=f"Agreed the pour sequence {token}",
        )
    )
    await session.flush()

    hits = _of(await global_search(session, token), "meetings")

    assert len(hits) == 1
    _assert_named_by(hits[0], token)


@pytest.mark.asyncio
async def test_an_ncr_found_by_its_description_is_named(session: AsyncSession, project_id: uuid.UUID) -> None:
    """NCRs are searched on description, which the title never carried."""
    token = _token()
    session.add(
        NCR(
            project_id=project_id,
            ncr_number="",
            title="",
            description=f"Cover to reinforcement short by 12 mm {token}",
            ncr_type="workmanship",
            severity="minor",
        )
    )
    await session.flush()

    hits = _of(await global_search(session, token), "ncr")

    assert len(hits) == 1
    _assert_named_by(hits[0], token)


# --- Composite titles that used to ship a separator with nothing beside it ---


@pytest.mark.asyncio
async def test_a_position_without_an_ordinal_does_not_lead_with_a_separator(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """An unnumbered position read as ``" - Concrete"``; the dash names nothing."""
    token = _token()
    boq = BOQ(project_id=project_id, name="Title harness")
    session.add(boq)
    await session.flush()
    session.add(Position(boq_id=boq.id, ordinal="", description=f"Concrete C30/37 {token}", unit="m3"))
    await session.flush()

    hits = _of(await global_search(session, token), "boq")

    assert len(hits) == 1
    _assert_named_by(hits[0], token)
    assert hits[0]["title"] == f"Concrete C30/37 {token}"


@pytest.mark.asyncio
async def test_a_cost_item_without_a_code_does_not_lead_with_a_separator(session: AsyncSession) -> None:
    """A custom rate carries no catalogue code, so the code half is empty."""
    token = _token()
    session.add(CostItem(code="", description=f"Site hoarding {token}", unit="m", rate="42.00"))
    await session.flush()

    hits = _of(await global_search(session, token), "costs")

    assert len(hits) == 1
    _assert_named_by(hits[0], token)
    assert hits[0]["title"] == f"Site hoarding {token}"


@pytest.mark.asyncio
async def test_an_inspection_without_a_number_does_not_lead_with_a_separator(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """An inspection raised before numbering read as ``" - Slab pour"``."""
    token = _token()
    session.add(
        QualityInspection(
            project_id=project_id,
            inspection_number="",
            inspection_type="witness",
            title=f"Slab pour check {token}",
        )
    )
    await session.flush()

    hits = _of(await global_search(session, token), "inspections")

    assert len(hits) == 1
    _assert_named_by(hits[0], token)
    assert hits[0]["title"] == f"Slab pour check {token}"


# --- Last resort: a row that answers none of its own columns ---


@pytest.mark.asyncio
async def test_a_row_with_nothing_to_say_is_still_not_blank_and_not_a_bare_id(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """``%`` is a wildcard to ILIKE, so a row that is empty everywhere matches it.

    That is the one way a hit reaches search with no column left to name it.
    It must still come back as something a person can read, and specifically
    not as a bare UUID, which is the complaint recorded against another screen.
    """
    document = Document(project_id=project_id, name="", description="")
    session.add(document)
    await session.flush()

    hits = _of(await global_search(session, "%"), "documents")

    assert len(hits) == 1
    title = hits[0]["title"]
    assert title.strip(), "a row that answers no column still may not be blank"
    assert title != str(document.id), "a bare identifier is not a name a person can read"
    assert "document" in title


# --- Negative controls: the fallbacks must not displace a real title ---


@pytest.mark.asyncio
async def test_a_named_document_is_still_titled_by_its_name(session: AsyncSession, project_id: uuid.UUID) -> None:
    """Without this, a fix that reached for the description would rename every file."""
    token = _token()
    session.add(
        Document(project_id=project_id, name=f"Site plan {token}", description=f"Issued for construction {token}")
    )
    await session.flush()

    hits = _of(await global_search(session, token), "documents")

    assert len(hits) == 1
    assert hits[0]["title"] == f"Site plan {token}"


@pytest.mark.asyncio
async def test_a_numbered_position_still_reads_number_then_description(
    session: AsyncSession, project_id: uuid.UUID
) -> None:
    """The composite title is what estimators read; the fix must not flatten it."""
    token = _token()
    boq = BOQ(project_id=project_id, name="Title harness")
    session.add(boq)
    await session.flush()
    session.add(Position(boq_id=boq.id, ordinal="01.10.030", description=f"Blinding {token}", unit="m2"))
    await session.flush()

    hits = _of(await global_search(session, token), "boq")

    assert len(hits) == 1
    assert hits[0]["title"] == f"01.10.030 - Blinding {token}"
