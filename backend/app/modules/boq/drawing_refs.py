# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Which drawing sheet and revision each BOQ quantity came from.

A takeoff measurement is stamped with the drawing it was taken on (Project Files document,
sheet, number, title, revision) when it is created. A BOQ position then knows its source
drawings through the measurements linked to it, plus an optional manual reference the
estimator types for a line that did not come from a takeoff (``metadata.drawing_ref`` and
``metadata.drawing_revision``).

"Outdated" is derived on read, never stored: the recorded revision is compared with what the
documents register calls current today. Registering a newer revision therefore flags every
affected position at once, and withdrawing it un-flags them, with nothing to keep in sync.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

#: Position metadata keys of the manual reference.
MANUAL_REF_KEY = "drawing_ref"
MANUAL_REV_KEY = "drawing_revision"
#: Transient metadata key the exporters read; set on in-memory export rows only.
EXPORT_TEXT_KEY = "_drawing_ref_text"


@dataclass(slots=True)
class DrawingProvenance:
    """The drawing a measurement was taken on, as the register read at that moment."""

    document_id: str | None = None
    sheet_id: str | None = None
    number: str | None = None
    title: str | None = None
    revision: str | None = None

    def as_columns(self) -> dict[str, str | None]:
        """The ``TakeoffMeasurement`` column values."""
        return {
            "drawing_document_id": self.document_id,
            "drawing_sheet_id": self.sheet_id,
            "drawing_number": self.number,
            "drawing_title": self.title,
            "drawing_revision": self.revision,
        }


def _clip(value: Any, length: int) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text[:length] or None


async def resolve_provenance(
    session: AsyncSession, project_id: uuid.UUID, document_id: str | None, page: int
) -> DrawingProvenance:
    """Read the drawing behind ``document_id`` / ``page`` from the documents register.

    ``document_id`` is the measurement's polymorphic reference: a takeoff upload (whose
    ``source_document_id`` names the Project Files document, if any) or a Project Files
    document directly. A sheet row for the page wins over the document's own fields, since a
    multi-sheet PDF carries one number and revision per page.
    """
    from app.modules.documents.models import Document, Sheet  # noqa: PLC0415
    from app.modules.takeoff.models import TakeoffDocument  # noqa: PLC0415

    if not document_id:
        return DrawingProvenance()
    try:
        doc_uuid = uuid.UUID(str(document_id))
    except (ValueError, TypeError):
        return DrawingProvenance()

    source_id: uuid.UUID | None = None
    takeoff_doc = await session.get(TakeoffDocument, doc_uuid)
    if takeoff_doc is not None and takeoff_doc.project_id == project_id:
        if takeoff_doc.source_document_id:
            try:
                source_id = uuid.UUID(str(takeoff_doc.source_document_id))
            except ValueError:
                source_id = None
    else:
        source_id = doc_uuid
    if source_id is None:
        return DrawingProvenance()

    document = await session.get(Document, source_id)
    if document is None or document.project_id != project_id:
        return DrawingProvenance()
    prov = DrawingProvenance(
        document_id=str(document.id),
        number=_clip(document.drawing_number, 100),
        title=_clip(document.name, 500),
        revision=_clip(document.revision_code, 50),
    )
    sheet = (
        await session.execute(
            select(Sheet).where(Sheet.document_id == str(document.id), Sheet.page_number == int(page or 1)).limit(1)
        )
    ).scalar_one_or_none()
    if sheet is not None:
        prov.sheet_id = str(sheet.id)
        prov.number = _clip(sheet.sheet_number, 100) or prov.number
        prov.title = _clip(sheet.sheet_title, 500) or prov.title
        prov.revision = _clip(sheet.revision, 50) or prov.revision
    return prov


