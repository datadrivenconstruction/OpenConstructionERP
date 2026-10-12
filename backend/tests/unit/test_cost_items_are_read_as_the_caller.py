# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A cost item in a user-owned catalogue is read by its owner and by admins only.

``app.core.cost_scope`` applies one rule to every ORM read of a cost item, for
the caller the request bound. These tests pin the rule against the query
shapes the code uses: a column select, an alias, a join, a subquery, a union,
an aggregate and a load by primary key all have to give the same answer.

Three users: A owns a private catalogue, B is another user, and an admin.
Every case also carries a shared row B must keep seeing, so a rule that
simply hid everything would fail too.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import func, select, text, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core import cost_scope
from app.modules.costs.models import CostCatalog, CostItem
from app.modules.users.models import User
from tests._pg import transactional_session

_WORD = "zzprivatescope"


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _user(s: AsyncSession, role: str) -> uuid.UUID:
    user = User(
        id=uuid.uuid4(),
        email=f"scope-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x" * 60,
        full_name="Scope Test",
        role=role,
        locale="en",
        is_active=True,
        metadata_={},
    )
    s.add(user)
    await s.flush()
    return user.id


class World:
    """A's private catalogue with two rows, one shared row, and three users."""

    alice: uuid.UUID
    bob: uuid.UUID
    admin: uuid.UUID
    catalog_id: uuid.UUID
    private_ids: list[uuid.UUID]
    shared_id: uuid.UUID
    region: str


async def _world(s: AsyncSession) -> World:
    w = World()
    with cost_scope.system_scope():
        w.alice = await _user(s, "manager")
        w.bob = await _user(s, "editor")
        w.admin = await _user(s, "admin")
        w.region = f"RQA-PRIV-{uuid.uuid4().hex[:6]}"
        catalog = CostCatalog(id=uuid.uuid4(), name=w.region, currency="EUR", created_by=w.alice)
        s.add(catalog)
        await s.flush()
        w.catalog_id = catalog.id
        private = [
            CostItem(
                id=uuid.uuid4(),
                code=f"PRIV.{i:03d}",
                description=f"{_WORD} private wall {i}",
                unit="m2",
                rate="101.5",
                currency="EUR",
                region=w.region,
                catalog_id=catalog.id,
                classification={"collection": "Private walls"},
                is_active=True,
            )
            for i in range(2)
        ]
        shared = CostItem(
            id=uuid.uuid4(),
            code="SHARED.001",
            description=f"{_WORD} shared wall",
            unit="m2",
            rate="55",
            currency="EUR",
            region=f"SHARED-{uuid.uuid4().hex[:6]}",
            classification={"collection": "Shared walls"},
            is_active=True,
        )
        s.add_all([*private, shared])
        await s.flush()
        w.private_ids = [p.id for p in private]
        w.shared_id = shared.id
    # Nothing a test reads may come from the identity map instead of the query.
    s.expire_all()
    return w


def _mine(w: World) -> Any:
    return CostItem.id.in_([*w.private_ids, w.shared_id])


async def _ids(s: AsyncSession, stmt: Any) -> set[uuid.UUID]:
    return {row[0] for row in (await s.execute(stmt)).all()}


READERS = [
    ("alice", True),
    ("admin", True),
    ("bob", False),
    (None, False),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("reader", "sees_private"), READERS)
async def test_every_query_shape_follows_the_rule(
    session: AsyncSession, reader: str | None, sees_private: bool
) -> None:
    w = await _world(session)
    expected = {w.shared_id, *(w.private_ids if sees_private else [])}
    private = set(w.private_ids)
    other = aliased(CostItem)
    shapes: dict[str, Any] = {
        "entity": select(CostItem.id).select_from(CostItem).where(_mine(w)),
        "column": select(CostItem.id).where(_mine(w)),
        "aliased": select(other.id).where(other.id.in_([*w.private_ids, w.shared_id])),
        "joined": select(CostItem.id)
        .join(CostCatalog, CostCatalog.id == CostItem.catalog_id, isouter=True)
        .where(_mine(w)),
        "subquery": select(CostItem.id).where(
            CostItem.id.in_(select(other.id).where(other.description.ilike(f"%{_WORD}%")))
        ),
        "union": union_all(
            select(CostItem.id).where(CostItem.id.in_(w.private_ids)),
            select(CostItem.id).where(CostItem.id == w.shared_id),
        ),
        "text column": select(CostItem.id, text("oe_costs_item.rate")).where(_mine(w)),
    }
    with cost_scope.caller_scope(getattr(w, reader) if reader else None):
        for name, stmt in shapes.items():
            got = await _ids(session, stmt)
            assert got & private == (private if sees_private else set()), f"{name} as {reader}"
            assert w.shared_id in got, f"{name} as {reader} lost the shared row"

        rows = (await session.execute(select(CostItem).where(_mine(w)))).scalars().all()
        assert {r.id for r in rows} == expected

        count = (await session.execute(select(func.count(CostItem.id)).where(_mine(w)))).scalar()
        assert count == len(expected)

        grouped = dict(
            (
                await session.execute(
                    select(CostItem.region, func.count(CostItem.id)).where(_mine(w)).group_by(CostItem.region)
                )
            ).all()
        )
        assert (w.region in grouped) is sees_private

        session.expire_all()
        got_one = await session.get(CostItem, w.private_ids[0])
        assert (got_one is not None) is sees_private
        assert await session.get(CostItem, w.shared_id) is not None

        visible = await cost_scope.visible_ids(session, [*w.private_ids, w.shared_id, "not-a-uuid"])
        assert visible == {str(i) for i in expected}


@pytest.mark.asyncio
async def test_system_work_reads_every_row_even_when_a_request_started_it(session: AsyncSession) -> None:
    w = await _world(session)
    with cost_scope.caller_scope(w.bob):
        assert not await _ids(session, select(CostItem.id).where(CostItem.id.in_(w.private_ids)))
        with cost_scope.system_scope():
            assert cost_scope.is_system()
            assert await _ids(session, select(CostItem.id).where(CostItem.id.in_(w.private_ids))) == set(w.private_ids)
        assert not await _ids(session, select(CostItem.id).where(CostItem.id.in_(w.private_ids)))
    assert cost_scope.is_system()


@pytest.mark.asyncio
async def test_a_row_whose_catalogue_is_gone_is_read_by_admins_only(session: AsyncSession) -> None:
    w = await _world(session)
    with cost_scope.system_scope():
        orphan = CostItem(
            id=uuid.uuid4(),
            code="ORPHAN.001",
            description="orphan",
            unit="m2",
            rate="1",
            currency="EUR",
            region=w.region,
            catalog_id=uuid.uuid4(),
            is_active=True,
        )
        session.add(orphan)
        await session.flush()
        orphan_id = orphan.id
    session.expire_all()
    for reader, sees in ((w.alice, False), (w.bob, False), (None, False), (w.admin, True)):
        with cost_scope.caller_scope(reader):
            assert bool(await _ids(session, select(CostItem.id).where(CostItem.id == orphan_id))) is sees


@pytest.mark.asyncio
async def test_a_demoted_admin_stops_reading_private_rows_at_once(session: AsyncSession) -> None:
    """The admin test reads the stored role, not a claim made when a token was issued."""
    w = await _world(session)
    stmt = select(CostItem.id).where(CostItem.id.in_(w.private_ids))
    with cost_scope.caller_scope(w.admin):
        assert await _ids(session, stmt) == set(w.private_ids)
        admin = await session.get(User, w.admin)
        admin.role = "editor"
        await session.flush()
        assert not await _ids(session, stmt)
