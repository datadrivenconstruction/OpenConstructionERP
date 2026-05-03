"""Service layer for dashboard presets / collections (T05).

Owns:

* CRUD on :class:`DashboardPreset` rows.
* "Share with project" toggle — flips ``shared_with_project`` and
  promotes ``kind='preset'`` to ``kind='collection'`` on the same call
  (a private preset can't be "half-shared").
* Authorisation checks: only the owner can update/delete; others can
  read collections that are shared with their project.
* Event emission via :mod:`.events`.

Errors mirror the snapshot service: typed exceptions carrying a
``message_key`` so the router can localise responses.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from app.core.events import event_bus
from app.modules.dashboards import events as event_taxonomy
from app.modules.dashboards.models import DashboardPreset
from app.modules.dashboards.presets_repository import DashboardPresetRepository

logger = logging.getLogger(__name__)


# ── Errors ──────────────────────────────────────────────────────────────────


class PresetError(Exception):
    """Base class for preset service errors."""

    http_status: int = 500
    message_key: str = "common.unknown_error"

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.details = details or {}


class PresetNotFoundError(PresetError):
    http_status = 404
    message_key = "preset.not_found"


class PresetAccessDeniedError(PresetError):
    http_status = 403
    message_key = "preset.access_denied"


class PresetValidationError(PresetError):
    http_status = 422
    message_key = "preset.validation_failed"


# ── DTO ─────────────────────────────────────────────────────────────────────


@dataclass
class CreatePresetArgs:
    name: str
    owner_id: uuid.UUID
    description: str | None = None
    kind: str = "preset"
    project_id: uuid.UUID | None = None
    config_json: dict[str, Any] | None = None
    shared_with_project: bool = False
    tenant_id: str | None = None


# ── Service ────────────────────────────────────────────────────────────────


class DashboardPresetService:
    MAX_NAME_LENGTH = 200
    MAX_DESCRIPTION_LENGTH = 2000
    ALLOWED_KINDS = ("preset", "collection")

    def __init__(self, repo: DashboardPresetRepository) -> None:
        self.repo = repo

    # -- create ------------------------------------------------------------

    async def create(self, args: CreatePresetArgs) -> DashboardPreset:
        self._validate_name(args.name)
        self._validate_kind(args.kind)
        self._validate_description(args.description)

        # A bare 'preset' that has shared_with_project=True is
        # nonsensical — auto-promote to 'collection' so the data shape
        # is internally consistent.
        kind = args.kind
        if args.shared_with_project and kind == "preset":
            kind = "collection"

        row = DashboardPreset(
            id=uuid.uuid4(),
            tenant_id=args.tenant_id,
            project_id=args.project_id,
            owner_id=args.owner_id,
            name=args.name.strip(),
            description=(args.description or "").strip() or None,
            kind=kind,
            config_json=args.config_json or {},
            shared_with_project=bool(args.shared_with_project),
        )
        await self.repo.add(row)

        await self._publish_saved(row)
        return row

    # -- read --------------------------------------------------------------

    async def get(
        self,
        preset_id: uuid.UUID,
        *,
        owner_id: uuid.UUID,
        tenant_id: str | None,
    ) -> DashboardPreset:
        """Read by id with project-collection visibility rules.

        The owner can always see their own rows. Non-owners can see the
        row if it's a shared collection; otherwise they get a 404
        (deliberately not 403 — leaking the existence of the row would
        let an attacker probe shared-vs-private status).
        """
        row = await self.repo.get(preset_id, tenant_id=tenant_id)
        if row is None:
            raise PresetNotFoundError(
                f"Preset {preset_id} not found.",
                details={"preset_id": str(preset_id)},
            )
        if row.owner_id != owner_id:
            if not (row.kind == "collection" and row.shared_with_project):
                raise PresetNotFoundError(
                    f"Preset {preset_id} not found.",
                    details={"preset_id": str(preset_id)},
                )
        return row

    async def list_visible(
        self,
        *,
        owner_id: uuid.UUID,
        tenant_id: str | None,
        project_id: uuid.UUID | None = None,
        kind: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[DashboardPreset], int]:
        if kind is not None and kind not in self.ALLOWED_KINDS:
            raise PresetValidationError(
                f"Unknown kind '{kind}'.",
                details={"kind": kind},
            )
        return await self.repo.list_visible(
            owner_id=owner_id,
            tenant_id=tenant_id,
            project_id=project_id,
            kind=kind,
            limit=limit,
            offset=offset,
        )

    # -- update ------------------------------------------------------------

    async def update(
        self,
        preset_id: uuid.UUID,
        *,
        owner_id: uuid.UUID,
        tenant_id: str | None,
        name: str | None = None,
        description: str | None = None,
        kind: str | None = None,
        config_json: dict[str, Any] | None = None,
        shared_with_project: bool | None = None,
    ) -> DashboardPreset:
        row = await self.repo.get(preset_id, tenant_id=tenant_id)
        if row is None:
            raise PresetNotFoundError(
                f"Preset {preset_id} not found.",
                details={"preset_id": str(preset_id)},
            )
        if row.owner_id != owner_id:
            raise PresetAccessDeniedError(
                f"Only the owner can edit preset {preset_id}.",
                details={"preset_id": str(preset_id)},
            )

        if name is not None:
            self._validate_name(name)
            row.name = name.strip()
        if description is not None:
            self._validate_description(description)
            row.description = description.strip() or None
        if kind is not None:
            self._validate_kind(kind)
            row.kind = kind
        if config_json is not None:
            row.config_json = config_json
        if shared_with_project is not None:
            row.shared_with_project = bool(shared_with_project)
            if row.shared_with_project and row.kind == "preset":
                row.kind = "collection"
        row.updated_at = datetime.now(UTC)

        await self.repo.session.flush()
        await self._publish_saved(row)
        return row

    async def toggle_share(
        self,
        preset_id: uuid.UUID,
        *,
        owner_id: uuid.UUID,
        tenant_id: str | None,
    ) -> DashboardPreset:
        row = await self.repo.get(preset_id, tenant_id=tenant_id)
        if row is None:
            raise PresetNotFoundError(
                f"Preset {preset_id} not found.",
                details={"preset_id": str(preset_id)},
            )
        if row.owner_id != owner_id:
            raise PresetAccessDeniedError(
                f"Only the owner can toggle sharing on preset {preset_id}.",
                details={"preset_id": str(preset_id)},
            )

        row.shared_with_project = not row.shared_with_project
        if row.shared_with_project:
            row.kind = "collection"
        row.updated_at = datetime.now(UTC)
        await self.repo.session.flush()

        await self._publish_saved(row)
        return row

    # -- delete ------------------------------------------------------------

    async def delete(
        self,
        preset_id: uuid.UUID,
        *,
        owner_id: uuid.UUID,
        tenant_id: str | None,
    ) -> None:
        row = await self.repo.get(preset_id, tenant_id=tenant_id)
        if row is None:
            raise PresetNotFoundError(
                f"Preset {preset_id} not found.",
                details={"preset_id": str(preset_id)},
            )
        if row.owner_id != owner_id:
            raise PresetAccessDeniedError(
                f"Only the owner can delete preset {preset_id}.",
                details={"preset_id": str(preset_id)},
            )

        await self.repo.delete(row)

        try:
            event_bus.publish_detached(
                event_taxonomy.DASHBOARD_DELETED,
                {
                    "dashboard_id": str(row.id),
                    "tenant_id": row.tenant_id,
                },
                source_module=event_taxonomy.SOURCE_MODULE,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                "dashboards.preset.delete event failed: %s",
                type(exc).__name__, exc_info=True,
            )

    # -- validators --------------------------------------------------------

    def _validate_name(self, name: str) -> None:
        if not name or not name.strip():
            raise PresetValidationError(
                "Preset name is required.",
                details={"field": "name"},
            )
        if len(name) > self.MAX_NAME_LENGTH:
            raise PresetValidationError(
                f"Preset name exceeds {self.MAX_NAME_LENGTH} characters.",
                details={"field": "name", "max_length": self.MAX_NAME_LENGTH},
            )

    def _validate_kind(self, kind: str) -> None:
        if kind not in self.ALLOWED_KINDS:
            raise PresetValidationError(
                f"Unknown preset kind '{kind}'.",
                details={"field": "kind", "allowed": list(self.ALLOWED_KINDS)},
            )

    def _validate_description(self, description: str | None) -> None:
        if description is None:
            return
        if len(description) > self.MAX_DESCRIPTION_LENGTH:
            raise PresetValidationError(
                f"Preset description exceeds {self.MAX_DESCRIPTION_LENGTH} characters.",
                details={
                    "field": "description",
                    "max_length": self.MAX_DESCRIPTION_LENGTH,
                },
            )

    # -- events ------------------------------------------------------------

    async def _publish_saved(self, row: DashboardPreset) -> None:
        try:
            event_bus.publish_detached(
                event_taxonomy.DASHBOARD_SAVED,
                {
                    "dashboard_id": str(row.id),
                    "workspace_id": str(row.project_id) if row.project_id else None,
                    "scope": row.kind,
                    "title": row.name,
                    "tenant_id": row.tenant_id,
                },
                source_module=event_taxonomy.SOURCE_MODULE,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning(
                "dashboards.preset.saved event failed: %s",
                type(exc).__name__, exc_info=True,
            )


__all__ = [
    "CreatePresetArgs",
    "DashboardPresetService",
    "PresetAccessDeniedError",
    "PresetError",
    "PresetNotFoundError",
    "PresetValidationError",
]
