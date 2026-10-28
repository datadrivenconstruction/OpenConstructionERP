# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Drawing revision compare business logic.

Two ways in, one stored shape out:

* **PDF sheets** are rasterised and diffed in the browser with pdf.js; the
  service checks both revisions belong to the project, that every region lies
  on the sheet and that the alignment is usable, then stores the regions.
* **DWG/DXF** revisions are diffed here from the entity records the CAD
  converter already stores (:mod:`app.modules.drawing_compare.entity_diff`).

A stored change then drives the follow-ups that already exist elsewhere: an
RFI (``oe_rfi``), a revision cloud (``oe_markups`` on a sheet, a rectangle
annotation on a DWG), and a ``needs_remeasure`` flag on every takeoff
measurement, DWG annotation, markup and BOQ position that sits inside the
region. Every one of those modules is reached by a lazy import, so a missing
module turns its follow-up into a 409 instead of breaking the compare.
"""

from __future__ import annotations

import logging
import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import publish_after_commit
from app.core.i18n import t
from app.modules.drawing_compare.entity_diff import cluster_entity_changes, diff_entities, drawing_extent
from app.modules.drawing_compare.geometry import (
    IDENTITY,
    Rect,
    invert_affine,
    points_of,
    shape_in_region,
    similarity_from_two_points,
)
from app.modules.drawing_compare.models import DrawingChange, DrawingComparison
from app.modules.drawing_compare.repository import ComparisonRepository
from app.modules.drawing_compare.schemas import (
    AffectedItem,
    AffectedPosition,
    ChangeMarkupCreate,
    ChangeRfiCreate,
    ChangeUpdate,
    DwgComparisonCreate,
    PdfComparisonCreate,
    PreviousRevisionResponse,
    RemeasureResponse,
)
from app.modules.drawing_compare.thumbnail import records_in, region_svg

logger = logging.getLogger(__name__)

SOURCE_MODULE = "oe_drawing_compare"
REMEASURE_KEY = "needs_remeasure"
# A region may overhang the sheet by this share before it is refused.
_EDGE_TOLERANCE = 0.01
# Grow regions by this share of the sheet diagonal when looking for what sits inside.
_INSIDE_MARGIN = 0.0025
# DWG regions: entities closer than this share of the drawing diagonal form one region.
_DWG_CLUSTER_GAP = 0.015


def _not_found(key: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=t(f"drawing_compare.errors.{key}"))


def _unprocessable(key: str, **params: Any) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=t(f"drawing_compare.errors.{key}", **params),
    )


def _as_uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


@dataclass
class _Side:
    """One revision as the follow-ups need it."""

    ref_id: str
    label: str
    revision: str | None
    doc_ids: set[str] = field(default_factory=set)
    markup_doc_id: str | None = None
    drawing_id: uuid.UUID | None = None
    version_id: uuid.UUID | None = None


class DrawingCompareService:
    """Store, read, triage and follow up drawing revision compares."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ComparisonRepository(session)

    # ── Revision sides ──────────────────────────────────────────────────

    async def _resolve_pdf_side(self, project_id: uuid.UUID, ref_id: str) -> _Side:
        """A PDF revision: a takeoff document, or a documents-hub row."""
        ref_uuid = _as_uuid(ref_id)
        if ref_uuid is None:
            raise _not_found("revision_not_found")
        try:
            from app.modules.takeoff.models import TakeoffDocument
        except ImportError:  # pragma: no cover - takeoff ships with core
            TakeoffDocument = None  # type: ignore[assignment]  # noqa: N806
        doc_model: Any = None
        try:
            from app.modules.documents.models import Document

            doc_model = Document
        except ImportError:  # pragma: no cover
            doc_model = None

        if TakeoffDocument is not None:
            tdoc = await self.session.get(TakeoffDocument, ref_uuid)
            if tdoc is not None and tdoc.project_id == project_id:
                side = _Side(ref_id=str(tdoc.id), label=tdoc.filename, revision=None, doc_ids={str(tdoc.id)})
                side.markup_doc_id = tdoc.source_document_id or str(tdoc.id)
                if tdoc.source_document_id:
                    side.doc_ids.add(tdoc.source_document_id)
                    src_uuid = _as_uuid(tdoc.source_document_id)
                    if doc_model is not None and src_uuid is not None:
                        src = await self.session.get(doc_model, src_uuid)
                        if src is not None:
                            side.revision = src.revision_code
                return side
        if doc_model is not None:
            doc = await self.session.get(doc_model, ref_uuid)
            if doc is not None and doc.project_id == project_id:
                side = _Side(
                    ref_id=str(doc.id),
                    label=doc.name,
                    revision=doc.revision_code,
                    doc_ids={str(doc.id)},
                    markup_doc_id=str(doc.id),
                )
                if TakeoffDocument is not None:
                    rows = await self.session.execute(
                        select(TakeoffDocument.id).where(
                            TakeoffDocument.project_id == project_id,
                            TakeoffDocument.source_document_id == str(doc.id),
                        )
                    )
                    side.doc_ids.update(str(r) for r in rows.scalars().all())
                return side
        raise _not_found("revision_not_found")

    async def _resolve_dwg_side(
        self,
        project_id: uuid.UUID,
        drawing_id: uuid.UUID,
        version_id: uuid.UUID | None,
    ) -> tuple[_Side, Any]:
        """A DWG revision: a parsed version of a drawing in the project."""
        try:
            from app.modules.dwg_takeoff.models import DwgDrawing, DwgDrawingVersion
            from app.modules.dwg_takeoff.repository import DwgDrawingVersionRepository
        except ImportError as exc:  # pragma: no cover
            raise HTTPException(status.HTTP_409_CONFLICT, t("drawing_compare.errors.module_missing")) from exc
        drawing = await self.session.get(DwgDrawing, drawing_id)
        if drawing is None or drawing.project_id != project_id:
            raise _not_found("revision_not_found")
        versions = DwgDrawingVersionRepository(self.session)
        if version_id is not None:
            version = await self.session.get(DwgDrawingVersion, version_id)
            if version is None or version.drawing_id != drawing_id:
                raise _not_found("revision_not_found")
        else:
            version = await versions.get_latest_for_drawing(drawing_id)
            if version is None:
                raise _not_found("revision_not_parsed")
        side = _Side(
            ref_id=str(version.id),
            label=drawing.name,
            revision=f"v{version.version_number}",
            doc_ids={str(drawing.id)},
            drawing_id=drawing.id,
            version_id=version.id,
        )
        return side, version

    async def _sides_of(self, cmp: DrawingComparison) -> tuple[_Side, _Side]:
        """Re-resolve both sides of a stored compare (revisions may have been deleted)."""
        if cmp.source_kind == "dwg":
            meta = cmp.metadata_ or {}
            sides: list[_Side] = []
            for which in ("old", "new"):
                drawing_id = _as_uuid(meta.get(f"{which}_drawing_id"))
                version_id = _as_uuid(getattr(cmp, f"{which}_ref_id"))
                if drawing_id is None:
                    raise _not_found("revision_not_found")
                side, _ = await self._resolve_dwg_side(cmp.project_id, drawing_id, version_id)
                sides.append(side)
            return sides[0], sides[1]
        return (
            await self._resolve_pdf_side(cmp.project_id, cmp.old_ref_id),
            await self._resolve_pdf_side(cmp.project_id, cmp.new_ref_id),
        )

    # ── Create ──────────────────────────────────────────────────────────

    @staticmethod
    def _summary(changes: list[DrawingChange], extra: dict[str, Any] | None = None) -> dict[str, Any]:
        counts = {"added": 0, "removed": 0, "modified": 0, "text": 0}
        for ch in changes:
            counts[ch.kind] = counts.get(ch.kind, 0) + 1
        return {**counts, "total": len(changes), **(extra or {})}

    async def create_pdf_comparison(self, data: PdfComparisonCreate, user_id: str) -> DrawingComparison:
        """Store a sheet compare computed in the browser."""
        if data.old_ref_id == data.new_ref_id and data.old_page == data.new_page:
            raise _unprocessable("same_revision")
        old = await self._resolve_pdf_side(data.project_id, data.old_ref_id)
        new = await self._resolve_pdf_side(data.project_id, data.new_ref_id)

        alignment = data.alignment.model_dump()
        if data.alignment.method == "manual":
            if len(data.alignment.points_old) != 2 or len(data.alignment.points_new) != 2:
                raise _unprocessable("manual_points")
            try:
                alignment["matrix"] = list(
                    similarity_from_two_points(
                        [(p[0], p[1]) for p in data.alignment.points_old],
                        [(p[0], p[1]) for p in data.alignment.points_new],
                    )
                )
            except (ValueError, IndexError) as exc:
                raise _unprocessable("manual_points") from exc
        try:
            invert_affine(alignment["matrix"])
        except ValueError as exc:
            raise _unprocessable("alignment_singular") from exc

        page = Rect(0.0, 0.0, data.page_width, data.page_height)
        tol = max(data.page_width, data.page_height) * _EDGE_TOLERANCE
        changes: list[DrawingChange] = []
        for i, ch in enumerate(data.changes, start=1):
            region = Rect(ch.x, ch.y, ch.w, ch.h)
            if region.area <= 0 and ch.kind != "text":
                raise _unprocessable("region_empty", seq=i)
            if not region.intersects(page.expanded(tol)):
                raise _unprocessable("region_off_sheet", seq=i)
            changes.append(
                DrawingChange(
                    seq=i,
                    kind=ch.kind,
                    page=data.new_page,
                    x=ch.x,
                    y=ch.y,
                    w=ch.w,
                    h=ch.h,
                    score=ch.score,
                    old_text=ch.old_text,
                    new_text=ch.new_text,
                    details=ch.details,
                    thumbnail=ch.thumbnail,
                )
            )
        cmp = DrawingComparison(
            project_id=data.project_id,
            name=data.name or f"{new.label} / {old.label}",
            source_kind="pdf",
            old_ref_id=old.ref_id,
            new_ref_id=new.ref_id,
            old_page=data.old_page,
            new_page=data.new_page,
            old_label=old.label,
            new_label=new.label,
            old_revision=old.revision,
            new_revision=new.revision,
            page_width=data.page_width,
            page_height=data.page_height,
            alignment=alignment,
            settings=data.settings,
            summary=self._summary(changes),
            created_by=user_id,
        )
        await self.repo.add(cmp, changes)
        self._announce_created(cmp)
        return cmp

    async def create_dwg_comparison(self, data: DwgComparisonCreate, user_id: str) -> DrawingComparison:
        """Diff two DWG/DXF revisions entity by entity and store the regions."""
        old, old_version = await self._resolve_dwg_side(data.project_id, data.old_drawing_id, data.old_version_id)
        new, new_version = await self._resolve_dwg_side(data.project_id, data.new_drawing_id, data.new_version_id)
        if old.version_id == new.version_id:
            raise _unprocessable("same_revision")

        from app.modules.dwg_takeoff.service import DwgTakeoffService

        dwg = DwgTakeoffService(self.session)
        old_records = await dwg.load_version_entities(old_version)
        new_records = await dwg.load_version_entities(new_version)
        result = diff_entities(old_records, new_records, tolerance=data.tolerance)
        extent = drawing_extent(old_records, new_records)
        diag = math.hypot(extent.w, extent.h) if extent is not None else 0.0
        regions = cluster_entity_changes(result.changes, gap=diag * _DWG_CLUSTER_GAP, min_size=diag * 0.004)

        changes: list[DrawingChange] = []
        for i, region in enumerate(regions, start=1):
            old_members = [old_records[m.old_index] for m in region.members if m.old_index is not None]
            new_members = [new_records[m.new_index] for m in region.members if m.new_index is not None]
            context = records_in(new_records, region.box.expanded(max(region.box.w, region.box.h) * 0.1))
            changes.append(
                DrawingChange(
                    seq=i,
                    kind=region.kind,
                    page=None,
                    x=region.box.x,
                    y=region.box.y,
                    w=region.box.w,
                    h=region.box.h,
                    score=float(sum(region.counts.values())),
                    old_text=region.old_text,
                    new_text=region.new_text,
                    layer=region.layer[:255],
                    entity_type=region.entity_type[:64],
                    details={"counts": region.counts, "layers": region.layers, "entities": region.entities},
                    thumbnail=region_svg(region.box, context=context, old=old_members, new=new_members),
                )
            )
        cmp = DrawingComparison(
            project_id=data.project_id,
            name=data.name or f"{new.label} {new.revision} / {old.label} {old.revision}",
            source_kind="dwg",
            old_ref_id=old.ref_id,
            new_ref_id=new.ref_id,
            old_label=old.label,
            new_label=new.label,
            old_revision=old.revision,
            new_revision=new.revision,
            alignment={"method": "none", "matrix": list(IDENTITY)},
            settings={"tolerance": result.tolerance, "cluster_gap": diag * _DWG_CLUSTER_GAP},
            summary=self._summary(
                changes,
                {
                    "entities": result.counts(),
                    "old_entities": result.old_total,
                    "new_entities": result.new_total,
                    "by_layer": result.by_layer()[:200],
                },
            ),
            created_by=user_id,
            metadata_={"old_drawing_id": str(old.drawing_id), "new_drawing_id": str(new.drawing_id)},
        )
        if extent is not None:
            cmp.metadata_ = {**cmp.metadata_, "extent": [extent.x, extent.y, extent.w, extent.h]}
        await self.repo.add(cmp, changes)
        self._announce_created(cmp)
        return cmp

    def _announce_created(self, cmp: DrawingComparison) -> None:
        publish_after_commit(
            self.session,
            "drawing_compare.comparison.created",
            {
                "project_id": str(cmp.project_id),
                "comparison_id": str(cmp.id),
                "source_kind": cmp.source_kind,
                "old_ref_id": cmp.old_ref_id,
                "new_ref_id": cmp.new_ref_id,
                "changes": int((cmp.summary or {}).get("total", 0)),
            },
            source_module=SOURCE_MODULE,
        )

    # ── Read / delete ───────────────────────────────────────────────────

    async def get(self, comparison_id: uuid.UUID, *, with_changes: bool = True) -> DrawingComparison:
        """A compare by id or 404."""
        cmp = await self.repo.get(comparison_id, with_changes=with_changes)
        if cmp is None:
            raise _not_found("comparison_not_found")
        return cmp

    async def list_comparisons(
        self, project_id: uuid.UUID, *, ref_id: str | None, limit: int, offset: int
    ) -> list[DrawingComparison]:
        """Compares of a project, newest first."""
        return await self.repo.list_for_project(project_id, ref_id=ref_id, limit=limit, offset=offset)

    async def count_comparisons(self, project_id: uuid.UUID, *, ref_id: str | None) -> int:
        """How many compares the same filters match, ignoring the page."""
        return await self.repo.count_for_project(project_id, ref_id=ref_id)

    async def delete(self, cmp: DrawingComparison) -> None:
        """Delete a compare (re-measure flags it raised stay on their rows)."""
        await self.repo.delete(cmp)

    async def get_change(self, change_id: uuid.UUID) -> tuple[DrawingChange, DrawingComparison]:
        """A change and its compare, or 404."""
        change = await self.repo.get_change(change_id)
        if change is None:
            raise _not_found("change_not_found")
        cmp = await self.get(change.comparison_id, with_changes=False)
        return change, cmp

    # ── Triage ──────────────────────────────────────────────────────────

    async def update_change(self, change: DrawingChange, data: ChangeUpdate, user_id: str) -> DrawingChange:
        """Record the reviewer's status and comment."""
        fields = data.model_dump(exclude_unset=True)
        if "status" in fields and fields["status"] is not None:
            change.status = fields["status"]
        if "comment" in fields:
            change.comment = fields["comment"] or None
        change.reviewed_by = user_id
        await self.session.flush()
        return change

    # ── Follow-ups ──────────────────────────────────────────────────────

    def _kind_label(self, kind: str) -> str:
        return t(f"drawing_compare.kind.{kind}")

    async def create_rfi(
        self, change: DrawingChange, cmp: DrawingComparison, data: ChangeRfiCreate, user_id: str
    ) -> tuple[str, str]:
        """Raise a draft RFI from a change and link it back."""
        try:
            from app.modules.rfi.schemas import RFICreate
            from app.modules.rfi.service import RFIService
        except ImportError as exc:  # pragma: no cover
            raise HTTPException(status.HTTP_409_CONFLICT, t("drawing_compare.errors.module_missing")) from exc
        _old, new = await self._sides_of(cmp)
        sheet = new.label if change.page is None else t("drawing_compare.sheet_page", label=new.label, page=change.page)
        subject = data.subject or t("drawing_compare.rfi.subject", seq=change.seq, sheet=sheet)
        question = data.question or t(
            "drawing_compare.rfi.question",
            sheet=sheet,
            old=cmp.old_revision or cmp.old_label,
            new=cmp.new_revision or cmp.new_label,
            kind=self._kind_label(change.kind),
        )
        if not data.question and change.comment:
            question = f"{question}\n\n{change.comment}"
        if not data.question and (change.old_text or change.new_text):
            question = f"{question}\n\n" + t(
                "drawing_compare.text_change", old=change.old_text or "", new=change.new_text or ""
            )
        linked = [new.markup_doc_id] if new.markup_doc_id else []
        rfi = await RFIService(self.session).create_rfi(
            RFICreate(
                project_id=cmp.project_id,
                subject=subject[:500],
                question=question[:10_000],
                priority=data.priority,
                linked_drawing_ids=linked,
                metadata={"drawing_compare": {"comparison_id": str(cmp.id), "change_id": str(change.id)}},
            ),
            user_id,
        )
        change.rfi_id = str(rfi.id)
        if change.status == "open":
            change.status = "relevant"
        change.reviewed_by = user_id
        await self.session.flush()
        return str(rfi.id), rfi.rfi_number

    async def create_markup(
        self, change: DrawingChange, cmp: DrawingComparison, data: ChangeMarkupCreate, user_id: str
    ) -> tuple[str, str]:
        """Cloud the region on the new revision and link the markup back."""
        _old, new = await self._sides_of(cmp)
        text = data.text or t("drawing_compare.markup.text", seq=change.seq, kind=self._kind_label(change.kind))
        meta = {"drawing_compare": {"comparison_id": str(cmp.id), "change_id": str(change.id)}}
        x2, y2 = change.x + change.w, change.y + change.h
        if cmp.source_kind == "dwg":
            from app.modules.dwg_takeoff.schemas import DwgAnnotationCreate
            from app.modules.dwg_takeoff.service import DwgTakeoffService

            assert new.drawing_id is not None  # noqa: S101 - set for every DWG side
            ann = await DwgTakeoffService(self.session).create_annotation(
                DwgAnnotationCreate(
                    project_id=cmp.project_id,
                    drawing_id=new.drawing_id,
                    drawing_version_id=new.version_id,
                    annotation_type="rectangle",
                    geometry={"points": [{"x": change.x, "y": change.y}, {"x": x2, "y": y2}]},
                    text=text,
                    color=data.color,
                    layer_name="REVISION_COMPARE",
                    metadata=meta,
                ),
                user_id,
            )
            target_id = str(ann.id)
        else:
            try:
                from app.modules.markups.schemas import MarkupCreate
                from app.modules.markups.service import MarkupsService
            except ImportError as exc:  # pragma: no cover
                raise HTTPException(status.HTTP_409_CONFLICT, t("drawing_compare.errors.module_missing")) from exc
            markup = await MarkupsService(self.session).create_markup(
                MarkupCreate(
                    project_id=cmp.project_id,
                    document_id=new.markup_doc_id,
                    page=change.page or cmp.new_page or 1,
                    type="cloud",
                    geometry={"points": [[change.x, change.y], [x2, change.y], [x2, y2], [change.x, y2]]},
                    text=text,
                    color=data.color,
                    label=f"#{change.seq}",
                    layer="revision_compare",
                    metadata=meta,
                ),
                user_id,
            )
            target_id = str(markup.id)
        change.markup_id = target_id
        if change.status == "open":
            change.status = "relevant"
        change.reviewed_by = user_id
        await self.session.flush()
        return target_id, f"#{change.seq}"

    # ── Re-measure ──────────────────────────────────────────────────────

    async def _affected(self, change: DrawingChange, cmp: DrawingComparison) -> tuple[list[AffectedItem], list[Any]]:
        """Measurements, annotations and markups inside the region, with their rows."""
        old, new = await self._sides_of(cmp)
        region = Rect(change.x, change.y, change.w, change.h)
        rows: list[Any] = []
        items: list[AffectedItem] = []
        if cmp.source_kind == "pdf":
            diag = math.hypot(cmp.page_width or 0.0, cmp.page_height or 0.0)
            margin = diag * _INSIDE_MARGIN
            matrix = (cmp.alignment or {}).get("matrix") or list(IDENTITY)
            sides = [("new", new, cmp.new_page, None), ("old", old, cmp.old_page, matrix)]
            try:
                from app.modules.takeoff.models import TakeoffMeasurement
            except ImportError:  # pragma: no cover
                TakeoffMeasurement = None  # type: ignore[assignment]  # noqa: N806
            try:
                from app.modules.markups.models import Markup
            except ImportError:  # pragma: no cover
                Markup = None  # type: ignore[assignment]  # noqa: N806
            seen: set[str] = set()
            for which, side, page, mtx in sides:
                if TakeoffMeasurement is not None and side.doc_ids:
                    stmt = select(TakeoffMeasurement).where(
                        TakeoffMeasurement.project_id == cmp.project_id,
                        TakeoffMeasurement.document_id.in_(sorted(side.doc_ids)),
                        TakeoffMeasurement.page == (page or 1),
                    )
                    for m in (await self.session.execute(stmt)).scalars().all():
                        if str(m.id) in seen or not shape_in_region(
                            points_of(m.points), region, matrix=mtx, margin=margin
                        ):
                            continue
                        seen.add(str(m.id))
                        rows.append(m)
                        items.append(
                            AffectedItem(
                                id=str(m.id),
                                source="takeoff",
                                document_id=m.document_id,
                                page=m.page,
                                label=(m.annotation or m.group_name or m.type or "")[:200],
                                revision=which,  # type: ignore[arg-type]
                                linked_boq_position_id=m.linked_boq_position_id,
                            )
                        )
                if Markup is not None and side.doc_ids:
                    stmt = select(Markup).where(
                        Markup.project_id == cmp.project_id,
                        Markup.document_id.in_(sorted(side.doc_ids)),
                        Markup.page == (page or 1),
                    )
                    for mk in (await self.session.execute(stmt)).scalars().all():
                        if str(mk.id) == change.markup_id or str(mk.id) in seen:
                            continue
                        if not shape_in_region(points_of(mk.geometry), region, matrix=mtx, margin=margin):
                            continue
                        seen.add(str(mk.id))
                        rows.append(mk)
                        items.append(
                            AffectedItem(
                                id=str(mk.id),
                                source="markup",
                                document_id=mk.document_id,
                                page=mk.page,
                                label=(mk.label or mk.text or mk.type or "")[:200],
                                revision=which,  # type: ignore[arg-type]
                                linked_boq_position_id=mk.linked_boq_position_id,
                            )
                        )
        else:
            from app.modules.dwg_takeoff.models import DwgAnnotation

            drawing_ids = {d for d in (old.drawing_id, new.drawing_id) if d is not None}
            stmt = select(DwgAnnotation).where(
                DwgAnnotation.project_id == cmp.project_id,
                DwgAnnotation.drawing_id.in_(sorted(drawing_ids, key=str)),
            )
            for ann in (await self.session.execute(stmt)).scalars().all():
                if str(ann.id) == change.markup_id:
                    continue
                if ann.drawing_version_id is not None and ann.drawing_version_id not in (
                    old.version_id,
                    new.version_id,
                ):
                    continue
                if not shape_in_region(points_of(ann.geometry), region):
                    continue
                which = (
                    "old" if ann.drawing_version_id == old.version_id and old.version_id != new.version_id else "new"
                )
                if ann.drawing_version_id is None and ann.drawing_id != new.drawing_id:
                    which = "old"
                rows.append(ann)
                items.append(
                    AffectedItem(
                        id=str(ann.id),
                        source="dwg_annotation",
                        document_id=str(ann.drawing_id),
                        label=(ann.text or ann.annotation_type or "")[:200],
                        revision=which,  # type: ignore[arg-type]
                        linked_boq_position_id=ann.linked_boq_position_id,
                    )
                )
        return items, rows

    async def _positions(self, project_id: uuid.UUID, ids: set[str]) -> list[Any]:
        """BOQ positions of the project with these ids."""
        uuids = [u for u in (_as_uuid(i) for i in ids) if u is not None]
        if not uuids:
            return []
        try:
            from app.modules.boq.models import BOQ, Position
        except ImportError:  # pragma: no cover
            return []
        stmt = (
            select(Position)
            .join(BOQ, BOQ.id == Position.boq_id)
            .where(BOQ.project_id == project_id, Position.id.in_(uuids))
            .order_by(Position.ordinal)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def remeasure(
        self,
        change: DrawingChange,
        cmp: DrawingComparison,
        user_id: str,
        *,
        dry_run: bool,
        can_flag_boq: bool = True,
    ) -> RemeasureResponse:
        """List (and unless ``dry_run``, flag) what sits inside a change.

        The flag is ``metadata.needs_remeasure`` on each row: which compare
        and change raised it, against which revision, by whom and when. The
        same flag goes onto every BOQ position whose quantity comes from a
        flagged row.
        """
        items, rows = await self._affected(change, cmp)
        position_ids = {i.linked_boq_position_id for i in items if i.linked_boq_position_id}
        positions = await self._positions(cmp.project_id, position_ids)  # type: ignore[arg-type]
        pos_out = [
            AffectedPosition(id=str(p.id), ordinal=p.ordinal or "", description=(p.description or "")[:300])
            for p in positions
        ]
        if dry_run:
            return RemeasureResponse(change_id=change.id, dry_run=True, items=items, positions=pos_out)
        if positions:
            # Flagging writes position metadata, so it needs the BOQ's own write right and an open bill.
            if not can_flag_boq:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: boq.update")
            from app.modules.boq.models import BOQ

            locked = (
                await self.session.execute(
                    select(BOQ.id).where(BOQ.id.in_({p.boq_id for p in positions}), BOQ.is_locked.is_(True))
                )
            ).first()
            if locked is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=t("errors.boq_locked"))

        now = datetime.now(UTC)
        flag = {
            "comparison_id": str(cmp.id),
            "change_id": str(change.id),
            "change_seq": change.seq,
            "new_ref_id": cmp.new_ref_id,
            "new_label": cmp.new_label,
            "new_revision": cmp.new_revision,
            "flagged_at": now.isoformat(),
            "flagged_by": user_id,
        }
        for row in [*rows, *positions]:
            row.metadata_ = {**(row.metadata_ or {}), REMEASURE_KEY: flag}
        change.flagged_measurement_ids = [i.id for i in items if i.source == "takeoff"]
        change.flagged_annotation_ids = [i.id for i in items if i.source in ("dwg_annotation", "markup")]
        change.flagged_position_ids = [p.id for p in pos_out]
        change.flagged_at = now
        if change.status == "open":
            change.status = "relevant"
        change.reviewed_by = user_id
        await self.session.flush()
        publish_after_commit(
            self.session,
            "drawing_compare.remeasure.flagged",
            {
                "project_id": str(cmp.project_id),
                "comparison_id": str(cmp.id),
                "change_id": str(change.id),
                "measurement_ids": list(change.flagged_measurement_ids),
                "annotation_ids": list(change.flagged_annotation_ids),
                "position_ids": list(change.flagged_position_ids),
            },
            source_module=SOURCE_MODULE,
        )
        return RemeasureResponse(change_id=change.id, dry_run=False, items=items, positions=pos_out, flagged_at=now)

    async def clear_remeasure(self, change: DrawingChange, cmp: DrawingComparison) -> DrawingChange:
        """Lift the flags this change raised (another change's flag is left alone)."""
        targets: list[tuple[Any, list[str]]] = []
        annotation_ids = change.flagged_annotation_ids or []
        try:
            from app.modules.takeoff.models import TakeoffMeasurement

            targets.append((TakeoffMeasurement, change.flagged_measurement_ids or []))
        except ImportError:  # pragma: no cover
            pass
        try:
            from app.modules.markups.models import Markup

            targets.append((Markup, annotation_ids))
        except ImportError:  # pragma: no cover
            pass
        try:
            from app.modules.dwg_takeoff.models import DwgAnnotation

            targets.append((DwgAnnotation, annotation_ids))
        except ImportError:  # pragma: no cover
            pass
        try:
            from app.modules.boq.models import Position

            targets.append((Position, change.flagged_position_ids or []))
        except ImportError:  # pragma: no cover
            pass
        for model, ids in targets:
            uuids = [u for u in (_as_uuid(i) for i in ids) if u is not None]
            if not uuids:
                continue
            for row in (await self.session.execute(select(model).where(model.id.in_(uuids)))).scalars().all():
                meta = dict(row.metadata_ or {})
                flag = meta.get(REMEASURE_KEY)
                if isinstance(flag, dict) and flag.get("change_id") == str(change.id):
                    meta.pop(REMEASURE_KEY, None)
                    row.metadata_ = meta
        change.flagged_measurement_ids = []
        change.flagged_annotation_ids = []
        change.flagged_position_ids = []
        change.flagged_at = None
        await self.session.flush()
        return change

    # ── Previous revision ───────────────────────────────────────────────

    async def previous_revision(self, project_id: uuid.UUID, document_id: str) -> PreviousRevisionResponse:
        """The takeoff document of the revision this one supersedes, from the documents chain."""
        out = PreviousRevisionResponse(document_id=document_id)
        side = await self._resolve_pdf_side(project_id, document_id)
        try:
            from app.modules.documents.models import Document
            from app.modules.takeoff.models import TakeoffDocument
        except ImportError:  # pragma: no cover
            return out
        for doc_id in sorted(side.doc_ids):
            doc_uuid = _as_uuid(doc_id)
            doc = await self.session.get(Document, doc_uuid) if doc_uuid else None
            if doc is None or doc.project_id != project_id or doc.parent_document_id is None:
                continue
            parent = await self.session.get(Document, doc.parent_document_id)
            if parent is None or parent.project_id != project_id:
                continue
            tdoc = (
                await self.session.execute(
                    select(TakeoffDocument).where(
                        TakeoffDocument.project_id == project_id,
                        TakeoffDocument.source_document_id == str(parent.id),
                    )
                )
            ).scalar_one_or_none()
            out.previous_document_id = str(tdoc.id) if tdoc is not None else str(parent.id)
            out.previous_label = parent.revision_code or parent.name
            out.source = "documents_chain"
            return out
        return out

    # ── Report ──────────────────────────────────────────────────────────

    async def report_pdf(self, cmp: DrawingComparison, *, locale: str | None = None) -> tuple[bytes, str]:
        """The printable change report and its file name."""
        from app.modules.drawing_compare.pdf_export import build_change_report_pdf
        from app.modules.projects.models import Project

        project = await self.session.get(Project, cmp.project_id)
        rfi_numbers: dict[str, str] = {}
        rfi_ids = [u for u in (_as_uuid(c.rfi_id) for c in cmp.changes if c.rfi_id) if u is not None]
        if rfi_ids:
            try:
                from app.modules.rfi.models import RFI

                rows = await self.session.execute(select(RFI.id, RFI.rfi_number).where(RFI.id.in_(rfi_ids)))
                rfi_numbers = {str(rid): number for rid, number in rows.all()}
            except ImportError:  # pragma: no cover
                rfi_numbers = {}
        pdf = build_change_report_pdf(
            cmp,
            list(cmp.changes),
            project_name=getattr(project, "name", "") or "",
            rfi_numbers=rfi_numbers,
            locale=locale,
        )
        stem = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (cmp.new_label or "drawing"))[:60]
        return pdf, f"revision_compare_{stem}_{str(cmp.id)[:8]}.pdf"

    # ── Validation ──────────────────────────────────────────────────────

    async def validate(self, cmp: DrawingComparison, *, locale: str | None = None) -> Any:
        """Run the ``drawing_compare`` rule set over a stored compare."""
        from app.core.validation.engine import validation_engine
        from app.modules.drawing_compare.validators import DRAWING_COMPARE_RULE_SET, register_drawing_compare_rules

        register_drawing_compare_rules()
        changes = await self.repo.list_changes(cmp.id)
        payload = {
            "comparison": {
                "id": str(cmp.id),
                "source_kind": cmp.source_kind,
                "old_ref_id": cmp.old_ref_id,
                "new_ref_id": cmp.new_ref_id,
                "old_page": cmp.old_page,
                "new_page": cmp.new_page,
                "page_width": cmp.page_width,
                "page_height": cmp.page_height,
                "alignment": cmp.alignment or {},
            },
            "changes": [
                {
                    "id": str(c.id),
                    "seq": c.seq,
                    "x": c.x,
                    "y": c.y,
                    "w": c.w,
                    "h": c.h,
                    "status": c.status,
                    "comment": c.comment,
                    "rfi_id": c.rfi_id,
                    "markup_id": c.markup_id,
                    "flagged_at": c.flagged_at,
                }
                for c in changes
            ],
        }
        return await validation_engine.validate(
            data=payload,
            rule_sets=[DRAWING_COMPARE_RULE_SET],
            target_type="drawing_comparison",
            target_id=str(cmp.id),
            project_id=str(cmp.project_id),
            metadata={"locale": locale} if locale else None,
        )
