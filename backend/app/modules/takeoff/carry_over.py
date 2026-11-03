"""Carry takeoff measurements from one drawing revision onto the next.

When revision C of a sheet replaces revision B, the estimator does not want to
measure the whole sheet again. Carry-over copies every confirmed measurement of
the old revision onto the new one at the same page and the same coordinates,
re-checks the scale against the new sheet's calibration, and flags each copy
``carry_over.status = "needs_review"`` until somebody looks at it on the new
sheet and confirms it (or re-measures it). The copies keep the compare key of
their originals, so the existing revision compare shows what the re-measure
changed, per measurement and per BOQ position.

Confirming a carried measurement releases the BOQ link of the measurement it
was copied from, so the position's quantity now traces to the current revision
and the ``boq.drawing.superseded_revision`` warning clears.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status

from app.modules.takeoff import revision_match as rm

CARRY_KEY = "carry_over"
CARRIED_TO_KEY = "carried_to"
RELEASED_LINK_KEY = "released_boq_link"
NEEDS_REVIEW = "needs_review"
CONFIRMED = "confirmed"

#: Two calibrations closer than this (relative) are the same scale.
SCALE_TOLERANCE = 0.005

#: Scale verdicts, as the UI shows them.
SCALE_SAME = "same"  # new sheet calibrated at the old scale: values unchanged
SCALE_CHANGED = "changed"  # new sheet calibrated differently: values recomputed at the new scale
SCALE_UNVERIFIED = "unverified"  # new sheet not calibrated: old scale kept, calibrate and review
SCALE_NONE = "not_applicable"  # count or annotation, no scale involved

_GEOMETRY_TYPES = {"distance", "polyline", "area", "volume"}


def page_scale(page_scales: dict[str, Any] | None, page: int) -> float | None:
    """The pixels-per-unit calibration of one page, from the document's ``PageScales`` JSON.

    Only a page's own ``byPage`` entry counts; the document default is a
    convenience for drawing, not evidence that this sheet was checked.
    """
    if not isinstance(page_scales, dict):
        return None
    by_page = page_scales.get("byPage")
    entry = by_page.get(str(page)) if isinstance(by_page, dict) else None
    if not isinstance(entry, dict):
        return None
    try:
        value = float(entry.get("pixelsPerUnit") or 0)
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def scale_verdict(measurement_type: str | None, old_scale: float | None, new_scale: float | None) -> str:
    """How the new sheet's calibration relates to the scale the measurement was taken at."""
    if (measurement_type or "").strip().lower() not in _GEOMETRY_TYPES:
        return SCALE_NONE
    if not new_scale:
        return SCALE_UNVERIFIED
    if not old_scale:
        return SCALE_CHANGED
    return SCALE_SAME if abs(new_scale - old_scale) / old_scale <= SCALE_TOLERANCE else SCALE_CHANGED


def is_carried_pending(measurement: Any) -> bool:
    """True for a carried measurement nobody has confirmed yet."""
    meta = getattr(measurement, "metadata_", None)
    carry = meta.get(CARRY_KEY) if isinstance(meta, dict) else None
    return isinstance(carry, dict) and carry.get("status") == NEEDS_REVIEW


def carry_status(measurement: Any) -> tuple[str | None, str | None]:
    """``(status, scale_check)`` of a carried measurement, ``(None, None)`` otherwise."""
    meta = getattr(measurement, "metadata_", None)
    carry = meta.get(CARRY_KEY) if isinstance(meta, dict) else None
    if not isinstance(carry, dict):
        return None, None
    return carry.get("status"), carry.get("scale_check")


@dataclass(slots=True)
class CarryReport:
    """What a carry-over did, for the response and the toast."""

    carried_ids: list[str] = field(default_factory=list)
    already_carried: int = 0
    skipped_unreviewed: int = 0
    skipped_page_missing: int = 0
    remeasure_ids: list[str] = field(default_factory=list)
    scale_checks: dict[str, int] = field(default_factory=dict)
    revision_link: str = "unlinked"

    def as_dict(self) -> dict[str, Any]:
        """JSON shape of the API."""
        return {
            "carried": len(self.carried_ids),
            "carried_ids": self.carried_ids,
            "already_carried": self.already_carried,
            "skipped_unreviewed": self.skipped_unreviewed,
            "skipped_page_missing": self.skipped_page_missing,
            "remeasure_ids": self.remeasure_ids,
            "scale_checks": self.scale_checks,
            "revision_link": self.revision_link,
        }


