# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Row-level-security tenant plumbing (default OFF).

PostgreSQL row-level security is the backstop under the app-layer tenant
guards: even if a query forgets its ``tenant_id`` filter, the database refuses
to return or change another tenant's rows. It is enforced only when
``settings.rls_enforce`` is True, because the app otherwise connects as the
cluster superuser, and a superuser bypasses every policy. The flag is opt-in,
so this module is inert on a default install.

Mechanism, when enabled (single connection, no second engine):

* A per-request :class:`~contextvars.ContextVar` carries the caller's tenant.
  ``rls_request_context`` (in ``app.dependencies``) binds it at the top of a
  request and clears it at the end. The default is a private ``_UNSET`` sentinel
  so a background/out-of-request session (which never binds it) is
  distinguishable from an anonymous request (which binds ``None``).
* An ``after_begin`` listener runs on every transaction of the request session:
    - background session (``_UNSET``): do nothing, so the transaction keeps the
      connecting superuser role and bypasses RLS, exactly as before;
    - request session: ``SET LOCAL ROLE`` to the non-superuser runtime role so
      policies apply, then stamp a transaction-local ``app.current_tenant`` GUC.
      ``SET LOCAL`` is transaction-scoped, so it resets on commit and never
      contaminates the pooled connection; the listener re-applies it on the next
      transaction, so it survives mid-request commits.
* An anonymous request binds ``None`` -> empty GUC -> a fail-closed policy
  (``tenant_id = current_setting('app.current_tenant', true)``) matches no
  tenant rows, while global reference tables (never policied) stay readable.

