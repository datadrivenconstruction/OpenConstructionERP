"""‌⁠‍Finance service — business logic for invoicing, payments, budgets, and EVM.

Stateless service layer.
"""

import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import event_bus
from app.modules.finance.models import (
    EVMSnapshot,
    Invoice,
    InvoiceLineItem,
    LedgerEntry,
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
    LedgerEntryCreate,
    PaymentCreate,
)

logger = logging.getLogger(__name__)


def _safe_decimal(value: object, default: Decimal = Decimal("0")) -> Decimal:
    """Coerce *value* to Decimal; return *default* on any error."""
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _utcnow_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(UTC).isoformat()


# ── Allowed status transitions ──────────────────────────────────────────────
#
# Kept in addition to :mod:`app.core.fsm.registry` for backwards compatibility:
# the update_invoice() path uses this table to enforce transitions when the
# client PATCHes the ``status`` field directly. The new FSM-driven flows
# (``approve_invoice`` / ``pay_invoice``) write through :func:`log_activity`
# and use the canonical FSM nomenclature.
#
# Legacy values (``pending`` / ``approved``) are accepted as aliases for the
# canonical FSM nodes after the v3033 data migration remaps existing rows.
_INVOICE_STATUS_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"pending", "approved", "sent", "cancelled"},
    "pending": {"approved", "sent", "cancelled", "draft"},
    "approved": {"paid", "sent", "cancelled"},
    "sent": {"paid", "cancelled"},
    "paid": {"credit_note_issued"},  # only credit-note reversal allowed
    "cancelled": {"draft"},  # allow re-opening
    "credit_note_issued": set(),  # terminal
}

_VALID_INVOICE_STATUSES = set(_INVOICE_STATUS_TRANSITIONS.keys())


def _parse_decimal(value: str, field_name: str = "value") -> Decimal:
    """‌⁠‍Parse a string to Decimal, raising a clear error on failure."""
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid numeric value for {field_name}: {value!r}",
        ) from exc


