# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Forecast method, snapshot documentation and snapshot comparison.

The report (:mod:`app.modules.costmodel.cost_control_service`) answers what
each line will cost. This service answers how that was worked out and why it
moved:

* the project's forecast method and evidence threshold, and the method a
  single line was set to with its comment;
* the draft snapshot: refreshed from today's figures, documented line by line
  (comment plus evidence), and frozen once every move above the threshold is
  documented (rule V20). A frozen snapshot is never changed again;
* the comparison matrix (several snapshots side by side) and the delta ladder
  (from one total to another, line by line, with the cause and the evidence
  of each step);
* the forecast panel: methods in force and the findings of V19, V20 and V22.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import get_locale, t
from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.costmodel.cost_control import ZERO
from app.modules.costmodel.cost_control_schemas import (
    ComparisonColumn,
    ComparisonRow,
    CostControlReport,
    CostControlSettingsInfo,
    CostControlSettingsRequest,
    DeltaLadder,
    EvidenceItem,
    ForecastFinding,
    ForecastPanel,
    LadderStepInfo,
    LineMethodChoice,
    LineMethodRequest,
    SnapshotDetail,
    SnapshotLine,
    SnapshotMatrix,
    SnapshotNoteRequest,
    SnapshotSummary,
)
from app.modules.costmodel.cost_control_service import (
    SNAPSHOT_DRAFT,
    SNAPSHOT_FROZEN,
    CostControlService,
    _snapshot_summary,
)
from app.modules.costmodel.cost_control_settings import (
    ForecastSettings,
    load_choices,
    load_settings,
    settings_from_meta,
    settings_row,
)
from app.modules.costmodel.forecast_docs import (
    PCT,
    comparison_matrix,
    delta_ladder,
    money,
    needs_evidence,
    note_complete,
)
from app.modules.costmodel.forecast_rules import PAYLOAD_KEY, RULE_NUMBERS, RULE_SET
from app.modules.costmodel.models import (
    CostControlSettings,
    CostForecastMethodChoice,
    CostForecastSnapshot,
    CostForecastSnapshotNote,
    CostLine,
    FrozenSnapshotError,
)

#: Snapshots the matrix compares when the caller names none: the latest frozen ones.
MATRIX_DEFAULT_SNAPSHOTS = 5
#: The most states one matrix holds.
MATRIX_MAX_COLUMNS = 12
#: The live state's id in a comparison request.
LIVE = "live"


def _settings_info(settings: ForecastSettings) -> CostControlSettingsInfo:
    return CostControlSettingsInfo(
        project_id=settings.project_id,
        forecast_method=settings.forecast_method,  # type: ignore[arg-type]
        evidence_threshold_amount=settings.threshold_amount,
        evidence_threshold_pct=settings.threshold_pct,
        is_default=settings.is_default,
        updated_by=settings.updated_by,
        updated_at=settings.updated_at,
    )


def _evidence(raw: object) -> list[EvidenceItem]:
    out: list[EvidenceItem] = []
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            out.append(EvidenceItem.model_validate(item))
        except ValueError:
            continue
    return out


def _frozen_conflict() -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=t("cost_control.errors.snapshot_frozen"))


