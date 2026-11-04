"""Promoting a request over HTTP commits the agreed amount, not the headline estimate."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.variations import router as r


class _Svc:
    def __init__(self, vr):
        self.vr = vr
        self.payload = None

    async def get_request(self, _id):
        return self.vr

    async def convert_vr_to_vo(self, _id, payload, user_id=None):
        self.payload = payload
        raise RuntimeError("stop")


async def _run(monkeypatch, vr, body):
    async def _ok(*a, **k):
        return None

    async def _thr(*a, **k):
        return Decimal("1000000")

    monkeypatch.setattr(r, "verify_project_access", _ok)
    monkeypatch.setattr(r, "project_high_value_threshold", _thr)
    svc = _Svc(vr)
    with pytest.raises(RuntimeError):
        await r.convert_vr_to_vo(
            vr_id=uuid.uuid4(), session=None, user_id="u", user_payload={"role": "admin"}, body=body, service=svc
        )
    return svc.payload


def _vr(agreed):
    return SimpleNamespace(
        project_id=uuid.uuid4(),
        title="t",
        estimated_cost_impact=Decimal("100000"),
        agreed_cost_impact=agreed,
        estimated_schedule_days=3,
        currency="EUR",
    )


@pytest.mark.asyncio
async def test_agreed_amount_wins_over_estimate(monkeypatch):
    p = await _run(monkeypatch, _vr(Decimal("60000")), r._ConvertVOBody())
    assert p.final_cost_impact == Decimal("60000")


@pytest.mark.asyncio
async def test_estimate_is_fallback_when_nothing_agreed(monkeypatch):
    p = await _run(monkeypatch, _vr(None), r._ConvertVOBody())
    assert p.final_cost_impact == Decimal("100000")
