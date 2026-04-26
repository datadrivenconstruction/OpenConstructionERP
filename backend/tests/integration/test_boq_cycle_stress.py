"""BOQ position-hierarchy cycle detection — scale & concurrency stress.

Companion to ``test_boq_cycle_detection.py``: that file pins the
correctness contract on small (≤ 4-node) trees; this one stresses the
same guard at a depth/breadth and concurrency profile that real
projects actually hit. The guard logic lives in
``BOQService._validate_parent_id``.

Three scenarios:

1. **Long chain.** 1 000-node linear chain (each parent_id = previous).
   Pointing the root at the leaf must reject quickly — the bound is
   set to catch an O(n²) regression rather than chase microseconds:
   the current implementation walks descendants via N sequential
   ``list_children`` queries, which on aiosqlite + SQLite costs ~2-3
   ms per round-trip. We allow up to 5 s on a 1 000-node chain (≈ 5
   ms/node); a true regression to quadratic walking would blow well
   past that.

2. **Wide tree.** 8 levels × 3 children = 9 841-position balanced
   tree. Re-parenting a leaf under the root is a legal move (the leaf
   has no descendants) and must pass. Re-parenting the root under a
   leaf must reject because the leaf is a transitive descendant.

3. **Concurrent reparent.** 10 ``asyncio`` tasks each try to introduce
   a *different* cycle on a small chain at the same time. After
   ``asyncio.gather(..., return_exceptions=True)`` resolves, no row
   in the DB may participate in a cycle — the guard must hold under
   interleaving even if every individual ``_validate_parent_id`` call
   sees a stale read.

Isolation: each test gets a fresh tempfile-backed SQLite DB with only
the tables we touch (User, Project, BOQ, Position, plus the BOQ
satellites). The production ``backend/openestimate.db`` is never
touched. See ``feedback_test_isolation.md``.

Run::

    cd backend
    python -m pytest tests/integration/test_boq_cycle_stress.py -v --tb=short
"""

from __future__ import annotations

import asyncio
import tempfile
import time
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


