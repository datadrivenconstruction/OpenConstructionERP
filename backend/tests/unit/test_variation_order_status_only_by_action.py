"""A variation order changes status only through its actions, and a new one is issued."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.variations import router as r
from app.modules.variations.schemas import VariationOrderCreate, VariationOrderUpdate
from app.modules.variations.service import VariationsService


class _Repo:
    def __init__(self, vo):
        self.vo = vo
        self.written = None

    async def get_by_id(self, _id):
        return self.vo

    async def update_fields(self, _id, **f):
        self.written = f


class _Sess:
    async def refresh(self, _o):
        return None


def _svc(status="issued"):
    vo = SimpleNamespace(id=uuid.uuid4(), status=status, ball_in_court=None, code="VO-1")
    svc = VariationsService.__new__(VariationsService)
    svc.vo_repo = _Repo(vo)
    svc.session = _Sess()
    return svc


@pytest.mark.asyncio
async def test_patch_cannot_complete_an_order():
    svc = _svc()
    with pytest.raises(HTTPException) as e:
        await svc.update_order(svc.vo_repo.vo.id, VariationOrderUpdate(status="completed"))
    assert e.value.status_code == 422
    assert svc.vo_repo.written is None


@pytest.mark.asyncio
async def test_patch_may_resend_the_current_status():
    svc = _svc()
    await svc.update_order(svc.vo_repo.vo.id, VariationOrderUpdate(status="issued", title="x"))
    assert svc.vo_repo.written == {"title": "x"}


@pytest.mark.asyncio
async def test_create_route_refuses_a_preset_status(monkeypatch):
    async def _ok(*a, **k):
        return None

    monkeypatch.setattr(r, "verify_project_access", _ok)
    data = VariationOrderCreate(project_id=uuid.uuid4(), status="completed")
    with pytest.raises(HTTPException) as e:
        await r.create_variation_order(data=data, user_id="u", user_payload={}, session=None, service=None)
    assert e.value.status_code == 422


@pytest.mark.asyncio
async def test_create_route_applies_the_high_value_gate(monkeypatch):
    async def _ok(*a, **k):
        return None

    async def _thr(*a, **k):
        return Decimal("1000")

    monkeypatch.setattr(r, "verify_project_access", _ok)
    monkeypatch.setattr(r, "project_high_value_threshold", _thr)
    data = VariationOrderCreate(project_id=uuid.uuid4(), final_cost_impact=Decimal("5000"))
    with pytest.raises(HTTPException) as e:
        await r.create_variation_order(
            data=data, user_id="u", user_payload={"role": "manager", "permissions": []}, session=None, service=None
        )
    assert e.value.status_code == 403
