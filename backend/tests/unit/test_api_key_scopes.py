# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for API-key permission scoping.

An ``APIKey`` row carries a ``permissions`` list that was written at creation
and read by nothing. These tests pin the rule that now reads it: the authority
of a request authenticated by an API key is the INTERSECTION of the owner's
live permissions and the key's declared list, so a key can be held below its
owner but never raised above them, and an empty list narrows nothing.

Two behaviours here would have passed against the pre-fix code and must not be
allowed to regress quietly:

* the narrowing is applied BEFORE the admin bypass, so an admin-owned key is
  narrowable at all - the case the column exists for;
* the ICS calendar feed, whose credential rides in a subscription URL, demands
  its scope be named outright and refuses a general-purpose key.

Pure: no DB, no app, no network. The calendar route is driven directly over a
stand-in session, and ``verify_project_access`` is replaced with a sentinel so
"the scope gate let this through" is observable without building a real project.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import HTTPException

import app.core.permissions as core_perms
from app import dependencies as deps
from app.dependencies import ApiKeyPrincipal, RequirePermissionOrApiKey, key_scopes_allow
from app.modules.integrations import router as integrations_router
from app.modules.integrations.permissions import (
    CALENDAR_FEED_PERMISSION,
    register_integrations_permissions,
)

PERMISSION = "inbound.write"
OTHER_PERMISSION = "inbound.read"


class _FakeUser:
    """Stand-in for the User row an API key resolves to."""

    def __init__(self, user_id: str, role: str, *, is_active: bool = True) -> None:
        self.id = user_id
        self.role = role
        self.is_active = is_active


class _FakeRequest:
    """The API-key resolver is monkeypatched, so a bare object is enough."""


def _grant(monkeypatch: pytest.MonkeyPatch, granted_role: str | None) -> None:
    """Stub the live registry: only ``granted_role`` holds PERMISSION."""
    monkeypatch.setattr(
        core_perms.permission_registry,
        "role_has_permission",
        lambda role, perm: role == granted_role and perm == PERMISSION,
    )


def _use_key(
    monkeypatch: pytest.MonkeyPatch,
    user: _FakeUser,
    scopes: list[str] | None = None,
) -> None:
    """Stub the API-key resolver with an owner and the key's declared scopes."""

    async def _resolve(_request: object) -> ApiKeyPrincipal:
        return ApiKeyPrincipal(user=user, scopes=list(scopes or []))

    monkeypatch.setattr(deps, "resolve_api_key_principal", _resolve)


# --- key_scopes_allow: the narrowing rule on its own ------------------------


def test_empty_list_narrows_nothing() -> None:
    # The shape every key issued before this change actually has.
    assert key_scopes_allow([], PERMISSION) is True


def test_missing_list_narrows_nothing() -> None:
    assert key_scopes_allow(None, PERMISSION) is True


def test_declared_permission_passes() -> None:
    assert key_scopes_allow([PERMISSION, OTHER_PERMISSION], PERMISSION) is True


def test_undeclared_permission_is_refused() -> None:
    assert key_scopes_allow([OTHER_PERMISSION], PERMISSION) is False


def test_require_declared_drops_the_empty_list_escape() -> None:
    # A route may demand the scope be named; "narrows nothing" stops being a pass.
    assert key_scopes_allow([], PERMISSION, require_declared=True) is False
    assert key_scopes_allow(None, PERMISSION, require_declared=True) is False
    assert key_scopes_allow([PERMISSION], PERMISSION, require_declared=True) is True


# --- the intersection, through the gate that decides ------------------------


def test_narrow_key_refused_outside_its_list(monkeypatch: pytest.MonkeyPatch) -> None:
    # Owner's role grants the permission; the key does not declare it. The
    # intersection is empty, so the request is refused even though the same
    # human calling with a browser session would be allowed.
    _grant(monkeypatch, "editor")
    _use_key(monkeypatch, _FakeUser("owner-1", "editor"), scopes=[OTHER_PERMISSION])
    gate = RequirePermissionOrApiKey(PERMISSION)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(gate(_FakeRequest(), None))
    assert exc.value.status_code == 403


