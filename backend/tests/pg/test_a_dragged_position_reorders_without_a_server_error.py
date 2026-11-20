"""PG: dragging a position in a bill with sections reorders it instead of failing with 500.

The grid collected every row id it rendered, so an expanded position sent its
resource rows (``<uuid>_res_0``) and its add-resource row along with the real
positions. The router parsed each id with ``uuid.UUID`` and the first synthetic
one raised, which surfaced as a 500. The grid now sends position ids only, and the
router refuses a malformed id with 422 rather than crashing.

Gated by ``OE_TEST_DB=pg`` (see conftest).
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select

from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.boq.models import BOQ, Position
from app.modules.boq.router import router
from app.modules.projects.models import Project
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _bill(session) -> tuple[User, BOQ, dict[str, uuid.UUID]]:
    owner = User(email=f"reorder-{uuid.uuid4().hex[:8]}@example.test", hashed_password="x", full_name="Reorder")
    session.add(owner)
    await session.flush()
    project = Project(name="Reorder", owner_id=owner.id, currency="EUR")
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name="Sections and lines")
    session.add(boq)
    await session.flush()
    s1 = Position(boq_id=boq.id, ordinal="01", description="Earthworks", unit="", sort_order=0)
    s2 = Position(boq_id=boq.id, ordinal="02", description="Concrete", unit="", sort_order=3)
    session.add_all([s1, s2])
    await session.flush()
    rows = {"s1": s1.id, "s2": s2.id}
    for key, parent, ordinal, order in (
        ("a", s1, "01.001", 1),
        ("b", s1, "01.002", 2),
        ("c", s2, "02.001", 4),
    ):
        pos = Position(
            boq_id=boq.id,
            parent_id=parent.id,
            ordinal=ordinal,
            description=f"Line {ordinal}",
            unit="m3",
            quantity="1",
            unit_rate="10",
            total="10",
            sort_order=order,
        )
        session.add(pos)
        await session.flush()
        rows[key] = pos.id
    return owner, boq, rows


def _app(session, owner: User) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1/boq")

    async def _session():
        yield session

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(owner.id)
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": str(owner.id),
        "role": "admin",
        "permissions": [],
    }
    return app


async def _order(session, ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    rows = (await session.execute(select(Position.id, Position.sort_order).where(Position.id.in_(ids)))).all()
    return {r[0]: r[1] for r in rows}


async def _post(session, owner: User, boq: BOQ, ids: list[str]) -> httpx.Response:
    transport = httpx.ASGITransport(app=_app(session, owner))
    async with httpx.AsyncClient(transport=transport, base_url="http://reorder-test") as c:
        return await c.post(f"/api/v1/boq/boqs/{boq.id}/positions/reorder/", json={"position_ids": ids})


async def test_a_position_drag_inside_a_section_reorders_the_lines(pg_session) -> None:
    owner, boq, r = await _bill(pg_session)

    resp = await _post(pg_session, owner, boq, [str(r["b"]), str(r["a"]), str(r["c"])])

    assert resp.status_code == 200, resp.text
    order = await _order(pg_session, [r["a"], r["b"], r["c"]])
    assert order[r["b"]] < order[r["a"]] < order[r["c"]]


async def test_a_section_drag_sends_sections_and_children_together(pg_session) -> None:
    owner, boq, r = await _bill(pg_session)

    ids = [r["s2"], r["c"], r["s1"], r["a"], r["b"]]
    resp = await _post(pg_session, owner, boq, [str(i) for i in ids])

    assert resp.status_code == 200, resp.text
    order = await _order(pg_session, ids)
    assert [order[i] for i in ids] == [0, 1, 2, 3, 4]


async def test_a_synthetic_grid_row_id_is_refused_not_a_server_error(pg_session) -> None:
    """What the grid sent with an expanded position: its resource and add rows."""
    owner, boq, r = await _bill(pg_session)
    before = await _order(pg_session, [r["a"], r["b"], r["c"]])

    ids = [str(r["b"]), f"{r['b']}_res_0", f"{r['b']}_add_res", str(r["a"]), str(r["c"])]
    resp = await _post(pg_session, owner, boq, ids)

    assert resp.status_code == 422, resp.text
    assert await _order(pg_session, [r["a"], r["b"], r["c"]]) == before
