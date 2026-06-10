"""‌⁠‍Finance service - business logic for invoicing, payments, budgets, and EVM.

Stateless service layer.
"""

import logging
import uuid
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

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
    RecordClaimPaymentRequest,
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


def _project_fx_map(project: object | None) -> dict[str, str]:
    """Project the ``Project.fx_rates`` JSON list into ``{code: rate}``.

    Mirrors :func:`app.modules.boq.service._project_fx_map` - defensive
    against missing attribute / malformed entries so callers can always
    pass the result through :func:`_convert_to_base` without further guards.
    A rate is "units of base currency per 1 unit of the foreign currency".
    """
    if project is None:
        return {}
    raw = getattr(project, "fx_rates", None)
    if not isinstance(raw, list):
        return {}
    out: dict[str, str] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        code = str(entry.get("code") or "").strip().upper()
        rate = str(entry.get("rate") or "").strip()
        if code and rate:
            out[code] = rate
    return out


def _convert_to_base(
    amounts_by_currency: dict[str, float],
    *,
    base_currency: str,
    fx_rates_map: dict[str, str],
) -> tuple[float, list[str]]:
    """Convert per-currency subtotals into the project base currency.

    Mirrors :func:`app.modules.boq.service._position_total_in_base`: an amount
    priced in a non-base currency contributes ``amount * fx_rates_map[code]``.
    A blank currency code is treated as already-base. A foreign currency with
    no configured FX rate is summed in its own units anyway (never zeroed) so
    the rollup degrades visibly, and its code is returned in the second tuple
    element so the caller can surface a "missing FX rate" hint.
    """
    base = (base_currency or "").strip().upper()
    total = Decimal("0")
    missing: list[str] = []
    for code, amount in amounts_by_currency.items():
        norm = (code or "").strip().upper()
        value = _safe_decimal(amount)
        if norm and norm != base:
            fx = fx_rates_map.get(norm)
            if fx:
                rate = _safe_decimal(fx, Decimal("1"))
                if rate > 0:
                    value = value * rate
            elif norm not in missing:
                missing.append(norm)
        total += value
    return round(float(total), 2), missing


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


# ── Gap E: retainage withholding maths ───────────────────────────────────────


