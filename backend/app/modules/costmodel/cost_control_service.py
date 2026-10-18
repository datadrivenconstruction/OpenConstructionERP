# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost control service: the report, snapshots, manual forecasts, line history.

The report reads two ways from the same figures. Along cost lines it answers
"what will each part of the building cost", along contracts "what will each
contractor cost". Money that sits on no cost line gets its own row on the cost
line axis, so both axes add up to the same commitment.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.i18n import t
from app.core.validation.engine import ValidationContext, rule_registry
from app.modules.costmodel.cost_control import (
    CENT,
    ZERO,
    LineFigures,
    LineInput,
    all_method_outcomes,
    automatic_forecast,
    method_outcome,
    variance,
    variance_pct,
)
from app.modules.costmodel.cost_control_data import ControlData, load_control_data
from app.modules.costmodel.cost_control_schemas import (
    AssignRequest,
    AssignResult,
    CostControlAccount,
    CostControlFinding,
    CostControlReport,
    CostControlRow,
    ForecastOverrideInfo,
    ForecastOverrideRequest,
    LineChangeEvent,
    LineHistory,
    LineHistoryPoint,
    LineMethodChoice,
    MethodOutcomeInfo,
    SnapshotCreateRequest,
    SnapshotDetail,
    SnapshotPage,
    SnapshotSummary,
    UnassignedItem,
    UnassignedPage,
)
from app.modules.costmodel.cost_control_settings import load_choices, load_settings, settings_from_meta
from app.modules.costmodel.models import (
    CostForecastMethodChoice,
    CostForecastOverride,
    CostForecastSnapshot,
    CostLine,
)
from app.modules.costmodel.validators import PAYLOAD_KEY, RULE_SET

AXIS_COST_LINE = "cost_line"
AXIS_CONTRACT = "contract"

KEY_UNASSIGNED = "unassigned"
KEY_LOOSE_CHANGES = "changes_without_contract"
KEY_OTHER = "other"
KEY_REMAINING = "remaining"
# Row key prefix of an account's own amount (the account id follows).
KEY_ALLOWANCE = "allowance:"

#: Saved forecasts a line's history reads, newest first: ten years of months.
HISTORY_SNAPSHOT_LIMIT = 120

#: Totals every report and snapshot carries, in this order.
TOTAL_FIELDS: tuple[str, ...] = (
    "budget",
    "estimate",
    "planned",
    "awarded",
    "changes",
    "committed",
    "certified",
    "paid",
    "forecast",
    "variance",
    "measured",
    "invoiced",
)

#: Row fields a snapshot keeps per cost line.
SNAPSHOT_ROW_FIELDS: tuple[str, ...] = (
    "planned",
    "awarded",
    "changes",
    "committed",
    "certified",
    "paid",
    "forecast",
    "budget",
    "estimate",
    "measured",
    "invoiced",
    "pending_changes",
)

SNAPSHOT_DRAFT = "draft"
SNAPSHOT_FROZEN = "frozen"


def _dec(raw: object) -> Decimal:
    try:
        value = Decimal(str(raw if raw not in (None, "") else "0"))
    except (ArithmeticError, ValueError):
        return ZERO
    return value if value.is_finite() else ZERO


def _override_info(row: CostForecastOverride) -> ForecastOverrideInfo:
    return ForecastOverrideInfo(
        id=row.id,
        amount=_dec(row.amount),
        reason=row.reason,
        document_ref=row.document_ref or "",
        document_id=row.document_id,
        created_by=row.created_by,
        created_at=row.created_at,
        closed_at=row.closed_at,
    )


def _snapshot_summary(row: CostForecastSnapshot) -> SnapshotSummary:
    rules = settings_from_meta(row.project_id, row.meta)
    return SnapshotSummary(
        id=row.id,
        taken_on=row.taken_on,
        stage=row.stage,
        label=row.label or "",
        note=row.note or "",
        currency=row.currency or "",
        totals={k: str(v) for k, v in (row.totals or {}).items()},
        created_by=row.created_by,
        created_at=row.created_at,
        status=row.status if row.status in (SNAPSHOT_DRAFT, SNAPSHOT_FROZEN) else SNAPSHOT_FROZEN,
        frozen_at=row.frozen_at,
        frozen_by=row.frozen_by,
        previous_snapshot_id=row.previous_snapshot_id,
        forecast_method=rules.forecast_method,
        threshold_amount=rules.threshold_amount,
        threshold_pct=rules.threshold_pct,
    )


