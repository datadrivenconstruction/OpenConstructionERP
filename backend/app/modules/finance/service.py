"""Finance service — business logic for invoicing, payments, budgets, and EVM.

Stateless service layer.
"""

import logging
import uuid
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus

from app.modules.finance.models import (
    EVMSnapshot,
    Invoice,
    InvoiceLineItem,
    Payment,
    ProjectBudget,
)
from app.modules.finance.repository import (
    BudgetRepository,
    EVMSnapshotRepository,
    InvoiceLineItemRepository,
    InvoiceRepository,
    PaymentRepository,
)
from app.modules.finance.schemas import (
    BudgetCreate,
    BudgetUpdate,
    EVMSnapshotCreate,
    InvoiceCreate,
    InvoiceUpdate,
    PaymentCreate,
)

logger = logging.getLogger(__name__)

# ── Allowed status transitions ──────────────────────────────────────────────

_INVOICE_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"pending", "approved", "cancelled"},
    "pending": {"approved", "cancelled", "draft"},
    "approved": {"paid", "cancelled"},
    "paid": set(),  # terminal
    "cancelled": {"draft"},  # allow re-opening
}

_VALID_INVOICE_STATUSES = set(_INVOICE_STATUS_TRANSITIONS.keys())


def _parse_decimal(value: str, field_name: str = "value") -> Decimal:
    """Parse a string to Decimal, raising a clear error on failure."""
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid numeric value for {field_name}: {value!r}",
        ) from exc


def _compute_invoice_total(subtotal: str, tax: str) -> str:
    """Compute amount_total = amount_subtotal + tax_amount."""
    s = _parse_decimal(subtotal, "amount_subtotal")
    t = _parse_decimal(tax, "tax_amount")
    return str(s + t)


