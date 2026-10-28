# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠What the drawing-sheet register promises on the way out: an order and a count.

Two properties, neither of which the read path actually had.

Order. ``SheetRepository.list_for_project`` ordered on ``page_number`` alone. A
page number is not unique: a set uploaded again starts at page 1 again, and one
import can register two revisions in a single instant. What settled those ties
was the query plan, and on this schema that means an index
``app.core.pg_optimizations`` attaches to ``create_all`` and an Alembic-built
database never receives, so the register's order was a property of how the
database had been built rather than of the rows in it. The route pages with
``offset`` and ``limit``, and two pages that settle one tie differently show a
row twice and skip the one it displaced. The test below pins a total order: the
sequence has to be a function of the rows, not of where they sit.

Count. The list route caps ``limit`` at 500 and the register asks for exactly
500, so a project holding more sheets than that was cut off with no way to
tell. The count is not expensive to produce - ``list_for_project`` already
computes it and the handler threw it away - it just never left the server. It
now travels as ``X-Total-Count``, the header the EAC and BCF list routes
already use, and CORS exposes it so a caller on another origin can read it.

Rows are seeded directly rather than split out of a PDF, so nothing here needs
reportlab and no test in this file skips.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.documents.models import Sheet
from app.modules.documents.repository import SheetRepository
from tests._pg import transactional_session

#: Mounted by the module loader from the package directory name.
SHEETS_BASE = "/api/v1/documents/sheets"

#: Granted to the caller in the route tests so RBAC is never what answers.
DOCUMENT_PERMS = ["documents.read", "documents.create", "documents.update", "documents.delete"]

#: The origin the app allows out of the box (``allowed_origins`` default).
BROWSER_ORIGIN = "http://localhost:5173"


# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Per-test PostgreSQL session inside an outer transaction.

    Order is the subject here, so the store has to be the real one: the ordering
    the repository leaves unspecified is decided by PostgreSQL, and only
    PostgreSQL can show what it decides.
    """
    async with transactional_session() as sess:
        yield sess


@pytest_asyncio.fixture(scope="module")
async def sheets_app() -> AsyncIterator[Any]:
    """Boot the real application once for this module, schema included.

    A discarded header is invisible below the route: the repository hands back
    the count either way. Only a request through the app can say whether it
    reaches the client.
    """
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Session on the same database the application under test is bound to."""
    from app.database import async_session_factory

    async with async_session_factory() as sess:
        yield sess


# ── Helpers ───────────────────────────────────────────────────────────────


