# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Land and parcels business logic.

Parcels live in the project CRS from the survey register. A file in another
system is transformed only on an import whose preview named both EPSG codes.
Areas come from the boundary points (shoelace), rounded as the active pack
says; ownership and rights are stored as data, never judged. Sending the
compensation of a parcel to a BOQ writes an audit row and a back-link.
"""

from __future__ import annotations

import base64
import binascii
import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.land_parcels import (
    calc_validators,  # noqa: F401 - registers SRV-101 with the parcel rules
    parcel_io,
)
from app.modules.land_parcels.geometry import open_ring, round_area, shoelace_area
from app.modules.land_parcels.models import (
    LandParcel,
    LandParcelPoint,
    LandParcelSettings,
    LandParty,
    LandRight,
    LandWorkZone,
)
from app.modules.land_parcels.profiles import ParcelProfile, profile_for
from app.modules.land_parcels.repository import ParcelRepository
from app.modules.land_parcels.schemas import (
    BoundaryPointIn,
    BoundaryPointOut,
    FindingOut,
    ImportFeatureOut,
    ImportPreview,
    ImportRequest,
    ImportResult,
    MarkTypeOut,
    ParcelCreate,
    ParcelDetail,
    ParcelOut,
    ParcelSummary,
    ParcelUpdate,
    PartyIn,
    PartyOut,
    ProfileOut,
    RightIn,
    RightOut,
    SendToBoqRequest,
    SendToBoqResult,
    SettingsIn,
    SettingsOut,
    ValidationReportOut,
    WorkZoneOut,
)
from app.modules.land_parcels.validators import PARCEL_RULE_SET

logger = logging.getLogger(__name__)

DEFAULT_TOLERANCE_PCT = Decimal("1")
DEFAULT_GAP_M = Decimal("0.05")
BASE_FORMATS = ("geojson", "shapefile", "dxf")


def bad_request(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=detail)


def not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _q4(value: float) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.0001"))


def _s(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _ring(points: list[LandParcelPoint]) -> list[tuple[Decimal, Decimal]]:
    return [(p.e, p.n) for p in points]


def _plain(value: Decimal) -> str:
    return format(value.normalize(), "f")


class ParcelService:
    """Stateless operations over one request's session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ParcelRepository(session)

    # ── Context ────────────────────────────────────────────────────────────

    async def profile(self, project_id: uuid.UUID, markets: list[str]) -> ParcelProfile:
        info = await self.repo.project_info(project_id)
        return profile_for(markets, info.get("country"))

    @staticmethod
    def profile_out(profile: ParcelProfile) -> ProfileOut:
        return ProfileOut(
            country=profile.country,
            id_label_key=profile.id_label_key,
            id_label_default=profile.id_label_default,
            id_example=profile.id_example,
            area_decimals=profile.area_decimals,
            area_tolerance_source=profile.area_tolerance_source,
            export_formats=[*BASE_FORMATS, *profile.exporters],
            id_pattern=profile.id_pattern,
            marks=[MarkTypeOut(key=m.key, monumented=m.monumented) for m in profile.marks],
        )

    async def settings(self, project_id: uuid.UUID) -> SettingsOut:
        row = await self.repo.get_settings(project_id)
        return SettingsOut(
            area_tolerance_pct=row.area_tolerance_pct if row else DEFAULT_TOLERANCE_PCT,
            gap_tolerance_m=row.gap_tolerance_m if row else DEFAULT_GAP_M,
        )

    async def set_settings(self, project_id: uuid.UUID, data: SettingsIn, user_id: str) -> SettingsOut:
        row = await self.repo.get_settings(project_id)
        old = (await self.settings(project_id)).model_dump(mode="json")
        if row is None:
            row = LandParcelSettings(project_id=project_id)
            self.session.add(row)
        row.area_tolerance_pct = data.area_tolerance_pct
        row.gap_tolerance_m = data.gap_tolerance_m
        await self.session.flush()
        new = await self.settings(project_id)
        await self._audit(
            "update", "land_parcel_settings", project_id, user_id, {"old": old, "new": new.model_dump(mode="json")}
        )
        return new

    async def _crs(self, project_id: uuid.UUID) -> tuple[int | None, bool]:
        return await self.repo.project_epsg(project_id)

    def _tolerance(self, legal: Decimal | None, profile: ParcelProfile, pct: Decimal) -> tuple[Decimal | None, str]:
        if legal is None:
            return None, ""
        if profile.area_tolerance is not None:
            tol = profile.area_tolerance(legal)
            src = f", {profile.area_tolerance_source}" if profile.area_tolerance_source else ""
            return tol, f"{tol} m2{src}"
        return (legal * pct / 100).quantize(Decimal("0.01")), f"{_plain(pct)}% config"

    async def _rows(
        self, project_id: uuid.UUID, include_superseded: bool = False
    ) -> tuple[list[LandParcel], dict[uuid.UUID, list[LandParcelPoint]]]:
        # A split or merged parent stays as history; checks and lists see only the live parcels.
        parcels = [p for p in await self.repo.list_parcels(project_id) if include_superseded or not p.superseded]
        return parcels, await self.repo.points_by_parcel([p.id for p in parcels])

    async def _context(
        self, project_id: uuid.UUID, profile: ParcelProfile, markets: list[str] | None = None
    ) -> dict[str, Any]:
        from app.modules.land_parcels.calc_service import corner_rows  # noqa: PLC0415

        parcels, points = await self._rows(project_id)
        cfg = await self.settings(project_id)
        out = []
        corners: list[dict[str, Any]] = []
        for p in parcels:
            corners += corner_rows(p, points.get(p.id, []), markets or [])
            tol, text = self._tolerance(p.legal_area, profile, cfg.area_tolerance_pct)
            computed = round_area(p.computed_area, profile.area_decimals) if p.computed_area is not None else None
            out.append(
                {
                    "id": str(p.id),
                    "ref": p.parcel_ref,
                    "status": p.status,
                    "legal_area": _s(p.legal_area),
                    "computed_area": _s(computed),
                    "closed": p.ring_closed,
                    "ring": [[float(e), float(n)] for e, n in _ring(points.get(p.id, []))],
                    "tolerance_m2": _s(tol),
                    "tolerance_text": text,
                    "id_valid": profile.id_valid(p.parcel_ref) if profile.id_pattern else None,
                    "id_label": profile.id_label_default,
                    "id_example": profile.id_example,
                }
            )
        zones = [{"id": str(z.id), "name": z.name, "ring": z.ring} for z in await self.repo.list_zones(project_id)]
        return {
            "parcels": out,
            "work_zones": zones,
            "corners": corners,
            "settings": {"gap_tolerance_m": str(cfg.gap_tolerance_m)},
        }

    async def validate(self, project_id: uuid.UUID, markets: list[str], locale: str = "en") -> ValidationReportOut:
        from app.core.validation.engine import validation_engine  # noqa: PLC0415

        profile = await self.profile(project_id, markets)
        report = await validation_engine.validate(
            data=await self._context(project_id, profile, markets),
            rule_sets=[PARCEL_RULE_SET],
            target_type="land_parcels",
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
                FindingOut(
                    rule_id=r.rule_id,
                    severity=str(getattr(r.severity, "value", r.severity)),
                    message=r.message,
                    suggestion=r.suggestion,
                    element_ref=",".join(x for x in (r.element_ref, (r.details or {}).get("other", "")) if x),
                )
                for r in failed
            ],
        )

    # ── Parcels ────────────────────────────────────────────────────────────

    def _out(
        self,
        p: LandParcel,
        points: list[LandParcelPoint],
        rights: list[LandRight],
        profile: ParcelProfile,
        findings: list[FindingOut],
    ) -> ParcelOut:
        computed = round_area(p.computed_area, profile.area_decimals) if p.computed_area is not None else None
        diff = abs(computed - p.legal_area) if computed is not None and p.legal_area is not None else None
        return ParcelOut(
            id=p.id,
            parcel_ref=p.parcel_ref,
            name=p.name,
            status=p.status,  # type: ignore[arg-type]
            legal_area=_plain(p.legal_area) if p.legal_area is not None else None,
            computed_area=_s(computed),
            area_diff=_s(round_area(diff, profile.area_decimals)) if diff is not None else None,
            ring_closed=p.ring_closed,
            epsg=p.epsg,
            acquisition_cost=_s(p.acquisition_cost),
            currency=p.currency,
            acquired_on=p.acquired_on,
            note=p.note,
            source=p.source,
            source_filename=p.source_filename,
            point_count=len(points),
            rights_count=len(rights),
            rights_kinds=sorted({r.kind for r in rights}),
            boq_position_id=p.boq_position_id,
            sent_at=p.sent_at,
            parent_ids=[str(x) for x in (p.parent_ids or [])],
            superseded=bool(p.superseded),
            findings=findings,
        )

    @staticmethod
    def _findings_for(report: ValidationReportOut, parcel_id: uuid.UUID) -> list[FindingOut]:
        pid = str(parcel_id)
        return [f for f in report.findings if pid in (f.element_ref or "").split(",")]

    async def list_parcels(
        self, project_id: uuid.UUID, markets: list[str], locale: str, include_superseded: bool = False
    ) -> list[ParcelOut]:
        profile = await self.profile(project_id, markets)
        parcels, points = await self._rows(project_id, include_superseded)
        rights = await self.repo.list_rights(project_id)
        report = await self.validate(project_id, markets, locale)
        by_parcel: dict[uuid.UUID, list[LandRight]] = {}
        for r in rights:
            by_parcel.setdefault(r.parcel_id, []).append(r)
        return [
            self._out(p, points.get(p.id, []), by_parcel.get(p.id, []), profile, self._findings_for(report, p.id))
            for p in parcels
        ]

    async def get_parcel(self, parcel_id: uuid.UUID) -> LandParcel:
        row = await self.repo.get_parcel(parcel_id)
        if row is None:
            raise not_found()
        return row

    async def detail(self, parcel: LandParcel, markets: list[str], locale: str) -> ParcelDetail:
        profile = await self.profile(parcel.project_id, markets)
        points = (await self.repo.points_by_parcel([parcel.id])).get(parcel.id, [])
        rights = await self.repo.list_rights(parcel.project_id, parcel.id)
        report = await self.validate(parcel.project_id, markets, locale)
        base = self._out(parcel, points, rights, profile, self._findings_for(report, parcel.id))
        return ParcelDetail(
            **base.model_dump(),
            points=[
                BoundaryPointOut(
                    seq=pt.seq,
                    label=pt.label,
                    e=float(pt.e),
                    n=float(pt.n),
                    mark=pt.mark,  # type: ignore[arg-type]
                    accuracy_m=float(pt.accuracy_m) if pt.accuracy_m is not None else None,
                    corner_status=pt.corner_status or "",
                    accuracy_class=pt.accuracy_class or "",
                )
                for pt in points
            ],
            rights=await self._rights_out(parcel.project_id, rights),
        )

    async def _require_crs(self, project_id: uuid.UUID) -> int | None:
        epsg, local = await self._crs(project_id)
        if epsg is None and not local:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Set the project CRS in the survey register before adding parcels",
            )
        return epsg

    async def _write_points(self, parcel: LandParcel, pts: list[BoundaryPointIn], closed: bool) -> None:
        ring = open_ring([(p.e, p.n) for p in pts])
        kept = pts[: len(ring)]
        rows = [
            LandParcelPoint(
                parcel_id=parcel.id,
                seq=i + 1,
                label=p.label.strip() or f"{parcel.parcel_ref}-{i + 1}",
                e=_q4(p.e),
                n=_q4(p.n),
                mark=p.mark,
                accuracy_m=_q4(p.accuracy_m) if p.accuracy_m is not None else None,
                corner_status=p.corner_status,
                accuracy_class=p.accuracy_class,
            )
            for i, p in enumerate(kept)
        ]
        await self.repo.replace_points(parcel.id, rows)
        parcel.ring_closed = closed
        parcel.computed_area = (
            shoelace_area([(r.e, r.n) for r in rows]).quantize(Decimal("0.0001")) if len(rows) >= 3 else None
        )
        await self.session.flush()

    async def create_parcel(self, project_id: uuid.UUID, data: ParcelCreate, user_id: str) -> LandParcel:
        epsg = await self._require_crs(project_id)
        info = await self.repo.project_info(project_id)
        parcel = LandParcel(
            project_id=project_id,
            parcel_ref=data.parcel_ref.strip(),
            name=data.name.strip(),
            legal_area=data.legal_area,
            status=data.status,
            acquisition_cost=data.acquisition_cost,
            currency=info.get("currency") or "",
            acquired_on=data.acquired_on,
            note=data.note,
            epsg=epsg,
            created_by=_uuid(user_id),
        )
        await self.repo.add(parcel)
        # Typed points form a ring by order; the closing vertex is implied.
        await self._write_points(parcel, data.points, closed=True)
        await self._audit(
            "create",
            "land_parcel",
            parcel.id,
            user_id,
            {"parcel_ref": parcel.parcel_ref, "project_id": str(project_id)},
        )
        return parcel

    async def update_parcel(self, parcel: LandParcel, data: ParcelUpdate, user_id: str) -> LandParcel:
        fields = data.model_dump(exclude_unset=True, exclude={"clear"})
        old = {k: _jsonable(getattr(parcel, k)) for k in fields}
        for key, value in fields.items():
            if value is not None:
                setattr(
                    parcel, key, value.strip() if isinstance(value, str) and key in ("parcel_ref", "name") else value
                )
        for key in data.clear:
            setattr(parcel, key, None)
        if data.status == "acquired" and parcel.acquired_on is None and "acquired_on" not in data.clear:
            parcel.acquired_on = date.today()
        await self.session.flush()
        new = {k: _jsonable(getattr(parcel, k)) for k in [*fields, *data.clear]}
        await self._audit("update", "land_parcel", parcel.id, user_id, {"old": old, "new": new})
        return parcel

    async def set_points(self, parcel: LandParcel, pts: list[BoundaryPointIn], user_id: str) -> LandParcel:
        before = _s(parcel.computed_area)
        await self._write_points(parcel, pts, closed=True)
        await self._audit(
            "update", "land_parcel", parcel.id, user_id,
            {"points": len(pts), "computed_area_old": before, "computed_area_new": _s(parcel.computed_area)},
        )  # fmt: skip
        return parcel

    async def delete_parcel(self, parcel: LandParcel, user_id: str) -> None:
        await self._audit("delete", "land_parcel", parcel.id, user_id, {"parcel_ref": parcel.parcel_ref})
        await self.repo.delete(parcel)

    # ── Parties and rights ─────────────────────────────────────────────────

    async def list_parties(self, project_id: uuid.UUID) -> list[PartyOut]:
        return [PartyOut.model_validate(p) for p in await self.repo.list_parties(project_id)]

    async def create_party(self, project_id: uuid.UUID, data: PartyIn, user_id: str) -> PartyOut:
        party = LandParty(project_id=project_id, **data.model_dump())
        await self.repo.add(party)
        await self._audit("create", "land_party", party.id, user_id, {"name": party.name})
        return PartyOut.model_validate(party)

    async def get_party(self, party_id: uuid.UUID) -> LandParty:
        row = await self.repo.get_party(party_id)
        if row is None:
            raise not_found()
        return row

    async def update_party(self, party: LandParty, data: PartyIn, user_id: str) -> PartyOut:
        for k, v in data.model_dump().items():
            setattr(party, k, v)
        await self.session.flush()
        await self._audit("update", "land_party", party.id, user_id, {"name": party.name})
        return PartyOut.model_validate(party)

    async def delete_party(self, party: LandParty, user_id: str) -> None:
        await self._audit("delete", "land_party", party.id, user_id, {"name": party.name})
        await self.repo.delete(party)

    async def _rights_out(self, project_id: uuid.UUID, rights: list[LandRight]) -> list[RightOut]:
        names = {p.id: p.name for p in await self.repo.list_parties(project_id)}
        return [
            RightOut.model_validate(r).model_copy(
                update={"party_name": names.get(r.party_id, "") if r.party_id else ""}
            )
            for r in rights
        ]

    async def list_rights(self, project_id: uuid.UUID) -> list[RightOut]:
        return await self._rights_out(project_id, await self.repo.list_rights(project_id))

    async def add_right(self, parcel: LandParcel, data: RightIn, user_id: str) -> RightOut:
        if data.party_id is not None:
            party = await self.get_party(data.party_id)
            if party.project_id != parcel.project_id:
                raise bad_request("The party belongs to another project")
        if data.valid_from and data.valid_to and data.valid_to < data.valid_from:
            raise bad_request("A right cannot end before it starts")
        right = LandRight(project_id=parcel.project_id, parcel_id=parcel.id, **data.model_dump())
        await self.repo.add(right)
        await self._audit(
            "create", "land_right", right.id, user_id, {"parcel_ref": parcel.parcel_ref, "kind": right.kind}
        )
        return (await self._rights_out(parcel.project_id, [right]))[0]

    async def get_right(self, right_id: uuid.UUID) -> LandRight:
        row = await self.repo.get_right(right_id)
        if row is None:
            raise not_found()
        return row

    async def delete_right(self, right: LandRight, user_id: str) -> None:
        await self._audit(
            "delete", "land_right", right.id, user_id, {"kind": right.kind, "parcel_id": str(right.parcel_id)}
        )
        await self.repo.delete(right)

    # ── Work zones ─────────────────────────────────────────────────────────

    async def list_zones(self, project_id: uuid.UUID) -> list[WorkZoneOut]:
        return [
            WorkZoneOut(
                id=z.id,
                name=z.name,
                epsg=z.epsg,
                source_filename=z.source_filename,
                vertex_count=len(open_ring(z.ring)),
            )
            for z in await self.repo.list_zones(project_id)
        ]

    async def get_zone(self, zone_id: uuid.UUID) -> LandWorkZone:
        row = await self.repo.get_zone(zone_id)
        if row is None:
            raise not_found()
        return row

    async def delete_zone(self, zone: LandWorkZone, user_id: str) -> None:
        await self._audit("delete", "land_work_zone", zone.id, user_id, {"name": zone.name})
        await self.repo.delete(zone)

    # ── Import ─────────────────────────────────────────────────────────────

    def _parse(self, req: ImportRequest) -> parcel_io.ParsedFile:
        try:
            if req.format == "shapefile":
                try:
                    data = base64.b64decode(req.content_base64, validate=True)
                except (binascii.Error, ValueError) as exc:
                    raise ValueError("The Shapefile zip did not arrive intact") from exc
                return parcel_io.parse_shapefile_zip(data, req.id_field, req.legal_area_field)
            return parcel_io.parse_geojson(req.text, req.id_field, req.legal_area_field)
        except ValueError as exc:
            raise bad_request(str(exc)) from exc

    @staticmethod
    def _looks_geographic(parsed: parcel_io.ParsedFile) -> bool:
        pts = [pt for f in parsed.features for pt in f.ring]
        return bool(pts) and all(abs(x) <= 180 and abs(y) <= 90 for x, y in pts)

    async def _source_and_target(
        self, project_id: uuid.UUID, req: ImportRequest, parsed: parcel_io.ParsedFile
    ) -> tuple[int | None, int | None]:
        target = await self._require_crs(project_id)
        source = parsed.epsg or req.source_epsg
        if source is None and target is not None and self._looks_geographic(parsed):
            source = 4326  # GeoJSON without a crs member is WGS 84 by RFC 7946
        if target is None and source is not None:
            raise bad_request("The project uses a local grid; a file in an EPSG system cannot be placed on it")
        return source, target

    @staticmethod
    def _transform(parsed: parcel_io.ParsedFile, source: int | None, target: int | None) -> None:
        if source is None or target is None or source == target:
            return
        from app.modules.survey_core import crs as crs_lib  # noqa: PLC0415

        try:
            for f in parsed.features:
                moved = crs_lib.transform_points([(x, y, None) for x, y in f.ring], source, target)
                f.ring = [(x, y) for x, y, _ in moved]
        except ValueError as exc:
            raise bad_request(str(exc)) from exc

    async def preview(self, project_id: uuid.UUID, req: ImportRequest, markets: list[str]) -> ImportPreview:
        parsed = self._parse(req)
        source, target = await self._source_and_target(project_id, req, parsed)
        self._transform(parsed, source, target)
        profile = await self.profile(project_id, markets)
        existing = {p.parcel_ref for p in await self.repo.list_parcels(project_id)}
        feats, total = [], Decimal("0")
        for f in parsed.features:
            area = shoelace_area([(_q4(x), _q4(y)) for x, y in f.ring])
            total += area
            feats.append(
                ImportFeatureOut(
                    index=f.index,
                    ref=f.ref,
                    name=f.name,
                    legal_area=_s(f.legal_area),
                    computed_area=_s(round_area(area, profile.area_decimals)),
                    status=f.status,
                    vertices=len(open_ring(f.ring)),
                    closed=f.closed,
                    exists=req.target == "parcels" and f.ref in existing,
                )
            )
        return ImportPreview(
            features_read=len(parsed.features) + len(parsed.problems),
            problem_count=len(parsed.problems),
            problems=parsed.problems,
            features=feats[:200],
            fields=parsed.fields,
            file_epsg=source,
            project_epsg=target,
            transform=f"EPSG {source} -> EPSG {target}" if source and target and source != target else None,
            total_area=_s(round_area(total, profile.area_decimals)) or "0",
        )

    async def import_file(
        self, project_id: uuid.UUID, req: ImportRequest, user_id: str, markets: list[str]
    ) -> ImportResult:
        parsed = self._parse(req)
        source, target = await self._source_and_target(project_id, req, parsed)
        self._transform(parsed, source, target)
        result = ImportResult()
        if req.target == "work_zone":
            for f in parsed.features:
                zone = LandWorkZone(
                    project_id=project_id,
                    name=(f.name or (f.ref if not f.ref.startswith("#") else "") or req.filename or "Work zone")[:255],
                    ring=[[float(_q4(x)), float(_q4(y))] for x, y in open_ring(f.ring)],
                    epsg=target,
                    source_filename=req.filename[:255],
                )
                await self.repo.add(zone)
                result.work_zones += 1
            await self._audit(
                "import", "land_work_zone", project_id, user_id, {"file": req.filename, "zones": result.work_zones}
            )
            return result

        info = await self.repo.project_info(project_id)
        by_ref = {p.parcel_ref: p for p in await self.repo.list_parcels(project_id)}
        for f in parsed.features:
            pts = [BoundaryPointIn(e=x, n=y) for x, y in f.ring]
            parcel = by_ref.get(f.ref)
            if parcel is not None and req.on_existing == "skip":
                result.skipped += 1
                continue
            cost = parcel_io._dec(f.properties.get("acquisition_cost") or f.properties.get("cost"))
            if parcel is None:
                parcel = LandParcel(
                    project_id=project_id,
                    parcel_ref=f.ref,
                    name=f.name,
                    legal_area=f.legal_area,
                    status=f.status,
                    acquisition_cost=cost,
                    currency=info.get("currency") or "",
                    epsg=target,
                    source=req.format,
                    source_filename=req.filename[:255],
                    created_by=_uuid(user_id),
                )
                await self.repo.add(parcel)
                by_ref[f.ref] = parcel
                result.created += 1
            else:
                parcel.legal_area = f.legal_area if f.legal_area is not None else parcel.legal_area
                parcel.source, parcel.source_filename, parcel.epsg = req.format, req.filename[:255], target
                result.replaced += 1
            await self._write_points(parcel, pts, closed=f.closed)
        profile = await self.profile(project_id, markets)
        total = sum((p.computed_area or Decimal("0")) for p in by_ref.values())
        result.total_area = _s(round_area(Decimal(total), profile.area_decimals)) or "0"
        await self._audit(
            "import", "land_parcel", project_id, user_id,
            {"file": req.filename, "format": req.format, "source_epsg": source, "target_epsg": target,
             "created": result.created, "replaced": result.replaced, "skipped": result.skipped},
        )  # fmt: skip
        return result

    # ── Export, plan, report ───────────────────────────────────────────────

    async def export_rows(self, project_id: uuid.UUID, profile: ParcelProfile) -> list[dict[str, Any]]:
        parcels, points = await self._rows(project_id)
        out = []
        for p in parcels:
            pts = points.get(p.id, [])
            if len(pts) < 3:
                continue
            out.append(
                {
                    "id": str(p.id),
                    "ref": p.parcel_ref,
                    "name": p.name,
                    "status": p.status,
                    "legal_area": p.legal_area,
                    "computed_area": round_area(p.computed_area, profile.area_decimals)
                    if p.computed_area is not None
                    else None,
                    "acquisition_cost": p.acquisition_cost,
                    "currency": p.currency,
                    "ring": [(float(pt.e), float(pt.n)) for pt in pts],
                    "points": [
                        {
                            "label": pt.label,
                            "e": float(pt.e),
                            "n": float(pt.n),
                            "mark": pt.mark,
                            "accuracy_m": float(pt.accuracy_m) if pt.accuracy_m is not None else None,
                        }
                        for pt in pts
                    ],
                }  # fmt: skip
            )
        return out

    async def export(self, project_id: uuid.UUID, fmt: str, markets: list[str]) -> tuple[bytes, str, str]:
        profile = await self.profile(project_id, markets)
        epsg, _ = await self._crs(project_id)
        rows = await self.export_rows(project_id, profile)
        if fmt == "geojson":
            return parcel_io.to_geojson(rows, epsg), "parcels.geojson", "application/geo+json"
        if fmt == "shapefile":
            return parcel_io.to_shapefile_zip(rows, epsg), "parcels_shp.zip", "application/zip"
        if fmt == "dxf":
            return parcel_io.to_dxf(rows), "parcels.dxf", "application/dxf"
        exporter = profile.exporters.get(fmt)
        if exporter is None:
            raise bad_request(f"Unknown export format {fmt}")
        info = await self.repo.project_info(project_id)
        return exporter(rows, {**info, "epsg": epsg})

    async def plan(self, project_id: uuid.UUID, markets: list[str]) -> dict[str, Any]:
        """Parcels and work zones as GeoJSON in WGS 84 for the map; ``local`` when there is no EPSG."""
        epsg, local = await self._crs(project_id)
        profile = await self.profile(project_id, markets)
        report = await self.validate(project_id, markets)
        blocking = {ref for f in report.findings if f.rule_id == "PAR-003" for ref in (f.element_ref or "").split(",")}
        rows = await self.export_rows(project_id, profile)
        zones = await self.repo.list_zones(project_id)

        def to_map(ring: list[tuple[float, float]]) -> list[list[float]]:
            closed = [*open_ring(ring), open_ring(ring)[0]]
            if epsg is None:
                return [[x, y] for x, y in closed]
            from app.modules.survey_core import crs as crs_lib  # noqa: PLC0415

            return [
                [round(x, 8), round(y, 8)]
                for x, y, _ in crs_lib.transform_points([(x, y, None) for x, y in closed], epsg, 4326)
            ]

        features: list[dict[str, Any]] = []
        try:
            for r in rows:
                features.append(
                    {
                        "type": "Feature",
                        "id": r["id"],
                        "properties": {
                            "kind": "parcel",
                            "id": r["id"],
                            "ref": r["ref"],
                            "status": r["status"],
                            "blocking": r["id"] in blocking,
                            "area": _s(r["computed_area"]),
                        },
                        "geometry": {"type": "Polygon", "coordinates": [to_map(r["ring"])]},
                    }  # fmt: skip
                )
            for z in zones:
                if len(open_ring(z.ring)) >= 3:
                    features.append(
                        {
                            "type": "Feature",
                            "id": str(z.id),
                            "properties": {"kind": "work_zone", "id": str(z.id), "name": z.name},
                            "geometry": {
                                "type": "Polygon",
                                "coordinates": [to_map([(float(x), float(y)) for x, y in z.ring])],
                            },
                        }
                    )
        except ValueError as exc:
            raise bad_request(str(exc)) from exc
        return {"type": "FeatureCollection", "local": epsg is None and local, "epsg": epsg, "features": features}

    async def summary(self, project_id: uuid.UUID, markets: list[str]) -> ParcelSummary:
        profile = await self.profile(project_id, markets)
        parcels = await self.repo.list_parcels(project_id)
        report = await self.validate(project_id, markets)
        blocking = {f.element_ref for f in report.findings if f.rule_id == "PAR-003"}
        by_status: dict[str, int] = {}
        for p in parcels:
            by_status[p.status] = by_status.get(p.status, 0) + 1
        total = sum(
            (round_area(p.computed_area, profile.area_decimals) for p in parcels if p.computed_area is not None),
            Decimal("0"),
        )
        cost = sum((p.acquisition_cost for p in parcels if p.acquisition_cost is not None), Decimal("0"))
        info = await self.repo.project_info(project_id)
        return ParcelSummary(
            parcels=len(parcels),
            acquired=by_status.get("acquired", 0),
            total_area=_s(round_area(total, profile.area_decimals)) or "0",
            blocking_works=len(blocking),
            cost_to_acquire=_s(cost.quantize(Decimal("0.01"))) or "0",
            currency=info.get("currency") or "",
            findings=report.error_count + report.warning_count,
            by_status=by_status,
        )

    async def schedule_pdf(self, project_id: uuid.UUID, markets: list[str], locale: str, user_name: str) -> bytes:
        from app.modules.land_parcels.report import build_schedule_pdf  # noqa: PLC0415

        epsg, local = await self._crs(project_id)
        profile = await self.profile(project_id, markets)
        info = await self.repo.project_info(project_id)
        parcels = await self.list_parcels(project_id, markets, locale)
        report = await self.validate(project_id, markets, locale)
        crs_text = f"EPSG {epsg}" if epsg else ("LOCAL" if local else "-")
        return build_schedule_pdf(
            project=info.get("name", ""),
            crs=crs_text,
            decimals=profile.area_decimals,
            parcels=[p.model_dump(mode="json") for p in parcels],
            findings=[f.model_dump(mode="json") for f in report.findings],
            summary=(await self.summary(project_id, markets)).model_dump(mode="json"),
            locale=locale,
            printed_by=user_name,
            id_label=profile.id_label_default,
        )

    # ── Send compensation onward ───────────────────────────────────────────

    async def send_to_boq(
        self, parcel: LandParcel, req: SendToBoqRequest, description: str, user_id: str
    ) -> SendToBoqResult:
        from app.modules.boq.models import BOQ, Position  # noqa: PLC0415

        if parcel.acquisition_cost is None:
            raise bad_request("The parcel has no acquisition cost to send")
        boq = await self.session.get(BOQ, req.boq_id)
        if boq is None or boq.project_id != parcel.project_id:
            raise bad_request("Choose a BOQ of the same project")
        if getattr(boq, "is_locked", False):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The BOQ is locked")
        cost = parcel.acquisition_cost.quantize(Decimal("0.01"))
        source_chip = {
            "parcel_id": str(parcel.id),
            "parcel_ref": parcel.parcel_ref,
            "computed_area_m2": _s(parcel.computed_area),
            "legal_area_m2": _s(parcel.legal_area),
            "status": parcel.status,
            "epsg": parcel.epsg,
            "sent_by": str(_uuid(user_id) or ""),
        }
        if req.position_id is not None:
            pos = await self.session.get(Position, req.position_id)
            if pos is None or pos.boq_id != boq.id:
                raise bad_request("The position is not in this BOQ")
            old = {"quantity": pos.quantity, "unit_rate": pos.unit_rate, "total": pos.total}
            qty = Decimal(str(pos.quantity or "0") or "0")
            if qty <= 0:
                qty = Decimal("1")
                pos.quantity = "1"
            pos.unit_rate = format((cost / qty).quantize(Decimal("0.0001")), "f")
            pos.total = format(cost, "f")
            mode = "replaced"
        else:
            n = (
                await self.session.execute(
                    select(func.count(Position.id)).where(Position.boq_id == boq.id, Position.source == "land_parcels")
                )
            ).scalar_one()
            top = (
                await self.session.execute(select(func.max(Position.sort_order)).where(Position.boq_id == boq.id))
            ).scalar()
            pos = Position(
                boq_id=boq.id,
                ordinal=f"LND.{int(n) + 1:03d}",
                description=(description or parcel.parcel_ref)[:2000],
                unit="lsum",
                quantity="1",
                unit_rate=format(cost, "f"),
                total=format(cost, "f"),
                source="land_parcels",
                sort_order=int(top or 0) + 1,
            )
            self.session.add(pos)
            old = None
            mode = "added"
        meta = dict(pos.metadata_ or {})
        meta["land_parcels"] = source_chip
        pos.metadata_ = meta
        await self.session.flush()
        parcel.boq_position_id = pos.id
        parcel.sent_at = datetime.now(UTC)
        parcel.sent_by = _uuid(user_id)
        await self.session.flush()
        await self._audit(
            "send", "land_parcel", parcel.id, user_id,
            {"target": "boq", "boq_id": str(boq.id), "position_id": str(pos.id), "mode": mode, "old": old,
             "total": format(cost, "f"), "currency": parcel.currency},
        )  # fmt: skip
        return SendToBoqResult(
            position_id=pos.id,
            boq_id=boq.id,
            ordinal=pos.ordinal,
            description=pos.description,
            total=pos.total,
            mode=mode,
        )

    # ── Audit ──────────────────────────────────────────────────────────────

    async def _audit(self, action: str, entity: str, entity_id: Any, user_id: str, details: dict[str, Any]) -> None:
        try:
            from app.core.audit import audit_log  # noqa: PLC0415

            await audit_log(
                self.session,
                action=action,
                entity_type=entity,
                entity_id=str(entity_id),
                user_id=str(_uuid(user_id)) if _uuid(user_id) else None,
                details=details,
            )
        except Exception:  # noqa: BLE001 - the audit trail must not undo the change it records
            logger.exception("land_parcels: audit entry for %s %s failed", entity, entity_id)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, date | datetime):
        return value.isoformat()
    return value


__all__ = ["ParcelService"]
