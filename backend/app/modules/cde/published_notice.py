# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tell the people whose work hangs off a container that it was published.

Publishing a container (ISO 19650 Gate B, shared -> published) is the moment a
drawing or specification becomes the version a site is built from. Somebody
who measured quantities off an earlier revision, linked a BOQ position to it,
or planned an activity around those positions needs to know that the document
under their work has moved, because their numbers may now be stale. Until now
the published event reached only the outgoing webhooks, so inside the
platform nobody was told.

What a published container carries
----------------------------------
A container is a list of revisions, and each revision may cross-link a
Documents hub row through ``DocumentRevision.document_id``. Every revision
counts, not just the current one: a measurement drawn on P01 is exactly the
record that needs a nudge when C01 is published.

Who owns a linked record
------------------------
Read off the records themselves, scoped to the container's project:

``takeoff_measurement``
    ``TakeoffMeasurement.created_by`` where the measurement's ``document_id``
    is one of the container's documents, or a takeoff document opened from
    one of them (``TakeoffDocument.source_document_id``). Both shapes are
    written in practice, so both are matched.
``<target_type>`` from ``oe_file_reference``
    A deliberate file -> record link (``boq_position``, ``rfi``, ``task`` ...)
    on one of the container's documents. The owner is whoever made the link.
``schedule_activity``
    An activity whose ``boq_position_ids`` holds a position reached by either
    route above. The owner is the schedule's ``created_by``.

BOQ positions carry no owner column of their own, so a position reaches a
person only through the link or the measurement that ties it to the
document. That is a deliberate reading, not a gap papered over.

Only current project members (the owner counts) are notified, and never the
person who published: they already know.

Idempotency
-----------
One notification per recipient per container revision. The key is the
container id in ``entity_id`` plus ``metadata.revision_id``, and on
PostgreSQL a transaction-scoped advisory lock on that pair makes two
concurrent deliveries of the same event queue behind each other instead of
both finding nothing and both writing.

The tables of other modules are reached through :data:`Base.metadata` rather
than imported, the way :mod:`app.modules.documents.references` does it, so a
deployment without takeoff, schedule or file references simply has fewer
routes to an owner instead of failing.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from collections import defaultdict
from typing import Any

from sqlalchemy import Table, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base
from app.modules.cde.models import DocumentContainer, DocumentRevision

logger = logging.getLogger(__name__)

NOTIFICATION_TYPE = "cde_linked_published"
ENTITY_TYPE = "cde_container"
TITLE_KEY = "notifications.cde.linked_published.title"
BODY_KEY = "notifications.cde.linked_published.body"

#: Revision key used when a published container has no revision at all. Such a
#: container links no document, so it never reaches anyone; the key only keeps
#: the metadata shape uniform.
_NO_REVISION = "none"


def _table(name: str, *columns: str) -> Table | None:
    """Return the table when it is installed and carries every named column."""
    table = Base.metadata.tables.get(name)
    if table is None:
        return None
    if any(col not in table.c for col in columns):
        logger.debug("cde published notice: %s lacks one of %s", name, columns)
        return None
    return table


def _as_uuid(value: Any) -> uuid.UUID | None:
    """Parse a user id that may be stored as a GUID or a free string."""
    if value is None or value == "":
        return None
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


async def container_document_ids(session: AsyncSession, container_id: uuid.UUID) -> set[str]:
    """Every Documents hub id any revision of the container cross-links."""
    rows = await session.execute(
        select(DocumentRevision.document_id).where(
            DocumentRevision.container_id == container_id,
            DocumentRevision.document_id.is_not(None),
        )
    )
    return {str(doc_id) for doc_id in rows.scalars().all() if doc_id}