class FinanceService:
    """Business logic for finance operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.invoices = InvoiceRepository(session)
        self.line_items = InvoiceLineItemRepository(session)
        self.payments_repo = PaymentRepository(session)
        self.budgets = BudgetRepository(session)
        self.evm = EVMSnapshotRepository(session)

    # ── Invoices ─────────────────────────────────────────────────────────────

    async def create_invoice(
        self,
        data: InvoiceCreate,
        user_id: str | None = None,
    ) -> Invoice:
        """Create a new invoice with optional line items.

        Automatically computes amount_total = amount_subtotal + tax_amount.
        """
        # Validate initial status
        if data.status not in _VALID_INVOICE_STATUSES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Invalid invoice status: '{data.status}'. "
                    f"Allowed: {', '.join(sorted(_VALID_INVOICE_STATUSES))}"
                ),
            )

        # Auto-generate invoice number if not provided
        invoice_number = data.invoice_number
        if not invoice_number:
            invoice_number = await self.invoices.next_invoice_number(
                data.project_id, data.invoice_direction
            )

        # Server-side total computation: always override amount_total
        computed_total = _compute_invoice_total(data.amount_subtotal, data.tax_amount)

        invoice = Invoice(
            project_id=data.project_id,
            contact_id=data.contact_id,
            invoice_direction=data.invoice_direction,
            invoice_number=invoice_number,
            invoice_date=data.invoice_date,
            due_date=data.due_date,
            currency_code=data.currency_code,
            amount_subtotal=data.amount_subtotal,
            tax_amount=data.tax_amount,
            retention_amount=data.retention_amount,
            amount_total=computed_total,
            tax_config_id=data.tax_config_id,
            status=data.status,
            payment_terms_days=data.payment_terms_days,
            notes=data.notes,
            created_by=uuid.UUID(user_id) if user_id else None,
            metadata_=data.metadata,
        )
        invoice = await self.invoices.create(invoice)

        # Create line items
        for idx, item_data in enumerate(data.line_items):
            item = InvoiceLineItem(
                invoice_id=invoice.id,
                description=item_data.description,
                quantity=item_data.quantity,
                unit=item_data.unit,
                unit_rate=item_data.unit_rate,
                amount=item_data.amount,
                wbs_id=item_data.wbs_id,
                cost_category=item_data.cost_category,
                sort_order=item_data.sort_order if item_data.sort_order else idx,
            )
            await self.line_items.create(item)

        # Re-fetch invoice with relationships (line_items, payments) eager-loaded
        refreshed = await self.invoices.get(invoice.id)
        if refreshed is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to re-fetch created invoice",
            )
        logger.info("Invoice created: %s (%s)", refreshed.invoice_number, refreshed.invoice_direction)
        return refreshed

    async def get_invoice(self, invoice_id: uuid.UUID) -> Invoice:
        """Get invoice by ID. Raises 404 if not found."""
        invoice = await self.invoices.get(invoice_id)
        if invoice is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invoice not found",
            )
        return invoice

    async def list_invoices(
        self,
        *,
        project_id: uuid.UUID | None = None,
        direction: str | None = None,
        invoice_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Invoice], int]:
        """List invoices with filters."""
        return await self.invoices.list(
            project_id=project_id,
            direction=direction,
            status=invoice_status,
            limit=limit,
            offset=offset,
        )

    async def update_invoice(
        self,
        invoice_id: uuid.UUID,
        data: InvoiceUpdate,
    ) -> Invoice:
        """Update invoice fields and optionally replace line items.

        Validates status transitions and recomputes amount_total when
        subtotal or tax are changed.
        """
        invoice = await self.get_invoice(invoice_id)  # 404 check

        fields = data.model_dump(exclude_unset=True, exclude={"line_items"})
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        # Validate status transition if status is being changed
        if "status" in fields and fields["status"] is not None:
            new_status = fields["status"]
            if new_status not in _VALID_INVOICE_STATUSES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Invalid invoice status: '{new_status}'. "
                        f"Allowed: {', '.join(sorted(_VALID_INVOICE_STATUSES))}"
                    ),
                )
            allowed = _INVOICE_STATUS_TRANSITIONS.get(invoice.status, set())
            if new_status != invoice.status and new_status not in allowed:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Cannot transition invoice from '{invoice.status}' to '{new_status}'. "
                        f"Allowed transitions: {', '.join(sorted(allowed)) or 'none'}"
                    ),
                )

        # Recompute total if subtotal or tax changed
        new_subtotal = fields.get("amount_subtotal", invoice.amount_subtotal)
        new_tax = fields.get("tax_amount", invoice.tax_amount)
        if "amount_subtotal" in fields or "tax_amount" in fields:
            fields["amount_total"] = _compute_invoice_total(
                new_subtotal or invoice.amount_subtotal,
                new_tax or invoice.tax_amount,
            )

        if fields:
            await self.invoices.update(invoice_id, **fields)

        # Replace line items if provided
        if data.line_items is not None:
            await self.line_items.delete_by_invoice(invoice_id)
            for idx, item_data in enumerate(data.line_items):
                item = InvoiceLineItem(
                    invoice_id=invoice_id,
                    description=item_data.description,
                    quantity=item_data.quantity,
                    unit=item_data.unit,
                    unit_rate=item_data.unit_rate,
                    amount=item_data.amount,
                    wbs_id=item_data.wbs_id,
                    cost_category=item_data.cost_category,
                    sort_order=item_data.sort_order if item_data.sort_order else idx,
                )
                await self.line_items.create(item)

        updated = await self.invoices.get(invoice_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invoice not found",
            )
        logger.info("Invoice updated: %s", invoice_id)
        return updated

    async def approve_invoice(self, invoice_id: uuid.UUID) -> Invoice:
        """Transition invoice to approved status."""
        invoice = await self.get_invoice(invoice_id)
        if invoice.status not in ("draft", "pending"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot approve invoice in status '{invoice.status}'",
            )
        await self.invoices.update(invoice_id, status="approved")
        updated = await self.invoices.get(invoice_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invoice not found",
            )
        logger.info("Invoice approved: %s", invoice.invoice_number)
        return updated

    async def pay_invoice(self, invoice_id: uuid.UUID) -> Invoice:
        """Transition invoice to paid status.

        After marking as paid, recalculates budget actuals for the project
        (sum of all paid invoices) and emits ``invoice.paid`` event.
        """
        invoice = await self.get_invoice(invoice_id)
        if invoice.status != "approved":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Cannot mark as paid invoice in status '{invoice.status}'. "
                    "Invoice must be approved first."
                ),
            )
        await self.invoices.update(invoice_id, status="paid")
        updated = await self.invoices.get(invoice_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invoice not found",
            )
        logger.info("Invoice paid: %s", invoice.invoice_number)

        # BUG-346: distribute actuals across budget rows by
        # ``(wbs_id, cost_category)`` instead of writing the whole project
        # total onto every row. The old behaviour made every budget line
        # look like it had consumed the full project spend, so the variance
        # dashboard flagged every category as 500% over-run after a single
        # paid invoice.
        #
        # Strategy:
        #   1. Walk all paid invoices of the project.
        #   2. For invoices with line items, bucket each line's ``amount``
        #      by ``(wbs_id, cost_category)``.
        #   3. For invoices without line items, attribute the full
        #      ``amount_total`` to the ``(None, None)`` bucket.
        #   4. For each ``ProjectBudget`` row, look up its matching bucket
        #      and set ``actual`` to the summed Decimal; unmatched rows are
        #      zeroed so a later cost-category removal doesn't leave stale
        #      actuals hanging.
        try:
            from collections import defaultdict

            from sqlalchemy import select
            from sqlalchemy.orm import selectinload

            paid_result = await self.session.execute(
                select(Invoice)
                .options(selectinload(Invoice.line_items))
                .where(
                    Invoice.project_id == invoice.project_id,
                    Invoice.status == "paid",
                )
            )
            paid_invoices = paid_result.scalars().all()

            # key = (wbs_id, cost_category); both None means "uncategorized"
            bucketed: dict[tuple[str | None, str | None], Decimal] = defaultdict(
                lambda: Decimal("0")
            )
            total_actual = Decimal("0")

            for inv in paid_invoices:
                items = list(inv.line_items or [])
                if items:
                    for item in items:
                        try:
                            amt = Decimal(str(item.amount))
                        except (InvalidOperation, ValueError):
                            continue
                        bucketed[(item.wbs_id, item.cost_category)] += amt
                        total_actual += amt
                else:
                    # No breakdown — attribute the full invoice total to the
                    # catch-all bucket.
                    try:
                        amt = Decimal(str(inv.amount_total))
                    except (InvalidOperation, ValueError):
                        continue
                    bucketed[(None, None)] += amt
                    total_actual += amt

            budget_result = await self.session.execute(
                select(ProjectBudget).where(
                    ProjectBudget.project_id == invoice.project_id
                )
            )
            budgets = list(budget_result.scalars().all())

            # Reset every budget row before assignment so removing a
            # cost_category from future invoices drains the actual back to 0.
            for budget in budgets:
                key = (budget.wbs_id, budget.category)
                budget.actual = str(bucketed.get(key, Decimal("0")))

            logger.info(
                "Updated budget actuals for project %s: total_actual=%s "
                "across %d budget row(s), %d bucket(s)",
                invoice.project_id,
                total_actual,
                len(budgets),
                len(bucketed),
            )
        except Exception:
            logger.exception(
                "Failed to update budget actuals after paying invoice %s",
                invoice.invoice_number,
            )

        # Emit event for additional cross-module handlers
        await event_bus.publish(
            "invoice.paid",
            {
                "project_id": str(invoice.project_id),
                "invoice_id": str(invoice.id),
                "amount_total": str(invoice.amount_total),
                "currency_code": invoice.currency_code or "EUR",
            },
            source_module="finance",
        )

        return updated

    # ── Payments ─────────────────────────────────────────────────────────────

    async def create_payment(self, data: PaymentCreate) -> Payment:
        """Record a payment against an invoice."""
        await self.get_invoice(data.invoice_id)  # 404 check

        payment = Payment(
            invoice_id=data.invoice_id,
            payment_date=data.payment_date,
            amount=data.amount,
            currency_code=data.currency_code,
            exchange_rate_snapshot=data.exchange_rate_snapshot,
            reference=data.reference,
            metadata_=data.metadata,
        )
        payment = await self.payments_repo.create(payment)
        logger.info("Payment recorded: %s for invoice %s", data.amount, data.invoice_id)
        return payment

    async def list_payments(
        self,
        *,
        invoice_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Payment], int]:
        """List payments with optional invoice filter."""
        return await self.payments_repo.list(
            invoice_id=invoice_id, limit=limit, offset=offset
        )

    # ── Budgets ──────────────────────────────────────────────────────────────

    async def create_budget(self, data: BudgetCreate) -> ProjectBudget:
        """Create a project budget line."""
        budget = ProjectBudget(
            project_id=data.project_id,
            wbs_id=data.wbs_id,
            category=data.category,
            original_budget=data.original_budget,
            revised_budget=data.revised_budget,
            committed=data.committed,
            actual=data.actual,
            forecast_final=data.forecast_final,
            metadata_=data.metadata,
        )
        budget = await self.budgets.create(budget)
        logger.info("Budget created: project=%s cat=%s", data.project_id, data.category)
        return budget

    async def get_budget(self, budget_id: uuid.UUID) -> ProjectBudget:
        """Get budget by ID. Raises 404 if not found."""
        budget = await self.budgets.get(budget_id)
        if budget is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Budget not found",
            )
        return budget

    async def list_budgets(
        self,
        *,
        project_id: uuid.UUID | None = None,
        category: str | None = None,
    ) -> tuple[list[ProjectBudget], int]:
        """List budgets with filters."""
        return await self.budgets.list(project_id=project_id, category=category)

    async def update_budget(
        self,
        budget_id: uuid.UUID,
        data: BudgetUpdate,
    ) -> ProjectBudget:
        """Update budget fields."""
        await self.get_budget(budget_id)  # 404 check

        fields = data.model_dump(exclude_unset=True)
        if "metadata" in fields:
            fields["metadata_"] = fields.pop("metadata")

        if fields:
            await self.budgets.update(budget_id, **fields)

        updated = await self.budgets.get(budget_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Budget not found",
            )
        logger.info("Budget updated: %s", budget_id)
        return updated

    # ── EVM ──────────────────────────────────────────────────────────────────

    async def create_evm_snapshot(self, data: EVMSnapshotCreate) -> EVMSnapshot:
        """Create an EVM snapshot for a project.

        Computes derived metrics server-side:
        Performance indices:
        - SV  = EV - PV                  (schedule variance)
        - CV  = EV - AC                  (cost variance)
        - SPI = EV / PV                  (schedule performance index, 0 if PV == 0)
        - CPI = EV / AC                  (cost performance index, 0 if AC == 0)

        Forecast metrics (EVM standard):
        - EAC  = AC + (BAC - EV) / CPI   (estimate at completion, CPI-based forecast)
        - VAC  = BAC - EAC               (variance at completion)
        - ETC  = EAC - AC                (estimate to complete)
        - TCPI = (BAC - EV) / (BAC - AC) (to-complete performance index)
        """
        bac = _parse_decimal(data.bac, "bac")
        ev = _parse_decimal(data.ev, "ev")
        pv = _parse_decimal(data.pv, "pv")
        ac = _parse_decimal(data.ac, "ac")

        sv = ev - pv
        cv = ev - ac
        spi = (ev / pv) if pv != 0 else Decimal("0")
        cpi = (ev / ac) if ac != 0 else Decimal("0")

        # Round indices to 4 decimal places for readability, then normalize
        # to remove trailing zeros (e.g. "0.9500" -> "0.95")
        spi = spi.quantize(Decimal("0.0001")).normalize()
        cpi = cpi.quantize(Decimal("0.0001")).normalize()

        # ── Forecast metrics ────────────────────────────────────────────
        # EAC: CPI-based forecast. Falls back to AC + remaining BAC when CPI==0.
        if cpi != 0:
            eac = ac + (bac - ev) / cpi
        else:
            eac = ac + (bac - ev)
        eac = eac.quantize(Decimal("0.01"))

        vac = (bac - eac).quantize(Decimal("0.01"))
        etc = (eac - ac).quantize(Decimal("0.01"))

        # TCPI: performance needed on remaining work to stay within BAC.
        remaining_budget = bac - ac
        if remaining_budget != 0:
            tcpi = ((bac - ev) / remaining_budget).quantize(Decimal("0.0001")).normalize()
        else:
            tcpi = Decimal("0")

        snapshot = EVMSnapshot(
            project_id=data.project_id,
            snapshot_date=data.snapshot_date,
            bac=data.bac,
            pv=data.pv,
            ev=data.ev,
            ac=data.ac,
            sv=str(sv),
            cv=str(cv),
            spi=str(spi),
            cpi=str(cpi),
            eac=str(eac),
            vac=str(vac),
            etc=str(etc),
            tcpi=str(tcpi),
            metadata_=data.metadata,
        )
        snapshot = await self.evm.create(snapshot)
        logger.info(
            "EVM snapshot created: project=%s date=%s EAC=%s VAC=%s SPI=%s CPI=%s",
            data.project_id, data.snapshot_date, eac, vac, spi, cpi,
        )
        return snapshot

    async def list_evm_snapshots(
        self,
        *,
        project_id: uuid.UUID | None = None,
    ) -> tuple[list[EVMSnapshot], int]:
        """List EVM snapshots for a project."""
        return await self.evm.list(project_id=project_id)

    # ── Dashboard ───────────────────────────────────────────────────────────

    async def get_dashboard(
        self,
        *,
        project_id: uuid.UUID | None = None,
    ) -> dict:
        """Compute aggregated finance KPIs for a project or globally.

        Uses SQL-level aggregation for invoices, budgets, and payments
        instead of loading all rows into Python — significantly faster
        for projects with many financial records.
        """
        from app.modules.finance.schemas import FinanceDashboardResponse

        # ── Invoices (SQL aggregation) ─────────────────────────────────
        inv_agg = await self.invoices.aggregate_for_dashboard(
            project_id=project_id,
        )
        total_payable = inv_agg["total_payable"]
        total_receivable = inv_agg["total_receivable"]
        total_overdue = inv_agg["total_overdue"]
        overdue_count = inv_agg["overdue_count"]
        status_counts = inv_agg["status_counts"]

        # ── Budgets (SQL aggregation) ──────────────────────────────────
        budget_agg = await self.budgets.aggregate_for_dashboard(
            project_id=project_id,
        )
        total_budget_original = budget_agg["total_budget_original"]
        total_budget_revised = budget_agg["total_budget_revised"]
        total_committed = budget_agg["total_committed"]
        total_actual = budget_agg["total_actual"]

        total_variance = total_budget_revised - total_actual
        budget_consumed_pct = (
            total_actual / total_budget_revised * 100
            if total_budget_revised > 0
            else 0.0
        )

        # Budget warning level
        if budget_consumed_pct >= 95:
            warning_level = "critical"
        elif budget_consumed_pct >= 80:
            warning_level = "caution"
        else:
            warning_level = "normal"

        # ── Payments (SQL aggregation) ─────────────────────────────────
        total_payments = await self.payments_repo.aggregate_total()

        # Net cash flow: receivable payments received minus payable payments made
        cash_flow_net = total_receivable - total_payable

        return FinanceDashboardResponse(
            total_payable=round(total_payable, 2),
            total_receivable=round(total_receivable, 2),
            total_overdue=round(total_overdue, 2),
            overdue_count=overdue_count,
            invoices_draft=status_counts["draft"],
            invoices_pending=status_counts["pending"],
            invoices_approved=status_counts["approved"],
            invoices_paid=status_counts["paid"],
            total_budget_original=round(total_budget_original, 2),
            total_budget_revised=round(total_budget_revised, 2),
            total_committed=round(total_committed, 2),
            total_actual=round(total_actual, 2),
            total_variance=round(total_variance, 2),
            budget_consumed_pct=round(budget_consumed_pct, 1),
            budget_warning_level=warning_level,
            total_payments=round(total_payments, 2),
            cash_flow_net=round(cash_flow_net, 2),
        ).model_dump()
