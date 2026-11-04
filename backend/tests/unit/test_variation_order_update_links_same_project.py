"""PATCH of a variation order cannot link a change order or contract from another project."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.variations.schemas import VariationOrderUpdate
from app.modules.variations.service import VariationsService


def _svc(project_id, owner):
    svc = VariationsService.__new__(VariationsService)
    vo = SimpleNamespace(id=uuid.uuid4(), project_id=project_id, status="issued", ball_in_court=None, code="VO-1")
    updated = {}

    async def get_order(_id):
        return vo

    async def update_fields(_id, **kw):
        updated.update(kw)

    async def refresh(_o):
        return None

    async def scalar(_stmt):
        return owner

    svc.get_order = get_order
    svc.vo_repo = SimpleNamespace(update_fields=update_fields)
    svc.session = SimpleNamespace(scalar=scalar, refresh=refresh)
    return svc, vo, updated


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["reference_change_order_id", "affected_contract_id"])
async def test_update_rejects_link_from_other_project(field):
    svc, vo, updated = _svc(uuid.uuid4(), uuid.uuid4())
    with pytest.raises(HTTPException) as e:
        await svc.update_order(vo.id, VariationOrderUpdate(**{field: uuid.uuid4()}))
    assert e.value.status_code == 422
    assert not updated


@pytest.mark.asyncio
@pytest.mark.parametrize("owner_missing", [False, True])
async def test_update_accepts_same_project_and_rejects_missing(owner_missing):
    pid = uuid.uuid4()
    svc, vo, updated = _svc(pid, None if owner_missing else pid)
    data = VariationOrderUpdate(affected_contract_id=uuid.uuid4())
    if owner_missing:
        with pytest.raises(HTTPException):
            await svc.update_order(vo.id, data)
    else:
        await svc.update_order(vo.id, data)
        assert "affected_contract_id" in updated