async def _seed_project(session: AsyncSession) -> uuid.UUID:
    """Insert a user and a project so the sheet rows have their foreign keys."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"sheets-read-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Sheets Read Path Tester",
        role="manager",
        is_active=True,
    )
    session.add(user)
    await session.flush()
    project = Project(name=f"Sheets Read Path {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(project)
    await session.flush()
    return project.id


async def _seed_project_for_user(session: AsyncSession) -> tuple[uuid.UUID, uuid.UUID]:
    """Commit a user and a project the booted app can see, and return both ids."""
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        email=f"sheets-read-route-{uuid.uuid4().hex[:8]}@test.io",
        hashed_password="x",
        full_name="Sheets Read Path Route Tester",
        role="manager",
        is_active=True,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    project = Project(name=f"Sheets Read Path Route {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return user.id, project.id


def _sheet(
    project_id: uuid.UUID,
    *,
    sheet_id: uuid.UUID,
    page_number: int,
    sheet_number: str,
    created_at: datetime,
    revision: str | None = None,
    previous_version_id: uuid.UUID | None = None,
    is_current: bool = True,
) -> Sheet:
    """Build one sheet row with its id and creation instant pinned.

    Both are normally left to a default, and both are what the order under test
    falls back on, so every test here states them outright.
    """
    return Sheet(
        id=sheet_id,
        project_id=project_id,
        document_id="drawing-set",
        page_number=page_number,
        sheet_number=sheet_number,
        created_at=created_at,
        revision=revision,
        previous_version_id=previous_version_id,
        is_current=is_current,
    )


def _sheet_id(suffix: str) -> uuid.UUID:
    """A uuid whose text form sorts by ``suffix``.

    The column is a ``VARCHAR(36)``, so the database compares the printed form.
    Spelling the ids out keeps the right answer readable in the assertion.
    """
    return uuid.UUID(f"00000000-0000-4000-8000-0000000000{suffix}")


@asynccontextmanager
async def _as_user(app: Any, user_id: uuid.UUID) -> AsyncIterator[AsyncClient]:
    """Drive the app as ``user_id``, a manager holding every documents permission."""
    from app.dependencies import get_current_user_payload

    async def _payload() -> dict[str, Any]:
        return {"sub": str(user_id), "role": "manager", "permissions": list(DOCUMENT_PERMS)}

    app.dependency_overrides[get_current_user_payload] = _payload
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client
    finally:
        app.dependency_overrides.clear()


# ── Order: the register lists the same rows the same way every time ────────

#: What a register holding two revisions of one set reads like, top to bottom.
REGISTER_ORDER = [("A-101", "A"), ("A-101", "B"), ("A-102", "A"), ("A-102", "B")]


def _imported_register(project_id: uuid.UUID, *, id_prefix: str) -> list[Sheet]:
    """Two revisions of a two-page set, both registered by one import.

    Every row carries the same instant, which is what one transaction writes: a
    database-side default is the transaction's own timestamp for every row at
    once, and the Python-side clock this platform reads is coarse enough to
    return the same value for a whole batch. Page 1 therefore holds two rows
    that are equal on everything the register orders by, and the ids ascend with
    the revision so the tie has a right answer to hold the listing to.
    """
    stamp = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
    return [
        _sheet(
            project_id,
            sheet_id=_sheet_id(f"{id_prefix}1"),
            page_number=1,
            sheet_number="A-101",
            created_at=stamp,
            revision="A",
        ),
        _sheet(
            project_id,
            sheet_id=_sheet_id(f"{id_prefix}2"),
            page_number=2,
            sheet_number="A-102",
            created_at=stamp,
            revision="A",
        ),
        _sheet(
            project_id,
            sheet_id=_sheet_id(f"{id_prefix}3"),
            page_number=1,
            sheet_number="A-101",
            created_at=stamp,
            revision="B",
        ),
        _sheet(
            project_id,
            sheet_id=_sheet_id(f"{id_prefix}4"),
            page_number=2,
            sheet_number="A-102",
            created_at=stamp,
            revision="B",
        ),
    ]


async def test_register_order_does_not_depend_on_where_the_rows_sit(session: AsyncSession) -> None:
    """The same register, written in two orders, lists the same way both times.

    Two projects hold that register, identical in every column a reader can see
    and written in opposite orders. Ordering on the page number alone leaves the
    rest to the storage, so the second register comes back with its two page-1
    rows the other way round, which is the register showing the superseded
    revision as though it were the current one.

    It is also what makes a paged register drop rows: the route pages with
    ``offset`` and ``limit``, and two requests that resolve one tie differently
    put the same row on both pages and no row on the boundary between them.
    """
    repo = SheetRepository(session)

    forward = await _seed_project(session)
    session.add_all(_imported_register(forward, id_prefix="a"))
    await session.flush()

    backwards = await _seed_project(session)
    session.add_all(list(reversed(_imported_register(backwards, id_prefix="b"))))
    await session.flush()

    forward_items, forward_total = await repo.list_for_project(forward)
    backwards_items, _ = await repo.list_for_project(backwards)

    assert forward_total == 4
    assert [(s.sheet_number, s.revision) for s in forward_items] == REGISTER_ORDER
    assert [(s.sheet_number, s.revision) for s in backwards_items] == REGISTER_ORDER


# ── Count: what the page could not show ────────────────────────────────────


async def test_list_sheets_reports_the_match_count_a_capped_page_cannot_show(
    sheets_app: Any,
    db_session: AsyncSession,
) -> None:
    """A truncated page carries the number of matches behind it.

    The register asks for the maximum the route allows. Short of the count, a
    full page and a cut-off one look the same, and the register is the only
    thing that could tell the reader sheets are missing. The count is asserted
    in the body, where the register reads it, and in the header, which older
    scripted callers still read.
    """
    user_id, project_id = await _seed_project_for_user(db_session)
    stamp = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
    db_session.add_all(
        [
            _sheet(project_id, sheet_id=uuid.uuid4(), page_number=1, sheet_number="A-101", created_at=stamp),
            _sheet(project_id, sheet_id=uuid.uuid4(), page_number=2, sheet_number="A-102", created_at=stamp),
            _sheet(
                project_id,
                sheet_id=uuid.uuid4(),
                page_number=3,
                sheet_number="A-103",
                created_at=stamp,
                is_current=False,
            ),
        ]
    )
    await db_session.commit()

    async with _as_user(sheets_app, user_id) as client:
        page = await client.get(f"{SHEETS_BASE}/", params={"project_id": str(project_id), "limit": 2})
        filtered = await client.get(
            f"{SHEETS_BASE}/",
            params={"project_id": str(project_id), "limit": 1, "current_only": "true"},
        )

    assert page.status_code == 200
    assert len(page.json()["items"]) == 2
    assert page.json()["total"] == 3
    assert page.headers["X-Total-Count"] == "3"

    # The count answers for the filter the caller sent, not for the project.
    assert filtered.status_code == 200
    assert len(filtered.json()["items"]) == 1
    assert filtered.json()["total"] == 2
    assert filtered.headers["X-Total-Count"] == "2"


async def test_total_count_header_is_exposed_to_a_cross_origin_reader(
    sheets_app: Any,
    db_session: AsyncSession,
) -> None:
    """A header the browser hides from JavaScript is not a signal.

    The bundled frontend calls the API on its own origin, but a separately
    hosted one is exactly what ``ALLOWED_ORIGINS`` is for, and there a response
    header is unreadable unless CORS names it.
    """
    user_id, project_id = await _seed_project_for_user(db_session)

    async with _as_user(sheets_app, user_id) as client:
        resp = await client.get(
            f"{SHEETS_BASE}/",
            params={"project_id": str(project_id)},
            headers={"Origin": BROWSER_ORIGIN},
        )

    assert resp.status_code == 200
    exposed = [h.strip().lower() for h in resp.headers.get("access-control-expose-headers", "").split(",")]
    assert "x-total-count" in exposed
