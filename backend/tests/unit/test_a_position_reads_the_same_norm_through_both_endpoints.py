# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""One position, two read paths, one answer about the norm that priced it.

Issue #457. A position is turned into a ``PositionResponse`` by two different
builders. ``service.build_position_response`` serves the whole-bill read and
sets the norm provenance; ``router._position_to_response`` serves every
single-position read and, when this file was written, did not mention the two
columns at all. So ``GET /boqs/{boq_id}`` answered the question and
``GET /positions/{position_id}`` answered ``null`` about the same row, with the
value sitting in the column. It shipped in v16.8.1 because every test written
for the feature asked one builder or the other, never both, and each of them
passed on its own.

That is what these tests are shaped against. They read one row through both
endpoints and assert the two answers are the same AND that they are the
identity the row was created with. Cross-endpoint equality alone is not enough:
``None == None`` is a passing comparison, so a regression that silenced both
builders would keep it green. Pinning to the seeded id is what makes the
comparison mean something.

The hand-typed line is here for the same reason from the other side. Absence has
to read back as absence through both endpoints, or a builder could satisfy the
first test by claiming a norm on every row.

The norm was the reported half of the drift and not all of it - six fields had
gone one way or the other - so the last test asserts the whole set. Two builders
for one entity will diverge again if they are allowed to exist; what this file
really guards is that there is one.

Run:
    cd backend
    python -m pytest tests/unit/test_a_position_reads_the_same_norm_through_both_endpoints.py -v
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.boq.models import BOQ, Position
from app.modules.boq.router import get_boq, get_position
from app.modules.boq.schemas import PositionCreate, PositionResponse
from app.modules.boq.service import BOQService
from app.modules.projects.models import Project
from tests._pg import transactional_session

WORK_KEY = "plastering_internal_two_coat"

#: Admins bypass ``_verify_boq_owner``, which keeps the ownership chain out of a
#: test about response shape. The owner id is still seeded and passed, so the
#: non-admin path would resolve too.
_ADMIN_PAYLOAD: dict[str, Any] = {"role": "admin", "permissions": []}


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    # FK triggers off so a project can be seeded without standing up a user row.
    async with transactional_session(disable_fks=True) as s:
        yield s


