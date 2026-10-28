# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Factory for per-module ``/vector/status/`` and ``/vector/reindex/`` routes.

Every module that plugs into the cross-module semantic memory layer
(``app.core.vector_index``) needs the same two HTTP endpoints:

* ``GET  /vector/status/``   - collection health / row count
* ``POST /vector/reindex/``  - (re)embed rows from the database

The business logic never varies - only the adapter, the SQLAlchemy model,
the permission strings and (occasionally) a custom statement for modules
whose rows are scoped via a join through a parent table.  This factory
captures that boilerplate so module routers reduce to a single
``include_router(create_vector_routes(...))`` call.

Usage (simple direct project_id column)::

    from app.core.vector_routes import create_vector_routes
    from app.core.vector_index import COLLECTION_DOCUMENTS
    from app.modules.documents.vector_adapter import document_vector_adapter
    from app.modules.documents.models import Document

    router.include_router(
        create_vector_routes(
            collection=COLLECTION_DOCUMENTS,
            adapter=document_vector_adapter,
            model=Document,
            read_permission="documents.read",
            write_permission="documents.update",
            project_id_attr="project_id",
        )
    )

Usage (parent-join, e.g. requirements joined via RequirementSet)::

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload
    from app.modules.requirements.models import Requirement, RequirementSet

    async def _statement(_session, project_id):
        stmt = select(Requirement).options(selectinload(Requirement.requirement_set))
        if project_id is not None:
            stmt = stmt.join(
                RequirementSet,
                Requirement.requirement_set_id == RequirementSet.id,
            ).where(RequirementSet.project_id == project_id)
        return stmt

    router.include_router(
        create_vector_routes(
            collection=COLLECTION_REQUIREMENTS,
            adapter=requirement_vector_adapter,
            statement_factory=_statement,
            read_permission="requirements.read",
            write_permission="requirements.update",
        )
    )

A custom scope returns the SELECT, never its rows.  That is the whole of
the contract, and it is what keeps the bound below in one place: the
factory owns the ordering, the paging, the release and the ceiling for
every module at once, and a module cannot opt out of them by handing
back a list it has already materialised.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import Select, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vector_index import (
    EmbeddingAdapter,
    collection_status,
    reindex_collection,
)
from app.dependencies import CurrentUserId, RequirePermission, SessionDep

logger = logging.getLogger(__name__)

#: Signature of a custom statement builder: takes the session + optional
#: ``project_id`` filter and returns the SELECT that yields the rows to
#: embed.  Used by modules whose rows are scoped through a join
#: (requirements, erp_chat messages).  It returns the statement rather
#: than the rows so the walk below can bound it.
StatementFn = Callable[[AsyncSession, uuid.UUID | None], Awaitable[Select[Any]]]

# Rows read, embedded and released in one page of a reindex pass.
#
# The handler used to read the module's whole table in one buffered statement
# and hold every entity for the length of the pass.  Measured on this tree with
# tracemalloc, one loaded ORM row costs 2.5 KiB (a requirement) to 29.7 KiB (a
# validation report, whose ``results`` JSON carries one entry per rule fired);
# documents 2.7, boq positions 2.7 and bim elements 3.1, then tasks 4.7, risks
# 6.2 and chat messages 7.3.  At the heaviest of those a 100 000-row collection
# is ~2.9 GiB held at once, on a platform whose stated floor is a 3 GB server
# that also runs PostgreSQL.  The two highest-count tables in the product are
# among the cheapest per row, so their exposure is cardinality rather than
# weight: a million positions is ~2.5 GiB on its own.
#
# Warm the profiler before trusting any of those: SQLAlchemy bills the first
# instance of a mapped class for instrumenting it, so whichever model is
# measured first reads several KiB too heavy.
#
# Paging the read is only half of the bound: the session keeps every entity it
# hands out until the transaction ends, whatever shape the read had, so each
# page is released below as well.  At this page size the heaviest consumer
# holds ~15 MiB and the lightest ~1 MiB, and what ``index_many`` is handed per
# embedding batch (64 rows) is unchanged.
_REINDEX_PAGE_ROWS = 500

# Ceiling on one reindex pass.
#
# Unlike the reads that were merely buffered, a cap is right here: every row on
# this path goes through the embedding model inside the request, so an uncapped
# pass is unbounded CPU work on an open connection.  It sits far above any
# collection the platform expects - the startup auto-backfill treats 5 000 rows
# as a normal pass (``vector_backfill_max_rows``) - so reaching it is an
# anomaly rather than a routine event.
#
# Reaching it is reported.  A truncated response that says nothing about being
# truncated is the worse half of the defect: the caller is handed a plausible
# ``indexed`` count and nothing at all to say that the rest of the collection
# is not in the search index and will not be found by a semantic search.
_REINDEX_MAX_ROWS = 100_000