@dataclass(slots=True)
class DrawingRef:
    """One source drawing of a position, aggregated over its measurements."""

    document_id: str | None
    takeoff_document_id: str | None
    sheet_id: str | None
    drawing_number: str | None
    drawing_title: str | None
    revision: str | None
    page: int
    measurement_count: int = 0
    current_revision: str | None = None
    outdated: bool = False
    compare: dict[str, str] | None = None

    def as_dict(self) -> dict[str, Any]:
        """JSON shape of the API and the validation context."""
        return {
            "document_id": self.document_id,
            "takeoff_document_id": self.takeoff_document_id,
            "sheet_id": self.sheet_id,
            "drawing_number": self.drawing_number,
            "drawing_title": self.drawing_title,
            "revision": self.revision,
            "current_revision": self.current_revision,
            "page": self.page,
            "measurement_count": self.measurement_count,
            "outdated": self.outdated,
            "compare": self.compare,
        }


@dataclass(slots=True)
class PositionDrawingRefs:
    """Every source drawing of one position plus its manual reference."""

    position_id: str
    ordinal: str
    refs: list[DrawingRef] = field(default_factory=list)
    manual: dict[str, str | None] | None = None
    manual_outdated: bool = False
    #: Measurements linked to the position that carry no recorded revision.
    unrevised_measurements: int = 0

    @property
    def outdated(self) -> bool:
        """True when any source drawing, manual or measured, has a newer revision."""
        return self.manual_outdated or any(r.outdated for r in self.refs)

    def as_dict(self) -> dict[str, Any]:
        """JSON shape of the API and the validation context."""
        return {
            "position_id": self.position_id,
            "ordinal": self.ordinal,
            "outdated": self.outdated,
            "manual": self.manual,
            "manual_outdated": self.manual_outdated,
            "unrevised_measurements": self.unrevised_measurements,
            "refs": [r.as_dict() for r in self.refs],
        }

    def export_text(self) -> str | None:
        """One line for the exports: ``A-101 rev C; S-200 rev 2``."""
        parts: list[str] = []
        for ref in self.refs:
            label = ref.drawing_number or ref.drawing_title
            if not label:
                continue
            parts.append(f"{label} rev {ref.revision}" if ref.revision else label)
        if self.manual and self.manual.get(MANUAL_REF_KEY):
            ref_text = str(self.manual[MANUAL_REF_KEY])
            rev = self.manual.get(MANUAL_REV_KEY)
            parts.append(f"{ref_text} rev {rev}" if rev else ref_text)
        seen: list[str] = []
        for p in parts:
            if p not in seen:
                seen.append(p)
        return "; ".join(seen) or None


def _norm(value: str | None) -> str:
    return (value or "").strip().casefold()


async def _current_revisions(session: AsyncSession, project_id: uuid.UUID) -> dict[str, tuple[str | None, str]]:
    """Drawing number -> (revision, document id) the register calls current in this project.

    Sheets win over documents because they carry the per-page title block; a number with no
    current row at all is absent, so it can never flag anything.
    """
    from app.modules.documents.models import Document, Sheet  # noqa: PLC0415

    current: dict[str, tuple[str | None, str]] = {}
    docs = await session.execute(
        select(Document.drawing_number, Document.revision_code, Document.id).where(
            Document.project_id == project_id,
            Document.drawing_number.is_not(None),
            Document.is_current_revision.is_not(False),
        )
    )
    for number, rev, doc_id in docs.all():
        if _norm(number):
            current[_norm(number)] = (rev, str(doc_id))
    sheets = await session.execute(
        select(Sheet.sheet_number, Sheet.revision, Sheet.document_id).where(
            Sheet.project_id == project_id, Sheet.sheet_number.is_not(None), Sheet.is_current.is_(True)
        )
    )
    for number, rev, doc_id in sheets.all():
        if _norm(number):
            current[_norm(number)] = (rev, str(doc_id))
    return current


