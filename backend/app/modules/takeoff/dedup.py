# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Startup heal: collapse duplicate from-source takeoff documents (issue #369).

``POST /documents/from-source`` find-or-creates a takeoff document by
``(project_id, source_document_id)``. It used to run an unlocked SELECT then an
INSERT, so two concurrent opens of the same Project-Files PDF could both miss
and both insert, minting duplicate ``oe_takeoff_document`` rows for one source.
Measurements and AI plan-read runs reference the document by its string id, so a
reader that resolved to a different duplicate than the one a measurement was
saved against saw the measurement vanish - it was stranded on an unreachable
row, never deleted.

A unique index on ``(project_id, source_document_id)`` now prevents new
duplicates, and the service resolves the losing insert to the winner. But the
index cannot be built on an already-populated database that still holds
duplicates, and embedded / stamped-alembic installs materialise it through the
startup schema heal (``postgres_auto_migrate``), not a data migration. So this
runs once at boot, right before that heal, to merge any pre-existing duplicates:
keep the oldest row per group as canonical, re-point its measurements and AI
runs, delete the newer duplicates and remove their orphaned PDF files.

Idempotent and cheap when there is nothing to merge (a single windowed scan that
returns no rows), so it is safe on every boot. PostgreSQL-only, matching the
rest of the runtime.
"""

import contextlib
import logging
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

logger = logging.getLogger(__name__)

# The canonical row per (project_id, source_document_id) group is the oldest one
# (created_at ASC), with the row id as a stable tie-breaker. Reused by the
# re-point and delete statements so they agree on the same winner.
_RANKED = """
    SELECT id, project_id, source_document_id,
           first_value(id) OVER w AS canonical_id
    FROM oe_takeoff_document
    WHERE source_document_id IS NOT NULL
    WINDOW w AS (
        PARTITION BY project_id, source_document_id
        ORDER BY created_at ASC, id ASC
    )
"""


async def collapse_duplicate_source_documents(conn: AsyncConnection) -> int:
    """Merge duplicate from-source takeoff documents into one canonical row.

    Args:
        conn: An open async PostgreSQL connection (inside a transaction).

    Returns:
        The number of duplicate rows collapsed (0 when the table is absent or
        already clean).
    """
    has_table = await conn.run_sync(lambda c: inspect(c).has_table("oe_takeoff_document"))
    if not has_table:
        # Fresh database: create_all has not built the table yet, so there is
        # nothing to merge and the index will be created clean.
        return 0

    # Non-canonical duplicates, each with its canonical target and on-disk file
    # so the orphaned PDFs can be removed after the rows are deleted.
    dupes = (
        await conn.execute(
            text(
                """
                SELECT id, canonical_id, file_path
                FROM (
                    SELECT id, file_path,
                           row_number() OVER w AS rn,
                           first_value(id) OVER w AS canonical_id
                    FROM oe_takeoff_document
                    WHERE source_document_id IS NOT NULL
                    WINDOW w AS (
                        PARTITION BY project_id, source_document_id
                        ORDER BY created_at ASC, id ASC
                    )
                ) ranked
                WHERE rn > 1
                """  # noqa: S608 - no user input, fixed table/column names
            )
        )
    ).fetchall()
    if not dupes:
        return 0

    # Re-point the children to the canonical row. Both tables store the document
    # id as a plain string (the GUID type is VARCHAR(36)), so a string equality
    # join is exact. Set-based: one statement covers every group.
    await conn.execute(
        text(
            f"""
            UPDATE oe_takeoff_measurement AS m
            SET document_id = r.canonical_id
            FROM ({_RANKED}) r
            WHERE m.document_id = r.id AND r.id <> r.canonical_id
            """  # noqa: S608
        )
    )
    await conn.execute(
        text(
            f"""
            UPDATE oe_ai_takeoff_run AS a
            SET document_id = r.canonical_id
            FROM ({_RANKED}) r
            WHERE a.document_id = r.id AND r.id <> r.canonical_id
            """  # noqa: S608
        )
    )
    await conn.execute(
        text(
            f"""
            DELETE FROM oe_takeoff_document AS d
            USING ({_RANKED}) r
            WHERE d.id = r.id AND r.id <> r.canonical_id
            """  # noqa: S608
        )
    )

    # Best-effort removal of the orphaned PDF bytes the deleted duplicates left
    # on disk. A missing or unremovable file is never fatal - the row is already
    # gone, which is what protects the data.
    for row in dupes:
        if row.file_path:
            with contextlib.suppress(OSError):
                Path(row.file_path).unlink()

    logger.info(
        "takeoff.dedup: collapsed %d duplicate from-source document(s) into their canonical rows",
        len(dupes),
    )
    return len(dupes)
