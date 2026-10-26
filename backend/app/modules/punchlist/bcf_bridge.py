# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Punch items as BCF topics, through the bcf module's codec.

Export writes one topic per punch item into a standard ``.bcfzip``; import reads
one back. Identity is the point of the exercise: the topic GUID *is* the punch
item id, each photo travels as a viewpoint snapshot whose GUID is derived from
the item id and the photo path, and each photo's evidence line travels as a
comment with a derived GUID. Exporting, editing the topics in another BCF tool
and importing again therefore updates the same items and never duplicates a
photo or an evidence comment.

Status changes coming back from BCF are applied only where they need no sign-off
in this app (open, assigned, in progress, resolved). A topic that comes back
verified or closed is reported for review instead: verification is a four-eyes
act here and a file from elsewhere cannot perform it.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.punchlist.models import PunchItem

logger = logging.getLogger(__name__)

#: Label every exported topic carries so an import can tell punch topics apart.
PUNCH_LABEL = "punchlist"
#: Most photos exported per item (each becomes one viewpoint with a snapshot).
MAX_PHOTOS_PER_TOPIC = 10
#: ``metadata`` key on a punch item holding comments imported from BCF.
BCF_META_KEY = "bcf"

_STATUS_TO_BCF: dict[str, str] = {
    "open": "Open",
    "assigned": "Assigned",
    "in_progress": "In Progress",
    "resolved": "Resolved",
    "verified": "Verified",
    "closed": "Closed",
}
_BCF_TO_STATUS: dict[str, str] = {
    "open": "open",
    "new": "open",
    "reopened": "open",
    "assigned": "assigned",
    "in progress": "in_progress",
    "inprogress": "in_progress",
    "active": "in_progress",
    "resolved": "resolved",
    "done": "resolved",
    "fixed": "resolved",
    "verified": "verified",
    "closed": "closed",
}
#: Statuses an import may set directly; the rest need a sign-off in the app.
_IMPORT_SETTABLE = frozenset({"open", "assigned", "in_progress", "resolved"})

_PRIORITY_TO_BCF = {"low": "Low", "medium": "Normal", "high": "High", "critical": "Critical"}
_BCF_TO_PRIORITY = {
    "low": "low",
    "minor": "low",
    "normal": "medium",
    "medium": "medium",
    "high": "high",
    "major": "high",
    "critical": "critical",
    "blocker": "critical",
}

_SNAPSHOT_EXT = {"png": ".png", "jpeg": ".jpg", "jpg": ".jpg"}


def status_to_bcf(status: str | None) -> str:
    """Punch status -> BCF TopicStatus text."""
    return _STATUS_TO_BCF.get((status or "open").lower(), "Open")


def status_from_bcf(raw: str | None) -> str | None:
    """BCF TopicStatus text -> punch status, or ``None`` when unknown."""
    if not raw:
        return None
    return _BCF_TO_STATUS.get(raw.strip().lower().replace("_", " "))


def priority_to_bcf(priority: str | None) -> str:
    """Punch priority -> BCF Priority text."""
    return _PRIORITY_TO_BCF.get((priority or "medium").lower(), "Normal")


def priority_from_bcf(raw: str | None) -> str | None:
    """BCF Priority text -> punch priority, or ``None`` when unknown."""
    if not raw:
        return None
    return _BCF_TO_PRIORITY.get(raw.strip().lower())


def photo_viewpoint_guid(item_id: uuid.UUID | str, photo_path: str) -> str:
    """Stable viewpoint GUID for one photo of one item."""
    return str(uuid.uuid5(uuid.UUID(str(item_id)), f"photo:{photo_path}"))


def evidence_comment_guid(item_id: uuid.UUID | str, photo_path: str) -> str:
    """Stable comment GUID for the evidence line of one photo."""
    return str(uuid.uuid5(uuid.UUID(str(item_id)), f"evidence:{photo_path}"))


def _as_uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return None