def test_narrow_key_allowed_inside_its_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _grant(monkeypatch, "editor")
    _use_key(monkeypatch, _FakeUser("owner-2", "editor"), scopes=[PERMISSION])
    gate = RequirePermissionOrApiKey(PERMISSION)
    assert asyncio.run(gate(_FakeRequest(), None)) == "owner-2"


def test_empty_key_list_behaves_exactly_as_before(monkeypatch: pytest.MonkeyPatch) -> None:
    # No narrowing declared, so the decision rests entirely on the owner's role,
    # which is what every existing key does today.
    _grant(monkeypatch, "editor")
    _use_key(monkeypatch, _FakeUser("owner-3", "editor"), scopes=[])
    gate = RequirePermissionOrApiKey(PERMISSION)
    assert asyncio.run(gate(_FakeRequest(), None)) == "owner-3"


def test_key_cannot_grant_what_the_owner_lacks(monkeypatch: pytest.MonkeyPatch) -> None:
    # The declared list only ever subtracts. A viewer's key that names a
    # permission the viewer's role does not hold is still refused - otherwise
    # self-service key creation would be privilege escalation.
    _grant(monkeypatch, granted_role=None)
    _use_key(monkeypatch, _FakeUser("owner-4", "viewer"), scopes=[PERMISSION])
    gate = RequirePermissionOrApiKey(PERMISSION)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(gate(_FakeRequest(), None))
    assert exc.value.status_code == 403


# --- the admin case, which is the reason the column exists ------------------


def test_admin_owned_key_is_narrowed_by_its_list(monkeypatch: pytest.MonkeyPatch) -> None:
    # The ordering test. The admin bypass returns unconditionally, so a
    # narrowing check placed after it would never run and this key would reach
    # everything its owner does. It has to run first.
    _grant(monkeypatch, granted_role=None)
    _use_key(monkeypatch, _FakeUser("admin-1", "admin"), scopes=[OTHER_PERMISSION])
    gate = RequirePermissionOrApiKey(PERMISSION)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(gate(_FakeRequest(), None))
    assert exc.value.status_code == 403


def test_admin_owned_key_still_passes_inside_its_list(monkeypatch: pytest.MonkeyPatch) -> None:
    _grant(monkeypatch, granted_role=None)
    _use_key(monkeypatch, _FakeUser("admin-2", "admin"), scopes=[PERMISSION])
    gate = RequirePermissionOrApiKey(PERMISSION)
    assert asyncio.run(gate(_FakeRequest(), None)) == "admin-2"


def test_admin_owned_key_without_a_list_is_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    # No declared list means no narrowing, for admins too. Existing keys keep
    # working exactly as they do today.
    _grant(monkeypatch, granted_role=None)
    _use_key(monkeypatch, _FakeUser("admin-3", "admin"), scopes=[])
    gate = RequirePermissionOrApiKey(PERMISSION)
    assert asyncio.run(gate(_FakeRequest(), None)) == "admin-3"


def test_jwt_caller_is_untouched_by_the_narrowing(monkeypatch: pytest.MonkeyPatch) -> None:
    # A bearer caller presents no key, so no list can narrow them. The JWT list
    # keeps its opposite polarity: present in the token means granted.
    _grant(monkeypatch, granted_role=None)
    gate = RequirePermissionOrApiKey(PERMISSION)
    payload = {"sub": "jwt-1", "role": "editor", "permissions": [PERMISSION]}
    assert asyncio.run(gate(_FakeRequest(), payload)) == "jwt-1"


# --- the ICS calendar feed --------------------------------------------------


class _FakeScalars:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def first(self) -> object | None:
        return self._rows[0] if self._rows else None


class _FakeResult:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def scalars(self) -> _FakeScalars:
        return _FakeScalars(self._rows)


class _FakeKey:
    """Stand-in for the APIKey row the feed looks up by token hash."""

    def __init__(self, owner_id: str, permissions: list[str]) -> None:
        self.user_id = owner_id
        self.permissions = permissions
        self.expires_at = None


