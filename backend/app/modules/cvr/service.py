# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CVR service - business logic for Cost-Value Reconciliation & Cashflow.

Stateless service layer. Handles:
- CVR report + line CRUD, with the single-currency guard and 2dp money quantize
- Report roll-up summary (totals, margin-to-date, forecast margin, percentages)
- Cashflow point CRUD and the cumulative S-curve series
- Interim payment application CRUD (net = gross - retention, always derived)

Money is Decimal end to end: every string that arrives from a schema is parsed
to Decimal, quantized to 2 places, and stored via MoneyType. Nothing here ever
touches a float.
"""

import logging
import uuid
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.core.json_merge import merge_metadata
from app.modules.cvr.compute import cumulative_series, net_of_retention, q2, summarise_lines, to_decimal
from app.modules.cvr.models import (
    CashflowPoint,
    CvrLine,
    CvrReport,
    PaymentApplication,
)
from app.modules.cvr.repository import (
    CashflowRepository,
    LineRepository,
    PaymentApplicationRepository,
    ReportRepository,
)
from app.modules.cvr.schemas import (
    CashflowPointCreate,
    CashflowPointUpdate,
    CashflowSeriesResponse,
    CvrLineCreate,
    CvrLineUpdate,
    CvrReportCreate,
    CvrReportUpdate,
    CvrSummaryResponse,
    PaymentApplicationCreate,
    PaymentApplicationUpdate,
    ProgressClaimOption,
)
from app.modules.cvr.validators import CvrValidationError, assert_single_currency

logger = logging.getLogger(__name__)


def _money(value: Any) -> Decimal:
    """Parse an incoming money value to a 2dp-quantized Decimal."""
    return q2(to_decimal(value))


def _claim_period(claim: Any) -> str | None:
    """The ``YYYY-MM`` a progress claim bills, read from its period end.

    The parsed date wins; the legacy string columns are the fallback for a
    claim written before the dates existed. None when nothing is readable.
    """
    period_to = getattr(claim, "period_to", None)
    if period_to is not None:
        return f"{period_to.year:04d}-{period_to.month:02d}"
    for raw in (getattr(claim, "period_end", None), getattr(claim, "claim_date", None)):
        text = str(raw or "").strip()
        if len(text) >= 7 and text[4] == "-" and text[:4].isdigit() and text[5:7].isdigit():
            if 1 <= int(text[5:7]) <= 12:
                return text[:7]
    return None


class CvrService:
    """Business logic for CVR operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.report_repo = ReportRepository(session)
        self.line_repo = LineRepository(session)
        self.cashflow_repo = CashflowRepository(session)
        self.payapp_repo = PaymentApplicationRepository(session)

    # ── Reports ───────────────────────────────────────────────────────────

    async def create_report(self, data: CvrReportCreate, user_id: str | None = None) -> CvrReport:
        """Create a CVR report. Raises 409 if the project+period already exists."""
        existing = await self.report_repo.get_by_project_period(data.project_id, data.period)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A CVR report for period '{data.period}' already exists in this project",
            )
        report = CvrReport(
            project_id=data.project_id,
            period=data.period,
            title=data.title,
            status=data.status,
            currency=(data.currency or "").strip().upper(),
            notes=data.notes,
            created_by=user_id,
            metadata_=data.metadata,
        )
        report = await self.report_repo.create(report)
        event_bus.publish_detached(
            "cvr.report.created",
            data={
                "project_id": str(data.project_id),
                "report_id": str(report.id),
                "period": data.period,
                "user_id": user_id,
            },
            source_module="cvr",
        )
        logger.info("CVR report created: %s (%s) project=%s", data.period, data.status, data.project_id)
        return report

    async def get_report(self, report_id: uuid.UUID) -> CvrReport:
        """Get a report by ID. Raises 404 if not found."""
        report = await self.report_repo.get_by_id(report_id)
        if report is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CVR report not found")
        return report

    async def list_reports(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        report_status: str | None = None,
    ) -> tuple[list[CvrReport], int]:
        """List CVR reports for a project."""
        return await self.report_repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=report_status,
        )

    async def update_report(self, report_id: uuid.UUID, data: CvrReportUpdate) -> CvrReport:
        """Update a report's fields, emitting a finalize event on draft -> final."""
        report = await self.get_report(report_id)
        old_status = report.status

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "currency" in fields and fields["currency"] is not None:
            fields["currency"] = str(fields["currency"]).strip().upper()
        if "metadata" in fields:
            incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(report, "metadata_", None), incoming) if isinstance(incoming, dict) else incoming
            )
        if not fields:
            return report

        await self.report_repo.update_fields(report_id, **fields)
        report = await self.report_repo.get_by_id(report_id)
        assert report is not None, "Report vanished between update and re-read"

        self._maybe_emit_finalized(report, old_status)
        logger.info("CVR report updated: %s (fields=%s)", report_id, list(fields.keys()))
        return report

    async def finalize_report(self, report_id: uuid.UUID) -> CvrReport:
        """Strike a report 'final'. No-op-safe: 400 if already final."""
        report = await self.get_report(report_id)
        if report.status == "final":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Report is already final",
            )
        await self.report_repo.update_fields(report_id, status="final")
        report = await self.report_repo.get_by_id(report_id)
        assert report is not None, "Report vanished between finalize and re-read"
        self._maybe_emit_finalized(report, "draft")
        return report

    def _maybe_emit_finalized(self, report: CvrReport, old_status: str) -> None:
        """Publish cvr.report.finalized once, only on a real draft -> final flip."""
        if report.status == "final" and old_status != "final":
            event_bus.publish_detached(
                "cvr.report.finalized",
                data={
                    "project_id": str(report.project_id),
                    "report_id": str(report.id),
                    "period": report.period,
                },
                source_module="cvr",
            )

    async def delete_report(self, report_id: uuid.UUID) -> None:
        """Delete a report (its lines cascade)."""
        report = await self.get_report(report_id)
        await self.report_repo.delete(report)

    async def report_line_count(self, report_id: uuid.UUID) -> int:
        """Count the lines on a report (used to populate line_count on responses)."""
        return await self.report_repo.line_count(report_id)

    # ── Lines ─────────────────────────────────────────────────────────────

    async def create_line(self, report_id: uuid.UUID, data: CvrLineCreate) -> CvrLine:
        """Add a cost head to a report, enforcing the single-currency guard."""
        report = await self.get_report(report_id)
        self._reject_if_final(report)
        self._guard_currency(report.currency, data.currency)

        line = CvrLine(
            report_id=report_id,
            cost_code=data.cost_code,
            description=data.description,
            cost_to_date=_money(data.cost_to_date),
            value_to_date=_money(data.value_to_date),
            accruals=_money(data.accruals),
            forecast_cost=_money(data.forecast_cost),
            forecast_value=_money(data.forecast_value),
            sort_order=data.sort_order,
            metadata_=data.metadata,
        )
        return await self.line_repo.create(line)

    async def get_line(self, line_id: uuid.UUID) -> CvrLine:
        """Get a line by ID. Raises 404 if not found."""
        line = await self.line_repo.get_by_id(line_id)
        if line is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="CVR line not found")
        return line

    async def list_lines(self, report_id: uuid.UUID) -> list[CvrLine]:
        """List the lines of a report (verifies the report exists first)."""
        await self.get_report(report_id)
        return await self.line_repo.list_for_report(report_id)

    async def update_line(self, line_id: uuid.UUID, data: CvrLineUpdate) -> CvrLine:
        """Update a line, re-checking the single-currency guard."""
        line = await self.get_line(line_id)
        report = await self.get_report(line.report_id)
        self._reject_if_final(report)
        self._guard_currency(report.currency, data.currency)

        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        # currency is a guard-only field, never a stored column on a line.
        fields.pop("currency", None)
        for money_field in ("cost_to_date", "value_to_date", "accruals", "forecast_cost", "forecast_value"):
            if money_field in fields and fields[money_field] is not None:
                fields[money_field] = _money(fields[money_field])
        if "metadata" in fields:
            incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(line, "metadata_", None), incoming) if isinstance(incoming, dict) else incoming
            )
        if not fields:
            return line

        await self.line_repo.update_fields(line_id, **fields)
        line = await self.line_repo.get_by_id(line_id)
        assert line is not None, "Line vanished between update and re-read"
        return line

    async def delete_line(self, line_id: uuid.UUID) -> None:
        """Delete a line from a report."""
        line = await self.get_line(line_id)
        report = await self.get_report(line.report_id)
        self._reject_if_final(report)
        await self.line_repo.delete(line)

    # ── Summary ───────────────────────────────────────────────────────────

    async def get_report_summary(self, report_id: uuid.UUID) -> CvrSummaryResponse:
        """Roll a report's lines up into totals, margins and advisory warnings."""
        report = await self.get_report(report_id)
        lines = await self.line_repo.list_for_report(report_id)
        totals = summarise_lines(lines)
        return CvrSummaryResponse(
            report_id=report.id,
            project_id=report.project_id,
            period=report.period,
            status=report.status,
            currency=report.currency,
            line_count=len(lines),
            **totals,
        )

    # ── Cashflow ──────────────────────────────────────────────────────────

    async def create_cashflow_point(self, data: CashflowPointCreate) -> CashflowPoint:
        """Create a cashflow point. Raises 409 on a duplicate project+period."""
        existing = await self.cashflow_repo.get_by_project_period(data.project_id, data.period)
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A cashflow point for period '{data.period}' already exists in this project",
            )
        point = CashflowPoint(
            project_id=data.project_id,
            period=data.period,
            cash_in=_money(data.cash_in),
            cash_out=_money(data.cash_out),
            currency=(data.currency or "").strip().upper(),
            label=data.label,
            metadata_=data.metadata,
        )
        return await self.cashflow_repo.create(point)

    async def get_cashflow_point(self, point_id: uuid.UUID) -> CashflowPoint:
        """Get a cashflow point by ID. Raises 404 if not found."""
        point = await self.cashflow_repo.get_by_id(point_id)
        if point is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cashflow point not found")
        return point

    async def list_cashflow_points(self, project_id: uuid.UUID) -> list[CashflowPoint]:
        """List a project's cashflow points, oldest period first."""
        return await self.cashflow_repo.list_for_project(project_id)

    async def update_cashflow_point(self, point_id: uuid.UUID, data: CashflowPointUpdate) -> CashflowPoint:
        """Update a cashflow point."""
        point = await self.get_cashflow_point(point_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if "currency" in fields and fields["currency"] is not None:
            fields["currency"] = str(fields["currency"]).strip().upper()
        for money_field in ("cash_in", "cash_out"):
            if money_field in fields and fields[money_field] is not None:
                fields[money_field] = _money(fields[money_field])
        if "metadata" in fields:
            incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(point, "metadata_", None), incoming) if isinstance(incoming, dict) else incoming
            )
        if not fields:
            return point
        await self.cashflow_repo.update_fields(point_id, **fields)
        point = await self.cashflow_repo.get_by_id(point_id)
        assert point is not None, "Cashflow point vanished between update and re-read"
        return point

    async def delete_cashflow_point(self, point_id: uuid.UUID) -> None:
        """Delete a cashflow point."""
        point = await self.get_cashflow_point(point_id)
        await self.cashflow_repo.delete(point)

    async def get_cashflow_series(self, project_id: uuid.UUID) -> CashflowSeriesResponse:
        """Build the cumulative cash-in / cash-out / net S-curve for a project."""
        points = await self.cashflow_repo.list_for_project(project_id)
        series = cumulative_series(points)
        # The series currency is the first non-blank point currency (all points
        # of a project are expected to share one).
        currency = ""
        for point in points:
            if point.currency:
                currency = point.currency
                break
        return CashflowSeriesResponse(project_id=project_id, currency=currency, **series)

    # ── Payment applications ──────────────────────────────────────────────

    async def _claim_in_project(self, project_id: uuid.UUID, claim_id: uuid.UUID) -> Any:
        """Return the progress claim if it sits under a contract of *project_id*.

        A progress claim carries no project of its own, so the check goes
        through its contract. A missing claim and a claim of another project
        both answer 400: the application is refused rather than linked to a
        claim the caller cannot see.
        """
        from sqlalchemy import select  # noqa: PLC0415

        # Lazy import: cvr stays loadable without the contracts module.
        from app.modules.contracts.models import Contract, ProgressClaim  # noqa: PLC0415

        stmt = (
            select(ProgressClaim)
            .join(Contract, Contract.id == ProgressClaim.contract_id)
            .where(ProgressClaim.id == claim_id, Contract.project_id == project_id)
        )
        claim = (await self.session.execute(stmt)).scalar_one_or_none()
        if claim is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Progress claim not found in this project",
            )
        return claim

    async def list_progress_claims_for_project(self, project_id: uuid.UUID) -> list[ProgressClaimOption]:
        """Every progress claim on the project's contracts, for the picker."""
        from sqlalchemy import select  # noqa: PLC0415

        from app.modules.contracts.models import Contract, ProgressClaim  # noqa: PLC0415

        stmt = (
            select(ProgressClaim, Contract.code)
            .join(Contract, Contract.id == ProgressClaim.contract_id)
            .where(Contract.project_id == project_id)
            .order_by(Contract.code, ProgressClaim.created_at)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            ProgressClaimOption(
                id=claim.id,
                contract_id=claim.contract_id,
                contract_code=code or "",
                claim_number=claim.claim_number or "",
                status=claim.status or "",
                period=_claim_period(claim),
                gross_amount=_money(claim.gross_amount),
                retention_amount=_money(claim.retention_amount),
                net_due=_money(claim.net_due),
                currency=claim.currency or "",
            )
            for claim, code in rows
        ]

    async def create_payment_application(
        self,
        data: PaymentApplicationCreate,
        user_id: str | None = None,
    ) -> PaymentApplication:
        """Create an IPA. ``net_value`` is derived as gross - retention.

        With ``progress_claim_id`` the claim fills every figure the caller did
        not send: its period end as the period, its number, its period gross
        and retention, and its currency. The net is still gross less retention,
        which is the claim's own net due unless the claim also pays back
        released retention.
        """
        sent = data.model_fields_set
        period = data.period
        application_number = data.application_number
        gross_in: Any = data.gross_value
        retention_in: Any = data.retention
        currency = (data.currency or "").strip().upper()
        if data.progress_claim_id is not None:
            claim = await self._claim_in_project(data.project_id, data.progress_claim_id)
            if not period:
                period = _claim_period(claim)
            if "application_number" not in sent:
                application_number = claim.claim_number or None
            if "gross_value" not in sent:
                gross_in = claim.gross_amount
            if "retention" not in sent:
                retention_in = claim.retention_amount
            if not currency:
                currency = (claim.currency or "").strip().upper()
            if not period:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="The progress claim has no period; send one with the application",
                )
        gross = _money(gross_in)
        retention = _money(retention_in)
        application = PaymentApplication(
            project_id=data.project_id,
            period=period,
            application_number=application_number,
            gross_value=gross,
            retention=retention,
            net_value=net_of_retention(gross, retention),
            currency=currency,
            status=data.status,
            notes=data.notes,
            progress_claim_id=data.progress_claim_id,
            created_by=user_id,
            metadata_=data.metadata,
        )
        return await self.payapp_repo.create(application)

    async def get_payment_application(self, app_id: uuid.UUID) -> PaymentApplication:
        """Get a payment application by ID. Raises 404 if not found."""
        application = await self.payapp_repo.get_by_id(app_id)
        if application is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment application not found")
        return application

    async def list_payment_applications(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        app_status: str | None = None,
    ) -> tuple[list[PaymentApplication], int]:
        """List a project's payment applications."""
        return await self.payapp_repo.list_for_project(
            project_id,
            offset=offset,
            limit=limit,
            status=app_status,
        )

    async def update_payment_application(
        self,
        app_id: uuid.UUID,
        data: PaymentApplicationUpdate,
    ) -> PaymentApplication:
        """Update an IPA, always recomputing net_value = gross - retention."""
        application = await self.get_payment_application(app_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)
        if fields.get("progress_claim_id") is not None:
            await self._claim_in_project(application.project_id, fields["progress_claim_id"])
        if "currency" in fields and fields["currency"] is not None:
            fields["currency"] = str(fields["currency"]).strip().upper()
        for money_field in ("gross_value", "retention"):
            if money_field in fields and fields[money_field] is not None:
                fields[money_field] = _money(fields[money_field])
        if "metadata" in fields:
            incoming = fields.pop("metadata")
            fields["metadata_"] = (
                merge_metadata(getattr(application, "metadata_", None), incoming)
                if isinstance(incoming, dict)
                else incoming
            )
        # Recompute net whenever gross or retention moves so the three figures
        # can never drift apart.
        if "gross_value" in fields or "retention" in fields:
            gross = fields.get("gross_value", application.gross_value)
            retention = fields.get("retention", application.retention)
            fields["net_value"] = net_of_retention(gross, retention)
        if not fields:
            return application
        await self.payapp_repo.update_fields(app_id, **fields)
        application = await self.payapp_repo.get_by_id(app_id)
        assert application is not None, "Payment application vanished between update and re-read"
        return application

    async def delete_payment_application(self, app_id: uuid.UUID) -> None:
        """Delete a payment application."""
        application = await self.get_payment_application(app_id)
        await self.payapp_repo.delete(application)

    # ── Guards ────────────────────────────────────────────────────────────

    @staticmethod
    def _guard_currency(report_currency: str, incoming_currency: str | None) -> None:
        """Translate the pure single-currency guard into a 400 on conflict."""
        try:
            assert_single_currency(report_currency, incoming_currency)
        except CvrValidationError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    @staticmethod
    def _reject_if_final(report: CvrReport) -> None:
        """Block line edits on a finalized report (re-open by setting draft)."""
        if report.status == "final":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot modify lines of a finalized CVR report. Set it back to draft first.",
            )
