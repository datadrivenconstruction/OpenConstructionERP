"""Field reports <-> the accepted revision's elements and BOQ positions.

The link lives in the report's own ``metadata.design`` (the ERP's free metadata field), so no core schema changes:
``{revision_id, model_id, element_keys, position_ids}``. A person picks the report and the elements; keys and
positions are checked against the accepted (published) revision and the design's own BOQ links before anything is
written. An approved report is a record and stays as it is.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select

from . import links
from .models import DesignRevision

MAX_REPORTS = 1000
EXCERPT = 160


async def published(session, project_id: uuid.UUID) -> DesignRevision | None:
    rows = (
        (
            await session.execute(
                select(DesignRevision)
                .where(DesignRevision.project_id == project_id, DesignRevision.status == "published")
                .order_by(DesignRevision.number.desc())
            )
        )
        .scalars()
        .all()
    )
    return next((r for r in rows if r.bim_model_id is not None), None)


def _design(report) -> dict[str, Any]:
    meta = report.metadata_ if isinstance(report.metadata_, dict) else {}
    d = meta.get("design")
    return d if isinstance(d, dict) else {}


def _row(report, d: dict[str, Any]) -> dict[str, Any]:
    text = (report.work_performed or "").strip().replace("\n", " ")
    return {
        "id": str(report.id),
        "report_date": str(report.report_date),
        "report_type": report.report_type,
        "status": report.status,
        "excerpt": text[:EXCERPT],
        "keys": list(d.get("element_keys") or []),
        "position_ids": list(d.get("position_ids") or []),
        "revision_id": d.get("revision_id"),
    }


async def _reports(session, project_id: uuid.UUID) -> list[Any]:
    from app.modules.fieldreports.models import FieldReport

    return list(
        (
            await session.execute(
                select(FieldReport)
                .where(FieldReport.project_id == project_id)
                .order_by(FieldReport.report_date.desc())
                .limit(MAX_REPORTS)
            )
        ).scalars()
    )


async def candidates(session, project_id: uuid.UUID) -> list[dict[str, Any]]:
    """The project's field reports, newest first, with what each one is linked to today."""
    return [_row(r, _design(r)) for r in await _reports(session, project_id)]


async def for_elements(session, project_id: uuid.UUID, keys: list[str]) -> list[dict[str, Any]]:
    """Reports that name one of these elements, or a BOQ position that one of them feeds."""
    want = set(keys)
    g = await links.build(session, project_id)
    via = {str(pid) for pid, n in g.positions.items() if want & set(n.keys)}
    out = []
    for r in await _reports(session, project_id):
        d = _design(r)
        hit_keys = sorted(want & set(d.get("element_keys") or []))
        hit_pos = sorted(via & set(d.get("position_ids") or []))
        if hit_keys or hit_pos:
            out.append({**_row(r, d), "matched_keys": hit_keys, "matched_positions": hit_pos})
    return out


async def set_links(
    session, project_id: uuid.UUID, report_id: uuid.UUID, keys: list[str], position_ids: list[uuid.UUID]
) -> dict[str, Any]:
    """Replace the report's links. Keys must be elements of the accepted revision, positions the design's own."""
    from app.modules.fieldreports.models import FieldReport

    report = await session.get(FieldReport, report_id)
    if report is None or report.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Field report not found")
    if report.status == "approved":
        raise HTTPException(status.HTTP_409_CONFLICT, "An approved report is a record and is not changed")
    rev = await published(session, project_id)
    if rev is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "There is no accepted design revision to link to")
    keys = list(dict.fromkeys(keys))
    g = await links.build(session, project_id)
    known = {k for k, _, _ in await links._elements(session, rev.bim_model_id)}
    bad = [k for k in keys if k not in known]
    if bad:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Not elements of the accepted revision: {bad[:5]}")
    pos_bad = [str(p) for p in position_ids if p not in g.positions]
    if pos_bad:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Not design positions of this project: {pos_bad[:5]}"
        )
    meta = dict(report.metadata_ or {})
    if keys or position_ids:
        meta["design"] = {
            "revision_id": str(rev.id),
            "model_id": str(rev.bim_model_id),
            "element_keys": keys,
            "position_ids": [str(p) for p in dict.fromkeys(position_ids)],
        }
    else:
        meta.pop("design", None)
    report.metadata_ = meta
    await session.flush()
    return _row(report, _design(report))


async def report_elements(session, project_id: uuid.UUID, report_id: uuid.UUID) -> dict[str, Any]:
    """Where a report points: the element ids in its model (viewer isolate), the keys (editor), the positions."""
    from app.modules.boq.models import Position
    from app.modules.fieldreports.models import FieldReport

    report = await session.get(FieldReport, report_id)
    if report is None or report.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Field report not found")
    d = _design(report)
    keys = list(d.get("element_keys") or [])
    model_id = uuid.UUID(d["model_id"]) if d.get("model_id") else None
    table = {k: i for k, i, _ in await links._elements(session, model_id)} if model_id else {}
    ids = [str(table[k]) for k in keys if k in table]
    pids = [uuid.UUID(p) for p in d.get("position_ids") or []]
    g = await links.build(session, project_id) if pids else None
    rows = (
        {p.id: p for p in (await session.execute(select(Position).where(Position.id.in_(pids)))).scalars()}
        if pids
        else {}
    )
    positions = [
        {
            "position_id": str(p),
            "boq_id": str(g.positions[p].extra["boq_id"]),
            "ordinal": rows[p].ordinal,
            "description": rows[p].description,
        }
        for p in pids
        if p in rows and p in g.positions
    ]
    return {
        "report_id": str(report_id),
        "model_id": str(model_id) if model_id else None,
        "keys": keys,
        "element_ids": ids,
        "isolate": ids if 0 < len(ids) <= links.ISOLATE_MAX else None,
        "positions": positions,
    }