def _as_aware(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


@dataclass
class PunchBcfImportReport:
    """Outcome of one punch BCF import."""

    status: str = "passed"
    created: int = 0
    updated: int = 0
    photos_added: int = 0
    comments_added: int = 0
    skipped: int = 0
    item_ids: list[str] = field(default_factory=list)
    issues: list[dict[str, str]] = field(default_factory=list)

    def warn(self, code: str, message: str, guid: str | None = None) -> None:
        self.issues.append({"severity": "warning", "code": code, "message": message, "guid": guid or ""})

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "created": self.created,
            "updated": self.updated,
            "photos_added": self.photos_added,
            "comments_added": self.comments_added,
            "skipped": self.skipped,
            "item_ids": self.item_ids,
            "issues": self.issues,
        }


def _topic_for_item(item: PunchItem, author: str, photo_blobs: dict[str, bytes]) -> Any:
    from app.modules.bcf import bcf_xml
    from app.modules.punchlist.service import PHOTO_EVIDENCE_KEY, evidence_caption

    labels = [PUNCH_LABEL]
    for extra in (item.category, item.trade):
        if extra and extra not in labels:
            labels.append(extra)
    meta = item.metadata_ if isinstance(item.metadata_, dict) else {}
    topic = bcf_xml.ParsedTopic(
        guid=str(item.id),
        title=item.title,
        description=item.description or None,
        topic_type="Punch item",
        topic_status=status_to_bcf(item.status),
        priority=priority_to_bcf(item.priority),
        index=None,
        assigned_to=item.assigned_to,
        due_date=_as_aware(item.due_date),
        labels=labels,
        creation_author=item.created_by or author,
        creation_date=_as_aware(item.created_at),
        modified_author=author,
        modified_date=_as_aware(item.updated_at),
    )
    records = meta.get(PHOTO_EVIDENCE_KEY) if isinstance(meta.get(PHOTO_EVIDENCE_KEY), dict) else {}
    for idx, path in enumerate(list(item.photos or [])[:MAX_PHOTOS_PER_TOPIC]):
        vp_guid = photo_viewpoint_guid(item.id, path)
        blob = photo_blobs.get(path)
        vp = bcf_xml.ParsedViewpoint(guid=vp_guid)
        if blob is not None:
            ext = Path(path).suffix.lower() or ".jpg"
            vp.snapshot_filename = f"snapshot_{idx + 1}{ext}"
            vp.snapshot_bytes = blob
        topic.viewpoints.append(vp)
        record = records.get(path) if isinstance(records, dict) else None
        if isinstance(record, dict):
            line = evidence_caption(record)
            if line:
                topic.comments.append(
                    bcf_xml.ParsedComment(
                        guid=evidence_comment_guid(item.id, path),
                        comment=f"Photo evidence: {line}",
                        author=author,
                        date=_as_aware(item.updated_at),
                        viewpoint_guid=vp_guid,
                    )
                )
    for stored in (
        (meta.get(BCF_META_KEY) or {}).get("comments", []) if isinstance(meta.get(BCF_META_KEY), dict) else []
    ):
        if not isinstance(stored, dict) or not stored.get("guid"):
            continue
        topic.comments.append(
            bcf_xml.ParsedComment(
                guid=str(stored["guid"]),
                comment=str(stored.get("text") or ""),
                author=stored.get("author"),
                date=_parse_iso(stored.get("date")),
            )
        )
    return topic


def _parse_iso(raw: Any) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return _as_aware(datetime.fromisoformat(raw.replace("Z", "+00:00")))
    except ValueError:
        return None


async def _project_name(session: AsyncSession, project_id: uuid.UUID) -> str:
    try:
        from app.modules.projects.repository import ProjectRepository

        project = await ProjectRepository(session).get_by_id(project_id)
        return getattr(project, "name", None) or str(project_id)
    except Exception:  # noqa: BLE001 - name is cosmetic
        return str(project_id)


