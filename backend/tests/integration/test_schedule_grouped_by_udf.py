# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Group the server-side activity grid by a user-defined field (T2.3).

``resolve_grouped_layout`` used to refuse a UDF group key outright. This suite
drives the real grouped endpoint end to end - register, login, a project, a
schedule, activities, two UDF definitions (a number and a text field), per
activity UDF values, then a grouped POST with ``group_by: udf:<id>`` - and
proves the bands and the per-row group paths line up.

The pure key/label stringifier is unit-tested on the local interpreter in
``tests/unit/test_codes_grouped_tree.py``; this is the DB-backed half (CI, the
PostgreSQL cluster bound by ``conftest.py`` before any ``from app...`` import).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.schedule import models as _schedule_models  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register_login_admin(client: AsyncClient) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"grp-udf-{uuid.uuid4().hex[:8]}@schedule.io"
    password = f"GrpUdf{uuid.uuid4().hex[:6]}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Grouped UDF Owner"},
    )
    assert reg.status_code in (200, 201), reg.text

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await s.commit()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _make_activity(client: AsyncClient, schedule_id: str, headers: dict[str, str], *, name: str, wbs: str) -> str:
    act = await client.post(
        f"/api/v1/schedule/schedules/{schedule_id}/activities/",
        json={
            "name": name,
            "wbs_code": wbs,
            "start_date": "2026-05-04",
            "end_date": "2026-05-15",
            "activity_type": "task",
        },
        headers=headers,
    )
    assert act.status_code == 201, act.text
    return act.json()["id"]


