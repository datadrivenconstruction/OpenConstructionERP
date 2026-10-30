# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Service charges business logic.

* Demands are raised as receivable drafts through the finance service API; finance
  approves, sends and collects them like any other invoice.
* Actual costs are read, never written: finance payables of the project and completed
  service work orders, grouped by their cost-category tag, inside the association's
  fiscal year.
* Posting a reconciliation raises a receivable for every unit that owes and a payable
  (refund) for every unit that overpaid, again through finance.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.service_charges.apportion import (
    PERIODS_PER_YEAR,
    ZERO,
    period_amount,
    q2,
    reconcile,
    unit_budget,
    weights,
)
from app.modules.service_charges.models import (
    ApportionmentKey,
    ApportionmentKeyLine,
    BudgetLine,
    ChargeBudget,
    ChargeDemand,
    OwnersAssociation,
    YearEndReconciliation,
)
from app.modules.service_charges.repository import ServiceChargesRepository
from app.modules.service_charges.schemas import (
    AssociationCreate,
    AssociationUpdate,
    BudgetCreate,
    BudgetLineIn,
    BudgetLineUpdate,
    BudgetUpdate,
    KeyCreate,
    KeyUpdate,
)

logger = logging.getLogger(__name__)

SOURCE_TAG = "service_charges"
#: Payable statuses that are not yet (or no longer) a cost.
_PAYABLE_EXCLUDED = frozenset({"draft", "cancelled", "void", "rejected"})
#: Work order statuses whose cost has been incurred.
_WO_DONE = ("completed", "verified", "billed", "closed")
UNCATEGORISED = "uncategorised"
SERVICE_DEFAULT_CATEGORY = "maintenance"


def _not_found(what: str) -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail=f"{what} not found")


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail=message)


def fiscal_window(year: int, start_month: int) -> tuple[date, date]:
    """The fiscal year ``year`` as ``[start, end)``; it starts on the 1st of ``start_month``."""
    return date(year, start_month, 1), date(year + 1, start_month, 1)


def _s(value: Decimal) -> str:
    return format(value, "f")


