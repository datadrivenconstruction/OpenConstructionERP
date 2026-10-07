# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tenant-scope resolution (multi-tenant isolation, Phase 1 scaffolding).

This module centralizes "which tenant is the caller?" into one place so
that, as data-access layers are hardened module-by-module, they can all
ask the same question the same way instead of each re-deriving the owner
id from the JWT.

Current state (single-tenant installs - the only shape shipped today)
---------------------------------------------------------------------
There is **no separate Tenant/Org entity** and **no ``tenant_id`` claim
in the JWT**. The "tenant" is simply the owning user's id (the JWT
``sub``). This matches the existing on-disk convention:

* ``Contact.tenant_id`` is backfilled to ``created_by`` (the creator's
  user id) by migration ``v231_contact_tenant_id`` - see its docstring:
  *"For single-tenant installs ... it equals the creator's user id."*
* ``dashboards.Snapshot.tenant_id`` is written as ``str(user_id)``.

So resolving the tenant to ``payload["sub"]`` produces exactly the value
those columns already store, which is why wiring a future query through
:data:`CurrentTenantId` is behaviour-preserving rather than a new policy.

Forward compatibility
----------------------
:func:`resolve_tenant_id` prefers an explicit ``tenant_id`` claim when
one is present, falling back to ``sub`` only when it is absent. The day a
real Tenants table + a ``tenant_id`` claim land in
:func:`app.modules.users.service.create_access_token`, this resolver
starts returning the org id with **no call-site changes**.

NON-BREAKING GUARANTEE
----------------------
The FastAPI dependency :data:`CurrentTenantId` is wired in
:mod:`app.dependencies` on top of ``get_optional_user_payload``, which
returns ``None`` for anonymous / unknown callers instead of raising. The
dependency therefore:

* never adds a 401/403 to an endpoint that did not already have one, and
* returns ``None`` whenever the tenant cannot be determined.

A ``None`` tenant must be treated by callers as "do not narrow the query"
**only** where that is already the established admin/unrestricted policy;
on a tenant-gated endpoint a ``None`` should scope to nothing (the safe
default, mirroring :func:`app.dependencies.accessible_project_ids`). No
endpoint is changed by merely importing this module - it is plumbing plus
one or two reference usages until Phase 2 rolls it out per module.

This is the app-layer half of the multi-tenant plan. PostgreSQL-native
RLS is a later, optional phase and is disabled by default. PostgreSQL
superusers and BYPASSRLS roles bypass policies even with ``FORCE ROW LEVEL
SECURITY``; enforced requests therefore need a separate non-bypassing role.

Import safety
-------------
This module intentionally imports **nothing** from :mod:`app.dependencies`
or :mod:`app.database` at module load. The pure resolver
:func:`resolve_tenant_id` is therefore importable (and unit-testable) in
any environment, even where the embedded PostgreSQL engine is not yet up.
The request-time dependency is assembled in :mod:`app.dependencies`
(which already owns the DB-session plumbing), keeping the import edge
one-directional: ``dependencies -> tenant_scope`` only, never back.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# The JWT claim that will carry a real organisation/tenant id once
# multi-tenancy ships. Resolved with priority over ``sub`` so the switch
# is a pure data change (the login flow starts emitting the claim) with
# no edits at any call site.
TENANT_CLAIM = "tenant_id"
SUBJECT_CLAIM = "sub"


def resolve_tenant_id(payload: dict[str, Any] | None) -> str | None:
    """Resolve the caller's tenant id from a decoded JWT payload.

    Pure function (no I/O) so it is trivially unit-testable.

    Resolution order:
        1. Explicit ``tenant_id`` claim, when present and non-empty
           (forward-compatible with real multi-tenancy).
        2. ``sub`` (the user id) - the tenant *is* the user in the
           single-tenant installs shipped today, matching the value
           stored in ``Contact.tenant_id`` / ``Snapshot.tenant_id``.
        3. ``None`` when there is no payload or neither claim is usable
           (anonymous request) - callers must treat this safely and
           never widen to "all rows" off the back of it.

    Args:
        payload: Decoded JWT payload, or ``None`` for an anonymous caller.

    Returns:
        The tenant id as a string, or ``None`` when it cannot be resolved.
    """
    if not payload:
        return None

    raw_tenant = payload.get(TENANT_CLAIM)
    if raw_tenant is not None:
        tenant = str(raw_tenant).strip()
        if tenant:
            return tenant

    raw_sub = payload.get(SUBJECT_CLAIM)
    if raw_sub is not None:
        sub = str(raw_sub).strip()
        if sub:
            return sub

    return None


# The request-time FastAPI dependency ``get_current_tenant_id`` and its
# ``CurrentTenantId`` alias live in :mod:`app.dependencies` (alongside
# ``CurrentUserId`` / ``SessionDep``): that module already owns the
# ``get_optional_user_payload`` building block and the DB-session
# plumbing, so wiring the dependency there keeps this module free of any
# ``app.dependencies`` / ``app.database`` import and thus pure-importable.
# Both simply delegate to :func:`resolve_tenant_id` above.


async def tenant_scope_owner(
    session: AsyncSession,
    tenant_id: str | None,
) -> str | None:
    """Resolve the owner-scope filter for ``tenant_id``, honouring admin bypass.

    Centralises the ``owner_filter = None if admin else user_id`` idiom
    currently copy-pasted across routers (e.g. ``contacts.list_contacts``).
    Pass the result as the ``owner_id=`` argument of a repository method
    that knows how to apply (or skip) the tenant filter:

        tenant_id = await tenant_scope_owner(session, tenant_id)
        items, total = await repo.list(owner_id=tenant_id, ...)

    Returns:
        ``None`` when the caller is an admin (= "do not filter", the same
        unrestricted sentinel ``accessible_project_ids`` uses) **or** when
        ``tenant_id`` is already ``None``; otherwise the tenant id
        unchanged.

    Note the deliberate overload of ``None``: an anonymous caller and an
    admin both map to ``None`` here. That is correct for the
    *company-wide* resources this helper targets (contacts, subcontractors,
    supplier catalogs), where the repository's ``owner_id=None`` branch is
    the admin/unrestricted view and an anonymous caller never reaches the
    handler (a ``RequirePermission`` guard rejects them first). Do **not**
    use this helper to gate a per-row fetch - use
    :func:`app.dependencies.verify_project_access` (404-on-deny) for that.
    """
    if tenant_id is None:
        return None

    if await _is_admin(session, tenant_id):
        return None

    return tenant_id


async def _is_admin(session: AsyncSession, user_id: str | None) -> bool:
    """Return ``True`` when ``user_id`` resolves to an active admin user.

    Mirrors the admin-bypass check in
    :func:`app.dependencies.verify_project_access` /
    :func:`app.dependencies.accessible_project_ids`: a malformed id or a
    lookup failure fails *closed* (treated as non-admin -> the caller's
    query stays scoped) rather than silently granting an unfiltered view.

    Imports are function-local on purpose: importing the users repository
    (and through it ``app.database``) at module import time would open a
    PostgreSQL connection during collection and break the pure unit tests
    / non-PG environments. Every other auth helper in this codebase defers
    these imports the same way.
    """
    import uuid as _uuid

    from app.modules.users.repository import UserRepository

    if user_id is None:
        return False

    try:
        uid = _uuid.UUID(str(user_id))
    except (TypeError, ValueError):
        return False

    try:
        user = await UserRepository(session).get_by_id(uid)
    except Exception:
        logger.exception("Admin-role lookup failed during tenant-scope resolution")
        return False

    return user is not None and getattr(user, "role", "") == "admin"
