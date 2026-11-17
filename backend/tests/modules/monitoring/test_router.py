# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Router wiring without a database: permissions, project access, status codes and the PDF response.

The service is replaced by a fake, so this checks only what the router owns.
The database-backed lessons live in ``test_api.py``.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.core.active_markets import resolve_active_markets
from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.monitoring import router as router_module
from app.modules.monitoring.schemas import MonitoringSummary
from app.modules.survey_core.permissions import register_survey_permissions

PROJECT = uuid.uuid4()
POINT = SimpleNamespace(id=uuid.uuid4(), project_id=PROJECT)
BASE = "/api/v1/monitoring"


class FakeService:
    calls: list[str] = []

    def __init__(self, session: object) -> None:
        self.session = session

    async def get_point(self, point_id: uuid.UUID):  # noqa: ANN201
        if point_id != POINT.id:
            raise HTTPException(status_code=404, detail="Not found")
        return POINT

    async def summary(self, project_id: uuid.UUID, markets: list[str]) -> MonitoringSummary:
        FakeService.calls.append(f"summary:{','.join(markets)}")
        return MonitoringSummary(points=2, ok=1, alert=0, action=1, alarm=0, unacknowledged=1)

    async def acknowledge(self, point: object, body: object, user_id: str, markets: list[str]) -> dict:
        FakeService.calls.append("ack")
        raise HTTPException(status_code=409, detail="Nothing to acknowledge")

    async def import_readings(self, *args: object) -> None:
        FakeService.calls.append(f"import:{args[-1]}")
        raise HTTPException(status_code=422, detail="stop here")

    async def report_pdf(self, project_id: uuid.UUID, markets: list[str], locale: str) -> bytes:
        return b"%PDF-1.4 fake"


def _app(role: str, permissions: list[str] | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(router_module.router, prefix=BASE)

    async def payload() -> dict:
        return {"sub": "u1", "role": role, "permissions": permissions or []}

    async def session():  # noqa: ANN202
        yield SimpleNamespace()

    app.dependency_overrides[get_current_user_payload] = payload
    app.dependency_overrides[get_current_user_id] = lambda: str(uuid.uuid4())
    app.dependency_overrides[get_session] = session
    app.dependency_overrides[resolve_active_markets] = lambda: ["*"]
    return app


@pytest.fixture(autouse=True)
def _fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeService.calls = []
    register_survey_permissions()
    monkeypatch.setattr(router_module, "MonitoringService", FakeService)


async def _client(app: FastAPI, monkeypatch: pytest.MonkeyPatch, access: bool = True) -> AsyncClient:
    async def verify(project_id: uuid.UUID, user_id: str, session: object) -> None:
        if not access:
            raise HTTPException(status_code=403, detail="No access")

    monkeypatch.setattr(router_module, "verify_project_access", verify)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_summary_for_a_viewer_gets_the_callers_markets(monkeypatch: pytest.MonkeyPatch) -> None:
    async with await _client(_app("viewer"), monkeypatch) as c:
        r = await c.get(f"{BASE}/projects/{PROJECT}/summary")
    assert r.status_code == 200
    assert r.json()["action"] == 1
    assert FakeService.calls == ["summary:*"]


async def test_a_viewer_cannot_import_readings(monkeypatch: pytest.MonkeyPatch) -> None:
    async with await _client(_app("viewer"), monkeypatch) as c:
        r = await c.post(f"{BASE}/projects/{PROJECT}/readings", json={"text": "point,date,z\nA,2026-10-09,1\n"})
    assert r.status_code == 403
    assert FakeService.calls == []


async def test_an_editor_imports_and_the_locale_travels(monkeypatch: pytest.MonkeyPatch) -> None:
    async with await _client(_app("editor"), monkeypatch) as c:
        r = await c.post(
            f"{BASE}/projects/{PROJECT}/readings?locale=de", json={"text": "point,date,z\nA,2026-10-09,1\n"}
        )
    assert r.status_code == 422
    assert FakeService.calls == ["import:de"]


async def test_an_editor_cannot_acknowledge_but_a_manager_and_a_surveyor_can(monkeypatch: pytest.MonkeyPatch) -> None:
    url = f"{BASE}/points/{POINT.id}/acknowledge"
    async with await _client(_app("editor"), monkeypatch) as c:
        assert (await c.post(url, json={"note": "seen"})).status_code == 403
    assert FakeService.calls == []
    for role in ("manager", "surveyor", "admin"):
        async with await _client(_app(role), monkeypatch) as c:
            assert (await c.post(url, json={"note": "seen"})).status_code == 409, role
    assert FakeService.calls == ["ack"] * 3


async def test_project_access_is_checked_before_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    async with await _client(_app("admin"), monkeypatch, access=False) as c:
        a = await c.get(f"{BASE}/projects/{PROJECT}/summary")
        b = await c.post(f"{BASE}/points/{POINT.id}/acknowledge", json={})
    assert (a.status_code, b.status_code) == (403, 403)
    assert FakeService.calls == []


async def test_the_report_is_a_pdf_attachment(monkeypatch: pytest.MonkeyPatch) -> None:
    async with await _client(_app("viewer"), monkeypatch) as c:
        r = await c.get(f"{BASE}/projects/{PROJECT}/report.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "monitoring-alarm-report.pdf" in r.headers["content-disposition"]


async def test_an_unknown_point_is_404_and_a_bad_body_is_422(monkeypatch: pytest.MonkeyPatch) -> None:
    async with await _client(_app("manager"), monkeypatch) as c:
        missing = await c.post(f"{BASE}/points/{uuid.uuid4()}/acknowledge", json={})
        bad = await c.post(f"{BASE}/projects/{PROJECT}/points", json={"code": "", "point_type": "laser"})
    assert missing.status_code == 404
    assert bad.status_code == 422
