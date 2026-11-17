# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Router wiring without a database: permissions, project access, status codes and the PDF response.

The service is replaced by a fake, so this checks only what the router owns.
The database-backed lessons live in ``test_api.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.setting_out import router as router_module
from app.modules.setting_out.schemas import NcrDraftOut, RecordOut, SettingOutSummary

PROJECT = uuid.uuid4()
REQ = SimpleNamespace(id=uuid.uuid4(), project_id=PROJECT, code="SO-001")
STAKE = SimpleNamespace(id=uuid.uuid4(), project_id=PROJECT, request_id=REQ.id)
REC = SimpleNamespace(id=uuid.uuid4(), project_id=PROJECT)


class FakeService:
    calls: list[str] = []

    def __init__(self, session: object) -> None:
        self.session = session

    async def get_request(self, request_id: uuid.UUID):  # noqa: ANN201
        if request_id != REQ.id:
            raise HTTPException(status_code=404, detail="Not found")
        return REQ

    async def get_stake(self, stake_id: uuid.UUID):  # noqa: ANN201
        return STAKE

    async def get_record(self, record_id: uuid.UUID):  # noqa: ANN201
        return REC

    async def summary(self, project_id: uuid.UUID) -> SettingOutSummary:
        FakeService.calls.append("summary")
        return SettingOutSummary(requests=1, open=0, passed=1, failed=1, ncr_drafts=1)

    async def add_record(self, stake: object, body: object, user_id: str) -> RecordOut:
        FakeService.calls.append("record")
        return RecordOut(
            id=uuid.uuid4(),
            point_id=STAKE.id,
            measured_e=389060.012,
            measured_n=5819029.991,
            measured_z=None,
            de_mm=12,
            dn_mm=-9,
            d_mm=15,
            dz_mm=None,
            tol_h_mm=10,
            tol_v_mm=10,
            verdict="fail",
            instrument="TS",
            control_ref="CP1",
            measured_by="Demo",
            measured_at=datetime.now(UTC),
            note="",
            ncr_id=None,
        )

    async def create_ncr_draft(self, rec: object, user_id: str, locale: str) -> NcrDraftOut:
        FakeService.calls.append(f"ncr:{locale}")
        return NcrDraftOut(ncr_id=str(uuid.uuid4()), ncr_number="NCR-001", record_id=REC.id)

    async def sheet_pdf(self, req: object, locale: str) -> bytes:
        return b"%PDF-1.4 fake"


def _app(role: str) -> FastAPI:
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1/setting-out")

    async def payload() -> dict:
        return {"sub": "u1", "role": role, "permissions": []}

    async def session():  # noqa: ANN202
        yield SimpleNamespace()

    app.dependency_overrides[get_current_user_payload] = payload
    app.dependency_overrides[get_current_user_id] = lambda: str(uuid.uuid4())
    app.dependency_overrides[get_session] = session
    return app


@pytest.fixture(autouse=True)
def _fakes(monkeypatch: pytest.MonkeyPatch) -> None:
    FakeService.calls = []
    monkeypatch.setattr(router_module, "SettingOutService", FakeService)


async def _client(app: FastAPI, monkeypatch: pytest.MonkeyPatch, access: bool = True) -> AsyncClient:
    async def verify(project_id: uuid.UUID, user_id: str, session: object) -> None:
        if not access:
            raise HTTPException(status_code=403, detail="No access")

    monkeypatch.setattr(router_module, "verify_project_access", verify)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_summary_for_a_viewer(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.survey_core.permissions import register_survey_permissions

    register_survey_permissions()
    async with await _client(_app("viewer"), monkeypatch) as c:
        r = await c.get(f"/api/v1/setting-out/projects/{PROJECT}/summary")
    assert r.status_code == 200
    assert r.json()["ncr_drafts"] == 1


async def test_viewer_cannot_record(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.modules.survey_core.permissions import register_survey_permissions

    register_survey_permissions()
    async with await _client(_app("viewer"), monkeypatch) as c:
        r = await c.post(f"/api/v1/setting-out/stakes/{STAKE.id}/records", json={"measured_e": 1, "measured_n": 2})
    assert r.status_code == 403
    assert "record" not in FakeService.calls


async def test_editor_records_and_gets_201(monkeypatch: pytest.MonkeyPatch) -> None:
    async with await _client(_app("admin"), monkeypatch) as c:
        r = await c.post(
            f"/api/v1/setting-out/stakes/{STAKE.id}/records", json={"measured_e": 389060.012, "measured_n": 5819029.991}
        )
    assert r.status_code == 201
    assert (r.json()["d_mm"], r.json()["verdict"]) == (15.0, "fail")


async def test_project_access_is_checked_before_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    async with await _client(_app("admin"), monkeypatch, access=False) as c:
        r = await c.post(f"/api/v1/setting-out/stakes/{STAKE.id}/records", json={"measured_e": 1, "measured_n": 2})
        s = await c.get(f"/api/v1/setting-out/projects/{PROJECT}/summary")
    assert (r.status_code, s.status_code) == (403, 403)
    assert FakeService.calls == []


async def test_ncr_passes_the_locale(monkeypatch: pytest.MonkeyPatch) -> None:
    async with await _client(_app("admin"), monkeypatch) as c:
        r = await c.post(f"/api/v1/setting-out/records/{REC.id}/ncr?locale=de")
    assert r.status_code == 201
    assert FakeService.calls == ["ncr:de"]


async def test_sheet_is_a_pdf_attachment(monkeypatch: pytest.MonkeyPatch) -> None:
    async with await _client(_app("admin"), monkeypatch) as c:
        r = await c.get(f"/api/v1/setting-out/requests/{REQ.id}/sheet.pdf")
        missing = await c.get(f"/api/v1/setting-out/requests/{uuid.uuid4()}/sheet.pdf")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert 'filename="setting-out-SO-001.pdf"' in r.headers["content-disposition"]
    assert missing.status_code == 404


async def test_record_body_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    async with await _client(_app("admin"), monkeypatch) as c:
        r = await c.post(f"/api/v1/setting-out/stakes/{STAKE.id}/records", json={"measured_e": "x"})
    assert r.status_code == 422