def _number(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def carried_values(old: Any, new_scale: float | None) -> dict[str, Any]:
    """Value columns of the copy: recomputed from the same points at the new sheet's scale.

    Without a calibration on the new sheet the old scale is kept, so the copy
    reads the same quantity until somebody calibrates the sheet.
    """
    from app.modules.takeoff.service import (  # noqa: PLC0415 - geometry lives with the service
        recompute_measurement_value,
        recompute_volume_value,
    )

    scale = new_scale or old.scale_pixels_per_unit
    old_value = _number(old.measurement_value)
    value = recompute_measurement_value(
        measurement_type=old.type,
        points=old.points,
        scale_pixels_per_unit=scale,
        count_value=old.count_value,
        client_value=old_value,
    )
    volume = recompute_volume_value(
        measurement_type=old.type,
        points=old.points,
        scale_pixels_per_unit=scale,
        depth=_number(old.depth),
        client_volume=_number(old.volume),
    )
    return {"scale_pixels_per_unit": scale, "measurement_value": value, "volume": volume}


async def _source_document_id(session: Any, document_id: str, project_id: uuid.UUID) -> tuple[str | None, Any]:
    """The Project Files document behind a measurement ``document_id``, and the takeoff row if any."""
    from app.modules.documents.models import Document  # noqa: PLC0415
    from app.modules.takeoff.models import TakeoffDocument  # noqa: PLC0415

    try:
        doc_uuid = uuid.UUID(str(document_id))
    except (ValueError, TypeError):
        return None, None
    takeoff_doc = await session.get(TakeoffDocument, doc_uuid)
    if takeoff_doc is not None and takeoff_doc.project_id == project_id:
        return takeoff_doc.source_document_id, takeoff_doc
    project_doc = await session.get(Document, doc_uuid)
    if project_doc is not None and project_doc.project_id == project_id:
        return str(project_doc.id), None
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found in this project")


async def revision_link(session: Any, from_source: str | None, to_source: str | None) -> str:
    """``register`` when Project Files says ``to`` replaced ``from``, else ``unlinked``.

    The register links revisions two ways: a document revision chain
    (``parent_document_id`` / ``is_current_revision``) and a sheet chain
    (``Sheet.previous_version_id``). Refuses (422) when the document chain
    names a different current revision: carrying measurements onto an
    unrelated sheet is never right. Loose uploads with no register entry pass
    as ``unlinked`` so a PDF dropped straight into takeoff still works.
    """
    from sqlalchemy import select  # noqa: PLC0415

    from app.modules.boq.drawing_refs import superseded_documents  # noqa: PLC0415
    from app.modules.documents.models import Sheet  # noqa: PLC0415

    if not from_source or not to_source:
        return "unlinked"
    if from_source == to_source:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Both sides are the same drawing revision",
        )
    superseded = await superseded_documents(session, {from_source})
    successor = superseded.get(from_source)
    if successor == to_source:
        return "register"
    if successor:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The target is not the current revision of the source drawing in Project Files",
        )
    old_sheets = select(Sheet.id).where(Sheet.document_id == from_source)
    chained = await session.execute(
        select(Sheet.id).where(Sheet.document_id == to_source, Sheet.previous_version_id.in_(old_sheets)).limit(1)
    )
    return "register" if chained.first() is not None else "unlinked"


ALIGN_NONE = "none"
ALIGN_AUTO = "auto"


async def _page_meta(session: Any, source_id: str | None, doc: Any) -> list[dict[str, Any]]:
    """``[{page, number, title}]`` for a revision: its register sheets, else bare page numbers."""
    from sqlalchemy import select  # noqa: PLC0415

    from app.modules.documents.models import Sheet  # noqa: PLC0415

    rows: dict[int, dict[str, Any]] = {}
    if source_id:
        found = await session.execute(
            select(Sheet.page_number, Sheet.sheet_number, Sheet.sheet_title).where(Sheet.document_id == source_id)
        )
        for page, number, title in found.all():
            rows[int(page)] = {"page": int(page), "number": number, "title": title}
    pages = int(getattr(doc, "pages", 0) or 0)
    for page in range(1, pages + 1):
        rows.setdefault(page, {"page": page, "number": None, "title": None})
    return [rows[k] for k in sorted(rows)]