class ForecastDocsService:
    """Forecast method, documentation and comparison for one project at a time."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.control = CostControlService(session)

    # ── Settings ──────────────────────────────────────────────────────────

    async def get_settings(self, project_id: uuid.UUID) -> CostControlSettingsInfo:
        return _settings_info(await load_settings(self.session, project_id))

    async def put_settings(
        self, project_id: uuid.UUID, body: CostControlSettingsRequest, user_id: str | None
    ) -> CostControlSettingsInfo:
        """Store the project's forecast method and evidence threshold (one row per project)."""
        row = await settings_row(self.session, project_id)
        if row is None:
            row = CostControlSettings(id=uuid.uuid4(), project_id=project_id)
            self.session.add(row)
        row.forecast_method = body.forecast_method
        row.evidence_threshold_amount = body.evidence_threshold_amount
        row.evidence_threshold_pct = body.evidence_threshold_pct
        row.updated_by = user_id
        await self.session.flush()
        await self.session.refresh(row)
        return _settings_info(await load_settings(self.session, project_id))

    # ── A line's method ───────────────────────────────────────────────────

    async def _choice(self, line_id: uuid.UUID) -> CostForecastMethodChoice | None:
        stmt = select(CostForecastMethodChoice).where(CostForecastMethodChoice.cost_line_id == line_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def set_line_method(self, line: CostLine, body: LineMethodRequest, user_id: str | None) -> LineMethodChoice:
        """Read one line with its own method. An open manual amount on it is closed and kept in the history."""
        await self.control._close_open(line.id, user_id, datetime.now(UTC))
        row = await self._choice(line.id)
        if row is None:
            row = CostForecastMethodChoice(
                id=uuid.uuid4(), project_id=line.project_id, cost_line_id=line.id, created_by=user_id
            )
            self.session.add(row)
        row.method = body.method
        row.comment = body.comment
        row.updated_by = user_id
        await self.session.flush()
        await self.session.refresh(row)
        return LineMethodChoice(
            cost_line_id=line.id,
            method=row.method,  # type: ignore[arg-type]
            comment=row.comment or "",
            updated_by=row.updated_by,
            updated_at=row.updated_at,
        )

    async def clear_line_method(self, line: CostLine) -> None:
        """Back to the project's method. 404 when the line follows it already."""
        row = await self._choice(line.id)
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=t("cost_control.errors.no_line_method"))
        await self.session.delete(row)
        await self.session.flush()

    # ── Rules V19, V20, V22 ───────────────────────────────────────────────

    @staticmethod
    def _line_payload(report: CostControlReport) -> list[dict[str, Any]]:
        out = []
        for r in report.rows:
            if r.kind != "cost_line":
                continue
            override = r.override
            out.append(
                {
                    "key": r.key,
                    "code": r.code,
                    "forecast": str(r.forecast),
                    "committed": str(r.committed),
                    "pending": str(r.pending_changes),
                    "method": r.forecast_method,
                    "method_origin": r.method_origin,
                    "method_comment": r.method_comment,
                    "manual": override is not None,
                    "manual_document": bool(
                        override is not None and (override.document_id or (override.document_ref or "").strip())
                    ),
                }
            )
        return out

    @staticmethod
    def _snapshot_payload(snap: CostForecastSnapshot, lines: list[SnapshotLine]) -> dict[str, Any]:
        rules = settings_from_meta(snap.project_id, snap.meta)
        return {
            "id": str(snap.id),
            "status": snap.status,
            # The first snapshot of a project is the baseline: there is no earlier figure to explain a move from.
            "baseline": snap.previous_snapshot_id is None,
            "threshold_amount": str(rules.threshold_amount),
            "threshold_pct": "" if rules.threshold_pct is None else str(rules.threshold_pct),
            "lines": [
                {
                    "key": line.key,
                    "code": line.code or line.description,
                    "previous": "" if line.previous is None else str(line.previous),
                    "current": str(line.forecast),
                    "comment": line.comment,
                    "evidence": [e.model_dump(mode="json") for e in line.evidence],
                }
                for line in lines
            ],
        }

    async def _run_rules(
        self, payload: dict[str, Any], *, project_id: uuid.UUID, locale: str, only: set[str] | None = None
    ) -> list[ForecastFinding]:
        context = ValidationContext(
            data={PAYLOAD_KEY: payload}, project_id=str(project_id), metadata={"locale": locale}
        )
        found: list[ForecastFinding] = []
        for rule in rule_registry.get_rules_for_sets([RULE_SET]):
            if not rule.enabled or (only is not None and rule.rule_id not in only):
                continue
            for r in await rule.validate(context):
                if r.passed:
                    continue
                found.append(
                    ForecastFinding(
                        rule_id=r.rule_id,
                        rule_number=RULE_NUMBERS.get(r.rule_id, ""),
                        severity=r.severity.value,  # type: ignore[arg-type]
                        message=r.message,
                        suggestion=r.suggestion or "",
                        element_ref=r.element_ref,
                        details=dict(r.details or {}),
                    )
                )
        return found

    # ── The forecast panel ────────────────────────────────────────────────

    async def panel(self, project_id: uuid.UUID, *, locale: str | None = None) -> ForecastPanel:
        """Methods in force across the project and the findings of V19, V20 and V22."""
        locale = locale or get_locale()
        report = await self.control.report(project_id)
        settings = await load_settings(self.session, project_id)
        counts: dict[str, int] = {}
        fallback = choices = manual = 0
        for r in report.rows:
            if r.kind != "cost_line":
                continue
            counts[r.forecast_method] = counts.get(r.forecast_method, 0) + 1
            fallback += 0 if r.method_applied else 1
            choices += 1 if r.method_origin == "line" else 0
            manual += 1 if r.method_origin == "manual" else 0
        draft = await self.control.open_draft(project_id)
        snapshot_payload = None
        if draft is not None:
            snapshot_payload = self._snapshot_payload(draft, await self._lines(draft))
        payload = {
            "currency": report.currency,
            "project_method": settings.forecast_method,
            "lines": self._line_payload(report),
            "snapshot": snapshot_payload,
        }
        return ForecastPanel(
            project_id=project_id,
            currency=report.currency,
            settings=_settings_info(settings),
            method_counts=counts,
            fallback_lines=fallback,
            line_choices=choices,
            manual_lines=manual,
            open_draft=_snapshot_summary(draft) if draft is not None else None,
            findings=await self._run_rules(payload, project_id=project_id, locale=locale),
        )

    # ── Snapshot lines and their notes ────────────────────────────────────

    async def _notes(self, snapshot_id: uuid.UUID) -> dict[str, CostForecastSnapshotNote]:
        stmt = select(CostForecastSnapshotNote).where(CostForecastSnapshotNote.snapshot_id == snapshot_id)
        return {n.row_key: n for n in (await self.session.execute(stmt)).scalars().all()}

    async def _previous(self, snap: CostForecastSnapshot) -> CostForecastSnapshot | None:
        if snap.previous_snapshot_id is None:
            return None
        return await self.session.get(CostForecastSnapshot, snap.previous_snapshot_id)

    @staticmethod
    def _rows(snap: CostForecastSnapshot | None) -> list[dict[str, Any]]:
        if snap is None:
            return []
        return [r for r in (snap.rows or []) if isinstance(r, dict)]

    async def _lines(self, snap: CostForecastSnapshot) -> list[SnapshotLine]:
        """Every row of the snapshot with its move since the previous frozen one and its note."""
        previous = await self._previous(snap)
        before = {str(r.get("key")): r for r in self._rows(previous)}
        notes = await self._notes(snap.id)
        threshold = settings_from_meta(snap.project_id, snap.meta).threshold
        out: list[SnapshotLine] = []
        for row in self._rows(snap):
            key = str(row.get("key") or "")
            current = money(row.get("forecast"))
            prior = before.get(key)
            prev_amount = money(prior.get("forecast")) if prior is not None else None
            delta = current - (prev_amount or ZERO)
            pct = None
            if prev_amount not in (None, ZERO):
                assert prev_amount is not None
                pct = (delta / prev_amount * Decimal("100")).quantize(PCT)
            note = notes.get(key)
            evidence = _evidence(note.evidence) if note is not None else []
            comment = note.comment if note is not None else ""
            out.append(
                SnapshotLine(
                    key=key,
                    kind=str(row.get("kind") or ""),
                    code=str(row.get("code") or ""),
                    description=str(row.get("description") or ""),
                    source=str(row.get("source") or "none"),
                    method=str(row.get("method") or "best_available"),
                    forecast=current,
                    committed=money(row.get("committed")),
                    previous=prev_amount,
                    delta=delta,
                    delta_pct=pct,
                    needs_evidence=previous is not None and needs_evidence(prev_amount, current, threshold),
                    documented=note_complete(comment, [e.model_dump() for e in evidence]),
                    comment=comment or "",
                    evidence=evidence,
                    note_updated_at=note.updated_at if note is not None else None,
                )
            )
        return out

    async def snapshot_detail(self, snap: CostForecastSnapshot, *, locale: str | None = None) -> SnapshotDetail:
        """A snapshot with its lines and, for a draft, the moves rule V20 still points at."""
        lines = await self._lines(snap)
        previous = await self._previous(snap)
        findings: list[ForecastFinding] = []
        if snap.status == SNAPSHOT_DRAFT:
            findings = await self._run_rules(
                {"currency": snap.currency or "", "snapshot": self._snapshot_payload(snap, lines)},
                project_id=snap.project_id,
                locale=locale or get_locale(),
                only={"cost_forecast.move_without_evidence"},
            )
        return SnapshotDetail(
            **_snapshot_summary(snap).model_dump(),
            rows=[{k: str(v) for k, v in r.items()} for r in self._rows(snap)],
            lines=lines,
            previous=_snapshot_summary(previous) if previous is not None else None,
            findings=findings,
        )

    async def snapshot(self, snapshot_id: uuid.UUID) -> CostForecastSnapshot:
        snap = await self.session.get(CostForecastSnapshot, snapshot_id)
        if snap is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=t("cost_control.errors.snapshot_missing"))
        return snap

    async def _check_document(self, project_id: uuid.UUID, document_id: uuid.UUID) -> None:
        from app.modules.documents.models import Document

        doc = await self.session.get(Document, document_id)
        if doc is None or doc.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=t("cost_control.errors.document_missing")
            )

    async def put_note(
        self, snap: CostForecastSnapshot, row_key: str, body: SnapshotNoteRequest, user_id: str | None
    ) -> SnapshotLine:
        """Write the comment and evidence behind one line of a draft. A frozen snapshot answers 409."""
        if snap.status != SNAPSHOT_DRAFT:
            raise _frozen_conflict()
        if row_key not in {str(r.get("key")) for r in self._rows(snap)}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=t("cost_control.errors.line_missing"))
        for item in body.evidence:
            if item.document_id is not None:
                await self._check_document(snap.project_id, item.document_id)
        evidence = [e.model_dump(mode="json") for e in body.evidence if e.ref or e.document_id]
        note = (await self._notes(snap.id)).get(row_key)
        try:
            if note is None:
                note = CostForecastSnapshotNote(id=uuid.uuid4(), snapshot_id=snap.id, row_key=row_key)
                self.session.add(note)
            note.comment = body.comment.strip()
            note.evidence = evidence
            note.updated_by = user_id
            await self.session.flush()
        except FrozenSnapshotError as exc:
            raise _frozen_conflict() from exc
        return next(line for line in await self._lines(snap) if line.key == row_key)

    async def refresh(self, snap: CostForecastSnapshot) -> SnapshotSummary:
        """Take today's figures into a draft. Notes stay on their lines."""
        if snap.status != SNAPSHOT_DRAFT:
            raise _frozen_conflict()
        report = await self.control.report(snap.project_id)
        settings = await load_settings(self.session, snap.project_id)
        previous = await self.control.latest_frozen(snap.project_id)
        try:
            snap.taken_on = report.as_of
            snap.currency = report.currency
            snap.totals = dict(report.totals)
            snap.rows = CostControlService.snapshot_rows(report)
            snap.previous_snapshot_id = previous.id if previous is not None else None
            snap.meta = settings.meta()
            await self.session.flush()
        except FrozenSnapshotError as exc:
            raise _frozen_conflict() from exc
        await self.session.refresh(snap)
        return _snapshot_summary(snap)

    async def freeze(
        self, snap: CostForecastSnapshot, user_id: str | None, *, locale: str | None = None
    ) -> SnapshotSummary:
        """Freeze a draft once every move above the threshold has a comment and evidence (rule V20).

        Refused with 422 and the lines still open; 409 when it is frozen already.
        """
        if snap.status != SNAPSHOT_DRAFT:
            raise _frozen_conflict()
        previous = await self.control.latest_frozen(snap.project_id)
        if previous is not None and previous.id != snap.previous_snapshot_id:
            snap.previous_snapshot_id = previous.id
            await self.session.flush()
        detail = await self.snapshot_detail(snap, locale=locale)
        if detail.findings:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "message": t("cost_control.errors.freeze_refused", count=len(detail.findings)),
                    "findings": [f.model_dump(mode="json") for f in detail.findings],
                },
            )
        snap.status = SNAPSHOT_FROZEN
        snap.frozen_at = datetime.now(UTC)
        snap.frozen_by = user_id
        await self.session.flush()
        await self.session.refresh(snap)
        return _snapshot_summary(snap)

    # ── Comparison ────────────────────────────────────────────────────────

    async def _snapshots_by_id(self, project_id: uuid.UUID, ids: list[uuid.UUID]) -> list[CostForecastSnapshot]:
        if not ids:
            return []
        stmt = select(CostForecastSnapshot).where(
            CostForecastSnapshot.project_id == project_id, CostForecastSnapshot.id.in_(ids)
        )
        found = {s.id: s for s in (await self.session.execute(stmt)).scalars().all()}
        missing = [i for i in ids if i not in found]
        if missing:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=t("cost_control.errors.snapshot_missing"))
        return sorted(found.values(), key=lambda s: (s.taken_on, s.created_at or datetime.min.replace(tzinfo=UTC)))

    async def _latest_frozen(self, project_id: uuid.UUID, limit: int) -> list[CostForecastSnapshot]:
        stmt = (
            select(CostForecastSnapshot)
            .where(CostForecastSnapshot.project_id == project_id, CostForecastSnapshot.status == SNAPSHOT_FROZEN)
            .order_by(CostForecastSnapshot.taken_on.desc(), CostForecastSnapshot.created_at.desc())
            .limit(limit)
        )
        return list(reversed((await self.session.execute(stmt)).scalars().all()))

    @staticmethod
    def _column(snap: CostForecastSnapshot | None, rows: list[dict[str, Any]], as_of: str = "") -> ComparisonColumn:
        total = sum((money(r.get("forecast")) for r in rows), ZERO)
        if snap is None:
            return ComparisonColumn(id=None, taken_on=as_of, status=LIVE, total=total)
        return ComparisonColumn(
            id=snap.id,
            taken_on=snap.taken_on,
            stage=snap.stage,
            label=snap.label or "",
            status=snap.status if snap.status in (SNAPSHOT_DRAFT, SNAPSHOT_FROZEN) else SNAPSHOT_FROZEN,  # type: ignore[arg-type]
            total=total,
        )

    async def _live(self, project_id: uuid.UUID) -> tuple[CostControlReport, list[dict[str, Any]]]:
        report = await self.control.report(project_id)
        return report, CostControlService.snapshot_rows(report)

    async def matrix(
        self, project_id: uuid.UUID, ids: list[uuid.UUID] | None = None, *, include_live: bool = True
    ) -> SnapshotMatrix:
        """Snapshots side by side, oldest first, today's figures last when asked for."""
        if ids:
            snaps = await self._snapshots_by_id(project_id, ids[:MATRIX_MAX_COLUMNS])
        else:
            snaps = await self._latest_frozen(project_id, MATRIX_DEFAULT_SNAPSHOTS)
        states: list[tuple[CostForecastSnapshot | None, list[dict[str, Any]]]] = [(s, self._rows(s)) for s in snaps]
        currency = snaps[-1].currency if snaps else ""
        as_of = ""
        if include_live:
            report, rows = await self._live(project_id)
            states.append((None, rows))
            currency = report.currency
            as_of = report.as_of
        _totals, rows_out = comparison_matrix([rows for _s, rows in states])
        return SnapshotMatrix(
            project_id=project_id,
            currency=currency or "",
            columns=[self._column(s, rows, as_of) for s, rows in states],
            rows=[
                ComparisonRow(
                    key=r.key,
                    code=r.code,
                    description=r.description,
                    kind=r.kind,
                    values=r.values,
                    delta=r.delta,
                    delta_pct=r.delta_pct,
                )
                for r in rows_out
            ],
        )

    async def ladder(
        self,
        project_id: uuid.UUID,
        *,
        start: str | None = None,
        end: str | None = None,
        min_step: Decimal = ZERO,
        limit: int | None = 25,
    ) -> DeltaLadder:
        """From one state's total to another's, line by line.

        ``start`` defaults to the latest frozen snapshot, ``end`` to today's
        figures (``live``). Notes are read from the end snapshot; for today's
        figures, from the open draft.
        """

        def parse(raw: str) -> uuid.UUID:
            try:
                return uuid.UUID(raw)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=t("cost_control.errors.snapshot_missing")
                ) from exc

        if start in (None, ""):
            latest = await self.control.latest_frozen(project_id)
            if latest is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail=t("cost_control.errors.no_frozen_snapshot")
                )
            start_snap = latest
        else:
            start_snap = (await self._snapshots_by_id(project_id, [parse(start)]))[0]
        currency = start_snap.currency or ""
        if end in (None, "", LIVE):
            report, end_rows = await self._live(project_id)
            end_column = self._column(None, end_rows, report.as_of)
            currency = report.currency
            notes_from = await self.control.open_draft(project_id)
        else:
            end_snap = (await self._snapshots_by_id(project_id, [parse(end)]))[0]
            end_rows = self._rows(end_snap)
            end_column = self._column(end_snap, end_rows)
            notes_from = end_snap
        notes: dict[str, tuple[str, list[dict[str, Any]]]] = {}
        if notes_from is not None:
            for key, note in (await self._notes(notes_from.id)).items():
                notes[key] = (note.comment or "", [e.model_dump(mode="json") for e in _evidence(note.evidence)])
        start_rows = self._rows(start_snap)
        out = delta_ladder(start_rows, end_rows, notes, min_step=min_step, limit=limit)
        return DeltaLadder(
            project_id=project_id,
            currency=currency,
            start_column=self._column(start_snap, start_rows),
            end_column=end_column,
            start=out.start,
            end=out.end,
            steps=[
                LadderStepInfo(
                    key=s.key,
                    code=s.code,
                    description=s.description,
                    kind=s.kind,
                    before=s.before,
                    after=s.after,
                    delta=s.delta,
                    cause=s.cause,  # type: ignore[arg-type]
                    source_before=s.source_before,
                    source_after=s.source_after,
                    method_before=s.method_before,
                    method_after=s.method_after,
                    comment=s.comment,
                    evidence=_evidence(s.evidence),
                )
                for s in out.steps
            ],
            other=out.other,
            other_count=out.other_count,
        )

    async def line_choices(self, project_id: uuid.UUID) -> dict[str, CostForecastMethodChoice]:
        return await load_choices(self.session, project_id)
