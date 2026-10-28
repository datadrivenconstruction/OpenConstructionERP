# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the capture endpoints' JWT-or-API-key authorization gate.

Pure (no DB, no app, no network): exercises
:class:`app.dependencies.RequirePermissionOrApiKey` directly. Proves that an
interactive JWT caller is gated exactly like ``RequirePermission`` (admin
bypass, permission-in-token, stale-token live-registry fallback, and 403 when
the role lacks the permission), that a headless caller with no bearer token is
authenticated via ``X-API-Key`` and held to the same permission, and that a bad
or expired API key's own 401 propagates unchanged.

The keys here all declare an empty scope list, which narrows nothing - that is
the shape every key issued so far has, so these tests pin that the scoping
added later left the existing behaviour alone. The narrowing itself is covered
in ``tests/unit/test_api_key_scopes.py``.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

import app.core.permissions as core_perms
from app import dependencies as deps
from app.dependencies import RequirePermissionOrApiKey

PERMISSION = "inbound.write"


class _FakeUser:
    """Minimal stand-in for the User row an API key resolves to."""

    def __init__(self, user_id: str, role: str) -> None:
        self.id = user_id
        self.role = role


class _FakeRequest:
    """The API-key path is monkeypatched, so a bare object is enough here."""


def _grant(monkeypatch: pytest.MonkeyPatch, granted_role: str | None) -> None:
    """Stub the live permission registry: only ``granted_role`` holds PERMISSION."""
    monkeypatch.setattr(
        core_perms.permission_registry,
        "role_has_permission",
        lambda role, perm: role == granted_role and perm == PERMISSION,
    )


def _use_api_key_user(
    monkeypatch: pytest.MonkeyPatch,
    user: _FakeUser | None,
    scopes: list[str] | None = None,
) -> None:
    """Stub the API-key resolver with ``user`` + ``scopes`` (or raise its 401).

    ``scopes`` is the key row's own permission list, which narrows what the
    owner may do through this key. It defaults to empty, meaning the key
    declares no narrowing - the shape every key issued so far actually has.
    """

    async def _resolve(_request: object) -> deps.ApiKeyPrincipal:
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return deps.ApiKeyPrincipal(user=user, scopes=list(scopes or []))

    monkeypatch.setattr(deps, "resolve_api_key_principal", _resolve)


# --- _authorize: the shared role->permission check --------------------------


def test_authorize_admin_bypasses() -> None:
    # Admin passes even with an empty permission list and no registry grant.
    RequirePermissionOrApiKey(PERMISSION)._authorize("admin", [])


def test_authorize_accepts_permission_in_jwt_list() -> None:
    RequirePermissionOrApiKey(PERMISSION)._authorize("editor", [PERMISSION])


def test_authorize_registry_fallback_for_stale_jwt(monkeypatch: pytest.MonkeyPatch) -> None:
    _grant(monkeypatch, "editor")
    # Token list lacks the permission (stale JWT) but the live registry grants
    # it to the role, so it still passes (issue #101 behavior preserved).
    RequirePermissionOrApiKey(PERMISSION)._authorize("editor", [])


def test_authorize_denied_raises_403(monkeypatch: pytest.MonkeyPatch) -> None:
    _grant(monkeypatch, granted_role=None)
    with pytest.raises(HTTPException) as exc:
        RequirePermissionOrApiKey(PERMISSION)._authorize("viewer", ["inbound.read"])
    assert exc.value.status_code == 403


# --- __call__: JWT (interactive) path ---------------------------------------


def test_jwt_with_permission_returns_subject() -> None:
    gate = RequirePermissionOrApiKey(PERMISSION)
    payload = {"sub": "user-1", "role": "editor", "permissions": [PERMISSION]}
    assert asyncio.run(gate(_FakeRequest(), payload)) == "user-1"


def test_jwt_admin_bypass_returns_subject() -> None:
    gate = RequirePermissionOrApiKey(PERMISSION)
    payload = {"sub": "admin-1", "role": "admin", "permissions": []}
    assert asyncio.run(gate(_FakeRequest(), payload)) == "admin-1"


def test_jwt_stale_token_registry_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    _grant(monkeypatch, "editor")
    gate = RequirePermissionOrApiKey(PERMISSION)
    payload = {"sub": "user-2", "role": "editor", "permissions": []}
    assert asyncio.run(gate(_FakeRequest(), payload)) == "user-2"


def test_jwt_without_permission_raises_403(monkeypatch: pytest.MonkeyPatch) -> None:
    _grant(monkeypatch, granted_role=None)
    gate = RequirePermissionOrApiKey(PERMISSION)
    payload = {"sub": "user-3", "role": "viewer", "permissions": ["inbound.read"]}
    with pytest.raises(HTTPException) as exc:
        asyncio.run(gate(_FakeRequest(), payload))
    assert exc.value.status_code == 403


# --- __call__: X-API-Key (headless) path ------------------------------------


def test_api_key_with_permission_returns_owner_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_api_key_user(monkeypatch, _FakeUser("key-owner-1", "editor"))
    _grant(monkeypatch, "editor")
    gate = RequirePermissionOrApiKey(PERMISSION)
    # No JWT payload -> the gate falls back to the resolved API-key user.
    assert asyncio.run(gate(_FakeRequest(), None)) == "key-owner-1"


def test_api_key_without_permission_raises_403(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_api_key_user(monkeypatch, _FakeUser("key-owner-2", "viewer"))
    _grant(monkeypatch, granted_role=None)
    gate = RequirePermissionOrApiKey(PERMISSION)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(gate(_FakeRequest(), None))
    assert exc.value.status_code == 403


def test_bad_api_key_401_propagates(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_api_key_user(monkeypatch, None)  # resolver raises its own 401
    gate = RequirePermissionOrApiKey(PERMISSION)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(gate(_FakeRequest(), None))
    assert exc.value.status_code == 401
