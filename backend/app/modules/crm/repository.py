# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠CRM data access layer."""

from __future__ import annotations

import uuid
from datetime import date as _date
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.crm.models import (
    Account,
    CrmActivity,
    Forecast,
    Lead,
    Opportunity,
    OpportunityStageHistory,
    PipelineStage,
    WinLossReason,
)

# ── Generic helpers ──────────────────────────────────────────────────────


async def _update_fields(
    session: AsyncSession,
    model: Any,
    pk: uuid.UUID,
    **fields: Any,
) -> None:
    """Update one row by primary key and keep the identity map honest.

    Expiring the whole session would be right for the row that changed and
    wrong for every other object the caller still holds. Under asyncio the next
    attribute read on any of them is a lazy load attempted from async code,
    which raises MissingGreenlet rather than quietly re-fetching. So the values
    we already know are written straight onto the instance, and only the ones
    the database had to compute are expired so they get read back.
    """
    if not fields:
        return
    stmt = update(model).where(model.id == pk).values(**fields)
    await session.execute(stmt)
    await session.flush()
    instance = session.identity_map.get(identity_key(model, pk))
    if instance is None:
        return
    computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
    for name, value in fields.items():
        if name not in computed:
            set_committed_value(instance, name, value)
    if computed:
        session.expire(instance, computed)


# ── Account ──────────────────────────────────────────────────────────────


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, account_id: uuid.UUID) -> Account | None:
        return await self.session.get(Account, account_id)

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        industry: str | None = None,
        owner_user_id: uuid.UUID | None = None,
        status: str | None = None,
    ) -> tuple[list[Account], int]:
        base = select(Account)
        if industry is not None:
            base = base.where(Account.industry == industry)
        if owner_user_id is not None:
            base = base.where(Account.owner_user_id == owner_user_id)
        if status is not None:
            base = base.where(Account.status == status)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Account.name.asc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def list_by_owner(self, owner_user_id: uuid.UUID) -> list[Account]:
        stmt = select(Account).where(Account.owner_user_id == owner_user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, account: Account) -> Account:
        self.session.add(account)
        await self.session.flush()
        return account

    async def update_fields(self, account_id: uuid.UUID, **fields: Any) -> None:
        await _update_fields(self.session, Account, account_id, **fields)

    async def delete(self, account_id: uuid.UUID) -> None:
        account = await self.get_by_id(account_id)
        if account is not None:
            await self.session.delete(account)
            await self.session.flush()


# ── Lead ──────────────────────────────────────────────────────────────────


class LeadRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, lead_id: uuid.UUID) -> Lead | None:
        return await self.session.get(Lead, lead_id)

    async def find_by_email(self, email: str) -> Lead | None:
        """Return the most-recent lead carrying ``email`` (case-insensitive).

        Used by ``CrmService.create_lead`` to translate concurrent inbound
        webhooks targeting the same address into a deterministic 409 instead
        of a duplicate-row silent-success or an IntegrityError 500.
        """
        normalised = email.strip().lower() if email else None
        if not normalised:
            return None
        stmt = (
            select(Lead).where(func.lower(Lead.contact_email) == normalised).order_by(Lead.created_at.desc()).limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        assigned_to: uuid.UUID | None = None,
        source: str | None = None,
    ) -> tuple[list[Lead], int]:
        base = select(Lead)
        if status is not None:
            base = base.where(Lead.status == status)
        if assigned_to is not None:
            base = base.where(Lead.assigned_to == assigned_to)
        if source is not None:
            base = base.where(Lead.source == source)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Lead.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def create(self, lead: Lead) -> Lead:
        self.session.add(lead)
        await self.session.flush()
        return lead

    async def update_fields(self, lead_id: uuid.UUID, **fields: Any) -> None:
        await _update_fields(self.session, Lead, lead_id, **fields)

    async def delete(self, lead_id: uuid.UUID) -> None:
        lead = await self.get_by_id(lead_id)
        if lead is not None:
            await self.session.delete(lead)
            await self.session.flush()


# ── Opportunity ──────────────────────────────────────────────────────────


class OpportunityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, opportunity_id: uuid.UUID) -> Opportunity | None:
        return await self.session.get(Opportunity, opportunity_id)

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        owner_user_id: uuid.UUID | None = None,
        stage_id: uuid.UUID | None = None,
        status: str | None = None,
        account_id: uuid.UUID | None = None,
    ) -> tuple[list[Opportunity], int]:
        base = select(Opportunity)
        if owner_user_id is not None:
            base = base.where(Opportunity.owner_user_id == owner_user_id)
        if stage_id is not None:
            base = base.where(Opportunity.stage_id == stage_id)
        if status is not None:
            base = base.where(Opportunity.status == status)
        if account_id is not None:
            base = base.where(Opportunity.account_id == account_id)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(Opportunity.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def list_by_owner(self, owner_user_id: uuid.UUID) -> list[Opportunity]:
        stmt = select(Opportunity).where(Opportunity.owner_user_id == owner_user_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_stage(self, stage_id: uuid.UUID) -> list[Opportunity]:
        stmt = select(Opportunity).where(Opportunity.stage_id == stage_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_open(self) -> list[Opportunity]:
        stmt = select(Opportunity).where(Opportunity.status == "open")
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_won_between(self, start: str, end: str) -> list[Opportunity]:
        stmt = select(Opportunity).where(
            Opportunity.status == "won",
            Opportunity.won_at.isnot(None),
            Opportunity.won_at >= start,
            Opportunity.won_at <= end,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_lost_between(self, start: str, end: str) -> list[Opportunity]:
        stmt = select(Opportunity).where(
            Opportunity.status == "lost",
            Opportunity.lost_at.isnot(None),
            Opportunity.lost_at >= start,
            Opportunity.lost_at <= end,
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def pipeline_value_by_owner(self) -> dict[uuid.UUID | None, Decimal]:
        """Aggregate sum(estimated_value) for open opportunities grouped by owner.

        Returns Decimal - Round-5 audit closed the legacy float coercion
        that silently drifted cents per million-dollar pipeline. Money
        flows here feed the dashboard cards and forecast comparisons, so
        cent-exactness is load-bearing.
        """
        stmt = (
            select(Opportunity.owner_user_id, func.coalesce(func.sum(Opportunity.estimated_value), 0))
            .where(Opportunity.status == "open")
            .group_by(Opportunity.owner_user_id)
        )
        result = await self.session.execute(stmt)
        return {row[0]: Decimal(str(row[1] or 0)) for row in result.all()}

    async def opportunities_closing_within_days(self, days: int) -> list[Opportunity]:
        """Return open opportunities with expected_close_date within ``days`` from today."""
        from datetime import timedelta as _td

        today = _date.today()
        horizon = today + _td(days=days)
        stmt = select(Opportunity).where(
            Opportunity.status == "open",
            Opportunity.expected_close_date.isnot(None),
            Opportunity.expected_close_date >= today.isoformat(),
            Opportunity.expected_close_date <= horizon.isoformat(),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, opportunity: Opportunity) -> Opportunity:
        self.session.add(opportunity)
        await self.session.flush()
        return opportunity

    async def update_fields(self, opportunity_id: uuid.UUID, **fields: Any) -> None:
        await _update_fields(self.session, Opportunity, opportunity_id, **fields)

    async def delete(self, opportunity_id: uuid.UUID) -> None:
        opp = await self.get_by_id(opportunity_id)
        if opp is not None:
            await self.session.delete(opp)
            await self.session.flush()


# ── PipelineStage ────────────────────────────────────────────────────────


class PipelineStageRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, stage_id: uuid.UUID) -> PipelineStage | None:
        return await self.session.get(PipelineStage, stage_id)

    async def get_by_code(self, code: str) -> PipelineStage | None:
        stmt = select(PipelineStage).where(PipelineStage.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self) -> list[PipelineStage]:
        stmt = select(PipelineStage).order_by(PipelineStage.display_order.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, stage: PipelineStage) -> PipelineStage:
        self.session.add(stage)
        await self.session.flush()
        return stage

    async def update_fields(self, stage_id: uuid.UUID, **fields: Any) -> None:
        await _update_fields(self.session, PipelineStage, stage_id, **fields)

    async def delete(self, stage_id: uuid.UUID) -> None:
        stage = await self.get_by_id(stage_id)
        if stage is not None:
            await self.session.delete(stage)
            await self.session.flush()


# ── OpportunityStageHistory ──────────────────────────────────────────────


class StageHistoryRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, history: OpportunityStageHistory) -> OpportunityStageHistory:
        self.session.add(history)
        await self.session.flush()
        return history

    async def list_for_opportunity(self, opportunity_id: uuid.UUID) -> list[OpportunityStageHistory]:
        stmt = (
            select(OpportunityStageHistory)
            .where(OpportunityStageHistory.opportunity_id == opportunity_id)
            .order_by(OpportunityStageHistory.created_at.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ── Activity ─────────────────────────────────────────────────────────────


class ActivityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, activity_id: uuid.UUID) -> CrmActivity | None:
        return await self.session.get(CrmActivity, activity_id)

    async def list_all(
        self,
        *,
        offset: int = 0,
        limit: int = 50,
        owner_user_id: uuid.UUID | None = None,
        opportunity_id: uuid.UUID | None = None,
        account_id: uuid.UUID | None = None,
        lead_id: uuid.UUID | None = None,
        kind: str | None = None,
        due_before: str | None = None,
    ) -> tuple[list[CrmActivity], int]:
        base = select(CrmActivity)
        if owner_user_id is not None:
            base = base.where(CrmActivity.owner_user_id == owner_user_id)
        if opportunity_id is not None:
            base = base.where(CrmActivity.opportunity_id == opportunity_id)
        if account_id is not None:
            base = base.where(CrmActivity.account_id == account_id)
        if lead_id is not None:
            base = base.where(CrmActivity.lead_id == lead_id)
        if kind is not None:
            base = base.where(CrmActivity.kind == kind)
        if due_before is not None:
            base = base.where(
                CrmActivity.due_at.isnot(None),
                CrmActivity.due_at <= due_before,
            )

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()

        stmt = base.order_by(CrmActivity.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all()), total

    async def count_for_lead(self, lead_id: uuid.UUID) -> int:
        """Number of activities logged against a lead.

        ``CrmActivity.lead_id`` is ``ON DELETE CASCADE``, so deleting the lead
        does not fail on these rows - it takes every logged call, email and
        meeting with it, without a word. Counting them is what lets the delete
        say so first.
        """
        stmt = select(func.count()).select_from(CrmActivity).where(CrmActivity.lead_id == lead_id)
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def create(self, activity: CrmActivity) -> CrmActivity:
        self.session.add(activity)
        await self.session.flush()
        return activity

    async def update_fields(self, activity_id: uuid.UUID, **fields: Any) -> None:
        await _update_fields(self.session, CrmActivity, activity_id, **fields)

    async def delete(self, activity_id: uuid.UUID) -> None:
        activity = await self.get_by_id(activity_id)
        if activity is not None:
            await self.session.delete(activity)
            await self.session.flush()


# ── Forecast ─────────────────────────────────────────────────────────────


class ForecastRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_period(self, period: str, owner_user_id: uuid.UUID | None = None) -> Forecast | None:
        stmt = select(Forecast).where(Forecast.period == period)
        if owner_user_id is None:
            stmt = stmt.where(Forecast.owner_user_id.is_(None))
        else:
            stmt = stmt.where(Forecast.owner_user_id == owner_user_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, forecast: Forecast) -> Forecast:
        self.session.add(forecast)
        await self.session.flush()
        return forecast

    async def upsert(self, forecast: Forecast) -> Forecast:
        existing = await self.get_by_period(forecast.period, forecast.owner_user_id)
        if existing is not None:
            existing.pipeline_value = forecast.pipeline_value
            existing.weighted_value = forecast.weighted_value
            existing.won_value = forecast.won_value
            existing.committed_value = forecast.committed_value
            existing.computed_at = forecast.computed_at
            # Refreshed with the rest. A field copied on create but not here
            # would leave the previous run's breakdown standing beside this
            # run's totals, which is a worse failure than dropping it: the two
            # halves of the row would describe different days and nothing would
            # say so.
            existing.by_currency = forecast.by_currency
            existing.mixed_currency = forecast.mixed_currency
            await self.session.flush()
            return existing
        return await self.create(forecast)

    async def list_all(self) -> list[Forecast]:
        stmt = select(Forecast).order_by(Forecast.period.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


# ── WinLossReason ────────────────────────────────────────────────────────


class WinLossReasonRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, reason_id: uuid.UUID) -> WinLossReason | None:
        return await self.session.get(WinLossReason, reason_id)

    async def get_by_code(self, code: str) -> WinLossReason | None:
        stmt = select(WinLossReason).where(WinLossReason.code == code)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_all(self) -> list[WinLossReason]:
        stmt = select(WinLossReason).order_by(WinLossReason.code.asc())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, reason: WinLossReason) -> WinLossReason:
        self.session.add(reason)
        await self.session.flush()
        return reason

    async def update_fields(self, reason_id: uuid.UUID, **fields: Any) -> None:
        await _update_fields(self.session, WinLossReason, reason_id, **fields)

    async def delete(self, reason_id: uuid.UUID) -> None:
        reason = await self.get_by_id(reason_id)
        if reason is not None:
            await self.session.delete(reason)
            await self.session.flush()
