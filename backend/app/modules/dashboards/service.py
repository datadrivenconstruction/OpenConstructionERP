"""SnapshotService — the orchestration seam for T01.

Composes the repository, the cad2data bridge, the snapshot-storage
helper, the DuckDB pool, and the event bus. Other dashboards tasks
(T02 … T11) read from snapshots that this service produces; they
never bypass it.

Error contract
--------------
Methods raise typed exceptions from :mod:`.errors` rather than
``HTTPException``. The router layer maps them to localised HTTP
responses so the service stays usable from offline scripts and tests.
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.events import event_bus
from app.modules.dashboards import events as event_taxonomy
from app.modules.dashboards.cad2data_bridge import (
    BridgeError,
    NoEntitiesExtractedError,
    SnapshotBuildResult,
    UnsupportedFormatError,
    UploadedFile,
    convert_to_snapshot_frames,
)
from app.modules.dashboards.duckdb_pool import DuckDBPool
from app.modules.dashboards.models import Snapshot, SnapshotSourceFile
from app.modules.dashboards.repository import SnapshotRepository
from app.modules.dashboards.snapshot_storage import (
    delete_snapshot_files,
    snapshot_prefix,
    write_manifest,
    write_parquet,
)

logger = logging.getLogger(__name__)


# ── Error types ─────────────────────────────────────────────────────────────


class SnapshotError(Exception):
    """Base class for snapshot service errors.

    Each subclass carries a ``message_key`` that the router uses to
    localise the 4xx/5xx response body (see
    :class:`~.schemas.SnapshotErrorOut`).
    """

    http_status: int = 500
    message_key: str = "common.unknown_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class SnapshotLabelInvalidError(SnapshotError):
    http_status = 422
    message_key = "snapshot.label.required"


class SnapshotLabelTooLongError(SnapshotError):
    http_status = 422
    message_key = "snapshot.label.too_long"


class SnapshotLabelDuplicateError(SnapshotError):
    http_status = 409
    message_key = "snapshot.label.duplicate"


class SnapshotNotFoundError(SnapshotError):
    http_status = 404
    message_key = "snapshot.not_found"


class SnapshotAccessDeniedError(SnapshotError):
    http_status = 403
    message_key = "snapshot.access_denied"


class SnapshotUnsupportedFormatError(SnapshotError):
    http_status = 422
    message_key = "snapshot.format.unsupported"


class SnapshotConversionFailedError(SnapshotError):
    http_status = 422
    message_key = "snapshot.parquet.missing_entities"


# ── DTO for service-internal plumbing ──────────────────────────────────────


@dataclass
class CreateSnapshotArgs:
    project_id: uuid.UUID
    label: str
    files: list[UploadedFile]
    user_id: uuid.UUID
    tenant_id: str | None = None
    parent_snapshot_id: uuid.UUID | None = None


# ── Service ────────────────────────────────────────────────────────────────


class SnapshotService:
    """Orchestrate create/list/get/delete for snapshots.

    A fresh instance is constructed per request — it does not hold
    state between calls. ``session`` and ``pool`` are injected so tests
    can pass in-memory stand-ins.
    """

    MAX_LABEL_LENGTH = 200

    def __init__(
        self,
        repo: SnapshotRepository,
        pool: DuckDBPool | None = None,
    ) -> None:
        self.repo = repo
        self.pool = pool

    # -- create ------------------------------------------------------------

    async def create(self, args: CreateSnapshotArgs) -> Snapshot:
        """Create a new snapshot.

        Ordering is deliberate:

        1. Validate label (cheap — fail fast).
        2. Check unique-label in project.
        3. Run conversion (expensive — would be wasted work if step 4 fails).
        4. Write Parquet + manifest to storage.
        5. Insert DB row + source-file rows in one transaction.
        6. Publish ``snapshot.created`` event.

        If step 4 or 5 fails, we best-effort clean up the Parquet files
        so the storage doesn't accumulate orphans. The DB side is fine —
        the transaction is still open, so a failure rolls back cleanly.
        """
        # 1 + 2
        self._validate_label(args.label)
        existing = await self.repo.get_by_label(args.project_id, args.label)
        if existing is not None:
            raise SnapshotLabelDuplicateError(
                f"Snapshot '{args.label}' already exists in project {args.project_id}.",
                details={"project_id": str(args.project_id), "label": args.label},
            )

        # 3 — convert.
        try:
            build = convert_to_snapshot_frames(args.files)
        except UnsupportedFormatError as exc:
            raise SnapshotUnsupportedFormatError(str(exc)) from exc
        except NoEntitiesExtractedError as exc:
            raise SnapshotConversionFailedError(str(exc)) from exc
        except BridgeError as exc:
            raise SnapshotConversionFailedError(str(exc)) from exc

        snapshot_id = uuid.uuid4()

        # 4 — persist Parquet + manifest. If any write fails, clean up
        # best-effort before propagating.
        try:
            await self._persist_parquet(args.project_id, snapshot_id, build)
            await self._write_manifest_file(
                args.project_id, snapshot_id, args, build,
            )
        except Exception:
            await self._cleanup_storage_on_failure(args.project_id, snapshot_id)
            raise

        # 5 — persist DB rows. Session is flushed within the repo; the
        # outer router-level Session dependency owns the final commit.
        try:
            row = Snapshot(
                id=snapshot_id,
                project_id=args.project_id,
                tenant_id=args.tenant_id,
                label=args.label,
                parquet_dir=snapshot_prefix(args.project_id, snapshot_id),
                total_entities=build.total_entities,
                total_categories=build.total_categories,
                summary_stats=build.summary_stats,
                source_files_json=build.source_files_df.to_dict(orient="records"),
                parent_snapshot_id=args.parent_snapshot_id,
                created_by_user_id=args.user_id,
            )
            await self.repo.add(row)

            source_file_rows = _build_source_file_rows(snapshot_id, build)
            await self.repo.add_source_files(source_file_rows)
        except Exception:
            await self._cleanup_storage_on_failure(args.project_id, snapshot_id)
            raise

        # 6 — publish. Wrap in a try so a buggy handler never blocks the
        # HTTP response.
        try:
            await event_bus.publish(
                event_taxonomy.SNAPSHOT_CREATED,
                {
                    "snapshot_id": str(snapshot_id),
                    "project_id": str(args.project_id),
                    "label": args.label,
                    "total_entities": build.total_entities,
                    "total_categories": build.total_categories,
                    "tenant_id": args.tenant_id,
                },
                source_module=event_taxonomy.SOURCE_MODULE,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                "dashboards.snapshot.publish event failed for snapshot_id=%s: %s",
                snapshot_id, type(exc).__name__, exc_info=True,
            )

        return row

    # -- read --------------------------------------------------------------

    async def get(
        self, snapshot_id: uuid.UUID, *, tenant_id: str | None,
    ) -> Snapshot:
        row = await self.repo.get(snapshot_id, tenant_id=tenant_id)
        if row is None:
            raise SnapshotNotFoundError(
                f"Snapshot {snapshot_id} not found (or not accessible to this tenant).",
                details={"snapshot_id": str(snapshot_id)},
            )
        return row

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        tenant_id: str | None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[Snapshot], int]:
        return await self.repo.list_for_project(
            project_id, tenant_id=tenant_id, limit=limit, offset=offset,
        )

    async def list_source_files(
        self, snapshot_id: uuid.UUID,
    ) -> list[SnapshotSourceFile]:
        return await self.repo.list_source_files(snapshot_id)

    # -- delete ------------------------------------------------------------

    async def delete(
        self, snapshot_id: uuid.UUID, *, tenant_id: str | None,
    ) -> None:
        row = await self.get(snapshot_id, tenant_id=tenant_id)
        project_id = row.project_id

        # Invalidate the DuckDB warm connection (if any) first — if we
        # delete Parquet under a live connection, a racing query can
        # read partial data.
        if self.pool is not None:
            try:
                await self.pool.invalidate(snapshot_id)
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning(
                    "dashboards.snapshot.pool_invalidate failed for snapshot_id=%s: %s",
                    snapshot_id, type(exc).__name__, exc_info=True,
                )

        # DB row first, then storage. Orphan files are less dangerous
        # than orphan rows pointing at non-existent data.
        await self.repo.delete(row)

        try:
            await delete_snapshot_files(project_id, snapshot_id)
        except Exception as exc:
            # Storage cleanup is best-effort; log + let the request
            # succeed so the user doesn't see a false failure.
            logger.warning(
                "dashboards.snapshot.delete storage cleanup failed for "
                "snapshot_id=%s: %s", snapshot_id, type(exc).__name__,
                exc_info=True,
            )

        try:
            await event_bus.publish(
                event_taxonomy.SNAPSHOT_DELETED,
                {
                    "snapshot_id": str(snapshot_id),
                    "project_id": str(project_id),
                    "tenant_id": tenant_id,
                },
                source_module=event_taxonomy.SOURCE_MODULE,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                "dashboards.snapshot.publish delete event failed for "
                "snapshot_id=%s: %s", snapshot_id, type(exc).__name__,
                exc_info=True,
            )

    # -- helpers -----------------------------------------------------------

    def _validate_label(self, label: str) -> None:
        if not label or not label.strip():
            raise SnapshotLabelInvalidError(
                "Snapshot label is required.",
                details={"field": "label"},
            )
        if len(label) > self.MAX_LABEL_LENGTH:
            raise SnapshotLabelTooLongError(
                f"Snapshot label exceeds {self.MAX_LABEL_LENGTH} characters.",
                details={"field": "label", "max_length": self.MAX_LABEL_LENGTH},
            )

    async def _persist_parquet(
        self,
        project_id: uuid.UUID,
        snapshot_id: uuid.UUID,
        build: SnapshotBuildResult,
    ) -> None:
        await write_parquet(
            project_id, snapshot_id, "entities", build.entities_df,
        )
        if not build.materials_df.empty:
            await write_parquet(
                project_id, snapshot_id, "materials", build.materials_df,
            )
        if not build.source_files_df.empty:
            await write_parquet(
                project_id, snapshot_id, "source_files", build.source_files_df,
            )

    async def _write_manifest_file(
        self,
        project_id: uuid.UUID,
        snapshot_id: uuid.UUID,
        args: CreateSnapshotArgs,
        build: SnapshotBuildResult,
    ) -> None:
        manifest_payload: dict[str, Any] = {
            "snapshot_id": str(snapshot_id),
            "project_id": str(project_id),
            "label": args.label,
            "created_by_user_id": str(args.user_id),
            "created_at": datetime.now(UTC).isoformat(),
            "total_entities": build.total_entities,
            "total_categories": build.total_categories,
            "summary_stats": build.summary_stats,
            "source_files": json.loads(
                build.source_files_df.to_json(orient="records") or "[]"
            ),
            "converter_notes": build.converter_notes,
        }
        await write_manifest(project_id, snapshot_id, manifest_payload)

    async def _cleanup_storage_on_failure(
        self, project_id: uuid.UUID, snapshot_id: uuid.UUID,
    ) -> None:
        try:
            await delete_snapshot_files(project_id, snapshot_id)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                "dashboards.snapshot.create rollback cleanup failed for "
                "snapshot_id=%s: %s", snapshot_id, type(exc).__name__,
                exc_info=True,
            )


# ── Helpers ─────────────────────────────────────────────────────────────────


def _build_source_file_rows(
    snapshot_id: uuid.UUID,
    build: SnapshotBuildResult,
) -> list[SnapshotSourceFile]:
    """Convert the source-files DataFrame into ORM rows keyed by the
    per-file id so converter-notes line up with the right file."""
    rows: list[SnapshotSourceFile] = []
    notes_by_id = build.converter_notes

    for record in build.source_files_df.to_dict(orient="records"):
        source_id = record["id"]
        rows.append(
            SnapshotSourceFile(
                id=uuid.UUID(source_id),
                snapshot_id=snapshot_id,
                original_name=record["original_name"],
                format=record["format"],
                discipline=record.get("discipline"),
                entity_count=int(record.get("entity_count", 0)),
                bytes_size=int(record.get("bytes_size", 0)),
                converter_notes=notes_by_id.get(source_id, {}),
            )
        )
    return rows
