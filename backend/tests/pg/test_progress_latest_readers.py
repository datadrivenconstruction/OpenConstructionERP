"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠PG: the single-row "latest" readers lead with ``seq``, not with ``recorded_at``.

Progress entries are append-only: a mistake is corrected by recording a NEW
entry, so the reading that counts is the one appended LAST. ``seq`` is what
makes that well defined - see :func:`app.modules.progress.repository._latest_first`
and migration ``v3258_progress_entry_seq``.

Three readers were ordering by ``recorded_at DESC`` alone and never went
through ``_latest_first()``, so they answered a different question from the
rest of the module:

* ``get_latest_for_position`` - the contracts progress-claim bridge reads the
  percent it bills from this row (``contracts/service.py``);
* ``get_latest_project_entry`` - the headline "overall % complete" on the
  client-facing progress report (``reporting/service.py``);
* ``get_entries_for_period`` - the same report takes element 0 of this list as
  the reporting window's percentage.

``recorded_at`` is not a total order. It defaults to the DB's ``now()``, which
in PostgreSQL is the TRANSACTION timestamp, so every row one transaction
writes shares it exactly; and it is back-datable, which is the case pinned
here. A correction appended after the reading it corrects, carrying an earlier
``recorded_at``, used to lose to the row it was meant to replace.

Real PostgreSQL because ``seq`` is a sequence-backed server default: on a
dialect without it the column these tests are about does not populate.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.modules.boq.models import BOQ, Position
from app.modules.progress.models import ProgressEntry
from app.modules.progress.repository import ProgressRepository
from app.modules.projects.models import Project
from app.modules.users.models import User

PERIOD = "2026-W21"

# The original reading, then the correction. The correction is appended second
# (so it takes the higher seq) but carries the EARLIER recorded_at, which is
# what a back-dated fix looks like. Ordering by recorded_at alone returns the
# 90 that the 30 exists to replace.
_SUPERSEDED_PCT = 90.0
_CORRECTION_PCT = 30.0


# ── Seeding ────────────────────────────────────────────────────────────────


async def _seed_project(session) -> Project:
    """Insert an owner and one project."""
    owner = User(email=f"latest-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(owner)
    await session.flush()
    project = Project(name="Latest reader project", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    return project


async def _seed_position(session, project: Project) -> Position:
    """Give the project one BOQ holding a single line to record against."""
    boq = BOQ(project_id=project.id, name="Main BOQ")
    session.add(boq)
    await session.flush()
    position = Position(boq_id=boq.id, ordinal="01.001", description="Line 1", unit="m3", quantity="100")
    session.add(position)
    await session.flush()
    return position


async def _append(session, project_id: uuid.UUID, pct: float, recorded_at: datetime, position_id=None) -> ProgressEntry:
    """Append one observation and read its database-assigned ``seq`` back.

    Flushed on its own so the sequence hands out numbers in call order, and
    refreshed because ``seq`` is a server default the INSERT does not return.
    """
    entry = ProgressEntry(
        project_id=project_id,
        boq_position_id=position_id,
        period_label=PERIOD,
        percent_complete=pct,
        recorded_at=recorded_at,
    )
    session.add(entry)
    await session.flush()
    await session.refresh(entry)
    return entry


async def _append_superseded_then_correction(session, project_id: uuid.UUID, position_id=None):
    """Write the reading, then a correction back-dated an hour behind it.

    Returns ``(superseded, correction)`` after asserting the shape the tests
    depend on: the correction really did land on a HIGHER seq while carrying
    an EARLIER timestamp. Without this the file could keep passing while
    testing nothing.
    """
    now = datetime.now(UTC)
    superseded = await _append(session, project_id, _SUPERSEDED_PCT, now, position_id)
    correction = await _append(session, project_id, _CORRECTION_PCT, now - timedelta(hours=1), position_id)

    assert correction.seq > superseded.seq, "the correction must be the later INSERT"
    assert correction.recorded_at < superseded.recorded_at, "the correction must be back-dated"

    # The discriminator. Ordering by recorded_at alone - what these readers did
    # before - returns the row the correction was written to supersede. Pinning
    # it here means the scenario cannot quietly stop telling the two orderings
    # apart and leave the tests below passing for the wrong reason.
    stale = (
        await session.execute(
            select(ProgressEntry)
            .where(ProgressEntry.project_id == project_id)
            .order_by(ProgressEntry.recorded_at.desc())
            .limit(1)
        )
    ).scalar_one()
    assert stale.id == superseded.id, "the old ordering must disagree, or this scenario proves nothing"

    return superseded, correction


# ── The readers ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_back_dated_correction_wins_for_the_position_reader(pg_session) -> None:
    """``get_latest_for_position`` returns the appended-last row, not the newest timestamp."""
    project = await _seed_project(pg_session)
    position = await _seed_position(pg_session, project)
    _superseded, correction = await _append_superseded_then_correction(pg_session, project.id, position.id)

    latest = await ProgressRepository(pg_session).get_latest_for_position(project.id, position.id)

    assert latest is not None
    assert latest.id == correction.id
    assert float(latest.percent_complete) == _CORRECTION_PCT


@pytest.mark.asyncio
async def test_a_back_dated_correction_wins_for_the_project_reader(pg_session) -> None:
    """``get_latest_project_entry`` picks the headline percentage by seq."""
    project = await _seed_project(pg_session)
    _superseded, correction = await _append_superseded_then_correction(pg_session, project.id)

    latest = await ProgressRepository(pg_session).get_latest_project_entry(project.id)

    assert latest is not None
    assert latest.id == correction.id
    assert float(latest.percent_complete) == _CORRECTION_PCT


@pytest.mark.asyncio
async def test_the_period_list_leads_with_the_appended_last_row(pg_session) -> None:
    """``get_entries_for_period`` puts the winner at element 0, which is what the report reads.

    The count alongside it is order-independent, so it is asserted too: the
    fix must reorder the window, not narrow it.
    """
    project = await _seed_project(pg_session)
    _superseded, correction = await _append_superseded_then_correction(pg_session, project.id)

    entries = await ProgressRepository(pg_session).get_entries_for_period(project.id, PERIOD)

    assert len(entries) == 2
    assert entries[0].id == correction.id
    assert float(entries[0].percent_complete) == _CORRECTION_PCT


@pytest.mark.asyncio
async def test_the_position_reader_still_refuses_another_projects_position(pg_session) -> None:
    """The tenant scope survives the ordering change.

    ``get_latest_for_position`` filters on ``project_id`` as well as the
    position so a position id from another project cannot leak an observation.
    Reordering touched that query, so the guarantee is re-pinned here.
    """
    owner_project = await _seed_project(pg_session)
    position = await _seed_position(pg_session, owner_project)
    await _append_superseded_then_correction(pg_session, owner_project.id, position.id)

    other_project = await _seed_project(pg_session)

    assert await ProgressRepository(pg_session).get_latest_for_position(other_project.id, position.id) is None
