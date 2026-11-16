# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Documents & templates API: the DOMAIN worked examples, permissions and the letter bridge."""

from __future__ import annotations

import io
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.money import format_money
from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.doc_templates.kinds import PASSWORD_RESET_KEY, register_builtin_kinds
from app.modules.doc_templates.models import DocTemplate  # noqa: F401 - registers ORM
from app.modules.doc_templates.permissions import register_doc_templates_permissions
from app.modules.doc_templates.router import router as dt_router
from app.modules.projects.models import Project
from app.modules.tendering.models import TenderBid, TenderPackage
from app.modules.users.models import User
from tests._pg import transactional_session

AWARD = "tendering.award_letter"
INTRO_DE = "Sehr geehrte Damen und Herren, wir freuen uns, Ihnen den Auftrag für {{package.name}} zu erteilen."


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    async with transactional_session() as s:
        yield s


async def _user(session, role: str = "admin", email: str | None = None) -> User:
    u = User(email=email or f"dt-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role=role, full_name="A. B.")
    session.add(u)
    await session.flush()
    return u


def _app(db_session, caller_id: str, role: str = "admin") -> FastAPI:
    register_doc_templates_permissions()
    register_builtin_kinds()
    app = FastAPI()
    app.include_router(dt_router, prefix="/dt")

    async def _session():
        yield db_session

    async def _uid() -> str:
        return caller_id

    async def _payload() -> dict:
        return {"sub": caller_id, "role": role, "permissions": ["doc_templates.read"]}

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = _uid
    app.dependency_overrides[get_current_user_payload] = _payload
    return app


@asynccontextmanager
async def _http(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def _publish(c: AsyncClient, key: str, locale: str, blocks: dict[str, str]) -> dict:
    r = await c.put(f"/dt/{key}/draft", params={"locale": locale}, json={"blocks": blocks})
    assert r.status_code == 200, r.text
    r = await c.post(f"/dt/{key}/publish", params={"locale": locale}, json={"note": ""})
    assert r.status_code == 200, r.text
    return r.json()


def test_worked_example_1_amount_format() -> None:
    assert format_money("1248300.00", "EUR", "de") == "1.248.300,00 €"


@pytest.mark.asyncio
async def test_worked_example_1_publish_restore_and_real_record_preview(db_session, monkeypatch) -> None:
    from app.modules.doc_templates import service as dt_service

    monkeypatch.setattr(dt_service, "PREVIEW_TIMEOUT", 120.0)  # cold font loading on slow CI hosts
    user = await _user(db_session)
    project = Project(name="Haus B", owner_id=user.id, locale="de")
    db_session.add(project)
    await db_session.flush()
    package = TenderPackage(project_id=project.id, name="Rohbau Haus B")
    db_session.add(package)
    await db_session.flush()
    bid = TenderBid(package_id=package.id, company_name="Bau AG", total_amount="1248300.00", currency="EUR")
    db_session.add(bid)
    await db_session.commit()

    async with _http(_app(db_session, str(user.id))) as c:
        await _publish(c, AWARD, "de", {"body": "Version eins für {{package.name}}."})
        await _publish(c, AWARD, "de", {"body": "Version zwei für {{package.name}}."})
        state = await _publish(c, AWARD, "de", {"body": INTRO_DE})
        assert [v["number"] for v in state["versions"]] == [3, 2, 1]
        assert state["published_text"]["body"] == INTRO_DE
        v2 = next(v for v in state["versions"] if v["number"] == 2)

        records = (await c.get(f"/dt/{AWARD}/records")).json()
        assert any(r["id"] == str(bid.id) and "Rohbau Haus B" in r["label"] for r in records)
        r = await c.post(
            f"/dt/{AWARD}/preview",
            params={"locale": "de"},
            json={"blocks": {"body": INTRO_DE}, "record_id": str(bid.id)},
        )
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        from pypdf import PdfReader

        text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(r.content)).pages)
        assert "Rohbau Haus B" in text
        assert "1.248.300,00" in text

        r = await c.post(f"/dt/{AWARD}/versions/{v2['id']}/restore", params={"locale": "de"})
        assert r.status_code == 200, r.text
        state = r.json()
        assert state["versions"][0]["number"] == 4 and state["versions"][0]["is_published"]
        assert state["published_text"]["body"] == "Version zwei für {{package.name}}."

    from app.modules.letter_templates.service import resolve as resolve_letter

    resolved = await resolve_letter(db_session, AWARD, "de", project.id)
    assert resolved.text.body == "Version zwei für {package}."