def _page_anchors(page_scales: Any, page: int) -> list[Any]:
    """Anchor points saved with a page's calibration (``byPage[page].anchors``), if any."""
    by_page = page_scales.get("byPage") if isinstance(page_scales, dict) else None
    entry = by_page.get(str(page)) if isinstance(by_page, dict) else None
    anchors = entry.get("anchors") if isinstance(entry, dict) else None
    return anchors if isinstance(anchors, list) else []


class Alignment:
    """Where each old page lands on the new revision, and the geometry fit per page."""

    def __init__(self, matches: list[rm.PageMatch], from_scales: Any, to_scales: Any, *, auto: bool) -> None:
        self.matches = {m.old: m for m in matches}
        self.auto = auto
        self.transforms: dict[int, rm.Transform] = {}
        self.diagonals: dict[int, float | None] = {}
        for m in matches:
            if m.new is None:
                continue
            old_a, new_a = _page_anchors(from_scales, m.old), _page_anchors(to_scales, m.new)
            self.transforms[m.old] = rm.estimate_transform(old_a, new_a) if auto else rm.Transform()
            xy = [p for p in (rm.anchor_xy(a) for a in new_a) if p]
            if len(xy) >= 2:
                xs, ys = [p[0] for p in xy], [p[1] for p in xy]
                self.diagonals[m.old] = ((max(xs) - min(xs)) ** 2 + (max(ys) - min(ys)) ** 2) ** 0.5
            else:
                self.diagonals[m.old] = None

    def propose(self, old: Any, scale_check: str) -> dict[str, Any] | None:
        """The proposal for one measurement, or None when its sheet has no counterpart."""
        match = self.matches.get(old.page or 1)
        if match is None or match.new is None:
            return None
        transform = self.transforms[match.old]
        conf = rm.confidence(match.score, transform, self.diagonals.get(match.old), scale_check)
        moved = rm.apply_transform(list(old.points or []), transform) if self.auto and transform.ok else None
        return {
            "page": match.new,
            "from_page": match.old,
            "page_method": match.method,
            "match_confidence": conf,
            "band": rm.band(conf),
            "transform": transform.as_dict(),
            "points": moved if moved else list(old.points or []),
        }


async def build_alignment(
    session: Any,
    from_source: str | None,
    from_doc: Any,
    to_source: str | None,
    to_doc: Any,
    *,
    align: str,
    page_map: dict[int, int] | None,
) -> Alignment:
    """Match the sheets of two revisions and fit each matched pair's geometry."""
    old_meta = await _page_meta(session, from_source, from_doc)
    new_meta = await _page_meta(session, to_source, to_doc)
    if align == ALIGN_AUTO:
        matches = rm.match_pages(old_meta, new_meta, page_map)
    else:
        # Manual map only: unmapped pages stay on the same page number, as before.
        new_pages = {m["page"] for m in new_meta}
        matches = []
        for m in old_meta:
            target = (page_map or {}).get(m["page"])
            if target in new_pages:
                matches.append(rm.PageMatch(m["page"], target, 1.0, rm.METHOD_MANUAL))
            else:
                same = m["page"] if m["page"] in new_pages else None
                matches.append(rm.PageMatch(m["page"], same, 1.0, rm.METHOD_INDEX))
    return Alignment(
        matches,
        getattr(from_doc, "page_scales", None),
        getattr(to_doc, "page_scales", None),
        auto=align == ALIGN_AUTO,
    )


def carried_values_at(old: Any, new_scale: float | None, points: list[Any]) -> dict[str, Any]:
    """:func:`carried_values` for points that were moved onto the new sheet."""

    class _Moved:
        def __getattr__(self, name: str) -> Any:
            return points if name == "points" else getattr(old, name)

    return carried_values(_Moved(), new_scale)


