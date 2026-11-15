"""The read-only demo lets its visitor read what the menus show; writes stay refused."""

from __future__ import annotations

import importlib

import pytest
from fastapi import HTTPException

from app.core import demo_read_only
from app.core.demo_read_only import ALLOWED_ENDPOINTS, DEMO_READ_GRANTS
from app.dependencies import RequirePermission

_EDITOR = {"sub": "u1", "role": "editor", "permissions": []}


def test_grants_are_read_permissions_only() -> None:
    assert DEMO_READ_GRANTS
    assert all(p.endswith(".read") for p in DEMO_READ_GRANTS)


@pytest.mark.parametrize("key", sorted(ALLOWED_ENDPOINTS))
def test_allowlisted_endpoint_exists(key: str) -> None:
    module, _, name = key.partition(":")
    assert callable(getattr(importlib.import_module(module), name, None)), key


@pytest.mark.asyncio
async def test_demo_visitor_reads_granted_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo_read_only, "demo_read_only_enabled", lambda: True)
    await RequirePermission("accounting_sync.read")(_EDITOR)


@pytest.mark.asyncio
async def test_installation_keeps_the_role_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo_read_only, "demo_read_only_enabled", lambda: False)
    with pytest.raises(HTTPException) as err:
        await RequirePermission("accounting_sync.read")(_EDITOR)
    assert err.value.status_code == 403


@pytest.mark.asyncio
async def test_demo_does_not_grant_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(demo_read_only, "demo_read_only_enabled", lambda: True)
    with pytest.raises(HTTPException):
        await RequirePermission("accounting_sync.write")(_EDITOR)