class _FakeSession:
    """Answers the feed's two reads: the key by hash, then its owner."""

    def __init__(self, key: _FakeKey | None, owner: _FakeUser | None) -> None:
        self._key = key
        self._owner = owner

    async def execute(self, _stmt: object) -> _FakeResult:
        return _FakeResult([self._key] if self._key is not None else [])

    async def get(self, _model: object, _pk: object) -> _FakeUser | None:
        return self._owner


class _ReachedProjectAccess(Exception):
    """Sentinel proving the scope gate passed control to the project guard."""


@pytest.fixture(autouse=True)
def _registered_permissions() -> None:
    """The feed asks the registry, which only knows scopes a module registered.

    An unregistered permission is "unknown -> deny" for every non-admin role, so
    without this the feed would refuse a correctly scoped viewer's key and the
    test would pass for the wrong reason.
    """
    register_integrations_permissions()


def _run_feed(
    scopes: list[str],
    role: str = "viewer",
    *,
    active: bool = True,
    reached: list[object] | None = None,
) -> str:
    """Drive the real route with a key carrying ``scopes``.

    Raises whatever the route raises. On the allowed path that is
    :class:`_ReachedProjectAccess`, since the project guard is the next step.
    ``reached`` collects one entry if the project guard was consulted at all.
    """
    owner = _FakeUser(str(uuid.uuid4()), role, is_active=active)
    key = _FakeKey(owner.id, scopes)
    session = _FakeSession(key, owner)
    log = reached if reached is not None else []

    async def _boom(*_args: object, **_kwargs: object) -> None:
        log.append(True)
        raise _ReachedProjectAccess

    original = deps.verify_project_access
    deps.verify_project_access = _boom  # type: ignore[assignment]
    try:
        return asyncio.run(
            integrations_router.calendar_feed(
                project_id=uuid.uuid4(),
                session=session,  # type: ignore[arg-type]
                token="a" * 40,
            )
        )
    finally:
        deps.verify_project_access = original  # type: ignore[assignment]


def test_calendar_feed_refuses_a_key_without_its_scope() -> None:
    # A general-purpose key - the only kind that exists today - does not open
    # the feed merely by existing.
    with pytest.raises(HTTPException) as exc:
        _run_feed([])
    assert exc.value.status_code == 403
    assert CALENDAR_FEED_PERMISSION in exc.value.detail


def test_calendar_feed_refuses_a_key_scoped_to_something_else() -> None:
    with pytest.raises(HTTPException) as exc:
        _run_feed(["integrations.read"])
    assert exc.value.status_code == 403


def test_calendar_feed_accepts_a_key_that_declares_the_scope() -> None:
    # Reaching the project guard is the pass condition: the scope gate is the
    # step before it, so the sentinel can only fire once the gate let it by.
    with pytest.raises(_ReachedProjectAccess):
        _run_feed([CALENDAR_FEED_PERMISSION])


def test_calendar_feed_refuses_a_deactivated_owners_key() -> None:
    # The key row stays is_active while the account behind it is switched off,
    # so the owner has to be checked separately.
    with pytest.raises(HTTPException) as exc:
        _run_feed([CALENDAR_FEED_PERMISSION], active=False)
    assert exc.value.status_code == 401


def test_calendar_feed_admin_key_still_needs_the_scope() -> None:
    # Admin bypasses the registry, never the key's declared list.
    with pytest.raises(HTTPException) as exc:
        _run_feed([], role="admin")
    assert exc.value.status_code == 403


def test_calendar_feed_refusal_never_reads_the_project() -> None:
    """The scope 403 is not a UUID-existence oracle.

    A 403 leaks only when its answer depends on the row: "exists but not
    yours" is distinguishable from "does not exist". This refusal is decided
    from the credential alone, so it answers identically for a real project id
    and a made-up one, which is why the integrations router may carry it
    without becoming a UUID-existence oracle (see TestIDORShape in
    tests/modules/test_integrations_security.py).
    """
    reached: list[object] = []
    with pytest.raises(HTTPException) as exc:
        _run_feed([], reached=reached)
    assert exc.value.status_code == 403
    assert reached == [], "the refusal consulted the project, so it can leak whether it exists"
