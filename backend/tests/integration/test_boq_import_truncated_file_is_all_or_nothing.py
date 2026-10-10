# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A file cut off midway must not leave half a bill behind.

Every BOQ import route (``/import/gaeb/``, ``/import/excel/`` and
``/import/auto/`` in both its synchronous and background form) is fed a real
fixture truncated at roughly 60 % of its bytes, into a bill that already holds
positions from a clean import. The route must refuse the file and the bill
must hold exactly the rows it held before: the count is read straight from the
database, not from the API, so a write the response does not mention is still
seen.

Run:
    cd backend
    python -m pytest tests/integration/test_boq_import_truncated_file_is_all_or_nothing.py -v
"""

from __future__ import annotations

import asyncio
import io
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.modules.boq.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.teams.models  # noqa: F401
import app.modules.users.models  # noqa: F401

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
_X83 = (_FIXTURES / "gaeb" / "oce_conformance_x83.x83").read_bytes()
_XPWE = (_FIXTURES / "xpwe" / "computo_small.xpwe").read_bytes()


def _truncated(content: bytes, fraction: float = 0.6) -> bytes:
    return content[: int(len(content) * fraction)]


def _xlsx_bytes() -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.append(["Pos", "Description", "Unit", "Quantity", "Unit Rate"])
    for i in range(1, 41):
        ws.append([f"01.{i:03d}", f"Concrete wall segment {i}", "m3", 10 + i, 120.5])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    fastapi_app = create_app()
    async with fastapi_app.router.lifespan_context(fastapi_app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield fastapi_app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    async with AsyncClient(transport=ASGITransport(app=app_instance), base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(scope="module")
async def auth_headers(http_client) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"atomic-{uuid.uuid4().hex[:8]}@import-atomic.io"
    password = f"Atomic{uuid.uuid4().hex[:6]}9"
    reg = await http_client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "Atomic"}
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(is_active=True, role="admin"))
        await s.commit()
    login = await http_client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def project_id(http_client, auth_headers) -> str:
    resp = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"Atomic {uuid.uuid4().hex[:6]}", "region": "DACH", "currency": "EUR"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


async def _seeded_boq(http_client, auth_headers, project_id: str) -> str:
    """A bill already holding the clean conformance X83."""
    resp = await http_client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project_id, "name": f"LV {uuid.uuid4().hex[:6]}"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    boq_id = resp.json()["id"]
    seed = await http_client.post(
        f"/api/v1/boq/boqs/{boq_id}/import/auto/",
        files={"file": ("seed.x83", _X83, "application/xml")},
        headers=auth_headers,
    )
    assert seed.status_code == 200, seed.text
    assert await _db_count(boq_id) > 0
    return boq_id


async def _db_count(boq_id: str) -> int:
    from sqlalchemy import func, select

    from app.database import async_session_factory
    from app.modules.boq.models import Position

    async with async_session_factory() as s:
        return int(
            (await s.execute(select(func.count(Position.id)).where(Position.boq_id == uuid.UUID(boq_id)))).scalar_one()
        )


_CASES = [
    pytest.param("import/gaeb/", "cut.x83", _truncated(_X83), id="gaeb-route-x83"),
    pytest.param("import/auto/", "cut.x83", _truncated(_X83), id="auto-x83"),
    pytest.param("import/auto/", "cut.xpwe", _truncated(_XPWE), id="auto-xpwe"),
    pytest.param("import/excel/", "cut.xlsx", None, id="excel-route-xlsx"),
    pytest.param("import/auto/", "cut.xlsx", None, id="auto-xlsx"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("route", "filename", "content"), _CASES)
async def test_truncated_file_leaves_bill_unchanged(
    http_client, auth_headers, project_id, route: str, filename: str, content: bytes | None
) -> None:
    if content is None:
        content = _truncated(_xlsx_bytes())
    boq_id = await _seeded_boq(http_client, auth_headers, project_id)
    before = await _db_count(boq_id)

    resp = await http_client.post(
        f"/api/v1/boq/boqs/{boq_id}/{route}",
        files={"file": (filename, content, "application/octet-stream")},
        headers=auth_headers,
    )

    assert resp.status_code in (400, 422), f"{route} accepted a truncated file: {resp.status_code} {resp.text[:300]}"
    assert await _db_count(boq_id) == before


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("filename", "content"),
    [
        pytest.param("cut.x83", _truncated(_X83), id="x83"),
        pytest.param("cut.xpwe", _truncated(_XPWE), id="xpwe"),
    ],
)
async def test_truncated_file_in_background_job_leaves_bill_unchanged(
    http_client, auth_headers, project_id, filename: str, content: bytes
) -> None:
    boq_id = await _seeded_boq(http_client, auth_headers, project_id)
    before = await _db_count(boq_id)

    resp = await http_client.post(
        f"/api/v1/boq/boqs/{boq_id}/import/auto/?background=true",
        files={"file": (filename, content, "application/octet-stream")},
        headers=auth_headers,
    )
    if resp.status_code != 202:
        # The dispatcher may refuse the file before it queues a job.
        assert resp.status_code in (400, 422), resp.text[:300]
    else:
        job_id = resp.json()["job_id"]
        status = None
        for _ in range(100):
            poll = await http_client.get(f"/api/v1/boq/boqs/{boq_id}/import/jobs/{job_id}/", headers=auth_headers)
            status = poll.json().get("status")
            if status not in ("pending", "running", "queued"):
                break
            await asyncio.sleep(0.1)
        assert status not in ("success", "succeeded"), poll.text[:300]

    assert await _db_count(boq_id) == before