def _row(
    *,
    key: str,
    kind: str,
    code: str,
    description: str,
    figures: LineFigures,
    account_id: str | None = None,
    status_: str = "",
    pending: Decimal = ZERO,
    override: ForecastOverrideInfo | None = None,
    method_origin: str = "project",
    method_comment: str = "",
) -> CostControlRow:
    forecast = method_outcome(figures)
    auto = automatic_forecast(figures)
    planned = figures.planned
    return CostControlRow(
        key=key,
        kind=kind,  # type: ignore[arg-type]
        code=code,
        description=description,
        account_id=account_id,
        status=status_,
        budget=figures.budget,
        estimate=figures.estimate,
        planned=planned,
        awarded=figures.awarded,
        changes=figures.changes,
        committed=figures.committed,
        certified=figures.certified,
        paid=figures.paid,
        measured=figures.measured,
        invoiced=figures.invoiced,
        pending_changes=pending,
        forecast=forecast.amount,
        forecast_source=forecast.source,
        automatic_forecast=auto.amount,
        automatic_source=auto.source,
        variance=variance(forecast.amount, planned) if planned != ZERO else ZERO,
        variance_pct=variance_pct(forecast.amount, planned),
        override=override,
        forecast_method=forecast.method,
        method_origin="manual" if figures.override is not None else method_origin,  # type: ignore[arg-type]
        method_applied=forecast.applied,
        method_comment=method_comment,
    )


def _totals(rows: list[CostControlRow], data: ControlData) -> dict[str, str]:
    sums = dict.fromkeys(TOTAL_FIELDS, ZERO)
    for r in rows:
        for name in TOTAL_FIELDS:
            if name == "variance":
                continue
            sums[name] += getattr(r, name)
    planned = sums["planned"]
    sums["variance"] = sums["forecast"] - planned if planned != ZERO else ZERO
    out = {name: str(value) for name, value in sums.items()}
    pct = variance_pct(sums["forecast"], planned)
    out["variance_pct"] = "" if pct is None else str(pct)
    out["pending_changes"] = str(data.pending_changes)
    out["pending_count"] = str(data.pending_count)
    out["forecast_with_pending"] = str(sums["forecast"] + data.pending_changes)
    return out


