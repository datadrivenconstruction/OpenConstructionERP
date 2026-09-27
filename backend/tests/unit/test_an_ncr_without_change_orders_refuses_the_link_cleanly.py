# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Linking an NCR to a change order with the change orders module off is a 400, not a 500.

``_check_change_order`` imported the change orders model with no guard, so on
an install where that module is disabled or not installed a write naming a
change order failed on the import or on a table never created. It now says
the link cannot be made.
"""

from __future__ import annotations

import sys
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.core.module_loader import module_loader
from app.modules.ncr.service import NCRService

pytestmark = pytest.mark.asyncio


def _service() -> tuple[NCRService, AsyncMock]:
    svc = NCRService.__new__(NCRService)
    scalar = AsyncMock()
    svc.session = SimpleNamespace(scalar=scalar)
    return svc, scalar


async def test_a_disabled_change_orders_module_refuses_the_link(monkeypatch) -> None:
    monkeypatch.setattr(module_loader, "_modules", {"oe_ncr": object()})
    monkeypatch.setattr(module_loader, "is_enabled", lambda name: name != "oe_changeorders")
    svc, scalar = _service()

    with pytest.raises(HTTPException) as caught:
        await svc._check_change_order(uuid.uuid4(), str(uuid.uuid4()))

    assert caught.value.status_code == 400
    assert "not enabled" in caught.value.detail
    scalar.assert_not_awaited()


async def test_a_missing_change_orders_module_refuses_the_link(monkeypatch) -> None:
    monkeypatch.setattr(module_loader, "_modules", {})
    monkeypatch.setitem(sys.modules, "app.modules.changeorders.models", None)
    svc, scalar = _service()

    with pytest.raises(HTTPException) as caught:
        await svc._check_change_order(uuid.uuid4(), str(uuid.uuid4()))

    assert caught.value.status_code == 400
    scalar.assert_not_awaited()
