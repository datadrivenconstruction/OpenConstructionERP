# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for ``_detect_language_mismatch`` (#229).

The helper compares the project region's language with the bound CWICR
catalogue's language so the UI can surface a "wrong catalogue" warning.
This file isolates the helper from the HTTP layer - the integration
test in ``tests/integration/test_match_catalog_binding.py`` covers the
full /vector/v3-status endpoint round trip.

All tests use a transaction-isolated PostgreSQL session from
``tests._pg.transactional_session`` (rolled back on teardown) so they run
fast and never touch the production database.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.costs.router import _detect_language_mismatch
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    """Transaction-isolated PostgreSQL session (rolled back on teardown)."""
    async with transactional_session() as s:
        yield s


async def _make_project(
    s: AsyncSession,
    *,
    region: str,
) -> uuid.UUID:
    from app.modules.projects.models import Project
    from app.modules.users.models import User

    user = User(
        id=uuid.uuid4(),
        email=f"lm-{uuid.uuid4().hex[:6]}@test.io",
        hashed_password="x" * 60,
        full_name="Lang Mismatch Test",
        role="estimator",
        locale="en",
        is_active=True,
        metadata_={},
    )
    s.add(user)
    await s.flush()

    pid = uuid.uuid4()
    s.add(
        Project(
            id=pid,
            name="t",
            region=region,
            status="active",
            owner_id=user.id,
        )
    )
    await s.commit()
    return pid


async def _bind(
    s: AsyncSession,
    project_id: uuid.UUID,
    catalogue_id: str | None,
) -> None:
    from app.modules.projects.models import MatchProjectSettings

    row = MatchProjectSettings(
        project_id=project_id,
        cost_database_id=catalogue_id,
    )
    s.add(row)
    await s.commit()


@pytest.mark.asyncio
async def test_unknown_when_project_missing(session: AsyncSession) -> None:
    out = await _detect_language_mismatch(session, uuid.uuid4())
    assert out["status"] == "unknown"


@pytest.mark.asyncio
async def test_unbound_when_no_catalogue(session: AsyncSession) -> None:
    pid = await _make_project(session, region="USA_NEWYORK")
    # Settings row absent => unbound
    out = await _detect_language_mismatch(session, pid)
    assert out["status"] == "unbound"
    assert out["project_region"] == "USA_NEWYORK"
    assert out["project_language"] == "en"


@pytest.mark.asyncio
async def test_ok_when_languages_match(session: AsyncSession) -> None:
    pid = await _make_project(session, region="USA_NEWYORK")
    await _bind(session, pid, "USA_USD")  # also "en"
    out = await _detect_language_mismatch(session, pid)
    assert out["status"] == "ok"
    assert out["project_language"] == "en"
    assert out["bound_language"] == "en"


@pytest.mark.asyncio
async def test_mismatch_us_project_with_russian_catalogue(session: AsyncSession) -> None:
    """The motivating bug: US project auto-bound to RU_MOSCOW because the
    Russian catalogue had the most rows globally (auto_bind_dominant_catalogue
    pre-2.9.34 picked by row count). The /match-elements UI must now flag
    this as a mismatch so the user can re-bind."""
    pid = await _make_project(session, region="USA_NEWYORK")
    await _bind(session, pid, "RU_MOSCOW")
    out = await _detect_language_mismatch(session, pid)
    assert out["status"] == "mismatch"
    assert out["project_language"] == "en"
    assert out["bound_language"] == "ru"
    assert out["project_region"] == "USA_NEWYORK"
    assert out["bound_catalogue"] == "RU_MOSCOW"


@pytest.mark.asyncio
async def test_mismatch_de_project_with_french_catalogue(session: AsyncSession) -> None:
    pid = await _make_project(session, region="DE_BERLIN")
    await _bind(session, pid, "FR_PARIS")
    out = await _detect_language_mismatch(session, pid)
    assert out["status"] == "mismatch"
    assert out["project_language"] == "de"
    assert out["bound_language"] == "fr"