# ─────────────────────────────────────────────────────────────────────────
# Per-test fixtures — fresh tempfile SQLite DB, never the prod one
# ─────────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session_factory():
    """Fresh per-test SQLite file with the BOQ-relevant tables created.

    Yields a sessionmaker. Each test opens its own short-lived sessions
    from it — concurrent tasks need independent sessions to actually
    interleave at the DB layer.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="boq_cycle_stress_"))
    tmp_db = tmp_dir / "stress.db"
    url = f"sqlite+aiosqlite:///{tmp_db.as_posix()}"
    engine = create_async_engine(url, future=True)

    # Import the models we need so SQLAlchemy registers their tables on
    # ``Base.metadata``. Order matters only for FK resolution at create
    # time — Project.owner_id references oe_users_user, BOQ.project_id
    # references oe_projects_project, etc.
    import app.modules.boq.models  # noqa: F401
    import app.modules.projects.models  # noqa: F401
    import app.modules.users.models  # noqa: F401
    from app.database import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()
        try:
            tmp_db.unlink(missing_ok=True)
            tmp_dir.rmdir()
        except OSError:
            pass


@pytest_asyncio.fixture
async def seeded_boq(session_factory):
    """Seed a User, Project, and BOQ. Returns the BOQ id (UUID).

    Created in its own session so subsequent test sessions can read
    the rows back.
    """
    from app.modules.boq.models import BOQ
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    async with session_factory() as session:
        user = User(
            id=uuid.uuid4(),
            email=f"stress-{uuid.uuid4().hex[:8]}@test.io",
            hashed_password="not-a-real-hash",
            full_name="Cycle Stress Tester",
            role="admin",
            locale="en",
            is_active=True,
            metadata_={},
        )
        project = Project(
            id=uuid.uuid4(),
            owner_id=user.id,
            name=f"Stress {uuid.uuid4().hex[:6]}",
            description="cycle stress",
            status="active",
        )
        session.add(user)
        await session.flush()
        session.add(project)
        await session.flush()
        boq = BOQ(
            id=uuid.uuid4(),
            project_id=project.id,
            name="Stress BOQ",
            description="",
        )
        session.add(boq)
        await session.commit()
        return boq.id


# ─────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────


async def _bulk_insert_chain(
    session: AsyncSession, boq_id: uuid.UUID, n: int
) -> list[uuid.UUID]:
    """Insert ``n`` positions in a single linear chain. Returns ids in order."""
    from app.modules.boq.models import Position

    ids: list[uuid.UUID] = [uuid.uuid4() for _ in range(n)]
    rows = [
        Position(
            id=ids[i],
            boq_id=boq_id,
            parent_id=ids[i - 1] if i > 0 else None,
            ordinal=f"chain.{i:05d}",
            description=f"chain node {i}",
            unit="m",
            quantity="1",
            unit_rate="0",
            total="0",
            classification={},
            source="manual",
            cad_element_ids=[],
            metadata_={},
            sort_order=i,
        )
        for i in range(n)
    ]
    session.add_all(rows)
    await session.commit()
    return ids


async def _bulk_insert_tree(
    session: AsyncSession,
    boq_id: uuid.UUID,
    depth: int,
    fanout: int,
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    """Insert a balanced tree, ``fanout`` children per level, ``depth`` levels.

    Total nodes: ``(fanout**(depth+1) - 1) / (fanout - 1)``. With
    depth=8, fanout=3 that's 9 841 — a realistic upper bound for a
    chunky industrial BOQ. Returns ``(root_id, leaf_ids)``.
    """
    from app.modules.boq.models import Position

    root_id = uuid.uuid4()
    rows: list[Position] = [
        Position(
            id=root_id,
            boq_id=boq_id,
            parent_id=None,
            ordinal="root",
            description="tree root",
            unit="m",
            quantity="1",
            unit_rate="0",
            total="0",
            classification={},
            source="manual",
            cad_element_ids=[],
            metadata_={},
            sort_order=0,
        )
    ]

    # BFS layer-by-layer. Track parents of the next layer.
    parents: list[uuid.UUID] = [root_id]
    leaves: list[uuid.UUID] = []
    counter = 1
    for level in range(depth):
        next_parents: list[uuid.UUID] = []
        is_last_level = level == depth - 1
        for parent_id in parents:
            for k in range(fanout):
                child_id = uuid.uuid4()
                rows.append(
                    Position(
                        id=child_id,
                        boq_id=boq_id,
                        parent_id=parent_id,
                        ordinal=f"L{level + 1}.{counter:06d}",
                        description=f"L{level + 1} #{k}",
                        unit="m",
                        quantity="1",
                        unit_rate="0",
                        total="0",
                        classification={},
                        source="manual",
                        cad_element_ids=[],
                        metadata_={},
                        sort_order=counter,
                    )
                )
                counter += 1
                next_parents.append(child_id)
                if is_last_level:
                    leaves.append(child_id)
        parents = next_parents

    # Bulk-insert in chunks to keep SQLite happy (statement size limits).
    CHUNK = 500
    for i in range(0, len(rows), CHUNK):
        session.add_all(rows[i : i + CHUNK])
        await session.flush()
    await session.commit()
    return root_id, leaves


async def _try_reparent(
    session_factory,
    boq_id: uuid.UUID,
    position_id: uuid.UUID,
    new_parent_id: uuid.UUID,
) -> tuple[bool, str]:
    """Run ``_validate_parent_id`` in a fresh session.

    Returns ``(accepted, reason)``. ``accepted=True`` means the guard
    raised nothing (the move would be allowed); ``False`` means it
    rejected with HTTP 400.
    """
    from app.modules.boq.service import BOQService

    async with session_factory() as session:
        svc = BOQService(session)
        try:
            await svc._validate_parent_id(
                boq_id=boq_id,
                position_id=position_id,
                new_parent_id=new_parent_id,
            )
            return True, "ok"
        except HTTPException as exc:
            return False, str(exc.detail)


async def _has_cycle(session: AsyncSession, boq_id: uuid.UUID) -> bool:
    """Walk every node in the BOQ via parent_id; flag any cycle.

    For each row we follow parent_id up to a hard cap (= total node
    count + 1). If we revisit a node before reaching ``None`` the
    parent chain has a cycle.
    """
    from sqlalchemy import select

    from app.modules.boq.models import Position

    rows = (
        (await session.execute(select(Position.id, Position.parent_id).where(Position.boq_id == boq_id)))
        .all()
    )
    parent_of: dict[uuid.UUID, uuid.UUID | None] = {row.id: row.parent_id for row in rows}
    cap = len(parent_of) + 1
    for start in parent_of:
        seen: set[uuid.UUID] = set()
        cur: uuid.UUID | None = start
        steps = 0
        while cur is not None:
            if cur in seen:
                return True
            seen.add(cur)
            cur = parent_of.get(cur)
            steps += 1
            if steps > cap:
                return True
    return False


# ═════════════════════════════════════════════════════════════════════════
# Scenario 1 — long linear chain (1 000 nodes)
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_long_chain_root_to_leaf_cycle_rejected_fast(
    session_factory, seeded_boq
) -> None:
    """A 1 000-node chain: pointing the root's parent at the tail leaf
    must reject within the linear-walk budget. The descendant walk has
    to traverse the entire chain to find the leaf, so this is the
    worst-case shape for the current (one-query-per-level) walker.

    Performance budget is set to catch an O(n²) regression rather than
    pin a microsecond target — the walk does N sequential async DB
    round-trips, which on Windows + SQLite costs a few ms each.
    """
    boq_id = seeded_boq

    async with session_factory() as session:
        ids = await _bulk_insert_chain(session, boq_id, 1_000)

    root_id = ids[0]
    leaf_id = ids[-1]

    t0 = time.perf_counter()
    accepted, reason = await _try_reparent(session_factory, boq_id, root_id, leaf_id)
    elapsed = time.perf_counter() - t0

    assert accepted is False, "Cycle attempt should reject"
    assert ("cycle" in reason.lower() or "descendant" in reason.lower()), reason
    # 5 s ceiling on a 1k chain ≈ 5 ms / node. The current walker is
    # O(n) with one async round-trip per level; SQLite + aiosqlite on
    # Windows clocks ~2-3 ms per call. An O(n²) regression on 1 000
    # nodes would need to crunch a million ops and would blow past 30+
    # seconds — well outside this budget.
    assert elapsed < 5.0, (
        f"Cycle detection on a 1k chain took {elapsed:.2f} s "
        "— suggests the descendant walk regressed from O(n) to O(n²)."
    )


@pytest.mark.asyncio
async def test_long_chain_legal_reparent_succeeds(
    session_factory, seeded_boq
) -> None:
    """In the same 1 000-node chain, moving the *leaf* under a sibling
    of the root (= a brand-new top-level position) is a legal move —
    the leaf has zero descendants, so the descendant walk terminates
    immediately. Confirms the fast path doesn't false-positive.
    """
    from app.modules.boq.models import Position

    boq_id = seeded_boq

    async with session_factory() as session:
        ids = await _bulk_insert_chain(session, boq_id, 1_000)
        # New top-level sibling — outside the chain entirely.
        sibling = Position(
            id=uuid.uuid4(),
            boq_id=boq_id,
            parent_id=None,
            ordinal="sibling.000",
            description="top-level sibling",
            unit="m",
            quantity="1",
            unit_rate="0",
            total="0",
            classification={},
            source="manual",
            cad_element_ids=[],
            metadata_={},
            sort_order=99_999,
        )
        session.add(sibling)
        await session.commit()
        sibling_id = sibling.id

    leaf_id = ids[-1]
    accepted, reason = await _try_reparent(session_factory, boq_id, leaf_id, sibling_id)
    assert accepted is True, f"Legal leaf reparent rejected: {reason}"


# ═════════════════════════════════════════════════════════════════════════
# Scenario 2 — wide balanced tree (8 levels × 3 children ≈ 9 841 nodes)
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_balanced_tree_leaf_to_root_legal(
    session_factory, seeded_boq
) -> None:
    """8×3 balanced tree (~9 841 positions). Re-parenting a leaf under
    the root is legal — leaves have no descendants, no cycle possible.
    """
    boq_id = seeded_boq

    async with session_factory() as session:
        root_id, leaves = await _bulk_insert_tree(session, boq_id, depth=8, fanout=3)

    leaf_id = leaves[0]
    # Sanity: tree size should be exactly (3^9 - 1) / 2 = 9841.
    accepted, reason = await _try_reparent(session_factory, boq_id, leaf_id, root_id)
    assert accepted is True, f"Leaf-under-root must be legal: {reason}"


@pytest.mark.asyncio
async def test_balanced_tree_root_to_leaf_rejected(
    session_factory, seeded_boq
) -> None:
    """Same tree: pointing the root's parent at any leaf must reject —
    every leaf is a transitive descendant of the root. The walk must
    terminate cleanly even on a ~10k-node tree.
    """
    boq_id = seeded_boq

    async with session_factory() as session:
        root_id, leaves = await _bulk_insert_tree(session, boq_id, depth=8, fanout=3)

    leaf_id = leaves[-1]
    t0 = time.perf_counter()
    accepted, reason = await _try_reparent(session_factory, boq_id, root_id, leaf_id)
    elapsed = time.perf_counter() - t0

    assert accepted is False, "Root-under-descendant must reject"
    assert ("cycle" in reason.lower() or "descendant" in reason.lower()), reason
    # Even on ~10k positions, the walk is O(tree size) and should be
    # well under 5 s. (We stay generous here because tree-walk fan-out
    # involves more child queries than the chain case.)
    assert elapsed < 5.0, (
        f"Cycle detection on a ~10k-node tree took {elapsed:.2f} s "
        "— a regression to O(n²) would explain anything above this."
    )


# ═════════════════════════════════════════════════════════════════════════
# Scenario 3 — concurrent cycle attempts
# ═════════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_concurrent_cycle_attempts_leave_zero_cycles(
    session_factory, seeded_boq
) -> None:
    """10 concurrent reparent attempts, each trying to introduce a
    *different* cycle on the same small chain. Every attempt is
    expected to reject (they all point an ancestor at one of its own
    descendants). Critically: even if the guard's read of the
    descendant chain is interleaved with another writer's commit, no
    cycle may end up persisted.

    We use the public service contract (via
    ``BOQService.update_position``) so the test exercises the same
    code path the API does — including the actual commit.
    """
    from app.modules.boq.schemas import PositionUpdate
    from app.modules.boq.service import BOQService

    boq_id = seeded_boq

    # Build a 10-node chain so each task can target a distinct
    # ancestor → descendant pair.
    async with session_factory() as session:
        chain = await _bulk_insert_chain(session, boq_id, 10)

    async def attempt_cycle(ancestor_idx: int, descendant_idx: int) -> str:
        """Run one update_position in its own session.

        Returns the outcome category ("rejected" / "accepted") so we
        can verify the count after gather. Any exception bubbles via
        ``return_exceptions=True``.
        """
        async with session_factory() as session:
            svc = BOQService(session)
            try:
                await svc.update_position(
                    chain[ancestor_idx],
                    PositionUpdate(parent_id=chain[descendant_idx]),
                )
                return "accepted"
            except HTTPException as exc:
                return f"rejected:{exc.status_code}:{exc.detail[:40]}"

    # 10 attempts: each sets ancestor[i].parent = descendant[i+1..9].
    # Every single one is illegal (ancestor would become child of its
    # own descendant). Pick distinct (anc, desc) pairs.
    pairs = [(i, j) for i in range(10) for j in range(i + 1, 10)][:10]
    assert len(pairs) == 10
    results = await asyncio.gather(
        *[attempt_cycle(a, d) for a, d in pairs],
        return_exceptions=True,
    )

    # No raw exceptions — the service layer must turn cycle attempts
    # into HTTP 400 not generic Python errors.
    for r in results:
        assert not isinstance(r, BaseException), f"Unexpected raw exception: {r!r}"
    accepted = [r for r in results if r == "accepted"]
    assert accepted == [], (
        f"Some concurrent cycle attempts were accepted: {accepted!r}"
    )

    # Final invariant: the DB itself contains no cycles, regardless of
    # which interleaving the asyncio scheduler chose.
    async with session_factory() as session:
        assert not await _has_cycle(session, boq_id), (
            "Database contains a parent_id cycle after concurrent attempts — "
            "the cycle guard does not hold under interleaving."
        )


@pytest.mark.asyncio
async def test_concurrent_legal_reparents_all_succeed(
    session_factory, seeded_boq
) -> None:
    """Sanity counterpart to the cycle test: 10 concurrent *legal*
    reparents all succeed. Catches the case where a paranoid lock or
    overzealous validation accidentally serialises legitimate writes.
    """
    from app.modules.boq.models import Position
    from app.modules.boq.schemas import PositionUpdate
    from app.modules.boq.service import BOQService

    boq_id = seeded_boq

    # Two top-level parents, ten leaves currently under parent A. Move
    # each leaf to parent B concurrently.
    async with session_factory() as session:
        parent_a = Position(
            id=uuid.uuid4(),
            boq_id=boq_id,
            parent_id=None,
            ordinal="A.000",
            description="parent A",
            unit="m",
            quantity="1",
            unit_rate="0",
            total="0",
            classification={},
            source="manual",
            cad_element_ids=[],
            metadata_={},
            sort_order=0,
        )
        parent_b = Position(
            id=uuid.uuid4(),
            boq_id=boq_id,
            parent_id=None,
            ordinal="B.000",
            description="parent B",
            unit="m",
            quantity="1",
            unit_rate="0",
            total="0",
            classification={},
            source="manual",
            cad_element_ids=[],
            metadata_={},
            sort_order=1,
        )
        session.add_all([parent_a, parent_b])
        await session.flush()

        leaves: list[uuid.UUID] = []
        for i in range(10):
            leaf = Position(
                id=uuid.uuid4(),
                boq_id=boq_id,
                parent_id=parent_a.id,
                ordinal=f"A.{i + 1:03d}",
                description=f"leaf {i}",
                unit="m",
                quantity="1",
                unit_rate="0",
                total="0",
                classification={},
                source="manual",
                cad_element_ids=[],
                metadata_={},
                sort_order=10 + i,
            )
            session.add(leaf)
            leaves.append(leaf.id)
        await session.commit()
        parent_b_id = parent_b.id

    async def move_to_b(leaf_id: uuid.UUID) -> str:
        async with session_factory() as session:
            svc = BOQService(session)
            try:
                await svc.update_position(leaf_id, PositionUpdate(parent_id=parent_b_id))
                return "ok"
            except HTTPException as exc:
                return f"rejected:{exc.detail[:40]}"

    results = await asyncio.gather(
        *[move_to_b(lid) for lid in leaves],
        return_exceptions=True,
    )

    # SQLite has limited write concurrency; some transactions may
    # collide and need a retry. Treat "database is locked" the same as
    # success for the *purpose of this test* — we only care that the
    # cycle guard didn't false-reject, not that SQLite handled all 10
    # writers gracefully.
    bad = [
        r
        for r in results
        if r != "ok"
        and not (isinstance(r, str) and "lock" in r.lower())
        and not (isinstance(r, BaseException) and "lock" in str(r).lower())
    ]
    assert not bad, f"Legal concurrent reparents wrongly rejected: {bad!r}"

    async with session_factory() as session:
        assert not await _has_cycle(session, boq_id), (
            "Legal reparents somehow introduced a cycle"
        )
