# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Connectors service: scan a watched folder and ingest new files as documents.

The pure normalization + dedup logic lives in
:mod:`app.modules.connectors.storage_connector`. This service supplies the IO
(walking the directory) and the persistence (creating a referencing
:class:`~app.modules.documents.models.Document` per new file and publishing the
standard ``documents.document.created`` event so the file is indexed for search
and shows on the timeline like any other document).

Dedup is idempotent: a file already imported by this source (matched on its
path or its content hash) is never imported twice, so re-syncing after no change
creates nothing.
"""

from __future__ import annotations

import logging
import mimetypes
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.connectors.models import ConnectorSource
from app.modules.connectors.storage_connector import (
    compute_sync_plan,
    hash_bytes,
    is_within_base,
    normalize_entry,
)
from app.modules.documents.models import Document

logger = logging.getLogger(__name__)

#: Marker key written into a Document's metadata so connector-created rows are
#: identifiable and can be deduplicated against on the next sync.
CONNECTOR_META_KEY = "connector"

#: Safety bounds for a folder scan so a misconfigured root cannot exhaust the
#: process: cap the number of files visited and the bytes read per file when
#: hashing (larger files fall back to a size signature for dedup).
MAX_FILES_PER_SYNC = 2000
MAX_HASH_BYTES = 8 * 1024 * 1024

#: Sub-directory (under the unified data root) that bounds every watched-folder
#: root when ``OE_CONNECTORS_BASE_DIR`` is not set.
_CONNECTORS_BASE_SUBDIR = "connectors_watch"


def _connectors_base_dir() -> Path:
    """Return the only directory tree a watched-folder root may live under.

    An operator can point this at a dedicated drop area with
    ``OE_CONNECTORS_BASE_DIR``; otherwise it is ``connectors_watch`` under the
    unified data root (:func:`app.core.storage.resolve_data_dir`, which honours
    ``OE_DATA_DIR`` / ``DATA_DIR`` / ``OE_CLI_DATA_DIR`` and the persistent
    per-user home for wheel installs). The directory is created if missing so a
    fresh install can register a source without manual setup.

    Resolved lazily, PER CALL (not at import time), so a test monkeypatch or an
    operator setting the env after import takes effect, and so this module is
    not import-coupled to ``app.config`` / Postgres. The returned path is
    canonicalized (symlinks resolved) so containment checks compare real paths.
    """
    raw = os.environ.get("OE_CONNECTORS_BASE_DIR")
    if raw and raw.strip():
        base = Path(raw.strip()).expanduser()
    else:
        from app.core.storage import resolve_data_dir

        base = resolve_data_dir() / _CONNECTORS_BASE_SUBDIR
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()


def _validate_root_path(root_path: str) -> str:
    """Confine a watched-folder root to the connectors base dir.

    Returns the stripped root unchanged when it is an absolute path whose real
    (symlink-resolved) location is the base dir or below it. Raises
    :class:`ValueError` otherwise - an empty/relative path, or one that escapes
    the base dir (for example ``/etc`` or a ``..`` traversal). Fail-closed: a
    root that cannot be resolved is rejected. Connectors shipped in v8.11.0 with
    no rows to migrate, so this can reject without back-compat concerns.
    """
    stripped = root_path.strip()
    candidate = Path(stripped)
    if not stripped or not candidate.is_absolute():
        raise ValueError("root_path must be an absolute path")
    base = _connectors_base_dir()
    try:
        resolved = candidate.resolve()
    except OSError as exc:
        raise ValueError("root_path could not be resolved") from exc
    if not is_within_base(base, resolved):
        raise ValueError("root_path must be inside the connectors base directory")
    return stripped


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _within(root: Path, candidate: Path) -> bool:
    """Whether ``candidate`` resolves to a path inside ``root`` (no escape)."""
    try:
        candidate.resolve().relative_to(root)
        return True
    except (ValueError, OSError):
        return False


def _file_signature(path: Path, size: int) -> str:
    """A content hash for ``path``: SHA-256 of bytes, or a size signature.

    Files up to ``MAX_HASH_BYTES`` are hashed by content so the same bytes under
    a new name are caught as duplicates. Larger files fall back to a cheap
    size-based signature (still stable for that file, just coarser for dedup).
    """
    if size > MAX_HASH_BYTES:
        return f"size:{size}"
    try:
        return hash_bytes(path.read_bytes())
    except OSError:
        return f"size:{size}"


def scan_watched_folder(root_path: str) -> list[dict]:
    """Walk ``root_path`` and return one raw listing entry per regular file.

    Confined to ``root_path``: a file that resolves outside the root (for
    example via a symlink) is skipped. Returns an empty list when the root is
    missing or is not a directory, so a misconfigured source syncs to nothing
    rather than raising.
    """
    if not root_path:
        return []
    root = Path(root_path)
    try:
        if not root.is_dir():
            return []
        root = root.resolve()
        # Re-assert containment at scan time, not only at create time: a root
        # that was inside the base dir when the source was registered could
        # later resolve outside it (a directory swapped for a symlink, or the
        # base dir narrowed). Fail-closed - sync nothing rather than walk an
        # escaped path.
        if not is_within_base(_connectors_base_dir(), root):
            logger.warning("connectors: scan root %s is outside the base dir; skipping", root)
            return []
    except OSError:
        return []

    entries: list[dict] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in sorted(filenames):
            if len(entries) >= MAX_FILES_PER_SYNC:
                logger.warning("connectors: scan hit the %d file cap at %s", MAX_FILES_PER_SYNC, root)
                return entries
            full = Path(dirpath) / filename
            try:
                if not full.is_file() or not _within(root, full):
                    continue
                stat = full.stat()
            except OSError:
                continue
            rel_folder = os.path.relpath(dirpath, root)
            entries.append(
                {
                    "name": filename,
                    "path": str(full),
                    "size": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
                    "content_hash": _file_signature(full, stat.st_size),
                    "type": mimetypes.guess_type(filename)[0] or "",
                    "folder": "" if rel_folder == "." else rel_folder,
                }
            )
    return entries


class ConnectorService:
    """Register inbound document sources and sync them into project documents."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_source(
        self,
        *,
        project_id: uuid.UUID,
        name: str,
        root_path: str,
        kind: str = "watched_folder",
        enabled: bool = True,
        created_by: str | None = None,
    ) -> ConnectorSource:
        source = ConnectorSource(
            project_id=project_id,
            name=name.strip(),
            root_path=_validate_root_path(root_path),
            kind=kind.strip() or "watched_folder",
            enabled=enabled,
            created_by=created_by,
        )
        self.session.add(source)
        await self.session.flush()
        return source

    async def list_sources(self, project_id: uuid.UUID) -> list[ConnectorSource]:
        stmt = (
            select(ConnectorSource)
            .where(ConnectorSource.project_id == project_id)
            .order_by(ConnectorSource.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_source(self, source_id: uuid.UUID) -> ConnectorSource | None:
        return (
            await self.session.execute(select(ConnectorSource).where(ConnectorSource.id == source_id))
        ).scalar_one_or_none()

    async def _known_for_source(self, source: ConnectorSource) -> tuple[set[str], set[str]]:
        """Return the external ids + content hashes this source already imported.

        Read from the connector marker on existing Document rows in the project,
        so a re-sync deduplicates against what is already on the record.
        """
        stmt = select(Document).where(Document.project_id == source.project_id)
        ids: set[str] = set()
        hashes: set[str] = set()
        for doc in (await self.session.execute(stmt)).scalars().all():
            meta = doc.metadata_ if isinstance(doc.metadata_, dict) else {}
            marker = meta.get(CONNECTOR_META_KEY)
            if not isinstance(marker, dict) or marker.get("source") != source.name:
                continue
            ext_id = marker.get("external_id")
            chash = marker.get("content_hash")
            if isinstance(ext_id, str) and ext_id:
                ids.add(ext_id)
            if isinstance(chash, str) and chash:
                hashes.add(chash)
        return ids, hashes

    async def sync_source(self, source: ConnectorSource, *, user_id: str | None = None) -> dict:
        """Scan the source and create a Document for each genuinely new file.

        Returns the partition summary (created / duplicate / already-known /
        total) plus the ids of the created documents. Idempotent: a second sync
        with no folder change creates nothing.
        """
        raw_entries = scan_watched_folder(source.root_path)
        incoming = [normalize_entry(entry, source=source.name) for entry in raw_entries]

        known_ids, known_hashes = await self._known_for_source(source)
        plan = compute_sync_plan(
            incoming,
            known_external_ids=known_ids,
            known_content_hashes=known_hashes,
        )

        created_ids: list[str] = []
        for inc in plan.to_create:
            document = Document(
                project_id=source.project_id,
                name=(inc.name or "(unnamed)")[:255],
                category="other",
                file_size=inc.size_bytes,
                mime_type=(inc.content_type or "")[:100],
                file_path=inc.external_id[:500],
                uploaded_by=user_id or "",
                metadata_={
                    CONNECTOR_META_KEY: {
                        "source": source.name,
                        "kind": source.kind,
                        "external_id": inc.external_id,
                        "content_hash": inc.content_hash,
                        "folder": inc.folder,
                    }
                },
            )
            self.session.add(document)
            await self.session.flush()
            created_ids.append(str(document.id))
            self._publish_created(source.project_id, document)

        result = {
            "source_id": str(source.id),
            "created": plan.created_count,
            "duplicate": plan.duplicate_count,
            "already_known": plan.known_count,
            "total": plan.total_count,
            "created_document_ids": created_ids,
        }
        source.last_synced_at = _iso_now()
        source.last_result = {
            "created": plan.created_count,
            "duplicate": plan.duplicate_count,
            "already_known": plan.known_count,
            "total": plan.total_count,
            "at": source.last_synced_at,
        }
        await self.session.flush()
        return result

    @staticmethod
    def _publish_created(project_id: uuid.UUID, document: Document) -> None:
        """Publish the standard document-created event (best-effort)."""
        try:
            from app.core.events import event_bus

            event_bus.publish_detached(
                "documents.document.created",
                {
                    "project_id": str(project_id),
                    "document_id": str(document.id),
                    "name": document.name,
                    "category": document.category,
                },
                source_module="oe_connectors",
            )
        except Exception as exc:  # pragma: no cover - best-effort signal
            logger.debug("connectors: failed to publish document.created: %s", exc)
