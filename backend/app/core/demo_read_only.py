# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Read-only mode for the public hosted demo.

Off by default. A deployment turns it on with ``OE_DEMO_READ_ONLY=true``
(``demo_read_only`` on :class:`app.config.Settings`), which is the only thing
that arms anything in this module: a self-hosted install never takes any of
these branches.

Why it is two layers and not one
--------------------------------
The obvious guard - refuse every non-GET request - makes the demo look broken,
because a large part of the API posts a body for a read: sign in, semantic
search, a validation report, a what-if simulation, a preview of an uploaded
file. The obvious repair - allowlist the non-writing routes - does not scale
here. The application mounts 2178 distinct non-GET handlers, and the
request-scoped session commits on the way out (``app.dependencies.get_session``,
``app.database.get_session``), so a handler that merely assigns an attribute on
a loaded row is a writer with no call to find. Nothing static can enumerate the
non-writing set reliably, and a list that has to be complete to be safe would
be wrong the week after it was written.

So the refusal is default-deny with a small allowlist, and it is backed by a
second guard at the database:

*Layer 1* - :func:`demo_read_only_guard`, mounted as an application-level
dependency in :mod:`app.main`. It runs after routing and before the handler, so
it keys the allowlist on the *endpoint function* rather than on a URL, and one
entry therefore covers every path a router is mounted at (the loader mirrors
each module at both a hyphenated and an underscored prefix, and several modules
carry a second alias mount on top of that). It refuses before the handler is
entered, so nothing has been written when the refusal is emitted.

*Layer 2* - :func:`_before_cursor_execute`, a listener on SQLAlchemy's ``Engine``
class. It raises on any row-moving statement issued while a request is in scope
and not permitted to write, before the statement reaches the database. This is
what makes the claim "the demo is read-only" rather than "these endpoints answer
403": it holds for every handler, including any that layer 1 lets through.

The two layers together mean an allowlist mistake is cheap in the direction that
matters. Allowlisting a route that turns out to write does not leak a write -
layer 2 refuses it with the same 403. Failing to allowlist a route that reads
costs the visitor a refusal dialog. Only the second one is a UX bug, and it is
fixed by adding one line here.

One exception to that, and it is the reason to read a candidate before adding
it rather than trusting layer 2 to catch the mistake. Layer 2 sees what goes
through SQLAlchemy, which is every write in the application but one:
``_pg_bulk_insert_cost_rows`` in ``app.modules.costs.router`` takes a raw DBAPI
cursor and ``COPY``s into it, which never reaches the listener. Two routes lead
there - ``load_cwicr_database`` and the partner-pack installer under
``/api/demo`` - and for those two, layer 1 is the only guard. It holds because
neither is allowlisted, and it stops holding the moment one of them is. So a
route that reaches that helper has to be refused by layer 1 on purpose, not
allowlisted on the assumption that layer 2 is underneath.

The refusal contract
--------------------
HTTP 403 with::

    {"detail": {"error": "demo_read_only", "message": "<plain English>"}}

