# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan editor service: view transform, conventions, code library, edits with history.

Edit model: every saved change of a record drawn on the plan is one ``oe_survey_edit`` row
(``rev`` counts per record). :func:`record_edit` refuses a change based on a stale revision
with a 409 naming who changed the record and when. What a change does to the record itself
is up to an :class:`EntityHandler`; ``sketch`` and ``point`` are built in, other packages
register theirs with :func:`register_entity_handler` (parcels, work zones, alignments).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.survey_core import plan_reference as ref
from app.modules.survey_core.models import SurveyPoint, SurveyPointSet
from app.modules.survey_core.plan_models import SurveyCodeLibrary, SurveyEdit, SurveyPlanSettings
from app.modules.survey_core.plan_schemas import (
    CodeLibraryIn,
    CodeLibraryOut,
    EditOpIn,
    EditRowOut,
    PlanPointOut,
    PlanSettingsOut,
    SaveResultOut,
    ViewTransformOut,
)
from app.modules.survey_core.plan_view import fit_view, local_view
from app.modules.survey_core.repository import SurveyRepository

logger = logging.getLogger(__name__)

PLAN_EDITS_SET = "Plan edits"
_MAX_POINTS = 50000


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _unprocessable(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


class EntityHandler(Protocol):
    """How plan edits reach one kind of record."""

    async def current(self, session: AsyncSession, project_id: uuid.UUID, entity_id: str) -> dict[str, Any] | None:
        """The record as a plan payload ``{layer, geometry, properties}``, or ``None`` when absent."""

    async def apply(
        self,
        session: AsyncSession,
        project_id: uuid.UUID,
        entity_id: str | None,
        op: str,
        after: dict[str, Any] | None,
        user_id: str | None,
    ) -> str:
        """Write the change and return the record id (new for a create)."""


_HANDLERS: dict[str, EntityHandler] = {}


def register_entity_handler(entity_type: str, handler: EntityHandler) -> None:
    """Let plan edits of ``entity_type`` reach their records (called at import by the owning module)."""
    _HANDLERS[entity_type] = handler


def entity_types() -> list[str]:
    return sorted(_HANDLERS)


async def current_rev(session: AsyncSession, project_id: uuid.UUID, entity_type: str, entity_id: str) -> int:
    row = await session.execute(
        select(func.max(SurveyEdit.rev)).where(
            SurveyEdit.project_id == project_id,
            SurveyEdit.entity_type == entity_type,
            SurveyEdit.entity_id == entity_id,
        )
    )
    return int(row.scalar_one() or 0)


async def _author_name(session: AsyncSession, user_id: str | None) -> str:
    uid = _uuid(user_id)
    if uid is None:
        return ""
    try:
        from app.modules.users.models import User  # noqa: PLC0415

        row = await session.get(User, uid)
    except Exception:  # noqa: BLE001 - a missing name must not block a save
        return ""
    return (getattr(row, "full_name", "") or getattr(row, "email", "") or "") if row else ""


async def record_edit(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    entity_type: str,
    entity_id: str,
    op: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    user_id: str | None,
    base_rev: int | None = None,
    note: str = "",
) -> SurveyEdit:
    """Append one revision of a record, refusing a change made against a stale revision.

    Args:
        base_rev: the revision the client read; ``None`` skips the check (creates, server jobs).

    Raises:
        HTTPException: 409 with ``code="stale_rev"`` when someone saved the record since ``base_rev``.
    """
    rev = await current_rev(session, project_id, entity_type, entity_id)
    if base_rev is not None and base_rev != rev:
        last = (
            await session.execute(
                select(SurveyEdit)
                .where(
                    SurveyEdit.project_id == project_id,
                    SurveyEdit.entity_type == entity_type,
                    SurveyEdit.entity_id == entity_id,
                )
                .order_by(SurveyEdit.rev.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stale_rev",
                "entity_type": entity_type,
                "entity_id": entity_id,
                "current_rev": rev,
                "author_name": last.author_name if last else "",
                "changed_at": last.created_at.isoformat() if last and last.created_at else "",
                "current": last.after if last else None,
            },
        )
    row = SurveyEdit(
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        rev=rev + 1,
        op=op,
        before=before,
        after=after,
        author=_uuid(user_id),
        author_name=await _author_name(session, user_id),
        note=note or "",
    )
    session.add(row)
    await session.flush()
    try:
        from app.core.audit import audit_log  # noqa: PLC0415

        await audit_log(
            session,
            action=f"plan_{op}",
            entity_type=f"survey_{entity_type}",
            entity_id=entity_id,
            user_id=str(_uuid(user_id)) if _uuid(user_id) else None,
            details={"project_id": str(project_id), "rev": rev + 1, "note": note or ""},
        )
    except Exception:  # noqa: BLE001 - the audit trail must not undo the change it records
        logger.exception("survey plan: audit entry for %s %s failed", entity_type, entity_id)
    return row


# ── Built-in handlers ─────────────────────────────────────────────────────


class SketchHandler:
    """Free drawing: the latest edit row is the feature."""

    async def current(self, session: AsyncSession, project_id: uuid.UUID, entity_id: str) -> dict[str, Any] | None:
        row = (
            await session.execute(
                select(SurveyEdit.after)
                .where(
                    SurveyEdit.project_id == project_id,
                    SurveyEdit.entity_type == "sketch",
                    SurveyEdit.entity_id == entity_id,
                )
                .order_by(SurveyEdit.rev.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        return row

    async def apply(
        self,
        session: AsyncSession,
        project_id: uuid.UUID,
        entity_id: str | None,
        op: str,
        after: dict[str, Any] | None,
        user_id: str | None,
    ) -> str:
        if op != "delete":
            _check_geometry(after)
        return entity_id or str(uuid.uuid4())


def _check_geometry(after: dict[str, Any] | None) -> dict[str, Any]:
    geom = (after or {}).get("geometry") or {}
    if geom.get("type") not in ("Point", "LineString", "Polygon"):
        raise _unprocessable("Plan features are points, lines or polygons")
    coords = geom.get("coordinates")
    if not isinstance(coords, list) or not coords:
        raise _unprocessable("A feature needs coordinates")
    return geom


def _point_xyz(after: dict[str, Any] | None) -> tuple[float, float, float | None]:
    geom = _check_geometry(after)
    if geom["type"] != "Point":
        raise _unprocessable("A survey point stays a point")
    c = geom["coordinates"]
    try:
        return float(c[0]), float(c[1]), (float(c[2]) if len(c) > 2 and c[2] is not None else None)
    except (TypeError, ValueError, IndexError) as exc:
        raise _unprocessable("Point coordinates must be numbers") from exc


def _dec(value: float, places: str) -> Decimal:
    return Decimal(repr(value)).quantize(Decimal(places))


class PointHandler:
    """Survey points: moves, code and label edits, new points into the "Plan edits" set."""

    async def current(self, session: AsyncSession, project_id: uuid.UUID, entity_id: str) -> dict[str, Any] | None:
        pid = _uuid(entity_id)
        p = await session.get(SurveyPoint, pid) if pid else None
        if p is None or p.project_id != project_id:
            return None
        return point_payload(p)

    async def apply(
        self,
        session: AsyncSession,
        project_id: uuid.UUID,
        entity_id: str | None,
        op: str,
        after: dict[str, Any] | None,
        user_id: str | None,
    ) -> str:
        if op == "delete":
            pid = _uuid(entity_id)
            if pid is None:
                raise _unprocessable("Unknown point")
            await session.execute(
                delete(SurveyPoint).where(SurveyPoint.id == pid, SurveyPoint.project_id == project_id)
            )
            return str(pid)
        e, n, z = _point_xyz(after)
        props = (after or {}).get("properties") or {}
        point = None
        if entity_id:
            pid = _uuid(entity_id)
            point = await session.get(SurveyPoint, pid) if pid else None
            if point is not None and point.project_id != project_id:
                point = None
        if point is None:
            set_id = await _plan_set(session, project_id, user_id)
            point = SurveyPoint(
                project_id=project_id,
                point_set_id=set_id,
                point_id=str(props.get("label") or props.get("point_id") or "P")[:64],
                e=_dec(e, "0.0001"),
                n=_dec(n, "0.0001"),
                kind=str(props.get("kind") or "topo")[:20],
            )
            session.add(point)
        point.e, point.n = _dec(e, "0.0001"), _dec(n, "0.0001")
        if z is not None:
            point.z = _dec(z, "0.0001")
        if "code" in props:
            point.code = str(props.get("code") or "")[:64]
        if props.get("label"):
            point.point_id = str(props["label"])[:64]
        if "description" in props:
            point.description = str(props.get("description") or "")[:255]
        await session.flush()
        return str(point.id)


async def _plan_set(session: AsyncSession, project_id: uuid.UUID, user_id: str | None) -> uuid.UUID:
    row = (
        await session.execute(
            select(SurveyPointSet).where(SurveyPointSet.project_id == project_id, SurveyPointSet.name == PLAN_EDITS_SET)
        )
    ).scalar_one_or_none()
    if row is not None:
        return row.id
    crs = await SurveyRepository(session).get_crs(project_id)
    row = SurveyPointSet(
        project_id=project_id,
        name=PLAN_EDITS_SET,
        file_format="plan",
        stored_epsg=crs.horizontal_epsg if crs and not crs.is_local_grid else None,
        created_by=_uuid(user_id),
    )
    session.add(row)
    await session.flush()
    return row.id


def point_payload(p: SurveyPoint) -> dict[str, Any]:
    coords: list[float] = [float(p.e), float(p.n)]
    if p.z is not None:
        coords.append(float(p.z))
    return {
        "layer": "control" if p.kind == "control" else "points",
        "geometry": {"type": "Point", "coordinates": coords},
        "properties": {"label": p.point_id, "code": p.code, "kind": p.kind, "description": p.description},
    }


register_entity_handler("sketch", SketchHandler())
register_entity_handler("point", PointHandler())


# ── Service ───────────────────────────────────────────────────────────────


@dataclass
class _Project:
    country: str | None


class PlanService:
    """Reads and writes behind ``/projects/{id}/view-transform|codes|plan-settings|edits``."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SurveyRepository(session)

    async def _project(self, project_id: uuid.UUID) -> _Project:
        from app.modules.projects.models import Project  # noqa: PLC0415

        row = await self.session.get(Project, project_id)
        return _Project(country=(row.country_code or None) if row else None)

    # View transform

    async def view_transform(self, project_id: uuid.UUID) -> ViewTransformOut:
        crs = await self.repo.get_crs(project_id)
        pts = await self.repo.point_positions(project_id)
        extent = None
        if pts:
            es = [p[1] for p in pts]
            ns = [p[2] for p in pts]
            extent = [min(es), min(ns), max(es), max(ns)]
        name = (crs.horizontal_name if crs else "") or ""
        if crs is None or crs.is_local_grid or not crs.horizontal_epsg:
            e0 = (extent[0] + extent[2]) / 2 if extent else 0.0
            n0 = (extent[1] + extent[3]) / 2 if extent else 0.0
            return ViewTransformOut(**local_view(e0, n0, extent, name))
        epsg = int(crs.horizontal_epsg)
        if extent is None:
            anchor = await self.repo.anchor_latlon(project_id)
            if anchor is None:
                return ViewTransformOut(**local_view(0.0, 0.0, None, name))
            try:
                from pyproj import Transformer  # noqa: PLC0415

                e, n = Transformer.from_crs(4326, epsg, always_xy=True).transform(anchor[1], anchor[0])
            except Exception:  # noqa: BLE001 - an anchor outside the zone falls back to a local view
                return ViewTransformOut(**local_view(0.0, 0.0, None, name))
            extent = [float(e) - 500.0, float(n) - 500.0, float(e) + 500.0, float(n) + 500.0]
        try:
            return ViewTransformOut(**fit_view(epsg, *extent))
        except Exception as exc:  # noqa: BLE001 - pyproj raises several types for unusable systems
            logger.warning("survey plan: view transform for EPSG %s failed: %s", epsg, exc)
            return ViewTransformOut(
                **local_view((extent[0] + extent[2]) / 2, (extent[1] + extent[3]) / 2, extent, name)
            )

    # Code library

    async def codes(self, project_id: uuid.UUID, markets: list[str]) -> CodeLibraryOut:
        row = await self._code_row(project_id)
        if row is not None:
            return CodeLibraryOut(items=list(row.codes or []), source="project")
        country = (await self._project(project_id)).country
        return default_library(country, markets)

    async def put_codes(
        self, project_id: uuid.UUID, body: CodeLibraryIn, user_id: str, markets: list[str]
    ) -> CodeLibraryOut:
        row = await self._code_row(project_id)
        if body.items is None:
            if row is not None:
                await self.session.delete(row)
                await self.session.flush()
            return await self.codes(project_id, markets)
        items = [i.model_dump() for i in body.items]
        dups = ref.duplicate_codes(items)
        if dups:
            raise _unprocessable(f"Duplicate codes: {', '.join(dups)}")
        if row is None:
            row = SurveyCodeLibrary(project_id=project_id, codes=items, updated_by=_uuid(user_id))
            self.session.add(row)
        else:
            row.codes = items
            row.updated_by = _uuid(user_id)
        await self.session.flush()
        return CodeLibraryOut(items=items, source="project")

    async def _code_row(self, project_id: uuid.UUID) -> SurveyCodeLibrary | None:
        return (
            await self.session.execute(select(SurveyCodeLibrary).where(SurveyCodeLibrary.project_id == project_id))
        ).scalar_one_or_none()

    # Conventions

    async def settings(self, project_id: uuid.UUID) -> PlanSettingsOut:
        country = (await self._project(project_id)).country
        defaults, source = ref.country_conventions(country)
        row = (
            await self.session.execute(select(SurveyPlanSettings).where(SurveyPlanSettings.project_id == project_id))
        ).scalar_one_or_none()
        own = ref.clean_conventions(row.conventions) if row else {}
        return PlanSettingsOut(
            conventions={**defaults, **own},
            defaults=defaults,
            source="project" if own else source,
            country=country,
            csf=await self._csf(project_id),
        )

    async def put_settings(
        self, project_id: uuid.UUID, conventions: dict[str, Any] | None, user_id: str
    ) -> PlanSettingsOut:
        row = (
            await self.session.execute(select(SurveyPlanSettings).where(SurveyPlanSettings.project_id == project_id))
        ).scalar_one_or_none()
        clean = ref.clean_conventions(conventions)
        if not clean:
            if row is not None:
                await self.session.delete(row)
        elif row is None:
            self.session.add(SurveyPlanSettings(project_id=project_id, conventions=clean, updated_by=_uuid(user_id)))
        else:
            row.conventions = clean
            row.updated_by = _uuid(user_id)
        await self.session.flush()
        return await self.settings(project_id)

    async def _csf(self, project_id: uuid.UUID) -> float | None:
        crs = await self.repo.get_crs(project_id)
        if crs is None or crs.is_local_grid or not crs.horizontal_epsg:
            return None
        pts = await self.repo.point_positions(project_id)
        if not pts:
            return None
        e = sum(p[1] for p in pts) / len(pts)
        n = sum(p[2] for p in pts) / len(pts)
        zs = [p[3] for p in pts if p[3] is not None]
        try:
            from app.modules.survey_core.geodesy import combined_scale_factor  # noqa: PLC0415

            return round(combined_scale_factor(int(crs.horizontal_epsg), e, n, sum(zs) / len(zs) if zs else 0.0).csf, 9)
        except Exception:  # noqa: BLE001 - no CSF is shown rather than a wrong one
            return None

    # Points and sketch

    async def plan_points(self, project_id: uuid.UUID) -> list[PlanPointOut]:
        revs = await self._revs(project_id, "point")
        rows = await self.session.execute(
            select(SurveyPoint)
            .where(SurveyPoint.project_id == project_id)
            .order_by(SurveyPoint.source_line, SurveyPoint.point_id)
            .limit(_MAX_POINTS)
        )
        return [
            PlanPointOut(
                id=str(p.id),
                point_id=p.point_id,
                e=float(p.e),
                n=float(p.n),
                z=float(p.z) if p.z is not None else None,
                code=p.code or "",
                kind=p.kind,
                source_line=p.source_line,
                rev=revs.get(str(p.id), 0),
            )
            for p in rows.scalars().all()
        ]

    async def _revs(self, project_id: uuid.UUID, entity_type: str) -> dict[str, int]:
        rows = await self.session.execute(
            select(SurveyEdit.entity_id, func.max(SurveyEdit.rev))
            .where(SurveyEdit.project_id == project_id, SurveyEdit.entity_type == entity_type)
            .group_by(SurveyEdit.entity_id)
        )
        return {eid: int(rev) for eid, rev in rows.all()}

    async def sketch(self, project_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = (
            await self.session.execute(
                select(SurveyEdit)
                .where(SurveyEdit.project_id == project_id, SurveyEdit.entity_type == "sketch")
                .order_by(SurveyEdit.entity_id, SurveyEdit.rev)
            )
        ).scalars()
        latest: dict[str, SurveyEdit] = {}
        for r in rows:
            latest[r.entity_id] = r
        out = []
        for eid, r in latest.items():
            if not r.after:
                continue
            out.append(
                {
                    "id": eid,
                    "layer": r.after.get("layer") or "sketch",
                    "geometry": r.after.get("geometry"),
                    "properties": r.after.get("properties") or {},
                    "rev": r.rev,
                    "entityType": "sketch",
                    "entityId": eid,
                }
            )
        return out

    # Edits

    async def save(self, project_id: uuid.UUID, ops: list[EditOpIn], user_id: str) -> list[SaveResultOut]:
        """Apply a batch atomically; one stale revision refuses the whole batch."""
        out: list[SaveResultOut] = []
        for op in ops:
            handler = _HANDLERS.get(op.entity_type)
            if handler is None:
                raise _unprocessable(f"Plan edits of {op.entity_type} are not supported")
            if op.op in ("update", "delete", "revert") and not op.entity_id:
                raise _unprocessable("An update or delete names its record")
            if op.op != "delete" and op.after is None:
                raise _unprocessable("A create or update carries the new state")
            before = await handler.current(self.session, project_id, op.entity_id) if op.entity_id else None
            if op.op in ("update", "delete") and before is None and op.entity_type != "sketch":
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
            if op.entity_id:
                # Check the revision before touching the record, so a refusal leaves it as it was.
                rev = await current_rev(self.session, project_id, op.entity_type, op.entity_id)
                if op.base_rev is not None and op.base_rev != rev:
                    await record_edit(
                        self.session,
                        project_id,
                        entity_type=op.entity_type,
                        entity_id=op.entity_id,
                        op=op.op,
                        before=before,
                        after=op.after,
                        user_id=user_id,
                        base_rev=op.base_rev,
                    )
            entity_id = await handler.apply(self.session, project_id, op.entity_id, op.op, op.after, user_id)
            after = (
                None if op.op == "delete" else await handler.current(self.session, project_id, entity_id) or op.after
            )
            row = await record_edit(
                self.session,
                project_id,
                entity_type=op.entity_type,
                entity_id=entity_id,
                op=op.op,
                before=before,
                after=op.after if op.entity_type == "sketch" else after,
                user_id=user_id,
                base_rev=op.base_rev if op.entity_id else None,
                note=op.note,
            )
            out.append(
                SaveResultOut(
                    client_id=op.client_id,
                    entity_type=op.entity_type,
                    entity_id=entity_id,
                    rev=row.rev,
                    edit_id=str(row.id),
                )
            )
        return out

    async def edits(
        self, project_id: uuid.UUID, entity_type: str = "", entity_id: str = "", limit: int = 200
    ) -> list[EditRowOut]:
        q = select(SurveyEdit).where(SurveyEdit.project_id == project_id)
        if entity_type:
            q = q.where(SurveyEdit.entity_type == entity_type)
        if entity_id:
            q = q.where(SurveyEdit.entity_id == entity_id)
        rows = await self.session.execute(q.order_by(SurveyEdit.created_at.desc(), SurveyEdit.rev.desc()).limit(limit))
        return [edit_out(r) for r in rows.scalars().all()]

    async def get_edit(self, edit_id: uuid.UUID) -> SurveyEdit | None:
        return await self.session.get(SurveyEdit, edit_id)

    async def restore(self, edit: SurveyEdit, user_id: str, note: str = "") -> SaveResultOut:
        """Make the state saved by ``edit`` current again, as a new revision."""
        handler = _HANDLERS.get(edit.entity_type)
        if handler is None:
            raise _unprocessable(f"Plan edits of {edit.entity_type} are not supported")
        project_id = edit.project_id
        before = await handler.current(self.session, project_id, edit.entity_id)
        target = edit.after
        if target is None:
            if before is not None:
                await handler.apply(self.session, project_id, edit.entity_id, "delete", None, user_id)
            entity_id = edit.entity_id
        else:
            entity_id = await handler.apply(self.session, project_id, edit.entity_id, "update", target, user_id)
        row = await record_edit(
            self.session,
            project_id,
            entity_type=edit.entity_type,
            entity_id=entity_id,
            op="revert",
            before=before,
            after=target,
            user_id=user_id,
            note=note or f"rev {edit.rev}",
        )
        return SaveResultOut(
            client_id="", entity_type=edit.entity_type, entity_id=entity_id, rev=row.rev, edit_id=str(row.id)
        )


def edit_out(r: SurveyEdit) -> EditRowOut:
    return EditRowOut(
        id=str(r.id),
        entity_type=r.entity_type,
        entity_id=r.entity_id,
        rev=r.rev,
        op=r.op,
        before=r.before,
        after=r.after,
        author=str(r.author) if r.author else None,
        author_name=r.author_name or "",
        created_at=r.created_at,
        note=r.note or "",
        summary=_summary(r.before, r.after),
    )


def _summary(before: dict[str, Any] | None, after: dict[str, Any] | None) -> str:
    """Language-neutral numbers for the history list: a point's shift in metres."""
    try:
        b = (before or {}).get("geometry") or {}
        a = (after or {}).get("geometry") or {}
        if b.get("type") == a.get("type") == "Point":
            de = float(a["coordinates"][0]) - float(b["coordinates"][0])
            dn = float(a["coordinates"][1]) - float(b["coordinates"][1])
            if de or dn:
                return f"{de:+.3f} / {dn:+.3f}"
    except (KeyError, IndexError, TypeError, ValueError):
        return ""
    return ""


def default_library(country: str | None, markets: list[str]) -> CodeLibraryOut:
    """The country's library when its market is active for the caller, else the neutral one."""
    from app.core.active_markets import pack_active  # noqa: PLC0415

    if country:
        own = ref.country_codes(country)
        if own and pack_active(markets, [country]):
            return CodeLibraryOut(items=own, source="pack", countries=[country.upper()])
    return CodeLibraryOut(items=ref.neutral_codes(), source="neutral")


async def plan_context(session: AsyncSession, project_id: uuid.UUID) -> dict[str, Any]:
    """Validation context of the plan rules (SRV-140..144): codes, coded points, sketch rings."""
    row = (
        await session.execute(select(SurveyCodeLibrary).where(SurveyCodeLibrary.project_id == project_id))
    ).scalar_one_or_none()
    library = list(row.codes or []) if row else ref.neutral_codes()
    codes = [
        c
        for (c,) in (
            await session.execute(
                select(SurveyPoint.code).where(SurveyPoint.project_id == project_id).order_by(SurveyPoint.source_line)
            )
        ).all()
    ]
    sketch = await PlanService(session).sketch(project_id)
    return {
        "plan": {
            "library": library,
            "library_source": "project" if row else "neutral",
            "codes": [c or "" for c in codes],
            "sketch": [{"id": f["id"], "geometry": f["geometry"]} for f in sketch],
        }
    }


__all__ = [
    "PLAN_EDITS_SET",
    "EntityHandler",
    "PlanService",
    "current_rev",
    "default_library",
    "edit_out",
    "entity_types",
    "plan_context",
    "point_payload",
    "record_edit",
    "register_entity_handler",
]
