# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Setting-out business logic.

A request snapshots its tolerance, so editing a profile later never rewrites a
verdict already given. Records are append-only: the newest record is the stake's
state and every earlier one stays as history. Every change writes an audit row.
A failed stake opens an NCR draft in the Quality module when a person presses
Create NCR draft, for all failures at once, or on its own when the project
setting ``auto_ncr`` is on. An engineer may instead accept the deviation.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.setting_out import tolerances as tol_lib
from app.modules.setting_out.design_io import (
    DesignFile,
    Problem,
    alignment_from_json,
    alignment_to_json,
    parse_design_csv,
    parse_landxml,
    parse_measured_csv,
    place_on_alignment,
)
from app.modules.setting_out.models import (
    SettingOutPoint,
    SettingOutRecord,
    SettingOutRequest,
    SettingOutSettings,
    SettingOutToleranceProfile,
)
from app.modules.setting_out.repository import SettingOutRepository
from app.modules.setting_out.schemas import (
    AcceptDeviation,
    BulkNcrOut,
    ChainageAnswer,
    ChainageQuery,
    DesignImport,
    DesignPreview,
    Finding,
    ImportProblem,
    MeasuredImport,
    MeasuredImportResult,
    NcrDraftOut,
    RecordCreate,
    RecordOut,
    RequestCreate,
    RequestDetail,
    RequestOut,
    RequestUpdate,
    SettingOutSummary,
    SettingsOut,
    SettingsUpdate,
    StakeCreate,
    StakeOut,
    ToleranceProfileCreate,
    ToleranceProfileOut,
    ToleranceValueOut,
    ValidationReportOut,
)
from app.modules.setting_out.stakeout_math import AlignmentError, stake_delta
from app.modules.setting_out.validators import SETTING_OUT_RULE_SET

logger = logging.getLogger(__name__)

DEMO_DIR = Path(__file__).resolve().parent / "demo" / "riverside"
DEMO_REQUEST_NAME = "Columns axis C"


def _err(code: int, detail: str) -> HTTPException:
    return HTTPException(status_code=code, detail=detail)


def not_found() -> HTTPException:
    return _err(status.HTTP_404_NOT_FOUND, "Not found")


def _d(value: float | None, places: str = "0.0001") -> Decimal | None:
    return None if value is None else Decimal(str(value)).quantize(Decimal(places))


def _f(value: Decimal | float | None) -> float | None:
    return None if value is None else float(value)


def _uuid(value: str | uuid.UUID | None) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _profile_out(p: tol_lib.ToleranceProfile) -> ToleranceProfileOut:
    return ToleranceProfileOut(
        key=p.key,
        name=p.name,
        source=p.source,  # type: ignore[arg-type]
        country=p.country,
        reference=p.reference,
        edition=p.edition,
        items={
            k: ToleranceValueOut(h_mm=v.h_mm, v_mm=v.v_mm, clause=v.clause, status=v.status) for k, v in p.items.items()
        },
    )


def tolerance_reference(profile: tol_lib.ToleranceProfile, value: tol_lib.Tolerance | None) -> str:
    """Standard, edition, clause and status of one tolerance, as stored on a request and quoted in an NCR."""
    parts = [profile.reference]
    if value is not None and value.clause:
        parts.append(value.clause)
    if value is not None and value.status:
        parts.append(value.status)
    return "; ".join(p for p in parts if p)[:500]


def _record_out(r: SettingOutRecord) -> RecordOut:
    return RecordOut(
        id=r.id,
        point_id=r.point_id,
        measured_e=float(r.measured_e),
        measured_n=float(r.measured_n),
        measured_z=_f(r.measured_z),
        de_mm=float(r.de_mm),
        dn_mm=float(r.dn_mm),
        d_mm=float(r.d_mm),
        dz_mm=_f(r.dz_mm),
        tol_h_mm=_f(r.tol_h_mm),
        tol_v_mm=_f(r.tol_v_mm),
        verdict=r.verdict,  # type: ignore[arg-type]
        instrument=r.instrument,
        control_ref=r.control_ref,
        measured_by=r.measured_by,
        measured_at=r.measured_at,
        note=r.note,
        ncr_id=r.ncr_id,
        deviation_accepted_at=r.deviation_accepted_at,
        deviation_accepted_by=r.deviation_accepted_by,
        deviation_note=r.deviation_note,
    )


def _problems(items: list[Problem]) -> list[ImportProblem]:
    return [ImportProblem(line=p.line, point_id=p.point_id, message=p.message) for p in items]


