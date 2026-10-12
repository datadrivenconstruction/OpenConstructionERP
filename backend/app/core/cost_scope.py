# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Which cost items a caller may read: the one rule, and where it is applied.

A cost item is either shared (``catalog_id IS NULL``, the installation-wide
cost base) or belongs to a user-owned catalogue (``CostCatalog.created_by``).
The rows follow the same ownership rule as the catalogue they belong to, and
the rule is stated once, here, rather than by each endpoint that reads them.

The rule is :func:`visible_cost_items`: a row is visible when it is shared,
when the caller created its catalogue, or when the caller is an admin. A row
whose catalogue no longer exists is visible to admins only.

It is applied in one place, :func:`install`: every ORM ``SELECT`` that touches
``CostItem`` gets the rule added before it runs, for whoever the current
context is bound to. The binding is made once per request
(:class:`RequestScopeMiddleware` plus the global ``rls_request_context``
dependency), so a route cannot forget it:

* an authenticated request reads as its user;
* an anonymous request reads shared rows only;
* a context nobody bound is system work (startup, seeding, migrations,
  workers started outside a request) and reads everything.

Work started from inside a request inherits the request's caller. Code that
must see every row regardless of who triggered it (uniqueness probes against
the global ``(code, region)`` constraint, indexers, event handlers) says so
with :func:`system_scope`; code that builds data everyone will read says
:func:`shared_scope`, so a private row never ends up in a shared table.

Raw SQL and derived stores (vector indexes) are outside the reach of an ORM
hook. Their hits are passed through :func:`visible_hits` or
:func:`visible_ids` before they are returned.
"""

from __future__ import annotations

import contextlib
import uuid
from collections.abc import Iterable, Iterator
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import Session
    from sqlalchemy.sql.elements import ColumnElement

# "Nobody bound a caller": system work, reads everything. Distinct from
# ``None``, which is an anonymous request and reads shared rows only.
_SYSTEM: Final = object()

_caller: ContextVar[Any] = ContextVar("cost_scope_caller", default=_SYSTEM)


def _as_uuid(value: uuid.UUID | str | None) -> uuid.UUID | None:
    if value is None or isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def bind_caller(user_id: uuid.UUID | str | None) -> Token[Any]:
    """Make ``user_id`` the reader for the current context.

    ``None``, or an id that is not a UUID, is an anonymous reader: shared rows
    only. Pass the token to :func:`reset_caller` in a ``finally``.
    """
    return _caller.set(_as_uuid(user_id))


def reset_caller(token: Token[Any]) -> None:
    """Undo a :func:`bind_caller`, tolerating a token from another context."""
    with contextlib.suppress(ValueError, LookupError):
        _caller.reset(token)


@contextlib.contextmanager
def caller_scope(user_id: uuid.UUID | str | None) -> Iterator[None]:
    """Read as ``user_id`` inside the block (``None`` reads shared rows only)."""
    token = bind_caller(user_id)
    try:
        yield
    finally:
        reset_caller(token)


@contextlib.contextmanager
def shared_scope() -> Iterator[None]:
    """Read shared rows only inside the block.

    For anything whose result is stored or cached for everyone: a shared
    aggregate must not be built from one user's private catalogue.
    """
    with caller_scope(None):
        yield


@contextlib.contextmanager
def system_scope() -> Iterator[None]:
    """Read every row inside the block, whoever started the work.

    For code that is not answering a user: uniqueness probes, indexers, event
    handlers, and checks that do their own ownership arithmetic. Never wrap a
    read whose rows travel back to a caller.
    """
    token = _caller.set(_SYSTEM)
    try:
        yield
    finally:
        reset_caller(token)


def in_request() -> bool:
    """True when something already bound a reader for this context."""
    return _caller.get() is not _SYSTEM


class RequestScopeMiddleware:
    """Start every request as an anonymous reader and end it as the system.

    Pure ASGI, so it wraps the whole request: the route, a streamed body and
    the background tasks that run after the response. Inside it the global
    request dependency raises the reader to the authenticated user, and that
    binding is left in place until this middleware resets it, so a generator
    that streams rows or a task that runs after the response still reads as
    the same user rather than as the system.
    """

    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        token = _caller.set(None)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_caller(token)


def is_system() -> bool:
    """True when the current context reads every row."""
    return _caller.get() is _SYSTEM


def current_caller() -> uuid.UUID | None:
    """The user the current context reads as; ``None`` for anonymous or system."""
    value = _caller.get()
    return None if value is _SYSTEM else value


def visible_cost_items(user_id: uuid.UUID | None) -> ColumnElement[bool]:
    """The rule: the ``CostItem`` rows ``user_id`` may read.

    Shared rows, rows in a catalogue the user created, and every row for an
    admin. The admin test reads the user's stored role when the query runs, so
    it cannot be claimed by a token and follows a role change at once.
    """
    from sqlalchemy import exists, or_, select  # noqa: PLC0415

    from app.modules.costs.models import CostCatalog, CostItem  # noqa: PLC0415
    from app.modules.users.models import User  # noqa: PLC0415

    shared = CostItem.catalog_id.is_(None)
    if user_id is None:
        return shared
    own = CostItem.catalog_id.in_(select(CostCatalog.id).where(CostCatalog.created_by == user_id))
    admin = exists(select(User.id).where(User.id == user_id, User.role == "admin"))
    return or_(shared, own, admin)


def _scope_cost_items(state: Any) -> None:
    """``do_orm_execute`` listener: add the rule to every ORM ``SELECT``."""
    caller = _caller.get()
    if caller is _SYSTEM or not state.is_select:
        return
    from sqlalchemy.orm import with_loader_criteria  # noqa: PLC0415

    from app.modules.costs.models import CostItem  # noqa: PLC0415

    state.statement = state.statement.options(
        with_loader_criteria(
            CostItem,
            visible_cost_items(caller),
            include_aliases=True,
            propagate_to_loaders=True,
        )
    )


def install(session_class: type[Session]) -> None:
    """Apply the rule to every ORM ``SELECT`` on ``session_class``. Idempotent.

    Attach to the sync ``Session`` class that ``AsyncSession`` drives, so it
    covers every session factory in the process.
    """
    from sqlalchemy import event  # noqa: PLC0415

    if not event.contains(session_class, "do_orm_execute", _scope_cost_items):
        event.listen(session_class, "do_orm_execute", _scope_cost_items)


async def visible_ids(session: AsyncSession, ids: Iterable[Any]) -> set[str]:
    """Which of ``ids`` are cost items the current caller may read.

    For results that did not come from an ORM query on ``CostItem``: vector
    hits and other derived stores hold a copy of the row, not the row. An id
    that is not a UUID, or names no row, is not visible.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.modules.costs.models import CostItem  # noqa: PLC0415

    wanted = {u for u in (_as_uuid(i) for i in ids) if u is not None}
    if not wanted:
        return set()
    caller = _caller.get()
    stmt = select(CostItem.id).where(CostItem.id.in_(wanted))
    if caller is not _SYSTEM:
        # Stated here as well as by the hook, so the answer does not depend
        # on which session class ``session`` was built from.
        stmt = stmt.where(visible_cost_items(caller))
    return {str(row[0]) for row in (await session.execute(stmt)).all()}