class ServiceChargesService:
    """Stateless operations over one session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = ServiceChargesRepository(session)

    # ── Lookups ──────────────────────────────────────────────────────────

    async def association(self, association_id: uuid.UUID) -> OwnersAssociation:
        row = await self.session.get(OwnersAssociation, association_id)
        if row is None:
            raise _not_found("Association")
        return row

    async def key(self, key_id: uuid.UUID) -> ApportionmentKey:
        row = await self.session.get(ApportionmentKey, key_id)
        if row is None:
            raise _not_found("Apportionment key")
        return row

    async def budget(self, budget_id: uuid.UUID) -> ChargeBudget:
        row = await self.session.get(ChargeBudget, budget_id)
        if row is None:
            raise _not_found("Budget")
        return row

    async def budget_line(self, line_id: uuid.UUID) -> BudgetLine:
        row = await self.session.get(BudgetLine, line_id)
        if row is None:
            raise _not_found("Budget line")
        return row

    # ── Validation ───────────────────────────────────────────────────────

    async def validation_payload(
        self,
        assoc: OwnersAssociation,
        budget: ChargeBudget | None = None,
        *,
        operation: str | None = None,
        reconciliation: dict[str, Any] | None = None,
        extra_currencies: Sequence[dict[str, str]] = (),
    ) -> dict[str, Any]:
        keys = await self.repo.keys(assoc.id)
        if budget is not None:
            used = {ln.key_id for ln in budget.lines} | ({budget.default_key_id} if budget.default_key_id else set())
            keys = [k for k in keys if k.id in used]
        budgets = await self.repo.budgets(assoc.id)
        years = [b.year for b in budgets]
        currencies: list[dict[str, str]] = list(extra_currencies)
        if assoc.legal_entity_id:
            try:
                from app.modules.legal_entities.models import LegalEntity

                entity = await self.session.get(LegalEntity, assoc.legal_entity_id)
            except ImportError:  # pragma: no cover - optional module
                entity = None
            if entity is not None and entity.functional_currency:
                currencies.append({"source": "legal_entity", "currency": entity.functional_currency})
        if budget is not None:
            for d in await self.repo.demands(budget.id):
                currencies.append({"source": f"demand:{d.unit_ref}:{d.period}", "currency": d.currency})
        return {
            "association": {"id": str(assoc.id), "currency": assoc.currency, "name": assoc.name},
            "keys": [
                {"id": str(k.id), "name": k.name, "method": k.method, "shares": [_s(ln.share) for ln in k.lines]}
                for k in keys
            ],
            "budget": None if budget is None else {"id": str(budget.id), "status": budget.status, "year": budget.year},
            "duplicate_years": sorted({y for y in years if years.count(y) > 1}),
            "operation": operation,
            "reconciliation": reconciliation,
            "currencies": currencies,
        }

    async def validate(self, data: dict[str, Any], target_id: str, project_id: uuid.UUID) -> dict[str, Any]:
        """Run the service charges rule set; failed results only."""
        from app.core.validation.engine import validation_engine
        from app.modules.service_charges.validators import SERVICE_CHARGES_RULE_SET

        report = await validation_engine.validate(
            data=data,
            rule_sets=[SERVICE_CHARGES_RULE_SET],
            target_type="service_charges",
            target_id=target_id,
            project_id=str(project_id),
        )
        failed = [r for r in report.results if not r.passed]
        return {
            "status": "errors" if report.errors else "warnings" if report.warnings else "passed",
            "checked": len(report.results),
            "results": [
                {
                    "rule_id": r.rule_id,
                    "severity": str(r.severity),
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "details": r.details,
                }
                for r in failed
            ],
        }

    async def _refuse_on_errors(self, data: dict[str, Any], target_id: str, project_id: uuid.UUID) -> None:
        result = await self.validate(data, target_id, project_id)
        errors = [r for r in result["results"] if r["severity"] == "error"]
        if errors:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"validation": errors})

    # ── Associations ─────────────────────────────────────────────────────

    async def create_association(self, data: AssociationCreate, actor: str | None) -> OwnersAssociation:
        if any(a.name == data.name for a in await self.repo.associations(data.project_id)):
            raise _conflict("An association with this name already exists in the project")
        row = OwnersAssociation(**data.model_dump(), created_by=actor)
        self.session.add(row)
        await self.session.flush()
        await self._refuse_on_errors(await self.validation_payload(row), str(row.id), row.project_id)
        await self.session.refresh(row)
        return row

    async def update_association(self, assoc: OwnersAssociation, data: AssociationUpdate) -> OwnersAssociation:
        changes = data.model_dump(exclude_unset=True)
        if "currency" in changes and changes["currency"] != assoc.currency:
            if any(b.status != "draft" for b in await self.repo.budgets(assoc.id)):
                raise _conflict("The currency cannot change once a budget is approved")
        for field, value in changes.items():
            setattr(assoc, field, value)
        await self.session.flush()
        await self._refuse_on_errors(await self.validation_payload(assoc), str(assoc.id), assoc.project_id)
        await self.session.refresh(assoc)
        return assoc

    async def delete_association(self, assoc: OwnersAssociation) -> None:
        if any(b.status != "draft" for b in await self.repo.budgets(assoc.id)):
            raise _conflict("An association with an approved budget cannot be deleted")
        for budget in await self.repo.budgets(assoc.id):
            await self.session.delete(budget)
        await self.session.flush()
        await self.session.delete(assoc)
        await self.session.flush()

    # ── Keys ─────────────────────────────────────────────────────────────

    def _key_payload(self, assoc: OwnersAssociation, key: ApportionmentKey) -> dict[str, Any]:
        return {
            "association": {"id": str(assoc.id), "currency": assoc.currency},
            "keys": [
                {
                    "id": str(key.id or ""),
                    "name": key.name,
                    "method": key.method,
                    "shares": [_s(ln.share) for ln in key.lines],
                }
            ],
        }

    async def create_key(self, assoc: OwnersAssociation, data: KeyCreate) -> ApportionmentKey:
        if any(k.name == data.name for k in await self.repo.keys(assoc.id)):
            raise _conflict("A key with this name already exists")
        self._unique_units(data.lines)
        key = ApportionmentKey(association_id=assoc.id, project_id=assoc.project_id, name=data.name, method=data.method)
        key.lines = [ApportionmentKeyLine(**ln.model_dump()) for ln in data.lines]
        await self._refuse_on_errors(self._key_payload(assoc, key), "", assoc.project_id)
        self.session.add(key)
        await self.session.flush()
        return key

    @staticmethod
    def _unique_units(lines: Sequence[Any]) -> None:
        refs = [ln.unit_ref for ln in lines]
        if len(refs) != len(set(refs)):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="A unit appears twice in the key")

    async def _key_locked(self, key: ApportionmentKey) -> bool:
        stmt = (
            select(ChargeBudget.id)
            .join(BudgetLine, BudgetLine.budget_id == ChargeBudget.id)
            .where(BudgetLine.key_id == key.id, ChargeBudget.status != "draft")
        )
        return (await self.session.execute(stmt.limit(1))).first() is not None

    async def update_key(self, assoc: OwnersAssociation, key: ApportionmentKey, data: KeyUpdate) -> ApportionmentKey:
        changes = data.model_dump(exclude_unset=True)
        if ("method" in changes or "lines" in changes) and await self._key_locked(key):
            raise _conflict("The key splits an approved budget; create a new key instead")
        if data.name is not None:
            key.name = data.name
        if data.method is not None:
            key.method = data.method
        if data.lines is not None:
            self._unique_units(data.lines)
            key.lines = [ApportionmentKeyLine(**ln.model_dump()) for ln in data.lines]
        await self._refuse_on_errors(self._key_payload(assoc, key), str(key.id), assoc.project_id)
        await self.session.flush()
        return key

    async def delete_key(self, key: ApportionmentKey) -> None:
        used = (await self.session.execute(select(BudgetLine.id).where(BudgetLine.key_id == key.id).limit(1))).first()
        if used is not None:
            raise _conflict("The key is used by a budget line")
        await self.session.delete(key)
        await self.session.flush()

    # ── Budgets ──────────────────────────────────────────────────────────

    async def _check_key(self, assoc: OwnersAssociation, key_id: uuid.UUID | None) -> None:
        if key_id is None:
            return
        key = await self.session.get(ApportionmentKey, key_id)
        if key is None or key.association_id != assoc.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Key does not belong to the association")

    async def create_budget(self, assoc: OwnersAssociation, data: BudgetCreate) -> ChargeBudget:
        if await self.repo.budget_for_year(assoc.id, data.year) is not None:
            raise _conflict(f"The association already has a budget for {data.year}")
        await self._check_key(assoc, data.default_key_id)
        budget = ChargeBudget(
            association_id=assoc.id,
            project_id=assoc.project_id,
            year=data.year,
            demand_frequency=data.demand_frequency,
            default_key_id=data.default_key_id,
            notes=data.notes,
        )
        lines = []
        for ln in data.lines:
            await self._check_key(assoc, ln.key_id)
            lines.append(BudgetLine(**ln.model_dump()))
        budget.lines = lines
        self.session.add(budget)
        await self.session.flush()
        return budget

    @staticmethod
    def _draft_only(budget: ChargeBudget) -> None:
        if budget.status != "draft":
            raise _conflict("Only a draft budget can change")

    async def update_budget(self, assoc: OwnersAssociation, budget: ChargeBudget, data: BudgetUpdate) -> ChargeBudget:
        self._draft_only(budget)
        changes = data.model_dump(exclude_unset=True)
        await self._check_key(assoc, changes.get("default_key_id"))
        for field, value in changes.items():
            setattr(budget, field, value)
        await self.session.flush()
        return budget

    async def delete_budget(self, budget: ChargeBudget) -> None:
        self._draft_only(budget)
        await self.session.delete(budget)
        await self.session.flush()

    async def approve_budget(self, assoc: OwnersAssociation, budget: ChargeBudget, actor: str | None) -> ChargeBudget:
        self._draft_only(budget)
        if not budget.lines:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="A budget needs at least one line")
        await self._refuse_on_errors(await self.validation_payload(assoc, budget), str(budget.id), assoc.project_id)
        budget.status = "approved"
        budget.approved_at = datetime.now(UTC)
        budget.approved_by = actor
        await self.session.flush()
        return budget

    async def add_line(self, assoc: OwnersAssociation, budget: ChargeBudget, data: BudgetLineIn) -> BudgetLine:
        self._draft_only(budget)
        await self._check_key(assoc, data.key_id)
        if any(ln.category == data.category for ln in budget.lines):
            raise _conflict("The budget already has a line for this category")
        line = BudgetLine(budget_id=budget.id, **data.model_dump())
        budget.lines.append(line)
        await self.session.flush()
        return line

    async def update_line(
        self, assoc: OwnersAssociation, budget: ChargeBudget, line: BudgetLine, data: BudgetLineUpdate
    ) -> BudgetLine:
        self._draft_only(budget)
        changes = data.model_dump(exclude_unset=True)
        await self._check_key(assoc, changes.get("key_id"))
        for field, value in changes.items():
            setattr(line, field, value)
        await self.session.flush()
        return line

    async def delete_line(self, budget: ChargeBudget, line: BudgetLine) -> None:
        self._draft_only(budget)
        budget.lines.remove(line)
        await self.session.flush()

    # ── Charges per unit ─────────────────────────────────────────────────

    async def _key_weights(
        self, assoc: OwnersAssociation
    ) -> tuple[dict[str, list[tuple[str, Decimal]]], dict[str, str]]:
        """Weights per key id and the payer of each unit (first key naming one wins)."""
        keys = await self.repo.keys(assoc.id)
        out = {str(k.id): weights(k.method, [(ln.unit_ref, Decimal(ln.share)) for ln in k.lines]) for k in keys}
        payers: dict[str, str] = {}
        for k in keys:
            for ln in k.lines:
                if ln.payer_contact_id and ln.unit_ref not in payers:
                    payers[ln.unit_ref] = ln.payer_contact_id
        return out, payers

    async def unit_charges(self, assoc: OwnersAssociation, budget: ChargeBudget) -> dict[str, Any]:
        keys, _ = await self._key_weights(assoc)
        yearly = unit_budget([(Decimal(ln.amount), str(ln.key_id)) for ln in budget.lines], keys)
        periods = PERIODS_PER_YEAR[budget.demand_frequency]
        return {
            "budget_id": budget.id,
            "currency": assoc.currency,
            "periods": periods,
            "units": [
                {
                    "unit_ref": unit,
                    "yearly": amount,
                    "per_period": [period_amount(amount, periods, i) for i in range(1, periods + 1)],
                }
                for unit, amount in sorted(yearly.items())
            ],
        }

    # ── Demands ──────────────────────────────────────────────────────────

    async def run_demands(
        self,
        assoc: OwnersAssociation,
        budget: ChargeBudget,
        period: int,
        issue_date: date | None,
        terms_days: int,
        actor: str | None,
    ) -> dict[str, Any]:
        """Raise one demand per unit for ``period``; a unit already demanded is skipped (idempotent)."""
        await self._refuse_on_errors(
            await self.validation_payload(assoc, budget, operation="demand"), str(budget.id), assoc.project_id
        )
        periods = PERIODS_PER_YEAR[budget.demand_frequency]
        if period > periods:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail=f"The budget has {periods} demand periods"
            )
        from app.modules.finance.schemas import InvoiceCreate
        from app.modules.finance.service import FinanceService

        keys, payers = await self._key_weights(assoc)
        yearly = unit_budget([(Decimal(ln.amount), str(ln.key_id)) for ln in budget.lines], keys)
        done = {(d.unit_ref, d.period) for d in await self.repo.demands(budget.id)}
        if issue_date is None:
            start, _ = fiscal_window(budget.year, assoc.fiscal_year_start_month)
            month0 = start.month - 1 + (period - 1) * (12 // periods)
            issue_date = date(start.year + month0 // 12, month0 % 12 + 1, 1)
        finance = FinanceService(self.session)
        created: list[str] = []
        skipped = 0
        for unit, amount in sorted(yearly.items()):
            if (unit, period) in done:
                skipped += 1
                continue
            value = q2(period_amount(amount, periods, period))
            demand = ChargeDemand(
                budget_id=budget.id,
                project_id=budget.project_id,
                unit_ref=unit,
                period=period,
                issue_date=issue_date,
                amount=value,
                currency=assoc.currency,
                payer_contact_id=payers.get(unit),
            )
            if value > ZERO:
                invoice = await finance.create_invoice(
                    InvoiceCreate(
                        project_id=budget.project_id,
                        contact_id=payers.get(unit),
                        invoice_direction="receivable",
                        invoice_date=issue_date.isoformat(),
                        due_date=(issue_date + timedelta(days=terms_days)).isoformat(),
                        currency_code=assoc.currency,
                        amount_subtotal=_s(value),
                        amount_total=_s(value),
                        payment_terms_days=str(terms_days),
                        status="draft",
                        notes=f"Service charge {assoc.name} {budget.year} period {period}/{periods} unit {unit}",
                        metadata={
                            "source": SOURCE_TAG,
                            "kind": "demand",
                            "association_id": str(assoc.id),
                            "budget_id": str(budget.id),
                            "unit_ref": unit,
                            "period": period,
                        },
                    ),
                    actor,
                )
                demand.invoice_id = invoice.id
                created.append(str(invoice.id))
            self.session.add(demand)
        await self.session.flush()
        return {"period": period, "created": len(yearly) - skipped, "skipped": skipped, "invoice_ids": created}

    # ── Actual costs ─────────────────────────────────────────────────────

    async def actual_costs(
        self, assoc: OwnersAssociation, budget: ChargeBudget
    ) -> tuple[dict[str, Decimal], list[dict[str, Any]]]:
        """Actual costs of the fiscal year by category, and the source documents read."""
        start, end = fiscal_window(budget.year, assoc.fiscal_year_start_month)
        lo, hi = start.isoformat(), end.isoformat()
        by_cat: dict[str, Decimal] = {}
        sources: list[dict[str, Any]] = []

        def add(category: str, amount: Decimal) -> None:
            by_cat[category] = by_cat.get(category, ZERO) + q2(amount)

        from app.modules.finance.models import Invoice

        stmt = select(Invoice).where(Invoice.project_id == assoc.project_id, Invoice.invoice_direction == "payable")
        for inv in (await self.session.execute(stmt)).scalars().all():
            meta = inv.metadata_ or {}
            if inv.status in _PAYABLE_EXCLUDED or meta.get("source") == SOURCE_TAG:
                continue
            if not (lo <= (inv.invoice_date or "")[:10] < hi):
                continue
            fallback = str(meta.get("cost_category") or UNCATEGORISED)
            if inv.line_items:
                for li in inv.line_items:
                    add(li.cost_category or fallback, Decimal(li.amount))
            else:
                add(fallback, Decimal(inv.amount_subtotal))
            sources.append(
                {
                    "kind": "payable",
                    "id": str(inv.id),
                    "ref": inv.invoice_number,
                    "currency": inv.currency_code or assoc.currency,
                    "amount": _s(q2(Decimal(inv.amount_subtotal))),
                }
            )

        try:
            from app.modules.service.models import ServiceContract, ServiceTicket, ServiceWorkOrder
        except ImportError:  # pragma: no cover - optional module
            return by_cat, sources
        wo_stmt = (
            select(ServiceWorkOrder)
            .join(ServiceTicket, ServiceTicket.id == ServiceWorkOrder.ticket_id)
            .join(ServiceContract, ServiceContract.id == ServiceTicket.contract_id)
            .where(ServiceContract.project_id == assoc.project_id, ServiceWorkOrder.status.in_(_WO_DONE))
        )
        for wo in (await self.session.execute(wo_stmt)).scalars().all():
            if not (lo <= (wo.completed_at or "")[:10] < hi):
                continue
            amount = sum((Decimal(i.total) for i in wo.items), ZERO) or Decimal(wo.billed_amount or 0)
            add(str((wo.metadata_ or {}).get("cost_category") or SERVICE_DEFAULT_CATEGORY), amount)
            sources.append(
                {
                    "kind": "work_order",
                    "id": str(wo.id),
                    "ref": wo.work_order_number,
                    "currency": wo.currency or assoc.currency,
                    "amount": _s(q2(amount)),
                }
            )
        return by_cat, sources

    # ── Reconciliation ───────────────────────────────────────────────────

    async def compute_reconciliation(self, assoc: OwnersAssociation, budget: ChargeBudget) -> YearEndReconciliation:
        if budget.status == "draft":
            raise _conflict("Approve the budget before reconciling it")
        rec = await self.repo.reconciliation(budget.id)
        if rec is not None and rec.status == "posted":
            raise _conflict("The reconciliation is already posted")
        by_cat, sources = await self.actual_costs(assoc, budget)
        keys, _ = await self._key_weights(assoc)
        demanded: dict[str, Decimal] = {}
        for d in await self.repo.demands(budget.id):
            demanded[d.unit_ref] = demanded.get(d.unit_ref, ZERO) + Decimal(d.amount)
        result = reconcile(
            by_cat,
            {ln.category: str(ln.key_id) for ln in budget.lines},
            str(budget.default_key_id) if budget.default_key_id else None,
            keys,
            demanded,
        )
        total_actual = sum(by_cat.values(), ZERO)
        if rec is None:
            rec = YearEndReconciliation(budget_id=budget.id, project_id=budget.project_id)
            self.session.add(rec)
        rec.status = "draft"
        rec.actual_by_category = {k: _s(v) for k, v in sorted(by_cat.items())}
        rec.unit_balances = [
            {k: (_s(v) if isinstance(v, Decimal) else v) for k, v in u.items()} for u in result["units"]
        ]
        rec.unallocated = {k: _s(v) for k, v in result["unallocated"].items()}
        rec.sources = sources
        rec.total_actual = total_actual
        rec.total_demanded = sum(demanded.values(), ZERO)
        await self.session.flush()
        payload = await self.validation_payload(
            assoc,
            budget,
            reconciliation=self.reconciliation_row(rec),
            extra_currencies=[{"source": f"{s['kind']}:{s['ref']}", "currency": s["currency"]} for s in sources],
        )
        await self._refuse_on_errors(payload, str(rec.id), assoc.project_id)
        return rec

    @staticmethod
    def reconciliation_row(rec: YearEndReconciliation) -> dict[str, Any]:
        return {
            "id": str(rec.id),
            "unit_balances": rec.unit_balances,
            "unallocated": rec.unallocated,
            "total_actual": _s(Decimal(rec.total_actual)),
        }

    async def post_reconciliation(
        self, assoc: OwnersAssociation, budget: ChargeBudget, actor: str | None
    ) -> YearEndReconciliation:
        """Raise the year-end balances through finance and close the budget."""
        rec = await self.repo.reconciliation(budget.id)
        if rec is None:
            raise _conflict("Compute the reconciliation first")
        if rec.status == "posted":
            raise _conflict("The reconciliation is already posted")
        await self._refuse_on_errors(
            await self.validation_payload(assoc, budget, reconciliation=self.reconciliation_row(rec)),
            str(rec.id),
            assoc.project_id,
        )
        from app.modules.finance.schemas import InvoiceCreate
        from app.modules.finance.service import FinanceService

        _, payers = await self._key_weights(assoc)
        finance = FinanceService(self.session)
        _, end = fiscal_window(budget.year, assoc.fiscal_year_start_month)
        on = min(date.today(), end + timedelta(days=365)).isoformat()
        invoices: list[str] = []
        credits: list[str] = []
        for row in rec.unit_balances:
            balance = Decimal(str(row["balance"]))
            if balance == ZERO:
                continue
            owes = balance < ZERO
            amount = _s(abs(balance))
            invoice = await finance.create_invoice(
                InvoiceCreate(
                    project_id=budget.project_id,
                    contact_id=payers.get(row["unit_ref"]),
                    invoice_direction="receivable" if owes else "payable",
                    invoice_date=on,
                    currency_code=assoc.currency,
                    amount_subtotal=amount,
                    amount_total=amount,
                    status="draft",
                    notes=f"Service charge year-end {assoc.name} {budget.year} unit {row['unit_ref']}",
                    metadata={
                        "source": SOURCE_TAG,
                        "kind": "balancing_charge" if owes else "credit",
                        "association_id": str(assoc.id),
                        "budget_id": str(budget.id),
                        "unit_ref": row["unit_ref"],
                    },
                ),
                actor,
            )
            (invoices if owes else credits).append(str(invoice.id))
        rec.posted_invoice_ids = invoices
        rec.posted_credit_ids = credits
        rec.status = "posted"
        rec.posted_at = datetime.now(UTC)
        rec.posted_by = actor
        budget.status = "closed"
        await self.session.flush()
        return rec

    # ── Export ───────────────────────────────────────────────────────────

    async def export(self, assoc: OwnersAssociation, fmt: str) -> tuple[bytes, str, str]:
        budgets = await self.repo.budgets(assoc.id)
        rows: list[dict[str, Any]] = []
        doc: dict[str, Any] = {
            "association": {
                "id": str(assoc.id),
                "name": assoc.name,
                "currency": assoc.currency,
                "fiscal_year_start_month": assoc.fiscal_year_start_month,
                "registration": assoc.registration,
            },
            "keys": [
                {
                    "name": k.name,
                    "method": k.method,
                    "lines": [{"unit_ref": ln.unit_ref, "share": _s(ln.share)} for ln in k.lines],
                }
                for k in await self.repo.keys(assoc.id)
            ],
            "budgets": [],
        }
        for b in budgets:
            demands = await self.repo.demands(b.id)
            rec = await self.repo.reconciliation(b.id)
            doc["budgets"].append(
                {
                    "year": b.year,
                    "status": b.status,
                    "lines": [{"category": ln.category, "amount": _s(ln.amount)} for ln in b.lines],
                    "demands": [
                        {
                            "unit_ref": d.unit_ref,
                            "period": d.period,
                            "amount": _s(d.amount),
                            "invoice_id": str(d.invoice_id or ""),
                        }
                        for d in demands
                    ],
                    "reconciliation": None
                    if rec is None
                    else {"status": rec.status, "total_actual": _s(rec.total_actual), "units": rec.unit_balances},
                }
            )
            for d in demands:
                rows.append(
                    {
                        "association": assoc.name,
                        "year": b.year,
                        "period": d.period,
                        "unit_ref": d.unit_ref,
                        "amount": _s(d.amount),
                        "currency": d.currency,
                        "invoice_id": str(d.invoice_id or ""),
                    }
                )
        if fmt == "csv":
            buf = io.StringIO()
            fields = ["association", "year", "period", "unit_ref", "amount", "currency", "invoice_id"]
            writer = csv.DictWriter(buf, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            return buf.getvalue().encode("utf-8"), "text/csv; charset=utf-8", "csv"
        return json.dumps(doc, ensure_ascii=False, indent=2).encode("utf-8"), "application/json", "json"
