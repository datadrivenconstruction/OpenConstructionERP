# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the Phase 1 tenant-scope scaffolding.

These pin the *resolution policy* of :mod:`app.core.tenant_scope` so the
multi-tenant hardening that builds on it (Phase 2 onwards) has a stable,
documented contract:

* the tenant is the explicit ``tenant_id`` claim when present, else the
  JWT ``sub`` (single-tenant installs: tenant == user), else ``None``;
* the resolver is total and never raises (anonymous / malformed payloads
  collapse to ``None`` rather than blowing up a request);
* :func:`tenant_scope_owner` reproduces the established
  ``None if admin else tenant`` filter and fails *closed* (a non-admin /
  unknown caller stays scoped, never widened to all rows).

The pure resolver tests run everywhere (the module imports no DB). The
admin-bypass tests stub :func:`app.core.tenant_scope._is_admin` so they
stay pure too - they assert the *branching*, not the DB lookup, which is
exercised by the integration suite (``tests/integration/test_tenant_isolation.py``).
"""

from __future__ import annotations

import pytest

from app.core.tenant_scope import (
    SUBJECT_CLAIM,
    TENANT_CLAIM,
    resolve_tenant_id,
    tenant_scope_owner,
)

# ── resolve_tenant_id: pure resolution policy ───────────────────────────────


def test_none_payload_resolves_to_none() -> None:
    """An anonymous caller (no payload) must yield None, not raise."""
    assert resolve_tenant_id(None) is None


def test_empty_payload_resolves_to_none() -> None:
    """A payload with neither claim resolves to None."""
    assert resolve_tenant_id({}) is None


def test_sub_only_resolves_to_sub() -> None:
    """With no tenant claim, the user id (sub) is the tenant.

    This is the single-tenant install shape shipped today and matches the
    value stored in ``Contact.tenant_id`` / ``Snapshot.tenant_id``.
    """
    assert resolve_tenant_id({SUBJECT_CLAIM: "user-123"}) == "user-123"


def test_tenant_claim_takes_priority_over_sub() -> None:
    """An explicit tenant_id claim wins over sub (forward compatibility).

    The day a real Tenants table + a ``tenant_id`` claim ship, this
    resolver starts returning the org id with no call-site changes.
    """
    payload = {SUBJECT_CLAIM: "user-123", TENANT_CLAIM: "org-9"}
    assert resolve_tenant_id(payload) == "org-9"


def test_blank_tenant_claim_falls_back_to_sub() -> None:
    """A present-but-blank tenant claim must not shadow a real sub."""
    payload = {SUBJECT_CLAIM: "user-123", TENANT_CLAIM: "   "}
    assert resolve_tenant_id(payload) == "user-123"


def test_blank_sub_resolves_to_none() -> None:
    """A whitespace-only sub is not a usable tenant id."""
    assert resolve_tenant_id({SUBJECT_CLAIM: "   "}) is None


def test_non_string_claims_are_coerced() -> None:
    """Numeric claims (some IdPs emit int sub) are coerced to str."""
    assert resolve_tenant_id({SUBJECT_CLAIM: 42}) == "42"
    assert resolve_tenant_id({TENANT_CLAIM: 7, SUBJECT_CLAIM: 42}) == "7"


def test_tenant_claim_surrounding_whitespace_is_stripped() -> None:
    """A real tenant id with stray whitespace is trimmed, not rejected."""
    assert resolve_tenant_id({TENANT_CLAIM: "  org-9  "}) == "org-9"


def test_zero_like_string_sub_is_preserved() -> None:
    """A falsy-looking but non-empty id ('0') is a valid tenant, not None."""
    assert resolve_tenant_id({SUBJECT_CLAIM: "0"}) == "0"


# ── tenant_scope_owner: admin-bypass branching (DB lookup stubbed) ──────────


class _SentinelSession:
    """Stand-in for an AsyncSession - never touched because _is_admin is stubbed."""


@pytest.mark.asyncio
async def test_owner_filter_none_tenant_short_circuits(monkeypatch) -> None:
    """A None tenant returns None without ever consulting the DB."""

    async def _boom(_session, _user_id):  # pragma: no cover - must not run
        raise AssertionError("_is_admin must not be called for a None tenant")

    monkeypatch.setattr("app.core.tenant_scope._is_admin", _boom)
    assert await tenant_scope_owner(_SentinelSession(), None) is None


@pytest.mark.asyncio
async def test_owner_filter_admin_is_unrestricted(monkeypatch) -> None:
    """An admin caller maps to None (= 'do not filter'), mirroring projects."""

    async def _is_admin_true(_session, _user_id):
        return True

    monkeypatch.setattr("app.core.tenant_scope._is_admin", _is_admin_true)
    assert await tenant_scope_owner(_SentinelSession(), "admin-user") is None


@pytest.mark.asyncio
async def test_owner_filter_non_admin_keeps_tenant(monkeypatch) -> None:
    """A normal user's query stays scoped to their own tenant id."""

    async def _is_admin_false(_session, _user_id):
        return False

    monkeypatch.setattr("app.core.tenant_scope._is_admin", _is_admin_false)
    assert await tenant_scope_owner(_SentinelSession(), "user-123") == "user-123"


# ── get_current_tenant_id: dependency delegates to the pure resolver ────────


@pytest.mark.asyncio
async def test_dependency_delegates_to_resolver() -> None:
    """The FastAPI dependency returns exactly resolve_tenant_id(payload).

    Lives in ``app.dependencies`` which imports the DB engine at module
    load, so this is skipped where the embedded PostgreSQL is not up
    (e.g. local py3.11 dev box) and exercised in CI.
    """
    try:
        from app.dependencies import get_current_tenant_id
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"app.dependencies not importable here (no DB engine): {exc}")

    assert await get_current_tenant_id(None) is None
    assert await get_current_tenant_id({"sub": "user-123"}) == "user-123"
    assert await get_current_tenant_id({"sub": "user-123", "tenant_id": "org-9"}) == "org-9"