async def may_read_catalogue(session: AsyncSession, catalog_id: Any) -> bool:
    """Whether the current caller may read the user-owned catalogue ``catalog_id``.

    The same rule as for its rows: the catalogue's creator and admins. A
    catalogue that does not exist reads as one the caller may not see, so the
    two cannot be told apart.
    """
    from sqlalchemy import exists, or_, select  # noqa: PLC0415

    from app.modules.costs.models import CostCatalog  # noqa: PLC0415
    from app.modules.users.models import User  # noqa: PLC0415

    wanted = _as_uuid(catalog_id)
    if wanted is None:
        return False
    caller = _caller.get()
    stmt = select(CostCatalog.id).where(CostCatalog.id == wanted)
    if caller is None:
        return False
    if caller is not _SYSTEM:
        admin = exists(select(User.id).where(User.id == caller, User.role == "admin"))
        stmt = stmt.where(or_(CostCatalog.created_by == caller, admin))
    return (await session.execute(stmt)).first() is not None


async def get_cost_item(session: AsyncSession, item_id: Any) -> Any:
    """Load one cost item by id as the current caller, or ``None``.

    Use this instead of ``session.get(CostItem, id)`` wherever the row goes
    back to a caller. ``session.get`` answers from the session's identity map
    without running a query when the row is already loaded, so a row that
    system-scoped code touched earlier in the same session would be handed
    over unchecked.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.modules.costs.models import CostItem  # noqa: PLC0415

    wanted = _as_uuid(item_id)
    if wanted is None:
        return None
    stmt = select(CostItem).where(CostItem.id == wanted)
    caller = _caller.get()
    if caller is not _SYSTEM:
        stmt = stmt.where(visible_cost_items(caller))
    return (await session.execute(stmt)).scalar_one_or_none()


async def visible_hits(session: AsyncSession, hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the vector hits whose cost item the current caller may not read.

    The cost vector store keeps a copy of each row (code, description, rate)
    with no owner on it, so every result of ``vector_search`` passes through
    here before it is used. Order is kept. System work gets the hits as is.
    """
    if not hits or _caller.get() is _SYSTEM:
        return hits
    allowed = await visible_ids(session, [hit.get("id") for hit in hits])
    return [hit for hit in hits if str(hit.get("id")) in allowed]


__all__ = [
    "bind_caller",
    "caller_scope",
    "RequestScopeMiddleware",
    "current_caller",
    "get_cost_item",
    "in_request",
    "install",
    "is_system",
    "may_read_catalogue",
    "reset_caller",
    "shared_scope",
    "system_scope",
    "visible_hits",
    "visible_cost_items",
    "visible_ids",
]
