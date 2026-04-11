"""Factory for per-module ``/vector/status/`` and ``/vector/reindex/`` routes.

Every module that plugs into the cross-module semantic memory layer
(``app.core.vector_index``) needs the same two HTTP endpoints:

* ``GET  /vector/status/``   — collection health / row count
* ``POST /vector/reindex/``  — (re)embed rows from the database

The business logic never varies — only the adapter, the SQLAlchemy model,
the permission strings and (occasionally) a custom loader for modules
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

    async def _loader(session, project_id):
        stmt = select(Requirement).options(selectinload(Requirement.requirement_set))
        if project_id is not None:
            stmt = stmt.join(
                RequirementSet,
                Requirement.requirement_set_id == RequirementSet.id,
            ).where(RequirementSet.project_id == project_id)
        return list((await session.execute(stmt)).scalars().all())

    router.include_router(
        create_vector_routes(
            collection=COLLECTION_REQUIREMENTS,
            adapter=requirement_vector_adapter,
            loader=_loader,
            read_permission="requirements.read",
            write_permission="requirements.update",
        )
    )
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vector_index import (
    EmbeddingAdapter,
    collection_status,
    reindex_collection,
)
from app.dependencies import CurrentUserId, RequirePermission, SessionDep

#: Signature of a custom row loader: takes the session + optional
#: ``project_id`` filter and returns the full list of rows that should
#: be embedded.  Used by modules whose rows are scoped through a join
#: (requirements, bim_hub elements, erp_chat messages).
LoaderFn = Callable[[AsyncSession, uuid.UUID | None], Awaitable[list[Any]]]


def create_vector_routes(
    *,
    collection: str,
    adapter: EmbeddingAdapter,
    read_permission: str | None,
    write_permission: str | None,
    model: type | None = None,
    options: list[Any] | None = None,
    project_id_attr: str | None = None,
    loader: LoaderFn | None = None,
) -> APIRouter:
    """Build a sub-router exposing ``/vector/status/`` and ``/vector/reindex/``.

    Exactly one of ``model`` or ``loader`` must be supplied.  When ``model``
    is given the factory builds a simple ``select(model)`` with optional
    ``selectinload`` options and, if ``project_id_attr`` is set, filters by
    that attribute when the caller passes ``?project_id=``.  When rows need
    a join through a parent table, pass a ``loader`` coroutine instead.

    The returned router has no prefix — the caller is expected to
    ``router.include_router(create_vector_routes(...))`` it into the
    module's main router so the endpoints land at
    ``/api/v1/{module}/vector/status/`` and ``/vector/reindex/``.

    Behaviour (status code, response shape, query param names,
    permission strings) is byte-for-byte identical to the hand-written
    endpoints this factory replaces.
    """
    if (model is None) == (loader is None):
        raise ValueError(
            "create_vector_routes: supply exactly one of 'model' or 'loader'"
        )

    sub = APIRouter()

    read_deps = (
        [Depends(RequirePermission(read_permission))] if read_permission else []
    )
    write_deps = (
        [Depends(RequirePermission(write_permission))] if write_permission else []
    )

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
        vector store before re-encoding — useful after an embedding
        model change.
        """
        if loader is not None:
            rows = await loader(session, project_id)
        else:
            assert model is not None  # narrow for type checker
            stmt = select(model)
            if options:
                stmt = stmt.options(*options)
            if project_id is not None and project_id_attr:
                stmt = stmt.where(getattr(model, project_id_attr) == project_id)
            rows = list((await session.execute(stmt)).scalars().all())

        return await reindex_collection(
            adapter,
            rows,
            purge_first=purge_first,
        )

    return sub
