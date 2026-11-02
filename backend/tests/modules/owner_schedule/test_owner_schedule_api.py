# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Owner schedule round trip through the API on PostgreSQL.

One story, in order: detect the owner's format, import it into a BOQ, price it in
the BOQ (with an own breakdown under one item), read the status and findings,
export the owner's file with exact totals, then apply an addendum selectively.
"""

from __future__ import annotations

import io
import json
import uuid
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from openpyxl import load_workbook
from sqlalchemy import select

from .conftest import agency_workbook

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@pytest_asyncio.fixture(scope="module")
async def client():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac


async def _user(client: AsyncClient, role: str) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    tag = uuid.uuid4().hex[:8]
    email, password = f"obs-{tag}@test.io", f"ObsTest{tag}9"
    reg = await client.post(
        "/api/v1/users/auth/register", json={"email": email, "password": password, "full_name": "Obs", "role": role}
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email).values(role=role, is_active=True))
        await s.commit()
    login = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _set_rate(item_no: str, boq_id: str, rate: str) -> None:
    from app.database import async_session_factory
    from app.modules.boq.models import Position

    async with async_session_factory() as s:
        pos = (
            await s.execute(select(Position).where(Position.boq_id == uuid.UUID(boq_id), Position.ordinal == item_no))
        ).scalar_one()
        pos.unit_rate = rate
        pos.total = str(Decimal(rate) * Decimal(pos.quantity))
        await s.commit()


async def _add_child(item_no: str, boq_id: str, total: str) -> None:
    from app.database import async_session_factory
    from app.modules.boq.models import Position

    async with async_session_factory() as s:
        parent = (
            await s.execute(select(Position).where(Position.boq_id == uuid.UUID(boq_id), Position.ordinal == item_no))
        ).scalar_one()
        s.add(
            Position(
                boq_id=parent.boq_id,
                parent_id=parent.id,
                ordinal=f"{item_no}.a",
                description="own breakdown",
                unit="h",
                quantity="1",
                unit_rate=total,
                total=total,
                classification={},
                source="manual",
                cad_element_ids=[],
                metadata_={},
                sort_order=999,
            )
        )
        await s.commit()


def _files(data: bytes, name: str = "bid.xlsx") -> dict:
    return {"file": (name, data, XLSX)}


async def test_round_trip(client: AsyncClient, monkeypatch):
    import app.modules.owner_schedule.service as svc
    from app.modules.owner_schedule.profile import ScheduleProfile

    from .conftest import FIXTURES

    data = json.loads((FIXTURES / "pack_profile.json").read_text(encoding="utf-8"))
    pack = ScheduleProfile.model_validate({**data, "key": "example-pack." + data["key"], "source": "pack"})
    monkeypatch.setattr(svc, "pack_profiles", lambda: [pack])

    admin = await _user(client, "admin")
    project = await client.post("/api/v1/projects/", json={"name": "Owner schedule"}, headers=admin)
    boq = await client.post(
        "/api/v1/boq/boqs/", json={"project_id": project.json()["id"], "name": "Bid"}, headers=admin
    )
    boq_id = boq.json()["id"]

    profiles = await client.get("/api/v1/owner_schedule/profiles", headers=admin)
    assert pack.key in {p["key"] for p in profiles.json()}

    det = await client.post("/api/v1/owner_schedule/detect", files=_files(agency_workbook()), headers=admin)
    assert det.status_code == 200, det.text
    assert det.json()[0]["profile_key"] == pack.key

    imp = await client.post(
        f"/api/v1/owner_schedule/boqs/{boq_id}/import",
        files=_files(agency_workbook()),
        data={"profile_key": pack.key},
        headers=admin,
    )
    assert imp.status_code == 201, imp.text
    assert imp.json()["created_positions"] == 4

    again = await client.post(
        f"/api/v1/owner_schedule/boqs/{boq_id}/import",
        files=_files(agency_workbook()),
        data={"profile_key": pack.key},
        headers=admin,
    )
    assert again.status_code == 409

    st = (await client.get(f"/api/v1/owner_schedule/boqs/{boq_id}", headers=admin)).json()
    assert (st["item_count"], st["priced_count"]) == (3, 0)
    rules = {f["rule_id"] for f in st["findings"]}
    assert {"owner_schedule.item_unpriced", "owner_schedule.alternate_unpriced"} <= rules

    await _set_rate("0201-001", boq_id, "15000")
    await _set_rate("0203-010", boq_id, "12.345")
    await _add_child("0401-005", boq_id, "29043.30")  # own breakdown, no rate on the owner line
    await _set_rate("ALT-1", boq_id, "9.99")

    st = (await client.get(f"/api/v1/owner_schedule/boqs/{boq_id}", headers=admin)).json()
    assert st["priced_count"] == 3
    assert not st["findings"], st["findings"]

    exp = await client.get(f"/api/v1/owner_schedule/boqs/{boq_id}/export", headers=admin)
    assert exp.status_code == 200, exp.text
    ws = load_workbook(io.BytesIO(exp.content))["Bid Schedule"]
    amounts = [Decimal(str(ws[f"F{r}"].value)) for r in (6, 7, 8)]
    report = (await client.get(f"/api/v1/owner_schedule/boqs/{boq_id}/check", headers=admin)).json()
    assert Decimal(report["total"]) == sum(amounts) == Decimal(report["line_sum"])
    assert ws["A1"].value == "Contract 24-117 Bid Schedule"
    assert ws["F10"].value.startswith("=SUM")

    revised = agency_workbook(
        [
            ("0201-001", "Clearing and grubbing", "LS", None),
            ("0203-010", "Unclassified excavation", "CY", 1300),
            ("0501-001", "Curb and gutter", "LF", 80),
            ("ALT-1", "Alternate: colored concrete", "SY", 120),
        ]
    )
    diff = await client.post(
        f"/api/v1/owner_schedule/boqs/{boq_id}/addendum/preview", files=_files(revised, "add1.xlsx"), headers=admin
    )
    kinds = {c["item_no"]: c["kind"] for c in diff.json()["changes"]}
    assert kinds == {"0203-010": "quantity_changed", "0501-001": "added", "0401-005": "removed"}

    applied = await client.post(
        f"/api/v1/owner_schedule/boqs/{boq_id}/addendum/apply",
        files=_files(revised, "add1.xlsx"),
        data={"item_nos": json.dumps(["0203-010", "0401-005"])},
        headers=admin,
    )
    assert applied.json() == {"revision": 1, "applied": 2}
    st = (await client.get(f"/api/v1/owner_schedule/boqs/{boq_id}", headers=admin)).json()
    items = {i["item_no"]: i for i in st["items"]}
    assert items["0203-010"]["quantity"] == "1300"
    assert items["0401-005"]["removed"]
    assert "0501-001" not in items
    # The removed item's position is still in the BOQ: it is now an extra line.
    assert "owner_schedule.extra_item" in {f["rule_id"] for f in st["findings"]}


async def test_other_project_cannot_read(client: AsyncClient):
    admin = await _user(client, "admin")
    project = await client.post("/api/v1/projects/", json={"name": "Private"}, headers=admin)
    boq = await client.post("/api/v1/boq/boqs/", json={"project_id": project.json()["id"], "name": "B"}, headers=admin)
    editor = await _user(client, "editor")
    resp = await client.get(f"/api/v1/owner_schedule/boqs/{boq.json()['id']}", headers=editor)
    assert resp.status_code == 404


async def test_profile_wizard_save_and_reject(client: AsyncClient):
    admin = await _user(client, "admin")
    good = {
        "key": f"wizard-{uuid.uuid4().hex[:6]}",
        "name": "Saved from wizard",
        "file_type": "xlsx",
        "first_data_row": 6,
        "columns": {"item_no": "A", "description": "B", "unit": "C", "quantity": "D", "unit_price": "E"},
    }
    ok = await client.post("/api/v1/owner_schedule/profiles", json=good, headers=admin)
    assert ok.status_code == 201, ok.text
    assert ok.json()["source"] == "user"
    bad = await client.post(
        "/api/v1/owner_schedule/profiles", json={**good, "columns": {"item_no": "A"}}, headers=admin
    )
    assert bad.status_code == 422
