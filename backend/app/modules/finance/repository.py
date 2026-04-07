"""Finance data access layer.

All database queries for finance entities live here.
No business logic — pure data access.
"""

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.finance.models import (
    EVMSnapshot,
    Invoice,
    InvoiceLineItem,
    Payment,
    ProjectBudget,
)


class InvoiceRepository:
    """Data access for Invoice model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, invoice_id: uuid.UUID) -> Invoice | None:
        """Get invoice by ID (with line items and payments via selectin)."""
        return await self.session.get(Invoice, invoice_id)

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

    async def update(self, invoice_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on an invoice."""
        stmt = update(Invoice).where(Invoice.id == invoice_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        self.session.expire_all()

    async def next_invoice_number(
        self, project_id: uuid.UUID, direction: str
    ) -> str:
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
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Payment], int]:
        """List payments with optional invoice filter."""
        base = select(Payment)
        if invoice_id is not None:
            base = base.where(Payment.invoice_id == invoice_id)

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