def _ordered_by_primary_key(stmt: Select[Any]) -> Select[Any]:
    """Append the entity's primary key to ``stmt``'s ORDER BY.

    The walk below addresses pages by offset, and an offset into an
    undefined ordering is not a position: the same row can be served
    twice and another skipped, silently, with every count still adding
    up.  The primary key is appended rather than imposed, so a statement
    that already orders itself keeps that order and gains a tiebreaker.
    """
    descriptions = stmt.column_descriptions
    entity = descriptions[0]["entity"] if descriptions else None
    if entity is None:
        raise ValueError(
            "reindex: the statement must select a mapped entity, so its rows can be walked in a defined order"
        )
    return stmt.order_by(*sa_inspect(entity).primary_key)


async def reindex_statement_in_pages(
    session: AsyncSession,
    adapter: EmbeddingAdapter,
    stmt: Select[Any],
    *,
    purge_first: bool = False,
) -> dict[str, Any]:
    """Walk ``stmt`` in bounded pages, embedding and releasing each one.

    This is the whole of the bound, in one place, for every reindex path in
    the platform.  ``create_vector_routes`` calls it for the six modules it
    serves; the two endpoints that cannot use the factory because they carry
    their own permission gating (boq positions, bim elements) call it
    directly.  A reindex that builds its own loop instead is a reindex that
    has to re-derive five separate properties, and the one it forgets will
    not announce itself:

    1. The walk is ORDERED.  Pages are addressed by offset, and an offset
       into an undefined ordering is not a position - the same row can be
       served twice and another skipped with every count still adding up.
    2. The read is PAGED, so the statement never materialises the table.
    3. Each page is FLUSHED before it is released.  Expunging first detaches
       the instances with their work still pending and drops it silently.
    4. Each page is RELEASED, because a ``Session`` holds every entity it
       hands out until the transaction ends whatever shape the read had.
       Paging without releasing moves the allocation around and bounds
       nothing.
    5. The ceiling is REPORTED.  A truncated response that says nothing
       about being truncated is the worse half of the defect.

    Args:
        session: The request's async session.  The walk expunges the rows it
            reads, so anything the caller still needs must be read first.
        adapter: Embedding adapter for the rows the statement selects.
        stmt: SELECT over a mapped entity.  Its own ORDER BY, if any, is
            kept and the primary key is appended as a tiebreaker.
        purge_first: Drop each page's ids from the vector store before
            re-encoding them.

    Returns:
        ``indexed`` / ``skipped`` / ``purged`` / ``collection`` as
        ``reindex_collection`` has always returned them, plus ``scanned``,
        ``cap``, ``truncated`` and a ``message`` describing the bound.

    Raises:
        ValueError: If the statement selects no mapped entity, which would
            leave the walk with no defined order to page by.
    """
    stmt = _ordered_by_primary_key(stmt)

    indexed = 0
    skipped = 0
    purged = False
    scanned = 0
    offset = 0
    hit_cap = False
    while True:
        if offset >= _REINDEX_MAX_ROWS:
            hit_cap = True
            break
        page_rows = min(_REINDEX_PAGE_ROWS, _REINDEX_MAX_ROWS - offset)
        page = list((await session.execute(stmt.offset(offset).limit(page_rows))).scalars().all())
        if not page:
            break

        # One call per page rather than one per pass. ``reindex_collection``
        # purges the ids it is about to index - ``vector_delete_collection``
        # is a delete BY ID on both backends, not a wipe - so purging per
        # page and purging once over the union of the pages leave the same
        # rows in the store. What does narrow is its per-collection lock:
        # purge and index stay paired under it, which is the property it
        # exists for, but two concurrent passes over one collection can now
        # interleave whole pages. Both only ever upsert by id, so the
        # interleaving costs repeated work, not a wrong index.
        result = await reindex_collection(adapter, page, purge_first=purge_first)
        indexed += int(result.get("indexed") or 0)
        skipped += int(result.get("skipped") or 0)
        purged = purged or bool(result.get("purged"))
        scanned += len(page)
        offset += len(page)

        # Write out anything the page left pending, then let go of it. The
        # order is load-bearing: expunging first would detach the instances
        # with their work unflushed and drop it on the floor. This pass only
        # reads, so the flush is a no-op today - it is what keeps the
        # release safe the day an adapter or an event handler touches a row.
        await session.flush()
        for row in page:
            session.expunge(row)
        if len(page) < page_rows:
            break

    truncated = False
    if hit_cap:
        # The pass stopped on the ceiling rather than on the end of the
        # collection. Look one row past it before saying so: a collection
        # that ends exactly on the ceiling was walked in full, and calling
        # that one truncated sends the reader after rows that are all there.
        # No flush before this expunge, unlike the pages above: the row is
        # read to be counted and is never handed to the adapter, so nothing
        # can have made it dirty between the read and the release.
        overflow = list((await session.execute(stmt.offset(offset).limit(1))).scalars().all())
        truncated = bool(overflow)
        for row in overflow:
            session.expunge(row)

    if truncated:
        logger.warning(
            "Reindex %s: stopped at the %d-row ceiling after %d rows; the rest is NOT indexed",
            adapter.collection_name,
            _REINDEX_MAX_ROWS,
            scanned,
        )

    return {
        "indexed": indexed,
        "skipped": skipped,
        "purged": purged,
        "collection": adapter.collection_name,
        # How much of the collection this pass actually walked, next to the
        # ceiling it was allowed to walk. ``indexed`` alone cannot separate
        # "the collection is this small" from "we stopped early", and
        # neither can ``skipped``, which counts rows that were read and
        # declined rather than rows that were never read.
        "scanned": scanned,
        "cap": _REINDEX_MAX_ROWS,
        "truncated": truncated,
        "message": (
            f"Stopped at the {_REINDEX_MAX_ROWS}-row ceiling after the first {scanned} rows. "
            f"The remainder is NOT in the search index and will not be found by a semantic search."
            if truncated
            else f"Indexed {indexed} of {scanned} rows."
        ),
    }