async def carry_measurements(
    service: Any,
    project_id: uuid.UUID,
    from_document_id: str,
    to_document_id: str,
    *,
    user_id: str,
    measurement_ids: list[str] | None = None,
    align: str = ALIGN_NONE,
    page_map: dict[int, int] | None = None,
) -> dict[str, Any]:
    """Copy the confirmed measurements of ``from`` onto ``to``, flagged for review.

    Idempotent: a measurement already carried onto ``to`` is not copied twice.
    With ``align="auto"`` sheets are matched by number/title and geometry is
    fitted to anchor pairs; ``page_map`` (old page -> new page) overrides the
    match. Proposals under the review band are not copied and are listed in
    ``remeasure_ids``. The default ``none`` keeps the same page, same pixels.
    """
    from app.modules.takeoff.models import TakeoffMeasurement  # noqa: PLC0415
    from app.modules.takeoff.service import MAX_COMPARE_MEASUREMENTS  # noqa: PLC0415

    if from_document_id == to_document_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Pick two different revisions",
        )
    session = service.session
    from_source, from_doc = await _source_document_id(session, from_document_id, project_id)
    to_source, to_doc = await _source_document_id(session, to_document_id, project_id)
    report = CarryReport(revision_link=await revision_link(session, from_source, to_source))

    old_rows = await service.measurement_repo.list_all_for_document(
        project_id, from_document_id, max_rows=MAX_COMPARE_MEASUREMENTS
    )
    new_rows = await service.measurement_repo.list_all_for_document(
        project_id, to_document_id, max_rows=MAX_COMPARE_MEASUREMENTS
    )
    already = {
        str((m.metadata_ or {}).get(CARRY_KEY, {}).get("from_measurement_id"))
        for m in new_rows
        if isinstance(m.metadata_, dict) and isinstance(m.metadata_.get(CARRY_KEY), dict)
    }
    wanted = {str(i) for i in measurement_ids} if measurement_ids else None
    pages = int(getattr(to_doc, "pages", 0) or 0)
    scales = getattr(to_doc, "page_scales", None)
    now = datetime.now(UTC).isoformat()
    aligned: Alignment | None = None
    if align == ALIGN_AUTO or page_map:
        aligned = await build_alignment(
            session, from_source, from_doc, to_source, to_doc, align=align, page_map=page_map
        )

    copies: list[tuple[Any, Any]] = []
    for old in sorted(old_rows, key=lambda m: (m.page or 1, str(m.id))):
        if wanted is not None and str(old.id) not in wanted:
            continue
        if str(old.id) in already:
            report.already_carried += 1
            continue
        if (old.review_status or CONFIRMED) != CONFIRMED or is_carried_pending(old):
            # A proposal nobody accepted, or a copy nobody checked, is not a measurement to propagate.
            report.skipped_unreviewed += 1
            continue
        proposal: dict[str, Any] | None = None
        target_page = old.page or 1
        if aligned is None:
            if pages and target_page > pages:
                report.skipped_page_missing += 1
                continue
        else:
            match = aligned.matches.get(target_page)
            if match is None or match.new is None:
                report.skipped_page_missing += 1
                continue
            target_page = match.new
        new_scale = page_scale(scales, target_page)
        verdict = scale_verdict(old.type, old.scale_pixels_per_unit, new_scale)
        if aligned is not None:
            proposal = aligned.propose(old, verdict)
            if proposal is not None and align == ALIGN_AUTO and proposal["band"] == rm.BAND_REMEASURE:
                report.remeasure_ids.append(str(old.id))
                continue
        report.scale_checks[verdict] = report.scale_checks.get(verdict, 0) + 1
        if proposal is not None:
            values = carried_values_at(old, new_scale, proposal["points"])
        else:
            values = carried_values(old, new_scale)
        base_meta = {
            k: v for k, v in (old.metadata_ or {}).items() if k not in (CARRY_KEY, CARRIED_TO_KEY, RELEASED_LINK_KEY)
        }
        base_meta[CARRY_KEY] = {
            "status": NEEDS_REVIEW,
            "from_measurement_id": str(old.id),
            "from_document_id": from_document_id,
            "from_revision": old.drawing_revision,
            "scale_check": verdict,
            "old_scale": old.scale_pixels_per_unit,
            "new_scale": new_scale,
            "old_value": _number(old.measurement_value),
            "carried_at": now,
            "carried_by": user_id,
        }
        if proposal is not None:
            base_meta[CARRY_KEY].update(
                match_confidence=proposal["match_confidence"],
                page_match=proposal["page_method"],
                transform=proposal["transform"],
                from_page=proposal["from_page"],
            )
        copy = TakeoffMeasurement(
            project_id=project_id,
            document_id=to_document_id,
            page=target_page,
            type=old.type,
            group_name=old.group_name,
            group_color=old.group_color,
            annotation=old.annotation,
            points=list(proposal["points"]) if proposal is not None else list(old.points or []),
            measurement_value=values["measurement_value"],
            measurement_unit=old.measurement_unit,
            depth=old.depth,
            volume=values["volume"],
            perimeter=old.perimeter if verdict in (SCALE_SAME, SCALE_NONE, SCALE_UNVERIFIED) else None,
            count_value=old.count_value,
            is_deduction=bool(old.is_deduction),
            scale_pixels_per_unit=values["scale_pixels_per_unit"],
            scale_source="inherited" if new_scale else old.scale_source,
            linked_boq_position_id=old.linked_boq_position_id,
            source=old.source or "manual",
            confidence=old.confidence,
            review_status=CONFIRMED,
            metadata_=base_meta,
            created_by=user_id,
        )
        await service._stamp_drawing(copy)  # noqa: SLF001 - same provenance stamp as a hand-drawn row
        copies.append((old, copy))

    if copies:
        await service.measurement_repo.create_bulk([c for _o, c in copies])
        for old, copy in copies:
            meta = dict(old.metadata_ or {})
            meta[CARRIED_TO_KEY] = str(copy.id)
            await service.measurement_repo.update_fields(old.id, metadata_=meta)
            report.carried_ids.append(str(copy.id))
    return report.as_dict()


