# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every path that copies a bill line carries its norm onto the column.

Issue #457. ``add_position`` is not the only writer of a position. A line is
also created by duplicating one, by duplicating a whole bill into a revision, by
restoring a snapshot and by the bulk create the importers use, and each of those
builds the row field by field instead of going through the single-create path.
All of them copy ``metadata``, so before this the copy carried the norm identity
in its metadata against a NULL ``norm_id`` column.

Which is why these assertions are on the COLUMN and never on the report. The
read side coalesces column then metadata, so a test that asked "does the
comparison still answer for the copy" passes identically with the copy sites
fixed and unfixed - it is measuring the fallback, not the fix. The column being
NULL is invisible until somebody groups by it, and then it is invisible in the
worst way: the query returns a number, and the number is a fraction of the work
reported as the whole of it. The bills this would hit hardest are the ones that
have been duplicated and revised most, which are the ones anybody actually wants
an outturn comparison for.

Run:
    cd backend
    python -m pytest tests/modules/boq/test_norm_provenance_survives_copies.py -v
"""

from __future__ import annotations

import uuid

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.boq.schemas import PositionCreate
from app.modules.boq.service import BOQService
from app.modules.projects.models import Project
from tests._pg import transactional_session

WORK_KEY = "plastering_internal_two_coat"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    # FK triggers off so a project can be seeded without standing up a user row.
    async with transactional_session(disable_fks=True) as s:
        yield s


def _norm_metadata(norm_id: uuid.UUID) -> dict:
    """The metadata shape ``apply_to_boq`` writes for a norm-priced line."""
    return {
        "assembly_id": str(uuid.uuid4()),
        "assembly_code": "ASM-PLA-01",
        "source": "assembly",
        "norm_id": str(norm_id),
        "work_key": WORK_KEY,
    }


async def _seed_bill(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """A project with one empty bill. Returns (project_id, boq_id)."""
    project = Project(
        name=f"Norm provenance {uuid.uuid4().hex[:6]}",
        currency="EUR",
        region="DACH",
        owner_id=uuid.uuid4(),
    )
    session.add(project)
    await session.flush()

    boq = BOQ(project_id=project.id, name="Bill priced from norms", status="draft", metadata_={})
    session.add(boq)
    await session.flush()
    return project.id, boq.id


async def _add_norm_priced_line(
    service: BOQService,
    boq_id: uuid.UUID,
    norm_id: uuid.UUID,
    *,
    ordinal: str = "1.1",
) -> Position:
    return await service.add_position(
        PositionCreate(
            boq_id=boq_id,
            ordinal=ordinal,
            description="Internal plastering, two coat",
            unit="m2",
            quantity=100,
            unit_rate=16.20,
            source="assembly",
            metadata=_norm_metadata(norm_id),
        )
    )


async def _columns_of(session: AsyncSession, position_id: uuid.UUID) -> tuple[str | None, str | None]:
    """Read the two columns straight out of the row, past the ORM identity map."""
    row = (
        await session.execute(
            select(Position.norm_id, Position.norm_work_key).where(Position.id == position_id),
        )
    ).first()
    assert row is not None
    return (str(row[0]) if row[0] else None), row[1]


class TestTheLineItself:
    async def test_a_norm_priced_line_lands_on_the_column(self, session: AsyncSession) -> None:
        """The baseline the rest of this file is measured against."""
        _project_id, boq_id = await _seed_bill(session)
        norm_id = uuid.uuid4()

        position = await _add_norm_priced_line(BOQService(session), boq_id, norm_id)
        await session.flush()

        assert await _columns_of(session, position.id) == (str(norm_id), WORK_KEY)

    async def test_a_hand_typed_line_claims_no_norm(self, session: AsyncSession) -> None:
        """The denominator. Absence has to stay absence, or every row matches."""
        _project_id, boq_id = await _seed_bill(session)

        position = await BOQService(session).add_position(
            PositionCreate(
                boq_id=boq_id,
                ordinal="1.9",
                description="Make good on completion",
                unit="lsum",
                quantity=1,
                unit_rate=850,
                source="manual",
            )
        )
        await session.flush()

        assert await _columns_of(session, position.id) == (None, None)


class TestTheCopies:
    """One test per writer that builds a Position outside ``add_position``."""

    async def test_duplicating_a_line_carries_its_norm(self, session: AsyncSession) -> None:
        _project_id, boq_id = await _seed_bill(session)
        norm_id = uuid.uuid4()
        service = BOQService(session)
        original = await _add_norm_priced_line(service, boq_id, norm_id)
        await session.flush()

        copy = await service.duplicate_position(original.id)
        await session.flush()

        assert copy.id != original.id
        assert await _columns_of(session, copy.id) == (str(norm_id), WORK_KEY)

    async def test_duplicating_a_bill_carries_every_norm(self, session: AsyncSession) -> None:
        """The baseline-to-revision path, and the one that matters most.

        An outturn comparison is normally read against the current revision of a
        bill rather than the original, so a revision that loses the provenance
        loses it exactly where the question gets asked.
        """
        _project_id, boq_id = await _seed_bill(session)
        first_norm = uuid.uuid4()
        second_norm = uuid.uuid4()
        service = BOQService(session)
        await _add_norm_priced_line(service, boq_id, first_norm, ordinal="1.1")
        await _add_norm_priced_line(service, boq_id, second_norm, ordinal="1.2")
        await session.flush()

        copy = await service.duplicate_boq(boq_id)
        await session.flush()

        copied = (
            await session.execute(
                select(Position.norm_id, Position.norm_work_key)
                .where(Position.boq_id == copy.id)
                .order_by(Position.ordinal),
            )
        ).all()
        assert [(str(nid), key) for nid, key in copied] == [
            (str(first_norm), WORK_KEY),
            (str(second_norm), WORK_KEY),
        ]

    async def test_restoring_a_snapshot_carries_the_norm(self, session: AsyncSession) -> None:
        """Restore rebuilds from the snapshot's JSON, not from the live rows.

        The snapshot format does not carry the column and older snapshots never
        will, so the restore reads the identity back out of the metadata the
        snapshot does carry.
        """
        _project_id, boq_id = await _seed_bill(session)
        norm_id = uuid.uuid4()
        service = BOQService(session)
        await _add_norm_priced_line(service, boq_id, norm_id)
        await session.flush()

        snapshot = await service.create_snapshot(boq_id, name="Before the change")
        await session.flush()
        await service.restore_snapshot(boq_id, snapshot.id)
        await session.flush()

        restored = (
            await session.execute(
                select(Position.norm_id, Position.norm_work_key).where(Position.boq_id == boq_id),
            )
        ).all()
        assert [(str(nid), key) for nid, key in restored] == [(str(norm_id), WORK_KEY)]

    async def test_the_bulk_create_path_lands_on_the_column(self, session: AsyncSession) -> None:
        """What an importer or a template expansion writes through."""
        _project_id, boq_id = await _seed_bill(session)
        norm_id = uuid.uuid4()

        created = await BOQService(session).bulk_add_positions(
            boq_id,
            [
                PositionCreate(
                    boq_id=boq_id,
                    ordinal="2.1",
                    description="Internal plastering, two coat",
                    unit="m2",
                    quantity=40,
                    unit_rate=16.20,
                    source="assembly",
                    metadata=_norm_metadata(norm_id),
                ),
                PositionCreate(
                    boq_id=boq_id,
                    ordinal="2.2",
                    description="Make good on completion",
                    unit="lsum",
                    quantity=1,
                    unit_rate=850,
                    source="manual",
                ),
            ],
        )
        await session.flush()

        assert await _columns_of(session, created[0].id) == (str(norm_id), WORK_KEY)
        # The line nobody priced from a norm still claims none.
        assert await _columns_of(session, created[1].id) == (None, None)


class TestWhatDoesNotTravel:
    async def test_a_malformed_id_in_the_metadata_is_not_copied_onto_the_column(self, session: AsyncSession) -> None:
        """Metadata is free-form JSON that clients write, so it holds anything.

        The column is a varchar under the platform's GUID type, so an unguarded
        copy would store the junk happily and the report would carry a norm
        nobody can look up.
        """
        _project_id, boq_id = await _seed_bill(session)
        service = BOQService(session)
        original = await service.add_position(
            PositionCreate(
                boq_id=boq_id,
                ordinal="3.1",
                description="Internal plastering, two coat",
                unit="m2",
                quantity=100,
                unit_rate=16.20,
                source="assembly",
                metadata={"norm_id": "not-a-uuid", "work_key": WORK_KEY},
            )
        )
        await session.flush()

        copy = await service.duplicate_position(original.id)
        await session.flush()

        assert await _columns_of(session, original.id) == (None, None)
        assert await _columns_of(session, copy.id) == (None, None)

    async def test_a_work_key_without_an_id_does_not_reach_the_column(self, session: AsyncSession) -> None:
        """The two columns may never disagree about whether there is a norm."""
        _project_id, boq_id = await _seed_bill(session)
        service = BOQService(session)
        original = await service.add_position(
            PositionCreate(
                boq_id=boq_id,
                ordinal="3.2",
                description="Internal plastering, two coat",
                unit="m2",
                quantity=100,
                unit_rate=16.20,
                source="assembly",
                metadata={"work_key": WORK_KEY},
            )
        )
        await session.flush()

        copy = await service.duplicate_position(original.id)
        await session.flush()

        assert await _columns_of(session, copy.id) == (None, None)