@pytest.mark.asyncio
async def test_publish_refuses_unknown_field_and_injection(db_session) -> None:
    user = await _user(db_session)
    await db_session.commit()
    async with _http(_app(db_session, str(user.id))) as c:
        for text in ("Hallo {{pkg}}", "{{ package.__class__ }}", "<script>alert(1)</script>"):
            r = await c.put(f"/dt/{AWARD}/draft", params={"locale": "de"}, json={"blocks": {"body": text}})
            assert r.status_code == 200
            assert any(i["severity"] == "error" for i in r.json()["issues"])
            r = await c.post(f"/dt/{AWARD}/publish", params={"locale": "de"}, json={})
            assert r.status_code == 422


@pytest.mark.asyncio
async def test_missing_translation_flags_and_prints_primary_language(db_session) -> None:
    user = await _user(db_session)
    await db_session.commit()
    async with _http(_app(db_session, str(user.id))) as c:
        await _publish(c, AWARD, "de", {"body": INTRO_DE})
        state = (await c.get(f"/dt/{AWARD}", params={"locale": "fr"})).json()
        assert state["has_translation"] is False
        assert state["primary_locale"] == "de"
        assert any(i["rule_id"] == "doctpl.locale_fallback" for i in state["issues"])
    from app.modules.letter_templates.service import resolve as resolve_letter

    assert "Auftrag" in (await resolve_letter(db_session, AWARD, "fr", None)).text.body


@pytest.mark.asyncio
async def test_reset_returns_to_builtin(db_session) -> None:
    user = await _user(db_session)
    await db_session.commit()
    async with _http(_app(db_session, str(user.id))) as c:
        await _publish(c, AWARD, "en", {"body": "Own words for {{package.name}}."})
        r = await c.post(f"/dt/{AWARD}/reset", params={"locale": "en"})
        assert r.status_code == 200
        assert r.json()["published_text"] is None
        rows = (await c.get("/dt/")).json()["items"]
        assert next(i for i in rows if i["key"] == AWARD)["status"] == "default"


@pytest.mark.asyncio
async def test_worked_example_4_no_rows_means_builtin(db_session) -> None:
    from app.core.email.templates import _LOGO_URL, brand_header
    from app.modules.doc_templates.service import resolve
    from app.modules.letter_templates.service import resolve as resolve_letter

    res = await resolve(db_session, AWARD, "de")
    assert res is not None and res.source == "default"
    assert (await resolve_letter(db_session, AWARD, "de", None)).source == "default"
    assert _LOGO_URL in brand_header()


@pytest.mark.asyncio
async def test_editor_needs_document_manager_role(db_session) -> None:
    admin = await _user(db_session)
    editor = await _user(db_session, role="editor")
    await db_session.commit()
    async with _http(_app(db_session, str(editor.id), role="editor")) as c:
        listing = (await c.get("/dt/")).json()
        assert listing["can_edit"] is False
        r = await c.put(f"/dt/{AWARD}/draft", params={"locale": "en"}, json={"blocks": {"body": "x"}})
        assert r.status_code == 403
        assert (await c.get("/dt/managers")).status_code == 403
    async with _http(_app(db_session, str(admin.id))) as c:
        r = await c.put(f"/dt/managers/{editor.id}", json={"is_manager": True})
        assert r.status_code == 200 and r.json()["is_manager"] is True
    async with _http(_app(db_session, str(editor.id), role="editor")) as c:
        r = await c.put(f"/dt/{AWARD}/draft", params={"locale": "en"}, json={"blocks": {"body": "x {{package.name}}"}})
        assert r.status_code == 200


@pytest.mark.asyncio
async def test_worked_example_3_test_send_goes_to_own_address(db_session, monkeypatch) -> None:
    from app.core.email import service as email_service
    from app.core.email.memory import MemoryEmailBackend
    from app.core.email.service import EmailService

    backend = MemoryEmailBackend()
    monkeypatch.setattr(email_service, "get_email_service", lambda *a, **k: EmailService(backend))
    monkeypatch.setattr(email_service, "email_delivery_enabled", lambda _s: True)
    user = await _user(db_session, email="editor@ridgeline-civil.example")
    await db_session.commit()
    async with _http(_app(db_session, str(user.id))) as c:
        blocks = {"subject": "Reset for {{recipient.name}}", "body": "Hello", "cta_label": "Go"}
        r = await c.post(f"/dt/{PASSWORD_RESET_KEY}/test-send", params={"locale": "en"}, json={"blocks": blocks})
        assert r.status_code == 200, r.text
        assert r.json() == {"sent": True, "to": user.email, "detail": ""}
        assert backend.sent[0].to == user.email
        assert backend.sent[0].subject == "[Test] Reset for Jane Smith"
        r = await c.post(f"/dt/{AWARD}/test-send", params={"locale": "en"}, json={"blocks": {}})
        assert r.status_code == 400

        r = await c.post(f"/dt/{PASSWORD_RESET_KEY}/preview", params={"locale": "en"}, json={"blocks": blocks})
        assert r.status_code == 200
        assert r.json()["subject"] == "Reset for Jane Smith"
