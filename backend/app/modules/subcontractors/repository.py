"""‌⁠‍Data-access layer for the subcontractors module."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

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


class _BaseRepo:
    """‌⁠‍Shared CRUD primitives — keeps the per-entity repos compact."""

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
        if not fields:
            return
        await self.session.execute(update(self.model).where(self.model.id == entity_id).values(**fields))
        await self.session.flush()
        self.session.expire_all()

    async def delete(self, entity_id: uuid.UUID) -> None:
        entity = await self.get_by_id(entity_id)
        if entity is not None:
            await self.session.delete(entity)
            await self.session.flush()


class SubcontractorRepository(_BaseRepo):
    """‌⁠‍CRUD + filters for Subcontractor."""

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
            # JSON contains check — keep simple/portable: load and filter in Python
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
        """Look up an active subcontractor by ``(country, tax_id)``.

        Used by ``SubcontractorService.create_subcontractor`` for the
        happy-path 409 — backed by the partial unique index added in
        ``v3099_subcontractors_unique_tax_id``.
        """
        if not tax_id:
            return None
        stmt = select(Subcontractor).where(
            Subcontractor.tax_id == tax_id,
            Subcontractor.is_active.is_(True),
        )
        if country:
            stmt = stmt.where(Subcontractor.country == country.upper()[:2])
        stmt = stmt.limit(1)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_with_insurance_expiry_within(
        self,
        *,
        upper_bound: date,
        active_only: bool = True,
    ) -> list[Subcontractor]:
        """Return subs whose ``insurance_expiry_date`` is on/before ``upper_bound``.

        This includes already-past expiries — the sweep surfaces both
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