class CostControlService:
    """Cost control for one project at a time."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Reading ───────────────────────────────────────────────────────────

    async def _lines(self, project_id: uuid.UUID) -> list[CostLine]:
        stmt = (
            select(CostLine)
            .where(CostLine.project_id == project_id, CostLine.status != "archived")
            .order_by(CostLine.code)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def _accounts(self, project_id: uuid.UUID) -> list[CostControlAccount]:
        from app.modules.costmodel.repository import ControlAccountRepository

        return [
            CostControlAccount(
                id=str(a.id),
                code=a.code,
                name=a.name,
                title=a.title or "",
                parent_id=str(a.parent_id) if a.parent_id else None,
                level=int(a.level or 1),
                own_amount=_dec(a.own_amount),
            )
            for a in await ControlAccountRepository(self.session).list_for_project(project_id)
        ]

    def _allowance_rows(self, accounts: list[CostControlAccount]) -> list[CostControlRow]:
        """An account's own amount as a row of its own: planned money not broken into cost lines yet.

        Only the plan: nothing is awarded or certified on an allowance, so its
        forecast is the plan until the money moves onto cost lines.
        """
        return [
            _row(
                key=f"{KEY_ALLOWANCE}{a.id}",
                kind="allowance",
                code=a.code,
                description=a.title or a.name,
                figures=LineFigures(budget=a.own_amount),
                account_id=a.id,
            )
            for a in accounts
            if a.own_amount != ZERO
        ]

    async def _open_overrides(self, project_id: uuid.UUID) -> dict[str, CostForecastOverride]:
        stmt = (
            select(CostForecastOverride)
            .where(CostForecastOverride.project_id == project_id, CostForecastOverride.closed_at.is_(None))
            .order_by(CostForecastOverride.created_at)
        )
        out: dict[str, CostForecastOverride] = {}
        for row in (await self.session.execute(stmt)).scalars().all():
            out[str(row.cost_line_id)] = row
        return out

    async def _latest_snapshot(self, project_id: uuid.UUID) -> CostForecastSnapshot | None:
        """The latest frozen snapshot: a draft is not a forecast anyone signed yet."""
        stmt = (
            select(CostForecastSnapshot)
            .where(CostForecastSnapshot.project_id == project_id, CostForecastSnapshot.status == SNAPSHOT_FROZEN)
            .order_by(CostForecastSnapshot.taken_on.desc(), CostForecastSnapshot.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    def _line_figures(
        self,
        line: CostLine,
        data: ControlData,
        overrides: dict[str, CostForecastOverride],
        method: str,
    ) -> LineFigures:
        key = str(line.id)
        committed = data.committed.get(key, ZERO)
        changes = data.changes.get(key, ZERO)
        override = overrides.get(key)
        return LineFigures(
            budget=data.budget.get(key, ZERO),
            estimate=data.estimate.get(key, ZERO),
            awarded=committed - changes,
            changes=changes,
            certified=data.certified.get(key, ZERO),
            paid=data.paid.get(key, ZERO),
            measured=data.measured.get(key, ZERO),
            invoiced=data.invoiced.get(key, ZERO),
            all_final=key in data.final_lines,
            override=_dec(override.amount) if override is not None else None,
            method=method,
            pending=data.pending_by_line.get(key, ZERO),
        )

    async def _cost_line_rows(
        self, project_id: uuid.UUID, data: ControlData
    ) -> tuple[list[CostControlRow], list[LineInput]]:
        overrides = await self._open_overrides(project_id)
        settings = await load_settings(self.session, project_id)
        choices = await load_choices(self.session, project_id)
        rows: list[CostControlRow] = []
        inputs: list[LineInput] = []
        for line in await self._lines(project_id):
            choice = choices.get(str(line.id))
            figures = self._line_figures(
                line, data, overrides, choice.method if choice is not None else settings.forecast_method
            )
            override = overrides.get(str(line.id))
            rows.append(
                _row(
                    key=str(line.id),
                    kind="cost_line",
                    code=line.code,
                    description=line.description or "",
                    figures=figures,
                    account_id=str(line.control_account_id) if line.control_account_id else None,
                    pending=figures.pending,
                    override=_override_info(override) if override is not None else None,
                    method_origin="line" if choice is not None else "project",
                    method_comment=choice.comment if choice is not None else "",
                )
            )
            inputs.append(LineInput(str(line.id), line.code, figures))
        if (
            data.unassigned_committed != ZERO
            or data.unassigned_certified != ZERO
            or data.unassigned_invoiced != ZERO
            or data.unassigned_paid != ZERO
        ):
            rows.append(
                _row(
                    key=KEY_UNASSIGNED,
                    kind="unassigned",
                    code="",
                    description="",
                    figures=LineFigures(
                        awarded=data.unassigned_committed,
                        certified=data.unassigned_certified,
                        paid=data.unassigned_paid,
                        measured=data.unassigned_measured,
                        invoiced=data.unassigned_invoiced,
                    ),
                )
            )
        if data.approved_changes_without_contract != ZERO:
            rows.append(
                _row(
                    key=KEY_LOOSE_CHANGES,
                    kind="changes_without_contract",
                    code="",
                    description=str(data.approved_changes_without_contract_count),
                    figures=LineFigures(changes=data.approved_changes_without_contract),
                )
            )
        return rows, inputs

    def _contract_rows(self, data: ControlData, project_forecast: Decimal) -> list[CostControlRow]:
        """The same money by contract. A last row carries what no contract holds yet.

        Planned money belongs to cost lines, not to contracts, so this axis has
        no plan of its own. Its forecast rows add up to the project forecast
        through the remaining row: work not yet awarded, own forecasts, and the
        difference measured work makes on a line shared by several contracts.
        """
        rows: list[CostControlRow] = []
        for c in data.contracts:
            figures = LineFigures(
                awarded=c.awarded,
                changes=c.changes,
                certified=c.certified,
                paid=c.paid,
                measured=c.measured,
                invoiced=c.invoiced,
                all_final=c.status == "completed",
            )
            rows.append(
                _row(
                    key=c.contract_id,
                    kind="contract",
                    code=c.code,
                    description=c.title,
                    figures=figures,
                    status_=c.status,
                    pending=c.pending_changes,
                )
            )
        # Orders and loose changes are not contracts, but they are cost; keep the axes equal.
        contract_committed = sum((c.awarded + c.changes for c in data.contracts), ZERO)
        spine_committed = sum(data.committed.values(), ZERO) + data.unassigned_committed
        other = spine_committed - contract_committed
        if other != ZERO:
            rows.append(
                _row(
                    key=KEY_OTHER,
                    kind="other",
                    code="",
                    description="",
                    figures=LineFigures(awarded=other),
                )
            )
        if data.approved_changes_without_contract != ZERO:
            rows.append(
                _row(
                    key=KEY_LOOSE_CHANGES,
                    kind="changes_without_contract",
                    code="",
                    description=str(data.approved_changes_without_contract_count),
                    figures=LineFigures(changes=data.approved_changes_without_contract),
                )
            )
        remaining = project_forecast - sum((r.forecast for r in rows), ZERO)
        if remaining != ZERO:
            rows.append(
                _row(
                    key=KEY_REMAINING,
                    kind="remaining",
                    code="",
                    description="",
                    figures=LineFigures(override=remaining),
                )
            )
        return rows

    async def _findings(
        self,
        project_id: uuid.UUID,
        inputs: list[LineInput],
        data: ControlData,
        latest: CostForecastSnapshot | None,
        today: date,
    ) -> list[CostControlFinding]:
        days: int | None = None
        if latest is not None:
            try:
                days = (today - date.fromisoformat(latest.taken_on)).days
            except ValueError:
                days = None
        has_money = any(
            i.figures.committed != ZERO or i.figures.planned != ZERO or i.figures.certified != ZERO for i in inputs
        )
        payload = {
            "lines": inputs,
            "unassigned_committed": data.unassigned_committed,
            "pending_changes": data.pending_changes,
            "pending_count": data.pending_count,
            "days_since_snapshot": days,
            "has_money": has_money,
        }
        from app.core.i18n import get_locale

        context = ValidationContext(
            data={PAYLOAD_KEY: payload}, project_id=str(project_id), metadata={"locale": get_locale()}
        )
        results = []
        for rule in rule_registry.get_rules_for_sets([RULE_SET]):
            if rule.enabled:
                results.extend(await rule.validate(context))
        findings = [
            CostControlFinding(
                rule_id=r.rule_id,
                severity="warning" if r.severity.value == "warning" else "info",
                line_key=r.element_ref,
                code=str(r.details.get("code") or ""),
                amount=_dec(r.details.get("amount")),
                details={k: str(v) for k, v in r.details.items() if k not in ("code", "amount")},
            )
            for r in results
            if not r.passed
        ]
        findings.sort(key=lambda f: (f.severity != "warning", -abs(f.amount), f.code))
        return findings

    async def report(
        self, project_id: uuid.UUID, *, axis: str = AXIS_COST_LINE, today: date | None = None
    ) -> CostControlReport:
        """The cost control report for a project along one axis."""
        today = today or datetime.now(UTC).date()
        data = await load_control_data(self.session, project_id)
        line_rows, inputs = await self._cost_line_rows(project_id, data)
        accounts = await self._accounts(project_id)
        line_rows += self._allowance_rows(accounts)
        # The totals are the project's, the same on both axes: the plan lives on
        # cost lines and on the accounts' own amounts.
        totals = _totals(line_rows, data)
        rows = line_rows if axis == AXIS_COST_LINE else self._contract_rows(data, _dec(totals["forecast"]))
        latest = await self._latest_snapshot(project_id)
        settings = await load_settings(self.session, project_id)
        return CostControlReport(
            project_id=project_id,
            currency=data.currency,
            axis=axis,  # type: ignore[arg-type]
            as_of=today.isoformat(),
            totals=totals,
            rows=rows,
            accounts=accounts if axis == AXIS_COST_LINE else [],
            findings=await self._findings(project_id, inputs, data, latest, today),
            last_snapshot=_snapshot_summary(latest) if latest is not None else None,
            forecast_method=settings.forecast_method,
        )

    # ── Money on no cost line ─────────────────────────────────────────────

    async def unassigned(self, project_id: uuid.UUID, *, offset: int = 0, limit: int = 500) -> UnassignedPage:
        """The lines behind the "not on any cost line" row, the same amounts it adds up."""
        entries = (await load_control_data(self.session, project_id)).unassigned_items
        items = [
            UnassignedItem(
                kind=e.kind,  # type: ignore[arg-type]
                id=uuid.UUID(e.id),
                group_id=uuid.UUID(e.group_id),
                group_code=e.group_code,
                group_title=e.group_title,
                code=e.code,
                description=e.description,
                amount=e.amount,
            )
            for e in entries[offset : offset + limit]
        ]
        return UnassignedPage(items=items, total=len(entries), offset=offset, limit=limit)

    async def assign(self, project_id: uuid.UUID, body: AssignRequest, user_id: str | None = None) -> AssignResult:
        """Put rows on one cost line of the same project.

        Order items keep the cost spine's link, and lose any split they had.
        Every other kind goes through
        :func:`~app.modules.costmodel.inheritance_service.set_vector`, which
        checks the row belongs to the project (another project's row is a 404,
        not a silent move) and asks for ``body.reason`` when the row inherits a
        different cost line.
        """
        from app.modules.costmodel.inheritance import SOURCE_PO_ITEM, drop_splits
        from app.modules.costmodel.inheritance_service import KIND_PO_ITEM, set_vector
        from app.modules.costmodel.service import CostSpineService

        line = await self.session.get(CostLine, body.cost_line_id)
        if line is None or line.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost line not found")
        spine = CostSpineService(self.session)
        for target in body.items:
            if target.kind != KIND_PO_ITEM:
                await set_vector(
                    self.session,
                    project_id,
                    kind=target.kind,
                    target_id=target.id,
                    mode="set",
                    cost_line_id=body.cost_line_id,
                    reason=body.reason,
                    user_id=user_id,
                )
                await self.session.flush()
                continue
            await drop_splits(self.session, SOURCE_PO_ITEM, [target.id])
            # Each link ends with expire_all; reload the line before the next one
            # reads it, or the attribute access would be lazy IO outside the loop.
            await self.session.refresh(line)
            await spine._apply_link(line, target.kind, target.id, link=True)
        return AssignResult(assigned=len(body.items))

    # ── Snapshots ─────────────────────────────────────────────────────────

    @staticmethod
    def snapshot_rows(report: CostControlReport) -> list[dict[str, str]]:
        """The rows a snapshot keeps: every report row with its source, method and figures."""
        return [
            {
                "key": r.key,
                "kind": r.kind,
                "code": r.code,
                "description": r.description,
                "source": r.forecast_source,
                "method": r.forecast_method,
                **{name: str(getattr(r, name).quantize(CENT)) for name in SNAPSHOT_ROW_FIELDS},
            }
            for r in report.rows
        ]

    async def open_draft(self, project_id: uuid.UUID) -> CostForecastSnapshot | None:
        """The project's draft snapshot, if one is open (there is at most one)."""
        stmt = (
            select(CostForecastSnapshot)
            .where(CostForecastSnapshot.project_id == project_id, CostForecastSnapshot.status == SNAPSHOT_DRAFT)
            .order_by(CostForecastSnapshot.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def latest_frozen(self, project_id: uuid.UUID) -> CostForecastSnapshot | None:
        """The latest frozen snapshot: the one a new draft's moves are measured from."""
        return await self._latest_snapshot(project_id)

    async def create_snapshot(
        self, project_id: uuid.UUID, body: SnapshotCreateRequest, user_id: str | None
    ) -> SnapshotSummary:
        """Take today's report as a draft snapshot.

        The draft can be refreshed and documented line by line, then frozen;
        frozen, it is never changed again. One draft per project at a time, so
        a month has one story.
        """
        if await self.open_draft(project_id) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=t("cost_control.errors.draft_open"),
            )
        report = await self.report(project_id)
        settings = await load_settings(self.session, project_id)
        previous = await self._latest_snapshot(project_id)
        snap = CostForecastSnapshot(
            id=uuid.uuid4(),
            project_id=project_id,
            taken_on=report.as_of,
            stage=body.stage,
            label=body.label.strip(),
            note=body.note.strip(),
            currency=report.currency,
            totals=dict(report.totals),
            rows=self.snapshot_rows(report),
            created_by=user_id,
            status=SNAPSHOT_DRAFT,
            previous_snapshot_id=previous.id if previous is not None else None,
            meta=settings.meta(),
        )
        self.session.add(snap)
        await self.session.flush()
        await self.session.refresh(snap)
        return _snapshot_summary(snap)

    async def list_snapshots(self, project_id: uuid.UUID, *, offset: int = 0, limit: int = 500) -> SnapshotPage:
        """Saved forecasts, oldest first, one page of them."""
        where = CostForecastSnapshot.project_id == project_id
        total = int((await self.session.execute(select(func.count()).where(where))).scalar() or 0)
        stmt = (
            select(CostForecastSnapshot)
            .where(where)
            .order_by(CostForecastSnapshot.taken_on, CostForecastSnapshot.created_at)
            .offset(offset)
            .limit(limit)
        )
        items = [_snapshot_summary(s) for s in (await self.session.execute(stmt)).scalars().all()]
        return SnapshotPage(items=items, total=total, offset=offset, limit=limit)

    async def get_snapshot(self, snapshot_id: uuid.UUID) -> tuple[uuid.UUID, SnapshotDetail]:
        """A snapshot with its rows, its lines and their documentation, and what still blocks a draft."""
        from app.modules.costmodel.cost_control_forecast import ForecastDocsService

        snap = await self.session.get(CostForecastSnapshot, snapshot_id)
        if snap is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
        return snap.project_id, await ForecastDocsService(self.session).snapshot_detail(snap)

    async def snapshot_project(self, snapshot_id: uuid.UUID) -> uuid.UUID:
        snap = await self.session.get(CostForecastSnapshot, snapshot_id)
        if snap is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
        return snap.project_id

    async def delete_snapshot(self, snapshot_id: uuid.UUID) -> None:
        """Remove a draft. A frozen snapshot is a record and stays (409)."""
        snap = await self.session.get(CostForecastSnapshot, snapshot_id)
        if snap is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Snapshot not found")
        if snap.status != SNAPSHOT_DRAFT:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=t("cost_control.errors.frozen_no_delete"),
            )
        await self.session.delete(snap)
        await self.session.flush()

    # ── Manual forecasts ──────────────────────────────────────────────────

    async def line_project(self, line_id: uuid.UUID) -> CostLine:
        line = await self.session.get(CostLine, line_id)
        if line is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost line not found")
        return line

    async def _close_open(self, line_id: uuid.UUID, user_id: str | None, now: datetime) -> int:
        stmt = select(CostForecastOverride).where(
            CostForecastOverride.cost_line_id == line_id, CostForecastOverride.closed_at.is_(None)
        )
        closed = 0
        for row in (await self.session.execute(stmt)).scalars().all():
            row.closed_at = now
            row.closed_by = user_id
            closed += 1
        return closed

    async def set_override(
        self, line: CostLine, body: ForecastOverrideRequest, user_id: str | None
    ) -> ForecastOverrideInfo:
        """Record a person's forecast for a line, closing the one it replaces.

        At most one forecast per line is open, enforced by a partial unique
        index. Two saves racing on one line: the second gets a 409 and can retry.
        """
        now = datetime.now(UTC)
        await self._close_open(line.id, user_id, now)
        # A person's amount is the line's method now: a method chosen for it before gives way.
        choice = (
            await self.session.execute(
                select(CostForecastMethodChoice).where(CostForecastMethodChoice.cost_line_id == line.id)
            )
        ).scalar_one_or_none()
        if choice is not None:
            await self.session.delete(choice)
        # Close first, on its own flush, so the index never sees two open rows.
        await self.session.flush()
        row = CostForecastOverride(
            id=uuid.uuid4(),
            project_id=line.project_id,
            cost_line_id=line.id,
            amount=body.amount,
            reason=body.reason,
            document_ref=body.document_ref.strip(),
            document_id=body.document_id,
            created_by=user_id,
        )
        self.session.add(row)
        try:
            async with self.session.begin_nested():
                await self.session.flush()
        except IntegrityError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Someone else just saved a forecast for this line. Reload and try again.",
            ) from exc
        await self.session.refresh(row)
        return _override_info(row)

    async def clear_override(self, line: CostLine, user_id: str | None) -> None:
        """Go back to the automatic forecast. 404 when there is nothing to clear."""
        closed = await self._close_open(line.id, user_id, datetime.now(UTC))
        if closed == 0:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No manual forecast on this line")
        await self.session.flush()

    # ── History ───────────────────────────────────────────────────────────

    async def line_history(self, line: CostLine) -> LineHistory:
        """Snapshots, approved changes and manual forecasts for one line, oldest first."""
        from app.modules.contracts.models import Contract, ContractLine, SovAdjustment
        from app.modules.costmodel.repository import _CONTRACT_UNBOUND_STATUSES, CostSpineRepository, _amount_in_base

        report = await self.report(line.project_id)
        current = next((r for r in report.rows if r.key == str(line.id)), None)
        if current is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cost line not found")

        # The latest ten years of monthly forecasts are plenty for one line's story.
        snaps = (
            (
                await self.session.execute(
                    select(CostForecastSnapshot)
                    .where(
                        CostForecastSnapshot.project_id == line.project_id,
                        CostForecastSnapshot.status == SNAPSHOT_FROZEN,
                    )
                    .order_by(CostForecastSnapshot.taken_on.desc(), CostForecastSnapshot.created_at.desc())
                    .limit(HISTORY_SNAPSHOT_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        points: list[LineHistoryPoint] = []
        for s in reversed(snaps):
            entry = next(
                (r for r in (s.rows or []) if isinstance(r, dict) and r.get("key") == str(line.id)),
                None,
            )
            if entry is None:
                continue
            points.append(
                LineHistoryPoint(
                    snapshot_id=s.id,
                    taken_on=s.taken_on,
                    stage=s.stage,
                    label=s.label or "",
                    forecast=_dec(entry.get("forecast")),
                    forecast_source=str(entry.get("source") or "none"),
                    committed=_dec(entry.get("committed")),
                    certified=_dec(entry.get("certified")),
                )
            )

        base, fx = await CostSpineRepository(self.session)._fx_context(line.project_id)
        adj_rows = (
            await self.session.execute(
                select(
                    SovAdjustment.approved_on,
                    SovAdjustment.source_kind,
                    SovAdjustment.source_code,
                    SovAdjustment.delta_value,
                    SovAdjustment.currency,
                    Contract.code,
                )
                .join(ContractLine, ContractLine.id == SovAdjustment.contract_line_id)
                .join(Contract, Contract.id == SovAdjustment.contract_id)
                # Only the cost side, and only contracts that bind: the same set the totals use.
                .where(
                    ContractLine.cost_line_id == line.id,
                    Contract.counterparty_type == "subcontractor",
                    Contract.status.not_in(_CONTRACT_UNBOUND_STATUSES),
                )
                .order_by(SovAdjustment.approved_on, SovAdjustment.created_at)
            )
        ).all()
        changes = [
            LineChangeEvent(
                approved_on=approved_on.isoformat() if approved_on else None,
                source_kind=kind or "",
                source_code=code or "",
                contract_code=contract_code or "",
                amount=_amount_in_base(str(delta), (ccy or "").strip().upper(), base, fx),
            )
            for approved_on, kind, code, delta, ccy, contract_code in adj_rows
        ]

        override_rows = (
            (
                await self.session.execute(
                    select(CostForecastOverride)
                    .where(CostForecastOverride.cost_line_id == line.id)
                    .order_by(CostForecastOverride.created_at)
                )
            )
            .scalars()
            .all()
        )
        settings = await load_settings(self.session, line.project_id)
        choice = (await load_choices(self.session, line.project_id)).get(str(line.id))
        figures = LineFigures(
            budget=current.budget,
            estimate=current.estimate,
            awarded=current.awarded,
            changes=current.changes,
            certified=current.certified,
            paid=current.paid,
            measured=current.measured,
            invoiced=current.invoiced,
            all_final=current.forecast_source == "final" or current.automatic_source == "final",
            override=current.override.amount if current.override is not None else None,
            pending=current.pending_changes,
        )
        methods = [
            MethodOutcomeInfo(
                method=name,  # type: ignore[arg-type]
                amount=outcome.amount,
                source=outcome.source,
                applied=outcome.applied,
                progress=outcome.progress,
                cpi=outcome.cpi,
                earned=outcome.earned,
                actual=outcome.actual,
            )
            for name, outcome in all_method_outcomes(figures).items()
        ]
        return LineHistory(
            cost_line_id=line.id,
            code=line.code,
            description=line.description or "",
            currency=report.currency,
            current=current,
            snapshots=points,
            changes=changes,
            overrides=[_override_info(o) for o in override_rows],
            project_method=settings.forecast_method,
            method_choice=(
                LineMethodChoice(
                    cost_line_id=line.id,
                    method=choice.method,  # type: ignore[arg-type]
                    comment=choice.comment or "",
                    updated_by=choice.updated_by or choice.created_by,
                    updated_at=choice.updated_at,
                )
                if choice is not None
                else None
            ),
            methods=methods,
        )
