# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the inbound-capture JWT-or-API-key auth seam.

Pure (no DB, no ASGI/TestClient): exercises :func:`resolve_capture_caller` and
:func:`_check_inbound_write` directly with constructed payload / request
stand-ins, the same style ``test_inbound_capture_signature.py`` uses for the
signature seam. Proves: a JWT payload with the permission (or role=admin)
resolves to its ``sub``; a JWT payload missing the permission is rejected even
via the live-registry fallback for a role that genuinely lacks it; no
JWT + no ``X-API-Key`` header is 401; and an ``X-API-Key`` header resolves
through :func:`app.dependencies.get_user_from_api_key` (mocked here) with the
identical permission gate applied to the resolved user's role.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest
from fastapi import HTTPException

from app.modules.inbound_capture import router as inbound_router
from app.modules.inbound_capture.permissions import register_inbound_capture_permissions
from app.modules.inbound_capture.router import resolve_capture_caller

# Registering is idempotent (a dict update keyed by permission string), so it
# is safe to call unconditionally rather than depend on app startup order.
register_inbound_capture_permissions()


class _StubRequest:
    """Minimal stand-in for starlette Request: only ``.headers`` is touched."""

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}


@dataclass
class _FakeUser:
    id: uuid.UUID
    role: str


# --- JWT path -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_jwt_payload_with_permission_resolves_sub() -> None:
    payload = {"sub": "user-1", "role": "editor", "permissions": ["inbound.write"]}
    user_id = await resolve_capture_caller(_StubRequest(), payload)
    assert user_id == "user-1"


@pytest.mark.asyncio
async def test_jwt_admin_bypasses_permission_list() -> None:
    payload = {"sub": "user-2", "role": "admin", "permissions": []}
    user_id = await resolve_capture_caller(_StubRequest(), payload)
    assert user_id == "user-2"


@pytest.mark.asyncio
async def test_jwt_falls_back_to_live_registry_for_stale_permissions_list() -> None:
    # "editor" genuinely has inbound.write in the live registry even though
    # this stale-looking payload's own permissions list doesn't carry it -
    # mirrors RequirePermission's Issue #101 fallback for a JWT issued before
    # a permission was added to the role.
    payload = {"sub": "user-3", "role": "editor", "permissions": []}
    user_id = await resolve_capture_caller(_StubRequest(), payload)
    assert user_id == "user-3"


@pytest.mark.asyncio
async def test_jwt_without_permission_is_rejected() -> None:
    payload = {"sub": "user-4", "role": "viewer", "permissions": []}
    with pytest.raises(HTTPException) as exc:
        await resolve_capture_caller(_StubRequest(), payload)
    assert exc.value.status_code == 403


# --- No credential --------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_jwt_and_no_api_key_header_is_401() -> None:
    with pytest.raises(HTTPException) as exc:
        await resolve_capture_caller(_StubRequest(), None)
    assert exc.value.status_code == 401


# --- API-key path (machine caller) ---------------------------------------------


@pytest.mark.asyncio
async def test_api_key_header_resolves_user_with_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_user = _FakeUser(id=uuid.uuid4(), role="editor")

    async def _fake_get_user_from_api_key(request: object) -> _FakeUser:
        return fake_user

    monkeypatch.setattr(inbound_router, "get_user_from_api_key", _fake_get_user_from_api_key)

    user_id = await resolve_capture_caller(_StubRequest({"X-API-Key": "sk_live_whatever"}), None)
    assert user_id == str(fake_user.id)


@pytest.mark.asyncio
async def test_api_key_header_rejects_user_without_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_user = _FakeUser(id=uuid.uuid4(), role="viewer")

    async def _fake_get_user_from_api_key(request: object) -> _FakeUser:
        return fake_user

    monkeypatch.setattr(inbound_router, "get_user_from_api_key", _fake_get_user_from_api_key)

    with pytest.raises(HTTPException) as exc:
        await resolve_capture_caller(_StubRequest({"X-API-Key": "sk_live_whatever"}), None)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_api_key_lookup_failure_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    """An invalid/expired key must surface get_user_from_api_key's own 401, not be swallowed."""

    async def _fake_get_user_from_api_key(request: object) -> None:
        raise HTTPException(status_code=401, detail="Invalid API key")

    monkeypatch.setattr(inbound_router, "get_user_from_api_key", _fake_get_user_from_api_key)

    with pytest.raises(HTTPException) as exc:
        await resolve_capture_caller(_StubRequest({"X-API-Key": "bad-key"}), None)
    assert exc.value.status_code == 401
