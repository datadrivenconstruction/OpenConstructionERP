# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A locked bill refuses the writers that live in the router, imports included.

CO2 enrichment, the manual CO2 assignment, custom column definitions and the
bill's named variables wrote straight from the router, past the lock guard the
service writers take, so a locked (issued) bill still changed. The importers
did reach the guard, but only per row, where every refusal was collected as a
row error: the user saw "Import failed at row 2" or a 200 with nothing
imported, never the lock. All of them now answer the lock's own 409 before
anything is written, and each case checks the bill is exactly as it was.

Run:
    cd backend
    python -m pytest tests/integration/test_locked_bill_refuses_side_writes.py -v
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import app.modules.boq.models  # noqa: F401
import app.modules.costs.models  # noqa: F401
import app.modules.projects.models  # noqa: F401
import app.modules.users.models  # noqa: F401

_CSV = b"Pos,Description,Unit,Quantity,Unit Rate\n9001,Imported slab,m3,5,120\n"
_GAEB = b'<?xml version="1.0" encoding="UTF-8"?><GAEB xmlns="http://www.gaeb.de/GAEB_DA_XML/DA83/3.3"></GAEB>'


@pytest_asyncio.fixture(scope="module")
async def http_client():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    fastapi_app = create_app()
    async with fastapi_app.router.lifespan_context(fastapi_app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with AsyncClient(transport=ASGITransport(app=fastapi_app), base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def headers(http_client):
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"lock-{uuid.uuid4().hex[:8]}@sidewrites.io"
    password = f"LockSide{uuid.uuid4().hex[:6]}9"
    reg = await http_client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Lock Side Writes"},
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()
    login = await http_client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _bill(client: AsyncClient, headers: dict[str, str], *, lock: bool) -> tuple[str, str]:
    """A bill with one concrete line and one custom column, locked if asked."""
    project = await client.post(
        "/api/v1/projects/",
        json={"name": f"Lock {uuid.uuid4().hex[:6]}", "region": "DACH", "currency": "EUR"},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    boq = await client.post(
        "/api/v1/boq/boqs/",
        json={"project_id": project.json()["id"], "name": "Issued bill"},
        headers=headers,
    )
    assert boq.status_code == 201, boq.text
    boq_id = boq.json()["id"]
    pos = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/positions/",
        json={
            "boq_id": boq_id,
            "ordinal": "0010",
            "description": "Reinforced concrete wall C30/37",
            "unit": "m3",
            "quantity": 10.0,
            "unit_rate": 185.0,
        },
        headers=headers,
    )
    assert pos.status_code == 201, pos.text
    col = await client.post(
        f"/api/v1/boq/boqs/{boq_id}/columns/",
        json={"name": "supplier", "column_type": "text"},
        headers=headers,
    )
    assert col.status_code == 201, col.text
    if lock:
        locked = await client.post(f"/api/v1/boq/boqs/{boq_id}/lock/", headers=headers)
        assert locked.status_code == 200, locked.text
    return boq_id, pos.json()["id"]


async def _state(client: AsyncClient, headers: dict[str, str], boq_id: str) -> dict[str, Any]:
    """What a write could change: the bill's metadata and every line on it."""
    resp = await client.get(f"/api/v1/boq/boqs/{boq_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    lines = sorted(
        (p["ordinal"], p["description"], p["quantity"], p["unit_rate"], p.get("metadata")) for p in body["positions"]
    )
    return {"metadata": body.get("metadata"), "lines": [repr(line) for line in lines]}


def _epd_id() -> str:
    from app.modules.boq.epd_materials import EPD_INDEX

    return next(iter(EPD_INDEX))


_WRITES: list[tuple[str, str, str, dict[str, Any]]] = [
    ("enrich-co2", "POST", "/boqs/{boq}/enrich-co2/", {"json": {}}),
    ("assign-co2", "PUT", "/positions/{pos}/co2/", {"json": "epd"}),
    ("add-column", "POST", "/boqs/{boq}/columns/", {"json": {"name": "trade", "column_type": "text"}}),
    ("delete-column", "DELETE", "/boqs/{boq}/columns/supplier", {}),
    ("variables", "PUT", "/boqs/{boq}/variables/", {"json": [{"name": "GFA", "type": "number", "value": 1200}]}),
    ("import-excel", "POST", "/boqs/{boq}/import/excel/", {"files": ("bill.csv", _CSV, "text/csv")}),
    ("import-auto", "POST", "/boqs/{boq}/import/auto/", {"files": ("bill.csv", _CSV, "text/csv")}),
    ("import-smart", "POST", "/boqs/{boq}/import/smart/", {"files": ("bill.csv", _CSV, "text/csv")}),
    ("import-gaeb", "POST", "/boqs/{boq}/import/gaeb/", {"files": ("bill.x83", _GAEB, "application/xml")}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("case", "method", "path", "body"), _WRITES, ids=[w[0] for w in _WRITES])
async def test_locked_bill_refuses_the_write_and_stays_as_issued(http_client, headers, case, method, path, body):
    boq_id, pos_id = await _bill(http_client, headers, lock=True)
    before = await _state(http_client, headers, boq_id)

    kwargs: dict[str, Any] = {}
    if body.get("json") == "epd":
        kwargs["json"] = {"epd_id": _epd_id()}
    elif "json" in body:
        kwargs["json"] = body["json"]
    if "files" in body:
        kwargs["files"] = {"file": body["files"]}
    url = "/api/v1/boq" + path.format(boq=boq_id, pos=pos_id)
    resp = await http_client.request(method, url, headers=headers, **kwargs)

    assert resp.status_code == 409, f"{case} on a locked bill answered {resp.status_code}: {resp.text}"
    # The lock's own message, not a row error that merely quotes it.
    assert not str(resp.json().get("detail", "")).startswith("Import failed")
    assert await _state(http_client, headers, boq_id) == before


@pytest.mark.asyncio
async def test_open_bill_still_takes_the_same_writes(http_client, headers):
    """The guard refuses the lock, not the write: an open bill changes."""
    boq_id, pos_id = await _bill(http_client, headers, lock=False)
    before = await _state(http_client, headers, boq_id)

    co2 = await http_client.put(f"/api/v1/boq/positions/{pos_id}/co2/", json={"epd_id": _epd_id()}, headers=headers)
    assert co2.status_code == 200, co2.text
    variables = await http_client.put(
        f"/api/v1/boq/boqs/{boq_id}/variables/",
        json=[{"name": "GFA", "type": "number", "value": 1200}],
        headers=headers,
    )
    assert variables.status_code == 200, variables.text
    imported = await http_client.post(
        f"/api/v1/boq/boqs/{boq_id}/import/excel/",
        files={"file": ("bill.csv", _CSV, "text/csv")},
        headers=headers,
    )
    assert imported.status_code == 200, imported.text

    after = await _state(http_client, headers, boq_id)
    assert after["metadata"] != before["metadata"]
    assert len(after["lines"]) == len(before["lines"]) + 1
