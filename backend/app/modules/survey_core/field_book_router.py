# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Traverse field book, included in the survey_core router (same prefix and permissions).

Endpoints:
    POST /calc/field-book                     - reduce a field book and close the traverse (nothing saved)
    POST /calc/field-book/parse               - read a field book CSV into the book shape
    GET  /calc/field-book/demo/riverside      - the Riverside control loop as a book
    POST /projects/{project_id}/field-books   - keep the traverse with its raw book; a failing closure needs a reason

The book is reduced (two faces meaned, slope to horizontal, any angle convention to angles
right) and the result goes through the existing field traverse closure, so SRV-050 and the
closure classes of the active markets apply unchanged.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from app.core.active_markets import ActiveMarkets
from app.dependencies import CurrentUserId, RequirePermission, SessionDep, verify_project_access
from app.modules.survey_core import field_book as fb
from app.modules.survey_core.calc_schemas import (
    Angle,
    AngleUnit,
    FieldTraverseIn,
    FieldTraverseOut,
    KnownPoint,
    StationIn,
)
from app.modules.survey_core.calc_service import CalcService
from app.modules.survey_core.cogo import parse_angle
from app.modules.survey_core.models import SurveyTraverse

router = APIRouter(tags=["survey_core"])

_READ = [Depends(RequirePermission("survey.read"))]
_WRITE = [Depends(RequirePermission("survey.write"))]
_LOCALE = Query("en", max_length=10)


class BookRowIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    station: str = Field(min_length=1, max_length=64)
    bs: str = Field(default="", max_length=64)
    fs: str = Field(default="", max_length=64)
    face_l: Angle | None = None
    face_r: Angle | None = None
    dist_mode: Literal["horizontal", "slope"] = "horizontal"
    distance: float | None = Field(default=None, gt=0, le=1e6)
    zenith: Angle | None = None
    hi: float | None = Field(default=None, ge=-10, le=100)
    ht: float | None = Field(default=None, ge=-10, le=100)
    note: str = Field(default="", max_length=500)


class FieldBookIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(default="Traverse", min_length=1, max_length=255)
    shape: Literal["loop", "link"] = "loop"
    angle_unit: AngleUnit = "dms"
    angle_mode: Literal["right", "left", "deflection", "azimuth"] = "right"
    start: KnownPoint
    backsight_id: str = Field(default="", max_length=64)
    backsight_azimuth: Angle | None = None
    #: Loop on a control backsight: the angle at the start from the last station to the backsight.
    closing_angle: Angle | None = None
    end: KnownPoint | None = None
    closing_azimuth: Angle | None = None
    rows: list[BookRowIn] = Field(min_length=2, max_length=500)
    class_key: str = Field(default="", max_length=60)
    angular_k_sec: float | None = Field(default=None, gt=0, le=3600)
    min_ratio: int | None = Field(default=None, ge=100, le=10_000_000)
    #: ``lsq`` adds the least-squares adjustment with error ellipses per station (Bowditch stays alongside).
    method: Literal["bowditch", "lsq"] = "bowditch"
    instrument_key: str = Field(default="", max_length=32)
    angle_sd_sec: float | None = Field(default=None, gt=0, le=600)
    dist_sd_mm: float | None = Field(default=None, ge=0, le=1000)
    dist_ppm: float | None = Field(default=None, ge=0, le=1000)
    centering_sd_mm: float | None = Field(default=None, ge=0, le=100)
    save_points: bool = False
    note: str = Field(default="", max_length=2000)


class ReducedRowOut(BaseModel):
    station: str
    angle_deg: float
    angle_right_deg: float
    face_diff_sec: float | None = None
    hd: float | None = None
    dh: float | None = None


class GridPoint(BaseModel):
    station_id: str
    e: float
    n: float


class FieldBookOut(BaseModel):
    rows: list[ReducedRowOut]
    traverse: FieldTraverseOut
    #: Stations run with the corrected angles but before the linear adjustment (the grey sketch).
    unadjusted: list[GridPoint]
    #: Where the unadjusted run ends; the misclosure vector goes from here to the fixed end.
    computed_end: GridPoint
    fixed_end: GridPoint


class BookText(BaseModel):
    text: str = Field(min_length=1, max_length=2_000_000)


def _ang(value: Angle | None, unit: str, deflection: bool = False) -> float | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    sign = 1.0
    if deflection and isinstance(value, str) and value.strip()[-1:].upper() in ("L", "R"):
        sign = -1.0 if value.strip()[-1].upper() == "L" else 1.0
        value = value.strip()[:-1]
    try:
        return sign * parse_angle(value, unit)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


