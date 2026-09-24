# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Contracts data access layer."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import bindparam, func, select, update
from sqlalchemy import delete as sa_delete
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.contracts.models import (
    Contract,
    ContractDocument,
    ContractLine,
    ContractMilestone,
    ContractParty,
    ContractSecurity,
    ContractTemplate,
    ContractTemplateClause,
    ContractTypeConfiguration,
    EOTClaim,
    FeeStructure,
    FinalAccount,
    GainshareConfiguration,
    LDClause,
    ProgressClaim,
    ProgressClaimLine,
    RetentionRelease,
    RetentionSchedule,
)
from app.modules.contracts.periods import claim_order_key, claims_before


class _CRUDBase:
    """Common CRUD operations shared by all contracts repositories."""

    model: type
    session: AsyncSession

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, item_id: uuid.UUID) -> Any:
        return await self.session.get(self.model, item_id)

    async def create(self, item: Any) -> Any:
        self.session.add(item)
        await self.session.flush()
        return item

    async def update_fields(self, item_id: uuid.UUID, **fields: Any) -> None:
        """Update specific fields on one row.

        A Core UPDATE bypasses the ORM, so the in-memory copy of the row is
        stale afterwards. This used to reconcile that with
        ``session.expire_all()``, which invalidated every instance in the
        session rather than the one row being written. On an async session
        reading an expired attribute raises MissingGreenlet instead of
        lazy-loading, so callers crashed on objects this update never touched -
        committing a progress claim died on the contract it had loaded three
        statements earlier.

        The values that were just written are copied onto the instance as its
        loaded state instead: the database now holds exactly these values, so
        recording them is truthful and leaves nothing expired. SQL expressions
        are skipped, since only the database knows their result; those
        attributes are expired individually and re-read on next access.
        """
        await self.session.execute(update(self.model).where(self.model.id == item_id).values(**fields))
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(self.model, item_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, item_id: uuid.UUID) -> None:
        obj = await self.get_by_id(item_id)
        if obj is not None:
            await self.session.delete(obj)
            await self.session.flush()


