# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Formal BOQ revisions as one lineage: numbering, navigation, isolation.

Worked example: an estimate R0 is issued, the client changes scope, R1 is
raised from R0, then R2 from R1. Opening any of the three shows R0, R1, R2 in
order with the current one marked, its neighbours, each total and the delta
against the revision it was raised from. Ordinary duplicates, what-if
scenarios and estimate branches hang off ``parent_estimate_id`` as well but
are not chronological revisions, so they stay out of the lineage.
"""

from __future__ import annotations

import asyncio
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import ValidationContext
from app.modules.boq.branch_service import BranchService
from app.modules.boq.models import BOQ, Position
from app.modules.boq.revisions import (
    REVISION_KEY,
    RevisionService,
    next_revision_number,
    revision_name,
)
from app.modules.boq.schemas import PositionCreate, PositionUpdate, ScenarioCreate
from app.modules.boq.service import BOQService
from app.modules.boq.validators import RevisionSupersededStillEditable
from app.modules.projects.models import Project
from tests._pg import transactional_session

# ── Pure helpers ────────────────────────────────────────────────────────────


def test_a_revision_is_named_after_its_bill_not_as_a_copy() -> None:
    assert revision_name("Main estimate", 1) == "Main estimate (R1)"
    # Raising R2 from R1 replaces the suffix instead of stacking it.
    assert revision_name("Main estimate (R1)", 2) == "Main estimate (R2)"
    # A legacy "(Copy)" name is not carried into the new revision.
    assert revision_name("Main estimate (Copy)", 3) == "Main estimate (R3)"
    assert revision_name("   ", 1) == "(R1)"


def test_the_next_number_never_reuses_a_stored_or_derived_number() -> None:
    # R0 only: the first revision is R1.
    assert next_revision_number([None]) == 1
    # R0 plus one legacy child without a stored number: that child reads as R1.
    assert next_revision_number([None, None]) == 2
    # A gap left by a deleted R2 is never filled again.
    assert next_revision_number([None, 1, 3]) == 4


# ── Against the database ────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _seed(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """A project with one bill R0 of two priced lines (1,000 + 500). Returns (project, bill)."""
    project = Project(name=f"Rev {uuid.uuid4().hex[:6]}", currency="EUR", region="DACH", owner_id=uuid.uuid4())
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="Main estimate", status="draft", metadata_={})
    session.add(boq)
    await session.flush()
    boq_id = boq.id
    service = BOQService(session)
    for ordinal, desc, qty, rate in (("1", "Slab", 10, 100), ("2", "Walls", 5, 100)):
        await service.add_position(
            PositionCreate(boq_id=boq_id, ordinal=ordinal, description=desc, unit="m3", quantity=qty, unit_rate=rate)
        )
    session.expunge_all()
    return project.id, boq_id


async def _line(session: AsyncSession, boq_id: uuid.UUID, ordinal: str) -> Position:
    stmt = select(Position).where(Position.boq_id == boq_id, Position.ordinal == ordinal)
    return (await session.execute(stmt)).scalars().one()


async def _chain(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID]:
    """R0 -> R1 (slab quantity 10 -> 12) -> R2 (walls removed). Returns (project, r0, r1, r2)."""
    project_id, r0 = await _seed(session)
    revisions = RevisionService(session)
    author = uuid.uuid4()
    r1 = (await revisions.create_revision(r0, user_id=author)).id
    slab = await _line(session, r1, "1")
    await BOQService(session).update_position(slab.id, PositionUpdate(quantity=12))
    r2 = (await revisions.create_revision(r1, user_id=author)).id
    walls = await _line(session, r2, "2")
    await BOQService(session).delete_position(walls.id)
    session.expunge_all()
    return project_id, r0, r1, r2


@pytest.mark.asyncio
async def test_any_revision_shows_the_whole_lineage_in_order(session: AsyncSession) -> None:
    _, r0, r1, r2 = await _chain(session)
    revisions = RevisionService(session)

    for current in (r0, r1, r2):
        lineage = await revisions.lineage(current)
        assert [e.boq_id for e in lineage.revisions] == [r0, r1, r2]
        assert [e.label for e in lineage.revisions] == ["R0", "R1", "R2"]
        assert [e.is_current for e in lineage.revisions] == [current == r0, current == r1, current == r2]
        assert lineage.current_in_lineage is True
        assert lineage.root_id == r0

    middle = await revisions.lineage(r1)
    assert middle.previous_id == r0 and middle.next_id == r2
    first = await revisions.lineage(r0)
    assert first.previous_id is None and first.next_id == r1
    last = await revisions.lineage(r2)
    assert last.previous_id == r1 and last.next_id is None


@pytest.mark.asyncio
async def test_each_revision_carries_its_total_and_the_delta_to_its_source(session: AsyncSession) -> None:
    _, r0, r1, r2 = await _chain(session)
    lineage = await RevisionService(session).lineage(r2)
    by_id = {e.boq_id: e for e in lineage.revisions}

    assert by_id[r0].grand_total == Decimal("1500.00")
    assert by_id[r0].delta_vs_parent is None
    assert by_id[r1].grand_total == Decimal("1700.00")
    assert by_id[r1].delta_vs_parent == Decimal("200.00")
    assert by_id[r2].grand_total == Decimal("1200.00")
    assert by_id[r2].delta_vs_parent == Decimal("-500.00")


@pytest.mark.asyncio
async def test_a_new_revision_is_numbered_named_and_attributed(session: AsyncSession) -> None:
    _, r0 = await _seed(session)
    author = uuid.uuid4()
    r1 = await RevisionService(session).create_revision(r0, user_id=author)
    row = (
        await session.execute(
            select(BOQ.name, BOQ.parent_estimate_id, BOQ.created_by, BOQ.status, BOQ.metadata_).where(BOQ.id == r1.id)
        )
    ).one()
    assert row.name == "Main estimate (R1)"
    assert row.parent_estimate_id == r0
    assert row.created_by == author
    assert row.status == "draft"
    assert row.metadata_[REVISION_KEY]["number"] == 1
    # The source bill is not touched: no backfill of R0's own metadata.
    source_meta = (await session.execute(select(BOQ.metadata_).where(BOQ.id == r0))).scalar_one()
    assert REVISION_KEY not in (source_meta or {})


@pytest.mark.asyncio
async def test_two_revisions_raised_from_the_same_bill_get_distinct_numbers(session: AsyncSession) -> None:
    _, r0 = await _seed(session)
    revisions = RevisionService(session)
    a = await revisions.create_revision(r0, user_id=None)
    b = await revisions.create_revision(r0, user_id=None)
    lineage = await revisions.lineage(r0)
    assert [e.label for e in lineage.revisions] == ["R0", "R1", "R2"]
    assert {a.id, b.id} == {e.boq_id for e in lineage.revisions[1:]}


@pytest.mark.asyncio
async def test_concurrent_creation_in_one_session_never_repeats_a_number(session: AsyncSession) -> None:
    _, r0 = await _seed(session)
    revisions = RevisionService(session)
    lock = asyncio.Lock()

    async def raise_one() -> None:
        async with lock:  # one AsyncSession cannot run two statements at once
            await revisions.create_revision(r0, user_id=None)

    await asyncio.gather(raise_one(), raise_one(), raise_one())
    labels = [e.label for e in (await revisions.lineage(r0)).revisions]
    assert labels == ["R0", "R1", "R2", "R3"]


@pytest.mark.asyncio
async def test_duplicates_scenarios_and_branches_stay_out_of_the_lineage(session: AsyncSession) -> None:
    _, r0 = await _seed(session)
    service = BOQService(session)
    revisions = RevisionService(session)
    r1 = (await revisions.create_revision(r0, user_id=None)).id

    duplicate = await service.duplicate_boq(r1)
    duplicate_meta = (await session.execute(select(BOQ.metadata_).where(BOQ.id == duplicate.id))).scalar_one()
    assert REVISION_KEY not in (duplicate_meta or {})

    scenario = await service.create_scenario(r1, ScenarioCreate(name="What if steel +10%"), actor_id=uuid.uuid4())
    branch = await BranchService(session).create_branch(r0, name="Precast alternative")

    lineage = await revisions.lineage(r1)
    ids = [e.boq_id for e in lineage.revisions]
    assert ids == [r0, r1]
    assert duplicate.id not in ids and scenario.id not in ids and branch.id not in ids

    # Opened from the scenario, the navigator does not pretend it is a revision.
    from_scenario = await revisions.lineage(scenario.id)
    assert [e.boq_id for e in from_scenario.revisions] == [scenario.id]


@pytest.mark.asyncio
async def test_a_legacy_chain_reads_with_derived_numbers_and_keeps_growing(session: AsyncSession) -> None:
    project_id, r0 = await _seed(session)
    # A revision made before numbering existed: parent link only, "(Copy)" name.
    legacy = BOQ(
        project_id=project_id, name="Main estimate (Copy)", status="draft", parent_estimate_id=r0, metadata_={}
    )
    session.add(legacy)
    await session.flush()
    legacy_id = legacy.id
    session.expunge_all()

    revisions = RevisionService(session)
    new = await revisions.create_revision(legacy_id, user_id=None)
    lineage = await revisions.lineage(new.id)
    assert [(e.label, e.number_is_derived) for e in lineage.revisions] == [
        ("R0", False),
        ("R1", True),
        ("R2", False),
    ]
    # The legacy bill keeps its name; numbering never renames history.
    name = (await session.execute(select(BOQ.name).where(BOQ.id == legacy_id))).scalar_one()
    assert name == "Main estimate (Copy)"


@pytest.mark.asyncio
async def test_an_editable_superseded_revision_is_flagged_until_locked(session: AsyncSession) -> None:
    _, r0, r1, _r2 = await _chain(session)
    revisions = RevisionService(session)
    rule = RevisionSupersededStillEditable()

    block = await revisions.rule_block(r1)
    assert block is not None and block["label"] == "R1" and block["later_labels"] == ["R2"]
    findings = await rule.validate(ValidationContext(data={"revision": block}))
    assert len(findings) == 1 and not findings[0].passed
    assert "R2" in findings[0].message

    await session.execute(BOQ.__table__.update().where(BOQ.id == r1).values(is_locked=True))
    locked = await revisions.rule_block(r1)
    assert locked is not None and locked["is_locked"] is True
    assert await rule.validate(ValidationContext(data={"revision": locked})) == []
    # The newest revision has nothing after it.
    latest = await revisions.rule_block(_r2)
    assert await rule.validate(ValidationContext(data={"revision": latest})) == []
    # A bill outside any lineage gives no block at all.
    assert await revisions.rule_block(uuid.uuid4()) is None
    assert r0 is not None