async def collect_linked_record_owners(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    document_ids: set[str],
) -> dict[uuid.UUID, dict[str, int]]:
    """Map each owner to how many of their records reference ``document_ids``.

    Returns ``{user_id: {kind: count}}``. A record is counted once per owner
    however many routes reach it.
    """
    if not document_ids:
        return {}

    owned: dict[uuid.UUID, set[tuple[str, str]]] = defaultdict(set)
    position_ids: set[str] = set()
    project_key = str(project_id)

    # ── Takeoff: measurements on the document or on a takeoff copy of it ──
    measurement_doc_ids = set(document_ids)
    takeoff_docs = _table("oe_takeoff_document", "id", "project_id", "source_document_id")
    if takeoff_docs is not None:
        rows = await session.execute(
            select(takeoff_docs.c.id).where(
                takeoff_docs.c.project_id == project_key,
                takeoff_docs.c.source_document_id.in_(sorted(document_ids)),
            )
        )
        measurement_doc_ids.update(str(row_id) for row_id in rows.scalars().all())

    measurements = _table(
        "oe_takeoff_measurement",
        "id",
        "project_id",
        "document_id",
        "created_by",
        "linked_boq_position_id",
    )
    if measurements is not None:
        rows = await session.execute(
            select(
                measurements.c.id,
                measurements.c.created_by,
                measurements.c.linked_boq_position_id,
            ).where(
                measurements.c.project_id == project_key,
                measurements.c.document_id.in_(sorted(measurement_doc_ids)),
            )
        )
        for row_id, created_by, position_id in rows.all():
            if position_id:
                position_ids.add(str(position_id))
            owner = _as_uuid(created_by)
            if owner is not None:
                owned[owner].add(("takeoff_measurement", str(row_id)))

    # ── Deliberate file -> record links ──────────────────────────────────
    file_refs = _table(
        "oe_file_reference",
        "project_id",
        "file_kind",
        "file_id",
        "target_type",
        "target_id",
        "created_by_id",
    )
    if file_refs is not None:
        rows = await session.execute(
            select(
                file_refs.c.target_type,
                file_refs.c.target_id,
                file_refs.c.created_by_id,
            ).where(
                file_refs.c.project_id == project_key,
                file_refs.c.file_kind == "document",
                file_refs.c.file_id.in_(sorted(document_ids)),
            )
        )
        for target_type, target_id, created_by in rows.all():
            if target_type == "boq_position" and target_id:
                position_ids.add(str(target_id))
            owner = _as_uuid(created_by)
            if owner is not None and target_type and target_id:
                owned[owner].add((str(target_type), str(target_id)))

    # ── Schedule activities planned on an affected position ──────────────
    schedules = _table("oe_schedule_schedule", "id", "project_id", "created_by")
    activities = _table("oe_schedule_activity", "id", "schedule_id", "boq_position_ids")
    if position_ids and schedules is not None and activities is not None:
        rows = await session.execute(
            select(
                activities.c.id,
                activities.c.boq_position_ids,
                schedules.c.created_by,
            )
            .join(schedules, schedules.c.id == activities.c.schedule_id)
            .where(schedules.c.project_id == project_key)
        )
        for row_id, linked, created_by in rows.all():
            # JSON, not JSONB, so containment is matched here rather than in
            # SQL. Scoped to one project's schedules, which bounds the scan.
            if not isinstance(linked, list):
                continue
            if not any(str(pid) in position_ids for pid in linked):
                continue
            owner = _as_uuid(created_by)
            if owner is not None:
                owned[owner].add(("schedule_activity", str(row_id)))

    result: dict[uuid.UUID, dict[str, int]] = {}
    for owner, records in owned.items():
        by_kind: dict[str, int] = defaultdict(int)
        for kind, _record_id in records:
            by_kind[kind] += 1
        result[owner] = dict(sorted(by_kind.items()))
    return result


def _lock_key(container_id: uuid.UUID, revision_key: str) -> int:
    """A signed 64-bit advisory-lock key for one container revision."""
    digest = hashlib.sha256(f"cde-published:{container_id}:{revision_key}".encode()).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


async def _already_notified(session: AsyncSession, container_id: uuid.UUID, revision_key: str) -> set[str]:
    """User ids already told about this container revision."""
    from app.modules.notifications.models import Notification

    rows = await session.execute(
        select(Notification.user_id, Notification.metadata_).where(
            Notification.notification_type == NOTIFICATION_TYPE,
            Notification.entity_type == ENTITY_TYPE,
            Notification.entity_id == str(container_id),
        )
    )
    return {str(user_id) for user_id, metadata in rows.all() if (metadata or {}).get("revision_id") == revision_key}


async def notify_linked_record_owners(
    session: AsyncSession,
    container_id: uuid.UUID,
    *,
    promoted_by: Any = None,
) -> list[uuid.UUID]:
    """Notify the owners of records linked to a published container.

    Writes into ``session`` and leaves the commit to the caller. Returns the
    users notified by this call, which is empty on a replay.
    """
    container = await session.get(DocumentContainer, container_id)
    if container is None:
        logger.debug("cde published notice: container %s is gone", container_id)
        return []
    if container.cde_state != "published":
        # The event is a claim about state; the row is the fact. A replay
        # after the container moved on to archived tells nobody anything new.
        logger.debug("cde published notice: container %s is %s", container_id, container.cde_state)
        return []

    document_ids = await container_document_ids(session, container_id)
    owners = await collect_linked_record_owners(
        session,
        project_id=container.project_id,
        document_ids=document_ids,
    )
    publisher = _as_uuid(promoted_by)
    if publisher is not None:
        owners.pop(publisher, None)
    if not owners:
        return []

    from app.modules.documents.folder_permissions_service import is_project_member

    members = {
        owner: by_kind
        for owner, by_kind in owners.items()
        if await is_project_member(session, container.project_id, owner)
    }
    if not members:
        return []

    revision_key = str(container.current_revision_id) if container.current_revision_id else _NO_REVISION
    revision_code = ""
    current_revision = _as_uuid(container.current_revision_id)
    if current_revision is not None:
        revision = await session.get(DocumentRevision, current_revision)
        if revision is not None:
            revision_code = revision.revision_code

    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        await session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": _lock_key(container_id, revision_key)},
        )
    done = await _already_notified(session, container_id, revision_key)

    from app.modules.notifications.service import NotificationService

    svc = NotificationService(session)
    notified: list[uuid.UUID] = []
    for owner in sorted(members, key=str):
        if str(owner) in done:
            continue
        by_kind = members[owner]
        await svc.create(
            user_id=owner,
            notification_type=NOTIFICATION_TYPE,
            title_key=TITLE_KEY,
            body_key=BODY_KEY,
            body_context={
                "container_code": container.container_code,
                "revision_code": revision_code or "-",
                "records": sum(by_kind.values()),
            },
            entity_type=ENTITY_TYPE,
            entity_id=str(container_id),
            action_url=f"/projects/{container.project_id}/cde?container={container_id}",
            metadata={
                "project_id": str(container.project_id),
                "revision_id": revision_key,
                "revision_code": revision_code,
                "records_by_kind": by_kind,
            },
        )
        notified.append(owner)

    logger.info(
        "cde published notice: container %s revision %s, %d notified, %d already told",
        container.container_code,
        revision_key,
        len(notified),
        len(done & {str(m) for m in members}),
    )
    return notified