def create_vector_routes(
    *,
    collection: str,
    adapter: EmbeddingAdapter,
    read_permission: str | None,
    write_permission: str | None,
    model: type | None = None,
    options: list[Any] | None = None,
    project_id_attr: str | None = None,
    statement_factory: StatementFn | None = None,
    loader: Any = None,
) -> APIRouter:
    """Build a sub-router exposing ``/vector/status/`` and ``/vector/reindex/``.

    Exactly one of ``model`` or ``statement_factory`` must be supplied.  When
    ``model`` is given the factory builds a simple ``select(model)`` with
    optional ``selectinload`` options and, if ``project_id_attr`` is set,
    filters by that attribute when the caller passes ``?project_id=``.  When
    rows need a join through a parent table, pass a ``statement_factory``
    coroutine that returns the SELECT instead.

    The returned router has no prefix - the caller is expected to
    ``router.include_router(create_vector_routes(...))`` it into the
    module's main router so the endpoints land at
    ``/api/v1/{module}/vector/status/`` and ``/vector/reindex/``.

    Status code, query param names and permission strings are identical to
    the hand-written endpoints this factory replaces, and so are the
    ``indexed`` / ``skipped`` / ``purged`` / ``collection`` keys of the
    reindex response.  What is new there is the report the bound owes its
    caller: ``scanned``, ``cap``, ``truncated`` and a ``message``.

    Args:
        collection: Vector collection name, e.g. ``COLLECTION_DOCUMENTS``.
        adapter: Embedding adapter for the module's rows.
        read_permission: Permission guarding ``/vector/status/``, or None.
        write_permission: Permission guarding ``/vector/reindex/``, or None.
        model: Mapped class to read, for the simple single-table case.
        options: Loader options (``selectinload(...)``) for that read.
        project_id_attr: Column on ``model`` the ``?project_id=`` filter uses.
        statement_factory: Coroutine returning the SELECT to walk, for rows
            scoped through a join.
        loader: Rejected.  Kept only so the previous contract - a coroutine
            returning the rows themselves - fails by name instead of as an
            unexpected keyword.

    Returns:
        An ``APIRouter`` carrying the two endpoints.

    Raises:
        ValueError: If neither or both of ``model`` / ``statement_factory``
            are given, or if the retired ``loader`` keyword is passed.
    """
    if loader is not None:
        raise ValueError(
            "create_vector_routes: 'loader' is retired. It returned the rows themselves, "
            "which put the whole collection in memory before the first row reached the "
            "vector store and left the factory nothing to bound. Pass 'statement_factory' "
            "instead - the same coroutine, returning the SELECT rather than executing it."
        )
    if (model is None) == (statement_factory is None):
        raise ValueError("create_vector_routes: supply exactly one of 'model' or 'statement_factory'")

    sub = APIRouter()

    read_deps = [Depends(RequirePermission(read_permission))] if read_permission else []
    write_deps = [Depends(RequirePermission(write_permission))] if write_permission else []

    @sub.get("/vector/status/", dependencies=read_deps)
    async def vector_status(_user_id: CurrentUserId) -> dict[str, Any]:
        """Return health + row count for this module's vector collection."""
        return collection_status(collection)

    @sub.post("/vector/reindex/", dependencies=write_deps)
    async def vector_reindex(
        session: SessionDep,
        _user_id: CurrentUserId,
        project_id: uuid.UUID | None = Query(default=None),
        purge_first: bool = Query(default=False),
    ) -> dict[str, Any]:
        """Backfill this module's vector collection.

        Pass ``?project_id=`` to scope the reindex to a single project.
        Set ``?purge_first=true`` to drop the matching subset from the
        vector store before re-encoding - useful after an embedding
        model change.

        The collection is walked in pages of ``_REINDEX_PAGE_ROWS``, each
        indexed and then released before the next is read, so the pass holds
        one page instead of the collection.  A collection larger than
        ``_REINDEX_MAX_ROWS`` is indexed up to that ceiling and the response
        says so: ``scanned`` next to ``cap`` and ``truncated``.
        """
        if statement_factory is not None:
            stmt = await statement_factory(session, project_id)
        else:
            assert model is not None  # narrow for type checker
            stmt = select(model)
            if options:
                stmt = stmt.options(*options)
            if project_id is not None and project_id_attr:
                stmt = stmt.where(getattr(model, project_id_attr) == project_id)
        return await reindex_statement_in_pages(session, adapter, stmt, purge_first=purge_first)

    return sub