async def _set_udf_value(client: AsyncClient, activity_id: str, headers: dict[str, str], udf_id: str, value) -> None:
    resp = await client.put(
        f"/api/v1/schedule/activities/{activity_id}/udf-values/",
        json={"values": [{"udf_id": udf_id, "value": value}]},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


@pytest_asyncio.fixture(scope="module")
async def grouped_world(http_client):
    """A project + schedule + activities tagged with a number and a text UDF.

    Layout of the four activities:

    * A1 -> floor 5, zone "North"
    * A2 -> floor 5, zone "South"
    * A3 -> floor 10, zone "North"
    * A4 -> (no UDF values at all)
    """
    headers = await _register_login_admin(http_client)

    proj = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"Grouped UDF {uuid.uuid4().hex[:6]}", "description": "udf grouping", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    sched = await http_client.post(
        "/api/v1/schedule/schedules/",
        json={
            "project_id": project_id,
            "name": "Grouped UDF Schedule",
            "start_date": "2026-05-01",
            "end_date": "2026-09-30",
        },
        headers=headers,
    )
    assert sched.status_code == 201, sched.text
    schedule_id = sched.json()["id"]

    # Two UDFs: a number (Numeric storage, reads back as Decimal) and a text one.
    num_udf = await http_client.post(
        f"/api/v1/schedule/projects/{project_id}/udfs/",
        json={"key": "floor", "label": "Floor", "value_type": "number"},
        headers=headers,
    )
    assert num_udf.status_code == 201, num_udf.text
    floor_id = num_udf.json()["id"]

    txt_udf = await http_client.post(
        f"/api/v1/schedule/projects/{project_id}/udfs/",
        json={"key": "zone", "label": "Zone", "value_type": "text"},
        headers=headers,
    )
    assert txt_udf.status_code == 201, txt_udf.text
    zone_id = txt_udf.json()["id"]

    a1 = await _make_activity(http_client, schedule_id, headers, name="A1", wbs="01.01")
    a2 = await _make_activity(http_client, schedule_id, headers, name="A2", wbs="01.02")
    a3 = await _make_activity(http_client, schedule_id, headers, name="A3", wbs="01.03")
    a4 = await _make_activity(http_client, schedule_id, headers, name="A4", wbs="01.04")

    # Send a whole-number value through to exercise the Numeric(18,4) read-back.
    await _set_udf_value(http_client, a1, headers, floor_id, 5)
    await _set_udf_value(http_client, a1, headers, zone_id, "North")
    await _set_udf_value(http_client, a2, headers, floor_id, 5)
    await _set_udf_value(http_client, a2, headers, zone_id, "South")
    await _set_udf_value(http_client, a3, headers, floor_id, 10)
    await _set_udf_value(http_client, a3, headers, zone_id, "North")
    # A4 deliberately gets no values -> it must land in the (none) band.

    return {
        "headers": headers,
        "schedule_id": schedule_id,
        "floor_id": floor_id,
        "zone_id": zone_id,
        "activities": {"A1": a1, "A2": a2, "A3": a3, "A4": a4},
    }


async def _grouped(client: AsyncClient, world: dict, group_keys: list[str]) -> dict:
    resp = await client.post(
        f"/api/v1/schedule/schedules/{world['schedule_id']}/activities/grouped/",
        json={"spec": {"group_by": [{"key": k} for k in group_keys]}, "page": 1, "page_size": 100},
        headers=world["headers"],
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_group_by_number_udf_bands_and_paths(http_client, grouped_world):
    """Grouping by a number UDF yields clean numeric bands + matching row paths."""
    body = await _grouped(http_client, grouped_world, [f"udf:{grouped_world['floor_id']}"])

    bands = {b["key"]: b for b in body["groups"]}
    # Numeric(18,4) read-back must render without storage padding ("5", not "5.0000").
    assert "5" in bands, f"expected a '5' band, got {sorted(bands)}"
    assert "10" in bands, f"expected a '10' band, got {sorted(bands)}"
    assert "__none__" in bands, "the unassigned activity must fall into a (none) band"
    # No Decimal repr ever leaks into a key or a label.
    for b in body["groups"]:
        assert "Decimal" not in b["key"]
        assert "Decimal" not in b["label"]
    # Band label falls back to the raw value (no meta is supplied for UDF levels).
    assert bands["5"]["label"] == "5"
    assert bands["10"]["label"] == "10"

    # Band counts: two on floor 5, one on floor 10, one unassigned.
    assert bands["5"]["count"] == 2
    assert bands["10"]["count"] == 1
    assert bands["__none__"]["count"] == 1
    assert sum(b["count"] for b in body["groups"]) == 4
    assert body["total_estimate"] == 4

    # Every leaf row's group_path[0] is exactly the band key it belongs to.
    by_name = {r["name"]: r for r in body["rows"]}
    assert by_name["A1"]["group_path"] == ["5"]
    assert by_name["A2"]["group_path"] == ["5"]
    assert by_name["A3"]["group_path"] == ["10"]
    assert by_name["A4"]["group_path"] == ["__none__"]


@pytest.mark.asyncio
async def test_group_by_text_then_number_udf_two_levels(http_client, grouped_world):
    """Two UDF levels (text then number) nest, and the paths stay aligned."""
    body = await _grouped(
        http_client,
        grouped_world,
        [f"udf:{grouped_world['zone_id']}", f"udf:{grouped_world['floor_id']}"],
    )

    # Top level: North (A1, A3), South (A2), (none) (A4).
    top = {b["key"]: b for b in body["groups"] if b["depth"] == 0}
    assert top["North"]["count"] == 2
    assert top["South"]["count"] == 1
    assert top["__none__"]["count"] == 1

    by_name = {r["name"]: r for r in body["rows"]}
    assert by_name["A1"]["group_path"] == ["North", "5"]
    assert by_name["A3"]["group_path"] == ["North", "10"]
    assert by_name["A2"]["group_path"] == ["South", "5"]
    # A4 has neither UDF -> (none) at both levels.
    assert by_name["A4"]["group_path"] == ["__none__", "__none__"]

    # Leaf counts still sum to the grand total.
    leaves = [b for b in body["groups"] if b["depth"] == 1]
    assert sum(b["count"] for b in leaves) == 4


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_group_by_udf_from_another_project_is_rejected(http_client, grouped_world):
    """A UDF id that is not in this project must be refused, not silently grouped."""
    headers = grouped_world["headers"]

    other_proj = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"Other {uuid.uuid4().hex[:6]}", "description": "foreign udf", "currency": "EUR"},
        headers=headers,
    )
    assert other_proj.status_code == 201, other_proj.text
    other_project_id = other_proj.json()["id"]

    foreign_udf = await http_client.post(
        f"/api/v1/schedule/projects/{other_project_id}/udfs/",
        json={"key": "floor", "label": "Floor", "value_type": "number"},
        headers=headers,
    )
    assert foreign_udf.status_code == 201, foreign_udf.text
    foreign_id = foreign_udf.json()["id"]

    resp = await http_client.post(
        f"/api/v1/schedule/schedules/{grouped_world['schedule_id']}/activities/grouped/",
        json={"spec": {"group_by": [{"key": f"udf:{foreign_id}"}]}},
        headers=headers,
    )
    assert resp.status_code == 422, f"a foreign UDF must be a 422, got {resp.status_code}: {resp.text}"
    assert "not in this project" in resp.text
