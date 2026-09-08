# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data-access layer for the subcontractors module."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.subcontractors.models import (
    Certificate,
    LienWaiver,
    PaymentApplication,
    PaymentApplicationLine,
    PrequalificationApplication,
    RetentionLedger,
    SubcontractAgreement,
    Subcontractor,
    SubcontractorContact,
    SubcontractorRating,
    WorkPackage,
)
from app.modules.subcontractors.tax_id import canonical_tax_id, tax_id_digit_run


class _BaseRepo:
    """Shared CRUD primitives - keeps the per-entity repos compact."""

    model: type[Any]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, entity_id: uuid.UUID) -> Any:
        return await self.session.get(self.model, entity_id)

    async def create(self, entity: Any) -> Any:
        self.session.add(entity)
        await self.session.flush()
        return entity

    async def update_fields(self, entity_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on one row.

        A Core UPDATE bypasses the ORM, so the in-memory copy of the row is
        stale afterwards. This used to reconcile that with
        ``session.expire_all()``, which invalidated every instance in the
        session rather than the one row being written. On an async session
        reading an expired attribute raises MissingGreenlet instead of
        lazy-loading, so callers crashed on objects this update never touched,
        and a long tail of services carry snapshot-the-scalars workarounds for
        it.

        Expiring just the written row is not enough either, because the caller
        usually still holds that very instance. Instead the values that were
        just written are copied onto it as its loaded state: the database now
        holds exactly these values, so recording them is truthful and leaves
        nothing expired for anyone to trip over.

        SQL expressions are skipped - their result is only known to the
        database, so those attributes are expired individually and re-read on
        next access.
        """
        if not fields:
            return
        await self.session.execute(update(self.model).where(self.model.id == entity_id).values(**fields))
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(self.model, entity_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, entity_id: uuid.UUID) -> None:
        entity = await self.get_by_id(entity_id)
        if entity is not None:
            await self.session.delete(entity)
            await self.session.flush()


class SubcontractorRepository(_BaseRepo):
    """CRUD + filters for Subcontractor."""

    model = Subcontractor

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        prequalification_status: str | None = None,
        trade_category: str | None = None,
        active_only: bool = True,
    ) -> tuple[list[Subcontractor], int]:
        base = select(Subcontractor)
        if active_only:
            base = base.where(Subcontractor.is_active.is_(True))
        if prequalification_status is not None:
            base = base.where(Subcontractor.prequalification_status == prequalification_status)
        if trade_category is not None:
            # JSON contains check - keep simple/portable: load and filter in Python
            # for cross-dialect parity. For the typical N≤1000 catalogue this is
            # cheap and correct on both SQLite and Postgres.
            pass

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Subcontractor.legal_name).offset(offset).limit(limit)
        rows = list((await self.session.execute(stmt)).scalars().all())
        if trade_category is not None:
            rows = [r for r in rows if trade_category in (r.trade_categories or [])]
        return rows, total

    async def find_by_tax_id(
        self,
        tax_id: str,
        *,
        country: str | None = None,
    ) -> Subcontractor | None:
        """Look up an active subcontractor holding the same tax number.

        "Same" is decided by :func:`canonical_tax_id`, not by the stored
        string. ``tax_id`` is kept as typed, so ``CHE-123.456.789 MWST`` and
        ``che123456789`` sit in the column as two spellings of one number, and
        an equality on the column used to call them two firms. The query
        narrows to rows whose digit run matches - every canonicalisation keeps
        the digits and their order, so the run is a superset key SQL can
        compute - and the exact comparison happens on the identity key here.

        Used by ``SubcontractorService`` for the happy-path 409 on create and
        on a PATCH that changes the number. The partial unique index added in
        ``v3099_subcontractors_unique_tax_id`` stays the backstop for the
        exact-string race.
        """
        if not tax_id:
            return None
        country_u = country.upper()[:2] if country else None
        key = canonical_tax_id(country_u, tax_id)
        if not key:
            return None
        stmt = select(Subcontractor).where(
            Subcontractor.is_active.is_(True),
            func.regexp_replace(Subcontractor.tax_id, r"\D", "", "g") == tax_id_digit_run(tax_id),
        )
        if country_u:
            stmt = stmt.where(Subcontractor.country == country_u)
        rows = (await self.session.execute(stmt)).scalars().all()
        for row in rows:
            if canonical_tax_id(row.country or country_u, row.tax_id) == key:
                return row
        return None

    async def get_by_contact_id(self, contact_id: uuid.UUID) -> Subcontractor | None:
        """Resolve the subcontractor linked to a CRM ``Contact`` row.

        The unified vendor master is the existing ``Subcontractor.contact_id``
        column (it points at the same ``oe_contacts_contact`` row a
        procurement PO references via ``vendor_contact_id``). This lets the
        procurement gate and the PO-row badge look up a vendor's
        prequalification / block status from a contact id without a second
        link table. Returns the active match, newest first, or ``None`` when
        the contact is not a registered subcontractor.
        """
        stmt = (
            select(Subcontractor)
            .where(
                Subcontractor.contact_id == contact_id,
                Subcontractor.is_active.is_(True),
            )
            .order_by(Subcontractor.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_with_insurance_expiry_within(
        self,
        *,
        upper_bound: date,
        active_only: bool = True,
    ) -> list[Subcontractor]:
        """Return subs whose ``insurance_expiry_date`` is on/before ``upper_bound``.

        This includes already-past expiries - the sweep surfaces both
        "expiring soon" and "already expired" so the GC can chase
        renewals on a single list.  Subs whose expiry is NULL are NOT
        included (they need a separate "missing insurance" report).
        """
        stmt = select(Subcontractor).where(
            Subcontractor.insurance_expiry_date.is_not(None),
            Subcontractor.insurance_expiry_date <= upper_bound,
        )
        if active_only:
            stmt = stmt.where(Subcontractor.is_active.is_(True))
        stmt = stmt.order_by(Subcontractor.insurance_expiry_date)
        return list((await self.session.execute(stmt)).scalars().all())


class SubcontractorContactRepository(_BaseRepo):
    """CRUD for SubcontractorContact."""

    model = SubcontractorContact

    async def list_by_subcontractor(
        self,
        subcontractor_id: uuid.UUID,
    ) -> list[SubcontractorContact]:
        stmt = (
            select(SubcontractorContact)
            .where(SubcontractorContact.subcontractor_id == subcontractor_id)
            .order_by(SubcontractorContact.primary.desc(), SubcontractorContact.name)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class PrequalificationRepository(_BaseRepo):
    """CRUD for PrequalificationApplication."""

    model = PrequalificationApplication

    async def list_for_subcontractor(
        self,
        subcontractor_id: uuid.UUID,
    ) -> list[PrequalificationApplication]:
        stmt = (
            select(PrequalificationApplication)
            .where(PrequalificationApplication.subcontractor_id == subcontractor_id)
            .order_by(PrequalificationApplication.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_by_status(
        self,
        status: str,
        *,
        offset: int = 0,
        limit: int = 50,
    ) -> list[PrequalificationApplication]:
        stmt = (
            select(PrequalificationApplication)
            .where(PrequalificationApplication.status == status)
            .order_by(PrequalificationApplication.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return list((await self.session.execute(stmt)).scalars().all())


class CertificateRepository(_BaseRepo):
    """CRUD for Certificate."""

    model = Certificate

    async def list_by_subcontractor(
        self,
        subcontractor_id: uuid.UUID,
    ) -> list[Certificate]:
        stmt = (
            select(Certificate)
            .where(Certificate.subcontractor_id == subcontractor_id)
            .order_by(Certificate.valid_until.asc().nullslast())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_expiring_within(
        self,
        days: int,
        *,
        today: date | None = None,
        subcontractor_id: uuid.UUID | None = None,
    ) -> list[Certificate]:
        ref = today or date.today()
        upper = ref + timedelta(days=days)
        stmt = select(Certificate).where(
            Certificate.valid_until.is_not(None),
            Certificate.valid_until <= upper,
            Certificate.revoked.is_(False),
        )
        if subcontractor_id is not None:
            stmt = stmt.where(Certificate.subcontractor_id == subcontractor_id)
        stmt = stmt.order_by(Certificate.valid_until.asc())
        return list((await self.session.execute(stmt)).scalars().all())


class AgreementRepository(_BaseRepo):
    """CRUD for SubcontractAgreement."""

    model = SubcontractAgreement

    async def list_for_subcontractor(
        self,
        subcontractor_id: uuid.UUID,
        *,
        status: str | None = None,
    ) -> list[SubcontractAgreement]:
        stmt = select(SubcontractAgreement).where(
            SubcontractAgreement.subcontractor_id == subcontractor_id,
        )
        if status is not None:
            stmt = stmt.where(SubcontractAgreement.status == status)
        stmt = stmt.order_by(SubcontractAgreement.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
    ) -> list[SubcontractAgreement]:
        stmt = select(SubcontractAgreement).where(
            SubcontractAgreement.project_id == project_id,
        )
        if status is not None:
            stmt = stmt.where(SubcontractAgreement.status == status)
        stmt = stmt.order_by(SubcontractAgreement.created_at.desc())
        return list((await self.session.execute(stmt)).scalars().all())


class WorkPackageRepository(_BaseRepo):
    """CRUD for WorkPackage."""

    model = WorkPackage

    async def list_for_agreement(
        self,
        agreement_id: uuid.UUID,
    ) -> list[WorkPackage]:
        stmt = (
            select(WorkPackage).where(WorkPackage.agreement_id == agreement_id).order_by(WorkPackage.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())


class PaymentApplicationRepository(_BaseRepo):
    """CRUD for PaymentApplication."""

    model = PaymentApplication

    async def list_for_agreement(
        self,
        agreement_id: uuid.UUID,
        *,
        status: str | None = None,
    ) -> list[PaymentApplication]:
        stmt = select(PaymentApplication).where(
            PaymentApplication.agreement_id == agreement_id,
        )
        if status is not None:
            stmt = stmt.where(PaymentApplication.status == status)
        stmt = stmt.order_by(PaymentApplication.submitted_at.desc().nullslast())
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_open_for_agreements(
        self,
        agreement_ids: list[uuid.UUID],
    ) -> int:
        """Single-query count of payment apps in any non-terminal status
        for the supplied agreement set. Replaces the per-agreement loop
        in ``SubcontractorService.dashboard``.
        """
        if not agreement_ids:
            return 0
        stmt = (
            select(func.count())
            .select_from(PaymentApplication)
            .where(
                PaymentApplication.agreement_id.in_(agreement_ids),
                PaymentApplication.status.in_(
                    ("submitted", "foreman_approved", "finance_approved"),
                ),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def next_application_number(self, agreement_id: uuid.UUID) -> str:
        """Mint the next ``PA-NNNN`` number for an agreement.

        Two concurrent ``submit_payment_application`` calls on the same
        agreement would otherwise both read the same ``COUNT(*)`` and mint
        identical application numbers. To serialise them, take an exclusive
        row lock on the parent agreement first: the lock is held until the
        surrounding transaction commits, so a second concurrent transaction
        blocks here until the first has flushed its new payment row and then
        sees the updated count. Mirrors the ``with_for_update`` pattern used
        in cde/repository.py (``FOR UPDATE`` is honoured on PostgreSQL, the
        only supported backend).
        """
        lock_stmt = select(SubcontractAgreement.id).where(SubcontractAgreement.id == agreement_id).with_for_update()
        await self.session.execute(lock_stmt)

        stmt = (
            select(func.count()).select_from(PaymentApplication).where(PaymentApplication.agreement_id == agreement_id)
        )
        count = (await self.session.execute(stmt)).scalar_one()
        return f"PA-{count + 1:04d}"


class PaymentApplicationLineRepository(_BaseRepo):
    """CRUD for PaymentApplicationLine."""

    model = PaymentApplicationLine

    async def list_for_application(
        self,
        payment_application_id: uuid.UUID,
    ) -> list[PaymentApplicationLine]:
        stmt = select(PaymentApplicationLine).where(
            PaymentApplicationLine.payment_application_id == payment_application_id,
        )
        return list((await self.session.execute(stmt)).scalars().all())


class RetentionLedgerRepository(_BaseRepo):
    """CRUD for RetentionLedger."""

    model = RetentionLedger

    async def list_for_agreement(
        self,
        agreement_id: uuid.UUID,
    ) -> list[RetentionLedger]:
        stmt = (
            select(RetentionLedger)
            .where(RetentionLedger.agreement_id == agreement_id)
            .order_by(RetentionLedger.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_for_payment_application(
        self,
        payment_application_id: uuid.UUID,
    ) -> list[RetentionLedger]:
        """Return ledger entries tied to a single payment application."""
        stmt = (
            select(RetentionLedger)
            .where(RetentionLedger.payment_application_id == payment_application_id)
            .order_by(RetentionLedger.created_at.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def balance_for_agreements(
        self,
        agreement_ids: list[uuid.UUID],
    ) -> dict[uuid.UUID, Any]:
        """Return ``{agreement_id: (accrued, released)}`` in a single query.

        ``Decimal`` math happens in the caller. This collapses the
        per-agreement ``retention_balance`` loop in dashboard().
        """
        from decimal import Decimal

        if not agreement_ids:
            return {}
        stmt = (
            select(
                RetentionLedger.agreement_id,
                func.coalesce(func.sum(RetentionLedger.accrued_amount), 0),
                func.coalesce(func.sum(RetentionLedger.released_amount), 0),
            )
            .where(RetentionLedger.agreement_id.in_(agreement_ids))
            .group_by(RetentionLedger.agreement_id)
        )
        rows = (await self.session.execute(stmt)).all()
        out: dict[uuid.UUID, tuple[Any, Any]] = {}
        for ag_id, accrued, released in rows:
            out[ag_id] = (Decimal(str(accrued or 0)), Decimal(str(released or 0)))
        return out


class RatingRepository(_BaseRepo):
    """CRUD for SubcontractorRating."""

    model = SubcontractorRating

    async def list_for_subcontractor(
        self,
        subcontractor_id: uuid.UUID,
    ) -> list[SubcontractorRating]:
        stmt = (
            select(SubcontractorRating)
            .where(SubcontractorRating.subcontractor_id == subcontractor_id)
            .order_by(SubcontractorRating.period.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_for_period(
        self,
        subcontractor_id: uuid.UUID,
        period: str,
    ) -> SubcontractorRating | None:
        stmt = select(SubcontractorRating).where(
            SubcontractorRating.subcontractor_id == subcontractor_id,
            SubcontractorRating.period == period,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class LienWaiverRepository(_BaseRepo):
    """CRUD for LienWaiver."""

    model = LienWaiver

    async def list_for_subcontractor(
        self,
        subcontractor_id: uuid.UUID,
    ) -> list[LienWaiver]:
        """Return all waivers for a subcontractor, newest first."""
        stmt = (
            select(LienWaiver)
            .where(LienWaiver.subcontractor_id == subcontractor_id)
            .order_by(LienWaiver.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def list_for_payment_app(
        self,
        payment_application_id: uuid.UUID,
    ) -> list[LienWaiver]:
        """Return waivers attached to a single payment application."""
        stmt = (
            select(LienWaiver)
            .where(LienWaiver.payment_application_id == payment_application_id)
            .order_by(LienWaiver.created_at.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())
