# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Leasing business logic.

* The schedule is derived from the lease and regenerated idempotently: a line is
  keyed by its period start, lines already invoiced are never touched, planned
  lines follow the lease.
* Rent invoices are raised only through :class:`FinanceService` as receivable
  drafts; finance approves and sends them as for any other invoice.
* Arrears are read from finance (invoice status and payments through the ageing
  loader), never from a ledger of our own.
* Every state change writes a :class:`LeaseEvent` and an audit row.
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from collections.abc import Callable, Sequence
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.leasing.models import Lease, LeaseDocument, LeaseEvent, RentScheduleLine
from app.modules.leasing.repository import HOLDING_STATUSES, LeasingRepository
from app.modules.leasing.schedule import FREQUENCY_MONTHS, add_months, build_schedule, q2, term_months
from app.modules.leasing.schemas import LeaseCreate, LeaseUpdate, RenewRequest, ReviewRequest, TerminateRequest

logger = logging.getLogger(__name__)

#: Fields that shape money or dates; they only change while the lease is a draft.
_FROZEN_WHEN_LIVE = frozenset(
    {
        "unit_kind",
        "unit_ref",
        "tenant_contact_id",
        "landlord_legal_entity_id",
        "start_date",
        "end_date",
        "rent_amount",
        "currency",
        "frequency",
        "deposit",
        "escalation_kind",
        "escalation_rate",
        "escalation_every_months",
        "tax_rate",
    }
)
_POSTED_INVOICE_STATUSES = ("pending", "approved", "sent")

ExportProfile = Callable[[list[dict[str, Any]]], tuple[bytes, str, str]]
_EXPORT_PROFILES: dict[str, ExportProfile] = {}


def register_export_profile(name: str, profile: ExportProfile) -> None:
    """Add an export profile (a pack adds e.g. a national lease registry format).

    ``profile`` receives the exported lease rows and returns ``(body, media_type, extension)``.
    """
    _EXPORT_PROFILES[name.lower()] = profile


def export_profiles() -> list[str]:
    return sorted(_EXPORT_PROFILES)


def _json_profile(rows: list[dict[str, Any]]) -> tuple[bytes, str, str]:
    import json

    return (
        json.dumps({"leases": rows}, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
        "application/json",
        "json",
    )


_CSV_COLUMNS = (
    "code",
    "status",
    "unit_kind",
    "unit_ref",
    "unit_label",
    "tenant_contact_id",
    "landlord_legal_entity_id",
    "start_date",
    "end_date",
    "term_months",
    "rent_amount",
    "currency",
    "frequency",
    "deposit",
    "escalation_kind",
    "escalation_rate",
    "break_date",
)


def _csv_profile(rows: list[dict[str, Any]]) -> tuple[bytes, str, str]:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=list(_CSV_COLUMNS), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: "" if row.get(k) is None else row.get(k) for k in _CSV_COLUMNS})
    return buf.getvalue().encode("utf-8"), "text/csv", "csv"


register_export_profile("json", _json_profile)
register_export_profile("csv", _csv_profile)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lease not found")


def lease_row(lease: Lease) -> dict[str, Any]:
    """A lease as plain data: what validation and export read."""
    return {
        "id": str(lease.id) if lease.id else "",
        "project_id": str(lease.project_id),
        "code": lease.code,
        "status": lease.status,
        "unit_kind": lease.unit_kind,
        "unit_ref": lease.unit_ref,
        "unit_label": lease.unit_label,
        "tenant_contact_id": lease.tenant_contact_id,
        "landlord_legal_entity_id": str(lease.landlord_legal_entity_id) if lease.landlord_legal_entity_id else None,
        "start_date": lease.start_date.isoformat() if lease.start_date else None,
        "end_date": lease.end_date.isoformat() if lease.end_date else None,
        "term_months": lease.term_months,
        "rent_amount": format(Decimal(lease.rent_amount or 0), "f"),
        "currency": lease.currency,
        "frequency": lease.frequency,
        "deposit": format(Decimal(lease.deposit or 0), "f"),
        "escalation_kind": lease.escalation_kind,
        "escalation_rate": format(lease.escalation_rate, "f") if lease.escalation_rate is not None else None,
        "break_date": lease.break_date.isoformat() if lease.break_date else None,
        "ext_refs": dict(lease.ext_refs or {}),
    }


