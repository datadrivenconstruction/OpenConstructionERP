"""A variation order cannot be created against another project's variation request."""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.modules.variations.schemas import VariationOrderCreate
from app.modules.variations.service import VariationsService


@pytest.mark.asyncio
async def test_create_order_rejects_request_from_other_project():
    pid = uuid.uuid4()
    vr = SimpleNamespace(project_id=uuid.uuid4(), contract_standard="FIDIC", contract_clause_ref="13.3")
    svc = VariationsService.__new__(VariationsService)

    async def get_request(_id):
        return vr

    svc.get_request = get_request
    svc.vo_repo = SimpleNamespace(next_code=lambda _p: _code())
    data = VariationOrderCreate(project_id=pid, title="x", variation_request_id=uuid.uuid4())
    with pytest.raises(HTTPException) as e:
        await svc.create_order(data, user_id="u")
    assert e.value.status_code == 422


async def _code():
    return "VO-1"
