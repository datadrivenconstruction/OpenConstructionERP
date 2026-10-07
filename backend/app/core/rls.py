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


def set_request_tenant(tenant_id: str | None) -> Token[Any]:
    """Bind ``tenant_id`` (or ``None`` for anonymous) to the current context.

    Marks this context as a request context, so the ``after_begin`` listener
    downgrades to the runtime role. Returns the reset token; pass it to
    :func:`reset_request_tenant` in a ``finally`` so it never leaks to the next
    request served on the same worker task.
    """
    return _request_tenant.set(tenant_id)


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

    # Failed registration must remain retryable, not masquerade as installed.
    _installed.add(key)
