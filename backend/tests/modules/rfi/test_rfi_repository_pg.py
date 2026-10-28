"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Wave 8 (Tests) - RFI repository SQL coverage (real PostgreSQL).

The in-memory stub repos the unit suites use cannot exercise the actual SQL in
``RFIRepository`` - the ``next_rfi_number`` MAX(cast(...)) aggregate with its
``RFI-[0-9]+`` regexp guard, and the ILIKE free-text ``list_for_project``
search. Both have real correctness requirements that only PostgreSQL can prove:

* ``next_rfi_number`` must format ``RFI-NNN`` zero-padded to 3 digits, scope to
  one project, and skip non-canonical (legacy / externally-numbered) rows so a
  single odd row does not break numbering for the whole project (the cast would
  otherwise raise on PostgreSQL).
* ``list_for_project`` search must match across subject / question /
  official_response / rfi_number, be case-insensitive, and stay project-scoped.
* ``with_total=False`` must skip the COUNT and still return a coherent tuple.

DB-backed; runs in CI against the shared ``oe_test_unit`` database inside a
transaction rolled back on teardown (``tests._pg``).
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio

from app.modules.projects.models import Project
from app.modules.rfi.models import RFI
from app.modules.rfi.repository import RFIRepository
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    async with transactional_session() as s:
        yield s


async def _make_user(session) -> uuid.UUID:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user.id


async def _make_project(session, owner_id: uuid.UUID) -> uuid.UUID:
    project = Project(name="Repo test", owner_id=owner_id)
    session.add(project)
    await session.flush()
    await session.refresh(project)
    return project.id


async def _add_rfi(
    session,
    *,
    project_id: uuid.UUID,
    raised_by: uuid.UUID,
    number: str,
    subject: str = "Subject",
    question: str = "Question",
    status: str = "open",
    official_response: str | None = None,
) -> RFI:
    rfi = RFI(
        project_id=project_id,
        rfi_number=number,
        subject=subject,
        question=question,
        status=status,
        raised_by=raised_by,
        official_response=official_response,
    )
    session.add(rfi)
    await session.flush()
    return rfi


# ── next_rfi_number ──────────────────────────────────────────────────────


class TestNextRFINumber:
    @pytest.mark.asyncio
    async def test_first_number_is_rfi_001(self, db_session) -> None:
        owner = await _make_user(db_session)
        project_id = await _make_project(db_session, owner)
        repo = RFIRepository(db_session)
        assert await repo.next_rfi_number(project_id) == "RFI-001"

    @pytest.mark.asyncio
    async def test_increments_from_existing_max(self, db_session) -> None:
        owner = await _make_user(db_session)
        project_id = await _make_project(db_session, owner)
        await _add_rfi(db_session, project_id=project_id, raised_by=owner, number="RFI-007")
        repo = RFIRepository(db_session)
        assert await repo.next_rfi_number(project_id) == "RFI-008"

    @pytest.mark.asyncio
    async def test_padding_expands_past_three_digits(self, db_session) -> None:
        owner = await _make_user(db_session)
        project_id = await _make_project(db_session, owner)
        await _add_rfi(db_session, project_id=project_id, raised_by=owner, number="RFI-1500")
        repo = RFIRepository(db_session)
        # ``:03d`` is a *minimum* width - 1501 keeps all four digits.
        assert await repo.next_rfi_number(project_id) == "RFI-1501"

    @pytest.mark.asyncio
    async def test_ignores_non_canonical_legacy_row(self, db_session) -> None:
        """A legacy / externally-numbered row (not ``RFI-<digits>``) must be
        skipped by the regexp guard. Without it, the integer cast raises on
        PostgreSQL and every new RFI for the project would 500."""
        owner = await _make_user(db_session)
        project_id = await _make_project(db_session, owner)
        await _add_rfi(db_session, project_id=project_id, raised_by=owner, number="LEGACY-XYZ")
        await _add_rfi(db_session, project_id=project_id, raised_by=owner, number="RFI-003")
        repo = RFIRepository(db_session)
        # Max canonical is 003; the legacy row is invisible to the aggregate.
        assert await repo.next_rfi_number(project_id) == "RFI-004"

    @pytest.mark.asyncio
    async def test_is_scoped_per_project(self, db_session) -> None:
        owner = await _make_user(db_session)
        project_a = await _make_project(db_session, owner)
        project_b = await _make_project(db_session, owner)
        await _add_rfi(db_session, project_id=project_a, raised_by=owner, number="RFI-050")
        repo = RFIRepository(db_session)
        # Project B is independent - it starts fresh despite A being at 050.
        assert await repo.next_rfi_number(project_b) == "RFI-001"