async def preview_carry(
    service: Any,
    project_id: uuid.UUID,
    from_document_id: str,
    to_document_id: str,
    *,
    align: str = ALIGN_AUTO,
    page_map: dict[int, int] | None = None,
) -> dict[str, Any]:
    """What a carry-over would do, with zero writes: page matches, fit and per-item confidence."""
    from app.modules.takeoff.service import MAX_COMPARE_MEASUREMENTS  # noqa: PLC0415

    if from_document_id == to_document_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Pick two different revisions",
        )
    session = service.session
    from_source, from_doc = await _source_document_id(session, from_document_id, project_id)
    to_source, to_doc = await _source_document_id(session, to_document_id, project_id)
    link = await revision_link(session, from_source, to_source)
    aligned = await build_alignment(session, from_source, from_doc, to_source, to_doc, align=align, page_map=page_map)
    old_rows = await service.measurement_repo.list_all_for_document(
        project_id, from_document_id, max_rows=MAX_COMPARE_MEASUREMENTS
    )
    new_rows = await service.measurement_repo.list_all_for_document(
        project_id, to_document_id, max_rows=MAX_COMPARE_MEASUREMENTS
    )
    already = {
        str((m.metadata_ or {}).get(CARRY_KEY, {}).get("from_measurement_id"))
        for m in new_rows
        if isinstance(m.metadata_, dict) and isinstance(m.metadata_.get(CARRY_KEY), dict)
    }
    scales = getattr(to_doc, "page_scales", None)
    items: list[dict[str, Any]] = []
    for old in sorted(old_rows, key=lambda m: (m.page or 1, str(m.id))):
        if str(old.id) in already or (old.review_status or CONFIRMED) != CONFIRMED or is_carried_pending(old):
            continue
        match = aligned.matches.get(old.page or 1)
        if match is None or match.new is None:
            items.append(
                {"measurement_id": str(old.id), "page_old": old.page or 1, "page_new": None, "confidence": 0.0}
                | {"band": rm.BAND_REMEASURE, "points_after": []}
            )
            continue
        verdict = scale_verdict(old.type, old.scale_pixels_per_unit, page_scale(scales, match.new))
        proposal = aligned.propose(old, verdict)
        if proposal is None:
            continue
        items.append(
            {
                "measurement_id": str(old.id),
                "page_old": proposal["from_page"],
                "page_new": proposal["page"],
                "confidence": proposal["match_confidence"],
                "band": proposal["band"],
                "points_after": proposal["points"],
            }
        )
    first = next((t for t in aligned.transforms.values() if t.ok), rm.Transform())
    return {
        "revision_link": link,
        "pages": [m.as_dict() for m in aligned.matches.values()],
        "transform": first.as_dict(),
        "items": items,
    }