``error`` is what the screen matches on; ``message`` is the fallback for
anything that is not our screen. Nothing here is localised - the client owns
the translated copy.
"""

from __future__ import annotations

import contextvars
import logging
import re
from collections.abc import AsyncGenerator
from enum import Enum
from typing import Any

from fastapi import HTTPException, status
from starlette.exceptions import WebSocketException
from starlette.requests import HTTPConnection

logger = logging.getLogger(__name__)

__all__ = [
    "DEMO_READ_ONLY_ERROR",
    "DEMO_READ_ONLY_MESSAGE",
    "ALLOWED_ENDPOINTS",
    "DemoReadOnlyError",
    "WriteScope",
    "demo_read_only_enabled",
    "demo_read_only_guard",
    "endpoint_key",
    "install",
    "read_only_refusal",
    "websocket_read_only_refusal",
]

#: Machine-readable key the frontend matches on. Do not change it without the
#: screen: it is the whole contract between the two.
DEMO_READ_ONLY_ERROR = "demo_read_only"

#: Fallback copy for any client that is not our own screen (curl, an API
#: consumer, a partner integration). Deliberately English-only: the screen
#: carries its own translated copy and matches on ``error`` above, never on
#: this text. It says four things on purpose - that this is the demo, that the
#: same version can be run by anyone and where every way of getting it is
#: listed, that it takes minutes, and that a self-hosted copy is the whole
#: product with the data staying with whoever runs it.
DEMO_READ_ONLY_MESSAGE = (
    "This is the public demo, so it is read-only and nothing you change here is kept. "
    "To run this exact version yourself, download a ready-made build for your operating "
    "system or install it from PyPI - every available option is listed at "
    "openconstructionerp.com/download. It takes a few minutes, and what you get is the "
    "full product with nothing held back, running on your own machine, where all of your "
    "data stays yours."
)

#: Methods that cannot change anything by definition. Everything else is
#: refused unless its endpoint is in :data:`ALLOWED_ENDPOINTS`.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


class WriteScope(Enum):
    """How much a request that got past layer 1 is allowed to write."""

    #: Nothing beyond the always-writable infrastructure tables below.
    NONE = "none"
    #: The above, plus the sign-in bookkeeping described on
    #: :data:`_AUTHENTICATION_WRITABLE`.
    AUTHENTICATION = "authentication"


# ── Infrastructure writes ───────────────────────────────────────────────────
# These are not demo content. They are the trace of a visit, and refusing them
# would 403 a read that happens to be audited. Both are declared here rather
# than tolerated silently, and the read-only proof counts their rows separately
# from everything else so the exemption is visible instead of assumed.

#: The universal audit trail. Measured, not assumed: the only table any request
#: wrote during the observation run that produced this list was this one, on
#: sign-in.
_ALWAYS_WRITABLE = frozenset({"oe_activity_log"})

#: What sign-in may write, and which statements it may write with. Keyed by
#: table so that the permitted kinds travel next to the reason, because the
#: reason differs per table and a single "authentication may write these"
#: set would have to be widened to the loosest member.
#:
#: ``oe_users_user`` - sign-in stamps ``last_login_at`` on the account row
#: (``app.modules.users.service.UserService.login``). UPDATE only: an INSERT
#: into this table is account creation, which the demo must keep refusing.
#:
#: ``oe_users_session`` - every pair of tokens is minted together with the row
#: that names it (``UserService._issue_token_pair``), so signing in INSERTs one
#: and refreshing UPDATEs it. Both are needed: a login that cannot write its
#: row does not fall back to a session nobody can revoke, it raises, which is
#: the right trade and is why leaving this table out refused sign-in outright
#: rather than degrading it. DELETE is not here - pruning expired rows is a
#: background job, which runs with no request in scope and never reaches this
#: check at all.
_AUTHENTICATION_WRITABLE: dict[str, frozenset[str]] = {
    "oe_users_user": frozenset({"UPDATE"}),
    "oe_users_session": frozenset({"INSERT", "UPDATE"}),
}


# ── The allowlist ───────────────────────────────────────────────────────────
# Keyed by "<endpoint module>:<endpoint qualname>", so it survives the kebab /
# underscore mirror mounts and the module aliases without naming any of them.
#
# Every entry below was read before it was added. This is deliberately the set
# a visitor browsing the demo needs, not the set of every route that happens
# not to write: see the module docstring for why completeness is neither
# achievable nor required here.

#: Sign-in. A visitor must be able to log into the demo, so these three write
#: their sign-in bookkeeping and nothing else. Note what is NOT here and must
#: not be added: ``register``, ``forgot_password``, ``reset_password``,
#: ``change_password``, ``create_api_key``, ``delete_account``. Those all live
#: in the same router and all mutate accounts, which is precisely the thing a
#: read-only demo exists to prevent.
_AUTHENTICATION_ENDPOINTS = (
    "app.modules.users.router:login",
    "app.modules.users.router:demo_login",
    "app.modules.users.router:refresh",
)

#: Reads that post a body because the query does not fit in a URL. Refusing
#: these would put a refusal dialog behind the Search button.
_READ_ONLY_ENDPOINTS = (
    "app.modules.boq.router:list_boqs_by_projects",
    "app.modules.boq.router:search_cost_items",
    "app.modules.boq.router:suggest_rate",
    "app.modules.boq.router:suggest_prerequisites",
    "app.modules.boq.router:check_anomalies",
    "app.modules.boq.router:check_scope",
    "app.modules.boq.router:validate_boq",
    "app.modules.changeorders.router:simulate_impact",
    "app.modules.cost_explorer.router:compare",
    "app.modules.cost_explorer.router:substitute",
    "app.modules.costs.router:match_cwicr",
    "app.modules.costs.router:match_cwicr_from_position",
    "app.modules.costs.router:suggest_costs_for_element",
    "app.modules.costs.router:suggest_costs_for_element_by_id",
    "app.modules.costs.router:preview_cost_file",
)

#: WebSocket endpoints a visitor is allowed to open on the demo. Sockets are
#: default-deny like every other route, and this is the list that keeps the
#: realtime features usable while the flag is on.
#:
#: READ THIS BEFORE ADDING A SOCKET, because the cost of forgetting is silence
#: rather than an error. A handshake cannot carry the 403 body the HTTP refusal
#: uses - an HTTPException is not a thing a WebSocket close can express - so a
#: refused socket reaches the browser as close code 1008 and a short reason,
#: and our own screen never gets the chance to explain itself. Measured on the
#: three clients we ship, none of which reconnects: the notifications hook has
#: no close handler at all and degrades quietly to React Query polling, the
#: collaboration-lock presence hook sets its status to closed while the
#: indicator renders an empty roster, and the global-presence hook degrades
#: the same way. A visitor cannot tell any of them apart from nobody else
#: being here. So a
#: socket left out of this list does not fail loudly anywhere a user or an
#: operator is looking. It just stops working on the demo and stays green
#: everywhere else.
#:
#: One entry covers every spelling. The loader mirrors an underscore-named
#: module at a legacy prefix, so presence is mounted at two URLs, and the key is
#: the endpoint function rather than the path: both resolve to the single entry
#: below. Verified on both FastAPI include shapes.
_READ_ONLY_SOCKET_ENDPOINTS = (
    "app.modules.notifications.router:notifications_ws",
    "app.modules.collaboration_locks.router:presence_ws",
    "app.modules.global_presence.router:global_presence_ws",
)

#: The resolved allowlist. Public so a test can assert against it and so the
#: screen team can see exactly what stays live.
ALLOWED_ENDPOINTS: dict[str, WriteScope] = {
    **dict.fromkeys(_AUTHENTICATION_ENDPOINTS, WriteScope.AUTHENTICATION),
    **dict.fromkeys(_READ_ONLY_ENDPOINTS, WriteScope.NONE),
    **dict.fromkeys(_READ_ONLY_SOCKET_ENDPOINTS, WriteScope.NONE),
}


class DemoReadOnlyError(Exception):
    """A write was attempted against a read-only demo.

    Raised by the database listener, i.e. by layer 2, and translated into the
    same 403 contract layer 1 emits. Carries the statement kind and target so
    an operator reading the log can see what tried to write.
    """

    def __init__(self, kind: str, table: str | None) -> None:
        self.kind = kind
        self.table = table
        super().__init__(f"{kind} on {table or 'an unnamed target'} refused: demo is read-only")


def demo_read_only_enabled() -> bool:
    """Whether this deployment is a read-only demo.

    Read per call, never cached in this module. The settings object itself is
    an ``lru_cache`` singleton, so a test that flips the environment clears
    that cache; caching the answer here as well would make it impossible to
    exercise both states in one run, which is exactly how a guard quietly
    becomes on-by-default or off-for-everyone without the suite noticing.
    """
    from app.config import get_settings

    return bool(get_settings().demo_read_only)


def read_only_refusal() -> HTTPException:
    """Build the 403 both layers answer with."""
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={"error": DEMO_READ_ONLY_ERROR, "message": DEMO_READ_ONLY_MESSAGE},
    )


def websocket_read_only_refusal() -> WebSocketException:
    """Build the close a refused handshake carries.

    1008 is "policy violation", which is what this is, and it is the code the
    two sockets already use for their own auth refusals so a client needs no
    new case. The reason carries :data:`DEMO_READ_ONLY_ERROR` and nothing else:
    a close reason is capped at 123 bytes, so the long message the 403 carries
    would not fit, and the machine-readable key is the half a client matches on
    anyway. Nothing here is localised, exactly as with the 403.
    """
    return WebSocketException(code=1008, reason=DEMO_READ_ONLY_ERROR)


def endpoint_key(endpoint: Any) -> str | None:
    """Identity of a route handler, independent of the URL it is mounted at."""
    module = getattr(endpoint, "__module__", None)
    qualname = getattr(endpoint, "__qualname__", None) or getattr(endpoint, "__name__", None)
    if not module or not qualname:
        return None
    return f"{module}:{qualname}"


# ── Per-request write permission ────────────────────────────────────────────
# ``None`` means "no request is in scope": application startup, the seeders,
# the CLI, the module loader and the background workers all run with this value
# and are never guarded. A request binds the scope its route was granted for
# the duration of the request and clears it afterwards, the same shape
# ``app.dependencies.rls_request_context`` uses, so the binding can never
# outlive the request that made it.

_write_scope: contextvars.ContextVar[WriteScope | None] = contextvars.ContextVar(
    "demo_read_only_write_scope",
    default=None,
)


async def demo_read_only_guard(connection: HTTPConnection) -> AsyncGenerator[None, None]:
    """Refuse a mutating request on a read-only demo, before the handler runs.

    Mounted as an application-level dependency, so it applies to every route
    the app mounts, including ones added by the module loader at startup and
    the alias mounts layered on afterwards. It takes no other dependency on
    purpose: an anonymous caller must get the 403 rather than a 401, and the
    refusal must not wait on token decoding or a database round trip.

    The parameter is typed ``HTTPConnection`` rather than ``Request`` because an
    application-level dependency is attached to WebSocket routes too, and FastAPI
    only fills a ``Request`` parameter for an HTTP route - a socket route would
    call this with the argument missing. ``HTTPConnection`` is the common base
    and is filled for both.

    WebSocket handshakes are refused here too, and they are default-deny like
    everything else: a socket carries no method, so there is nothing to key a
    safe-versus-unsafe decision on, and the only honest reading of "no method"
    is "not known to be safe". The three sockets a visitor needs are named in
    :data:`_READ_ONLY_SOCKET_ENDPOINTS` and everything else is closed with 1008.

    This is what keeps sockets at the same depth as the rest of the module.
    Refusing at the handshake is layer 1 for a socket; without it a socket would
    rest on the database tripwire alone, and that tripwire has a documented
    blind spot (the raw-cursor ``COPY`` described above) which layer 1 is what
    covers for HTTP. Allowlisting a socket is therefore the same promise as
    allowlisting a route: it has to be read first, not assumed safe because
    today's handler only broadcasts.
    """
    if not demo_read_only_enabled():
        yield
        return

    scope = connection.scope
    granted = ALLOWED_ENDPOINTS.get(endpoint_key(scope.get("endpoint")) or "")
    method = (scope.get("method") or "").upper()

    if scope.get("type") == "http" and method not in SAFE_METHODS and granted is None:
        logger.info("demo read-only: refused %s %s", method, scope.get("path", "?"))
        raise read_only_refusal()

    if scope.get("type") == "websocket" and granted is None:
        logger.info("demo read-only: refused websocket %s", scope.get("path", "?"))
        raise websocket_read_only_refusal()

    token = _write_scope.set(granted or WriteScope.NONE)
    try:
        yield
    finally:
        _write_scope.reset(token)


# ── Layer 2: the database tripwire ──────────────────────────────────────────

#: Leading keyword of a statement, past any leading whitespace or comment.
_LEADING = re.compile(r"\A(?:\s+|--[^\n]*\n|/\*.*?\*/)*([A-Za-z_]+)", re.DOTALL)

#: Statement kinds that move rows or change the schema. Deliberately not a
#: catch-all: ``SET``/``SHOW``/``BEGIN``/``COMMIT``/``SAVEPOINT``/``DISCARD``/
#: ``LOCK``/``ANALYZE`` are how the driver, the pool and the row-level-security
#: listener do their work, and refusing them would break every read.
_WRITE_KINDS = frozenset(
    {
        "INSERT",
        "UPDATE",
        "DELETE",
        "MERGE",
        "TRUNCATE",
        "CREATE",
        "DROP",
        "ALTER",
        "GRANT",
        "REVOKE",
        "COPY",
    }
)

_TARGET = {
    "INSERT": re.compile(r"\AINSERT\s+INTO\s+(?:ONLY\s+)?([\"\w.]+)", re.IGNORECASE),
    "UPDATE": re.compile(r"\AUPDATE\s+(?:ONLY\s+)?([\"\w.]+)", re.IGNORECASE),
    "DELETE": re.compile(r"\ADELETE\s+FROM\s+(?:ONLY\s+)?([\"\w.]+)", re.IGNORECASE),
    "MERGE": re.compile(r"\AMERGE\s+INTO\s+(?:ONLY\s+)?([\"\w.]+)", re.IGNORECASE),
    "TRUNCATE": re.compile(r"\ATRUNCATE\s+(?:TABLE\s+)?(?:ONLY\s+)?([\"\w.]+)", re.IGNORECASE),
}

#: ``COPY t FROM ...`` loads rows; ``COPY (SELECT ...) TO ...`` is how a bulk
#: export reads them out. Only the first one is a write.
_COPY_FROM = re.compile(r"\ACOPY\b[^;]*?\bFROM\b", re.IGNORECASE | re.DOTALL)

#: A session-local scratch table is not persistent state.
_TEMP_DDL = re.compile(r"\A(?:CREATE|DROP)\s+(?:GLOBAL\s+|LOCAL\s+)?TEMP(?:ORARY)?\b", re.IGNORECASE)


def _statement_target(kind: str, statement: str) -> str | None:
    """Bare table name a DML statement writes, or ``None`` when unreadable."""
    pattern = _TARGET.get(kind)
    if pattern is None:
        return None
    match = pattern.match(statement)
    if match is None:
        return None
    name = match.group(1).strip().strip('"')
    return name.rsplit(".", 1)[-1].strip('"').lower()


def classify_statement(statement: str) -> tuple[str, str | None] | None:
    """Classify a SQL statement as a write.

    Returns ``(kind, table)`` when the statement moves rows or changes the
    schema, and ``None`` when it does not. ``table`` is ``None`` when the
    target could not be read off the statement, which the caller must treat as
    "refuse": an unreadable target cannot be shown to be exempt.
    """
    if not statement:
        return None
    match = _LEADING.match(statement)
    if match is None:
        return None
    kind = match.group(1).upper()

    if kind == "WITH":
        # A CTE can carry DML in its body. Cheap containment check - the false
        # positive (the literal word inside a string) costs a refusal on a
        # route that is already refused by layer 1.
        body = statement.upper()
        for candidate in ("INSERT INTO", "UPDATE ", "DELETE FROM", "MERGE INTO"):
            if candidate in body:
                return (candidate.split()[0], None)
        return None

    if kind not in _WRITE_KINDS:
        return None
    if kind == "COPY" and not _COPY_FROM.match(statement.lstrip()):
        return None
    if kind in ("CREATE", "DROP") and _TEMP_DDL.match(statement.lstrip()):
        return None

    return (kind, _statement_target(kind, statement.lstrip()))


def _permitted(scope: WriteScope, kind: str, table: str | None) -> bool:
    """Whether a request holding ``scope`` may issue this statement."""
    if table is None:
        return False
    if table in _ALWAYS_WRITABLE:
        return True
    if scope is WriteScope.AUTHENTICATION and kind in _AUTHENTICATION_WRITABLE.get(table, frozenset()):
        return True
    return False


def _before_cursor_execute(
    conn: Any,
    cursor: Any,
    statement: str,
    parameters: Any,
    context: Any,
    executemany: bool,  # noqa: FBT001 - SQLAlchemy's signature
) -> None:
    """Refuse a write before the statement reaches the database.

    Registered on the ``Engine`` class, so it covers every engine in the
    process rather than the one this module happened to import. Inert unless
    the deployment is a read-only demo AND a request is in scope: startup,
    migrations, the seeders and the background workers all run with no request
    scope and are untouched.
    """
    scope = _write_scope.get()
    if scope is None:
        return
    if not demo_read_only_enabled():
        return
    verdict = classify_statement(statement)
    if verdict is None:
        return
    kind, table = verdict
    if _permitted(scope, kind, table):
        return
    logger.warning(
        "demo read-only: refused %s on %s at the database (scope=%s)",
        kind,
        table or "an unnamed target",
        scope.value,
    )
    raise DemoReadOnlyError(kind, table)


_installed = False


def install() -> None:
    """Register the database tripwire. Idempotent.

    Listens on the ``Engine`` class rather than on one engine instance,
    matching how :mod:`app.database` registers its slow-query listeners, so an
    engine built later by a module or a test is covered too.
    """
    global _installed
    if _installed:
        return
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    event.listen(Engine, "before_cursor_execute", _before_cursor_execute)
    _installed = True


# ── Test seam ───────────────────────────────────────────────────────────────


def _set_write_scope(scope: WriteScope | None) -> contextvars.Token:
    """Set the per-request write scope. Test-only; production sets it in the guard."""
    return _write_scope.set(scope)


def _reset_write_scope(token: contextvars.Token) -> None:
    """Undo :func:`_set_write_scope`. Test-only."""
    _write_scope.reset(token)
