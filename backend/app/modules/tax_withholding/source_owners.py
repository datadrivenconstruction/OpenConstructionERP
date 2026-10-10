# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Who owns the document a set of statutory tax lines is filed on.

A set of statutory tax lines names its document by an id from another module:
a progress claim in ``contracts``, a payment application in
``subcontractors``, an invoice in ``finance``. This module must load without
any of them, so there is no foreign key, and nothing stored here can say
whether the id is real or which project it belongs to. Without an answer to
that, a caller who may write to project B could file a set under any id
nobody had claimed yet, including the id of project A's claim, and so decide
what A's certificate would later find.

The dependency therefore points the other way, as it does for
:mod:`app.modules.contracts.claim_context`. The module that owns a kind of
document registers a resolver for it here, and every statutory route asks the
resolver before it reads or writes.

Fail closed. A kind with no resolver registered is refused, exactly like a
document the resolver does not know: an install where the owning module is
absent has no such documents, so there is nothing a set could honestly be
filed on.

No model imports, so an owner module can import this file from its startup
hook without pulling the tax tables in.
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

#: ``resolver(session, source_id)`` returns the id of the project that owns the
#: document, or ``None`` when there is no such document. It may be sync or async.
SourceOwnerResolver = Callable[[AsyncSession, uuid.UUID], uuid.UUID | None | Awaitable[uuid.UUID | None]]

_resolvers: dict[str, SourceOwnerResolver] = {}


class SourceOwnerMissingError(LookupError):
    """No module has registered as the owner of this kind of document."""


def register_source_owner(source_kind: str, resolver: SourceOwnerResolver) -> None:
    """Make ``resolver`` the authority on which project a ``source_kind`` document belongs to.

    Registering the same kind again replaces the resolver, so a module that
    registers on every load stays registered once.

    Args:
        source_kind: One of the statutory source kinds, for example
            ``progress_claim``.
        resolver: Called as ``resolver(session, source_id)``; its return value
            is awaited when it is awaitable.
    """
    _resolvers[source_kind] = resolver


def unregister_source_owner(source_kind: str) -> None:
    """Remove the resolver of one kind; with none registered this does nothing."""
    _resolvers.pop(source_kind, None)


def registered_source_kinds() -> tuple[str, ...]:
    """The kinds that have an owner on this install, sorted."""
    return tuple(sorted(_resolvers))


async def resolve_source_project(session: AsyncSession, source_kind: str, source_id: uuid.UUID) -> uuid.UUID | None:
    """The project that owns one source document, or ``None`` when it does not exist.

    Raises:
        SourceOwnerMissingError: No resolver is registered for ``source_kind``.
            The caller refuses the request; it does not treat the kind as
            unowned and therefore free.
    """
    resolver = _resolvers.get(source_kind)
    if resolver is None:
        raise SourceOwnerMissingError(source_kind)
    found = resolver(session, source_id)
    if inspect.isawaitable(found):
        found = await found
    if found is None:
        return None
    return found if isinstance(found, uuid.UUID) else uuid.UUID(str(found))


async def source_belongs_to_project(
    session: AsyncSession,
    *,
    source_kind: str,
    source_id: uuid.UUID,
    project_id: uuid.UUID,
) -> bool:
    """Whether the named document exists and belongs to ``project_id``.

    False for a kind nobody owns, for a document the owner does not know and
    for a document of another project. The three are not told apart on
    purpose: each is "this is not your document", and the caller answers all
    of them the same way.
    """
    try:
        owner = await resolve_source_project(session, source_kind, source_id)
    except SourceOwnerMissingError:
        return False
    return owner is not None and owner == project_id


__all__ = [
    "SourceOwnerMissingError",
    "SourceOwnerResolver",
    "register_source_owner",
    "registered_source_kinds",
    "resolve_source_project",
    "source_belongs_to_project",
    "unregister_source_owner",
]
