# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Takeoff data access layer."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.util import identity_key
from sqlalchemy.sql.elements import ClauseElement

from app.modules.takeoff.models import AiTakeoffRun, TakeoffDocument, TakeoffMeasurement


class TakeoffRepository:
    """Data access for TakeoffDocument model."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, doc_id: uuid.UUID) -> TakeoffDocument | None:
        return await self.session.get(TakeoffDocument, doc_id)

    async def list_for_user(
        self,
        owner_id: uuid.UUID,
        *,
        project_id: uuid.UUID | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[TakeoffDocument]:
        stmt = select(TakeoffDocument).where(TakeoffDocument.owner_id == owner_id)
        if project_id:
            stmt = stmt.where(TakeoffDocument.project_id == project_id)
        stmt = stmt.order_by(TakeoffDocument.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_source_document_id(
        self, source_document_id: str, *, project_id: uuid.UUID
    ) -> TakeoffDocument | None:
        """Return the takeoff document created from a Project-Files document.

        Idempotency lookup for ``POST /documents/from-source``: scoped to the
        project so the same source id in two projects never collides, and
        ordered oldest-first so the canonical row wins if a race ever created
        two.
        """
        stmt = (
            select(TakeoffDocument)
            .where(
                TakeoffDocument.source_document_id == source_document_id,
                TakeoffDocument.project_id == project_id,
            )
            .order_by(TakeoffDocument.created_at.asc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def create(self, doc: TakeoffDocument) -> TakeoffDocument:
        self.session.add(doc)
        await self.session.flush()
        return doc

    async def update_fields(self, doc_id: uuid.UUID, **fields: object) -> None:
        stmt = update(TakeoffDocument).where(TakeoffDocument.id == doc_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        # Expire cached ORM instances so the next get_by_id re-reads from DB
        instance = self.session.identity_map.get(identity_key(TakeoffDocument, doc_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, doc_id: uuid.UUID) -> None:
        doc = await self.get_by_id(doc_id)
        if doc is not None:
            await self.session.delete(doc)
            await self.session.flush()


class MeasurementRepository:
    """Data access for TakeoffMeasurement models."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, measurement_id: uuid.UUID) -> TakeoffMeasurement | None:
        """Get a measurement by ID."""
        return await self.session.get(TakeoffMeasurement, measurement_id)

    async def list_for_project(
        self,
        project_id: uuid.UUID,
        *,
        document_id: str | None = None,
        page: int | None = None,
        group_name: str | None = None,
        measurement_type: str | None = None,
        offset: int = 0,
        limit: int = 200,
    ) -> list[TakeoffMeasurement]:
        """List measurements for a project with optional filters."""
        stmt = select(TakeoffMeasurement).where(TakeoffMeasurement.project_id == project_id)
        if document_id is not None:
            stmt = stmt.where(TakeoffMeasurement.document_id == document_id)
        if page is not None:
            stmt = stmt.where(TakeoffMeasurement.page == page)
        if group_name is not None:
            stmt = stmt.where(TakeoffMeasurement.group_name == group_name)
        if measurement_type is not None:
            stmt = stmt.where(TakeoffMeasurement.type == measurement_type)

        stmt = stmt.order_by(TakeoffMeasurement.created_at.desc()).offset(offset).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_for_document(
        self,
        project_id: uuid.UUID,
        document_id: str,
    ) -> int:
        """Count every measurement one document holds inside one project.

        Used by the revision compare to report the true size of each side,
        so a capped compare can say how much it did not look at instead of
        presenting a partial diff as a complete one.

        Args:
            project_id: Owning project.
            document_id: The takeoff document to count.

        Returns:
            The number of measurement rows, 0 when the document has none.
        """
        stmt = select(func.count(TakeoffMeasurement.id)).where(
            TakeoffMeasurement.project_id == project_id,
            TakeoffMeasurement.document_id == document_id,
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one_or_none() or 0)

    async def list_all_for_document(
        self,
        project_id: uuid.UUID,
        document_id: str,
        *,
        max_rows: int,
        chunk_size: int = 1000,
    ) -> list[TakeoffMeasurement]:
        """Read up to ``max_rows`` measurements of one document, in chunks.

        The revision compare needs the WHOLE set of both documents, not an
        arbitrary window: a diff computed over two differently sliced
        windows invents added and removed rows. Rows are therefore paged
        out in ``chunk_size`` batches up to a caller-supplied safety cap
        that only exists to bound memory.

        Paging uses the totally ordered key ``(created_at DESC, id DESC)``.
        ``created_at`` alone is not unique, and ties reshuffle between
        OFFSET pages, which would drop and duplicate rows across chunks.

        Args:
            project_id: Owning project.
            document_id: The takeoff document to read.
            max_rows: Hard ceiling on the number of rows returned.
            chunk_size: Rows per round trip.

        Returns:
            The measurements in ``(created_at DESC, id DESC)`` order,
            truncated at ``max_rows``. Compare the length against
            :meth:`count_for_document` to detect that the cap was hit.
        """
        if max_rows <= 0:
            return []
        out: list[TakeoffMeasurement] = []
        offset = 0
        while len(out) < max_rows:
            batch_limit = min(chunk_size, max_rows - len(out))
            stmt = (
                select(TakeoffMeasurement)
                .where(
                    TakeoffMeasurement.project_id == project_id,
                    TakeoffMeasurement.document_id == document_id,
                )
                .order_by(TakeoffMeasurement.created_at.desc(), TakeoffMeasurement.id.desc())
                .offset(offset)
                .limit(batch_limit)
            )
            result = await self.session.execute(stmt)
            batch = list(result.scalars().all())
            out.extend(batch)
            if len(batch) < batch_limit:
                break
            offset += batch_limit
        return out

    async def create(self, measurement: TakeoffMeasurement) -> TakeoffMeasurement:
        """Insert a new measurement."""
        self.session.add(measurement)
        await self.session.flush()
        return measurement

    async def create_bulk(self, measurements: list[TakeoffMeasurement]) -> list[TakeoffMeasurement]:
        """Insert multiple measurements at once."""
        self.session.add_all(measurements)
        await self.session.flush()
        return measurements

    async def update_fields(self, measurement_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a measurement."""
        stmt = update(TakeoffMeasurement).where(TakeoffMeasurement.id == measurement_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(TakeoffMeasurement, measurement_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def delete(self, measurement_id: uuid.UUID) -> None:
        """Hard delete a measurement."""
        item = await self.get_by_id(measurement_id)
        if item is not None:
            await self.session.delete(item)
            await self.session.flush()

    async def all_for_project(self, project_id: uuid.UUID, *, confirmed_only: bool = True) -> list[TakeoffMeasurement]:
        """Return a project's measurements for summary and export.

        Defaults to confirmed rows only. A detector proposal is a suggestion
        awaiting a human, not a quantity: counting one into a total or writing
        it into an export hands somebody a number nobody agreed to. Rejected
        rows are kept as a record of the decision and must not come back either.

        The predicate is an allowlist rather than ``NOT IN ('proposed',
        'rejected')`` so a status added later is excluded until someone decides
        it belongs in a priced number. ``review_status`` defaults to
        ``'confirmed'`` in the column, so every hand-drawn and pre-existing row
        already satisfies it.

        Args:
            project_id: Owning project.
            confirmed_only: Keep only human-confirmed rows. Pass ``False`` only
                where the caller genuinely wants proposals too, such as a
                review queue or usage telemetry.

        Returns:
            The matching measurements.
        """
        stmt = select(TakeoffMeasurement).where(TakeoffMeasurement.project_id == project_id)
        if confirmed_only:
            stmt = stmt.where(TakeoffMeasurement.review_status == "confirmed")
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count_confirmed_for_project(self, project_id: uuid.UUID) -> int:
        """Count a project's human-confirmed measurements.

        The project dashboard reports work that has been agreed, so this is
        deliberately the same allowlist :meth:`all_for_project` uses rather
        than a second copy of the predicate spelled out at the call site: one
        definition of what counts as a quantity, so the tile and the totals
        cannot drift apart.

        Args:
            project_id: Owning project.

        Returns:
            The number of confirmed measurements, 0 when there are none.
        """
        stmt = select(func.count(TakeoffMeasurement.id)).where(
            TakeoffMeasurement.project_id == project_id,
            TakeoffMeasurement.review_status == "confirmed",
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one_or_none() or 0)

    async def count_unreviewed_for_project(self, project_id: uuid.UUID) -> int:
        """Count a project's detector proposals that nobody has decided on yet.

        The counterpart to :meth:`count_confirmed_for_project`. Confirmed rows
        are what a quantity, an export or a priced estimate is built from, so
        anything still ``proposed`` is work the drawing shows and the numbers do
        not. That gap is invisible unless somebody reports it, which is what
        this count exists for.

        Rejected rows are not counted: a decision was made about those.

        Args:
            project_id: Owning project.

        Returns:
            The number of measurements still awaiting review, 0 when there are
            none.
        """
        stmt = select(func.count(TakeoffMeasurement.id)).where(
            TakeoffMeasurement.project_id == project_id,
            TakeoffMeasurement.review_status == "proposed",
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one_or_none() or 0)

    async def list_proposals_for_run(self, run_id: uuid.UUID) -> list[TakeoffMeasurement]:
        """Return all proposal rows minted by one plan-read run.

        Proposals are ordinary :class:`TakeoffMeasurement` rows stamped with the
        run id in ``metadata_['ai_takeoff_run_id']`` and ``review_status`` of
        ``'proposed'``. Ordered newest-first so the review panel renders a
        stable list.
        """
        stmt = (
            select(TakeoffMeasurement)
            .where(TakeoffMeasurement.metadata_["ai_takeoff_run_id"].as_string() == str(run_id))
            .order_by(TakeoffMeasurement.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_proposals_for_document(
        self,
        document_id: str,
        *,
        page: int | None = None,
        review_status: str = "proposed",
    ) -> list[TakeoffMeasurement]:
        """Return proposal rows on one document, optionally scoped to a page.

        Covers every proposal path, not just the plan-read run: the offline
        vector recognizer and the seeded symbol search stamp the same
        ``review_status`` so one queue reviews them all. Ordered oldest-first
        so the reviewer walks the sheet in the order the detector produced,
        which keeps the canvas highlight moving predictably.
        """
        stmt = (
            select(TakeoffMeasurement)
            .where(TakeoffMeasurement.document_id == document_id)
            .where(TakeoffMeasurement.review_status == review_status)
        )
        if page is not None:
            stmt = stmt.where(TakeoffMeasurement.page == page)
        result = await self.session.execute(stmt.order_by(TakeoffMeasurement.created_at.asc()))
        return list(result.scalars().all())

    async def count_by_review_status(self, document_id: str) -> dict[str, int]:
        """Return ``{review_status: count}`` for one document.

        Drives the review panel's progress line without pulling every row over
        the wire, and is what the unreviewed-proposals validation rule reads.
        """
        stmt = (
            select(TakeoffMeasurement.review_status, func.count())
            .where(TakeoffMeasurement.document_id == document_id)
            .group_by(TakeoffMeasurement.review_status)
        )
        result = await self.session.execute(stmt)
        return {str(status): int(count) for status, count in result.all()}


class AiTakeoffRunRepository:
    """Data access for the vision-LLM plan-read run (issue #194)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, run_id: uuid.UUID) -> AiTakeoffRun | None:
        """Fetch a run by id (fresh SELECT, bypasses the identity map)."""
        stmt = select(AiTakeoffRun).where(AiTakeoffRun.id == run_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, run: AiTakeoffRun) -> AiTakeoffRun:
        """Insert a new plan-read run."""
        self.session.add(run)
        await self.session.flush()
        return run

    async def update_fields(self, run_id: uuid.UUID, **fields: object) -> None:
        """Update specific fields on a run and expire cached instances."""
        stmt = update(AiTakeoffRun).where(AiTakeoffRun.id == run_id).values(**fields)
        await self.session.execute(stmt)
        await self.session.flush()
        instance = self.session.identity_map.get(identity_key(AiTakeoffRun, run_id))
        if instance is None:
            return
        computed = [name for name, value in fields.items() if isinstance(value, ClauseElement)]
        for name, value in fields.items():
            if name not in computed:
                set_committed_value(instance, name, value)
        if computed:
            self.session.expire(instance, computed)

    async def rolling_spend_usd(self, user_id: uuid.UUID, *, window_hours: int = 24) -> float:
        """Sum a user's plan-read spend over a recent window.

        Used by the pre-flight cost gate so the cap is per-user and windowed,
        not a single global ceiling - one tenant cannot exhaust another's
        budget. ``window_hours <= 0`` sums all of the user's runs.
        """
        stmt = select(func.coalesce(func.sum(AiTakeoffRun.cost_usd_estimate), 0.0)).where(
            AiTakeoffRun.user_id == user_id
        )
        if window_hours > 0:
            cutoff = datetime.now(UTC) - timedelta(hours=window_hours)
            stmt = stmt.where(AiTakeoffRun.created_at >= cutoff)
        result = await self.session.execute(stmt)
        return float(result.scalar_one() or 0.0)