class SettingOutService:
    """Stateless operations over one request's session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SettingOutRepository(session)

    async def _audit(self, action: str, entity_id: uuid.UUID, user_id: str | None, details: dict[str, Any]) -> None:
        try:
            from app.core.audit import audit_log  # noqa: PLC0415

            uid = _uuid(user_id)
            await audit_log(
                self.session,
                action=action,
                entity_type="setting_out",
                entity_id=str(entity_id),
                user_id=str(uid) if uid else None,
                details=details,
            )
        except Exception:  # noqa: BLE001 - the audit trail must not undo the change it records
            logger.exception("setting_out: audit entry for %s failed", entity_id)

    # ── Settings ───────────────────────────────────────────────────────────

    async def get_settings(self, project_id: uuid.UUID) -> SettingsOut:
        row = await self.repo.settings(project_id)
        if row is None:
            return SettingsOut()
        return SettingsOut(default_tolerance_key=row.default_tolerance_key, auto_ncr=row.auto_ncr)

    async def set_settings(
        self, project_id: uuid.UUID, body: SettingsUpdate, user_id: str, markets: list[str]
    ) -> SettingsOut:
        if body.default_tolerance_key:
            await self._resolve(project_id, body.default_tolerance_key, "other", markets)
        row = await self.repo.settings(project_id)
        if row is None:
            row = SettingOutSettings(project_id=project_id, default_tolerance_key="", auto_ncr=False)
            self.session.add(row)
        old = {"default_tolerance_key": row.default_tolerance_key or "", "auto_ncr": bool(row.auto_ncr)}
        if body.default_tolerance_key is not None:
            row.default_tolerance_key = body.default_tolerance_key
        if body.auto_ncr is not None:
            row.auto_ncr = body.auto_ncr
        await self.session.flush()
        await self._audit("settings", project_id, user_id, {"old": old, "new": body.model_dump(exclude_none=True)})
        return SettingsOut(default_tolerance_key=row.default_tolerance_key, auto_ncr=row.auto_ncr)

    # ── Tolerance profiles ─────────────────────────────────────────────────

    async def profiles(self, project_id: uuid.UUID, markets: list[str]) -> list[ToleranceProfileOut]:
        """Demo profile, then the active packs' profiles, then the project's own."""
        out = [_profile_out(tol_lib.DEMO_PROFILE)]
        out += [_profile_out(p) for p in tol_lib.pack_profiles_for(markets)]
        for row in await self.repo.list_profiles(project_id):
            out.append(_profile_out(self._project_profile(row)))
        return out

    @staticmethod
    def _project_profile(row: SettingOutToleranceProfile) -> tol_lib.ToleranceProfile:
        p = tol_lib.profile_from_items(f"project:{row.id}", row.name, row.items or {})
        return tol_lib.ToleranceProfile(p.key, p.name, "project", p.items, "", row.reference)

    async def create_profile(
        self, project_id: uuid.UUID, body: ToleranceProfileCreate, user_id: str
    ) -> ToleranceProfileOut:
        row = SettingOutToleranceProfile(
            project_id=project_id,
            name=body.name,
            reference=body.reference,
            items={k: v.model_dump() for k, v in body.items.items()},
            created_by=_uuid(user_id),
        )
        await self.repo.add(row)
        await self._audit("create", row.id, user_id, {"profile": body.model_dump(mode="json")})
        return _profile_out(self._project_profile(row))

    async def _resolve(
        self, project_id: uuid.UUID, key: str, item_type: str, markets: list[str]
    ) -> tuple[str, str, float | None, float | None, str]:
        """``(label, source, h_mm, v_mm, reference)`` of profile ``key`` for ``item_type``; empty key = no profile."""
        if not key:
            return "", "", None, None, ""
        profile: tol_lib.ToleranceProfile | None
        if key.startswith("project:"):
            row = await self.repo.get_profile(_uuid(key.split(":", 1)[1]) or uuid.uuid4())
            profile = self._project_profile(row) if row and row.project_id == project_id else None
        else:
            profile = tol_lib.builtin_profile(key, markets)
        if profile is None:
            raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, "Unknown tolerance profile")
        value = profile.for_item(item_type)
        reference = tolerance_reference(profile, value)
        if value is None:
            return profile.name, profile.source, None, None, reference
        return profile.name, profile.source, value.h_mm, value.v_mm, reference

    # ── Requests ───────────────────────────────────────────────────────────

    async def create_request(
        self, project_id: uuid.UUID, body: RequestCreate, user_id: str, markets: list[str]
    ) -> RequestOut:
        label, source, h, v, reference = await self._resolve(project_id, body.tolerance_key, body.item_type, markets)
        req = SettingOutRequest(
            project_id=project_id,
            code=await self.repo.next_code(project_id),
            name=body.name,
            item_type=body.item_type,
            tolerance_key=body.tolerance_key,
            tolerance_label=label,
            tolerance_source=source,
            tolerance_reference=reference,
            tol_h_mm=_d(body.tol_h_mm if body.tol_h_mm is not None else h, "0.1"),
            tol_v_mm=_d(body.tol_v_mm if body.tol_v_mm is not None else v, "0.1"),
            element_ref_type=body.element_ref_type,
            element_ref_id=body.element_ref_id,
            element_ref_label=body.element_ref_label,
            instrument=body.instrument,
            control_ref=body.control_ref,
            note=body.note,
            created_by=_uuid(user_id),
        )
        await self.repo.add(req)
        await self._audit("create", req.id, user_id, {"request": body.model_dump(mode="json"), "code": req.code})
        return self._request_out(req, [], {})

    async def update_request(
        self, req: SettingOutRequest, body: RequestUpdate, user_id: str, markets: list[str]
    ) -> RequestOut:
        changes = body.model_dump(exclude_unset=True)
        old = {k: getattr(req, k) for k in changes}
        for field in ("name", "item_type", "element_ref_type", "element_ref_id", "element_ref_label",
                      "instrument", "control_ref", "note"):  # fmt: skip
            if changes.get(field) is not None:
                setattr(req, field, changes[field])
        if "tolerance_key" in changes or "item_type" in changes:
            key = changes.get("tolerance_key", req.tolerance_key) or ""
            label, source, h, v, reference = await self._resolve(req.project_id, key, req.item_type, markets)
            req.tolerance_key, req.tolerance_label, req.tolerance_source = key, label, source
            req.tolerance_reference = reference
            req.tol_h_mm, req.tol_v_mm = _d(h, "0.1"), _d(v, "0.1")
        if "tol_h_mm" in changes:
            req.tol_h_mm = _d(changes["tol_h_mm"], "0.1")
        if "tol_v_mm" in changes:
            req.tol_v_mm = _d(changes["tol_v_mm"], "0.1")
        await self.session.flush()
        await self._audit(
            "update",
            req.id,
            user_id,
            {"old": {k: str(v) for k, v in old.items()}, "new": body.model_dump(mode="json", exclude_unset=True)},
        )
        return await self.request_out(req)

    async def get_request(self, request_id: uuid.UUID) -> SettingOutRequest:
        req = await self.repo.get_request(request_id)
        if req is None:
            raise not_found()
        return req

    async def delete_request(self, req: SettingOutRequest, user_id: str) -> None:
        await self._audit("delete", req.id, user_id, {"code": req.code, "name": req.name})
        await self.repo.delete_request(req)

    @staticmethod
    def _latest(records: list[SettingOutRecord]) -> tuple[dict[uuid.UUID, SettingOutRecord], dict[uuid.UUID, int]]:
        latest: dict[uuid.UUID, SettingOutRecord] = {}
        counts: dict[uuid.UUID, int] = {}
        for r in records:
            latest[r.point_id] = r
            counts[r.point_id] = counts.get(r.point_id, 0) + 1
        return latest, counts

    def _stake_out(self, p: SettingOutPoint, latest: SettingOutRecord | None, count: int) -> StakeOut:
        return StakeOut(
            id=p.id,
            point_id=p.point_id,
            design_e=float(p.design_e),
            design_n=float(p.design_n),
            design_z=_f(p.design_z),
            chainage=_f(p.chainage),
            offset_m=_f(p.offset_m),
            code=p.code,
            verdict=latest.verdict if latest else "open",  # type: ignore[arg-type]
            latest=_record_out(latest) if latest else None,
            record_count=count,
        )

    def _request_out(
        self, req: SettingOutRequest, stakes: list[SettingOutPoint], latest: dict[uuid.UUID, SettingOutRecord]
    ) -> RequestOut:
        verdicts = [latest[s.id].verdict if s.id in latest else "open" for s in stakes]
        return RequestOut(
            id=req.id,
            project_id=req.project_id,
            code=req.code,
            name=req.name,
            item_type=req.item_type,
            tolerance_key=req.tolerance_key,
            tolerance_label=req.tolerance_label,
            tolerance_source=req.tolerance_source,
            tolerance_reference=req.tolerance_reference or "",
            tol_h_mm=_f(req.tol_h_mm),
            tol_v_mm=_f(req.tol_v_mm),
            element_ref_type=req.element_ref_type,
            element_ref_id=req.element_ref_id,
            element_ref_label=req.element_ref_label,
            alignment=req.alignment,
            instrument=req.instrument,
            control_ref=req.control_ref,
            source_filename=req.source_filename,
            note=req.note,
            created_at=req.created_at,
            point_count=len(stakes),
            open_count=verdicts.count("open"),
            pass_count=verdicts.count("pass"),
            fail_count=verdicts.count("fail"),
        )

    async def request_out(self, req: SettingOutRequest) -> RequestOut:
        stakes = await self.repo.stakes([req.id])
        latest, _ = self._latest(await self.repo.records([req.id]))
        return self._request_out(req, stakes, latest)

    async def list_requests(self, project_id: uuid.UUID) -> list[RequestOut]:
        reqs = await self.repo.list_requests(project_id)
        ids = [r.id for r in reqs]
        stakes = await self.repo.stakes(ids)
        latest, _ = self._latest(await self.repo.records(ids))
        return [self._request_out(r, [s for s in stakes if s.request_id == r.id], latest) for r in reqs]

    async def detail(self, req: SettingOutRequest) -> RequestDetail:
        stakes = await self.repo.stakes([req.id])
        latest, counts = self._latest(await self.repo.records([req.id]))
        base = self._request_out(req, stakes, latest)
        return RequestDetail(
            **base.model_dump(),
            stakes=[self._stake_out(s, latest.get(s.id), counts.get(s.id, 0)) for s in stakes],
        )

    # ── Design import ──────────────────────────────────────────────────────

    @staticmethod
    def _parse(req: SettingOutRequest, body: DesignImport) -> DesignFile:
        parsed = (
            parse_landxml(body.text, body.alignment_name)
            if body.file_format == "landxml"
            else parse_design_csv(body.text)
        )
        alignment = parsed.alignment or alignment_from_json(req.alignment)
        place_on_alignment(parsed.points, alignment, parsed.problems)
        parsed.alignment = alignment
        return parsed

    async def preview_design(self, req: SettingOutRequest, body: DesignImport) -> DesignPreview:
        parsed = self._parse(req, body)
        return DesignPreview(
            rows_read=parsed.rows_read,
            points=[
                {"point_id": p.point_id, "e": p.e, "n": p.n, "z": p.z, "chainage": p.chainage, "offset_m": p.offset}
                for p in parsed.points[:20]
            ],
            alignment=alignment_to_json(parsed.alignment) if parsed.alignment else None,
            problems=_problems(parsed.problems),
            problem_count=len(parsed.problems),
        )

    async def import_design(self, req: SettingOutRequest, body: DesignImport, user_id: str) -> RequestDetail:
        parsed = self._parse(req, body)
        if not parsed.points and parsed.alignment is None:
            raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file has no design stakes and no alignment")
        if body.mode == "replace":
            await self.repo.delete_unmeasured_stakes(req.id)
        existing = {s.point_id for s in await self.repo.stakes([req.id])}
        start = len(existing)
        added = 0
        for i, p in enumerate(parsed.points):
            if p.point_id in existing:
                continue
            self.session.add(
                SettingOutPoint(
                    project_id=req.project_id,
                    request_id=req.id,
                    point_id=p.point_id,
                    design_e=_d(p.e),
                    design_n=_d(p.n),
                    design_z=_d(p.z),
                    chainage=_d(p.chainage),
                    offset_m=_d(p.offset),
                    code=p.code,
                    sort_order=start + i,
                )
            )
            added += 1
        if parsed.alignment is not None:
            req.alignment = alignment_to_json(parsed.alignment)
        req.source_filename = body.filename or req.source_filename
        await self.session.flush()
        await self._audit(
            "import",
            req.id,
            user_id,
            {
                "file": body.filename,
                "format": body.file_format,
                "stakes_added": added,
                "problems": len(parsed.problems),
            },
        )
        return await self.detail(req)

    async def add_stake(self, req: SettingOutRequest, body: StakeCreate, user_id: str) -> StakeOut:
        stakes = await self.repo.stakes([req.id])
        if any(s.point_id == body.point_id for s in stakes):
            raise _err(status.HTTP_409_CONFLICT, "Point id already in this request")
        e, n, ch, off = body.e, body.n, body.chainage, body.offset_m
        alignment = alignment_from_json(req.alignment)
        try:
            if e is None or n is None:
                if ch is None or alignment is None:
                    raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give E and N, or a chainage on an alignment")
                e, n = alignment.point_at(ch, off or 0.0)
            elif alignment is not None and ch is None:
                ch, off = alignment.station_offset(e, n)
        except AlignmentError as exc:
            raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        stake = SettingOutPoint(
            project_id=req.project_id,
            request_id=req.id,
            point_id=body.point_id,
            design_e=_d(e),
            design_n=_d(n),
            design_z=_d(body.z),
            chainage=_d(ch),
            offset_m=_d(off),
            code=body.code,
            sort_order=len(stakes),
        )
        await self.repo.add(stake)
        await self._audit("create", req.id, user_id, {"stake": body.point_id, "e": e, "n": n})
        return self._stake_out(stake, None, 0)

    async def get_stake(self, stake_id: uuid.UUID) -> SettingOutPoint:
        stake = await self.repo.get_stake(stake_id)
        if stake is None:
            raise not_found()
        return stake

    def chainage(self, req: SettingOutRequest, q: ChainageQuery) -> ChainageAnswer:
        alignment = alignment_from_json(req.alignment)
        if alignment is None:
            raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, "This request has no alignment")
        try:
            if q.e is not None and q.n is not None:
                ch, off = alignment.station_offset(q.e, q.n)
                return ChainageAnswer(e=q.e, n=q.n, chainage=round(ch, 4), offset_m=round(off, 4))
            if q.chainage is None:
                raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, "Give E and N, or a chainage")
            e, n = alignment.point_at(q.chainage, q.offset_m or 0.0)
            return ChainageAnswer(e=round(e, 4), n=round(n, 4), chainage=q.chainage, offset_m=q.offset_m or 0.0)
        except AlignmentError as exc:
            raise _err(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc

    # ── Records ────────────────────────────────────────────────────────────

    async def _record(
        self,
        req: SettingOutRequest,
        stake: SettingOutPoint,
        e: float,
        n: float,
        z: float | None,
        instrument: str | None,
        control_ref: str | None,
        note: str,
        user_id: str,
        measured_by: str = "",
    ) -> SettingOutRecord:
        tol_h, tol_v = _f(req.tol_h_mm), _f(req.tol_v_mm)
        delta = stake_delta((float(stake.design_e), float(stake.design_n), _f(stake.design_z)), (e, n, z), tol_h, tol_v)
        uid = _uuid(user_id)
        rec = SettingOutRecord(
            project_id=req.project_id,
            request_id=req.id,
            point_id=stake.id,
            measured_e=_d(e),
            measured_n=_d(n),
            measured_z=_d(z),
            de_mm=_d(delta.de_mm, "0.1"),
            dn_mm=_d(delta.dn_mm, "0.1"),
            d_mm=_d(delta.d_mm, "0.1"),
            dz_mm=_d(delta.dz_mm, "0.1"),
            tol_h_mm=req.tol_h_mm,
            tol_v_mm=req.tol_v_mm,
            verdict=delta.verdict,
            instrument=(req.instrument if instrument is None else instrument)[:255],
            control_ref=(req.control_ref if control_ref is None else control_ref)[:255],
            measured_by=(measured_by or await self.repo.user_name(uid))[:255],
            measured_by_id=uid,
            measured_at=datetime.now(UTC),
            note=note,
        )
        await self.repo.add(rec)
        await self._audit(
            "create",
            req.id,
            user_id,
            {
                "stake": stake.point_id,
                "record": str(rec.id),
                "d_mm": delta.d_mm,
                "dz_mm": delta.dz_mm,
                "verdict": delta.verdict,
            },
        )
        if rec.verdict == "fail":
            await self._auto_ncr(rec, user_id)
        return rec

    async def _auto_ncr(self, rec: SettingOutRecord, user_id: str) -> None:
        """Open the NCR draft on its own when the project asks for it; a failure never undoes the record."""
        settings = await self.repo.settings(rec.project_id)
        if settings is None or not settings.auto_ncr:
            return
        try:
            async with self.session.begin_nested():
                await self.create_ncr_draft(rec, user_id)
        except Exception:  # noqa: BLE001 - the measurement stands even when Quality is unavailable
            logger.exception("setting_out: automatic NCR draft for record %s failed", rec.id)

    async def add_record(self, stake: SettingOutPoint, body: RecordCreate, user_id: str) -> RecordOut:
        req = await self.get_request(stake.request_id)
        rec = await self._record(
            req,
            stake,
            body.measured_e,
            body.measured_n,
            body.measured_z,
            body.instrument,
            body.control_ref,
            body.note,
            user_id,
        )
        return _record_out(rec)

    async def import_measured(self, req: SettingOutRequest, body: MeasuredImport, user_id: str) -> MeasuredImportResult:
        rows, problems = parse_measured_csv(body.text)
        by_id = {s.point_id: s for s in await self.repo.stakes([req.id])}
        passed = failed = recorded = 0
        for row in rows:
            stake = by_id.get(row.point_id)
            if stake is None:
                problems.append(Problem(row.line, "no design stake with this id in the request", row.point_id))
                continue
            rec = await self._record(
                req,
                stake,
                row.e,
                row.n,
                row.z,
                row.instrument or None,
                row.control_ref or None,
                row.note,
                user_id,
                row.measured_by,
            )
            recorded += 1
            passed += rec.verdict == "pass"
            failed += rec.verdict == "fail"
        return MeasuredImportResult(recorded=recorded, passed=passed, failed=failed, problems=_problems(problems))

    async def history(self, stake: SettingOutPoint) -> list[RecordOut]:
        return [_record_out(r) for r in await self.repo.point_records(stake.id)]

    async def get_record(self, record_id: uuid.UUID) -> SettingOutRecord:
        rec = await self.repo.get_record(record_id)
        if rec is None:
            raise not_found()
        return rec

    async def create_ncr_draft(self, rec: SettingOutRecord, user_id: str, locale: str = "en") -> NcrDraftOut:
        """Open an NCR in Quality for a failed stake; once per record."""
        if rec.verdict != "fail":
            raise _err(status.HTTP_409_CONFLICT, "Only a failed stake opens an NCR")
        if rec.ncr_id:
            raise _err(status.HTTP_409_CONFLICT, "This record already has an NCR")
        if rec.deviation_accepted_at is not None:
            raise _err(status.HTTP_409_CONFLICT, "The deviation of this record was accepted")
        try:
            from app.modules.ncr.schemas import NCRCreate  # noqa: PLC0415
            from app.modules.ncr.service import NCRService  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - the quality module is optional
            raise _err(status.HTTP_409_CONFLICT, "The quality (NCR) module is not installed") from exc
        from app.core.validation.messages import translate  # noqa: PLC0415

        req = await self.get_request(rec.request_id)
        stake = await self.get_stake(rec.point_id)
        height_fail = rec.tol_h_mm is not None and rec.d_mm <= rec.tol_h_mm and rec.dz_mm is not None
        d = abs(rec.dz_mm) if height_fail and rec.dz_mm is not None else rec.d_mm
        t = rec.tol_v_mm if height_fail else rec.tol_h_mm

        def fmt(v: object) -> str:
            return f"{float(v):g}" if v is not None else "?"  # type: ignore[arg-type]

        title = translate("setting_out.stake_off.fail", locale=locale, id=stake.point_id, d=fmt(d), t=fmt(t))
        description = "\n".join(
            [
                f"{req.code} {req.name}",
                f"{stake.point_id}: design E {float(stake.design_e):.3f} N {float(stake.design_n):.3f}"
                + (f" Z {float(stake.design_z):.3f}" if stake.design_z is not None else ""),
                f"measured E {float(rec.measured_e):.3f} N {float(rec.measured_n):.3f}"
                + (f" Z {float(rec.measured_z):.3f}" if rec.measured_z is not None else ""),
                f"dE {float(rec.de_mm):g} mm, dN {float(rec.dn_mm):g} mm, d {float(rec.d_mm):g} mm"
                + (f", dZ {float(rec.dz_mm):g} mm" if rec.dz_mm is not None else ""),
                f"tolerance {fmt(rec.tol_h_mm)} mm"
                + (f", height {fmt(rec.tol_v_mm)} mm" if rec.tol_v_mm is not None else "")
                + f" ({req.tolerance_label})",
                f"source: {req.tolerance_reference or '-'}",
                f"{rec.measured_by} · {rec.instrument} · {rec.control_ref}",
            ]
        )
        ncr = await NCRService(self.session).create_ncr(
            NCRCreate(
                project_id=rec.project_id,
                title=title[:500],
                description=description,
                ncr_type="workmanship",
                severity="minor",
                location_description=f"{req.name} / {stake.point_id}"[:500],
                metadata={
                    "source": "setting_out",
                    "draft": True,
                    "request_id": str(req.id),
                    "record_id": str(rec.id),
                    "point_id": stake.point_id,
                    "d_mm": float(rec.d_mm),
                    "dz_mm": _f(rec.dz_mm),
                    "tol_h_mm": _f(rec.tol_h_mm),
                    "tol_v_mm": _f(rec.tol_v_mm),
                    "tolerance_label": req.tolerance_label,
                    "tolerance_reference": req.tolerance_reference or "",
                    "rule_id": "SET-001",
                },
            ),
            user_id=user_id,
        )
        rec.ncr_id = str(ncr.id)
        await self.session.flush()
        await self._audit(
            "create", req.id, user_id, {"ncr": str(ncr.id), "record": str(rec.id), "stake": stake.point_id}
        )
        return NcrDraftOut(ncr_id=str(ncr.id), ncr_number=str(ncr.ncr_number or ""), record_id=rec.id)

    async def create_ncr_drafts(
        self, project_id: uuid.UUID, user_id: str, locale: str = "en", request_id: uuid.UUID | None = None
    ) -> BulkNcrOut:
        """One NCR draft for every failed stake that has neither an NCR nor an accepted deviation."""
        ids = [r.id for r in await self.repo.list_requests(project_id) if request_id is None or r.id == request_id]
        latest, _ = self._latest(await self.repo.records(ids))
        created: list[NcrDraftOut] = []
        skipped = 0
        for rec in latest.values():
            if rec.verdict != "fail":
                continue
            if rec.ncr_id or rec.deviation_accepted_at is not None:
                skipped += 1
                continue
            created.append(await self.create_ncr_draft(rec, user_id, locale))
        return BulkNcrOut(created=created, skipped=skipped)

    async def accept_deviation(self, rec: SettingOutRecord, body: AcceptDeviation, user_id: str) -> RecordOut:
        """Record that the engineer accepts a failed stake as built, with the reason."""
        if rec.verdict != "fail":
            raise _err(status.HTTP_409_CONFLICT, "Only a failed stake has a deviation to accept")
        if rec.deviation_accepted_at is not None:
            raise _err(status.HTTP_409_CONFLICT, "The deviation of this record was already accepted")
        rec.deviation_accepted_at = datetime.now(UTC)
        rec.deviation_accepted_by = (await self.repo.user_name(_uuid(user_id)))[:255]
        rec.deviation_note = body.note
        await self.session.flush()
        await self._audit("accept_deviation", rec.request_id, user_id, {"record": str(rec.id), "note": body.note})
        return _record_out(rec)

    # ── Validation, summary, sheet ─────────────────────────────────────────

    async def _context(self, project_id: uuid.UUID, request_id: uuid.UUID | None = None) -> dict[str, Any]:
        reqs = [r for r in await self.repo.list_requests(project_id) if request_id is None or r.id == request_id]
        ids = [r.id for r in reqs]
        codes = {r.id: r.code for r in reqs}
        stakes = await self.repo.stakes(ids)
        latest, _ = self._latest(await self.repo.records(ids))
        out = []
        for s in stakes:
            rec = latest.get(s.id)
            out.append(
                {
                    "request": codes.get(s.request_id, ""),
                    "point_id": s.point_id,
                    "measured": rec is not None,
                    "verdict": rec.verdict if rec else "open",
                    "d_mm": _f(rec.d_mm) if rec else None,
                    "dz_mm": _f(rec.dz_mm) if rec else None,
                    "tol_h_mm": _f(rec.tol_h_mm) if rec else None,
                    "tol_v_mm": _f(rec.tol_v_mm) if rec else None,
                    "instrument": rec.instrument if rec else "",
                    "control_ref": rec.control_ref if rec else "",
                    "ncr_id": rec.ncr_id if rec else None,
                    "deviation_accepted": bool(rec and rec.deviation_accepted_at is not None),
                }
            )
        return {"stakes": out}

    async def validate(
        self, project_id: uuid.UUID, locale: str = "en", request_id: uuid.UUID | None = None
    ) -> ValidationReportOut:
        from app.core.validation.engine import validation_engine  # noqa: PLC0415

        report = await validation_engine.validate(
            data=await self._context(project_id, request_id),
            rule_sets=[SETTING_OUT_RULE_SET],
            target_type="setting_out",
            target_id=str(request_id or project_id),
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

    async def summary(self, project_id: uuid.UUID) -> SettingOutSummary:
        reqs = await self.list_requests(project_id)
        ids = [r.id for r in reqs]
        latest, _ = self._latest(await self.repo.records(ids))
        return SettingOutSummary(
            requests=len(reqs),
            open=sum(r.open_count for r in reqs),
            passed=sum(r.pass_count for r in reqs),
            failed=sum(r.fail_count for r in reqs),
            ncr_drafts=sum(1 for r in latest.values() if r.ncr_id),
        )

    async def sheet_pdf(self, req: SettingOutRequest, locale: str = "en") -> bytes:
        from app.modules.setting_out.sheet_pdf import build_setting_out_sheet  # noqa: PLC0415

        detail = await self.detail(req)
        report = await self.validate(req.project_id, locale, req.id)
        scale_note, scale_findings = await self._scale_note(detail, locale)
        return build_setting_out_sheet(
            detail,
            project_name=await self.repo.project_name(req.project_id),
            crs_label=await self.repo.project_crs_label(req.project_id),
            findings=[*report.findings, *scale_findings],
            locale=locale,
            scale_note=scale_note,
        )

    async def _scale_note(self, detail: RequestDetail, locale: str) -> tuple[str, list[Finding]]:
        """CSF line for the sheet at the stakes' centre, and SRV-025 when grid and ground differ by 0.5 mm or more."""
        from app.core.validation.messages import translate  # noqa: PLC0415
        from app.modules.survey_core.service import SurveyService  # noqa: PLC0415

        if not detail.stakes:
            return "", []
        e = sum(s.design_e for s in detail.stakes) / len(detail.stakes)
        n = sum(s.design_n for s in detail.stakes) / len(detail.stakes)
        zs = [s.design_z for s in detail.stakes if s.design_z is not None]
        sf = await SurveyService(self.session).scale_factor(
            detail.project_id, e=e, n=n, height_m=sum(zs) / len(zs) if zs else None
        )
        if sf is None:
            return "", []
        note = translate(
            "setting_out.sheet.scale_line",
            locale=locale,
            csf=f"{sf.csf:.8f}",
            k=f"{sf.k:.8f}",
            h=f"{sf.height_m:.1f}",
            grid=f"{sf.distance_m:.3f}",
            ground=f"{sf.ground_m:.3f}",
        )
        if abs(sf.diff_mm) < 0.5:
            return note, []
        params = {"d": f"{sf.distance_m:g}", "mm": f"{sf.diff_mm:.0f}"}
        return note, [
            Finding(
                rule_id="SRV-025",
                severity="warning",
                message=translate("survey.ground_grid.fail", locale=locale, **params),
                suggestion=translate("survey.ground_grid.suggestion", locale=locale, **params),
            )
        ]

    async def export_stakes(self, req: SettingOutRequest, fmt: str, locale: str = "en") -> tuple[str, list]:
        """Design stakes of a request in a survey exchange format, in the project CRS."""
        from app.modules.survey_core.point_export import ExportPoint  # noqa: PLC0415
        from app.modules.survey_core.service import SurveyService  # noqa: PLC0415

        detail = await self.detail(req)
        points = [
            ExportPoint(s.point_id, s.design_e, s.design_n, s.design_z, s.code, detail.name) for s in detail.stakes
        ]
        return await SurveyService(self.session).write_points(
            req.project_id,
            points,
            fmt,
            locale=locale,
            project_name=await self.repo.project_name(req.project_id),
        )

    # ── Riverside Yard demo ────────────────────────────────────────────────

    async def load_riverside_demo(self, project_id: uuid.UUID, user_id: str) -> RequestDetail:
        """Request "Columns axis C" with the demo profile, its alignment and the two design stakes.

        Idempotent: a project that already has the request gets it back unchanged.
        Measured values are left for the learner to type (lessons 2 and 3).
        """
        for r in await self.repo.list_requests(project_id):
            if r.name == DEMO_REQUEST_NAME:
                return await self.detail(r)
        out = await self.create_request(
            project_id,
            RequestCreate(
                name=DEMO_REQUEST_NAME,
                item_type="column",
                tolerance_key=tol_lib.DEMO_KEY,
                element_ref_type="boq",
                element_ref_label="Columns axis C",
                instrument="Demo total station",
                control_ref="CP1, CP2",
            ),
            user_id,
            ["*"],
        )
        req = await self.get_request(out.id)
        await self.import_design(
            req,
            DesignImport(
                text=(DEMO_DIR / "axis_c.xml").read_text(encoding="utf-8"), filename="axis_c.xml", file_format="landxml"
            ),
            user_id,
        )
        return await self.import_design(
            req,
            DesignImport(
                text=(DEMO_DIR / "stakeout_design.csv").read_text(encoding="utf-8"), filename="stakeout_design.csv"
            ),
            user_id,
        )
