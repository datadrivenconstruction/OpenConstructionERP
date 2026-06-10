"""‌⁠‍Finance data access layer.

All database queries for finance entities live here.
No business logic - pure data access.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.finance.models import (
    EVMSnapshot,
    Invoice,
    InvoiceLineItem,
    Payment,
    ProjectBudget,
)


class InvoiceRepository:
    """‌⁠‍Data access for Invoice model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, invoice_id: uuid.UUID) -> Invoice | None:
        """‌⁠‍Get invoice by ID (with line items and payments via selectin)."""
        stmt = (
            select(Invoice)
            .where(Invoice.id == invoice_id)
            .options(
                selectinload(Invoice.line_items),
                selectinload(Invoice.payments),
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        direction: str | None = None,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Invoice], int]:
        """List invoices with filters and pagination."""
        base = select(Invoice)

        if project_id is not None:
            base = base.where(Invoice.project_id == project_id)
        if direction is not None:
            base = base.where(Invoice.invoice_direction == direction)
        if status is not None:
            base = base.where(Invoice.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Invoice.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, invoice: Invoice) -> Invoice:
        """Insert a new invoice."""
        self.session.add(invoice)
        await self.session.flush()
        return invoice

    async def find_by_source_claim(self, claim_id: uuid.UUID) -> Invoice | None:
        """Return the receivable invoice auto-created from *claim_id*, or None.

        Gap E idempotency anchor: ``create_receivable_from_claim`` calls this
        first so a second ``contracts.claim.certified`` (event replay, double
        click, concurrent certification) returns the existing AR invoice rather
        than writing a duplicate. Line items / payments are eager-loaded so the
        caller can serialise the row straight back through ``InvoiceResponse``.
        """
        stmt = (
            select(Invoice)
            .where(Invoice.source_claim_id == claim_id)
            .options(
                selectinload(Invoice.line_items),
                selectinload(Invoice.payments),
            )
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(self, invoice_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on an invoice."""
        stmt = update(Invoice).where(Invoice.id == invoice_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def next_invoice_number(self, project_id: uuid.UUID, direction: str) -> str:
        """Generate the next invoice number for a project and direction.

        Uses MAX of existing invoice numbers to avoid race conditions where
        COUNT-based generation would produce duplicates under concurrency.
        Extracts the numeric suffix from the highest existing invoice number
        and increments it.
        """
        prefix = "INV-P" if direction == "payable" else "INV-R"
        stmt = (
            select(func.max(Invoice.invoice_number))
            .where(Invoice.project_id == project_id)
            .where(Invoice.invoice_direction == direction)
            .where(Invoice.invoice_number.like(f"{prefix}-%"))
        )
        max_number = (await self.session.execute(stmt)).scalar_one_or_none()

        if max_number:
            # Extract numeric suffix, e.g. "INV-P-003" -> 3
            try:
                suffix = int(max_number.rsplit("-", 1)[-1])
            except (ValueError, IndexError):
                suffix = 0
            return f"{prefix}-{suffix + 1:03d}"

        return f"{prefix}-001"

    async def aggregate_for_dashboard(
        self,
        *,
        project_id: uuid.UUID | None = None,
    ) -> dict:
        """Aggregate invoice KPIs using SQL instead of loading all rows.

        Returns dict with payable/receivable/overdue totals and status counts,
        computed entirely in the database for performance.
        """
        from sqlalchemy import Numeric, cast

        # Group by currency as well so the caller can FX-convert each
        # currency's subtotal into the project base currency rather than
        # blindly summing mixed currencies (domain money rule).
        base = select(
            Invoice.invoice_direction,
            Invoice.status,
            Invoice.currency_code,
            func.count().label("cnt"),
            func.sum(cast(Invoice.amount_total, Numeric)).label("total"),
        )
        if project_id is not None:
            base = base.where(Invoice.project_id == project_id)
        base = base.group_by(
            Invoice.invoice_direction,
            Invoice.status,
            Invoice.currency_code,
        )

        result = await self.session.execute(base)
        rows = result.all()

        # Per-currency subtotals: {currency_code: amount}. Empty currency_code
        # is kept under "" so the service treats it as the base currency.
        payable_by_currency: dict[str, float] = {}
        receivable_by_currency: dict[str, float] = {}
        status_counts: dict[str, int] = {
            "draft": 0,
            "pending": 0,
            "approved": 0,
            # Since the v3033 FSM migration, approve writes status "sent".
            # Keep both so dashboard approved counts stay accurate.
            "sent": 0,
            "credit_note_issued": 0,
            "paid": 0,
            "cancelled": 0,
        }

        for direction, status, currency_code, cnt, total in rows:
            if status in status_counts:
                status_counts[status] += cnt
            if status not in ("paid", "cancelled"):
                code = currency_code or ""
                amount = float(total or 0)
                if direction == "payable":
                    payable_by_currency[code] = payable_by_currency.get(code, 0.0) + amount
                elif direction == "receivable":
                    receivable_by_currency[code] = receivable_by_currency.get(code, 0.0) + amount

        # Overdue count + per-currency amount
        from datetime import date

        today = date.today().isoformat()
        overdue_base = select(
            Invoice.currency_code,
            func.count().label("cnt"),
            func.coalesce(func.sum(cast(Invoice.amount_total, Numeric)), 0).label("total"),
        ).where(
            Invoice.due_date < today,
            Invoice.status.notin_(("paid", "cancelled")),
            Invoice.due_date.isnot(None),
            # due_date is a VARCHAR; an empty string is a valid persisted value
            # (a draft with no due date set). Lexically "" < today is True, so
            # without this guard blank-due-date invoices pollute the overdue KPI
            # as phantom overdues. Exclude them.
            Invoice.due_date != "",
        )
        if project_id is not None:
            overdue_base = overdue_base.where(Invoice.project_id == project_id)
        overdue_base = overdue_base.group_by(Invoice.currency_code)

        overdue_rows = (await self.session.execute(overdue_base)).all()
        overdue_by_currency: dict[str, float] = {}
        overdue_count = 0
        for currency_code, cnt, total in overdue_rows:
            overdue_by_currency[currency_code or ""] = overdue_by_currency.get(currency_code or "", 0.0) + float(
                total or 0
            )
            overdue_count += cnt

        # Dominant invoice currency - used as a dashboard fallback when no
        # budget line carries a currency yet.
        cur_stmt = (
            select(Invoice.currency_code, func.count().label("cnt"))
            .where(Invoice.currency_code != "")
            .group_by(Invoice.currency_code)
            .order_by(func.count().desc())
        )
        if project_id is not None:
            cur_stmt = cur_stmt.where(Invoice.project_id == project_id)
        cur_row = (await self.session.execute(cur_stmt)).first()
        currency = cur_row[0] if cur_row else ""

        return {
            "payable_by_currency": payable_by_currency,
            "receivable_by_currency": receivable_by_currency,
            "overdue_by_currency": overdue_by_currency,
            "overdue_count": overdue_count,
            "status_counts": status_counts,
            "currency": currency,
        }


class InvoiceLineItemRepository:
    """Data access for InvoiceLineItem model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, item: InvoiceLineItem) -> InvoiceLineItem:
        """Insert a new line item."""
        self.session.add(item)
        await self.session.flush()
        return item

    async def delete_by_invoice(self, invoice_id: uuid.UUID) -> None:
        """Delete all line items for an invoice."""
        from sqlalchemy import delete

        stmt = delete(InvoiceLineItem).where(InvoiceLineItem.invoice_id == invoice_id)
        await self.session.execute(stmt)
        await self.session.flush()


class PaymentRepository:
    """Data access for Payment model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, payment_id: uuid.UUID) -> Payment | None:
        """Get payment by ID."""
        return await self.session.get(Payment, payment_id)

    async def list(
        self,
        *,
        invoice_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Payment], int]:
        """List payments with optional invoice / project filter.

        ``project_id`` scopes payments to a single project by joining to the
        parent invoice (``Payment.invoice_id`` → ``Invoice.project_id``).
        Without it (and without ``invoice_id``) the query is unscoped - the
        router must therefore always supply one of the two so payments don't
        leak across tenants.
        """
        base = select(Payment)
        if invoice_id is not None:
            base = base.where(Payment.invoice_id == invoice_id)
        if project_id is not None:
            base = base.where(Payment.invoice_id.in_(select(Invoice.id).where(Invoice.project_id == project_id)))

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Payment.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, payment: Payment) -> Payment:
        """Insert a new payment."""
        self.session.add(payment)
        await self.session.flush()
        return payment

    async def aggregate_total(self, *, invoice_id: uuid.UUID | None = None) -> float:
        """Sum all payment amounts using SQL aggregation.

        Returns total as float. Much faster than loading all rows.
        """
        from sqlalchemy import Numeric, cast

        base = select(func.coalesce(func.sum(cast(Payment.amount, Numeric)), 0))
        if invoice_id is not None:
            base = base.where(Payment.invoice_id == invoice_id)
        result = (await self.session.execute(base)).scalar_one()
        return round(float(result), 2)

    async def aggregate_by_currency(
        self,
        *,
        project_id: uuid.UUID | None = None,
    ) -> dict[str, float]:
        """Sum payment amounts grouped by currency, scoped to a project.

        Payments inherit their currency from ``currency_code`` (or "" when
        blank → treated as base by the caller). Scoped to a single project by
        joining to the parent invoice so a project dashboard never blends in
        other tenants' payments.
        """
        from sqlalchemy import Numeric, case, cast

        # Net out refunds. Refunds are stored as a positive ``amount`` with
        # ``is_refund=True`` (see service.create_payment), and the refund guard
        # treats them as reducing net cash. Summing them positively would
        # inflate total_payments (a 100 payment + 100 refund must net to 0, not
        # 200), so subtract refund rows instead of adding them.
        net_amount = case(
            (Payment.is_refund.is_(True), -cast(Payment.amount, Numeric)),
            else_=cast(Payment.amount, Numeric),
        )
        base = select(
            Payment.currency_code,
            func.coalesce(func.sum(net_amount), 0),
        )
        if project_id is not None:
            base = base.where(Payment.invoice_id.in_(select(Invoice.id).where(Invoice.project_id == project_id)))
        base = base.group_by(Payment.currency_code)

        rows = (await self.session.execute(base)).all()
        out: dict[str, float] = {}
        for currency_code, total in rows:
            out[currency_code or ""] = out.get(currency_code or "", 0.0) + float(total or 0)
        return out

    async def get_by_idempotency_key(self, key: str) -> Payment | None:
        """Return an existing payment that matches *key*, or None.

        Used by create_payment() to implement idempotency: a second POST
        with the same key returns the existing row without writing a duplicate.
        """
        stmt = select(Payment).where(Payment.idempotency_key == key).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_by_source_claim(self, claim_id: uuid.UUID) -> list[Payment]:
        """Return every payment recorded against the certified claim *claim_id*.

        Gap E: a certified claim can be paid in instalments (each holding its own
        retainage), so this returns a list ordered oldest-first. Used by the
        retainage-release flow and the claim → receivable lookup endpoint.
        """
        stmt = select(Payment).where(Payment.source_claim_id == claim_id).order_by(Payment.created_at.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class BudgetRepository:
    """Data access for ProjectBudget model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, budget_id: uuid.UUID) -> ProjectBudget | None:
        """Get budget by ID."""
        return await self.session.get(ProjectBudget, budget_id)

    async def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
        category: str | None = None,
    ) -> tuple[list[ProjectBudget], int]:
        """List budgets with filters."""
        base = select(ProjectBudget)
        if project_id is not None:
            base = base.where(ProjectBudget.project_id == project_id)
        if category is not None:
            base = base.where(ProjectBudget.category == category)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(ProjectBudget.created_at.desc())
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def aggregate_for_dashboard(
        self,
        *,
        project_id: uuid.UUID | None = None,
    ) -> dict:
        """Aggregate budget totals using SQL instead of loading all rows.

        Returns dict with original/revised/committed/actual totals.
        """
        from sqlalchemy import Numeric, cast

        # Group by currency so the caller can FX-convert each currency's
        # subtotals into the project base currency instead of summing mixed
        # currencies as if 1 EUR == 1 USD (domain money rule).
        base = select(
            ProjectBudget.currency_code,
            func.coalesce(func.sum(cast(ProjectBudget.original_budget, Numeric)), 0),
            func.coalesce(func.sum(cast(ProjectBudget.revised_budget, Numeric)), 0),
            func.coalesce(func.sum(cast(ProjectBudget.committed, Numeric)), 0),
            func.coalesce(func.sum(cast(ProjectBudget.actual, Numeric)), 0),
        )
        if project_id is not None:
            base = base.where(ProjectBudget.project_id == project_id)
        base = base.group_by(ProjectBudget.currency_code)

        rows = (await self.session.execute(base)).all()

        original_by_currency: dict[str, float] = {}
        revised_by_currency: dict[str, float] = {}
        committed_by_currency: dict[str, float] = {}
        actual_by_currency: dict[str, float] = {}
        for currency_code, original, revised, committed, actual in rows:
            code = currency_code or ""
            original_by_currency[code] = original_by_currency.get(code, 0.0) + float(original)
            revised_by_currency[code] = revised_by_currency.get(code, 0.0) + float(revised)
            committed_by_currency[code] = committed_by_currency.get(code, 0.0) + float(committed)
            actual_by_currency[code] = actual_by_currency.get(code, 0.0) + float(actual)

        # Resolve the dominant currency for the dashboard so the UI does
        # not have to hardcode one. We pick the most-used non-empty
        # currency_code among this project's budget lines. Empty when no
        # budget line carries a currency (the UI then leaves it unstamped
        # rather than mislabelling totals).
        cur_stmt = (
            select(
                ProjectBudget.currency_code,
                func.count().label("cnt"),
            )
            .where(ProjectBudget.currency_code != "")
            .group_by(ProjectBudget.currency_code)
            .order_by(func.count().desc())
        )
        if project_id is not None:
            cur_stmt = cur_stmt.where(ProjectBudget.project_id == project_id)
        cur_row = (await self.session.execute(cur_stmt)).first()
        currency = cur_row[0] if cur_row else ""

        return {
            "original_by_currency": original_by_currency,
            "revised_by_currency": revised_by_currency,
            "committed_by_currency": committed_by_currency,
            "actual_by_currency": actual_by_currency,
            "currency": currency,
        }

    async def create(self, budget: ProjectBudget) -> ProjectBudget:
        """Insert a new budget line."""
        self.session.add(budget)
        await self.session.flush()
        return budget

    async def update(self, budget_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a budget."""
        stmt = update(ProjectBudget).where(ProjectBudget.id == budget_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()


class EVMSnapshotRepository:
    """Data access for EVMSnapshot model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list(
        self,
        *,
        project_id: uuid.UUID | None = None,
    ) -> tuple[list[EVMSnapshot], int]:
        """List EVM snapshots for a project."""
        base = select(EVMSnapshot)
        if project_id is not None:
            base = base.where(EVMSnapshot.project_id == project_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(EVMSnapshot.snapshot_date.desc())
        result = await self.session.execute(stmt)
        items = list(result.scalars().all())

        return items, total

    async def create(self, snapshot: EVMSnapshot) -> EVMSnapshot:
        """Insert a new EVM snapshot."""
        self.session.add(snapshot)
        await self.session.flush()
        return snapshot