def _q2(value: Decimal) -> Decimal:
    """Quantize a money Decimal to 2 places (half-up, the accounting default)."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def compute_payment_withholding(
    gross: object,
    *,
    retention_pct: object = Decimal("0"),
    withholding_amount: object | None = None,
) -> tuple[Decimal, Decimal]:
    """Split a certified gross into (cash to pay, retainage withheld).

    The cash paid out is ``gross - withheld``. The retainage withheld is either
    the explicit ``withholding_amount`` (when supplied) or ``gross *
    retention_pct / 100`` otherwise. Both legs are clamped so they stay within
    ``[0, gross]`` - a retention percentage above 100 or a withholding above the
    gross can never produce a negative cash payment (which would be a phantom
    refund) nor a withholding larger than the claim.

    Returns ``(amount_to_pay, withheld)`` both quantized to 2dp. Pure function:
    no DB, no I/O - the unit suite asserts exact Decimals against it.
    """
    g = _safe_decimal(gross)
    if g < 0:
        g = Decimal("0")
    if withholding_amount is not None:
        withheld = _safe_decimal(withholding_amount)
    else:
        pct = _safe_decimal(retention_pct)
        withheld = g * pct / Decimal("100")
    # Clamp into [0, gross]: never withhold more than the claim, never negative.
    if withheld < 0:
        withheld = Decimal("0")
    if withheld > g:
        withheld = g
    amount_to_pay = g - withheld
    return _q2(amount_to_pay), _q2(withheld)


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
                cost_line_id=getattr(item_data, "cost_line_id", None),
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

        # Replace line items if provided - record a single audit row that
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
                    cost_line_id=getattr(item_data, "cost_line_id", None),
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

        The FSM nomenclature was unified in v3033 - what the legacy code path
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
        # FSM audit row - see :mod:`app.core.fsm.registry` for the invoice
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

        # Emit event so cross-module handlers can react (TOP-30 #4: ERP
        # connectors configured to auto-push on approval pick this up).
        event_bus.publish_detached(
            "invoice.approved",
            {
                "project_id": str(invoice.project_id),
                "invoice_id": str(invoice.id),
                "amount_total": str(invoice.amount_total),
                "currency_code": invoice.currency_code or "",
            },
            source_module="finance",
        )
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

            # key = (wbs_id, cost_category, currency); wbs_id/cost_category both
            # None means "uncategorized". The currency is part of the key so we
            # never blend two currencies into one ProjectBudget.actual (FX
            # never-blend rule): each budget row carries its own currency_code
            # and only receives the bucket priced in that same currency. A blank
            # invoice currency is normalised to "" to match a blank budget-row
            # currency (both treated as base). Mixed-currency invoices on the
            # same (wbs_id, cost_category) therefore land in separate buckets
            # and the per-currency dashboard rollup FX-converts them correctly,
            # instead of summing them as if 1 USD == 1 EUR.
            bucketed: dict[tuple[str | None, str | None, str], Decimal] = defaultdict(lambda: Decimal("0"))
            total_actual = Decimal("0")

            for inv in paid_invoices:
                # getattr keeps this resilient when an invoice row predates the
                # currency_code column (or a caller passes a lightweight stub):
                # a missing/blank code means "base currency" and buckets under "".
                inv_currency = (getattr(inv, "currency_code", "") or "").strip().upper()
                items = list(inv.line_items or [])
                if items:
                    for item in items:
                        try:
                            amt = Decimal(str(item.amount))
                        except (InvalidOperation, ValueError):
                            continue
                        bucketed[(item.wbs_id, item.cost_category, inv_currency)] += amt
                        total_actual += amt
                else:
                    # No breakdown - attribute the full invoice total to the
                    # catch-all bucket for this invoice's currency.
                    try:
                        amt = Decimal(str(inv.amount_total))
                    except (InvalidOperation, ValueError):
                        continue
                    bucketed[(None, None, inv_currency)] += amt
                    total_actual += amt

            budget_result = await self.session.execute(
                select(ProjectBudget).where(ProjectBudget.project_id == invoice.project_id)
            )
            budgets = list(budget_result.scalars().all())

            # Reset every budget row before assignment so removing a
            # cost_category from future invoices drains the actual back to 0.
            # Assign Decimal (not str) - MoneyType column expects Decimal on
            # the ORM side; str assignment works on SQLite but triggers a
            # type-coercion warning on PostgreSQL (BUG-FINANCE-ACT01).
            for budget in budgets:
                # Match the bucket priced in the budget row's own currency only,
                # so a row stamped EUR never absorbs a USD invoice's amount. A
                # row without a currency_code (legacy/stub) buckets under "" and
                # so still matches base-currency invoice amounts as before.
                budget_currency = (getattr(budget, "currency_code", "") or "").strip().upper()
                key = (budget.wbs_id, budget.category, budget_currency)
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

        # ── Post to the costmodel.BudgetLine cost spine (Gap B) ─────────────
        # In addition to the legacy ProjectBudget bucketing above, mirror every
        # paid invoice into the cost spine via the shared
        # CostSpineService.post_actual_to_budget_line(). This is the table the
        # EVM / forecasting dashboards read. Both updates happen inside the same
        # request transaction so the two budget tables never drift.
        #
        # Idempotency: the spine method is keyed on (source_kind, source_ref)
        # where source_ref is "{invoice_id}:{item_id}" (or ":full"), so paying
        # the same invoice twice - or replaying this loop over every already-paid
        # invoice of the project on each pay - posts each line exactly once.
        #
        # FX: amounts are converted to the project base currency BEFORE posting
        # (the spine stores base-currency actuals). A missing rate keeps the
        # foreign value as-is (never zeroed), matching the rest of the cost
        # domain. Non-fatal: a spine failure must NEVER roll back the payment.
        try:
            await self._post_paid_invoices_to_spine(invoice.project_id)
        except Exception:
            logger.exception(
                "Spine posting failed for invoice %s - payment unaffected",
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

    async def _post_paid_invoices_to_spine(self, project_id: uuid.UUID) -> None:
        """Mirror every paid invoice of a project into the costmodel cost spine.

        Walks all ``status="paid"`` invoices for ``project_id`` and posts each
        line item (or the full total for a headerless invoice) into
        ``CostSpineService.post_actual_to_budget_line``. The spine method is
        idempotent on ``(source_kind, source_ref)``, so re-running this sweep on
        every pay only ever posts each line once - no double counting, and a
        newly-paid invoice's lines get posted on the pass triggered by its own
        payment.

        FX: each amount is converted to the project base currency here, before
        posting, because the spine stores base-currency actuals. A line priced
        in a currency without a configured project FX rate keeps its own value
        (never zeroed) so a forgotten rate surfaces as a visibly-wrong figure
        rather than silently dropping money.
        """
        import hashlib

        from sqlalchemy import select
        from sqlalchemy.orm import selectinload

        from app.modules.costmodel.service import CostSpineService
        from app.modules.projects.repository import ProjectRepository

        # Resolve the project base currency + FX table once.
        project = await ProjectRepository(self.session).get_by_id(project_id)
        base_currency = (getattr(project, "currency", "") or "").strip().upper() if project else ""
        fx_map = _project_fx_map(project)

        def _to_base(raw: object, currency: str) -> str:
            """Convert a stored money value to the project base currency string.

            Reuses ``_convert_to_base`` (the finance FX helper) so semantics are
            identical to the dashboard: a foreign currency with no rate is kept
            in its own units, never zeroed. Returns a Decimal-as-string.
            """
            amount = _safe_decimal(raw)
            converted, _missing = _convert_to_base(
                {(currency or "").strip().upper(): float(amount)},
                base_currency=base_currency,
                fx_rates_map=fx_map,
            )
            return str(Decimal(str(converted)))

        result = await self.session.execute(
            select(Invoice)
            .options(selectinload(Invoice.line_items))
            .where(Invoice.project_id == project_id, Invoice.status == "paid")
        )
        paid_invoices = result.scalars().all()

        spine = CostSpineService(self.session)

        async def _post_one(
            *,
            posting_ref: str,
            cost_line_id: uuid.UUID | None,
            cost_category: str | None,
            amount_base: str,
            currency: str,
        ) -> None:
            """Post a single line, isolating its failure from the rest of the sweep.

            One malformed line (e.g. an out-of-vocabulary ``cost_category``,
            which the spine rejects with a 400) must not abort posting for the
            other lines / invoices. Each failure is logged and skipped.
            """
            idempotency = hashlib.sha256(f"invoice_paid:{posting_ref}".encode()).hexdigest()[:16]
            try:
                await spine.post_actual_to_budget_line(
                    project_id=project_id,
                    cost_line_id=cost_line_id,
                    cost_category=cost_category,
                    amount_base=amount_base,
                    currency=currency,
                    source_kind="invoice_paid",
                    source_ref=posting_ref,
                    idempotency_key=idempotency,
                )
            except Exception:
                logger.exception("Spine posting failed for invoice line ref=%s - skipped", posting_ref)

        for inv in paid_invoices:
            inv_currency = inv.currency_code or ""
            items = list(inv.line_items or [])
            if items:
                for item in items:
                    await _post_one(
                        posting_ref=f"{inv.id}:{item.id}",
                        cost_line_id=getattr(item, "cost_line_id", None),
                        cost_category=item.cost_category or None,
                        amount_base=_to_base(item.amount, inv_currency),
                        currency=inv_currency,
                    )
            else:
                await _post_one(
                    posting_ref=f"{inv.id}:full",
                    cost_line_id=None,
                    cost_category=None,
                    amount_base=_to_base(inv.amount_total, inv_currency),
                    currency=inv_currency,
                )

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
           must be provided - prevents silent silent currency confusion.
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
                        f"currency '{inv_currency}' - supply an explicit "
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

    # ── Gap E: certified claim → receivable invoice ──────────────────────────

    async def create_receivable_from_claim(
        self,
        claim_id: uuid.UUID,
        *,
        actor_id: str | None = None,
    ) -> Invoice:
        """Auto-create a receivable invoice from a certified progress claim.

        Idempotent: if a receivable invoice already carries this ``claim_id`` in
        its ``source_claim_id`` column it is returned unchanged (event replay /
        double certification / concurrent calls all converge on one row).

        The claim's contract supplies the project and counterparty; the claim
        supplies the gross / retention / net figures. Each ``ProgressClaimLine``
        becomes one ``InvoiceLineItem`` (3 claim lines → 3 invoice items). The
        claim's gross lands in ``amount_subtotal`` / ``amount_total`` and the
        retainage in ``retention_amount``; the net collectible is therefore
        ``amount_total - retention_amount``. Storing the gross (not the net)
        keeps retention a single deduction so the payment-time withholding never
        double-counts it.

        Multi-currency: amounts denominated in the claim currency are converted
        into the project base currency via ``Project.fx_rates`` before storing.
        A currency with no configured rate keeps its own value (never zeroed) so
        a forgotten rate surfaces as a visibly-wrong figure rather than dropping
        money silently.

        Raises:
            HTTPException 404 when the claim or its contract is missing.
            HTTPException 400 when the claim is not in ``certified`` status.
        """
        from app.modules.contracts.repository import (
            ContractRepository,
            ProgressClaimLineRepository,
            ProgressClaimRepository,
        )
        from app.modules.projects.repository import ProjectRepository

        claim_repo = ProgressClaimRepository(self.session)
        claim = await claim_repo.get_by_id(claim_id)
        if claim is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Progress claim not found",
            )

        # ── Idempotency: one AR invoice per claim ────────────────────────────
        existing = await self.invoices.find_by_source_claim(claim_id)
        if existing is not None:
            return existing

        if claim.status != "certified":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(f"Claim must be certified before it can be invoiced (current status: '{claim.status}')."),
            )

        contract_repo = ContractRepository(self.session)
        contract = await contract_repo.get_by_id(claim.contract_id)
        if contract is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Contract for progress claim not found",
            )

        project_id = contract.project_id
        # Counterparty (client) on the contract becomes the invoice contact.
        contact_id = str(contract.counterparty_id) if contract.counterparty_id else None
        claim_currency = (claim.currency or contract.currency or "").strip().upper()

        # ── FX: convert claim figures into the project base currency ─────────
        project = await ProjectRepository(self.session).get_by_id(project_id)
        base_currency = (getattr(project, "currency", "") or "").strip().upper() if project else ""
        fx_map = _project_fx_map(project)

        def _to_base(raw: object) -> Decimal:
            converted, _missing = _convert_to_base(
                {claim_currency: float(_safe_decimal(raw))},
                base_currency=base_currency,
                fx_rates_map=fx_map,
            )
            return Decimal(str(converted))

        # Invoice money model (conventional, so payment-time withholding works):
        #   amount_subtotal / amount_total = GROSS certified work value
        #   retention_amount               = retainage to hold back
        #   net collectible now            = amount_total - retention_amount
        # The design's shorthand "net_due → subtotal" would store the net and
        # make the payment then withhold retention a SECOND time. Storing the
        # gross (with retention broken out) keeps a single source of truth: the
        # withholding payment subtracts retention_amount exactly once. We prefer
        # the claim's own gross_amount; if it is absent/zero we reconstruct it
        # from net_due + retention so a thin claim still books a sane gross.
        gross_base = _to_base(claim.gross_amount)
        net_base = _to_base(claim.net_due)
        retention_base = _to_base(claim.retention_amount)
        if gross_base <= 0 < (net_base + retention_base):
            gross_base = net_base + retention_base
        invoice_currency = base_currency or claim_currency

        # ── Map claim lines → invoice line items ─────────────────────────────
        line_repo = ProgressClaimLineRepository(self.session)
        claim_lines = await line_repo.list_for_claim(claim_id)

        invoice_number = await self.invoices.next_invoice_number(project_id, "receivable")
        invoice = Invoice(
            project_id=project_id,
            contact_id=contact_id,
            invoice_direction="receivable",
            invoice_number=invoice_number,
            invoice_date=(claim.claim_date or "")[:10],
            due_date=None,
            currency_code=invoice_currency,
            amount_subtotal=gross_base,
            tax_amount=Decimal("0"),
            retention_amount=retention_base,
            amount_total=gross_base,
            status="draft",
            source_claim_id=claim_id,
            notes=f"Auto-created from certified progress claim {claim.claim_number}",
            created_by=uuid.UUID(actor_id) if actor_id else None,
            metadata_={
                "source": "progress_claim",
                "claim_id": str(claim_id),
                "claim_number": claim.claim_number,
                "contract_id": str(claim.contract_id),
                "claim_currency": claim_currency,
                "gross_amount": str(gross_base),
                "net_due": str(net_base),
            },
        )
        invoice = await self.invoices.create(invoice)

        for idx, cl in enumerate(claim_lines):
            amount_base = _to_base(cl.period_completed_value)
            await self.line_items.create(
                InvoiceLineItem(
                    invoice_id=invoice.id,
                    description=(f"Progress claim {claim.claim_number} line (contract line {cl.contract_line_id})"),
                    quantity=_safe_decimal(cl.period_completed_qty, Decimal("1")) or Decimal("1"),
                    unit=None,
                    unit_rate=Decimal("0"),
                    amount=amount_base,
                    wbs_id=None,
                    cost_category=None,
                    sort_order=idx,
                )
            )

        refreshed = await self.invoices.get(invoice.id)
        if refreshed is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to re-fetch created receivable invoice",
            )

        # Audit row - best-effort (mirrors create_invoice / approve paths).
        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=actor_id,
                entity_type="invoice",
                entity_id=str(refreshed.id),
                action="created_from_claim",
                reason=f"Receivable auto-created from certified claim {claim.claim_number}",
                metadata={
                    "claim_id": str(claim_id),
                    "claim_number": claim.claim_number,
                    "gross_base": str(gross_base),
                    "net_due_base": str(net_base),
                    "retention_base": str(retention_base),
                    "currency": invoice_currency,
                },
            )
        except Exception as exc:
            logger.warning(
                "Audit log FAILED for receivable-from-claim (claim_id=%s): %s",
                claim_id,
                exc,
                exc_info=True,
            )

        # Emit so reporting / BI can track certified-but-uncollected AR.
        event_bus.publish_detached(
            "finance.invoice.created_from_claim",
            {
                "project_id": str(project_id),
                "invoice_id": str(refreshed.id),
                "claim_id": str(claim_id),
                "amount_total": str(gross_base),
                "net_due": str(net_base),
                "retention_amount": str(retention_base),
                "currency_code": invoice_currency,
            },
            source_module="finance",
        )

        logger.info(
            "Receivable invoice %s auto-created from certified claim %s (gross=%s net=%s %s)",
            refreshed.invoice_number,
            claim.claim_number,
            gross_base,
            net_base,
            invoice_currency,
        )
        return refreshed

    async def get_receivable_for_claim(self, claim_id: uuid.UUID) -> Invoice | None:
        """Return the receivable invoice raised from *claim_id*, or None.

        Convenience lookup behind ``GET /claims/{claim_id}/receivable-invoice``.
        """
        return await self.invoices.find_by_source_claim(claim_id)

    async def record_payment_with_withholding(
        self,
        invoice_id: uuid.UUID,
        data: RecordClaimPaymentRequest,
        *,
        actor_id: str | None = None,
    ) -> Payment:
        """Record a payment that holds back retainage, then post the cash actual.

        Splits the gross into (cash paid, retainage withheld) via
        :func:`compute_payment_withholding`. When the caller omits
        ``withholding_amount`` it is derived from the invoice
        ``retention_amount``; when the caller omits ``amount`` the invoice net
        (``amount_total - retention_amount``) is paid out. Both are then re-split
        so the stored breakdown is always internally consistent.

        Idempotent on ``idempotency_key`` (a replay returns the existing row).

        After the payment is written, the cash paid out (NOT the withheld
        retainage - that is not yet a realised cost to the client/payer) is
        posted to the cost spine via
        :meth:`CostSpineService.post_actual_to_budget_line`. The spine call is
        non-fatal: a failure there must never roll back the payment.
        """
        # ── Idempotency check first (cheapest path) ──────────────────────────
        if data.idempotency_key:
            existing = await self.payments_repo.get_by_idempotency_key(data.idempotency_key)
            if existing is not None:
                return existing

        invoice = await self.get_invoice(invoice_id)  # 404 check

        inv_total = _safe_decimal(invoice.amount_total)
        inv_retention = _safe_decimal(invoice.retention_amount)

        # Resolve the gross being settled. When amount is given it is the cash
        # the caller intends to pay; gross = cash + withholding. When amount is
        # omitted we settle the whole invoice (gross = amount_total).
        explicit_withholding = _safe_decimal(data.withholding_amount) if data.withholding_amount is not None else None
        if data.amount is not None:
            cash_in = _safe_decimal(data.amount)
            withheld = explicit_withholding if explicit_withholding is not None else inv_retention
            gross = cash_in + withheld
        else:
            gross = inv_total
            withheld = explicit_withholding if explicit_withholding is not None else inv_retention

        amount_to_pay, withholding = compute_payment_withholding(gross, withholding_amount=withheld)

        pay_currency = data.currency_code or invoice.currency_code or ""
        payment = Payment(
            invoice_id=invoice_id,
            payment_date=data.payment_date,
            amount=amount_to_pay,
            currency_code=pay_currency,
            exchange_rate_snapshot=_safe_decimal(data.exchange_rate_snapshot, Decimal("1")),
            reference=data.reference,
            idempotency_key=data.idempotency_key,
            is_refund=False,
            withholding_amount=withholding,
            withholding_release_date=data.withholding_release_date,
            source_claim_id=invoice.source_claim_id,
            metadata_=data.metadata,
        )
        payment = await self.payments_repo.create(payment)

        # ── Post the cash paid out onto the cost spine ───────────────────────
        # Only the cash leg is a realised actual; withheld retainage is a
        # liability still owed, not yet spent. Non-fatal.
        try:
            await self._post_claim_payment_to_spine(
                project_id=invoice.project_id,
                payment=payment,
                currency=pay_currency,
            )
        except Exception:
            logger.exception(
                "Spine posting failed for claim payment %s - payment unaffected",
                payment.id,
            )

        # Audit row - best-effort.
        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=actor_id,
                entity_type="payment",
                entity_id=str(payment.id),
                action="created_with_withholding",
                reason="Claim payment recorded with retainage withholding",
                metadata={
                    "invoice_id": str(invoice_id),
                    "amount": str(amount_to_pay),
                    "withholding_amount": str(withholding),
                    "currency_code": pay_currency,
                    "source_claim_id": str(invoice.source_claim_id) if invoice.source_claim_id else "",
                },
            )
        except Exception as exc:
            logger.warning(
                "Audit log FAILED for withholding payment (invoice_id=%s): %s",
                invoice_id,
                exc,
                exc_info=True,
            )

        logger.info(
            "Payment with withholding recorded: paid=%s withheld=%s for invoice %s",
            amount_to_pay,
            withholding,
            invoice_id,
        )
        return payment

    async def _post_claim_payment_to_spine(
        self,
        *,
        project_id: uuid.UUID,
        payment: Payment,
        currency: str,
    ) -> None:
        """Post the cash leg of a claim payment onto the cost spine.

        FX: the payment ``amount`` is converted to the project base currency
        before posting (spine stores base-currency actuals). A missing rate keeps
        the foreign value as-is, never zeroed. Idempotent on
        ``(source_kind, source_ref)`` keyed by the payment id, so a replay of
        the same payment posts exactly once.
        """
        import hashlib

        from app.modules.costmodel.service import CostSpineService
        from app.modules.projects.repository import ProjectRepository

        project = await ProjectRepository(self.session).get_by_id(project_id)
        base_currency = (getattr(project, "currency", "") or "").strip().upper() if project else ""
        fx_map = _project_fx_map(project)
        converted, _missing = _convert_to_base(
            {(currency or "").strip().upper(): float(_safe_decimal(payment.amount))},
            base_currency=base_currency,
            fx_rates_map=fx_map,
        )
        amount_base = str(Decimal(str(converted)))

        posting_ref = f"payment:{payment.id}"
        idempotency = hashlib.sha256(f"claim_payment:{posting_ref}".encode()).hexdigest()[:16]
        spine = CostSpineService(self.session)
        await spine.post_actual_to_budget_line(
            project_id=project_id,
            cost_line_id=None,
            cost_category=None,
            amount_base=amount_base,
            currency=currency or "",
            source_kind="claim_payment",
            source_ref=posting_ref,
            idempotency_key=idempotency,
        )

    async def list_payments(
        self,
        *,
        invoice_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Payment], int]:
        """List payments with optional invoice / project filter."""
        return await self.payments_repo.list(
            invoice_id=invoice_id,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )

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
          caller does not supply one - never hardcoded (task #217).
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
            # failed/unavailable lookup must never 500 a budget create -
            # fall back to "" (honest unknown, never a wrong hardcoded
            # EUR - task #217).
            try:
                proj = (
                    await self.session.execute(select(Project.currency).where(Project.id == data.project_id))
                ).scalar_one_or_none()
            except Exception:  # noqa: BLE001 - lookup is non-critical
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
            # caller error, not a server fault - surface a clean 409 instead
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

        When all of BAC/PV/EV/AC are exactly "0" (a truly empty snapshot)
        the values are derived from the project's current budget and
        paid-invoice totals (same aggregation that powers ``get_dashboard``).
        Any explicitly-supplied value, including a single legitimate 0 such
        as ev=0 on an early project, is honoured unchanged so power users
        can still record bespoke snapshots.
        """
        bac = _parse_decimal(data.bac, "bac")
        ev = _parse_decimal(data.ev, "ev")
        pv = _parse_decimal(data.pv, "pv")
        ac = _parse_decimal(data.ac, "ac")

        zero = Decimal("0")
        # Only derive baselines for a truly empty snapshot (all four zero).
        # A legitimately-supplied single 0 (e.g. ev=0 on an early project)
        # must be respected, not overwritten with a derived value.
        if bac == zero and pv == zero and ev == zero and ac == zero:
            budget_agg = await self.budgets.aggregate_for_dashboard(
                project_id=data.project_id,
            )
            # Budget totals come back per-currency; convert each into the
            # project base currency (Project.fx_rates) before deriving EVM
            # baselines so a multi-currency project doesn't blend currencies.
            from app.modules.projects.repository import ProjectRepository

            project = await ProjectRepository(self.session).get_by_id(data.project_id)
            base_ccy = (getattr(project, "currency", "") or "").strip().upper() if project else ""
            fx_map = _project_fx_map(project)

            def _budget_base(amounts: dict[str, float]) -> Decimal:
                converted, _ = _convert_to_base(amounts, base_currency=base_ccy, fx_rates_map=fx_map)
                return Decimal(str(converted))

            revised = _budget_base(budget_agg["revised_by_currency"])
            original = _budget_base(budget_agg["original_by_currency"])
            derived_bac = revised or original
            derived_ac = _budget_base(budget_agg["actual_by_currency"])
            derived_committed = _budget_base(budget_agg["committed_by_currency"])
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

        # Round indices to 4 decimal places. Do NOT call .normalize(): for
        # integer-magnitude results normalize() collapses trailing zeros into
        # exponent form (e.g. Decimal("10") -> "1E+1"), which str() then emits
        # as scientific notation and breaks the decimal-string API contract.
        spi = spi.quantize(Decimal("0.0001"))
        cpi = cpi.quantize(Decimal("0.0001"))

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
        # report a negative remaining cost which is semantically wrong -
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
            # No .normalize() - see spi/cpi note above; it would render
            # integer-magnitude indices in scientific notation via str().
            tcpi = ((bac - ev) / remaining_budget).quantize(Decimal("0.0001"))
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
        instead of loading all rows into Python - significantly faster
        for projects with many financial records.
        """
        from app.modules.finance.schemas import FinanceDashboardResponse

        # ── Per-currency aggregates ────────────────────────────────────
        inv_agg = await self.invoices.aggregate_for_dashboard(project_id=project_id)
        budget_agg = await self.budgets.aggregate_for_dashboard(project_id=project_id)
        payments_by_currency = await self.payments_repo.aggregate_by_currency(project_id=project_id)
        overdue_count = inv_agg["overdue_count"]
        status_counts = inv_agg["status_counts"]

        # ── Resolve the project base currency + FX table ───────────────
        # When scoped to a single project we convert every foreign-currency
        # subtotal into the project base currency via Project.fx_rates
        # (mirrors boq.service). Without a base (cross-project rollup) we fall
        # back to the dominant currency and leave foreign amounts unconverted,
        # flagging the mix so the UI does not present a fictitious blended
        # number as if it were a single currency.
        base_currency = ""
        fx_rates_map: dict[str, str] = {}
        if project_id is not None:
            from app.modules.projects.repository import ProjectRepository

            project = await ProjectRepository(self.session).get_by_id(project_id)
            if project is not None:
                base_currency = (getattr(project, "currency", "") or "").strip().upper()
                fx_rates_map = _project_fx_map(project)

        # Dominant currency: prefer budget lines, fall back to invoices.
        dominant_currency = budget_agg.get("currency") or inv_agg.get("currency") or ""
        currency = base_currency or dominant_currency

        # Collect every currency actually in play across all financial records
        # so we can flag mixed-currency dashboards honestly.
        currencies_in_play = {
            c
            for grp in (
                inv_agg["payable_by_currency"],
                inv_agg["receivable_by_currency"],
                inv_agg["overdue_by_currency"],
                budget_agg["original_by_currency"],
                budget_agg["revised_by_currency"],
                budget_agg["committed_by_currency"],
                budget_agg["actual_by_currency"],
                payments_by_currency,
            )
            for c in grp
            if c
        }
        mixed_currencies = len(currencies_in_play) > 1
        missing: set[str] = set()

        def _to_base(amounts: dict[str, float]) -> float:
            converted, miss = _convert_to_base(amounts, base_currency=currency, fx_rates_map=fx_rates_map)
            missing.update(miss)
            return converted

        # ── Invoices ───────────────────────────────────────────────────
        total_payable = _to_base(inv_agg["payable_by_currency"])
        total_receivable = _to_base(inv_agg["receivable_by_currency"])
        total_overdue = _to_base(inv_agg["overdue_by_currency"])

        # ── Budgets ────────────────────────────────────────────────────
        total_budget_original = _to_base(budget_agg["original_by_currency"])
        total_budget_revised = _to_base(budget_agg["revised_by_currency"])
        total_committed = _to_base(budget_agg["committed_by_currency"])
        total_actual = _to_base(budget_agg["actual_by_currency"])

        total_variance = total_budget_revised - total_actual
        budget_consumed_pct = total_actual / total_budget_revised * 100 if total_budget_revised > 0 else 0.0

        # Budget warning level
        if budget_consumed_pct >= 95:
            warning_level = "critical"
        elif budget_consumed_pct >= 80:
            warning_level = "caution"
        else:
            warning_level = "normal"

        # ── Payments ───────────────────────────────────────────────────
        total_payments = _to_base(payments_by_currency)

        # Net cash flow: receivable payments received minus payable payments made
        cash_flow_net = total_receivable - total_payable

        return FinanceDashboardResponse(
            total_payable=round(total_payable, 2),
            total_receivable=round(total_receivable, 2),
            total_overdue=round(total_overdue, 2),
            overdue_count=overdue_count,
            invoices_draft=status_counts["draft"],
            invoices_pending=status_counts["pending"],
            invoices_approved=status_counts["approved"] + status_counts.get("sent", 0),
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
            mixed_currencies=mixed_currencies,
            missing_fx_rates=sorted(missing),
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
        * Rows are NEVER mutated after insert - corrections use
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