def _compute_invoice_total(subtotal: str, tax: str) -> str:
    """‌⁠‍Compute amount_total = amount_subtotal + tax_amount."""
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
                    f"Invalid invoice status: '{data.status}'. Allowed: {', '.join(sorted(_VALID_INVOICE_STATUSES))}"
                ),
            )

        # Auto-generate invoice number if not provided
        invoice_number = data.invoice_number
        if not invoice_number:
            invoice_number = await self.invoices.next_invoice_number(data.project_id, data.invoice_direction)

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
                        f"Invalid invoice status: '{new_status}'. Allowed: {', '.join(sorted(_VALID_INVOICE_STATUSES))}"
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

        # Replace line items if provided — record a single audit row that
        # captures the count + total delta (no per-item diff, just the
        # aggregate so audit logs aren't flooded by every bulk edit).
        if data.line_items is not None:
            prior_items = list(getattr(invoice, "line_items", None) or [])
            prior_count = len(prior_items)

            def _sum(items) -> Decimal:  # type: ignore[no-untyped-def]
                total = Decimal("0")
                for it in items:
                    amt = getattr(it, "amount", None)
                    if amt is None and isinstance(it, dict):
                        amt = it.get("amount")
                    try:
                        total += Decimal(str(amt or 0))
                    except (InvalidOperation, TypeError, ValueError):
                        continue
                return total

            prior_total = _sum(prior_items)
            new_total = _sum(data.line_items)

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

            # Single audit row for the bulk replacement. Best-effort:
            # failures are warned (not rolled back) for the same reason as
            # the approve/pay paths.
            try:
                from app.core.audit_log import log_activity

                await log_activity(
                    self.session,
                    actor_id=None,
                    entity_type="invoice",
                    entity_id=str(invoice_id),
                    action="line_items_replaced",
                    reason=(
                        f"Replaced {prior_count} line item(s) with "
                        f"{len(data.line_items)}; total delta="
                        f"{(new_total - prior_total)}"
                    ),
                    metadata={
                        "invoice_number": getattr(invoice, "invoice_number", None),
                        "prior_count": prior_count,
                        "new_count": len(data.line_items),
                        "prior_total": str(prior_total),
                        "new_total": str(new_total),
                        "total_delta": str(new_total - prior_total),
                    },
                )
            except Exception as exc:
                logger.warning(
                    "Audit log FAILED for invoice line-items replace (invoice_id=%s): %s",
                    invoice_id,
                    exc,
                    exc_info=True,
                )

        updated = await self.invoices.get(invoice_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invoice not found",
            )
        logger.info("Invoice updated: %s", invoice_id)
        return updated

    async def approve_invoice(
        self,
        invoice_id: uuid.UUID,
        *,
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> Invoice:
        """Transition invoice to ``sent`` status (legacy alias: ``approved``).

        The FSM nomenclature was unified in v3033 — what the legacy code path
        called ``approved`` is now stored as ``sent`` in the database. The
        method keeps its old name for backwards compatibility but writes the
        new value and records the transition in :class:`ActivityLog`.
        """
        invoice = await self.get_invoice(invoice_id)
        prior = invoice.status
        if prior not in ("draft", "pending"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Cannot approve invoice in status '{prior}'",
            )
        await self.invoices.update(invoice_id, status="sent")
        # FSM audit row — see :mod:`app.core.fsm.registry` for the invoice
        # lifecycle. Best-effort: an audit failure must NOT roll back the
        # status change, but it MUST surface as a warning so audit-log
        # outages don't go silently undetected (the prior debug-level log
        # was invisible in production where root level = INFO).
        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=actor_id,
                entity_type="invoice",
                entity_id=str(invoice_id),
                action="status_changed",
                from_status=prior,
                to_status="sent",
                reason=reason or "Invoice approved via approve_invoice()",
                metadata={"invoice_number": invoice.invoice_number},
            )
        except Exception as exc:
            logger.warning(
                "FSM audit log FAILED for invoice approve (user_id=%s, invoice_id=%s): %s",
                actor_id,
                invoice_id,
                exc,
                exc_info=True,
            )
        updated = await self.invoices.get(invoice_id)
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invoice not found",
            )
        logger.info("Invoice approved (sent): %s", invoice.invoice_number)
        return updated

    async def pay_invoice(
        self,
        invoice_id: uuid.UUID,
        *,
        actor_id: str | None = None,
        reason: str | None = None,
    ) -> Invoice:
        """Transition invoice to paid status.

        After marking as paid, recalculates budget actuals for the project
        (sum of all paid invoices) and emits ``invoice.paid`` event. Per
        the v3033 FSM the prior status must be ``sent`` (legacy alias
        ``approved`` is still accepted because both legacy values map to
        the same FSM node after the data migration).
        """
        invoice = await self.get_invoice(invoice_id)
        prior = invoice.status
        if prior not in ("approved", "sent"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(f"Cannot mark as paid invoice in status '{prior}'. Invoice must be sent first."),
            )
        await self.invoices.update(invoice_id, status="paid")
        # Best-effort: an audit failure must NOT roll back the status
        # change, but it MUST surface as a warning so audit-log outages
        # don't go silently undetected (was previously logger.debug, which
        # is invisible at production INFO root level).
        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=actor_id,
                entity_type="invoice",
                entity_id=str(invoice_id),
                action="status_changed",
                from_status=prior,
                to_status="paid",
                reason=reason or "Invoice paid via pay_invoice()",
                metadata={"invoice_number": invoice.invoice_number},
            )
        except Exception as exc:
            logger.warning(
                "FSM audit log FAILED for invoice pay (user_id=%s, invoice_id=%s): %s",
                actor_id,
                invoice_id,
                exc,
                exc_info=True,
            )
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
            bucketed: dict[tuple[str | None, str | None], Decimal] = defaultdict(lambda: Decimal("0"))
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
                select(ProjectBudget).where(ProjectBudget.project_id == invoice.project_id)
            )
            budgets = list(budget_result.scalars().all())

            # Reset every budget row before assignment so removing a
            # cost_category from future invoices drains the actual back to 0.
            # Assign Decimal (not str) — MoneyType column expects Decimal on
            # the ORM side; str assignment works on SQLite but triggers a
            # type-coercion warning on PostgreSQL (BUG-FINANCE-ACT01).
            for budget in budgets:
                key = (budget.wbs_id, budget.category)
                budget.actual = bucketed.get(key, Decimal("0"))

            logger.info(
                "Updated budget actuals for project %s: total_actual=%s across %d budget row(s), %d bucket(s)",
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
        event_bus.publish_detached(
            "invoice.paid",
            {
                "project_id": str(invoice.project_id),
                "invoice_id": str(invoice.id),
                "amount_total": str(invoice.amount_total),
                # Empty when the invoice carries no currency; subscribers
                # receive the truth ("no currency stamped") instead of a
                # mis-labelled EUR.
                "currency_code": invoice.currency_code or "",
            },
            source_module="finance",
        )

        return updated

    # ── Payments ─────────────────────────────────────────────────────────────

    async def create_payment(
        self,
        data: PaymentCreate,
        *,
        actor_id: str | None = None,
    ) -> Payment:
        """Record a payment against an invoice.

        R7 guards:
        1. Idempotency: if ``idempotency_key`` matches an existing payment,
           return that row without writing a duplicate.
        2. Currency normalization: if the payment currency differs from the
           invoice currency, an explicit FX rate (exchange_rate_snapshot != "1")
           must be provided — prevents silent silent currency confusion.
        3. Refund guard: total refunds cannot exceed total forward payments
           (net_paid >= 0).

        ``actor_id`` is optional so the legacy in-process callers
        (event-bus consumers, importers) don't break, but the router
        always supplies it.
        """
        # ── 1. Idempotency check ──────────────────────────────────────────────
        if data.idempotency_key:
            existing = await self.payments_repo.get_by_idempotency_key(data.idempotency_key)
            if existing is not None:
                return existing

        invoice = await self.get_invoice(data.invoice_id)  # 404 check

        # ── 2. Currency normalization ─────────────────────────────────────────
        inv_currency = getattr(invoice, "currency_code", "") or ""
        pay_currency = data.currency_code or ""
        fx_rate = _safe_decimal(data.exchange_rate_snapshot, Decimal("1"))
        if inv_currency and pay_currency and inv_currency != pay_currency:
            if fx_rate == Decimal("1"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Payment currency '{pay_currency}' differs from invoice "
                        f"currency '{inv_currency}' — supply an explicit "
                        f"exchange_rate_snapshot != '1'."
                    ),
                )

        # ── 3. Refund guard ───────────────────────────────────────────────────
        if data.is_refund:
            all_payments, _ = await self.payments_repo.list(invoice_id=data.invoice_id)
            total_forward = sum(_safe_decimal(p.amount) for p in all_payments if not getattr(p, "is_refund", False))
            total_refunds = sum(_safe_decimal(p.amount) for p in all_payments if getattr(p, "is_refund", False))
            refund_amount = _safe_decimal(data.amount)
            if total_forward - total_refunds - refund_amount < Decimal("0"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Refund of {data.amount} would exceed total payments "
                        f"({total_forward}) minus existing refunds ({total_refunds}). "
                        f"Net paid cannot go negative."
                    ),
                )

        payment = Payment(
            invoice_id=data.invoice_id,
            payment_date=data.payment_date,
            amount=data.amount,
            currency_code=data.currency_code,
            exchange_rate_snapshot=data.exchange_rate_snapshot,
            reference=data.reference,
            idempotency_key=data.idempotency_key,
            is_refund=bool(data.is_refund),
            metadata_=data.metadata,
        )
        payment = await self.payments_repo.create(payment)

        # R7 audit-trail row. Best-effort but logged at warning level
        # so an audit-table outage surfaces in production logs.
        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=actor_id,
                entity_type="payment",
                entity_id=str(payment.id),
                action="created",
                reason="Payment recorded via create_payment()",
                metadata={
                    "invoice_id": str(data.invoice_id),
                    "amount": str(data.amount),
                    "currency_code": data.currency_code or "",
                    "payment_date": data.payment_date,
                    "reference": data.reference or "",
                },
            )
        except Exception as exc:
            logger.warning(
                "Audit log FAILED for payment create (actor_id=%s, invoice_id=%s): %s",
                actor_id,
                data.invoice_id,
                exc,
                exc_info=True,
            )

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
        return await self.payments_repo.list(invoice_id=invoice_id, limit=limit, offset=offset)

    # ── Budgets ──────────────────────────────────────────────────────────────

    async def create_budget(self, data: BudgetCreate) -> ProjectBudget:
        """Create a project budget line.

        Two sensible defaults are applied so manually-created lines behave
        like commercial staff expect:

        * ``revised_budget`` defaults to ``original_budget`` when the caller
          leaves it at "0". The revised budget only diverges once a change
          order revises it; without this, variance and consumed-% would be
          computed against a zero baseline (always 0%, nonsensical).
        * ``currency_code`` is inherited from the parent project when the
          caller does not supply one — never hardcoded (task #217).
        """
        from sqlalchemy import select

        from app.modules.projects.models import Project

        revised = data.revised_budget
        try:
            if Decimal(revised or "0") == 0 and Decimal(data.original_budget or "0") != 0:
                revised = data.original_budget
        except (InvalidOperation, ValueError, TypeError):
            revised = data.revised_budget

        currency_code = data.currency_code
        if not currency_code:
            # Best-effort, mirrors boq ``_resolve_project_currency``: a
            # failed/unavailable lookup must never 500 a budget create —
            # fall back to "" (honest unknown, never a wrong hardcoded
            # EUR — task #217).
            try:
                proj = (
                    await self.session.execute(select(Project.currency).where(Project.id == data.project_id))
                ).scalar_one_or_none()
            except Exception:  # noqa: BLE001 — lookup is non-critical
                proj = None
            currency_code = proj or ""

        budget = ProjectBudget(
            project_id=data.project_id,
            wbs_id=data.wbs_id,
            category=data.category,
            currency_code=currency_code,
            original_budget=data.original_budget,
            revised_budget=revised,
            committed=data.committed,
            actual=data.actual,
            forecast_final=data.forecast_final,
            metadata_=data.metadata,
        )
        try:
            budget = await self.budgets.create(budget)
        except IntegrityError as exc:
            # ``oe_finance_budget`` has a UNIQUE constraint on
            # (project_id, wbs_id, category). A duplicate budget line is a
            # caller error, not a server fault — surface a clean 409 instead
            # of letting the IntegrityError bubble as a raw 500.
            await self.session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"A budget line for WBS '{data.wbs_id}' / category "
                    f"'{data.category}' already exists for this project."
                ),
            ) from exc
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

        Client-supplied BAC/PV/EV/AC values that are exactly "0" are
        replaced with values derived from the project's current budget and
        paid-invoice totals (same aggregation that powers ``get_dashboard``).
        Non-zero client values are honoured unchanged so power users can
        still record bespoke snapshots.
        """
        bac = _parse_decimal(data.bac, "bac")
        ev = _parse_decimal(data.ev, "ev")
        pv = _parse_decimal(data.pv, "pv")
        ac = _parse_decimal(data.ac, "ac")

        zero = Decimal("0")
        if bac == zero or pv == zero or ev == zero or ac == zero:
            budget_agg = await self.budgets.aggregate_for_dashboard(
                project_id=data.project_id,
            )
            derived_bac = Decimal(str(budget_agg["total_budget_revised"] or budget_agg["total_budget_original"]))
            derived_ac = Decimal(str(budget_agg["total_actual"]))
            derived_committed = Decimal(str(budget_agg["total_committed"]))
            # PV approximation: planned spend up to snapshot date is the
            # revised baseline (matches dashboard behaviour where plan
            # equals revised budget). EV approximation: committed work
            # represents earned value progress when no schedule timeline
            # is present.
            derived_pv = derived_bac
            derived_ev = derived_committed if derived_committed > zero else derived_ac
            if bac == zero:
                bac = derived_bac
            if ac == zero:
                ac = derived_ac
            if pv == zero:
                pv = derived_pv
            if ev == zero:
                ev = derived_ev

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
        # ETC ("estimate to complete") = forecast spend remaining. When a
        # project is already over-forecast (ac > eac), ``eac - ac`` would
        # report a negative remaining cost which is semantically wrong —
        # the answer is "nothing more should be spent" (i.e. 0), not a
        # negative budget recovery. Clamp at zero so the FE KPI card
        # doesn't render a misleading negative figure.
        etc = max(eac - ac, Decimal("0")).quantize(Decimal("0.01"))

        # TCPI: performance needed on remaining work to stay within BAC.
        # Clamp when over budget (bac - ac <= 0): the index is undefined
        # because no remaining budget exists, and a negative denominator
        # would flip the sign and report misleading positive performance.
        remaining_budget = bac - ac
        if remaining_budget > 0:
            tcpi = ((bac - ev) / remaining_budget).quantize(Decimal("0.0001")).normalize()
        else:
            tcpi = Decimal("0")

        snapshot = EVMSnapshot(
            project_id=data.project_id,
            snapshot_date=data.snapshot_date,
            bac=str(bac),
            pv=str(pv),
            ev=str(ev),
            ac=str(ac),
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
            data.project_id,
            data.snapshot_date,
            eac,
            vac,
            spi,
            cpi,
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
        budget_consumed_pct = total_actual / total_budget_revised * 100 if total_budget_revised > 0 else 0.0

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

        # Dominant currency: prefer budget lines, fall back to invoices.
        currency = budget_agg.get("currency") or inv_agg.get("currency") or ""

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
            currency=currency,
        ).model_dump()

    # ── Ledger (R7 double-entry) ──────────────────────────────────────────────

    async def create_ledger_transaction(
        self,
        data: LedgerEntryCreate,
    ) -> tuple[LedgerEntry, LedgerEntry]:
        """Write a balanced double-entry ledger transaction.

        Invariants enforced:
        * debit_amount == credit_amount (400 if unbalanced)
        * Two rows are written atomically via a SAVEPOINT:
            - debit row:  debit_amount > 0, credit_amount == 0
            - credit row: credit_amount > 0, debit_amount == 0
        * Rows are NEVER mutated after insert — corrections use
          :meth:`reverse_ledger_transaction`.
        """
        debit_val = _safe_decimal(data.debit_amount)
        credit_val = _safe_decimal(data.credit_amount)
        if debit_val <= Decimal("0"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=("Zero or negative debit amount. Double-entry invariant requires debit_amount > 0."),
            )
        if debit_val != credit_val:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"Double-entry invariant violated: debit {debit_val} "
                    f"!= credit {credit_val}. "
                    f"Unbalanced transaction rejected."
                ),
            )

        posted_at = data.posted_at or _utcnow_iso()
        project_id = data.project_id

        async with self.session.begin_nested():
            debit_row = LedgerEntry(
                project_id=project_id,
                transaction_ref=data.transaction_ref,
                account_code=data.debit_account,
                description=data.description,
                debit_amount=debit_val,
                credit_amount=Decimal("0"),
                currency_code=data.currency_code or "",
                posted_at=posted_at,
                source_type=data.source_type,
                source_id=data.source_id,
                is_reversal=False,
                created_by=data.created_by,
            )
            credit_row = LedgerEntry(
                project_id=project_id,
                transaction_ref=data.transaction_ref,
                account_code=data.credit_account,
                description=data.description,
                debit_amount=Decimal("0"),
                credit_amount=credit_val,
                currency_code=data.currency_code or "",
                posted_at=posted_at,
                source_type=data.source_type,
                source_id=data.source_id,
                is_reversal=False,
                created_by=data.created_by,
            )
            self.session.add(debit_row)
            self.session.add(credit_row)
            await self.session.flush()

        logger.info(
            "Ledger transaction created: ref=%s dr=%s cr=%s",
            data.transaction_ref,
            debit_val,
            credit_val,
        )
        return debit_row, credit_row

    async def reverse_ledger_transaction(
        self,
        transaction_ref: str,
        *,
        project_id: uuid.UUID | None = None,
        description: str | None = None,
        created_by: str | None = None,
    ) -> tuple[LedgerEntry, LedgerEntry]:
        """Append a corrective reversal pair for an existing transaction.

        Immutability: the original rows are NEVER updated.  Reversal rows
        have ``is_reversal=True`` and ``reversal_of_id`` pointing at the
        original row they mirror.

        The reversal transaction_ref uses the ``:rev`` suffix convention:
        e.g. ``TXN-001:rev``.
        """
        from sqlalchemy import select

        stmt = select(LedgerEntry).where(
            LedgerEntry.transaction_ref == transaction_ref,
            LedgerEntry.is_reversal == False,  # noqa: E712
        )
        rows = list((await self.session.execute(stmt)).scalars().all())
        if not rows:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No ledger entries found for transaction_ref '{transaction_ref}'.",
            )

        posted_at = _utcnow_iso()
        # :rev suffix is the canonical naming convention for corrective entries
        reversal_ref = f"{transaction_ref}:rev"
        rev_description = description or f"Reversal of {transaction_ref}"

        # Identify the debit and credit legs by which amount is non-zero
        orig_debit = next((r for r in rows if _safe_decimal(r.debit_amount) > 0), rows[0])
        orig_credit = next((r for r in rows if _safe_decimal(r.credit_amount) > 0), rows[-1])

        async with self.session.begin_nested():
            # Reversal debit row uses the credit account (accounts are swapped)
            rev_debit = LedgerEntry(
                project_id=project_id or orig_debit.project_id,
                transaction_ref=reversal_ref,
                account_code=orig_credit.account_code,  # ← swapped
                description=rev_description,
                debit_amount=orig_debit.debit_amount,  # same magnitude
                credit_amount=Decimal("0"),
                currency_code=orig_debit.currency_code,
                posted_at=posted_at,
                source_type=orig_debit.source_type,
                source_id=orig_debit.source_id,
                is_reversal=True,
                reversal_of_id=orig_debit.id,
                created_by=created_by,
            )
            # Reversal credit row uses the debit account (accounts are swapped)
            rev_credit = LedgerEntry(
                project_id=project_id or orig_credit.project_id,
                transaction_ref=reversal_ref,
                account_code=orig_debit.account_code,  # ← swapped
                description=rev_description,
                debit_amount=Decimal("0"),
                credit_amount=orig_credit.credit_amount,  # same magnitude
                currency_code=orig_credit.currency_code,
                posted_at=posted_at,
                source_type=orig_credit.source_type,
                source_id=orig_credit.source_id,
                is_reversal=True,
                reversal_of_id=orig_credit.id,
                created_by=created_by,
            )
            self.session.add(rev_debit)
            self.session.add(rev_credit)
            await self.session.flush()

        logger.info("Ledger reversal created: %s → %s", transaction_ref, reversal_ref)
        return rev_debit, rev_credit