class LeasingService:
    """Stateless operations over one session."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = LeasingRepository(session)

    # ── Lookups ──────────────────────────────────────────────────────────

    async def get(self, lease_id: uuid.UUID) -> Lease:
        lease = await self.repo.get(lease_id)
        if lease is None:
            raise _not_found()
        return lease

    async def _context(self, lease: Lease) -> dict[str, Any]:
        """Country, landlord currency and tenant identifiers for the rules."""
        country: str | None = None
        entity_currency: str | None = None
        if lease.landlord_legal_entity_id:
            try:
                from app.modules.legal_entities.models import LegalEntity

                entity = await self.session.get(LegalEntity, lease.landlord_legal_entity_id)
            except ImportError:  # pragma: no cover - optional module
                entity = None
            if entity is None:
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Landlord legal entity not found")
            country, entity_currency = entity.country_code, entity.functional_currency
        if country is None:
            from app.modules.projects.models import Project

            project = await self.session.get(Project, lease.project_id)
            country = getattr(project, "country_code", None) if project else None
        schemes: list[str] = []
        from app.modules.contacts.models import Contact

        try:
            contact = await self.session.get(Contact, uuid.UUID(str(lease.tenant_contact_id)))
        except ValueError:
            contact = None
        if contact is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Tenant contact not found")
        if contact.vat_number:
            schemes.append("vat")
        for source in (contact.custom_properties or {}, contact.metadata_ or {}):
            for ident in source.get("identifiers") or source.get("party_identifiers") or []:
                if isinstance(ident, dict) and ident.get("scheme") and ident.get("value"):
                    schemes.append(str(ident["scheme"]))
        overlaps = await self.repo.overlapping(
            lease.unit_kind, lease.unit_ref, lease.start_date, lease.end_date, lease.id
        )
        return {
            "lease": lease_row(lease),
            "country": country,
            "entity_currency": entity_currency,
            "overlaps": [o.code for o in overlaps],
            "tenant_identifier_schemes": schemes,
        }

    async def validate(self, lease: Lease) -> dict[str, Any]:
        """Run the leasing rule set over one lease; failed results only."""
        from app.core.validation.engine import validation_engine
        from app.modules.leasing.validators import LEASING_RULE_SET

        data = await self._context(lease)
        report = await validation_engine.validate(
            data=data,
            rule_sets=[LEASING_RULE_SET],
            target_type="lease",
            target_id=str(lease.id or ""),
            project_id=str(lease.project_id),
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

    async def _refuse_on_errors(self, lease: Lease) -> None:
        result = await self.validate(lease)
        errors = [r for r in result["results"] if r["severity"] == "error"]
        if errors:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={"validation": errors})

    async def _event(self, lease: Lease, kind: str, on: date, actor: str | None, **payload: Any) -> LeaseEvent:
        ev = LeaseEvent(
            lease_id=lease.id,
            project_id=lease.project_id,
            kind=kind,
            event_date=on,
            payload={k: (format(v, "f") if isinstance(v, Decimal) else v) for k, v in payload.items()},
            actor_id=actor,
        )
        self.session.add(ev)
        try:
            from app.core.audit_log import log_activity

            await log_activity(
                self.session,
                actor_id=actor,
                entity_type="lease",
                entity_id=lease.id,
                action=kind,
                to_status=lease.status,
                module="leasing",
                parent_entity_type="project",
                parent_entity_id=lease.project_id,
                metadata={"code": lease.code, **ev.payload},
            )
        except Exception:  # noqa: BLE001 - audit is best effort, the event row is the record
            logger.warning("leasing: audit write failed for %s %s", lease.id, kind, exc_info=True)
        return ev

    # ── CRUD ─────────────────────────────────────────────────────────────

    async def create(self, data: LeaseCreate, actor: str | None) -> Lease:
        if await self.repo.code_taken(data.project_id, data.code):
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Lease code already used in this project")
        lease = Lease(**data.model_dump(), status="draft", created_by=actor, document_links=[])
        lease.term_months = term_months(data.start_date, data.end_date) if data.end_date >= data.start_date else 0
        await self._refuse_on_errors(lease)
        self.session.add(lease)
        await self.session.flush()
        await self._event(lease, "created", date.today(), actor)
        await self.session.flush()
        return lease

    async def update(self, lease: Lease, data: LeaseUpdate, actor: str | None) -> Lease:
        changes = data.model_dump(exclude_unset=True)
        if lease.status != "draft" and _FROZEN_WHEN_LIVE & set(changes):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Terms of a live lease change by renewal or review, not by editing",
            )
        if "code" in changes and await self.repo.code_taken(lease.project_id, changes["code"], lease.id):
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Lease code already used in this project")
        for key, value in changes.items():
            setattr(lease, key, value)
        if lease.end_date >= lease.start_date:
            lease.term_months = term_months(lease.start_date, lease.end_date)
        await self.session.flush()
        await self._refuse_on_errors(lease)
        await self._event(lease, "updated", date.today(), actor, fields=sorted(changes))
        await self.session.flush()
        return lease

    async def delete(self, lease: Lease) -> None:
        if lease.status != "draft":
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Only a draft lease can be deleted")
        await self.session.delete(lease)
        await self.session.flush()

    # ── Lifecycle ────────────────────────────────────────────────────────

    async def activate(self, lease: Lease, on: date | None, actor: str | None) -> Lease:
        if lease.status != "draft":
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Only a draft lease can be activated")
        lease.status = "active"
        await self.session.flush()
        try:
            await self._refuse_on_errors(lease)
        except HTTPException:
            lease.status = "draft"
            await self.session.flush()
            raise
        await self.generate_schedule(lease)
        await self._event(lease, "activated", on or date.today(), actor)
        await self.session.flush()
        return lease

    async def terminate(self, lease: Lease, body: TerminateRequest, actor: str | None) -> Lease:
        if lease.status not in HOLDING_STATUSES:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Only an active lease can be terminated")
        if body.effective < lease.start_date:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Termination before the lease starts")
        today = date.today()
        lease.end_date = min(lease.end_date, body.effective)
        lease.term_months = term_months(lease.start_date, lease.end_date)
        lease.notice_date = body.notice_given_on or today
        if body.effective <= today:
            lease.status = "ended"
            lease.ended_on = body.effective
        else:
            lease.status = "notice"
        await self.generate_schedule(lease)
        await self._event(
            lease,
            "termination",
            lease.notice_date,
            actor,
            effective=body.effective.isoformat(),
            reason=body.reason or "",
        )
        await self.session.flush()
        return lease

    async def renew(self, lease: Lease, body: RenewRequest, actor: str | None) -> Lease:
        if lease.status not in (*HOLDING_STATUSES, "ended"):
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Only an active or ended lease can be renewed")
        start = lease.end_date + timedelta(days=1)
        if body.end_date <= start:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The renewal must end after it starts")
        code = body.code or f"{lease.code}-R"
        n = 1
        while await self.repo.code_taken(lease.project_id, code):
            n += 1
            code = f"{lease.code}-R{n}"
        data = LeaseCreate(
            project_id=lease.project_id,
            code=code,
            unit_kind=lease.unit_kind,  # type: ignore[arg-type]
            unit_ref=lease.unit_ref,
            unit_label=lease.unit_label,
            tenant_contact_id=lease.tenant_contact_id,
            landlord_legal_entity_id=lease.landlord_legal_entity_id,
            start_date=start,
            end_date=body.end_date,
            rent_amount=body.rent_amount if body.rent_amount is not None else Decimal(lease.rent_amount),
            currency=lease.currency,
            frequency=lease.frequency,  # type: ignore[arg-type]
            deposit=Decimal(lease.deposit),
            escalation_kind=lease.escalation_kind,  # type: ignore[arg-type]
            escalation_rate=lease.escalation_rate,
            escalation_index=lease.escalation_index,
            escalation_every_months=lease.escalation_every_months,
            tax_code=lease.tax_code,
            tax_rate=Decimal(lease.tax_rate),
            payment_terms_days=lease.payment_terms_days,
            ext_refs=dict(lease.ext_refs or {}),
        )
        new = await self.create(data, actor)
        new.renewed_from_id = lease.id
        await self._event(lease, "renewal", date.today(), actor, renewal_id=str(new.id), renewal_code=new.code)
        await self.session.flush()
        return new

    async def review(self, lease: Lease, body: ReviewRequest, actor: str | None) -> Lease:
        if lease.escalation_kind != "index":
            raise HTTPException(status.HTTP_409_CONFLICT, detail="Only an index-linked lease records review rates")
        await self._event(
            lease,
            "review",
            body.event_date or date.today(),
            actor,
            review_number=body.review_number,
            rate=body.rate,
            note=body.note or "",
        )
        await self.session.flush()
        if lease.status in HOLDING_STATUSES:
            await self.generate_schedule(lease)
        return lease

    # ── Schedule ─────────────────────────────────────────────────────────

    async def generate_schedule(self, lease: Lease) -> list[RentScheduleLine]:
        """Bring the stored lines in line with the lease. Running it twice changes nothing."""
        rates = {k: Decimal(v) for k, v in (await self.repo.review_rates(lease.id)).items()}
        wanted = build_schedule(
            start=lease.start_date,
            end=lease.end_date,
            rent_amount=Decimal(lease.rent_amount),
            frequency=lease.frequency,
            escalation_kind=lease.escalation_kind,
            escalation_rate=lease.escalation_rate,
            escalation_every_months=lease.escalation_every_months,
            index_rates=rates,
            tax_rate=Decimal(lease.tax_rate or 0),
        )
        by_start = {line.period_start: line for line in await self.repo.lines(lease.id)}
        keep: set[date] = set()
        for spec in wanted:
            keep.add(spec.period_start)
            line = by_start.get(spec.period_start)
            if line is not None and line.invoice_id is not None:
                continue
            if line is None:
                line = RentScheduleLine(lease_id=lease.id, project_id=lease.project_id, period_start=spec.period_start)
                self.session.add(line)
            line.seq = spec.seq
            line.period_end = spec.period_end
            line.due_date = spec.due_date
            line.amount = spec.amount
            line.tax_amount = spec.tax_amount
            line.tax_code = lease.tax_code
            line.review_number = spec.review_number
        for start, line in by_start.items():
            if start not in keep and line.invoice_id is None:
                await self.session.delete(line)
        await self.session.flush()
        return await self.repo.lines(lease.id)

    async def run_schedule(
        self,
        leases: Sequence[Lease],
        as_of: date,
        actor: str | None,
    ) -> dict[str, Any]:
        """Raise a receivable draft in finance for every due, uninvoiced line."""
        from app.modules.finance.schemas import InvoiceCreate
        from app.modules.finance.service import FinanceService

        finance = FinanceService(self.session)
        created: list[str] = []
        skipped = 0
        for lease in leases:
            if lease.status not in HOLDING_STATUSES:
                continue
            for line in await self.repo.lines(lease.id):
                if line.due_date > as_of:
                    continue
                if line.invoice_id is not None:
                    skipped += 1
                    continue
                subtotal, tax = q2(Decimal(line.amount)), q2(Decimal(line.tax_amount or 0))
                due = line.due_date + timedelta(days=int(lease.payment_terms_days or 0))
                invoice = await finance.create_invoice(
                    InvoiceCreate(
                        project_id=lease.project_id,
                        contact_id=lease.tenant_contact_id,
                        invoice_direction="receivable",
                        invoice_date=line.due_date.isoformat(),
                        due_date=due.isoformat(),
                        currency_code=lease.currency,
                        amount_subtotal=format(subtotal, "f"),
                        tax_amount=format(tax, "f"),
                        amount_total=format(subtotal + tax, "f"),
                        payment_terms_days=str(lease.payment_terms_days or 0),
                        status="draft",
                        notes=f"Rent {lease.code} {line.period_start.isoformat()} - {line.period_end.isoformat()}",
                        metadata={
                            "source": "leasing",
                            "lease_id": str(lease.id),
                            "schedule_line_id": str(line.id),
                            "tax_code": line.tax_code or "",
                        },
                    ),
                    actor,
                )
                line.invoice_id = invoice.id
                created.append(str(invoice.id))
            if created:
                await self._event(lease, "schedule_run", as_of, actor, as_of=as_of.isoformat())
        await self.session.flush()
        return {"as_of": as_of, "invoices_created": len(created), "invoice_ids": created, "skipped": skipped}

    # ── Reports ──────────────────────────────────────────────────────────

    async def tenant_names(self, leases: Sequence[Lease]) -> dict[str, str]:
        """Display names of the tenant contacts, by contact id."""
        from sqlalchemy import select

        from app.modules.contacts.models import Contact

        ids = []
        for x in leases:
            try:
                ids.append(uuid.UUID(str(x.tenant_contact_id)))
            except ValueError:
                continue
        if not ids:
            return {}
        rows = await self.session.execute(select(Contact).where(Contact.id.in_(ids)))
        out: dict[str, str] = {}
        for c in rows.scalars().all():
            person = " ".join(p for p in (c.first_name, c.last_name) if p)
            out[str(c.id)] = c.company_name or c.legal_name or person or ""
        return out

    async def rent_roll(self, leases: Sequence[Lease], as_of: date) -> dict[str, Any]:
        lines = await self.repo.lines_for_leases([x.id for x in leases])
        by_lease: dict[uuid.UUID, list[RentScheduleLine]] = {}
        for line in lines:
            by_lease.setdefault(line.lease_id, []).append(line)
        names = await self.tenant_names(leases)
        rows: list[dict[str, Any]] = []
        totals: dict[str, Decimal] = {}
        for lease in leases:
            if lease.status not in HOLDING_STATUSES:
                continue
            own = by_lease.get(lease.id, [])
            current = next((ln for ln in own if ln.period_start <= as_of <= ln.period_end), None)
            upcoming = next((ln for ln in own if ln.due_date > as_of), None)
            step = FREQUENCY_MONTHS.get(lease.frequency, 1)
            full = [
                ln for ln in own if ln.period_end >= add_months(lease.start_date, ln.seq * step) - timedelta(days=1)
            ]
            # A prorated last period would understate the rent, so take the latest full period instead.
            ref = current if current in full else next((ln for ln in reversed(full) if ln.period_start <= as_of), None)
            rent = Decimal(ref.amount) if ref else Decimal(lease.rent_amount)
            annual = q2(rent * Decimal(12) / Decimal(FREQUENCY_MONTHS.get(lease.frequency, 1)))
            totals[lease.currency] = totals.get(lease.currency, Decimal("0")) + annual
            rows.append(
                {
                    "lease_id": str(lease.id),
                    "code": lease.code,
                    "unit_kind": lease.unit_kind,
                    "unit_ref": lease.unit_ref,
                    "unit_label": lease.unit_label,
                    "tenant_contact_id": lease.tenant_contact_id,
                    "tenant_name": names.get(lease.tenant_contact_id, ""),
                    "status": lease.status,
                    "start_date": lease.start_date,
                    "end_date": lease.end_date,
                    "currency": lease.currency,
                    "frequency": lease.frequency,
                    "current_rent": format(q2(rent), "f"),
                    "annual_rent": format(annual, "f"),
                    "deposit": format(q2(Decimal(lease.deposit)), "f"),
                    "next_due_date": upcoming.due_date if upcoming else None,
                    "break_date": lease.break_date,
                }
            )
        return {"as_of": as_of, "items": rows, "totals": {k: format(q2(v), "f") for k, v in totals.items()}}

    async def arrears(self, leases: Sequence[Lease], as_of: date) -> dict[str, Any]:
        """Overdue rent as finance sees it: posted invoices, payments to date, nothing ledgered here."""
        from app.modules.finance.ageing import open_balance
        from app.modules.finance.service import FinanceService

        lines = await self.repo.lines_for_leases([x.id for x in leases])
        lease_by_invoice: dict[str, Lease] = {}
        by_id = {x.id: x for x in leases}
        for line in lines:
            if line.invoice_id is not None:
                lease_by_invoice[str(line.invoice_id)] = by_id[line.lease_id]
        if not lease_by_invoice:
            return {"as_of": as_of, "items": [], "totals": {}}
        invoices = await FinanceService(self.session).load_ageing_invoices(
            statuses=_POSTED_INVOICE_STATUSES,
            direction="receivable",
            invoice_ids=[uuid.UUID(i) for i in lease_by_invoice],
        )
        names = await self.tenant_names(leases)
        rows: list[dict[str, Any]] = []
        totals: dict[str, dict[str, Decimal]] = {}
        for inv in invoices:
            bal = open_balance(inv, as_of=as_of.isoformat())
            if bal.due <= 0 or bal.days_past_due <= 0:
                continue
            lease = lease_by_invoice[str(inv.invoice_id)]
            cur = totals.setdefault(inv.currency_code, {})
            cur[bal.bucket] = cur.get(bal.bucket, Decimal("0")) + bal.due
            cur["total"] = cur.get("total", Decimal("0")) + bal.due
            rows.append(
                {
                    "lease_id": str(lease.id),
                    "code": lease.code,
                    "unit_label": lease.unit_label or lease.unit_ref,
                    "tenant_contact_id": lease.tenant_contact_id,
                    "tenant_name": names.get(lease.tenant_contact_id, ""),
                    "currency": inv.currency_code,
                    "invoice_id": str(inv.invoice_id),
                    "invoice_number": inv.invoice_number,
                    "due_date": bal.effective_due_date,
                    "days_past_due": bal.days_past_due,
                    "bucket": bal.bucket,
                    "total": format(bal.total, "f"),
                    "paid": format(bal.paid, "f"),
                    "due": format(bal.due, "f"),
                }
            )
        rows.sort(key=lambda r: -r["days_past_due"])
        return {
            "as_of": as_of,
            "items": rows,
            "totals": {c: {k: format(q2(v), "f") for k, v in b.items()} for c, b in totals.items()},
        }

    async def tenant_parties(self, leases: Sequence[Lease]) -> dict[str, dict[str, Any]]:
        """Name, phone and identifiers of each tenant contact, by contact id."""
        from sqlalchemy import select

        from app.modules.contacts.models import Contact

        ids = []
        for x in leases:
            try:
                ids.append(uuid.UUID(str(x.tenant_contact_id)))
            except ValueError:
                continue
        if not ids:
            return {}
        rows = await self.session.execute(select(Contact).where(Contact.id.in_(ids)))
        out: dict[str, dict[str, Any]] = {}
        for c in rows.scalars().all():
            person = " ".join(p for p in (c.first_name, c.last_name) if p)
            idents: list[dict[str, str]] = []
            for source in (c.custom_properties or {}, c.metadata_ or {}):
                for ident in source.get("identifiers") or source.get("party_identifiers") or []:
                    if isinstance(ident, dict) and ident.get("scheme") and ident.get("value"):
                        idents.append({"scheme": str(ident["scheme"]), "value": str(ident["value"])})
            if c.vat_number:
                idents.append({"scheme": "vat", "value": c.vat_number})
            out[str(c.id)] = {
                "name": c.company_name or c.legal_name or person or "",
                "phone": c.primary_phone or "",
                "is_company": bool(c.company_name and not person),
                "identifiers": idents,
            }
        return out

    async def export(self, leases: Sequence[Lease], profile: str) -> tuple[bytes, str, str]:
        from app.modules.leasing.export_profiles import enrich_row, load_profiles, render_csv

        name = profile.lower()
        data_profile = load_profiles().get(name)
        fn = _EXPORT_PROFILES.get(name)
        if fn is None and data_profile is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Unknown export profile {profile!r}; available: {', '.join(export_profiles())}",
            )
        parties = await self.tenant_parties(leases)
        rows = [enrich_row(lease_row(x), parties.get(str(x.tenant_contact_id))) for x in leases]
        if fn is not None:
            return fn(rows)
        return render_csv(data_profile or {}, rows)

    # ── Documents ────────────────────────────────────────────────────────

    async def documents(self, lease: Lease) -> list[dict[str, str]]:
        ids = [x.document_id for x in lease.document_links]
        if not ids:
            return []
        from sqlalchemy import select

        from app.modules.documents.models import Document

        rows = await self.session.execute(
            select(Document).where(Document.id.in_(ids), Document.project_id == lease.project_id)
        )
        return [{"id": str(d.id), "name": d.name, "category": d.category} for d in rows.scalars().all()]

    async def link_document(self, lease: Lease, document_id: uuid.UUID, actor: str | None) -> Lease:
        from app.modules.documents.models import Document

        doc = await self.session.get(Document, document_id)
        if doc is None or doc.project_id != lease.project_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")
        if all(x.document_id != document_id for x in lease.document_links):
            lease.document_links.append(LeaseDocument(document_id=document_id))
            await self._event(lease, "document_linked", date.today(), actor, document_id=str(document_id))
            await self.session.flush()
        return lease

    async def unlink_document(self, lease: Lease, document_id: uuid.UUID, actor: str | None) -> Lease:
        kept = [x for x in lease.document_links if x.document_id != document_id]
        if len(kept) != len(lease.document_links):
            lease.document_links[:] = kept
            await self._event(lease, "document_unlinked", date.today(), actor, document_id=str(document_id))
            await self.session.flush()
        return lease