async def _seed_bill(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """A project with one empty bill. Returns (owner_id, boq_id)."""
    owner_id = uuid.uuid4()
    project = Project(
        name=f"Norm read path {uuid.uuid4().hex[:6]}",
        currency="EUR",
        region="DACH",
        owner_id=owner_id,
    )
    session.add(project)
    await session.flush()

    boq = BOQ(project_id=project.id, name="Bill priced from norms", status="draft", metadata_={})
    session.add(boq)
    await session.flush()
    return owner_id, boq.id


async def _add_norm_priced_line(session: AsyncSession, boq_id: uuid.UUID, norm_id: uuid.UUID) -> Position:
    """A line created the way applying an assembly built from a norm creates one."""
    position = await BOQService(session).add_position(
        PositionCreate(
            boq_id=boq_id,
            ordinal="1.1",
            description="Internal plastering, two coat",
            unit="m2",
            quantity=100,
            unit_rate=16.20,
            source="assembly",
            metadata={
                "assembly_id": str(uuid.uuid4()),
                "assembly_code": "ASM-PLA-01",
                "source": "assembly",
                "norm_id": str(norm_id),
                "work_key": WORK_KEY,
            },
        )
    )
    await session.flush()
    return position


async def _read_single(session: AsyncSession, position_id: uuid.UUID, owner_id: uuid.UUID) -> PositionResponse:
    """The row as ``GET /api/v1/boq/positions/{position_id}`` answers it."""
    return await get_position(
        position_id=position_id,
        user_id=str(owner_id),
        payload=dict(_ADMIN_PAYLOAD),
        session=session,
        service=BOQService(session),
    )


async def _read_from_bill(
    session: AsyncSession,
    boq_id: uuid.UUID,
    position_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> PositionResponse:
    """The same row as ``GET /api/v1/boq/boqs/{boq_id}`` answers it."""
    bill = await get_boq(
        boq_id=boq_id,
        _user_id=str(owner_id),
        payload=dict(_ADMIN_PAYLOAD),
        session=session,
        service=BOQService(session),
    )
    matching = [p for p in bill.positions if p.id == position_id]
    assert matching, "the bill read did not return the position under test"
    return matching[0]


class TestBothEndpointsAnswerTheSameNorm:
    async def test_a_norm_priced_line_reports_its_norm_through_both_endpoints(self, session: AsyncSession) -> None:
        """The headline. One row, two readers, one provenance."""
        owner_id, boq_id = await _seed_bill(session)
        norm_id = uuid.uuid4()
        position = await _add_norm_priced_line(session, boq_id, norm_id)

        single = await _read_single(session, position.id, owner_id)
        from_bill = await _read_from_bill(session, boq_id, position.id, owner_id)

        # Pinned to the seeded identity, not merely to each other: two Nones
        # agree, and that agreement is exactly the bug this file exists for.
        assert from_bill.norm_id == norm_id
        assert from_bill.norm_work_key == WORK_KEY
        assert single.norm_id == norm_id
        assert single.norm_work_key == WORK_KEY
        assert (single.norm_id, single.norm_work_key) == (from_bill.norm_id, from_bill.norm_work_key)

    async def test_a_hand_typed_line_claims_no_norm_through_either_endpoint(self, session: AsyncSession) -> None:
        """The denominator. Absence stays absence, or every row matches."""
        owner_id, boq_id = await _seed_bill(session)
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

        single = await _read_single(session, position.id, owner_id)
        from_bill = await _read_from_bill(session, boq_id, position.id, owner_id)

        assert (single.norm_id, single.norm_work_key) == (None, None)
        assert (from_bill.norm_id, from_bill.norm_work_key) == (None, None)

    async def test_the_two_endpoints_agree_on_every_field_that_had_drifted(self, session: AsyncSession) -> None:
        """The norm was not the only field the two builders disagreed about.

        Six had drifted, in both directions: the whole-bill read alone set
        ``risk_dispersion``, ``price_basis``, ``norm_id`` and ``norm_work_key``,
        the single-position read alone set ``cost_item_id`` and ``version``.
        Merging the builders is what fixes the norm, and it is also what makes
        the other four agree, so this asserts the whole set rather than the two
        fields the issue was reported about.

        Every value here is deliberately non-default. A field left at its schema
        default agrees with a builder that never sets it, which is the shape of
        the bug rather than evidence against it.
        """
        owner_id, boq_id = await _seed_bill(session)
        norm_id = uuid.uuid4()
        cost_item_id = uuid.uuid4()
        position = await _add_norm_priced_line(session, boq_id, norm_id)

        # The estimating-judgement columns are written by paths of their own
        # (a risk pass, a quote import), so they are set here directly: this is
        # a test about the shape of a response, not about who wrote the row.
        position.metadata_ = {**position.metadata_, "cost_item_id": str(cost_item_id)}
        position.risk_dispersion = "0.15"
        position.price_basis = "quote"
        position.version = 3
        await session.flush()

        single = await _read_single(session, position.id, owner_id)
        from_bill = await _read_from_bill(session, boq_id, position.id, owner_id)

        drifted = ("norm_id", "norm_work_key", "risk_dispersion", "price_basis", "cost_item_id", "version")
        assert {f: getattr(single, f) for f in drifted} == {f: getattr(from_bill, f) for f in drifted}
        assert single.norm_id == norm_id
        assert single.norm_work_key == WORK_KEY
        assert single.risk_dispersion == 0.15
        assert single.price_basis == "quote"
        assert single.cost_item_id == cost_item_id
        assert single.version == 3

    async def test_the_provenance_survives_serialisation_from_both_endpoints(self, session: AsyncSession) -> None:
        """A builder that sets a field the schema does not declare ships nothing.

        Asserting on the model attribute alone cannot see that: pydantic would
        have raised on the way in. Asserting on the serialised payload is what
        proves ``PositionResponse`` declares the fields and the client receives
        them.
        """
        owner_id, boq_id = await _seed_bill(session)
        norm_id = uuid.uuid4()
        position = await _add_norm_priced_line(session, boq_id, norm_id)

        single = (await _read_single(session, position.id, owner_id)).model_dump(mode="json")
        from_bill = (await _read_from_bill(session, boq_id, position.id, owner_id)).model_dump(mode="json")

        assert single["norm_id"] == str(norm_id)
        assert single["norm_work_key"] == WORK_KEY
        assert from_bill["norm_id"] == str(norm_id)
        assert from_bill["norm_work_key"] == WORK_KEY
        # The metadata the write path read the identity out of is still there,
        # under both spellings the two builders used to pass it through.
        assert single["metadata"]["norm_id"] == str(norm_id)
        assert from_bill["metadata"]["norm_id"] == str(norm_id)