def to_traverse(body: FieldBookIn) -> tuple[fb.ReducedBook, FieldTraverseIn]:
    """Reduce the book and phrase it as a field traverse in decimal degrees, angles right."""
    unit = body.angle_unit
    defl = body.angle_mode == "deflection"
    rows = [
        fb.BookRow(
            r.station,
            _ang(r.face_l, unit, defl),
            _ang(r.face_r, unit, defl),
            r.distance,
            r.dist_mode,
            _ang(r.zenith, unit),
            r.hi,
            r.ht,
        )
        for r in body.rows
    ]
    try:
        reduced = fb.reduce_book(
            body.shape,
            body.angle_mode,
            rows,
            _ang(body.backsight_azimuth, unit),
            _ang(body.closing_angle, unit),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    closing = _ang(body.closing_azimuth, unit)
    if body.shape == "link" and body.angle_mode == "azimuth":
        closing = rows[-1].face_l if rows[-1].face_l is not None else rows[-1].face_r
    last = len(reduced.stations) - 1
    traverse = FieldTraverseIn(
        name=body.name,
        shape=body.shape,
        angle_unit="deg",
        angle_sense="right",
        start=body.start,
        azimuth=reduced.azimuth_deg,
        stations=[
            StationIn(
                station_id=s.station_id,
                angle=s.angle_deg,
                distance_m=None if body.shape == "link" and i == last else s.distance_m,
            )
            for i, s in enumerate(reduced.stations)
        ],
        end=body.end,
        closing_azimuth=closing,
        class_key=body.class_key,
        angular_k_sec=body.angular_k_sec,
        min_ratio=body.min_ratio,
        method=body.method,
        instrument_key=body.instrument_key,
        angle_sd_sec=body.angle_sd_sec,
        dist_sd_mm=body.dist_sd_mm,
        dist_ppm=body.dist_ppm,
        centering_sd_mm=body.centering_sd_mm,
        save_points=body.save_points,
        note=body.note,
    )
    return reduced, traverse


def _out(reduced: fb.ReducedBook, body: FieldBookIn, result: FieldTraverseOut) -> FieldBookOut:
    start = body.start
    fixed = body.end if body.shape == "link" and body.end is not None else start
    return FieldBookOut(
        rows=[ReducedRowOut(**vars(r)) for r in reduced.rows],
        traverse=result,
        unadjusted=[GridPoint(station_id=s.station_id, e=s.e - s.c_e, n=s.n - s.c_n) for s in result.stations],
        computed_end=GridPoint(station_id=fixed.station_id, e=fixed.e + result.f_e, n=fixed.n + result.f_n),
        fixed_end=GridPoint(station_id=fixed.station_id, e=fixed.e, n=fixed.n),
    )


@router.post("/calc/field-book", response_model=FieldBookOut, dependencies=_READ)
async def calc_field_book(
    body: FieldBookIn,
    markets: ActiveMarkets,
    session: SessionDep,
    user_id: CurrentUserId,
    project_id: uuid.UUID | None = None,
    locale: str = _LOCALE,
) -> FieldBookOut:
    """Reduce and close; with ``project_id`` the project's survey profile supplies the allowance."""
    reduced, traverse = to_traverse(body)
    k = ratio = None
    if project_id is not None:
        await verify_project_access(project_id, user_id, session)
        prof = await CalcService(session).survey.profile(project_id)
        k, ratio = prof.angular_k_sec, prof.traverse_min_ratio
    try:
        result = await CalcService.compute_traverse(traverse, markets, k, ratio, locale)
    except HTTPException:
        # A book the least-squares model cannot solve still closes by the compass rule; the ellipses are left out.
        if traverse.method != "lsq":
            raise
        result = await CalcService.compute_traverse(
            traverse.model_copy(update={"method": "bowditch"}), markets, k, ratio, locale
        )
    return _out(reduced, body, result)


@router.post("/calc/field-book/parse", dependencies=_READ)
async def parse_field_book(body: BookText) -> dict:
    try:
        return fb.parse_book_csv(body.text)
    except (ValueError, KeyError) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get("/calc/field-book/demo/riverside", dependencies=_READ)
async def demo_field_book() -> dict:
    return fb.parse_book_csv(fb.DEMO_BOOK.read_text(encoding="utf-8"))


@router.post(
    "/projects/{project_id}/field-books",
    response_model=FieldBookOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=_WRITE,
)
async def create_field_book(
    project_id: uuid.UUID,
    body: FieldBookIn,
    session: SessionDep,
    user_id: CurrentUserId,
    markets: ActiveMarkets,
    locale: str = _LOCALE,
) -> FieldBookOut:
    await verify_project_access(project_id, user_id, session)
    reduced, traverse = to_traverse(body)
    service = CalcService(session)
    prof = await service.survey.profile(project_id)
    check = await CalcService.compute_traverse(traverse, markets, prof.angular_k_sec, prof.traverse_min_ratio, locale)
    if "fail" in (check.angular_verdict, check.linear_verdict) and not body.note.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="The traverse does not close within its class; give a reason to accept it",
        )
    result = await service.create_traverse(project_id, traverse, markets, user_id, locale)
    if result.traverse is not None:
        row = await session.get(SurveyTraverse, uuid.UUID(str(result.traverse.id)))
        if row is not None:
            row.observations = {**(row.observations or {}), "field_book": body.model_dump(mode="json")}
            await session.flush()
    return _out(reduced, body, result)


__all__ = ["FieldBookIn", "FieldBookOut", "router", "to_traverse"]