async def confirm_carried(
    service: Any,
    project_id: uuid.UUID,
    measurement_ids: list[str],
    *,
    user_id: str,
    push_quantity: bool = False,
) -> dict[str, Any]:
    """Confirm carried measurements; release the superseded original's BOQ link.

    With ``push_quantity`` the confirmed value is written into the linked BOQ
    position through the same guarded path as a link-and-push.
    """
    confirmed: list[str] = []
    pushed: list[str] = []
    not_pending = 0
    for raw in measurement_ids:
        try:
            mid = uuid.UUID(str(raw))
        except ValueError:
            not_pending += 1
            continue
        m = await service.measurement_repo.get_by_id(mid)
        if m is None or m.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Measurement not found")
        if not is_carried_pending(m):
            not_pending += 1
            continue
        meta = dict(m.metadata_ or {})
        carry = dict(meta[CARRY_KEY])
        carry.update(status=CONFIRMED, confirmed_at=datetime.now(UTC).isoformat(), confirmed_by=user_id)
        meta[CARRY_KEY] = carry
        await service.measurement_repo.update_fields(m.id, metadata_=meta)
        origin_id = carry.get("from_measurement_id")
        if origin_id and m.linked_boq_position_id:
            try:
                origin = await service.measurement_repo.get_by_id(uuid.UUID(str(origin_id)))
            except ValueError:
                origin = None
            if origin is not None and origin.linked_boq_position_id == m.linked_boq_position_id:
                origin_meta = dict(origin.metadata_ or {})
                origin_meta[RELEASED_LINK_KEY] = origin.linked_boq_position_id
                await service.measurement_repo.update_fields(
                    origin.id, linked_boq_position_id=None, metadata_=origin_meta
                )
        if push_quantity and m.linked_boq_position_id:
            await service._push_quantity_to_position(m.linked_boq_position_id, m)  # noqa: SLF001
            pushed.append(str(m.id))
        confirmed.append(str(m.id))
    return {"confirmed": len(confirmed), "confirmed_ids": confirmed, "pushed": len(pushed), "not_pending": not_pending}


def position_deltas(rows: list[dict[str, Any]], positions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Per BOQ position: measured quantity on each revision, the delta and its money.

    ``rows`` are compare rows (``old_value`` / ``new_value`` / ``cost_impact`` /
    ``is_deduction``); ``positions`` maps position id -> ordinal, description,
    unit and the quantity the bill holds now.
    """
    from decimal import Decimal, InvalidOperation  # noqa: PLC0415

    acc: dict[str, dict[str, Any]] = {}
    for row in rows:
        pid = row.get("linked_boq_position_id")
        if not pid or (row.get("review_status") or CONFIRMED) != CONFIRMED:
            # An AI proposal nobody accepted is not a quantity of either revision.
            continue
        sign = -1.0 if row.get("is_deduction") else 1.0
        e = acc.setdefault(
            pid,
            {"old": 0.0, "new": 0.0, "cost": Decimal("0"), "has_cost": False, "pending": 0, "rows": 0},
        )
        e["old"] += sign * float(row.get("old_value") or 0.0)
        e["new"] += sign * float(row.get("new_value") or 0.0)
        e["rows"] += 1
        if row.get("carry_status") == NEEDS_REVIEW:
            e["pending"] += 1
        if row.get("cost_impact") is not None:
            try:
                e["cost"] += Decimal(str(row["cost_impact"]))
                e["has_cost"] = True
            except (InvalidOperation, ValueError):
                pass
    out: list[dict[str, Any]] = []
    for pid, e in acc.items():
        pos = positions.get(pid) or {}
        out.append(
            {
                "position_id": pid,
                "ordinal": pos.get("ordinal"),
                "description": pos.get("description"),
                "unit": pos.get("unit"),
                "boq_quantity": pos.get("quantity"),
                "old_quantity": round(e["old"], 4),
                "new_quantity": round(e["new"], 4),
                "delta_quantity": round(e["new"] - e["old"], 4),
                "cost_impact": str(e["cost"].quantize(Decimal("0.01"))) if e["has_cost"] else None,
                "carried_pending": e["pending"],
                "measurements": e["rows"],
            }
        )
    out.sort(key=lambda d: (str(d.get("ordinal") or ""), d["position_id"]))
    return out
