"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Regression tests for the backup restore data-loss footgun.

Export is scoped to the requesting user's own project graph, but restore in
``replace`` mode used to run an unconditional ``DELETE FROM <table>`` over
every backup table. The result: a single user restoring their own per-user
backup wiped every other user's rows across the whole instance, then
re-inserted only their own. ``build_scope_clause`` now scopes both sides to
the same ownership graph, so a replace-restore can only ever clear the
requesting user's data.

These tests run the EXACT delete loop the router uses (reverse-order, scoped
delete per table) against a transaction-isolated PostgreSQL session with two
tenants, and assert the other tenant's rows survive untouched.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from app.modules.backup.service import build_scope_clause, get_backup_tables
from tests._pg import transactional_session

TENANT_A = uuid.uuid4()
TENANT_B = uuid.uuid4()
PROJECT_A = uuid.uuid4()
PROJECT_B = uuid.uuid4()


@pytest_asyncio.fixture
async def session():
    """Two tenants, each with a project, a BOQ, and BOQ positions."""
    async with transactional_session() as s:
        from app.modules.boq.models import BOQ, Position
        from app.modules.projects.models import Project
        from app.modules.users.models import User

        for uid, email in [(TENANT_A, "backup-a@test.io"), (TENANT_B, "backup-b@test.io")]:
            s.add(User(id=uid, email=email, hashed_password="x", full_name=email))
        await s.flush()
        for pid, oid in [(PROJECT_A, TENANT_A), (PROJECT_B, TENANT_B)]:
            s.add(Project(id=pid, name=str(pid), owner_id=oid, currency="EUR"))
        await s.flush()
        for pid, tag in [(PROJECT_A, "A"), (PROJECT_B, "B")]:
            boq = BOQ(project_id=pid, name=f"BOQ-{tag}")
            s.add(boq)
            await s.flush()
            for i in range(3):
                s.add(
                    Position(
                        boq_id=boq.id,
                        ordinal=f"{tag}.{i:03d}",
                        description=f"pos {tag} {i}",
                        unit="m3",
                    )
                )
        await s.flush()
        yield s


async def _count(session, model_cls, clause=None) -> int:
    stmt = select(func.count()).select_from(model_cls)
    if clause is not None:
        stmt = stmt.where(clause)
    return (await session.execute(stmt)).scalar_one()


@pytest.mark.asyncio
async def test_export_scope_is_per_user(session):
    """The scope clause selects only the requesting user's owned rows."""
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project

    tables = get_backup_tables()
    by_key = {k: cls for k, _t, cls in tables}

    proj_a = build_scope_clause(by_key, "projects", str(TENANT_A))
    boqs_a = build_scope_clause(by_key, "boqs", str(TENANT_A))
    pos_a = build_scope_clause(by_key, "positions", str(TENANT_A))

    # User A sees exactly their own project, BOQ, and 3 positions...
    assert await _count(session, Project, proj_a) == 1
    assert await _count(session, BOQ, boqs_a) == 1
    assert await _count(session, Position, pos_a) == 3
    # ...even though the table holds both tenants' data.
    assert await _count(session, Project) == 2
    assert await _count(session, Position) == 6


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_replace_restore_delete_leaves_other_users_data(session):
    """The reverse-order scoped delete loop (what restore replace mode runs)
    removes only the requesting user's rows; the other tenant is untouched.
    """
    from app.modules.boq.models import BOQ, Position
    from app.modules.projects.models import Project

    tables = get_backup_tables()
    by_key = {k: cls for k, _t, cls in tables}

    # Replicate the router's replace-mode clear: children before parents.
    for _backup_key, _table_name, model_cls in reversed(tables):
        scope = build_scope_clause(by_key, _backup_key, str(TENANT_A))
        if scope is None:
            continue
        await session.execute(delete(model_cls).where(scope))
    await session.flush()

    # Tenant A is gone...
    assert await _count(session, Project, Project.owner_id == TENANT_A) == 0
    assert await _count(session, BOQ, BOQ.project_id == PROJECT_A) == 0
    assert await _count(session, Position, Position.boq_id.in_(select(BOQ.id).where(BOQ.project_id == PROJECT_A))) == 0

    # ...but tenant B survives completely.
    assert await _count(session, Project, Project.owner_id == TENANT_B) == 1
    assert await _count(session, BOQ, BOQ.project_id == PROJECT_B) == 1
    assert await _count(session, Position, Position.boq_id.in_(select(BOQ.id).where(BOQ.project_id == PROJECT_B))) == 3