class ContractRepository(_CRUDBase):
    model = Contract

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        counterparty_type: str | None = None,
        contract_type: str | None = None,
    ) -> tuple[list[Contract], int]:
        stmt = select(Contract).where(Contract.project_id == project_id)
        if status is not None:
            stmt = stmt.where(Contract.status == status)
        if counterparty_type is not None:
            stmt = stmt.where(Contract.counterparty_type == counterparty_type)
        if contract_type is not None:
            stmt = stmt.where(Contract.contract_type == contract_type)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        items = (
            (await self.session.execute(stmt.order_by(Contract.created_at.desc()).offset(offset).limit(limit)))
            .scalars()
            .all()
        )
        return list(items), total

    async def list_active_for_counterparty(
        self,
        counterparty_id: uuid.UUID,
    ) -> list[Contract]:
        stmt = select(Contract).where(
            Contract.counterparty_id == counterparty_id,
            Contract.status == "active",
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_code(self, code: str) -> Contract | None:
        result = await self.session.execute(select(Contract).where(Contract.code == code).limit(1))
        return result.scalar_one_or_none()


class ContractLineRepository(_CRUDBase):
    model = ContractLine

    async def list_for_contract(self, contract_id: uuid.UUID) -> list[ContractLine]:
        stmt = (
            select(ContractLine)
            .where(ContractLine.contract_id == contract_id)
            .order_by(ContractLine.order_index, ContractLine.code)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def bulk_create(self, lines: list[ContractLine]) -> list[ContractLine]:
        for line in lines:
            self.session.add(line)
        await self.session.flush()
        return lines


class ContractTypeConfigurationRepository(_CRUDBase):
    model = ContractTypeConfiguration

    async def list_all(self) -> list[ContractTypeConfiguration]:
        result = await self.session.execute(
            select(ContractTypeConfiguration).order_by(
                ContractTypeConfiguration.contract_type,
            )
        )
        return list(result.scalars().all())

    async def get_by_type(
        self,
        contract_type: str,
    ) -> ContractTypeConfiguration | None:
        result = await self.session.execute(
            select(ContractTypeConfiguration)
            .where(
                ContractTypeConfiguration.contract_type == contract_type,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()


class RetentionScheduleRepository(_CRUDBase):
    model = RetentionSchedule

    async def list_for_contract(
        self,
        contract_id: uuid.UUID,
    ) -> list[RetentionSchedule]:
        result = await self.session.execute(
            select(RetentionSchedule).where(
                RetentionSchedule.contract_id == contract_id,
            )
        )
        return list(result.scalars().all())


class RetentionReleaseRepository(_CRUDBase):
    model = RetentionRelease

    async def list_for_contract(self, contract_id: uuid.UUID) -> list[RetentionRelease]:
        """Every release on a contract, void ones included, oldest first."""
        result = await self.session.execute(
            select(RetentionRelease)
            .where(RetentionRelease.contract_id == contract_id)
            .order_by(RetentionRelease.created_at, RetentionRelease.id)
        )
        return list(result.scalars().all())

    async def billed_on_claims(self, claim_ids: list[uuid.UUID]) -> list[RetentionRelease]:
        """The releases billed on any of ``claim_ids``."""
        if not claim_ids:
            return []
        result = await self.session.execute(
            select(RetentionRelease).where(
                RetentionRelease.progress_claim_id.in_(claim_ids),
                RetentionRelease.status == "billed",
            )
        )
        return list(result.scalars().all())


class FeeStructureRepository(_CRUDBase):
    model = FeeStructure

    async def get_for_contract(self, contract_id: uuid.UUID) -> FeeStructure | None:
        result = await self.session.execute(
            select(FeeStructure)
            .where(
                FeeStructure.contract_id == contract_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()


class GainshareConfigurationRepository(_CRUDBase):
    model = GainshareConfiguration

    async def get_for_contract(
        self,
        contract_id: uuid.UUID,
    ) -> GainshareConfiguration | None:
        result = await self.session.execute(
            select(GainshareConfiguration)
            .where(
                GainshareConfiguration.contract_id == contract_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()


class LDClauseRepository(_CRUDBase):
    model = LDClause

    async def list_for_contract(self, contract_id: uuid.UUID) -> list[LDClause]:
        result = await self.session.execute(select(LDClause).where(LDClause.contract_id == contract_id))
        return list(result.scalars().all())


class ProgressClaimRepository(_CRUDBase):
    model = ProgressClaim

    async def claims_for_contract(
        self,
        contract_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
    ) -> tuple[list[ProgressClaim], int]:
        stmt = select(ProgressClaim).where(ProgressClaim.contract_id == contract_id)
        if status is not None:
            stmt = stmt.where(ProgressClaim.status == status)

        count_stmt = select(func.count()).select_from(stmt.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        items = (
            (await self.session.execute(stmt.order_by(ProgressClaim.created_at.desc()).offset(offset).limit(limit)))
            .scalars()
            .all()
        )
        return list(items), total

    async def ordered_for_contract(self, contract_id: uuid.UUID) -> list[ProgressClaim]:
        """Every claim on a contract in billing order, rejected ones included.

        Sorted in Python by :func:`~app.modules.contracts.periods.claim_order_key`
        rather than in SQL: a contract carries a few dozen claims at most, and
        one key function shared by every caller is worth more than an ORDER BY
        that would have to spell "undated last" per dialect. Callers that must
        skip rejected claims do so themselves, because "previous" for the
        period rules and "prior" for the money both skip them, while a list for
        display does not.
        """
        result = await self.session.execute(select(ProgressClaim).where(ProgressClaim.contract_id == contract_id))
        return sorted(result.scalars().all(), key=claim_order_key)

    async def prior_claims(self, contract_id: uuid.UUID, *, before_claim_id: uuid.UUID | None) -> list[ProgressClaim]:
        """The claims a payment application counts as previously certified.

        Strictly before ``before_claim_id`` in billing order, rejected ones
        left out: a rejected claim certified nothing. "Every other claim on the
        contract" is the reading this replaces, and it counted a later claim as
        previous whenever an earlier one was re-rendered or regenerated.
        ``None`` (a claim not stored yet) sees every claim on the contract.
        """
        ordered = await self.ordered_for_contract(contract_id)
        earlier = claims_before(ordered, before_claim_id) if before_claim_id is not None else ordered
        return [claim for claim in earlier if claim.status != "rejected"]

    async def claim_numbers_past_draft(self, contract_id: uuid.UUID) -> list[str]:
        """The numbers of the claims on a contract that have left draft, sorted.

        Read by the contract delete, which cascades to every claim. A claim
        billed without a schedule of values (T&M, cost-plus) has no lines, so
        the billed-line check cannot see it; this asks the claims directly.
        """
        result = await self.session.execute(
            select(ProgressClaim.claim_number).where(
                ProgressClaim.contract_id == contract_id,
                ProgressClaim.status != "draft",
            )
        )
        return sorted(number or "" for number in result.scalars().all())

    async def next_claim_number(self, contract_id: uuid.UUID) -> str:
        result = await self.session.execute(
            select(func.count()).select_from(ProgressClaim).where(ProgressClaim.contract_id == contract_id)
        )
        count = result.scalar_one()
        return f"PC-{count + 1:04d}"

    async def unpaid_claims_total(self, contract_id: uuid.UUID) -> Decimal:
        result = await self.session.execute(
            select(func.coalesce(func.sum(ProgressClaim.net_due), 0)).where(
                ProgressClaim.contract_id == contract_id,
                ProgressClaim.status.in_(("submitted", "approved", "certified")),
            )
        )
        value = result.scalar_one()
        return Decimal(str(value or 0))

    async def paid_total(self, contract_id: uuid.UUID) -> Decimal:
        result = await self.session.execute(
            select(func.coalesce(func.sum(ProgressClaim.net_due), 0)).where(
                ProgressClaim.contract_id == contract_id,
                ProgressClaim.status == "paid",
            )
        )
        value = result.scalar_one()
        return Decimal(str(value or 0))

    async def outstanding_retention(self, contract_id: uuid.UUID) -> Decimal:
        result = await self.session.execute(
            select(func.coalesce(func.sum(ProgressClaim.retention_amount), 0)).where(
                ProgressClaim.contract_id == contract_id,
                ProgressClaim.status.in_(("approved", "certified", "paid")),
            )
        )
        value = result.scalar_one()
        return Decimal(str(value or 0))


class ProgressClaimLineRepository(_CRUDBase):
    model = ProgressClaimLine

    async def list_for_claim(
        self,
        claim_id: uuid.UUID,
    ) -> list[ProgressClaimLine]:
        result = await self.session.execute(
            select(ProgressClaimLine).where(
                ProgressClaimLine.progress_claim_id == claim_id,
            )
        )
        return list(result.scalars().all())

    async def bulk_create(
        self,
        lines: list[ProgressClaimLine],
    ) -> list[ProgressClaimLine]:
        for line in lines:
            self.session.add(line)
        await self.session.flush()
        return lines

    async def claims_billing_lines(self, contract_line_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
        """Which of these schedule of values lines a claim has billed on, and which claims.

        Returns each billed line's id mapped to the numbers of the claims whose
        lines point at it, sorted; a line no claim line references is absent.
        This is the single definition of "billed" for a schedule line: the
        service refuses to rewrite or delete a line that appears here, and the
        line listing reports the same set, so the screen and the server cannot
        disagree about which lines are locked.

        Every claim status counts, a draft or a rejected one included. The
        foreign key from the claim line cascades, so deleting the schedule line
        takes the claim's lines with it whatever state the claim is in.
        """
        if not contract_line_ids:
            return {}
        stmt = (
            select(ProgressClaimLine.contract_line_id, ProgressClaim.claim_number)
            .join(ProgressClaim, ProgressClaim.id == ProgressClaimLine.progress_claim_id)
            .where(ProgressClaimLine.contract_line_id.in_(set(contract_line_ids)))
            .distinct()
        )
        billed: dict[uuid.UUID, list[str]] = {}
        for line_id, claim_number in (await self.session.execute(stmt)).all():
            billed.setdefault(line_id, []).append(claim_number or "")
        return {line_id: sorted(numbers) for line_id, numbers in billed.items()}

    async def update_fields_many(self, fields_by_id: dict[uuid.UUID, dict[str, Any]]) -> None:
        """Write the same columns on many claim lines in one statement.

        :meth:`update_fields` for a batch. ``fields_by_id`` maps a line's id
        to the values to write on it, and every entry names the same columns.
        One UPDATE goes out with a parameter set per line, where a loop over
        :meth:`update_fields` made a round trip per line, which on a long
        schedule of values was most of the time a claim took to work out.

        The values written are copied onto whichever of those lines the
        session already holds, as :meth:`update_fields` does and for the same
        reason: in an async session a stale attribute is not reloaded on
        access, and the certificate reads column I straight off these
        instances. Plain values only, since a SQL expression would leave the
        in-memory copy unknown.

        Raises:
            ValueError: the entries name different columns, or a value is a
                SQL expression.
        """
        if not fields_by_id:
            return
        names = sorted(next(iter(fields_by_id.values())))
        for values in fields_by_id.values():
            if sorted(values) != names:
                raise ValueError("update_fields_many needs every line to name the same columns")
            if any(isinstance(value, ClauseElement) for value in values.values()):
                raise ValueError("update_fields_many writes plain values, not SQL expressions")
        # Anything the unit of work still holds for these rows goes out first,
        # so a later flush cannot write an older value over this one.
        await self.session.flush()
        table = self.model.__table__
        columns = sa_inspect(self.model).columns
        stmt = (
            update(table)
            .where(table.c.id == bindparam("row_id"))
            .values({columns[name]: bindparam(f"new_{name}") for name in names})
        )
        await self.session.execute(
            stmt,
            [
                {"row_id": row_id, **{f"new_{name}": values[name] for name in names}}
                for row_id, values in fields_by_id.items()
            ],
        )
        for row_id, values in fields_by_id.items():
            instance = self.session.identity_map.get(identity_key(self.model, row_id))
            if instance is None:
                continue
            for name, value in values.items():
                set_committed_value(instance, name, value)

    async def delete_for_claim(self, claim_id: uuid.UUID) -> int:
        """Delete every claim line belonging to ``claim_id``.

        Returns the number of rows removed. Used by the Gap I progress bridge
        when committing a freshly-populated set of lines: the existing draft
        lines are wiped in one statement (instead of an N+1 per-row delete)
        before the new breakdown is inserted, so re-running the populate +
        commit is idempotent and never accumulates stale duplicate lines.
        """
        stmt = sa_delete(ProgressClaimLine).where(
            ProgressClaimLine.progress_claim_id == claim_id,
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(result.rowcount or 0)

    async def delete_for_claim_lines(self, claim_id: uuid.UUID, contract_line_ids: set[uuid.UUID]) -> int:
        """Delete this claim's lines on the given SoV lines, and only those.

        Committing a populate preview replaces the rows the person ticked. A
        line on any other SoV line, typed in by hand or left over from an
        earlier commit, is not part of that decision and stays.
        """
        if not contract_line_ids:
            return 0
        stmt = sa_delete(ProgressClaimLine).where(
            ProgressClaimLine.progress_claim_id == claim_id,
            ProgressClaimLine.contract_line_id.in_(contract_line_ids),
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return int(result.rowcount or 0)

    async def prior_period_value_by_line(
        self,
        contract_id: uuid.UUID,
        *,
        before_claim_id: uuid.UUID | None,
    ) -> dict[uuid.UUID, Decimal]:
        """Sum of ``period_completed_value`` per contract line across prior claims.

        This is G703 column D, work completed from previous applications, and
        the base every running ``cumulative_completed_value`` is built on.
        "Prior" is :meth:`ProgressClaimRepository.prior_claims`: the claims
        strictly before ``before_claim_id`` in billing order, rejected ones
        left out. It used to be every claim except the one being written,
        which counted a later claim as previous whenever an earlier one was
        regenerated or re-rendered. ``None`` (a claim not stored yet) counts
        every non-rejected claim. Returns ``{contract_line_id: Decimal}``.
        """
        prior = await ProgressClaimRepository(self.session).prior_claims(contract_id, before_claim_id=before_claim_id)
        if not prior:
            return {}
        stmt = (
            select(
                ProgressClaimLine.contract_line_id,
                func.coalesce(func.sum(ProgressClaimLine.period_completed_value), 0),
            )
            .where(ProgressClaimLine.progress_claim_id.in_([claim.id for claim in prior]))
            .group_by(ProgressClaimLine.contract_line_id)
        )
        result = await self.session.execute(stmt)
        return {row[0]: Decimal(str(row[1] or 0)) for row in result.all()}

    async def period_value_by_claim(self, contract_id: uuid.UUID) -> dict[uuid.UUID, Decimal]:
        """What each claim's own lines bill this period, summed per claim, for every claim on a contract.

        One aggregate rather than every claim line hydrated to add up a
        handful of numbers. A claim with no lines is absent, which reads as
        zero. Returns ``{progress_claim_id: Decimal}``.
        """
        stmt = (
            select(
                ProgressClaimLine.progress_claim_id,
                func.coalesce(func.sum(ProgressClaimLine.period_completed_value), 0),
            )
            .join(ProgressClaim, ProgressClaim.id == ProgressClaimLine.progress_claim_id)
            .where(ProgressClaim.contract_id == contract_id)
            .group_by(ProgressClaimLine.progress_claim_id)
        )
        result = await self.session.execute(stmt)
        return {row[0]: Decimal(str(row[1] or 0)) for row in result.all()}

    async def lines_with_claim_for_contract(
        self,
        contract_id: uuid.UUID,
    ) -> list[tuple[ProgressClaimLine, ProgressClaim]]:
        """All claim lines for a contract, each paired with its claim.

        Single JOIN query - replaces an N+1 (one claim-line query per
        progress claim) in the SoV-status rollup.

        It used to return the claim's status and nothing else, which was all
        the rollup needed while it only had to separate billed from paid. The
        rollup now also has to know which claim is the latest in billing
        order, and billing order is :func:`~app.modules.contracts.periods.claim_order_key`
        over three of the claim's own columns. Returning the claim hands the
        caller the whole ordering question instead of another column, and
        saves tagging derived values onto the line rows on the way out.

        No ORDER BY: the caller sorts by the shared key rather than by
        whatever this statement happened to return, for the reason given on
        :meth:`ProgressClaimRepository.ordered_for_contract`.
        """
        stmt = (
            select(ProgressClaimLine, ProgressClaim)
            .join(
                ProgressClaim,
                ProgressClaim.id == ProgressClaimLine.progress_claim_id,
            )
            .where(ProgressClaim.contract_id == contract_id)
        )
        result = await self.session.execute(stmt)
        return [(row[0], row[1]) for row in result.all()]


class FinalAccountRepository(_CRUDBase):
    model = FinalAccount

    async def get_for_contract(self, contract_id: uuid.UUID) -> FinalAccount | None:
        result = await self.session.execute(
            select(FinalAccount)
            .where(
                FinalAccount.contract_id == contract_id,
            )
            .limit(1)
        )
        return result.scalar_one_or_none()


class ContractPartyRepository(_CRUDBase):
    model = ContractParty

    async def list_for_contract(self, contract_id: uuid.UUID) -> list[ContractParty]:
        stmt = (
            select(ContractParty)
            .where(ContractParty.contract_id == contract_id)
            .order_by(ContractParty.is_primary.desc(), ContractParty.party_role)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class ContractSecurityRepository(_CRUDBase):
    model = ContractSecurity

    async def list_for_contract(
        self,
        contract_id: uuid.UUID,
        *,
        status: str | None = None,
        security_type: str | None = None,
    ) -> list[ContractSecurity]:
        stmt = select(ContractSecurity).where(ContractSecurity.contract_id == contract_id)
        if status is not None:
            stmt = stmt.where(ContractSecurity.status == status)
        if security_type is not None:
            stmt = stmt.where(ContractSecurity.security_type == security_type)
        result = await self.session.execute(stmt.order_by(ContractSecurity.created_at.desc()))
        return list(result.scalars().all())

    async def has_active_of_type(self, contract_id: uuid.UUID, security_type: str) -> bool:
        """True when an active security of the given type exists on the contract."""
        result = await self.session.execute(
            select(func.count())
            .select_from(ContractSecurity)
            .where(
                ContractSecurity.contract_id == contract_id,
                ContractSecurity.security_type == security_type,
                ContractSecurity.status == "active",
            )
        )
        return int(result.scalar_one() or 0) > 0


class EOTClaimRepository(_CRUDBase):
    model = EOTClaim

    async def list_for_contract(
        self,
        contract_id: uuid.UUID,
        *,
        status: str | None = None,
    ) -> list[EOTClaim]:
        stmt = select(EOTClaim).where(EOTClaim.contract_id == contract_id)
        if status is not None:
            stmt = stmt.where(EOTClaim.status == status)
        result = await self.session.execute(stmt.order_by(EOTClaim.created_at.desc()))
        return list(result.scalars().all())

    async def next_eot_number(self, contract_id: uuid.UUID) -> str:
        result = await self.session.execute(
            select(func.count()).select_from(EOTClaim).where(EOTClaim.contract_id == contract_id)
        )
        count = result.scalar_one()
        return f"EOT-{count + 1:04d}"

    async def total_days_granted(self, contract_id: uuid.UUID) -> int:
        """Sum of granted days across decided EOT claims on the contract."""
        result = await self.session.execute(
            select(func.coalesce(func.sum(EOTClaim.days_granted), 0)).where(
                EOTClaim.contract_id == contract_id,
                EOTClaim.status.in_(("granted", "partially_granted")),
            )
        )
        return int(result.scalar_one() or 0)


class ContractDocumentRepository(_CRUDBase):
    model = ContractDocument

    async def list_for_contract(
        self,
        contract_id: uuid.UUID,
        *,
        doc_role: str | None = None,
    ) -> list[ContractDocument]:
        stmt = select(ContractDocument).where(ContractDocument.contract_id == contract_id)
        if doc_role is not None:
            stmt = stmt.where(ContractDocument.doc_role == doc_role)
        result = await self.session.execute(stmt.order_by(ContractDocument.created_at.desc()))
        return list(result.scalars().all())


class ContractMilestoneRepository(_CRUDBase):
    model = ContractMilestone

    async def list_for_contract(self, contract_id: uuid.UUID) -> list[ContractMilestone]:
        stmt = (
            select(ContractMilestone)
            .where(ContractMilestone.contract_id == contract_id)
            .order_by(ContractMilestone.planned_date, ContractMilestone.code)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class ContractTemplateClauseRepository(_CRUDBase):
    model = ContractTemplateClause

    async def list_for_template(self, template_id: uuid.UUID) -> list[ContractTemplateClause]:
        stmt = (
            select(ContractTemplateClause)
            .where(ContractTemplateClause.template_id == template_id)
            .order_by(ContractTemplateClause.sort_order, ContractTemplateClause.number)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def delete_for_template(self, template_id: uuid.UUID) -> int:
        result = await self.session.execute(
            sa_delete(ContractTemplateClause).where(ContractTemplateClause.template_id == template_id)
        )
        return int(result.rowcount or 0)


class ContractTemplateRepository(_CRUDBase):
    """Authored clause templates, and the one place they are unioned with the built-ins.

    Nothing else in the codebase may compose the two halves. The built-in
    catalogue is a module constant that cannot be edited or versioned; this
    table holds what a tenant authored. Keeping the union here means the shape
    a caller sees is decided once, and the invariant that no code appears twice
    is testable rather than a convention.
    """

    model = ContractTemplate

    async def get_version(self, code: str, version: int) -> ContractTemplate | None:
        result = await self.session.execute(
            select(ContractTemplate).where(ContractTemplate.code == code, ContractTemplate.version == version).limit(1)
        )
        return result.scalar_one_or_none()

    async def list_versions(self, code: str) -> list[ContractTemplate]:
        result = await self.session.execute(
            select(ContractTemplate).where(ContractTemplate.code == code).order_by(ContractTemplate.version)
        )
        return list(result.scalars().all())

    async def max_version(self, code: str) -> int:
        """Highest version number under ``code``, or 0 when the code is unused."""
        result = await self.session.execute(
            select(func.max(ContractTemplate.version)).where(ContractTemplate.code == code)
        )
        return int(result.scalar() or 0)

    async def current_version(self, code: str) -> ContractTemplate | None:
        """The version a caller means when it names a code and no number.

        The latest published version, or the latest draft when the template has
        never been published. An archived version is never current: archiving is
        how a tenant retires paper it no longer signs, and resolving to it would
        make the retirement invisible.
        """
        published = await self.session.execute(
            select(ContractTemplate)
            .where(ContractTemplate.code == code, ContractTemplate.status == "published")
            .order_by(ContractTemplate.version.desc())
            .limit(1)
        )
        row = published.scalar_one_or_none()
        if row is not None:
            return row
        draft = await self.session.execute(
            select(ContractTemplate)
            .where(ContractTemplate.code == code, ContractTemplate.status == "draft")
            .order_by(ContractTemplate.version.desc())
            .limit(1)
        )
        return draft.scalar_one_or_none()

    async def list_current(self) -> list[ContractTemplate]:
        """One row per authored lineage: its current version, as defined above.

        Written as a Python fold over one ordered SELECT rather than a window
        function, because the authored catalogue is tenant-sized (tens of rows,
        not thousands) and a correlated subquery here would have to be written
        twice for the published-else-draft rule.
        """
        result = await self.session.execute(
            select(ContractTemplate).order_by(ContractTemplate.code, ContractTemplate.version)
        )
        best: dict[str, ContractTemplate] = {}
        for row in result.scalars().all():
            if row.status == "archived":
                continue
            held = best.get(row.code)
            if held is None:
                best[row.code] = row
                continue
            # Published outranks draft regardless of number, so publishing v2
            # stays current while v3 is still being drafted. Within one status
            # the higher version wins, and the ORDER BY already delivers those
            # in ascending order.
            if held.status == "published" and row.status != "published":
                continue
            best[row.code] = row
        return [best[code] for code in sorted(best)]

    async def list_all(self) -> list[dict[str, Any]]:
        """Every template a user may choose from: built-in first, then authored.

        This is the union point named in the class docstring. Every entry has
        the same keys whichever half it came from, and two of them say which
        half that was:

            source    "builtin" | "authored"
            editable  False for a built-in, True for an authored draft

        A built-in reports ``version`` 0 rather than null, so a caller never has
        to branch on the type of the field to sort or compare it. Zero reads as
        "not a versioned template", which is exactly what a constant is.
        """
        from app.modules.contracts.service import list_contract_templates

        entries: list[dict[str, Any]] = []
        for builtin in list_contract_templates():
            entries.append(
                {
                    "code": builtin["code"],
                    "name": builtin["name"],
                    "family": builtin["family"],
                    "description": "",
                    "retention_release_event": builtin["retention_release_event"],
                    "clause_count": builtin["clause_count"],
                    "source": "builtin",
                    "editable": False,
                    "version": 0,
                    "status": "published",
                    "derived_from_builtin": None,
                    "template_id": None,
                }
            )

        rows = await self.list_current()
        if rows:
            counts = await self.session.execute(
                select(
                    ContractTemplateClause.template_id,
                    func.count(ContractTemplateClause.id),
                )
                .where(ContractTemplateClause.template_id.in_([row.id for row in rows]))
                .group_by(ContractTemplateClause.template_id)
            )
            clause_counts = {template_id: count for template_id, count in counts.all()}
        else:
            clause_counts = {}

        for row in rows:
            entries.append(
                {
                    "code": row.code,
                    "name": row.name,
                    "family": row.family,
                    "description": row.description,
                    "retention_release_event": row.retention_release_event,
                    "clause_count": int(clause_counts.get(row.id, 0)),
                    "source": "authored",
                    "editable": row.status == "draft",
                    "version": row.version,
                    "status": row.status,
                    "derived_from_builtin": row.derived_from_builtin,
                    "template_id": str(row.id),
                }
            )
        return entries
