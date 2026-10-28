# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Data access for EAC block graphs.

Every function is tenant-scoped: the tenant id is a required argument, never
inferred, so a caller cannot accidentally reach across tenants by forgetting a
filter. Reads return ``None`` rather than raising, leaving the 404 decision to
the router.

Two things worth knowing about how this layer behaves:

* Reads use ``select()`` with an explicit tenant predicate rather than
  ``session.get()``. ``session.get()`` answers from the identity map, so it can
  hand back a row another statement in the same session already deleted, and it
  cannot express the tenant filter at all.
* Writing a canvas replaces the whole graph body. The blocks and wires are
  deleted and re-inserted rather than diffed, which matches what the editor
  sends (``loadGraph`` takes a whole snapshot) and keeps ordinals contiguous
  without a reorder dance. Block identity survives because it lives in
  ``client_id``, not in the database primary key.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.eac.models import EacBlock, EacBlockConnection, EacBlockGraph
from app.modules.eac.schemas_graph import BlockWrite, ConnectionWrite


async def get_graph(
    session: AsyncSession,
    graph_id: uuid.UUID,
    tenant_id: uuid.UUID,
) -> EacBlockGraph | None:
    """Fetch one graph with its blocks and wires, or None.

    Args:
        session: Active async session.
        graph_id: Graph primary key.
        tenant_id: Owning tenant; a graph belonging to anyone else reads as
            absent rather than forbidden, so the API cannot be used to probe
            for the existence of another tenant's work.

    Returns:
        The graph with ``blocks`` and ``connections`` already loaded, or None.
    """
    stmt = select(EacBlockGraph).where(
        EacBlockGraph.id == graph_id,
        EacBlockGraph.tenant_id == tenant_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_graphs(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    project_id: uuid.UUID | None = None,
    rule_id: uuid.UUID | None = None,
    search: str | None = None,
    include_unscoped: bool = True,
    limit: int = 50,
    offset: int = 0,
) -> Sequence[EacBlockGraph]:
    """List graphs for a tenant, newest edit first.

    Args:
        session: Active async session.
        tenant_id: Owning tenant.
        project_id: When given, restrict to this project. Graphs with no
            project are reusable, so they are included as well unless
            ``include_unscoped`` is False.
        rule_id: When given, restrict to graphs bound to this rule.
        search: Case-insensitive substring match on the name.
        include_unscoped: Whether a project filter also returns the reusable,
            project-less graphs.
        limit: Page size, clamped by the caller.
        offset: Rows to skip.

    Returns:
        Matching graphs, ordered by ``updated_at`` descending.
    """
    stmt = select(EacBlockGraph).where(EacBlockGraph.tenant_id == tenant_id)
    if project_id is not None:
        if include_unscoped:
            stmt = stmt.where(
                or_(
                    EacBlockGraph.project_id == project_id,
                    EacBlockGraph.project_id.is_(None),
                )
            )
        else:
            stmt = stmt.where(EacBlockGraph.project_id == project_id)
    if rule_id is not None:
        stmt = stmt.where(EacBlockGraph.rule_id == rule_id)
    if search:
        stmt = stmt.where(func.lower(EacBlockGraph.name).like(f"%{search.lower()}%"))
    stmt = stmt.order_by(EacBlockGraph.updated_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return result.scalars().all()


async def count_graphs(
    session: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    project_id: uuid.UUID | None = None,
    rule_id: uuid.UUID | None = None,
    search: str | None = None,
    include_unscoped: bool = True,
) -> int:
    """Count the graphs :func:`list_graphs` would page through."""
    stmt = select(func.count(EacBlockGraph.id)).where(EacBlockGraph.tenant_id == tenant_id)
    if project_id is not None:
        if include_unscoped:
            stmt = stmt.where(
                or_(
                    EacBlockGraph.project_id == project_id,
                    EacBlockGraph.project_id.is_(None),
                )
            )
        else:
            stmt = stmt.where(EacBlockGraph.project_id == project_id)
    if rule_id is not None:
        stmt = stmt.where(EacBlockGraph.rule_id == rule_id)
    if search:
        stmt = stmt.where(func.lower(EacBlockGraph.name).like(f"%{search.lower()}%"))
    result = await session.execute(stmt)
    return int(result.scalar_one() or 0)


async def replace_graph_body(
    session: AsyncSession,
    graph: EacBlockGraph,
    blocks: Sequence[BlockWrite],
    connections: Sequence[ConnectionWrite],
) -> None:
    """Replace a graph's blocks and wires with the given snapshot.

    Ordinals are assigned 0..n-1 in the order received, so the "ordered set" is
    exactly the order the estimator's canvas produced. No fractional order key
    is used: whole-snapshot writes make explicit renumbering free, and a derived
    key eventually exhausts its precision under repeated insertion at one point.

    The existing rows go in one bulk DELETE each rather than through the
    relationship collection, so a graph with a few hundred blocks costs two
    statements instead of a per-row cascade.

    Two details make that safe in an async session, and both are easy to get
    wrong:

    * The deletes carry ``synchronize_session="fetch"`` so the ORM marks the
      matching in-memory children deleted. Without it they stay persistent
      ghosts in the identity map, still holding the ``(graph_id, client_id)``
      pair the new rows are about to reuse.
    * The collections are re-read with an awaited ``session.refresh`` rather
      than assigned. Assigning to a loaded collection makes SQLAlchemy load the
      current contents first to work out the orphans, and that load is emitted
      outside the greenlet, which is exactly the ``MissingGreenlet`` this
      codebase keeps meeting.

    Args:
        session: Active async session.
        graph: The graph being rewritten; must already be persistent.
        blocks: The new blocks, in canvas order.
        connections: The new wires, in canvas order.
    """
    await session.execute(
        delete(EacBlockConnection)
        .where(EacBlockConnection.graph_id == graph.id)
        .execution_options(synchronize_session="fetch")
    )
    await session.execute(
        delete(EacBlock).where(EacBlock.graph_id == graph.id).execution_options(synchronize_session="fetch")
    )
    await session.flush()

    for ordinal, block in enumerate(blocks):
        session.add(
            EacBlock(
                graph_id=graph.id,
                client_id=block.client_id,
                ordinal=ordinal,
                kind=block.kind,
                color=block.color,
                title=block.title,
                position_x=block.position.x,
                position_y=block.position.y,
                slots=[slot.model_dump(exclude_none=True) for slot in block.slots],
                params=dict(block.params),
            )
        )
    for ordinal, conn in enumerate(connections):
        session.add(
            EacBlockConnection(
                graph_id=graph.id,
                client_id=conn.client_id,
                ordinal=ordinal,
                source_block_client_id=conn.source_block_client_id,
                source_slot_id=conn.source_slot_id,
                target_block_client_id=conn.target_block_client_id,
                target_slot_id=conn.target_slot_id,
                data_type=conn.data_type,
            )
        )
    await session.flush()
    # The new children were added by graph_id, not appended to the collections,
    # so re-read them here. Doing it now, inside the await, is what lets the
    # router render the response synchronously afterwards.
    await session.refresh(graph, ["blocks", "connections"])


async def delete_graph(session: AsyncSession, graph: EacBlockGraph) -> None:
    """Delete a graph and, by cascade, its blocks and wires."""
    await session.delete(graph)
    await session.flush()


__all__ = [
    "count_graphs",
    "delete_graph",
    "get_graph",
    "list_graphs",
    "replace_graph_body",
]
