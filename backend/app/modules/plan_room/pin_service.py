# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pin registry service: the one place that creates, moves, relinks and reads location pins.

A pin references a record (RFI, punch item, inspection, NCR, photo, observation) or stands alone as a
note, and sits either on a drawing page or on a BIM element. The record keeps its own data; the pin
mirrors its status so a drawing can be filtered without opening every record.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from importlib import import_module
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_after_commit
from app.core.validation.quality_rules import gate_record
from app.modules.plan_room.models import PlanPin
from app.modules.plan_room.schemas import PinCreate, PinUpdate
from app.modules.plan_room.validators import PIN_FIELDS, PLAN_ROOM_RULE_SET

logger = logging.getLogger(__name__)

# kind -> (module, model, number attr, title attr, status attr, closed statuses)
_KINDS: dict[str, tuple[str, str, str | None, str | None, str | None, frozenset[str]]] = {
    "rfi": ("app.modules.rfi.models", "RFI", "rfi_number", "subject", "status", frozenset({"closed", "void"})),
    "punch": ("app.modules.punchlist.models", "PunchItem", None, "title", "status", frozenset({"closed"})),
    "inspection": (
        "app.modules.inspections.models",
        "QualityInspection",
        "inspection_number",
        "title",
        "status",
        frozenset({"completed", "cancelled"}),
    ),
    "ncr": ("app.modules.ncr.models", "NCR", "ncr_number", "title", "status", frozenset({"closed", "void"})),
    "photo": ("app.modules.documents.models", "ProjectPhoto", None, "caption", None, frozenset()),
    "observation": (
        "app.modules.safety.models",
        "SafetyObservation",
        "observation_number",
        "description",
        "status",
        frozenset({"closed"}),
    ),
}


@dataclass(frozen=True)
class TargetInfo:
    found: bool
    closed: bool = False
    status: str | None = None
    label: str | None = None


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


def _model(kind: str) -> Any | None:
    spec = _KINDS.get(kind)
    if spec is None:
        return None
    try:
        return getattr(import_module(spec[0]), spec[1])
    except Exception:  # noqa: BLE001 - the owning module may be absent
        logger.debug("plan_room: %s model unavailable", kind, exc_info=True)
        return None


def _label(kind: str, row: Any) -> str | None:
    _, _, num, title, _, _ = _KINDS[kind]
    number = str(getattr(row, num, "") or "") if num else ""
    text = str(getattr(row, title, "") or "") if title else ""
    if kind == "photo" and not text:
        text = str(getattr(row, "filename", "") or "")
    label = f"{number} {text[:80]}".strip()
    return label or None


