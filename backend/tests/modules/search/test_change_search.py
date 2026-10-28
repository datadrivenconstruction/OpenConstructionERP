# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for change-family unified search (PostgreSQL, py3.12).

Drives the new SQL-track branches in :func:`_sql_search_collection` directly:
change orders, MoC entries, and the combined variations surface (notice /
request / order). Also checks the per-project access fence so a query never
returns a change record from a project the caller cannot read.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from tests._pg import transactional_session

from app.core.vector_index import (
    COLLECTION_CHANGE_ORDERS,
    COLLECTION_MOC,
    COLLECTION_VARIATIONS,
)
from app.modules.changeorders.models import ChangeOrder
from app.modules.moc.models import MoCEntry
from app.modules.projects.models import Project  # noqa: F401 - register ORM
from app.modules.search.service import _sql_search_collection
from app.modules.users.models import User
from app.modules.variations.models import Notice, VariationOrder, VariationRequest


@pytest_asyncio.fixture
async def session() -> AsyncSession:
    async with transactional_session() as s:
        yield s


async def _project(session: AsyncSession) -> uuid.UUID:
    user = User(
        email=f"srch-{uuid.uuid4().hex[:8]}@example.com",
        hashed_password="x",
        full_name="Srch",
        role="admin",
    )
    session.add(user)
    await session.flush()
    proj = Project(name=f"Srch {uuid.uuid4().hex[:6]}", owner_id=user.id)
    session.add(proj)
    await session.flush()
    return proj.id


@pytest.mark.asyncio
async def test_change_order_is_searchable(session: AsyncSession) -> None:
    pid = await _project(session)
    co = ChangeOrder(project_id=pid, code="CO-S1", title="Reinforced concrete alpha widget", status="draft")
    session.add(co)
    await session.flush()

    hits = await _sql_search_collection(session, COLLECTION_CHANGE_ORDERS, "alpha widget", project_id=str(pid))
    assert [h.id for h in hits] == [str(co.id)]
    assert hits[0].collection == COLLECTION_CHANGE_ORDERS
    assert hits[0].payload.get("code") == "CO-S1"


@pytest.mark.asyncio
async def test_moc_entry_is_searchable(session: AsyncSession) -> None:
    pid = await _project(session)
    m = MoCEntry(project_id=pid, code="MOC-S1", title="Beta cladding swap", risk_level="high")
    session.add(m)
    await session.flush()

    hits = await _sql_search_collection(session, COLLECTION_MOC, "cladding", project_id=str(pid))
    assert [h.id for h in hits] == [str(m.id)]
    assert hits[0].payload.get("risk_level") == "high"


@pytest.mark.asyncio
async def test_variations_surface_spans_three_entities(session: AsyncSession) -> None:
    pid = await _project(session)
    notice = Notice(project_id=pid, code="NOT-S1", title="Gamma early warning sprocket")
    vr = VariationRequest(project_id=pid, code="VR-S1", title="Delta scope addition")
    vo = VariationOrder(project_id=pid, code="VO-S1", title="Epsilon final order")
    session.add_all([notice, vr, vo])
    await session.flush()

    notice_hits = await _sql_search_collection(session, COLLECTION_VARIATIONS, "sprocket", project_id=str(pid))
    assert [h.id for h in notice_hits] == [str(notice.id)]
    assert notice_hits[0].payload.get("kind") == "notice"

    vr_hits = await _sql_search_collection(session, COLLECTION_VARIATIONS, "scope addition", project_id=str(pid))
    assert [h.id for h in vr_hits] == [str(vr.id)]
    assert vr_hits[0].payload.get("kind") == "request"

    vo_hits = await _sql_search_collection(session, COLLECTION_VARIATIONS, "final order", project_id=str(pid))
    assert [h.id for h in vo_hits] == [str(vo.id)]
    assert vo_hits[0].payload.get("kind") == "order"


@pytest.mark.asyncio
async def test_search_is_fenced_to_the_project(session: AsyncSession) -> None:
    pid = await _project(session)
    other_pid = await _project(session)
    co = ChangeOrder(project_id=pid, code="CO-S2", title="Zeta isolated widget", status="draft")
    session.add(co)
    await session.flush()

    # Pinned to a different project -> not visible.
    assert await _sql_search_collection(session, COLLECTION_CHANGE_ORDERS, "isolated", project_id=str(other_pid)) == []

    # Cross-project with an empty accessible set -> impossible predicate.
    assert await _sql_search_collection(session, COLLECTION_CHANGE_ORDERS, "isolated", allowed_project_ids=set()) == []

    # Cross-project including the owning project -> visible.
    hits = await _sql_search_collection(session, COLLECTION_CHANGE_ORDERS, "isolated", allowed_project_ids={pid})
    assert [h.id for h in hits] == [str(co.id)]
