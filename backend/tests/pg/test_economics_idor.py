# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Who may read, edit and propose the economics, over HTTP against PostgreSQL; plus the API contract.

Identity is the variable under test: a stranger from another tenant, an editor trying to propose or
approve (manager only), another project's rows reached through this project's route, and the money
contract (decimal strings in, floats refused).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.economics.permissions import register_economics_permissions
from app.modules.economics.router import router
from tests._pg import isolated_engine
from tests.pg.economics_fixtures import build_world, call, fill
from tests.pg.governance_fixtures import World

pytestmark = [pytest.mark.asyncio, pytest.mark.tenant_isolation]

BASE = "/api/v1/economics"


@pytest_asyncio.fixture
async def world():
    register_economics_permissions()
    async with isolated_engine() as engine:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        yield await build_world(factory, governance=False)


@asynccontextmanager
async def client_as(w: World, user_id: uuid.UUID, role: str):
    from app.dependencies import get_current_user_id, get_current_user_payload, get_session

    app = FastAPI()
    app.include_router(router, prefix=BASE)

    async def _session():
        async with w.factory() as s:
            yield s
            await s.commit()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = lambda: str(user_id)
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": str(user_id),
        "role": role,
        "permissions": [],
        "tenant_id": str(user_id),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://eco-test") as c:
        yield c


async def test_a_stranger_from_another_tenant_cannot_read_edit_or_propose(world: World) -> None:
    await fill(world)
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.outsider, "manager") as c:
        responses = [
            await c.get(f"{p}/plan"),
            await c.get(f"{p}/business-case"),
            await c.get(f"{p}/cost-frame"),
            await c.get(f"{p}/financing"),
            await c.get(f"{p}/readiness"),
            await c.get(f"{p}/registers"),
            await c.put(f"{p}/registers/tax", json={"vat_treatment": "exempt"}),
            await c.post(f"{p}/registers/securities", json={"kind": "bid"}),
            await c.get(f"{p}/export?what=financing&format=xlsx"),
            await c.post(f"{p}/cost-frame/lines", json={"code": "500", "amount": "1"}),
            await c.post(f"{p}/propose", json={"rationale": "x"}),
            await c.post(f"{p}/approve"),
        ]
    assert [r.status_code for r in responses] == [404] * len(responses)


async def test_every_document_exports_as_pdf_and_xlsx_in_the_readers_language(world: World) -> None:
    await fill(world)
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.manager, "manager") as c:
        for what in ("frame", "case", "financing"):
            pdf = await c.get(f"{p}/export?what={what}&format=pdf")
            xlsx = await c.get(f"{p}/export?what={what}&format=xlsx")
            assert pdf.status_code == 200, what
            assert pdf.content.startswith(b"%PDF"), what
            assert xlsx.status_code == 200, what
            assert xlsx.content.startswith(b"PK"), what
            assert pdf.headers["content-language"]
            assert xlsx.headers["content-language"] == pdf.headers["content-language"]


async def test_the_printed_figures_are_the_screens_figures(world: World) -> None:
    from app.core.register_export import register_text_rows
    from app.modules.economics import export as ex

    await fill(world)
    frame = await call(world, "cost_frame")
    doc = ex.frame_document(frame, project_name="P", locale="de", country="DE")
    rows = register_text_rows(doc)
    assert rows[0][2] == "Budget"
    assert any("2.000.000,00" in cell for row in rows for cell in row)
    financing = await call(world, "financing")
    printed = ex.financing_document(financing, project_name="P", locale="en")
    assert Decimal(financing["coverage"]["sources_total"]) == sum((Decimal(r[3]) for r in printed.rows), Decimal(0))


async def test_an_editor_can_edit_but_not_propose_or_approve(world: World) -> None:
    await fill(world)
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.editor, "editor") as c:
        edited = await c.post(f"{p}/cost-frame/lines", json={"code": "500", "title": "Outdoor", "amount": "1000.50"})
        proposed = await c.post(f"{p}/propose", json={"rationale": "x"})
        approved = await c.post(f"{p}/approve")
        seen = await c.get(f"{p}/plan")
    assert edited.status_code == 201
    assert [proposed.status_code, approved.status_code] == [403, 403]
    assert seen.json()["can"] == {"edit": True, "manage": False, "records": True}


async def test_money_is_a_decimal_string_and_a_float_is_refused(world: World) -> None:
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.manager, "manager") as c:
        refused = await c.post(f"{p}/cost-frame/lines", json={"code": "500", "amount": 1000.5})
        accepted = await c.post(f"{p}/cost-frame/lines", json={"code": "500", "amount": "1000.5"})
        frame = await c.get(f"{p}/cost-frame")
    assert refused.status_code == 422
    assert accepted.status_code == 201
    line = frame.json()["lines"][0]
    assert line["amount"] == "1000.50"
    assert isinstance(frame.json()["totals"]["frame"], str)


async def test_another_projects_rows_are_404(world: World) -> None:
    other = await build_world(world.factory, governance=False)
    await fill(other)
    async with world.factory() as s:
        from app.modules.economics.repository import EconomicsRepository

        foreign = (await EconomicsRepository(s).frame_lines(other.project_id))[0]
        foreign_source = (await EconomicsRepository(s).sources(other.project_id))[0]
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.manager, "manager") as c:
        patched = await c.patch(f"{p}/cost-frame/lines/{foreign.id}", json={"title": "mine now"})
        deleted = await c.delete(f"{p}/cost-frame/lines/{foreign.id}")
        tranche = await c.post(
            f"{p}/financing/sources/{foreign_source.id}/tranches", json={"due_on": "2027-01-01", "amount": "1"}
        )
    assert [patched.status_code, deleted.status_code, tranche.status_code] == [404, 404, 404]
    assert len((await call(other, "cost_frame"))["lines"]) == 2


async def test_registers_of_another_project_are_404_and_a_viewer_cannot_write(world: World) -> None:
    other = await build_world(world.factory, governance=False)
    await call(other, "add_security", {"kind": "bid", "description": "Foreign bond"}, other.manager)
    await call(other, "add_insurance", {"kind": "liability", "insurer": "Foreign"}, other.manager)
    async with world.factory() as s:
        from app.modules.economics.repository import EconomicsRepository

        foreign_security = (await EconomicsRepository(s).securities(other.project_id))[0]
        foreign_insurance = (await EconomicsRepository(s).insurances(other.project_id))[0]
    p = f"{BASE}/projects/{world.project_id}"
    async with client_as(world, world.manager, "manager") as c:
        patched = await c.patch(f"{p}/registers/securities/{foreign_security.id}", json={"status": "released"})
        deleted = await c.delete(f"{p}/registers/insurances/{foreign_insurance.id}")
        bad_area = await c.put(f"{p}/registers/process/finance", json={"status": "set_up"})
    assert [patched.status_code, deleted.status_code, bad_area.status_code] == [404, 404, 422]
    assert len((await call(other, "registers"))["securities"]) == 1
    async with client_as(world, world.manager, "viewer") as c:
        read = await c.get(f"{p}/registers")
        written = await c.put(f"{p}/registers/tax", json={"vat_treatment": "exempt"})
    assert [read.status_code, written.status_code] == [200, 403]
