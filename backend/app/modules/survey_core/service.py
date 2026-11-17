# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Survey register business logic.

Nothing is converted silently: a file in another system than the project's is
transformed only on an import whose preview said so, with both EPSG codes on
screen, and the set keeps the code it was measured in. A detected CRS is a
suggestion with a confidence until someone allowed to confirm confirms it.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.survey_core import crs as crs_lib
from app.modules.survey_core.models import (
    SurveyPoint,
    SurveyPointSet,
    SurveyProfile,
    SurveyProjectCrs,
    SurveyTraverse,
)
from app.modules.survey_core.point_io import (
    PRESETS,
    ParsedPoint,
    ParseResult,
    Problem,
    detect_delimiter,
    guess_preset,
    parse_geojson,
    parse_points,
    resolve_duplicates,
    split_line,
)
from app.modules.survey_core.repository import SurveyRepository
from app.modules.survey_core.schemas import (
    CrsInfoOut,
    CrsSuggestion,
    Finding,
    GuessOut,
    ImportPreview,
    ImportProblem,
    ImportRequest,
    ImportResult,
    PointListResponse,
    PointOut,
    PointSetOut,
    PreviewRow,
    ProjectCrsOut,
    ProjectCrsSet,
    ProjectCrsState,
    RegisterSummary,
    SurveyProfileIn,
    SurveyProfileOut,
    TransformRequest,
    TransformResponse,
    TraverseCreate,
    TraverseLegOut,
    TraverseOut,
    ValidationReportOut,
)
from app.modules.survey_core.survey_math import same_position
from app.modules.survey_core.traverse import close_traverse, level_verdict, parse_legs, traverse_verdict
from app.modules.survey_core.validators import SURVEY_RULE_SET

logger = logging.getLogger(__name__)

PREVIEW_ROWS = 20


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _info(epsg: int) -> CrsInfoOut:
    i = crs_lib.describe(epsg)
    return CrsInfoOut(epsg=i.epsg, name=i.name, kind=i.kind, unit=i.unit, is_geographic=i.is_geographic, area=i.area)


def _suggestion(epsg: int, reason: str, confidence: float | None = None, country: str = "") -> CrsSuggestion | None:
    try:
        base = _info(epsg)
    except ValueError:
        return None
    return CrsSuggestion(**base.model_dump(), reason=reason, confidence=confidence, pack_country=country)


def _d(value: float | None, places: str = "0.0001") -> Decimal | None:
    return None if value is None else Decimal(str(value)).quantize(Decimal(places))


def _f(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)


def _crs_out(row: SurveyProjectCrs) -> ProjectCrsOut:
    return ProjectCrsOut(
        project_id=row.project_id,
        horizontal_epsg=row.horizontal_epsg,
        horizontal_name=row.horizontal_name,
        vertical_mode=row.vertical_mode,
        vertical_epsg=row.vertical_epsg,
        is_local_grid=row.is_local_grid,
        local_origin_e=_f(row.local_origin_e),
        local_origin_n=_f(row.local_origin_n),
        local_rotation_deg=_f(row.local_rotation_deg),
        local_scale_factor=_f(row.local_scale_factor),
        source=row.source,
        detected_confidence=row.detected_confidence,
        confirmed_by=row.confirmed_by,
        confirmed_at=row.confirmed_at,
    )


def _point_out(p: SurveyPoint) -> PointOut:
    return PointOut(
        id=p.id,
        point_set_id=p.point_set_id,
        point_id=p.point_id,
        e=float(p.e),
        n=float(p.n),
        z=_f(p.z),
        code=p.code,
        kind=p.kind,
        sigma=_f(p.sigma),
        description=p.description,
    )


