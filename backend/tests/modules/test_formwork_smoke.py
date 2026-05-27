"""Happy-path smoke test for the Formwork module (task #112).

Proves end-to-end wiring:

1. Seed one FormworkSystem via ``POST /systems/``.
2. Create one FormworkAssignment, verify ``computed_unit_cost`` and
   ``computed_total`` match the documented formula:

       unit_cost = unit_rate * (1 + waste_pct/100) / reuse_count
       total     = area_m2  * unit_cost

3. Append one schedule line under the assignment.
4. Verify list endpoints return the rows.

Comprehensive RBAC / IDOR / multi-tenant coverage is deliberately
deferred to a follow-up wave — this file is the proof-of-life only.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from decimal import Decimal
from pathlib import Path

# ── Per-module SQLite isolation (MUST run BEFORE app imports) ─────────────
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-formwork-"))
_TMP_DB = _TMP_DIR / "formwork.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}"
os.environ["DATABASE_SYNC_URL"] = f"sqlite:///{_TMP_DB.as_posix()}"

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _admin_header(client: AsyncClient) -> tuple[str, dict[str, str]]:
    """Register + activate + log in a fresh admin user."""
    tag = uuid.uuid4().hex[:8]
    email = f"formwork-{tag}@test.io"
    password = f"FormTest{tag}9"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": f"Form Tester {tag}",
            "role": "admin",
        },
    )
    assert reg.status_code in (200, 201), reg.text

    # Force-activate + force-admin (registration may demote to viewer).
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as session:
        await session.execute(
            update(User).where(User.email == email.lower()).values(role="admin", is_active=True),
        )
        await session.commit()

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    token = login.json().get("access_token", "")
    assert token, login.text
    return email, {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_formwork_end_to_end(client: AsyncClient):
    _, header = await _admin_header(client)

    # Create a project (FormworkAssignment.project_id is FK-constrained).
    proj = await client.post(
        "/api/v1/projects/",
        json={"name": "Formwork Smoke", "description": "task #112"},
        headers=header,
    )
    assert proj.status_code in (200, 201), proj.text
    project_id = proj.json()["id"]

    # 1. Create one FormworkSystem.
    sys_resp = await client.post(
        "/api/v1/formwork/systems/",
        json={
            "name": "Smoke Test Doka Framax",
            "system_type": "wall",
            "supplier": "Doka",
            "material": "steel",
            "reuses_max": 100,
            "unit_rate": "65.00",
            "currency": "EUR",
        },
        headers=header,
    )
    assert sys_resp.status_code == 201, sys_resp.text
    system = sys_resp.json()
    system_id = system["id"]
    # Money serialises as string (v3 §10 Decimal contract).
    assert isinstance(system["unit_rate"], str)
    assert Decimal(system["unit_rate"]) == Decimal("65.00")

    # 2. Create a FormworkAssignment and verify computed cost.
    # unit_cost = 65.00 * (1 + 10/100) / 10 = 7.15
    # total     = 200.00 * 7.15            = 1430.00
    assign_resp = await client.post(
        "/api/v1/formwork/assignments/",
        json={
            "project_id": project_id,
            "formwork_system_id": system_id,
            "area_m2": "200.00",
            "reuse_count": 10,
            "waste_pct": "10.00",
            "notes": "L02 walls",
        },
        headers=header,
    )
    assert assign_resp.status_code == 201, assign_resp.text
    assignment = assign_resp.json()
    assignment_id = assignment["id"]
    assert Decimal(assignment["computed_unit_cost"]) == Decimal("7.15")
    assert Decimal(assignment["computed_total"]) == Decimal("1430.00")

    # 3. Append a schedule line.
    line_resp = await client.post(
        f"/api/v1/formwork/assignments/{assignment_id}/schedule-lines/",
        json={
            "pour_no": 1,
            "level_label": "L02 walls",
            "area_m2": "200.00",
            "notes": "first lift",
        },
        headers=header,
    )
    assert line_resp.status_code == 201, line_resp.text
    line = line_resp.json()
    assert line["pour_no"] == 1
    assert line["level_label"] == "L02 walls"
    assert Decimal(line["area_m2"]) == Decimal("200.00")

    # 4. Verify list endpoints return what we inserted.
    list_sys = await client.get(
        "/api/v1/formwork/systems/",
        headers=header,
    )
    assert list_sys.status_code == 200, list_sys.text
    assert any(s["id"] == system_id for s in list_sys.json())

    list_asn = await client.get(
        "/api/v1/formwork/assignments/",
        params={"project_id": project_id},
        headers=header,
    )
    assert list_asn.status_code == 200, list_asn.text
    assert any(a["id"] == assignment_id for a in list_asn.json())

    list_lines = await client.get(
        f"/api/v1/formwork/assignments/{assignment_id}/schedule-lines/",
        headers=header,
    )
    assert list_lines.status_code == 200, list_lines.text
    assert len(list_lines.json()) == 1
