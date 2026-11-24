"""Sidebar badges cost one SQL statement and count only open items of the project."""

import uuid

import pytest
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.sidebar_badges_router import sidebar_badges
from app.modules.rfi.models import RFI
from app.modules.safety.models import SafetyIncident, SafetyObservation
from app.modules.tasks.models import Task

_TABLES = [Task.__table__, RFI.__table__, SafetyIncident.__table__, SafetyObservation.__table__]


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Task.metadata.create_all(c, tables=_TABLES))
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as s:
        yield s
    await engine.dispose()


async def _insert(session: AsyncSession, table, **values) -> None:
    await session.execute(table.insert().values(id=uuid.uuid4(), **values))


@pytest.mark.asyncio
async def test_badges_issue_one_statement_and_count_open_items(session: AsyncSession) -> None:
    project = uuid.uuid4()
    other = uuid.uuid4()
    statements: list[str] = []

    def _record(conn, cursor, statement, *args) -> None:  # noqa: ANN001
        statements.append(statement)

    for status in ("draft", "open", "completed"):
        await _insert(session, Task.__table__, project_id=project, task_type="task", title="t", status=status)
    await _insert(session, Task.__table__, project_id=other, task_type="task", title="t", status="open")
    for status in ("draft", "open", "closed"):
        await _insert(
            session,
            RFI.__table__,
            project_id=project,
            rfi_number=f"RFI-{status}",
            subject="s",
            question="q",
            raised_by=uuid.uuid4(),
            status=status,
        )
    await session.flush()

    sync_engine = session.bind.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _record)
    try:
        result = await sidebar_badges(session=session, project_id=project, user_id=None)
    finally:
        event.remove(sync_engine, "before_cursor_execute", _record)

    assert len(statements) == 1
    assert result.tasks_open == 2
    assert result.rfi_open == 2
    assert result.safety_open == 0