class SurveyService:
    """Stateless operations over one request's session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SurveyRepository(session)

    # ── CRS ────────────────────────────────────────────────────────────────

    async def crs_state(self, project_id: uuid.UUID, markets: list[str]) -> ProjectCrsState:
        row = await self.repo.get_crs(project_id)
        total, _ = await self.repo.counts(project_id)
        suggestions: list[CrsSuggestion] = []
        pin = await self.repo.anchor_latlon(project_id)
        if pin is not None:
            utm = crs_lib.utm_epsg_for(*pin)
            if utm:
                s = _suggestion(utm, "project_location", 0.9)
                if s:
                    suggestions.append(s)
        for epsg, _note, country in crs_lib.pack_crs_for(markets):
            s = _suggestion(epsg, "pack", None, country)
            if s:
                suggestions.append(s)
        geo = _suggestion(4326, "geographic")
        if geo:
            suggestions.append(geo)
        seen: set[int] = set()
        unique = [s for s in suggestions if not (s.epsg in seen or seen.add(s.epsg))]
        return ProjectCrsState(crs=_crs_out(row) if row else None, suggestions=unique, point_count=total)

    async def set_crs(
        self, project_id: uuid.UUID, data: ProjectCrsSet, user_id: str, may_confirm: bool
    ) -> ProjectCrsOut:
        if not data.is_local_grid and data.horizontal_epsg is None:
            raise _bad_request("Choose an EPSG code or a local grid")
        if data.is_local_grid and (data.local_origin_e is None or data.local_origin_n is None):
            raise _bad_request("A local grid needs its origin E and N")
        name = ""
        if data.horizontal_epsg is not None:
            try:
                info = crs_lib.describe(data.horizontal_epsg)
            except ValueError as exc:
                raise _bad_request(str(exc)) from exc
            if info.kind == "vertical":
                raise _bad_request("A vertical system cannot be the horizontal CRS")
            name = info.name
        if data.vertical_mode == "epsg":
            if data.vertical_epsg is None:
                raise _bad_request("Choose the vertical EPSG code")
            try:
                crs_lib.describe(data.vertical_epsg)
            except ValueError as exc:
                raise _bad_request(str(exc)) from exc

        row = await self.repo.get_crs(project_id)
        total, _ = await self.repo.counts(project_id)
        changes_points = (
            row is not None
            and total > 0
            and (row.horizontal_epsg != data.horizontal_epsg or row.is_local_grid != data.is_local_grid)
        )
        if changes_points:
            if not may_confirm:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: survey.confirm")
            expected = str(data.horizontal_epsg) if data.horizontal_epsg is not None else "LOCAL"
            if data.confirm_text.strip().upper() != expected:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Points exist: type {expected} to change the project CRS",
                )
        old = _crs_out(row).model_dump(mode="json") if row else None
        if row is None:
            row = SurveyProjectCrs(project_id=project_id)
            self.session.add(row)
        actor = _uuid(user_id)
        row.horizontal_epsg = None if data.is_local_grid else data.horizontal_epsg
        row.horizontal_name = "" if data.is_local_grid else name
        row.vertical_mode = data.vertical_mode
        row.vertical_epsg = data.vertical_epsg if data.vertical_mode == "epsg" else None
        row.is_local_grid = data.is_local_grid
        row.local_origin_e = _d(data.local_origin_e) if data.is_local_grid else None
        row.local_origin_n = _d(data.local_origin_n) if data.is_local_grid else None
        row.local_rotation_deg = _d(data.local_rotation_deg, "0.00000001") if data.is_local_grid else None
        row.local_scale_factor = _d(data.local_scale_factor, "0.0000000001") if data.is_local_grid else None
        row.source = data.source
        row.detected_confidence = data.detected_confidence if data.source == "detected" else None
        # Picking a system by hand is a confirmation; accepting a detected one is, only for someone allowed to confirm.
        confirmed = data.source == "user" or may_confirm
        row.confirmed_by = actor if confirmed else None
        row.confirmed_at = datetime.now(UTC) if confirmed else None
        await self.session.flush()
        new = _crs_out(row)
        await self._audit(
            "update" if old else "create", project_id, user_id, {"old": old, "new": new.model_dump(mode="json")}
        )
        return new

    async def confirm_crs(self, project_id: uuid.UUID, user_id: str) -> ProjectCrsOut:
        row = await self.repo.get_crs(project_id)
        if row is None:
            raise not_found()
        row.confirmed_by = _uuid(user_id)
        row.confirmed_at = datetime.now(UTC)
        await self.session.flush()
        out = _crs_out(row)
        await self._audit("approve", project_id, user_id, {"new": out.model_dump(mode="json")})
        return out

    async def _audit(
        self,
        action: str,
        project_id: uuid.UUID,
        user_id: str,
        details: dict[str, Any],
        entity_type: str = "survey_project_crs",
    ) -> None:
        try:
            from app.core.audit import audit_log  # noqa: PLC0415

            await audit_log(
                self.session,
                action=action,
                entity_type=entity_type,
                entity_id=str(project_id),
                user_id=str(_uuid(user_id)) if _uuid(user_id) else None,
                details=details,
            )
        except Exception:  # noqa: BLE001 - the audit trail must not undo the change it records
            logger.exception("survey: audit entry for project %s failed", project_id)

    # ── Import ─────────────────────────────────────────────────────────────

    def _parse(self, req: ImportRequest) -> tuple[ParseResult, int | None, GuessOut | None, GuessOut | None, list[str]]:
        """Parsed file, the EPSG the file declares (GeoJSON only), the two guesses, and the header cells."""
        if req.file_format == "geojson":
            try:
                parsed, declared = parse_geojson(req.text, req.default_kind)
            except ValueError as exc:
                raise _bad_request(str(exc)) from exc
            return parsed, declared, None, None, []
        delim_guess = None
        delimiter = req.delimiter
        if not delimiter:
            try:
                d, c = detect_delimiter(req.text)
            except ValueError as exc:
                raise _bad_request(str(exc)) from exc
            delimiter, delim_guess = d, GuessOut(value=d, confidence=c)
        rows = [split_line(ln, delimiter) for ln in req.text.lstrip("﻿").splitlines()[:50] if ln.strip()]
        preset_guess = None
        columns: list[str] = [str(c) for c in req.columns]
        if not columns:
            name = req.column_preset if req.column_preset in PRESETS else ""
            if not name:
                name, conf = guess_preset(rows)
                preset_guess = GuessOut(value=name, confidence=conf)
            columns = PRESETS[name]
        try:
            parsed = parse_points(
                req.text,
                columns=columns,
                delimiter=delimiter,
                has_header=req.has_header,
                default_kind=req.default_kind,
            )
        except ValueError as exc:
            raise _bad_request(str(exc)) from exc
        header = rows[0] if rows and req.has_header else []
        return parsed, None, delim_guess, preset_guess, header

    async def _epsgs(
        self, project_id: uuid.UUID, req: ImportRequest, declared: int | None
    ) -> tuple[int | None, int | None]:
        row = await self.repo.get_crs(project_id)
        target = row.horizontal_epsg if row and not row.is_local_grid else None
        source = req.source_epsg or declared or target
        return source, target

    @staticmethod
    def _transform(points: list[ParsedPoint], source: int, target: int) -> None:
        try:
            moved = crs_lib.transform_points([(p.e, p.n, p.z) for p in points], source, target)
        except ValueError as exc:
            raise _bad_request(str(exc)) from exc
        for p, (e, n, _z) in zip(points, moved, strict=True):
            p.e, p.n = round(e, 4), round(n, 4)

    async def _existing_conflicts(self, project_id: uuid.UUID, points: list[ParsedPoint]) -> list[Problem]:
        existing = {pid: (e, n, z) for pid, e, n, z, _ in await self.repo.point_positions(project_id)}
        out: list[Problem] = []
        for p in points:
            seen = existing.get(p.point_id)
            if seen is not None and not same_position(seen, (p.e, p.n, p.z)):
                out.append(Problem("SRV-003", p.line, p.point_id, "existing"))
        return out

    async def preview(self, project_id: uuid.UUID, req: ImportRequest) -> ImportPreview:
        parsed, declared, delim_guess, preset_guess, header = self._parse(req)
        source, target = await self._epsgs(project_id, req, declared)
        will_transform = bool(source and target and source != target)
        kept = resolve_duplicates(parsed.points, req.duplicate_policy)
        if will_transform and kept:
            self._transform(kept, source, target)  # type: ignore[arg-type]
        conflicts = await self._existing_conflicts(project_id, kept)
        detected = None
        if target is None and source is None and parsed.points:
            detected = self._detect(parsed.points)
        problems = [*parsed.problems, *conflicts]
        sample_rows = (
            [
                split_line(ln, delim_guess.value if delim_guess else (req.delimiter or ","))
                for ln in req.text.lstrip("﻿").splitlines()[:5]
                if ln.strip()
            ]
            if req.file_format != "geojson"
            else []
        )
        return ImportPreview(
            rows_read=parsed.rows_read,
            problem_count=len(problems),
            problems=[ImportProblem(**vars(p)) for p in problems],
            rows=[
                PreviewRow(line=p.line, point_id=p.point_id, e=p.e, n=p.n, z=p.z, code=p.code, kind=p.kind)
                for p in kept[:PREVIEW_ROWS]
            ],
            delimiter=delim_guess,
            preset=preset_guess,
            header=header,
            sample=sample_rows,
            points_to_import=len(kept),
            source_epsg=source,
            target_epsg=target,
            will_transform=will_transform,
            detected_crs=detected,
            existing_conflicts=len(conflicts),
        )

    @staticmethod
    def _detect(points: list[ParsedPoint]) -> CrsSuggestion | None:
        try:
            from app.modules.cad.crs_detector import detect_from_bbox  # noqa: PLC0415
        except ImportError:  # pragma: no cover - cad is a core module
            return None
        es, ns = [p.e for p in points], [p.n for p in points]
        guess = detect_from_bbox((min(es), min(ns), max(es), max(ns)), "m")
        if guess.epsg is None:
            return None
        return _suggestion(guess.epsg, "detected", round(guess.confidence, 2))

    async def import_points(self, project_id: uuid.UUID, req: ImportRequest, user_id: str) -> ImportResult:
        parsed, declared, _dg, preset_guess, _h = self._parse(req)
        kept = resolve_duplicates(parsed.points, req.duplicate_policy)
        if not kept:
            raise _bad_request("The file has no readable points")
        source, target = await self._epsgs(project_id, req, declared)
        transformed = bool(source and target and source != target)
        if transformed:
            self._transform(kept, source, target)  # type: ignore[arg-type]
        conflicts = await self._existing_conflicts(project_id, kept)
        preset = req.column_preset or (preset_guess.value if preset_guess else "")
        point_set = SurveyPointSet(
            project_id=project_id,
            name=(req.name or req.filename or "Point set").strip()[:255],
            source_filename=req.filename[:255],
            file_format=req.file_format,
            column_preset="" if req.file_format == "geojson" else preset,
            instrument=req.instrument,
            surveyed_by=req.surveyed_by,
            survey_date=req.survey_date,
            source_epsg=source,
            stored_epsg=target if transformed else source,
            transformed=transformed,
            duplicate_policy=req.duplicate_policy,
            rows_read=parsed.rows_read,
            point_count=len(kept),
            note=req.note,
            created_by=_uuid(user_id),
        )
        await self.repo.add(point_set)
        await self.repo.add_points(
            [
                SurveyPoint(
                    project_id=project_id,
                    point_set_id=point_set.id,
                    point_id=p.point_id,
                    e=_d(p.e),
                    n=_d(p.n),
                    z=_d(p.z),
                    code=p.code,
                    kind=p.kind,
                    sigma=_d(p.sigma),
                    description=p.description,
                    source_line=p.line,
                )
                for p in kept
            ]
        )
        problems = [*parsed.problems, *conflicts]
        return ImportResult(
            point_set=PointSetOut.model_validate(point_set),
            imported=len(kept),
            problems=[ImportProblem(**vars(p)) for p in problems],
        )

    # ── Register reads and edits ───────────────────────────────────────────

    async def list_points(self, project_id: uuid.UUID, **filters: Any) -> PointListResponse:
        items, total = await self.repo.list_points(project_id, **filters)
        return PointListResponse(items=[_point_out(p) for p in items], total=total)

    async def list_sets(self, project_id: uuid.UUID) -> list[PointSetOut]:
        return [PointSetOut.model_validate(s) for s in await self.repo.list_sets(project_id)]

    async def get_set(self, set_id: uuid.UUID) -> SurveyPointSet:
        s = await self.repo.get_set(set_id)
        if s is None:
            raise not_found()
        return s

    async def delete_set(self, point_set: SurveyPointSet) -> None:
        await self.repo.delete_set(point_set)

    async def declare_set_crs(self, point_set: SurveyPointSet, epsg: int) -> PointSetOut:
        """Say which system a set without one was measured in. Coordinates are not moved."""
        try:
            crs_lib.describe(epsg)
        except ValueError as exc:
            raise _bad_request(str(exc)) from exc
        point_set.source_epsg = epsg
        point_set.stored_epsg = epsg
        await self.session.flush()
        return PointSetOut.model_validate(point_set)

    # ── Validation and summary ─────────────────────────────────────────────

    async def _context(self, project_id: uuid.UUID) -> dict[str, Any]:
        row = await self.repo.get_crs(project_id)
        sets = await self.repo.list_sets(project_id)
        crs = (
            {
                "horizontal_epsg": row.horizontal_epsg,
                "is_local_grid": row.is_local_grid,
                "source": row.source,
                "detected_confidence": row.detected_confidence,
                "confirmed": row.confirmed_at is not None,
            }
            if row
            else {}
        )
        return {
            "crs": crs,
            "point_sets": [{"id": str(s.id), "name": s.name, "stored_epsg": s.stored_epsg} for s in sets],
            "points": [
                {"point_id": pid, "e": e, "n": n, "z": z, "set_id": sid}
                for pid, e, n, z, sid in await self.repo.point_positions(project_id)
            ],
            "traverses": [
                {
                    "id": str(t.id),
                    "name": t.name,
                    "kind": t.kind,
                    "ratio": t.ratio,
                    "profile_ratio": t.profile_ratio,
                    "misclosure_mm": _f(t.misclosure_mm),
                    "allowed_mm": _f(t.allowed_mm),
                    "k_mm": _f(t.k_mm),
                }
                for t in await self.repo.list_traverses(project_id)
            ],
        }

    async def validate(self, project_id: uuid.UUID, locale: str = "en") -> ValidationReportOut:
        from app.core.validation.engine import validation_engine  # noqa: PLC0415

        report = await validation_engine.validate(
            data=await self._context(project_id),
            rule_sets=[SURVEY_RULE_SET],
            target_type="survey_register",
            target_id=str(project_id),
            project_id=str(project_id),
            metadata={"locale": locale},
        )
        failed = [r for r in report.results if not r.passed]
        return ValidationReportOut(
            status=str(getattr(report.status, "value", report.status)),
            error_count=len(report.errors),
            warning_count=len(report.warnings),
            info_count=len(report.infos),
            findings=[
                Finding(
                    rule_id=r.rule_id,
                    severity=str(getattr(r.severity, "value", r.severity)),
                    message=r.message,
                    suggestion=r.suggestion,
                    element_ref=r.element_ref,
                )
                for r in failed
            ],
        )

    async def summary(self, project_id: uuid.UUID) -> RegisterSummary:
        total, control = await self.repo.counts(project_id)
        sets = await self.repo.list_sets(project_id)
        report = await self.validate(project_id)
        return RegisterSummary(
            points=total,
            control=control,
            point_sets=len(sets),
            findings=len(report.findings),
            last_import=await self.repo.last_import(project_id),
        )

    # ── Plan ───────────────────────────────────────────────────────────────

    async def plan(self, project_id: uuid.UUID, limit: int = 5000) -> dict[str, Any]:
        """Survey points as GeoJSON in WGS 84 for the map; a local grid stays in its own metres."""
        from sqlalchemy import select  # noqa: PLC0415

        from app.modules.survey_core import crs as crs_lib  # noqa: PLC0415

        row = await self.repo.get_crs(project_id)
        epsg = row.horizontal_epsg if row and not row.is_local_grid else None
        rows = (
            await self.session.execute(
                select(SurveyPoint.point_id, SurveyPoint.e, SurveyPoint.n, SurveyPoint.z, SurveyPoint.kind)
                .where(SurveyPoint.project_id == project_id)
                .order_by(SurveyPoint.point_id)
                .limit(limit)
            )
        ).all()
        to_ll = crs_lib.wgs84_projector(epsg)
        ll = to_ll([float(r[1]) for r in rows], [float(r[2]) for r in rows]) if rows else []
        features = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
                "properties": {
                    "layer": "points",
                    "id": r[0],
                    "kind": r[4],
                    "e": float(r[1]),
                    "n": float(r[2]),
                    "z": float(r[3]) if r[3] is not None else None,
                },
            }
            for r, (lon, lat) in zip(rows, ll, strict=True)
        ]
        return {
            "type": "FeatureCollection",
            "features": features,
            "properties": {"epsg": epsg, "local_grid": epsg is None},
        }

    # ── Profiles ───────────────────────────────────────────────────────────

    async def profile(self, project_id: uuid.UUID | None) -> SurveyProfileOut:
        """The thresholds in force: the project's own row, else the workspace default, else none."""
        row = await self.repo.get_profile(project_id) if project_id is not None else None
        scope = "project"
        if row is None:
            row = await self.repo.get_profile(None)
            scope = "workspace"
        if row is None:
            return SurveyProfileOut(scope="none")
        return SurveyProfileOut(
            scope=scope,  # type: ignore[arg-type]
            source=row.source,
            label=row.label,
            traverse_min_ratio=row.traverse_min_ratio,
            level_k_mm=_f(row.level_k_mm),
            coverage_min_pct=_f(row.coverage_min_pct),
        )

    async def set_profile(
        self, project_id: uuid.UUID | None, data: SurveyProfileIn, user_id: str, source: str = "user"
    ) -> SurveyProfileOut:
        """Write the project's profile, or the workspace default when ``project_id`` is None (audited)."""
        row = await self.repo.get_profile(project_id)
        old = None
        if row is None:
            row = SurveyProfile(project_id=project_id)
            self.session.add(row)
        else:
            old = {
                "label": row.label,
                "traverse_min_ratio": row.traverse_min_ratio,
                "level_k_mm": _f(row.level_k_mm),
                "coverage_min_pct": _f(row.coverage_min_pct),
            }
        row.label = data.label
        row.source = source
        row.traverse_min_ratio = data.traverse_min_ratio
        row.level_k_mm = _d(data.level_k_mm, "0.01")
        row.coverage_min_pct = _d(data.coverage_min_pct, "0.01")
        await self.session.flush()
        await self._audit(
            "update" if old else "create",
            project_id or uuid.UUID(int=0),
            user_id,
            {"old": old, "new": data.model_dump(mode="json")},
            entity_type="survey_profile",
        )
        return await self.profile(project_id)

    # ── Traverses and level runs ───────────────────────────────────────────

    async def create_traverse(self, project_id: uuid.UUID, data: TraverseCreate, user_id: str) -> TraverseOut:
        """Compute and keep a closed traverse or a level run, judged against the profile in force."""
        prof = await self.profile(project_id)
        row = SurveyTraverse(project_id=project_id, name=data.name.strip(), kind=data.kind, note=data.note)
        row.created_by = _uuid(user_id)
        row.profile_label = prof.label
        if data.kind == "traverse":
            try:
                legs = parse_legs(data.text)
                result = close_traverse(legs)
            except ValueError as exc:
                raise _bad_request(str(exc)) from exc
            row.legs = [
                {
                    "leg": leg.leg,
                    "from": leg.start,
                    "to": leg.end,
                    "length_m": leg.length_m,
                    "d_e": leg.d_e,
                    "d_n": leg.d_n,
                }
                for leg in legs
            ]
            row.length_m = _d(result.length_m, "0.001")  # type: ignore[assignment]
            row.f_e = _d(result.f_e)
            row.f_n = _d(result.f_n)
            row.misclosure_m = _d(result.misclosure_m)
            row.ratio = result.ratio
            row.profile_ratio = prof.traverse_min_ratio
            row.verdict = traverse_verdict(result.ratio, prof.traverse_min_ratio)
        else:
            if data.distance_km is None or data.misclosure_mm is None:
                raise _bad_request("A level run needs its distance (km) and misclosure (mm)")
            k = data.k_mm if data.k_mm is not None else prof.level_k_mm
            allowed, verdict = level_verdict(data.misclosure_mm, data.distance_km, k)
            row.legs = []
            row.length_m = _d(data.distance_km * 1000.0, "0.001")  # type: ignore[assignment]
            row.distance_km = _d(data.distance_km)
            row.misclosure_mm = _d(data.misclosure_mm, "0.01")
            row.k_mm = _d(k, "0.01")
            row.allowed_mm = _d(allowed, "0.01")
            row.verdict = verdict
        self.session.add(row)
        await self.session.flush()
        return _traverse_out(row)

    async def list_traverses(self, project_id: uuid.UUID) -> list[TraverseOut]:
        return [_traverse_out(t) for t in await self.repo.list_traverses(project_id)]

    async def get_traverse(self, traverse_id: uuid.UUID) -> SurveyTraverse:
        row = await self.repo.get_traverse(traverse_id)
        if row is None:
            raise not_found()
        return row

    async def delete_traverse(self, row: SurveyTraverse) -> None:
        await self.repo.delete(row)

    @staticmethod
    def transform(req: TransformRequest) -> TransformResponse:
        pts = [(float(p[0]), float(p[1]), (p[2] if len(p) > 2 else None)) for p in req.points]
        try:
            moved = crs_lib.transform_points(pts, req.source_epsg, req.target_epsg)
            return TransformResponse(source=_info(req.source_epsg), target=_info(req.target_epsg), points=moved)
        except ValueError as exc:
            raise _bad_request(str(exc)) from exc