# ── list_for_project search ──────────────────────────────────────────────


class TestListSearch:
    @pytest.mark.asyncio
    async def test_search_matches_subject_case_insensitive(self, db_session) -> None:
        owner = await _make_user(db_session)
        project_id = await _make_project(db_session, owner)
        await _add_rfi(db_session, project_id=project_id, raised_by=owner, number="RFI-001", subject="Foundation rebar")
        await _add_rfi(db_session, project_id=project_id, raised_by=owner, number="RFI-002", subject="Roof flashing")
        repo = RFIRepository(db_session)
        rows, total = await repo.list_for_project(project_id, search="REBAR")
        assert total == 1
        assert rows[0].rfi_number == "RFI-001"

    @pytest.mark.asyncio
    async def test_search_matches_official_response(self, db_session) -> None:
        owner = await _make_user(db_session)
        project_id = await _make_project(db_session, owner)
        await _add_rfi(
            db_session,
            project_id=project_id,
            raised_by=owner,
            number="RFI-001",
            subject="Generic",
            official_response="Use grade C35/45 concrete",
        )
        await _add_rfi(db_session, project_id=project_id, raised_by=owner, number="RFI-002", subject="Generic")
        repo = RFIRepository(db_session)
        rows, total = await repo.list_for_project(project_id, search="C35/45")
        assert total == 1
        assert rows[0].rfi_number == "RFI-001"

    @pytest.mark.asyncio
    async def test_search_matches_rfi_number(self, db_session) -> None:
        owner = await _make_user(db_session)
        project_id = await _make_project(db_session, owner)
        await _add_rfi(db_session, project_id=project_id, raised_by=owner, number="RFI-042")
        await _add_rfi(db_session, project_id=project_id, raised_by=owner, number="RFI-099")
        repo = RFIRepository(db_session)
        rows, total = await repo.list_for_project(project_id, search="042")
        assert total == 1
        assert rows[0].rfi_number == "RFI-042"

    @pytest.mark.asyncio
    async def test_search_is_project_scoped(self, db_session) -> None:
        owner = await _make_user(db_session)
        project_a = await _make_project(db_session, owner)
        project_b = await _make_project(db_session, owner)
        await _add_rfi(db_session, project_id=project_a, raised_by=owner, number="RFI-001", subject="Shared keyword")
        await _add_rfi(db_session, project_id=project_b, raised_by=owner, number="RFI-001", subject="Shared keyword")
        repo = RFIRepository(db_session)
        rows, total = await repo.list_for_project(project_a, search="Shared keyword")
        # Only project A's row, even though B has an identical subject.
        assert total == 1
        assert all(r.project_id == project_a for r in rows)

    @pytest.mark.asyncio
    async def test_status_filter_combines_with_project_scope(self, db_session) -> None:
        owner = await _make_user(db_session)
        project_id = await _make_project(db_session, owner)
        await _add_rfi(db_session, project_id=project_id, raised_by=owner, number="RFI-001", status="open")
        await _add_rfi(db_session, project_id=project_id, raised_by=owner, number="RFI-002", status="draft")
        repo = RFIRepository(db_session)
        rows, total = await repo.list_for_project(project_id, status="open")
        assert total == 1
        assert rows[0].status == "open"

    @pytest.mark.asyncio
    async def test_with_total_false_skips_count_but_returns_tuple(self, db_session) -> None:
        owner = await _make_user(db_session)
        project_id = await _make_project(db_session, owner)
        for n in range(3):
            await _add_rfi(db_session, project_id=project_id, raised_by=owner, number=f"RFI-{n + 1:03d}")
        repo = RFIRepository(db_session)
        rows, total = await repo.list_for_project(project_id, with_total=False, limit=2)
        # When the count is skipped, the returned total is the page length.
        assert len(rows) == 2
        assert total == len(rows)