async def _superseded(
    session: AsyncSession, document_ids: set[str], sheet_ids: set[str]
) -> tuple[set[str], set[str], dict[str, str]]:
    """Recorded documents / sheets the register has since replaced, and their successors.

    Returns (superseded document ids, superseded sheet ids, document id -> current document id
    of the same revision chain).
    """
    from app.modules.documents.models import Document, Sheet  # noqa: PLC0415

    def _uuids(ids: set[str]) -> list[uuid.UUID]:
        out: list[uuid.UUID] = []
        for raw in ids:
            try:
                out.append(uuid.UUID(raw))
            except ValueError:
                continue
        return out

    old_docs: set[str] = set()
    successor: dict[str, str] = {}
    if document_ids:
        rows = (
            await session.execute(
                select(Document.id, Document.parent_document_id, Document.is_current_revision).where(
                    Document.id.in_(_uuids(document_ids))
                )
            )
        ).all()
        roots: dict[str, uuid.UUID] = {}
        for doc_id, parent_id, is_current in rows:
            if is_current is False:
                old_docs.add(str(doc_id))
                roots[str(doc_id)] = parent_id or doc_id
        if roots:
            chain = (
                await session.execute(
                    select(Document.id, Document.parent_document_id).where(
                        (Document.parent_document_id.in_(set(roots.values())) | Document.id.in_(set(roots.values()))),
                        Document.is_current_revision.is_(True),
                    )
                )
            ).all()
            for cur_id, cur_parent in chain:
                for old_id, root in roots.items():
                    if root in (cur_id, cur_parent):
                        successor[old_id] = str(cur_id)
    old_sheets: set[str] = set()
    if sheet_ids:
        rows = (await session.execute(select(Sheet.id, Sheet.is_current).where(Sheet.id.in_(_uuids(sheet_ids))))).all()
        old_sheets = {str(sid) for sid, is_current in rows if not is_current}
    return old_docs, old_sheets, successor


async def _takeoff_docs_for(session: AsyncSession, project_id: uuid.UUID, source_ids: set[str]) -> dict[str, str]:
    """Project Files document id -> takeoff document id opened from it."""
    from app.modules.takeoff.models import TakeoffDocument  # noqa: PLC0415

    if not source_ids:
        return {}
    rows = await session.execute(
        select(TakeoffDocument.source_document_id, TakeoffDocument.id).where(
            TakeoffDocument.project_id == project_id, TakeoffDocument.source_document_id.in_(source_ids)
        )
    )
    return {str(src): str(tid) for src, tid in rows.all() if src}