def _traverse_out(t: SurveyTraverse) -> TraverseOut:
    length = float(t.length_m or 0)
    f_e, f_n = _f(t.f_e) or 0.0, _f(t.f_n) or 0.0
    legs = []
    for leg in t.legs or []:
        share = float(leg.get("length_m") or 0) / length if length > 0 else 0.0
        legs.append(
            TraverseLegOut(
                leg=str(leg.get("leg") or ""),
                start=str(leg.get("from") or ""),
                end=str(leg.get("to") or ""),
                length_m=float(leg.get("length_m") or 0),
                d_e=float(leg.get("d_e") or 0),
                d_n=float(leg.get("d_n") or 0),
                c_e=round(-f_e * share, 4),
                c_n=round(-f_n * share, 4),
            )
        )
    return TraverseOut(
        id=t.id,
        project_id=t.project_id,
        name=t.name,
        kind=t.kind,
        method=t.method,
        legs=legs,
        length_m=length,
        f_e=_f(t.f_e),
        f_n=_f(t.f_n),
        misclosure_m=_f(t.misclosure_m),
        ratio=t.ratio,
        profile_ratio=t.profile_ratio,
        distance_km=_f(t.distance_km),
        misclosure_mm=_f(t.misclosure_mm),
        k_mm=_f(t.k_mm),
        allowed_mm=_f(t.allowed_mm),
        verdict=t.verdict,
        profile_label=t.profile_label,
        note=t.note,
        created_at=t.created_at,
    )


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None
