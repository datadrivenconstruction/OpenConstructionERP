# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Plan Room service - read-only overlay aggregation + pin CRUD.

Composites a document page's overlays (defect pins, markups, measurements and
photos) into a single read-only payload, and owns create / delete for the
positioned photo / note pins.

Every external overlay source is read at request time behind a fail-soft lazy
import: a module or table that is absent (or errors) contributes an empty list
rather than failing the whole read. This mirrors the best-effort lazy imports
in ``closeout._outstanding_work`` and keeps Plan Room from hard-depending on any
optional module being installed.
"""

import logging
import uuid
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.plan_room.models import PlanPin
from app.modules.plan_room.repository import PlanPinRepository
from app.modules.plan_room.schemas import (
    OverlayMarkup,
    OverlayMeasurement,
    OverlayPhoto,
    OverlayPin,
    OverlaysResponse,
    OverlayVersion,
    PlanPinCreate,
)

logger = logging.getLogger(__name__)


def _num_to_str(value: Any) -> str | None:
    """Render a Decimal/Numeric quantity as a string (never a lossy float)."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return str(value)
    return str(value)


class PlanRoomService:
    """Read-only overlay aggregation and positioned-pin CRUD."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.pin_repo = PlanPinRepository(session)

    # -- Document resolution ------------------------------------------------

    async def resolve_document(self, document_id: str) -> Any | None:
        """Resolve a Documents-hub row by id (fail-soft, lazy import).

        Returns the ``Document`` ORM row, or ``None`` when the id is not a
        UUID, the row is absent, or the documents module is unavailable. The
        router turns a ``None`` into a 404.
        """
        try:
            from app.modules.documents.models import Document
        except Exception:  # noqa: BLE001 - documents module optional at import
            logger.debug("plan_room: documents module unavailable", exc_info=True)
            return None
        try:
            doc_uuid = uuid.UUID(str(document_id))
        except (ValueError, TypeError):
            return None
        try:
            return await self.session.get(Document, doc_uuid)
        except Exception:  # noqa: BLE001 - fail soft
            logger.debug("plan_room: document lookup failed", exc_info=True)
            return None

    # -- Overlay composite --------------------------------------------------

    async def get_overlays(self, document: Any, page: int) -> OverlaysResponse:
        """Composite every overlay on a document page into one payload."""
        document_id = str(document.id)
        version = OverlayVersion(
            document_id=document_id,
            revision_code=getattr(document, "revision_code", None),
            is_current_revision=getattr(document, "is_current_revision", None),
        )
        punch_pins = await self._punch_pins(document_id, page)
        plan_pins = await self._plan_pins(document_id, page)
        return OverlaysResponse(
            document_id=document_id,
            page=page,
            version=version,
            pins=punch_pins + plan_pins,
            markups=await self._markups(document_id, page),
            measurements=await self._measurements(document_id, page),
            photos=await self._photos(document_id),
        )

    async def _plan_pins(self, document_id: str, page: int) -> list[OverlayPin]:
        """Positioned Plan Room photo / note pins (owned by this module)."""
        try:
            rows = await self.pin_repo.list_for_page(document_id, page)
        except Exception:  # noqa: BLE001 - fail soft
            logger.debug("plan_room: plan-pin read failed", exc_info=True)
            return []
        return [
            OverlayPin(
                kind="plan",
                id=str(p.id),
                x=p.x,
                y=p.y,
                note=p.note,
                photo_ref=p.photo_ref,
                file_version_id=p.file_version_id,
            )
            for p in rows
        ]

    async def _punch_pins(self, document_id: str, page: int) -> list[OverlayPin]:
        """Positioned punch-list defect pins (read from the punchlist module).

        Only punch items with a drawing coordinate on this page are pins;
        unplaced items (no ``location_x`` / ``location_y``) are excluded.
        """
        try:
            from app.modules.punchlist.models import PunchItem

            stmt = select(PunchItem).where(
                PunchItem.document_id == document_id,
                PunchItem.page == page,
                PunchItem.location_x.is_not(None),
                PunchItem.location_y.is_not(None),
            )
            rows = (await self.session.execute(stmt)).scalars().all()
        except Exception:  # noqa: BLE001 - fail soft, module may be absent
            logger.debug("plan_room: punch-pin read failed", exc_info=True)
            return []
        out: list[OverlayPin] = []
        for it in rows:
            photos = getattr(it, "photos", None) or []
            out.append(
                OverlayPin(
                    kind="punch",
                    id=str(it.id),
                    x=it.location_x,
                    y=it.location_y,
                    title=it.title,
                    status=it.status,
                    priority=it.priority,
                    assigned_to=it.assigned_to,
                    photo_ref=str(photos[0]) if photos else None,
                )
            )
        return out

    async def _markups(self, document_id: str, page: int) -> list[OverlayMarkup]:
        """Drawing markups on this document page (read from the markups module)."""
        try:
            from app.modules.markups.models import Markup

            stmt = select(Markup).where(Markup.document_id == document_id, Markup.page == page)
            rows = (await self.session.execute(stmt)).scalars().all()
        except Exception:  # noqa: BLE001 - fail soft
            logger.debug("plan_room: markup read failed", exc_info=True)
            return []
        return [
            OverlayMarkup(
                id=str(m.id),
                page=m.page,
                type=m.type,
                geometry=getattr(m, "geometry", {}) or {},
                color=m.color,
                line_width=m.line_width,
                opacity=m.opacity,
                text=m.text,
                label=m.label,
                layer=m.layer,
                status=m.status,
                measurement_value=_num_to_str(m.measurement_value),
                measurement_unit=m.measurement_unit,
                file_version_id=str(m.file_version_id) if m.file_version_id is not None else None,
            )
            for m in rows
        ]

    async def _measurements(self, document_id: str, page: int) -> list[OverlayMeasurement]:
        """Takeoff measurements on this document page (read from takeoff module).

        Reuses the ``document_id`` + ``page`` filter shape of the takeoff
        measurement list query.
        """
        try:
            from app.modules.takeoff.models import TakeoffMeasurement

            stmt = select(TakeoffMeasurement).where(
                TakeoffMeasurement.document_id == document_id,
                TakeoffMeasurement.page == page,
            )
            rows = (await self.session.execute(stmt)).scalars().all()
        except Exception:  # noqa: BLE001 - fail soft
            logger.debug("plan_room: measurement read failed", exc_info=True)
            return []
        return [
            OverlayMeasurement(
                id=str(ms.id),
                type=ms.type,
                points=getattr(ms, "points", []) or [],
                measurement_value=_num_to_str(ms.measurement_value),
                measurement_unit=ms.measurement_unit,
                group_name=ms.group_name,
                group_color=ms.group_color,
                annotation=ms.annotation,
            )
            for ms in rows
        ]

    async def _photos(self, document_id: str) -> list[OverlayPhoto]:
        """Project photos attached to this document (document-level, no page)."""
        try:
            from app.modules.documents.models import ProjectPhoto

            stmt = select(ProjectPhoto).where(ProjectPhoto.document_id == document_id)
            rows = (await self.session.execute(stmt)).scalars().all()
        except Exception:  # noqa: BLE001 - fail soft
            logger.debug("plan_room: photo read failed", exc_info=True)
            return []
        return [
            OverlayPhoto(
                id=str(ph.id),
                document_id=ph.document_id,
                filename=ph.filename,
                thumbnail_path=ph.thumbnail_path,
                caption=ph.caption,
                taken_at=ph.taken_at,
            )
            for ph in rows
        ]

    # -- Pin CRUD -----------------------------------------------------------

    async def create_pin(
        self,
        *,
        project_id: uuid.UUID,
        document_id: str,
        page: int,
        data: PlanPinCreate,
        user_id: str | None = None,
    ) -> PlanPin:
        """Create a positioned photo / note pin on a document page."""
        pin = PlanPin(
            project_id=project_id,
            document_id=document_id,
            page=page,
            x=data.x,
            y=data.y,
            note=data.note,
            photo_ref=data.photo_ref,
            file_version_id=data.file_version_id,
            created_by=user_id,
            metadata_=data.metadata,
        )
        pin = await self.pin_repo.create(pin)
        logger.info("plan_room pin created: doc=%s page=%s project=%s", document_id, page, project_id)
        return pin

    async def get_pin(self, pin_id: uuid.UUID) -> PlanPin:
        """Get a pin by id. Raises 404 if not found."""
        pin = await self.pin_repo.get_by_id(pin_id)
        if pin is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pin not found")
        return pin

    async def delete_pin(self, pin_id: uuid.UUID) -> None:
        """Delete a pin (existence already checked by the caller via get_pin)."""
        await self.pin_repo.delete(pin_id)
