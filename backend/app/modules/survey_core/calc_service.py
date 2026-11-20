# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Survey calculations: COGO, traverse from field observations and the level book.

Computing never writes. Saving is a separate, audited step: COGO results become
points of a "computed" point set with their method and inputs; a field
traverse is kept with its observations and may write its adjusted stations as
control points; a level book is kept as a level run and may write adjusted RLs
onto register points with the same id.
"""

from __future__ import annotations

import json
import math
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.survey_core import closure_classes as classes_lib
from app.modules.survey_core import cogo
from app.modules.survey_core.calc_schemas import (
    AdjustedStationOut,
    CalcClassesOut,
    CalcDemoOut,
    ClosureClassOut,
    CogoRequest,
    CogoResult,
    ComputedPointsSave,
    CornerClassOut,
    EllipseOut,
    FieldTraverseIn,
    FieldTraverseOut,
    InstrumentClassOut,
    LevelBookIn,
    LevelBookOut,
    LsqOut,
    LsqResidualOut,
    LsqStationOut,
    ReducedRowOut,
    SavedPoints,
)
from app.modules.survey_core.calc_validators import SURVEY_CALC_RULE_SET
from app.modules.survey_core.field_traverse import Station, adjust, angular_verdict
from app.modules.survey_core.level_book import BookRow, reduce
from app.modules.survey_core.lsq_traverse import CONFIDENCE_95, INSTRUMENT_CLASSES, Weights, adjust_lsq
from app.modules.survey_core.models import SurveyPoint, SurveyPointSet, SurveyTraverse
from app.modules.survey_core.schemas import Finding
from app.modules.survey_core.service import SurveyService, _traverse_out
from app.modules.survey_core.traverse import level_verdict, traverse_verdict


def _bad(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def _d(value: float | None, places: str = "0.0001") -> Decimal | None:
    return None if value is None else Decimal(str(round(value, 8))).quantize(Decimal(places))


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


async def run_rules(data: dict[str, Any], locale: str, rule_set: str = SURVEY_CALC_RULE_SET) -> list[Finding]:
    """Findings of one rule set over a transient context (nothing is stored)."""
    from app.core.validation.engine import validation_engine  # noqa: PLC0415

    report = await validation_engine.validate(
        data=data, rule_sets=[rule_set], target_type="survey_calc", target_id="", metadata={"locale": locale}
    )
    return [
        Finding(
            rule_id=r.rule_id,
            severity=str(getattr(r.severity, "value", r.severity)),
            message=r.message,
            suggestion=r.suggestion,
            element_ref=r.element_ref,
        )
        for r in report.results
        if not r.passed
    ]


def classes(markets: list[str]) -> CalcClassesOut:
    return CalcClassesOut(
        closure=[ClosureClassOut(**vars(c)) for c in classes_lib.closure_classes(markets)],
        corner=[CornerClassOut(**vars(c)) for c in classes_lib.corner_classes(markets)],
        instruments=[InstrumentClassOut(**vars(i)) for i in INSTRUMENT_CLASSES],
    )


DEMO_PATH = Path(__file__).resolve().parent / "demo" / "riverside" / "calc_demo.json"


def demo_inputs() -> CalcDemoOut:
    """The riverside demo field book: a closed traverse and a level run, as the forms take them."""
    return CalcDemoOut.model_validate(json.loads(DEMO_PATH.read_text(encoding="utf-8")))


def _weights(body: FieldTraverseIn) -> Weights:
    """A priori standard deviations: the instrument class, each value overridable."""
    base = next((i for i in INSTRUMENT_CLASSES if i.key == body.instrument_key), None)
    if body.instrument_key and base is None:
        raise _bad("Unknown instrument class")
    angle = body.angle_sd_sec or (base.angle_sd_sec if base else None)
    dist = body.dist_sd_mm if body.dist_sd_mm is not None else (base.dist_sd_mm if base else None)
    if angle is None or dist is None:
        raise _bad("Least squares needs an instrument class or the angle and distance standard deviations")
    ppm = body.dist_ppm if body.dist_ppm is not None else (base.dist_ppm if base else 0.0)
    centering = body.centering_sd_mm if body.centering_sd_mm is not None else (base.centering_sd_mm if base else 0.0)
    return Weights(angle, dist, ppm, centering)


def _lsq_out(body: FieldTraverseIn, stations: list[Station], bowditch: list[AdjustedStationOut], unit: str) -> LsqOut:
    w = _weights(body)
    try:
        res = adjust_lsq(
            body.shape,
            (body.start.e, body.start.n),
            _angle(body.azimuth, unit),
            stations,
            w,
            body.angle_sense,
            (body.end.e, body.end.n) if body.end else None,
            _angle(body.closing_azimuth, unit) if body.closing_azimuth is not None else None,
        )
    except ValueError as exc:
        raise _bad(str(exc)) from exc
    by_id = {s.station_id: s for s in bowditch}
    out_stations = []
    for s in res.stations:
        b = by_id.get(s.station_id)
        out_stations.append(
            LsqStationOut(
                station_id=s.station_id,
                e=s.e,
                n=s.n,
                fixed=s.fixed,
                d_e_mm=round((s.e - b.e) * 1000.0, 2) if b else 0.0,
                d_n_mm=round((s.n - b.n) * 1000.0, 2) if b else 0.0,
            )
        )
    return LsqOut(
        iterations=res.iterations,
        observations=res.observations,
        unknowns=res.unknowns,
        redundancy=res.redundancy,
        vtpv=round(res.vtpv, 4),
        sigma0=round(res.sigma0, 4),
        chi2_lower=round(res.chi2_lower, 4),
        chi2_upper=round(res.chi2_upper, 4),
        chi2_pass=res.chi2_pass,
        alpha=res.alpha,
        confidence_95=round(CONFIDENCE_95, 4),
        angle_sd_sec=w.angle_sd_sec,
        dist_sd_mm=w.dist_sd_mm,
        dist_ppm=w.dist_ppm,
        centering_sd_mm=w.centering_sd_mm,
        stations=out_stations,
        residuals=[
            LsqResidualOut(
                kind=r.kind,  # type: ignore[arg-type]
                ref=r.ref,
                observed=r.observed,
                residual=round(r.residual, 2),
                sd=round(r.sd, 2),
                redundancy=round(r.redundancy, 3),
                standardized=None if r.standardized is None else round(r.standardized, 2),
                flagged=r.flagged,
                suspect=r.suspect,
            )
            for r in res.residuals
        ],
        ellipses=[EllipseOut(**vars(e)) for e in res.ellipses],
        relative_ellipses=[EllipseOut(**vars(e)) for e in res.relative_ellipses],
    )


def _need(*values: object) -> None:
    if any(v is None for v in values):
        raise _bad("This computation needs more inputs")


def _angle(value: object, unit: str) -> float:
    try:
        return cogo.parse_angle(value, unit)  # type: ignore[arg-type]
    except ValueError as exc:
        raise _bad(str(exc)) from exc


async def compute_cogo(req: CogoRequest, locale: str = "en") -> CogoResult:
    """One COGO computation; SRV-040/041 come back as findings, never as an error status."""
    unit = req.angle_unit
    out = CogoResult(method=req.method, angle_unit=unit)
    status_flag = "ok"
    inputs: dict[str, Any] = {"angle_unit": unit}
    try:
        if req.method == "inverse":
            _need(req.a, req.b)
            inv = cogo.inverse(req.a, req.b)  # type: ignore[arg-type]
            out.distance, out.bearing_deg, out.d_e, out.d_n, out.d_z = (
                inv.distance,
                inv.bearing_deg,
                inv.d_e,
                inv.d_n,
                inv.d_z,
            )
            inputs.update(a=req.a, b=req.b)
        elif req.method == "polar":
            _need(req.a, req.bearing_a, req.distance)
            b = _angle(req.bearing_a, unit)
            out.solutions = [list(cogo.polar(req.a, b, req.distance))]  # type: ignore[arg-type]
            out.bearing_deg, out.distance = b, req.distance
            inputs.update(a=req.a, bearing=str(req.bearing_a), distance=req.distance)
        elif req.method == "bearing_bearing":
            _need(req.a, req.b, req.bearing_a, req.bearing_b)
            ba, bb = _angle(req.bearing_a, unit), _angle(req.bearing_b, unit)
            inputs.update(a=req.a, bearing_a=str(req.bearing_a), b=req.b, bearing_b=str(req.bearing_b))
            out.solutions = [list(cogo.bearing_bearing(req.a, ba, req.b, bb))]  # type: ignore[arg-type]
        elif req.method == "line_line":
            _need(req.a, req.b, req.c, req.d)
            inputs.update(a=req.a, b=req.b, c=req.c, d=req.d)
            out.solutions = [list(cogo.line_line(req.a, req.b, req.c, req.d))]  # type: ignore[arg-type]
        elif req.method == "distance_distance":
            _need(req.a, req.b, req.distance_a, req.distance_b)
            inputs.update(a=req.a, distance_a=req.distance_a, b=req.b, distance_b=req.distance_b)
            out.solutions = [list(p) for p in cogo.distance_distance(req.a, req.distance_a, req.b, req.distance_b)]  # type: ignore[arg-type]
            if len(out.solutions) == 2:
                status_flag = "two_solutions"
        elif req.method == "offset":
            _need(req.a, req.b, req.c)
            off = cogo.offset_to_line(req.a, req.b, req.c)  # type: ignore[arg-type]
            out.chainage, out.offset, out.solutions = off.chainage, off.offset, [list(off.foot)]
            inputs.update(a=req.a, b=req.b, p=req.c)
        else:
            _need(req.ring)
            out.area, out.perimeter = cogo.area(req.ring)  # type: ignore[arg-type]
            inputs.update(ring=req.ring)
    except cogo.CogoError as exc:
        if exc.code != "parallel":
            raise _bad(str(exc)) from exc
        status_flag = "parallel"
    if out.bearing_deg is not None:
        out.bearing_text = cogo.format_angle(out.bearing_deg, unit, 5 if unit == "dms" else 4)
    out.inputs = inputs
    out.findings = await run_rules({"cogo": [{"ref": req.method, "method": req.method, "status": status_flag}]}, locale)
    return out


class CalcService:
    """Saving side of the calculations; computing lives in the pure functions above."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.survey = SurveyService(session)

    async def _new_set(self, project_id: uuid.UUID, name: str, fmt: str, count: int, user_id: str) -> SurveyPointSet:
        crs = await self.survey.repo.get_crs(project_id)
        point_set = SurveyPointSet(
            project_id=project_id,
            name=name[:255],
            file_format=fmt,
            source_epsg=crs.horizontal_epsg if crs else None,
            stored_epsg=crs.horizontal_epsg if crs else None,
            point_count=count,
            rows_read=count,
            created_by=_uuid(user_id),
        )
        await self.survey.repo.add(point_set)
        return point_set

    async def save_points(self, project_id: uuid.UUID, body: ComputedPointsSave, user_id: str) -> SavedPoints:
        """Keep computed points with method and inputs as one new point set (audited)."""
        stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M")
        point_set = await self._new_set(project_id, body.name or f"Computed {stamp}", "cogo", len(body.points), user_id)
        await self.survey.repo.add_points(
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
                    description=p.description,
                    method=p.method,
                    inputs=p.inputs,
                )
                for p in body.points
            ]
        )
        await self.survey._audit(
            "create",
            point_set.id,
            user_id,
            {"computed_points": [p.point_id for p in body.points], "methods": sorted({p.method for p in body.points})},
            entity_type="survey_point_set",
        )
        return SavedPoints(point_set_id=str(point_set.id), saved=len(body.points))

    # ── Field traverse ─────────────────────────────────────────────────────

    @staticmethod
    async def compute_traverse(
        body: FieldTraverseIn, markets: list[str], profile_k: float | None, profile_ratio: int | None, locale: str
    ) -> FieldTraverseOut:
        unit = body.angle_unit
        cls = classes_lib.find_closure(body.class_key, markets) if body.class_key else None
        if body.class_key and cls is None:
            raise _bad("This closure class is not offered for your markets")
        k = body.angular_k_sec or (cls.angular_k_sec if cls else None) or profile_k
        min_ratio = body.min_ratio or (cls.traverse_min_ratio if cls else None) or profile_ratio
        stations = [Station(s.station_id, _angle(s.angle, unit), s.distance_m) for s in body.stations]
        try:
            result = adjust(
                body.shape,
                (body.start.e, body.start.n),
                _angle(body.azimuth, unit),
                stations,
                body.angle_sense,
                (body.end.e, body.end.n) if body.end else None,
                _angle(body.closing_azimuth, unit) if body.closing_azimuth is not None else None,
            )
        except ValueError as exc:
            raise _bad(str(exc)) from exc
        allowed, ang_verdict = angular_verdict(result.angular_misclosure_sec, result.angle_count, k)
        out = FieldTraverseOut(
            shape=result.shape,
            angle_count=result.angle_count,
            angle_sum_deg=result.angle_sum_deg,
            expected_sum_deg=result.expected_sum_deg,
            angular_misclosure_sec=round(result.angular_misclosure_sec, 2),
            angular_correction_sec=round(result.angular_correction_sec, 2),
            angular_k_sec=k,
            angular_allowed_sec=None if allowed is None else round(allowed, 2),
            angular_verdict=ang_verdict,
            length_m=result.length_m,
            f_e=result.f_e,
            f_n=result.f_n,
            misclosure_m=result.misclosure_m,
            ratio=result.ratio,
            min_ratio=min_ratio,
            linear_verdict=traverse_verdict(result.ratio, min_ratio),
            class_label=cls.label if cls else "",
            stations=[AdjustedStationOut(**vars(s)) for s in result.stations],
            method=body.method,
        )
        context: dict[str, Any] = {
            "traverses": [
                {
                    "id": body.name,
                    "kind": "traverse",
                    "angle_count": result.angle_count,
                    "ang_misclosure_sec": result.angular_misclosure_sec,
                    "ang_k_sec": k,
                }
            ]
        }
        if body.method == "lsq":
            out.lsq = _lsq_out(body, stations, out.stations, unit)
            context["lsq"] = [
                {
                    "ref": body.name,
                    "vtpv": out.lsq.vtpv,
                    "lower": out.lsq.chi2_lower,
                    "upper": out.lsq.chi2_upper,
                    "redundancy": out.lsq.redundancy,
                    "sigma0": out.lsq.sigma0,
                }
            ]
            context["lsq_residuals"] = [
                {"ref": r.ref, "kind": r.kind, "w": r.standardized} for r in out.lsq.residuals if r.suspect
            ]
        out.findings = await run_rules(context, locale)
        return out

    async def create_traverse(
        self, project_id: uuid.UUID, body: FieldTraverseIn, markets: list[str], user_id: str, locale: str
    ) -> FieldTraverseOut:
        prof = await self.survey.profile(project_id)
        out = await self.compute_traverse(body, markets, prof.angular_k_sec, prof.traverse_min_ratio, locale)
        verdicts = {out.angular_verdict, out.linear_verdict}
        row = SurveyTraverse(
            project_id=project_id,
            name=body.name.strip(),
            kind="traverse",
            method="field_lsq" if out.lsq else "field_bowditch",
            note=body.note,
            legs=[
                {"leg": str(i + 1), "from": s.station_id, "to": "", "length_m": s.distance_m or 0.0, "d_e": 0, "d_n": 0}
                for i, s in enumerate(body.stations)
                if s.distance_m
            ],
            length_m=_d(out.length_m, "0.001"),
            f_e=_d(out.f_e),
            f_n=_d(out.f_n),
            misclosure_m=_d(out.misclosure_m),
            ratio=out.ratio,
            profile_ratio=out.min_ratio,
            verdict="fail" if "fail" in verdicts else ("pass" if "pass" in verdicts else "no_profile"),
            profile_label=out.class_label or prof.label,
            created_by=_uuid(user_id),
            angle_count=out.angle_count,
            ang_misclosure_sec=_d(out.angular_misclosure_sec, "0.01"),
            ang_k_sec=_d(out.angular_k_sec, "0.01"),
            ang_allowed_sec=_d(out.angular_allowed_sec, "0.01"),
            observations={
                "input": body.model_dump(mode="json", exclude={"save_points", "note"}),
                "stations": [s.model_dump() for s in out.stations],
                **({"lsq": out.lsq.model_dump()} if out.lsq else {}),
            },
        )
        # Legs as run with the corrected azimuths, so the traverse view shows the same closure.
        for leg, a, b in zip(row.legs, out.stations, [*out.stations[1:], out.stations[0]], strict=False):
            az = math.radians(a.azimuth_deg or 0.0)
            leg["to"] = b.station_id
            leg["d_e"] = round(leg["length_m"] * math.sin(az), 4)
            leg["d_n"] = round(leg["length_m"] * math.cos(az), 4)
        self.session.add(row)
        await self.session.flush()
        if body.save_points:
            point_set = await self._new_set(project_id, f"Traverse {row.name}", "traverse", len(out.stations), user_id)
            lsq_xy = {s.station_id: (s.e, s.n) for s in out.lsq.stations} if out.lsq else {}
            await self.survey.repo.add_points(
                [
                    SurveyPoint(
                        project_id=project_id,
                        point_set_id=point_set.id,
                        point_id=s.station_id,
                        e=_d(lsq_xy.get(s.station_id, (s.e, s.n))[0]),
                        n=_d(lsq_xy.get(s.station_id, (s.e, s.n))[1]),
                        kind="control",
                        method="traverse_lsq" if out.lsq else "traverse",
                        inputs={"traverse_id": str(row.id), "c_e": s.c_e, "c_n": s.c_n},
                    )
                    for s in out.stations
                ]
            )
            out.points_saved = len(out.stations)
        await self.survey._audit(
            "create", row.id, user_id, {"traverse": row.name, "verdict": row.verdict}, entity_type="survey_traverse"
        )
        out.traverse = _traverse_out(row)
        return out

    # ── Level book ─────────────────────────────────────────────────────────

    @staticmethod
    async def compute_level_book(
        body: LevelBookIn, markets: list[str], profile_k: float | None, locale: str
    ) -> LevelBookOut:
        cls = classes_lib.find_closure(body.class_key, markets) if body.class_key else None
        if body.class_key and cls is None:
            raise _bad("This closure class is not offered for your markets")
        rows = [BookRow(r.station, r.bs, r.is_, r.fs, r.distance_m, r.rl) for r in body.rows]
        try:
            result = reduce(rows, body.start_rl, body.close_rl, body.method)
        except ValueError as exc:
            raise _bad(str(exc)) from exc
        k = body.k_mm or (cls.level_k_mm if cls else None) or profile_k
        allowed, verdict = (None, "no_profile")
        if result.misclosure_mm is not None:
            allowed, verdict = level_verdict(result.misclosure_mm, result.distance_km, k)
        out = LevelBookOut(
            method=result.method,
            rows=[
                ReducedRowOut(
                    station=r.station,
                    bs=r.bs,
                    is_=r.is_,
                    fs=r.fs,
                    rise=None if r.rise is None else round(r.rise, 4),
                    fall=None if r.fall is None else round(r.fall, 4),
                    hi=None if r.hi is None else round(r.hi, 4),
                    rl=round(r.rl, 4),
                    run_m=r.run_m,
                    correction_mm=round(r.correction_m * 1000, 2),
                    step_mm=r.step_mm,
                    rl_adjusted=round(r.rl_adjusted, 4),
                )
                for r in result.rows
            ],
            sum_bs=round(result.sum_bs, 4),
            sum_fs=round(result.sum_fs, 4),
            sum_rise=round(result.sum_rise, 4),
            sum_fall=round(result.sum_fall, 4),
            first_rl=result.first_rl,
            last_rl=round(result.last_rl_checked, 4),
            arithmetic_ok=result.arithmetic_ok,
            known_close_rl=result.known_close_rl,
            misclosure_mm=None if result.misclosure_mm is None else round(result.misclosure_mm, 2),
            distance_km=result.distance_km,
            k_mm=k,
            allowed_mm=None if allowed is None else round(allowed, 2),
            verdict=verdict,
            class_label=cls.label if cls else "",
        )
        out.findings = await run_rules({"traverses": [_level_check(body.name, out)]}, locale)
        return out

    async def create_level_book(
        self, project_id: uuid.UUID, body: LevelBookIn, markets: list[str], user_id: str, locale: str
    ) -> LevelBookOut:
        prof = await self.survey.profile(project_id)
        out = await self.compute_level_book(body, markets, prof.level_k_mm, locale)
        row = SurveyTraverse(
            project_id=project_id,
            name=body.name.strip(),
            kind="level",
            method=body.method,
            note=body.note,
            legs=[],
            length_m=_d(out.distance_km * 1000.0, "0.001"),
            distance_km=_d(out.distance_km),
            misclosure_mm=_d(out.misclosure_mm, "0.01"),
            k_mm=_d(out.k_mm, "0.01"),
            allowed_mm=_d(out.allowed_mm, "0.01"),
            verdict=out.verdict,
            profile_label=out.class_label or prof.label,
            created_by=_uuid(user_id),
            observations={
                "input": body.model_dump(mode="json", by_alias=True, exclude={"write_rls", "note"}),
                "rows": [r.model_dump(by_alias=True) for r in out.rows],
                "check": _level_check(body.name, out),
            },
        )
        self.session.add(row)
        await self.session.flush()
        if body.write_rls and out.arithmetic_ok:
            out.points_updated = await self._write_rls(project_id, out)
        await self.survey._audit(
            "create",
            row.id,
            user_id,
            {"level_book": row.name, "verdict": row.verdict, "points_updated": out.points_updated},
            entity_type="survey_traverse",
        )
        out.traverse = _traverse_out(row)
        return out

    async def _write_rls(self, project_id: uuid.UUID, out: LevelBookOut) -> int:
        """Adjusted RLs onto register points whose id matches a book station."""
        by_id = {r.station: r.rl_adjusted for r in out.rows}
        found = (
            await self.session.execute(
                select(SurveyPoint).where(SurveyPoint.project_id == project_id, SurveyPoint.point_id.in_(list(by_id)))
            )
        ).scalars()
        count = 0
        for p in found:
            p.z = _d(by_id[p.point_id])
            count += 1
        await self.session.flush()
        return count


def _level_check(name: str, out: LevelBookOut) -> dict[str, Any]:
    return {
        "id": name,
        "name": name,
        "kind": "level",
        "arithmetic_ok": out.arithmetic_ok,
        "sum_bs": out.sum_bs,
        "sum_fs": out.sum_fs,
        "first_rl": out.first_rl,
        "last_rl": out.last_rl,
        "misclosure_mm": out.misclosure_mm,
        "allowed_mm": out.allowed_mm,
        "k_mm": out.k_mm,
    }


__all__ = ["CalcService", "classes", "compute_cogo", "demo_inputs", "run_rules"]