class PinService:
    """Create, move, relink, delete and read pins; mirror the status of the record they point at."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- Lookups ------------------------------------------------------------

    async def resolve_target(self, kind: str, target_id: str | None, project_id: uuid.UUID) -> TargetInfo:
        """Find the record a pin points at, scoped to the pin's project."""
        if kind == "note":
            return TargetInfo(found=True)
        model, tid = _model(kind), _uuid(target_id)
        if model is None or tid is None:
            return TargetInfo(found=False)
        row = await self.session.get(model, tid)
        if row is None or getattr(row, "project_id", None) != project_id:
            return TargetInfo(found=False)
        spec = _KINDS[kind]
        current = getattr(row, spec[4], None) if spec[4] else None
        return TargetInfo(found=True, closed=current in spec[5], status=current, label=_label(kind, row))

    async def labels(self, rows: list[PlanPin]) -> dict[str, TargetInfo]:
        """Resolve many pins' records at once, one query per kind."""
        out: dict[str, TargetInfo] = {}
        by_kind: dict[str, set[uuid.UUID]] = {}
        for pin in rows:
            tid = _uuid(pin.target_id)
            if pin.target_kind in _KINDS and tid is not None:
                by_kind.setdefault(pin.target_kind, set()).add(tid)
        for kind, ids in by_kind.items():
            model = _model(kind)
            if model is None:
                continue
            spec = _KINDS[kind]
            try:
                found = (await self.session.execute(select(model).where(model.id.in_(ids)))).scalars().all()
            except Exception:  # noqa: BLE001 - fail soft, labels are decoration
                logger.debug("plan_room: label lookup failed for %s", kind, exc_info=True)
                continue
            for row in found:
                current = getattr(row, spec[4], None) if spec[4] else None
                out[f"{kind}:{row.id}"] = TargetInfo(True, current in spec[5], current, _label(kind, row))
        return out

    async def _sheet(self, document_id: str, page: int) -> Any | None:
        try:
            from app.modules.documents.models import Sheet
        except Exception:  # noqa: BLE001
            return None
        stmt = (
            select(Sheet)
            .where(func.btrim(Sheet.document_id) == document_id.strip(), Sheet.page_number == page)
            .order_by(Sheet.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def _page_count(self, document_id: str) -> int | None:
        try:
            from app.modules.documents.models import Sheet

            top = (
                await self.session.execute(
                    select(func.max(Sheet.page_number)).where(func.btrim(Sheet.document_id) == document_id.strip())
                )
            ).scalar()
        except Exception:  # noqa: BLE001
            return None
        return int(top) if top else None

    async def _document(self, document_id: str, project_id: uuid.UUID) -> Any:
        from app.modules.documents.models import Document

        doc_id = _uuid(document_id)
        doc = await self.session.get(Document, doc_id) if doc_id else None
        if doc is None or doc.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        return doc

    async def _bim_element(self, element_id: str, project_id: uuid.UUID) -> Any | None:
        try:
            from app.modules.bim_hub.models import BIMElement, BIMModel
        except Exception:  # noqa: BLE001
            return None
        eid = _uuid(element_id)
        if eid is None:
            return None
        stmt = (
            select(BIMElement)
            .join(BIMModel, BIMModel.id == BIMElement.model_id)
            .where(BIMElement.id == eid, BIMModel.project_id == project_id)
        )
        return (await self.session.execute(stmt)).scalars().first()

    # -- Rules --------------------------------------------------------------

    async def _gate(self, pin: PlanPin, *, operation: str, extra: dict[str, Any]) -> list[dict[str, Any]]:
        """Run the plan_room rule set over the pin; returns the non-blocking findings."""
        record = {
            "id": str(pin.id) if pin.id else "",
            "page": pin.page,
            "note": pin.note,
            "photo_ref": pin.photo_ref,
            "file_version_id": pin.file_version_id,
            "target_kind": pin.target_kind,
            "target_id": pin.target_id,
            "x": pin.x,
            "y": pin.y,
            "document_id": pin.document_id or None,
            "bim_element_id": pin.bim_element_id,
            **extra,
        }
        return await gate_record(
            PLAN_ROOM_RULE_SET,
            "pin",
            record,
            PIN_FIELDS,
            operation=operation,
            project_id=pin.project_id,
            error_code="plan_room_rules_failed",
        )

    async def _facts(self, pin: PlanPin) -> tuple[dict[str, Any], Any | None]:
        """Look up what the rules judge: the record, the page count, the sheet, the BIM element."""
        facts: dict[str, Any] = {}
        target = await self.resolve_target(pin.target_kind, pin.target_id, pin.project_id)
        facts["target_found"] = target.found
        facts["target_closed"] = target.closed
        if target.found and target.status:
            pin.status = target.status
        sheet = None
        if pin.document_id:
            doc = await self._document(pin.document_id, pin.project_id)
            facts["page_count"] = await self._page_count(pin.document_id)
            sheet = await self._sheet(pin.document_id, pin.page)
            if sheet is not None:
                pin.sheet_id = str(sheet.id)
            facts["sheet_superseded"] = bool(
                (sheet is not None and sheet.is_current is False) or doc.is_current_revision is False
            )
        if pin.bim_element_id:
            element = await self._bim_element(pin.bim_element_id, pin.project_id)
            facts["bim_element_found"] = element is not None
            if element is not None:
                pin.bim_model_id = str(element.model_id)
        return facts, sheet

    # -- Writes -------------------------------------------------------------

    async def create(self, data: PinCreate, user_id: str | None) -> PlanPin:
        """Create a pin; a replay of the same ``client_op_id`` returns the pin it created."""
        if data.client_op_id:
            prior = await self._by_client_op(data.project_id, data.client_op_id)
            if prior is not None:
                return prior
        pin = PlanPin(
            project_id=data.project_id,
            document_id=(data.document_id or "").strip(),
            page=data.page or 1,
            x=data.x if data.x is not None else 0.0,
            y=data.y if data.y is not None else 0.0,
            note=data.note,
            photo_ref=data.photo_ref,
            file_version_id=data.file_version_id,
            created_by=user_id,
            target_kind=data.target_kind,
            target_id=data.target_id,
            sheet_id=data.sheet_id,
            bim_model_id=data.bim_model_id,
            bim_element_id=data.bim_element_id,
            bim_xyz=data.bim_xyz,
            client_op_id=data.client_op_id,
            revision_state="current",
            metadata_=data.metadata,
        )
        if pin.document_id and (data.x is None or data.y is None):
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="x and y are required")
        facts, _ = await self._facts(pin)
        warnings = await self._gate(pin, operation="create", extra=facts)
        self.session.add(pin)
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError:
            # A concurrent replay of the same client op won the unique key: answer with its pin.
            prior = await self._by_client_op(data.project_id, data.client_op_id or "")
            if prior is None:
                raise
            return prior
        await self._write_through_punch(pin)
        pin.validation_warnings = warnings  # type: ignore[attr-defined]
        self._publish(pin, "created")
        return pin

    async def update(self, pin: PlanPin, data: PinUpdate) -> PlanPin:
        """Move, relink or review a pin. Only the fields sent change."""
        sent = data.model_dump(exclude_unset=True)
        moved = any(k in sent for k in ("document_id", "page", "x", "y", "bim_element_id", "bim_xyz"))
        if "document_id" in sent and sent["document_id"]:
            pin.bim_element_id = pin.bim_model_id = pin.bim_xyz = None
        if "bim_element_id" in sent and sent["bim_element_id"]:
            pin.document_id, pin.sheet_id = "", None
            pin.page, pin.x, pin.y = 1, 0.0, 0.0
        for key, value in sent.items():
            if key == "document_id":
                value = (value or "").strip()
            if key in {"x", "y", "page"} and value is None:
                continue
            setattr(pin, key, value)
        if moved and "revision_state" not in sent and pin.revision_state == "needs_review":
            pin.revision_state = "current"
        facts, _ = await self._facts(pin)
        warnings = await self._gate(pin, operation="update", extra=facts)
        await self.session.flush()
        if moved:
            await self._write_through_punch(pin)
        pin.validation_warnings = warnings  # type: ignore[attr-defined]
        if moved:
            self._publish(pin, "moved")
        return pin

    async def delete(self, pin: PlanPin) -> None:
        self._publish(pin, "deleted")
        await self.session.delete(pin)
        await self.session.flush()

    async def carry_forward(
        self, project_id: uuid.UUID, from_sheet_id: str, to_document_id: str, user_id: str | None
    ) -> list[PlanPin]:
        """Copy the pins of a superseded sheet onto its replacement, marked for review.

        The old pin is marked ``carried`` and the copy ``needs_review``; a page the new document no
        longer has leaves the old pin ``orphaned``.
        """
        doc = await self._document(to_document_id, project_id)
        count = await self._page_count(str(doc.id))
        rows = (
            (
                await self.session.execute(
                    select(PlanPin).where(PlanPin.project_id == project_id, PlanPin.sheet_id == from_sheet_id)
                )
            )
            .scalars()
            .all()
        )
        out: list[PlanPin] = []
        for old in rows:
            if old.revision_state == "carried":
                continue
            if count is not None and old.page > count:
                old.revision_state = "orphaned"
                continue
            sheet = await self._sheet(str(doc.id), old.page)
            copy = PlanPin(
                project_id=project_id,
                document_id=str(doc.id),
                page=old.page,
                x=old.x,
                y=old.y,
                note=old.note,
                photo_ref=old.photo_ref,
                created_by=user_id,
                target_kind=old.target_kind,
                target_id=old.target_id,
                sheet_id=str(sheet.id) if sheet is not None else None,
                status=old.status,
                revision_state="needs_review",
                carried_from_pin_id=str(old.id),
                metadata_=dict(old.metadata_ or {}),
            )
            old.revision_state = "carried"
            self.session.add(copy)
            out.append(copy)
        await self.session.flush()
        return out

    async def _write_through_punch(self, pin: PlanPin) -> None:
        """A punch pin and its item share one drawing coordinate: keep the item's copy in step."""
        if pin.target_kind != "punch" or not pin.document_id:
            return
        item = await self.session.get(_model("punch"), _uuid(pin.target_id)) if _model("punch") else None
        if item is None:
            return
        item.document_id, item.page = pin.document_id, pin.page
        item.location_x, item.location_y = pin.x, pin.y
        await self.session.flush()

    def _publish(self, pin: PlanPin, action: str) -> None:
        publish_after_commit(
            self.session,
            f"plan_room.pin.{action}",
            {
                "project_id": str(pin.project_id),
                "pin_id": str(pin.id),
                "target_kind": pin.target_kind,
                "target_id": pin.target_id,
                "document_id": pin.document_id,
                "page": pin.page,
                "bim_element_id": pin.bim_element_id,
            },
            source_module="oe_plan_room",
        )

    # -- Reads --------------------------------------------------------------

    async def get(self, pin_id: uuid.UUID) -> PlanPin:
        pin = await self.session.get(PlanPin, pin_id)
        if pin is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pin not found")
        return pin

    async def _by_client_op(self, project_id: uuid.UUID, client_op_id: str) -> PlanPin | None:
        stmt = select(PlanPin).where(PlanPin.project_id == project_id, PlanPin.client_op_id == client_op_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def list_pins(
        self,
        project_id: uuid.UUID,
        *,
        document_id: str | None = None,
        sheet_id: str | None = None,
        page: int | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        status_: str | None = None,
        revision_state: str | None = None,
        bim_model_id: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> tuple[list[PlanPin], int]:
        """Pins of a project, newest first, with the total before paging."""
        conds = [PlanPin.project_id == project_id]
        for column, value in (
            (PlanPin.document_id, document_id),
            (PlanPin.sheet_id, sheet_id),
            (PlanPin.page, page),
            (PlanPin.target_kind, target_kind),
            (PlanPin.target_id, target_id),
            (PlanPin.status, status_),
            (PlanPin.revision_state, revision_state),
            (PlanPin.bim_model_id, bim_model_id),
        ):
            if value is not None:
                conds.append(column == value)
        total = (await self.session.execute(select(func.count()).select_from(PlanPin).where(*conds))).scalar_one()
        stmt = select(PlanPin).where(*conds).order_by(PlanPin.created_at.desc()).offset(offset).limit(limit)
        return list((await self.session.execute(stmt)).scalars().all()), int(total)

    async def mirror_status(self, kind: str, target_id: str, new_status: str) -> int:
        """Copy a record's new status onto every pin that points at it."""
        rows = (
            (
                await self.session.execute(
                    select(PlanPin).where(PlanPin.target_kind == kind, PlanPin.target_id == target_id)
                )
            )
            .scalars()
            .all()
        )
        for pin in rows:
            pin.status = new_status
        await self.session.flush()
        return len(rows)

    async def drop_for_target(self, kind: str, target_id: str) -> int:
        """Remove the pins of a record that was deleted."""
        rows = (
            (
                await self.session.execute(
                    select(PlanPin).where(PlanPin.target_kind == kind, PlanPin.target_id == target_id)
                )
            )
            .scalars()
            .all()
        )
        for pin in rows:
            await self.session.delete(pin)
        await self.session.flush()
        return len(rows)