async def export_punch_bcf(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    item_ids: Sequence[uuid.UUID] | None = None,
    version: str = "2.1",
    author: str = "",
) -> tuple[bytes, int]:
    """Build a ``.bcfzip`` with one topic per punch item of the project.

    Args:
        session: Database session.
        project_id: Project whose items are exported.
        item_ids: Optional selection; ``None`` exports every item.
        version: BCF version, ``"2.1"`` or ``"3.0"``.
        author: Label written as modification author.

    Returns:
        ``(archive_bytes, topic_count)``.

    Raises:
        ValueError: unsupported version, or a selection that matches nothing.
    """
    from app.modules.bcf import bcf_xml
    from app.modules.punchlist.service import _resolve_photo_path

    if version not in bcf_xml.SUPPORTED_VERSIONS:
        raise ValueError(f"Unsupported BCF version {version!r}")
    stmt = select(PunchItem).where(PunchItem.project_id == project_id).order_by(PunchItem.created_at)
    if item_ids is not None:
        stmt = stmt.where(PunchItem.id.in_(list(item_ids)))
    items = list((await session.execute(stmt)).scalars().all())
    if item_ids is not None and not items:
        raise ValueError("No punch items matched the selection")

    def _read_blobs() -> dict[uuid.UUID, dict[str, bytes]]:
        out: dict[uuid.UUID, dict[str, bytes]] = {}
        for it in items:
            blobs: dict[str, bytes] = {}
            for path in list(it.photos or [])[:MAX_PHOTOS_PER_TOPIC]:
                disk = _resolve_photo_path(path)
                if disk is None:
                    continue
                try:
                    blobs[path] = disk.read_bytes()
                except OSError:
                    continue
            out[it.id] = blobs
        return out

    blobs = await asyncio.to_thread(_read_blobs)
    topics = [_topic_for_item(it, author, blobs.get(it.id, {})) for it in items]
    name = await _project_name(session, project_id)
    archive = await asyncio.to_thread(
        bcf_xml.build_bcfzip, version=version, project_id=str(project_id), project_name=name, topics=topics
    )
    return archive, len(topics)


def _known_guids(item: PunchItem) -> tuple[set[str], set[str]]:
    """Viewpoint and comment GUIDs this item already carries."""
    viewpoints = {photo_viewpoint_guid(item.id, p) for p in (item.photos or [])}
    comments = {evidence_comment_guid(item.id, p) for p in (item.photos or [])}
    meta = item.metadata_ if isinstance(item.metadata_, dict) else {}
    bcf_meta = meta.get(BCF_META_KEY) if isinstance(meta.get(BCF_META_KEY), dict) else {}
    for c in bcf_meta.get("comments", []) or []:
        if isinstance(c, dict) and c.get("guid"):
            comments.add(str(c["guid"]))
    viewpoints.update(str(g) for g in bcf_meta.get("viewpoints", []) or [])
    return viewpoints, comments


def _store_snapshot(item_id: uuid.UUID, blob: bytes, user_id: str | None) -> tuple[str, dict[str, Any]] | None:
    """Write an imported snapshot as a punch photo; ``None`` when not an image."""
    from app.core.file_signature import ALLOWED_PHOTO_TYPES, SIGNATURE_BYTES_REQUIRED, detect
    from app.core.photo_evidence import build_evidence_record, prepare_stored_photo
    from app.core.storage import module_uploads_dir

    photos_dir = module_uploads_dir("punchlist", "photos")
    kind = detect(blob[:SIGNATURE_BYTES_REQUIRED])
    if kind is None or kind not in ALLOWED_PHOTO_TYPES:
        return None
    stored, exif, original_sha = prepare_stored_photo(blob)
    ext = _SNAPSHOT_EXT.get(str(kind).lower(), ".img")
    filename = f"{item_id}_{uuid.uuid4().hex[:8]}{ext}"
    photos_dir.mkdir(parents=True, exist_ok=True)
    (photos_dir / filename).write_bytes(stored)
    path = f"punchlist/photos/{filename}"
    record = build_evidence_record(stored, path=path, exif=exif, uploaded_by=user_id, original_sha256=original_sha)
    record["imported_from"] = "bcf"
    return path, record


