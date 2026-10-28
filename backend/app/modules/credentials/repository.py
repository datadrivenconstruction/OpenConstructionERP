# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Professional-credentials data-access layer.

Holds the SQL half of the one status rule. :func:`effective_status_expr` is the
database mirror of :func:`app.modules.credentials.service.recompute_status`, and
the two must agree for every input - a register that filters rows by one rule
and labels them by another is worse than one that is merely stale, because the
disagreement is invisible. ``tests/modules/credentials/test_credentials_status_agreement.py``
drives a matrix through both and fails the moment they diverge.

Why an expression rather than the stored column: ``status`` is written only when
someone writes to the row. A credential that simply ages into its reminder
window is never written to, so every query that trusts the stored column misses
exactly the rows the register exists to surface.
"""

from __future__ import annotations

import uuid
from datetime import date as _date

import sqlalchemy as sa
from sqlalchemy import Integer, case, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.credentials.models import Credential, CredentialRequirement
from app.modules.credentials.schemas import PERSONNEL_CREDENTIAL_TYPES

# The expiry-alert buckets, shared by the "expiring soon" query and the
# dashboard widget. A perpetual credential (no valid_until) never enters these.
_ALERT_STATUSES: tuple[str, ...] = ("expiring_soon", "expired")

# Manual states the date arithmetic must never overwrite. Kept in sync with the
# service-side frozenset of the same name; the agreement test pins that.
_MANUAL_STATUSES: tuple[str, ...] = ("suspended", "revoked")


def in_register() -> sa.ColumnElement[bool]:
    """Rows the register shows: everything except personnel documents, which the staffing file serves."""
    return Credential.credential_type.not_in(PERSONNEL_CREDENTIAL_TYPES)


def days_until_expiry_expr(today: _date) -> sa.ColumnElement[int]:
    """Signed days from ``today`` to ``valid_until``, as a SQL expression.

    PostgreSQL returns an integer for ``date - date``. ``type_coerce`` tells
    SQLAlchemy that without emitting a redundant CAST, so the value compares
    cleanly against the integer ``notify_days_before`` column.
    """
    return sa.type_coerce(Credential.valid_until - today, Integer)


def effective_status_expr(today: _date) -> sa.ColumnElement[str]:
    """The status a credential actually has on ``today``, computed in SQL.

    Mirrors :func:`app.modules.credentials.service.recompute_status` exactly,
    including the inclusive reminder boundary and the precedence of manual
    states over the date arithmetic.
    """
    days_left = days_until_expiry_expr(today)
    return case(
        (Credential.status.in_(_MANUAL_STATUSES), Credential.status),
        (Credential.valid_until.is_(None), literal("active")),
        (Credential.valid_until < today, literal("expired")),
        (days_left <= func.greatest(Credential.notify_days_before, 0), literal("expiring_soon")),
        else_=literal("active"),
    )


class CredentialRepository:
    """Data access for :class:`Credential` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, credential_id: uuid.UUID) -> Credential | None:
        return await self.session.get(Credential, credential_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        today: _date,
        status: str | None = None,
        credential_type: str | None = None,
        holder_user_id: uuid.UUID | None = None,
    ) -> list[Credential]:
        """List a project's credentials, filtering on the *derived* status.

        Filtering on the stored column would drop rows that aged into the
        requested bucket without being written to since, which is the common
        case for anything expiring.
        """
        stmt = select(Credential).where(Credential.project_id == project_id, in_register())
        if status is not None:
            stmt = stmt.where(effective_status_expr(today) == status)
        if credential_type is not None:
            stmt = stmt.where(Credential.credential_type == credential_type)
        if holder_user_id is not None:
            stmt = stmt.where(Credential.holder_user_id == holder_user_id)
        # Perpetual credentials (NULL valid_until) sort last; the rest ascend by
        # expiry so the most-urgent rows lead, matching the UI default.
        stmt = stmt.order_by(
            Credential.valid_until.is_(None),
            Credential.valid_until.asc(),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_expiring_soon(
        self,
        project_id: uuid.UUID,
        *,
        today: _date,
        limit: int = 50,
    ) -> list[Credential]:
        """Credentials already lapsed or inside their reminder window.

        Uses the derived status, so a row that quietly aged past its threshold
        appears here on the day it does, not on the day someone next edits it.
        """
        stmt = (
            select(Credential)
            .where(
                Credential.project_id == project_id,
                in_register(),
                effective_status_expr(today).in_(_ALERT_STATUSES),
            )
            .order_by(Credential.valid_until.asc())
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_drifted(
        self,
        project_id: uuid.UUID,
        *,
        today: _date,
        register_only: bool = False,
    ) -> list[Credential]:
        """Rows whose stored status no longer matches the derived one.

        The status refresh covers every row, personnel documents included: their
        expiry alert is what reminds the people responsible. ``register_only``
        is for counts the register displays.
        """
        stmt = select(Credential).where(
            Credential.project_id == project_id,
            effective_status_expr(today) != Credential.status,
        )
        if register_only:
            stmt = stmt.where(in_register())
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_by_effective_status(
        self,
        project_id: uuid.UUID,
        *,
        today: _date,
    ) -> dict[str, int]:
        """Grouped counts keyed by derived status, for the summary tile."""
        status_col = effective_status_expr(today).label("status")
        stmt = (
            select(status_col, func.count())
            .where(Credential.project_id == project_id, in_register())
            .group_by(status_col)
        )
        result = await self.session.execute(stmt)
        return {row[0]: int(row[1]) for row in result.all()}

    async def count_matching(
        self,
        project_id: uuid.UUID,
        *conditions: sa.ColumnElement[bool],
    ) -> int:
        """Count a project's credentials that satisfy extra ``conditions``."""
        stmt = (
            select(func.count())
            .select_from(Credential)
            .where(Credential.project_id == project_id, in_register(), *conditions)
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def create(self, credential: Credential) -> Credential:
        self.session.add(credential)
        await self.session.flush()
        return credential

    async def delete(self, credential_id: uuid.UUID) -> None:
        row = await self.get_by_id(credential_id)
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()


class RequirementRepository:
    """Data access for :class:`CredentialRequirement` rows."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, requirement_id: uuid.UUID) -> CredentialRequirement | None:
        return await self.session.get(CredentialRequirement, requirement_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        include_inactive: bool = False,
    ) -> list[CredentialRequirement]:
        stmt = select(CredentialRequirement).where(CredentialRequirement.project_id == project_id)
        if not include_inactive:
            stmt = stmt.where(CredentialRequirement.is_active.is_(True))
        stmt = stmt.order_by(
            # Blocking rules lead: they are the ones that stop work.
            CredentialRequirement.is_blocking.desc(),
            CredentialRequirement.credential_type.asc(),
            CredentialRequirement.applies_to.asc(),
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def find_conflict(
        self,
        project_id: uuid.UUID,
        *,
        credential_type: str,
        applies_to: str,
        holder_kind: str,
        exclude_id: uuid.UUID | None = None,
    ) -> CredentialRequirement | None:
        """Find a requirement already covering this scope.

        Checked in the service before a write so a duplicate answers 409 rather
        than surfacing as a raw unique-constraint IntegrityError.
        """
        stmt = select(CredentialRequirement).where(
            CredentialRequirement.project_id == project_id,
            CredentialRequirement.credential_type == credential_type,
            CredentialRequirement.applies_to == applies_to,
            CredentialRequirement.holder_kind == holder_kind,
        )
        if exclude_id is not None:
            stmt = stmt.where(CredentialRequirement.id != exclude_id)
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create(self, requirement: CredentialRequirement) -> CredentialRequirement:
        self.session.add(requirement)
        await self.session.flush()
        return requirement

    async def delete(self, requirement_id: uuid.UUID) -> None:
        row = await self.get_by_id(requirement_id)
        if row is not None:
            await self.session.delete(row)
            await self.session.flush()


__all__ = [
    "CredentialRepository",
    "RequirementRepository",
    "days_until_expiry_expr",
    "effective_status_expr",
    "in_register",
]