Import-light (SQLAlchemy + settings only) so the database layer can import it
without a dependency cycle.
"""

from __future__ import annotations

import contextlib
import logging
from collections.abc import Sequence
from contextvars import ContextVar, Token
from typing import Any, Final

from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.config import get_settings

logger = logging.getLogger(__name__)

# The PostgreSQL run-time parameter the tenant policies read. A dotted,
# app-namespaced name is required for a custom GUC (a bare name is rejected by
# PostgreSQL as an unrecognised configuration parameter).
GUC_NAME: Final[str] = "app.current_tenant"

# Non-superuser runtime role that request transactions run as, so policies
# apply. Created idempotently by the migrator (see app.core.rls_setup). A
# hardcoded identifier - never interpolate user input into a SET ROLE.
APP_ROLE: Final[str] = "oe_app"

# BYPASSRLS role available for background work that must span tenants. Not used
# by the request path; documented here as the companion to APP_ROLE.
SYSTEM_ROLE: Final[str] = "oe_system"

# Distinguishes "no request bound this context" (background/system session ->
# keep the superuser role, bypass RLS) from "request bound an anonymous caller"
# (None -> downgrade role, empty tenant, fail closed).
_UNSET: Final = object()

# Per-request tenant, bound at request entry and read when a transaction begins.
_request_tenant: ContextVar[Any] = ContextVar("rls_request_tenant", default=_UNSET)

# Per-request list of project ids the caller's organization holds a live grant on
# (ADR 006). Bound beside the tenant by the same dependency and read by the same
# listener, so the two GUCs a two-arm policy needs are set together and never one
# without the other. A tuple of ids rather than a joined string: the listener does
# the joining, so no caller can bind a value that already contains the separator.
_request_granted_projects: ContextVar[Any] = ContextVar("rls_request_granted_projects", default=_UNSET)

# Guards one-time listener registration so a re-import (or a test that rebuilds
# the engine) does not stack duplicate listeners on the same Session class.
_installed: set[int] = set()


def rls_enabled() -> bool:
    """Return True when row-level-security enforcement is switched on.

    Reads the cached settings singleton. A settings failure must propagate:
    treating an unreadable flag as disabled would let request transactions
    retain the connecting role and silently bypass tenant policies. This also
    prevents background transactions from starting until settings recover.
    """
    return bool(get_settings().rls_enforce)


#: The GUC that carries the projects the caller's company was invited to. Set by
#: the same listener that sets :data:`GUC_NAME`, and read by the second policy
#: provisioned on tables carrying both ``tenant_id`` and ``project_id``.
GRANTED_GUC_NAME: Final[str] = "app.granted_projects"


def grants_enabled() -> bool:
    """Return True when cross-organization project participation is switched on.

    Reads the cached settings singleton beside :func:`rls_enabled`, and a settings
    failure propagates for the same reason: this flag decides whether a second GUC
    is stamped and whether a second policy is provisioned, so answering "off"
    because the settings could not be read would silently narrow what a caller
    whose company was invited in is allowed to see.
    """
    return bool(get_settings().project_grants_enforce)


def set_request_granted_projects(project_ids: Sequence[str] | None) -> Token[Any]:
    """Bind the projects the caller's company holds a live grant on.

    ``None`` and ``()`` both stamp an empty GUC, which the grant arm matches
    nothing against: a caller with no grants sees only their own company's rows,
    which is the one of the two answers that is safe to be wrong about.
    """
    return _request_granted_projects.set(tuple(project_ids or ()))


def current_request_granted_projects() -> tuple[str, ...] | None:
    """The projects bound to this context, or None when nothing bound them."""
    value = _request_granted_projects.get()
    return None if value is _UNSET else tuple(value)


def reset_request_granted_projects(token: Token[Any]) -> None:
    """Undo a :func:`set_request_granted_projects`, tolerating a stale token."""
    with contextlib.suppress(ValueError, LookupError):
        _request_granted_projects.reset(token)


def set_request_tenant(tenant_id: str | None) -> Token[Any]:
    """Bind ``tenant_id`` (or ``None`` for anonymous) to the current context.

    Marks this context as a request context, so the ``after_begin`` listener
    downgrades to the runtime role. Returns the reset token; pass it to
    :func:`reset_request_tenant` in a ``finally`` so it never leaks to the next
    request served on the same worker task.
    """
    return _request_tenant.set(tenant_id)


@contextlib.asynccontextmanager
async def bound_tenant(tenant_id: str | None, granted_projects: Sequence[str] | None = None) -> Any:
    """Bind a tenant around work that has no request to inherit one from.

    The request path binds through :func:`app.dependencies.rls_request_context`,
    which reads the tenant off the caller's token. A background path has no token
    and no request, and until it binds something the ``after_begin`` listener sees
    the private ``_UNSET`` sentinel and leaves the session on the connecting
    superuser role, which bypasses every policy: that is how a run started by one
    company's user could read another company's rows without a single query being
    wrong.

    So the value is passed in, explicitly, by whoever started the work. ``None`` is
    allowed and is not the same as not binding: it stamps an empty
    ``app.current_tenant``, which a fail-closed policy matches nothing against. A
    run whose initiator belongs to no organization therefore sees no tenant rows
    rather than all of them, which is the only one of the two answers that is safe
    to be wrong about.

    Inert while ``OE_RLS_ENFORCE`` is off, exactly like the request binding: the
    listener ignores the value, so this costs a ContextVar and changes nothing on a
    default install.
    """
    # Both are bound even when ``granted_projects`` is not passed, so a background
    # path that binds a tenant cannot leave a grant list behind that the next task
    # on this worker would inherit and read projects nobody granted it.
    token = set_request_tenant(tenant_id)
    granted_token = set_request_granted_projects(granted_projects)
    try:
        yield tenant_id
    finally:
        reset_request_granted_projects(granted_token)
        reset_request_tenant(token)


def reset_request_tenant(token: Token[Any]) -> None:
    """Undo a :func:`set_request_tenant`, tolerating a stale/foreign token."""
    with contextlib.suppress(ValueError, LookupError):
        _request_tenant.reset(token)


def current_request_tenant() -> str | None:
    """Return the tenant bound to this context, or None (anonymous/unbound)."""
    value = _request_tenant.get()
    return None if value is _UNSET else value


def install(session_class: type[Session]) -> None:
    """Register the ``after_begin`` role/GUC listener on ``session_class``.

    Attach to the sync ``Session`` class underlying the async session factory.
    The listener is a no-op while the flag is off (one function call + a cached
    bool read), so the default path is effectively free. Idempotent.
    """
    key = id(session_class)
    if key in _installed:
        return

    @event.listens_for(session_class, "after_begin")
    def _scope_transaction(session, transaction, connection) -> None:  # noqa: ANN001, ARG001
        if not rls_enabled():
            return
        value = _request_tenant.get()
        if value is _UNSET:
            # Background/system session: keep the connecting (superuser) role so
            # jobs, the event bus and seeds keep working. Such work is trusted
            # system code; to scope it, run it under the BYPASSRLS system role.
            return
        # Request context (authenticated tenant string, or None for anonymous).
        # Downgrade to the non-superuser role so policies bite, then scope to the
        # tenant. A failure here MUST propagate: running the rest of the
        # transaction as the superuser would silently bypass the policies.
        connection.exec_driver_sql(f'SET LOCAL ROLE "{APP_ROLE}"')
        connection.execute(
            text("SELECT set_config(:name, :val, true)"),
            {"name": GUC_NAME, "val": value or ""},
        )
        if not grants_enabled():
            # Off means the second statement is not issued at all, so a default
            # install pays one round trip per transaction exactly as it did before
            # the grant arm existed.
            return
        granted = _request_granted_projects.get()
        connection.execute(
            text("SELECT set_config(:name, :val, true)"),
            {
                "name": GRANTED_GUC_NAME,
                # Unset is stamped empty rather than left alone: a transaction that
                # inherited a list bound by earlier work on the same task would read
                # projects nobody granted it. Fail closed, same as the tenant arm.
                "val": ",".join(granted) if granted is not _UNSET else "",
            },
        )

    # Failed registration must remain retryable, not masquerade as installed.
    _installed.add(key)