async def import_punch_bcf(
    session: AsyncSession,
    project_id: uuid.UUID,
    data: bytes,
    *,
    user_id: str | None,
    only_labelled: bool = False,
) -> PunchBcfImportReport:
    """Create or update punch items from a ``.bcfzip``.

    A topic whose GUID is the id of a punch item in this project updates that
    item; any other topic creates an item with the topic GUID as its id when
    the GUID is a free UUID (otherwise a fresh id, reported). With
    ``only_labelled`` the import ignores topics without the punch label, for
    mixed archives that also carry coordination issues.
    """
    from app.modules.bcf import bcf_xml
    from app.modules.punchlist.service import PHOTO_EVIDENCE_KEY

    report = PunchBcfImportReport()
    try:
        parsed = bcf_xml.parse_bcfzip(data)
    except bcf_xml.BCFParseError as exc:
        report.status = "errors"
        report.issues.append({"severity": "error", "code": "archive_invalid", "message": str(exc), "guid": ""})
        return report
    for issue in parsed.issues:
        report.issues.append(
            {"severity": issue.severity, "code": issue.code, "message": issue.message, "guid": issue.location or ""}
        )
    if parsed.has_errors:
        report.status = "errors"
        return report

    now_iso = datetime.now(UTC).isoformat()
    for topic in parsed.topics:
        if only_labelled and PUNCH_LABEL not in (topic.labels or []):
            report.skipped += 1
            continue
        topic_uuid = _as_uuid(topic.guid)
        item = await session.get(PunchItem, topic_uuid) if topic_uuid else None
        if item is not None and item.project_id != project_id:
            report.warn("foreign_item", "Topic id belongs to another project; imported as a new item", topic.guid)
            item = None
            topic_uuid = None

        if item is None:
            item = PunchItem(
                id=topic_uuid or uuid.uuid4(),
                project_id=project_id,
                title=(topic.title or "Untitled")[:255],
                description=topic.description or "",
                priority=priority_from_bcf(topic.priority) or "medium",
                status="open",
                created_by=user_id,
                photos=[],
                metadata_={},
                reopen_history=[],
            )
            if topic_uuid is None:
                report.warn("new_id", "Topic GUID is not a UUID; the item got a new id", topic.guid)
            session.add(item)
            await session.flush()
            report.created += 1
        else:
            item.title = (topic.title or item.title)[:255]
            item.description = topic.description or ""
            mapped_priority = priority_from_bcf(topic.priority)
            if mapped_priority:
                item.priority = mapped_priority
            report.updated += 1

        if topic.assigned_to is not None:
            item.assigned_to = topic.assigned_to[:36] or None
        if topic.due_date is not None:
            item.due_date = topic.due_date
        target = status_from_bcf(topic.topic_status)
        if target and target != item.status:
            if target in _IMPORT_SETTABLE:
                item.status = target
                if target == "resolved" and item.resolved_at is None:
                    item.resolved_at = datetime.now(UTC)
            else:
                report.warn(
                    "status_needs_signoff",
                    f"Topic is '{topic.topic_status}'; verify or close the item in the app",
                    topic.guid,
                )

        meta = dict(item.metadata_ or {})
        bcf_meta = dict(meta.get(BCF_META_KEY) or {})
        known_vps, known_comments = _known_guids(item)
        photos = list(item.photos or [])
        evidence = dict(meta.get(PHOTO_EVIDENCE_KEY) or {})
        imported_vps = list(bcf_meta.get("viewpoints") or [])
        for vp in topic.viewpoints:
            if vp.guid in known_vps or not vp.snapshot_bytes:
                continue
            stored = await asyncio.to_thread(_store_snapshot, item.id, vp.snapshot_bytes, user_id)
            if stored is None:
                report.warn("snapshot_not_image", "Viewpoint snapshot is not a supported image", topic.guid)
                continue
            path, record = stored
            photos.append(path)
            evidence[path] = record
            imported_vps.append(vp.guid)
            report.photos_added += 1
        comments = list(bcf_meta.get("comments") or [])
        for c in topic.comments:
            if not c.guid or c.guid in known_comments:
                continue
            comments.append(
                {
                    "guid": c.guid,
                    "author": c.author,
                    "date": c.date.isoformat() if c.date else None,
                    "text": c.comment,
                }
            )
            report.comments_added += 1
        bcf_meta.update({"comments": comments, "viewpoints": imported_vps, "last_import_at": now_iso})
        meta[BCF_META_KEY] = bcf_meta
        if evidence:
            meta[PHOTO_EVIDENCE_KEY] = evidence
        item.metadata_ = meta
        item.photos = photos
        report.item_ids.append(str(item.id))
        await session.flush()

    if any(i["severity"] == "error" for i in report.issues):
        report.status = "errors"
    elif report.issues:
        report.status = "warnings"
    return report