async def drawing_refs_for_boq(
    session: AsyncSession, boq_id: uuid.UUID, project_id: uuid.UUID
) -> dict[str, PositionDrawingRefs]:
    """Position id -> source drawings for every position of the bill that has any."""
    from app.modules.boq.models import Position  # noqa: PLC0415
    from app.modules.takeoff.models import TakeoffMeasurement  # noqa: PLC0415

    positions = (
        await session.execute(
            select(Position.id, Position.ordinal, Position.metadata_).where(Position.boq_id == boq_id)
        )
    ).all()
    if not positions:
        return {}
    by_id = {str(pid): (ordinal or "", meta if isinstance(meta, dict) else {}) for pid, ordinal, meta in positions}

    measurements = (
        await session.execute(
            select(TakeoffMeasurement).where(
                TakeoffMeasurement.project_id == project_id,
                TakeoffMeasurement.linked_boq_position_id.in_(list(by_id)),
                TakeoffMeasurement.review_status != "rejected",
            )
        )
    ).scalars()

    out: dict[str, PositionDrawingRefs] = {}

    def _entry(pid: str) -> PositionDrawingRefs:
        if pid not in out:
            out[pid] = PositionDrawingRefs(position_id=pid, ordinal=by_id[pid][0])
        return out[pid]

    grouped: dict[tuple[str, tuple[Any, ...]], DrawingRef] = {}
    for m in measurements:
        pid = str(m.linked_boq_position_id)
        entry = _entry(pid)
        if not m.drawing_revision:
            entry.unrevised_measurements += 1
        key = (pid, (m.drawing_document_id or m.document_id, m.drawing_sheet_id, m.drawing_revision, m.page))
        ref = grouped.get(key)
        if ref is None:
            ref = DrawingRef(
                document_id=m.drawing_document_id,
                takeoff_document_id=m.document_id,
                sheet_id=m.drawing_sheet_id,
                drawing_number=m.drawing_number,
                drawing_title=m.drawing_title,
                revision=m.drawing_revision,
                page=m.page or 1,
            )
            grouped[key] = ref
            entry.refs.append(ref)
        ref.measurement_count += 1

    for pid, (_ordinal, meta) in by_id.items():
        manual_ref = str(meta.get(MANUAL_REF_KEY) or "").strip()
        if manual_ref:
            manual_rev = str(meta.get(MANUAL_REV_KEY) or "").strip() or None
            _entry(pid).manual = {MANUAL_REF_KEY: manual_ref, MANUAL_REV_KEY: manual_rev}

    if not out:
        return out

    current = await _current_revisions(session, project_id)
    doc_ids = {r.document_id for e in out.values() for r in e.refs if r.document_id}
    sheet_ids = {r.sheet_id for e in out.values() for r in e.refs if r.sheet_id}
    old_docs, old_sheets, successor = await _superseded(session, doc_ids, sheet_ids)
    takeoff_of = await _takeoff_docs_for(
        session, project_id, set(successor.values()) | {doc for _rev, doc in current.values()}
    )

    for entry in out.values():
        for ref in entry.refs:
            cur_rev, cur_doc = current.get(_norm(ref.drawing_number), (None, "")) if ref.drawing_number else (None, "")
            cur = cur_rev
            ref.current_revision = cur
            by_register = (ref.document_id in old_docs) or (ref.sheet_id in old_sheets)
            by_number = bool(ref.revision and cur and _norm(cur) != _norm(ref.revision))
            ref.outdated = by_register or by_number
            new_doc = successor.get(ref.document_id or "") or (cur_doc if cur_doc != ref.document_id else None)
            new_takeoff = takeoff_of.get(new_doc or "")
            if ref.outdated and ref.takeoff_document_id and new_takeoff and new_takeoff != ref.takeoff_document_id:
                ref.compare = {"from_document_id": ref.takeoff_document_id, "to_document_id": new_takeoff}
        if entry.manual and entry.manual.get(MANUAL_REV_KEY):
            cur = current.get(_norm(entry.manual[MANUAL_REF_KEY]), (None, ""))[0]
            entry.manual_outdated = bool(cur and _norm(cur) != _norm(entry.manual[MANUAL_REV_KEY]))
    return out


def stamp_export_text(rows: Any, refs: dict[str, PositionDrawingRefs]) -> None:
    """Put each position's drawing line under ``metadata[EXPORT_TEXT_KEY]`` on export rows.

    Walks ``BOQWithSections`` (sections with positions) or a flat ``positions`` list. Only the
    in-memory response objects are touched, never the database rows.
    """
    if not refs:
        return

    def _visit(pos: Any) -> None:
        entry = refs.get(str(getattr(pos, "id", "")))
        text = entry.export_text() if entry else None
        if not text:
            return
        meta = getattr(pos, "metadata", None)
        if not isinstance(meta, dict):
            meta = {}
            try:
                pos.metadata = meta
            except (AttributeError, TypeError, ValueError):
                return
        meta[EXPORT_TEXT_KEY] = text

    for pos in getattr(rows, "positions", None) or []:
        _visit(pos)
    for section in getattr(rows, "sections", None) or []:
        for pos in getattr(section, "positions", None) or []:
            _visit(pos)


def export_text(pos: Any) -> str | None:
    """The drawing line an exporter prints for ``pos``, if the export stamped one."""
    meta = getattr(pos, "metadata", None)
    if isinstance(meta, dict):
        value = meta.get(EXPORT_TEXT_KEY)
        return str(value) if value else None
    return None
