# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document layout API: publish with locks, scopes, variants, reprint, reset, restore, import/export, clauses."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.doc_templates.models import DocTemplateIssue
from app.modules.doc_templates.permissions import register_doc_templates_permissions
from app.modules.doc_templates.router import router as dt_router
from app.modules.procurement.export_routes import export_router
from app.modules.procurement.models import PurchaseOrder, PurchaseOrderItem
from app.modules.procurement.permissions import register_procurement_permissions
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

PO = "procurement.purchase_order"


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    async with transactional_session() as s:
        yield s


async def _user(session, role: str = "admin") -> User:
    u = User(email=f"lay-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role=role, full_name="M. K.")
    session.add(u)
    await session.flush()
    return u


async def _po(session, owner: User) -> PurchaseOrder:
    project = Project(name="Riverside", owner_id=owner.id, locale="en")
    session.add(project)
    await session.flush()
    po = PurchaseOrder(
        project_id=project.id,
        po_number=f"PO-{uuid.uuid4().hex[:6]}",
        po_type="standard",
        issue_date="2026-09-01",
        currency_code="EUR",
        amount_subtotal="1000.00",
        tax_amount="190.00",
        amount_total="1190.00",
        status="draft",
        retention_percent=Decimal("0"),
    )
    session.add(po)
    await session.flush()
    session.add(
        PurchaseOrderItem(po_id=po.id, description="Concrete", quantity="10", unit="m3", unit_rate="100", amount="1000")
    )
    await session.flush()
    return po


def _app(db_session, caller_id: str, role: str = "admin") -> FastAPI:
    register_doc_templates_permissions()
    register_procurement_permissions()
    app = FastAPI()
    app.include_router(dt_router, prefix="/dt")
    app.include_router(export_router, prefix="/proc")

    async def _session():
        yield db_session

    async def _uid() -> str:
        return caller_id

    async def _payload() -> dict:
        return {"sub": caller_id, "role": role, "permissions": ["doc_templates.read", "procurement.read"]}

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = _uid
    app.dependency_overrides[get_current_user_payload] = _payload
    return app


@asynccontextmanager
async def _http(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


def _with_heading(template: dict, text: str) -> dict:
    out = dict(template)
    out["body"] = [{"id": "intro", "type": "heading", "text": {"en": text}}, *template["body"]]
    return out


async def _publish(c: AsyncClient, template: dict, **params: str) -> dict:
    r = await c.put(f"/dt/layouts/{PO}/draft", params=params, json={"template": template})
    assert r.status_code == 200, r.text
    r = await c.post(f"/dt/layouts/{PO}/publish", params=params, json={"note": "x"})
    assert r.status_code == 200, r.text
    return r.json()


async def _issues(session, po: PurchaseOrder) -> list[DocTemplateIssue]:
    stmt = (
        select(DocTemplateIssue).where(DocTemplateIssue.record_id == str(po.id)).order_by(DocTemplateIssue.created_at)
    )
    return list((await session.execute(stmt)).scalars().all())


@pytest.mark.asyncio
async def test_layout_lifecycle(db_session) -> None:
    admin = await _user(db_session)
    po = await _po(db_session, admin)
    async with _http(_app(db_session, str(admin.id))) as c:
        r = await c.get("/dt/layouts/")
        assert r.status_code == 200, r.text
        assert PO in {i["key"] for i in r.json()["items"]}

        r = await c.get(f"/dt/layouts/{PO}")
        body = r.json()
        assert body["can_edit"] is True
        assert body["state"]["inherits"] == "standard"
        assert "line_items" in body["spec"]["locks"]["sections"]
        standard = body["state"]["template"]

        # A locked section cannot be hidden: the draft saves, publishing refuses.
        broken = dict(standard)
        broken["body"] = [dict(b, hidden=True) if b["id"] == "line_items" else b for b in standard["body"]]
        r = await c.put(f"/dt/layouts/{PO}/draft", json={"template": broken})
        assert r.status_code == 200
        assert "doctpl.required_section_hidden" in {i["rule_id"] for i in r.json()["state"]["issues"]}
        r = await c.post(f"/dt/layouts/{PO}/publish", json={"note": ""})
        assert r.status_code == 422

        state = (await _publish(c, _with_heading(standard, "Company layout")))["state"]
        assert state["published_number"] == 1 and not state["has_draft"]
        company_version = state["versions"][0]["id"]

        # Project override wins for that project's records.
        state = (await _publish(c, _with_heading(standard, "Project layout"), project_id=str(po.project_id)))["state"]
        project_version = state["versions"][0]["id"]
        # A named variant prints only when asked for.
        state = (await _publish(c, _with_heading(standard, "Short"), variant="short"))["state"]
        short_version = state["versions"][0]["id"]
        assert {v["variant"] for v in state["variants"]} >= {"standard", "short"}

        r = await c.get(f"/proc/{po.id}/export/pdf/")
        assert r.status_code == 200 and r.content.startswith(b"%PDF")
        assert r.headers["content-language"] == "en"
        r = await c.get(f"/proc/{po.id}/export/pdf/", params={"variant": "short"})
        assert r.status_code == 200
        r = await c.get(f"/proc/{po.id}/export/pdf/", params={"layout_version": company_version})
        assert r.status_code == 200
        logged = [str(i.template_version_id) for i in await _issues(db_session, po)]
        assert logged == [project_version, short_version, company_version]

        # Reset prints the standard form again; restore brings version 1 back as version 3.
        r = await c.post(f"/dt/layouts/{PO}/reset")
        assert r.status_code == 200 and r.json()["state"]["published"] is None
        r = await c.post(f"/dt/layouts/{PO}/versions/{company_version}/restore")
        assert r.status_code == 200
        assert r.json()["state"]["published_number"] == 3

        r = await c.get(f"/dt/layouts/{PO}/versions/{company_version}/diff")
        assert ("intro", "added") in {(x["id"], x["change"]) for x in r.json()["changes"]}
        r = await c.get(f"/dt/layouts/{PO}/versions/{project_version}")
        assert r.status_code == 200, r.text

    # A project layout's versions stay inside the project: an outsider cannot read or diff them.
    outsider = await _user(db_session, role="viewer")
    async with _http(_app(db_session, str(outsider.id), role="viewer")) as c:
        r = await c.get(f"/dt/layouts/{PO}/versions/{project_version}")
        assert r.status_code in (403, 404), r.text
        r = await c.get(f"/dt/layouts/{PO}/versions/{company_version}/diff", params={"against": project_version})
        assert r.status_code in (403, 404), r.text
        r = await c.get(f"/dt/layouts/{PO}/versions/{company_version}")
        assert r.status_code == 200, r.text
    async with _http(_app(db_session, str(admin.id))) as c:
        r = await c.post(f"/dt/layouts/{PO}/preview", json={"template": standard, "record_id": str(po.id)})
        assert r.status_code == 200 and r.content.startswith(b"%PDF")
        r = await c.get(f"/dt/layouts/{PO}/values", params={"record_id": str(po.id)})
        assert r.json()["values"]["doc.number"] == po.po_number


@pytest.mark.asyncio
async def test_import_export_and_clauses(db_session) -> None:
    admin = await _user(db_session)
    async with _http(_app(db_session, str(admin.id))) as c:
        r = await c.get(f"/dt/layouts/{PO}/export")
        exported = r.json()
        assert exported["kind"] == PO and exported["template"]["body"]
        r = await c.post(f"/dt/layouts/{PO}/import", params={"variant": "copy"}, json=exported)
        assert r.status_code == 200 and r.json()["state"]["has_draft"]
        wrong = dict(exported, kind="procurement.goods_receipt")
        r = await c.post(f"/dt/layouts/{PO}/import", json=wrong)
        assert r.status_code == 422

        r = await c.put(
            "/dt/layouts/clauses/warranty", json={"title": {"en": "Warranty"}, "text": {"en": "Five years."}}
        )
        assert r.status_code == 200
        r = await c.put("/dt/layouts/clauses/bad", json={"text": {"en": "<b>x</b>"}})
        assert r.status_code == 422
        assert [x["key"] for x in (await c.get("/dt/layouts/clauses")).json()["items"]] == ["warranty"]
        assert (await c.delete("/dt/layouts/clauses/warranty")).status_code == 204


@pytest.mark.asyncio
async def test_a_viewer_reads_but_cannot_edit(db_session) -> None:
    viewer = await _user(db_session, role="viewer")
    async with _http(_app(db_session, str(viewer.id), role="viewer")) as c:
        r = await c.get(f"/dt/layouts/{PO}")
        assert r.status_code == 200 and r.json()["can_edit"] is False
        r = await c.put(f"/dt/layouts/{PO}/draft", json={"template": {}})
        assert r.status_code == 403
        r = await c.get(f"/dt/layouts/{PO}", params={"project_id": str(uuid.uuid4())})
        assert r.status_code == 404
