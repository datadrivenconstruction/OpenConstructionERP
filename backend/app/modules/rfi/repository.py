# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""RFI data access layer."""

import uuid

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.rfi.models import RFI, RFIRequestType
from app.modules.rfi.request_types import format_request_number, number_regex


class RFIRepository:
    """Data access for RFI models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, rfi_id: uuid.UUID) -> RFI | None:
        return await self.session.get(RFI, rfi_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        offset: int = 0,
        limit: int = 50,
        status: str | None = None,
        search: str | None = None,
        with_total: bool = True,
        request_type: str | None = None,
    ) -> tuple[list[RFI], int]:
        """List a page of RFIs for a project, newest first.

        PERF: when ``with_total`` is False the ``COUNT(*)`` over the (possibly
        ILIKE-filtered) base query is skipped entirely - that aggregate is a
        second scan of the same predicate, and the list endpoint discards the
        count anyway (it returns a bare ``list[RFIResponse]``). Callers that
        actually need the total (paginated views / tests asserting the count)
        keep the default ``True``. When skipped, the returned total is the
        length of the page slice so the tuple shape never changes.
        """
        base = select(RFI).where(RFI.project_id == project_id)
        if status is not None:
            base = base.where(RFI.status == status)
        if request_type is not None:
            base = base.where(RFI.request_type == request_type)

        if search and search.strip():
            pattern = f"%{search.strip()}%"
            base = base.where(
                or_(
                    RFI.subject.ilike(pattern),
                    RFI.question.ilike(pattern),
                    RFI.official_response.ilike(pattern),
                    RFI.rfi_number.ilike(pattern),
                )
            )

        stmt = base.order_by(RFI.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        rows = list(result.scalars().all())

        if not with_total:
            return rows, len(rows)

        count_stmt = select(func.count()).select_from(base.subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        return rows, total

    async def next_rfi_number(self, project_id: uuid.UUID, *, prefix: str = "RFI", digits: int = 3) -> str:
        """Generate the next ``<PREFIX>-<N>`` number of one request type using MAX to avoid duplicates.

        Numbering runs per prefix inside the project: ``TQ-0001`` and
        ``RFI-001`` count independently. Only canonical ``<PREFIX>-<digits>``
        rows are cast: PostgreSQL rejects an empty or non-numeric integer cast
        (unlike SQLite, which yielded 0), so one legacy or externally-numbered
        row would otherwise raise on every new request for the project. The
        anchored pattern also keeps ``SBQ-0001`` out of the ``SQ`` sequence.
        """
        from sqlalchemy import Integer as SAInteger
        from sqlalchemy import cast
        from sqlalchemy.sql import func as sqlfunc

        # Extract the numeric suffix (e.g. 'TQ-0007' -> 7).
        stmt = (
            select(
                sqlfunc.coalesce(
                    sqlfunc.max(cast(func.substr(RFI.rfi_number, len(prefix) + 2), SAInteger)),
                    0,
                )
            )
            .where(RFI.project_id == project_id)
            .where(RFI.rfi_number.regexp_match(number_regex(prefix)))
        )
        max_num = (await self.session.execute(stmt)).scalar_one()
        return format_request_number(prefix, max_num + 1, digits)

    async def create(self, rfi: RFI) -> RFI:
        self.session.add(rfi)
        await self.session.flush()
        return rfi

    async def update_fields(self, rfi_id: uuid.UUID, **fields: object) -> None:
        stmt = update(RFI).where(RFI.id == rfi_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(RFI, rfi_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, rfi_id: uuid.UUID) -> None:
        rfi = await self.get_by_id(rfi_id)
        if rfi is not None:
            await self.session.delete(rfi)
            await self.session.flush()


class RequestTypeRepository:
    """Data access for a project's request type catalogue."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, type_id: uuid.UUID) -> RFIRequestType | None:
        return await self.session.get(RFIRequestType, type_id)

    async def list_for_project(self, project_id: uuid.UUID) -> list[RFIRequestType]:
        stmt = (
            select(RFIRequestType)
            .where(RFIRequestType.project_id == project_id)
            .order_by(RFIRequestType.sort_order, RFIRequestType.code)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_by_code(self, project_id: uuid.UUID, code: str) -> RFIRequestType | None:
        stmt = select(RFIRequestType).where(RFIRequestType.project_id == project_id, RFIRequestType.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def add(self, row: RFIRequestType) -> RFIRequestType:
        self.session.add(row)
        await self.session.flush()
        return row

    async def delete(self, row: RFIRequestType) -> None:
        await self.session.delete(row)
        await self.session.flush()

    async def request_counts(self, project_id: uuid.UUID) -> dict[str, int]:
        """How many requests of each type code the project holds."""
        stmt = select(RFI.request_type, func.count()).where(RFI.project_id == project_id).group_by(RFI.request_type)
        return {code: int(n) for code, n in (await self.session.execute(stmt)).all()}
