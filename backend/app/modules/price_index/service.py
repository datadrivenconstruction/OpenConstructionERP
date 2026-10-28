# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Price-index business logic.

Thin orchestration over the three tables plus the pure Decimal core in
:mod:`app.modules.price_index.index_math`. Data access is inlined on the
session (the module has no separate repository layer). All numeric work is
delegated to the pure functions so this layer stays free of rounding logic.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sql_json import json_path_text
from app.modules.boq.models import BOQ, Position
from app.modules.costs.models import CostItem
from app.modules.price_index import index_math
from app.modules.price_index.models import (
    CostIndexPoint,
    CostIndexSeries,
    LocationFactor,
)
from app.modules.price_index.schemas import (
    AdjustLine,
    AdjustLineResult,
    AdjustRequest,
    AdjustResponse,
    CostIndexPointCreate,
    CostIndexPointUpdate,
    CostIndexSeriesCreate,
    CostIndexSeriesUpdate,
    EscalatePreviewLine,
    EscalatePreviewRequest,
    EscalatePreviewResponse,
    LocationFactorCreate,
    LocationFactorUpdate,
)
from app.modules.projects.models import Project


class SeriesNotFoundError(LookupError):
    """Raised when a referenced cost-index series does not exist."""


class AmbiguousSeriesError(ValueError):
    """Raised when no series id is given but the store holds several to pick from."""


class ProjectNotFoundError(LookupError):
    """Raised when a project-scoped escalation names a project that does not exist."""


class PriceIndexService:
    """Orchestrates series/point/location-factor CRUD and batch adjustment."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Series ───────────────────────────────────────────────────────────

    async def list_series(self) -> list[tuple[CostIndexSeries, int]]:
        """Return every series paired with its point count, ordered by name."""
        count_col = func.count(CostIndexPoint.id)
        stmt = (
            select(CostIndexSeries, count_col)
            .outerjoin(CostIndexPoint, CostIndexPoint.series_id == CostIndexSeries.id)
            .group_by(CostIndexSeries.id)
            .order_by(CostIndexSeries.name)
        )
        rows = await self.session.execute(stmt)
        return [(series, int(count or 0)) for series, count in rows.all()]

    async def get_series(self, series_id: uuid.UUID) -> CostIndexSeries | None:
        return await self.session.get(CostIndexSeries, series_id)

    async def create_series(self, data: CostIndexSeriesCreate) -> CostIndexSeries:
        obj = CostIndexSeries(name=data.name, description=data.description)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def update_series(
        self,
        series_id: uuid.UUID,
        data: CostIndexSeriesUpdate,
    ) -> CostIndexSeries | None:
        obj = await self.get_series(series_id)
        if obj is None:
            return None
        for key, value in data.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(obj, key, value)
        await self.session.flush()
        return obj

    async def delete_series(self, series_id: uuid.UUID) -> bool:
        obj = await self.get_series(series_id)
        if obj is None:
            return False
        await self.session.delete(obj)
        await self.session.flush()
        return True

    async def point_count(self, series_id: uuid.UUID) -> int:
        stmt = select(func.count(CostIndexPoint.id)).where(CostIndexPoint.series_id == series_id)
        return int((await self.session.execute(stmt)).scalar_one())

    # ── Points ───────────────────────────────────────────────────────────

    async def add_point(
        self,
        series_id: uuid.UUID,
        data: CostIndexPointCreate,
    ) -> CostIndexPoint:
        obj = CostIndexPoint(series_id=series_id, period=data.period, factor=data.factor)
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def get_point(self, point_id: uuid.UUID) -> CostIndexPoint | None:
        return await self.session.get(CostIndexPoint, point_id)

    async def update_point(
        self,
        point_id: uuid.UUID,
        data: CostIndexPointUpdate,
    ) -> CostIndexPoint | None:
        obj = await self.get_point(point_id)
        if obj is None:
            return None
        for key, value in data.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(obj, key, value)
        await self.session.flush()
        return obj

    async def delete_point(self, point_id: uuid.UUID) -> bool:
        obj = await self.get_point(point_id)
        if obj is None:
            return False
        await self.session.delete(obj)
        await self.session.flush()
        return True

    # ── Location factors ─────────────────────────────────────────────────

    async def list_location_factors(self) -> list[LocationFactor]:
        stmt = select(LocationFactor).order_by(LocationFactor.region_code)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_location_factor(self, factor_id: uuid.UUID) -> LocationFactor | None:
        return await self.session.get(LocationFactor, factor_id)

    async def create_location_factor(self, data: LocationFactorCreate) -> LocationFactor:
        obj = LocationFactor(
            region_code=data.region_code,
            label=data.label,
            factor=data.factor,
        )
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def update_location_factor(
        self,
        factor_id: uuid.UUID,
        data: LocationFactorUpdate,
    ) -> LocationFactor | None:
        obj = await self.get_location_factor(factor_id)
        if obj is None:
            return None
        for key, value in data.model_dump(exclude_unset=True).items():
            if value is not None:
                setattr(obj, key, value)
        await self.session.flush()
        return obj

    async def delete_location_factor(self, factor_id: uuid.UUID) -> bool:
        obj = await self.get_location_factor(factor_id)
        if obj is None:
            return False
        await self.session.delete(obj)
        await self.session.flush()
        return True

    # ── Adjustment ───────────────────────────────────────────────────────

    async def adjust(self, request: AdjustRequest) -> AdjustResponse:
        """Bring a batch of amounts to the target period and region.

        The chosen series' points and every stored regional factor are loaded
        once, then each line is resolved with the pure Decimal core. A line
        whose period is absent from the series is reported with an ``error``
        and null figures rather than failing the whole batch.

        Args:
            request: The series to escalate against and the lines to adjust.

        Returns:
            The per-line results paired with the series name.

        Raises:
            SeriesNotFoundError: If ``request.series_id`` does not exist.
        """
        series = await self.get_series(request.series_id)
        if series is None:
            raise SeriesNotFoundError(str(request.series_id))

        points = {p.period: p.factor for p in series.points}
        regions: dict[str, Decimal] = {lf.region_code: lf.factor for lf in await self.list_location_factors()}

        results = [self._adjust_line(line, points, regions) for line in request.lines]
        return AdjustResponse(series_id=series.id, series_name=series.name, results=results)

    @staticmethod
    def _adjust_line(
        line: AdjustLine,
        points: dict[str, Decimal],
        regions: dict[str, Decimal],
    ) -> AdjustLineResult:
        """Resolve one line's factors and adjusted amount (pure, no I/O)."""
        base = AdjustLineResult(
            amount=line.amount,
            base_period=line.base_period,
            target_period=line.target_period,
            base_region=line.base_region,
            target_region=line.target_region,
        )
        try:
            temporal = index_math.resolve_factor(points, line.base_period, line.target_period)
        except index_math.PeriodNotFoundError as exc:
            base.error = str(exc)
            return base

        location = index_math.location_multiplier(regions, line.base_region, line.target_region)
        applied = index_math.combined_factor(temporal, location)
        adjusted = index_math.adjust(line.amount, temporal, location)

        base.temporal_factor = temporal
        base.location_factor = location
        base.applied_factor = applied
        base.adjusted_amount = adjusted
        base.note = _region_note(line, regions)
        return base

    # ── Escalate stored rates (preview) ──────────────────────────────────

    async def escalate_stored_rates(
        self,
        request: EscalatePreviewRequest,
    ) -> EscalatePreviewResponse:
        """Preview the estimate's own stored rates escalated to a target date.

        For each selected :class:`~app.modules.costs.models.CostItem` the stored
        rate is brought from the period of its ``price_as_of`` capture date to
        the period of ``request.target_date`` using the chosen series, reusing
        the pure Decimal core for both the index ratio and the rounding. Nothing
        is written back: this is a read-only preview, the safe compute path that
        precedes any later write-back into the BOQ.

        The selection has two scopes. Without ``project_id`` it is
        *catalogue-scoped*: the cost-database rows matched by the explicit ids
        and / or the region / category filter. With ``project_id`` it is
        *project-scoped*: exactly the cost items the project's BOQ references
        (see :meth:`_select_project_cost_items`), so the estimate itself is
        escalated rather than the catalogue at large.

        An item whose ``price_as_of`` is null, whose stored rate is not a number,
        or whose base / target period is absent from the series is returned
        flagged (``escalatable = False`` with a ``note``) rather than guessed, so
        one unusable item never voids the batch.

        Args:
            request: The target date, the series to escalate against and the
                item selectors (a ``project_id``, explicit ids and / or a
                region / category filter).

        Returns:
            The per-item preview paired with the resolved series, the target
            period and, in project scope, the project context.

        Raises:
            SeriesNotFoundError: If ``request.series_id`` does not exist, or it
                is omitted and no series exists at all.
            AmbiguousSeriesError: If ``request.series_id`` is omitted while more
                than one series exists.
            ProjectNotFoundError: If ``request.project_id`` is given but no such
                project exists.
        """
        series = await self._resolve_series(request.series_id)
        points = await self._load_series_points(series.id)
        target_period = index_math.period_for_date(request.target_date)

        scope = "catalogue"
        project_name: str | None = None
        project_fallback = False
        if request.project_id is not None:
            scope = "project"
            project_name, project_region = await self._require_project(request.project_id)
            items, project_fallback = await self._select_project_cost_items(request.project_id, request, project_region)
        else:
            items = await self._select_cost_items(request)

        results = [self._preview_line(item, points, target_period) for item in items]
        escalatable = sum(1 for line in results if line.escalatable)
        return EscalatePreviewResponse(
            series_id=series.id,
            series_name=series.name,
            target_date=request.target_date,
            target_period=target_period,
            item_count=len(results),
            escalatable_count=escalatable,
            scope=scope,
            project_id=request.project_id,
            project_name=project_name,
            project_fallback=project_fallback,
            results=results,
        )

    async def _resolve_series(self, series_id: uuid.UUID | None) -> CostIndexSeries:
        """Resolve the series to escalate against, defaulting to the sole one.

        When ``series_id`` is given it must exist. When it is omitted the store
        must hold exactly one series (the common single-series install); zero
        series is a :class:`SeriesNotFoundError` and several is an
        :class:`AmbiguousSeriesError`.
        """
        if series_id is not None:
            series = await self.get_series(series_id)
            if series is None:
                raise SeriesNotFoundError(str(series_id))
            return series
        rows = await self.list_series()
        if not rows:
            raise SeriesNotFoundError("no cost-index series exists")
        if len(rows) > 1:
            raise AmbiguousSeriesError("several cost-index series exist; specify series_id to choose one")
        return rows[0][0]

    async def series_points(self, series_id: uuid.UUID) -> dict[str, Decimal]:
        """Return a series' ``{period: index value}`` map.

        The public way for another module to read an index series. The BOQ
        module's escalation markup needs the points to resolve a factor, and
        going through this method rather than querying ``oe_price_index_point``
        directly keeps the table an implementation detail of the module that
        owns it.

        Args:
            series_id: The cost-index series to read.

        Returns:
            Every stored period of that series mapped to its index value.
            Empty when the series has no points or does not exist.
        """
        return await self._load_series_points(series_id)

    async def _load_series_points(self, series_id: uuid.UUID) -> dict[str, Decimal]:
        """Load a series' ``{period: factor}`` map with one direct query.

        Reads the points explicitly rather than through the ORM relationship so
        the result never depends on whether the series was already loaded into
        the session, avoiding a lazy load in an async context.
        """
        stmt = select(CostIndexPoint.period, CostIndexPoint.factor).where(CostIndexPoint.series_id == series_id)
        return dict((await self.session.execute(stmt)).all())

    async def _select_cost_items(self, request: EscalatePreviewRequest) -> list[CostItem]:
        """Select the cost items named or matched by the request filters.

        Explicit ``cost_item_ids`` are honoured as-is (even inactive rows, so a
        named item always resolves); a region / category filter restricts to
        active rows so soft-deleted items are never dredged up. All supplied
        constraints are applied together.
        """
        stmt = select(CostItem)
        if request.cost_item_ids:
            stmt = stmt.where(CostItem.id.in_(request.cost_item_ids))
        else:
            stmt = stmt.where(CostItem.is_active.is_(True))
        if request.region:
            stmt = stmt.where(CostItem.region == request.region)
        if request.category:
            stmt = stmt.where(_collection_expr(request.category))
        stmt = stmt.order_by(CostItem.code, CostItem.id)
        return list((await self.session.execute(stmt)).scalars().all())

    # ── Project-scoped selection ─────────────────────────────────────────

    async def _require_project(self, project_id: uuid.UUID) -> tuple[str, str]:
        """Return a project's ``(name, region)``, or raise if it does not exist.

        Guards the project scope so a bogus ``project_id`` surfaces as a clean
        not-found error instead of silently falling through to the region
        fallback (which, for a non-existent project, would have no region to
        bound it).
        """
        row = (await self.session.execute(select(Project.name, Project.region).where(Project.id == project_id))).first()
        if row is None:
            raise ProjectNotFoundError(str(project_id))
        name, region = row
        return name, (region or "").strip()

    async def _project_cost_item_ids(self, project_id: uuid.UUID) -> list[uuid.UUID]:
        """Collect the DISTINCT cost items a project's BOQ positions reference.

        The reliable typed link is ``Position.metadata_['cost_item_id']`` (a
        string UUID stamped both when a user applies a catalogue item to a
        position and when the match-elements pipeline commits a matched line).
        It is read directly with a dialect-aware JSON extract across every
        position of every BOQ the project owns, de-duplicated in stable order
        and coerced to UUIDs (an unparseable value is skipped, never guessed).

        Args:
            project_id: The project whose BOQ positions are inspected.

        Returns:
            The DISTINCT, parseable cost-item UUIDs the project's positions link
            to, in first-seen order (empty when no position carries a link).
        """
        id_text = json_path_text(Position.metadata_, "$.cost_item_id")
        stmt = (
            select(id_text)
            .select_from(Position)
            .join(BOQ, Position.boq_id == BOQ.id)
            .where(BOQ.project_id == project_id, id_text.is_not(None))
            .distinct()
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        unique: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()
        for value in rows:
            parsed = _coerce_uuid(value)
            if parsed is not None and parsed not in seen:
                seen.add(parsed)
                unique.append(parsed)
        return unique

    async def _select_project_cost_items(
        self,
        project_id: uuid.UUID,
        request: EscalatePreviewRequest,
        project_region: str,
    ) -> tuple[list[CostItem], bool]:
        """Select the cost items a project's BOQ uses; flag when the fallback ran.

        Primary path: the DISTINCT cost items the project's positions link to
        via ``metadata.cost_item_id`` (see :meth:`_project_cost_item_ids`),
        escalated exactly. A supplied ``region`` / ``category`` narrows that set
        further (AND). Explicit ids from the request are ignored here - the
        project's own links define the set.

        Fallback (documented): when NO position carries a typed link, positions
        hold no ``(region, category)`` tuple of their own to group by, so the
        project's own ``region`` is used as the best available regional proxy
        and its active cost items are escalated. To honour "never escalate the
        whole catalogue by accident", with neither a region (the project's or an
        explicit one) nor a category to bound it the selection is empty.

        Args:
            project_id: The project whose used cost items are resolved.
            request: The originating request (its region / category narrow the
                selection in both paths).
            project_region: The project's own region, the fallback proxy.

        Returns:
            The selected cost items paired with a flag that is ``True`` when the
            region fallback ran (no typed links were found).
        """
        ids = await self._project_cost_item_ids(project_id)
        if ids:
            stmt = select(CostItem).where(CostItem.id.in_(ids))
            if request.region:
                stmt = stmt.where(CostItem.region == request.region)
            if request.category:
                stmt = stmt.where(_collection_expr(request.category))
            stmt = stmt.order_by(CostItem.code, CostItem.id)
            return list((await self.session.execute(stmt)).scalars().all()), False

        region = (request.region or "").strip() or project_region
        category = (request.category or "").strip()
        if not region and not category:
            return [], True
        stmt = select(CostItem).where(CostItem.is_active.is_(True))
        if region:
            stmt = stmt.where(CostItem.region == region)
        if category:
            stmt = stmt.where(_collection_expr(category))
        stmt = stmt.order_by(CostItem.code, CostItem.id)
        return list((await self.session.execute(stmt)).scalars().all()), True

    @staticmethod
    def _preview_line(
        item: CostItem,
        points: dict[str, Decimal],
        target_period: str,
    ) -> EscalatePreviewLine:
        """Resolve one item's base rate, factor and escalated rate (pure, no I/O)."""
        line = EscalatePreviewLine(
            cost_item_id=item.id,
            code=item.code,
            unit=item.unit,
            region=item.region,
            currency=item.currency,
        )
        try:
            base_rate = index_math.to_decimal(item.rate)
        except ValueError:
            line.note = "stored rate is not a number; cannot escalate"
            return line
        line.base_rate = base_rate

        if item.price_as_of is None:
            line.note = "no price date on record (price_as_of is null); cannot escalate"
            return line
        line.base_date = item.price_as_of
        base_period = index_math.period_for_date(item.price_as_of)
        line.base_period = base_period

        try:
            factor = index_math.resolve_factor(points, base_period, target_period)
        except (index_math.PeriodNotFoundError, ValueError) as exc:
            line.note = f"{exc}; cannot escalate"
            return line

        # Reuse the pure money adjustment with a neutral location factor of 1:
        # the escalated rate is base_rate * factor rounded to two decimals.
        line.factor = factor
        line.escalated_rate = index_math.adjust(base_rate, factor, Decimal("1"))
        line.escalatable = True
        return line


def _coerce_uuid(value: str | None) -> uuid.UUID | None:
    """Parse a stored ``cost_item_id`` string into a UUID, or ``None`` if unusable.

    Position links are text, so a legacy or hand-edited value may not be a valid
    UUID; such a value is skipped rather than allowed to error the whole preview.
    """
    if not value:
        return None
    try:
        return uuid.UUID(str(value).strip())
    except (ValueError, AttributeError, TypeError):
        return None


def _collection_expr(category: str) -> Any:
    """Return a dialect-aware equality on the item's top classification level.

    The "category" of a cost item is the ``collection`` key of its
    classification JSON. Mirrors the cost-repository ``category`` filter so the
    same data matches identically across dev (SQLite ``json_extract``) and prod
    (PostgreSQL ``->>``).
    """
    from app.database import engine as _engine

    if "sqlite" in str(_engine.url):
        return json_path_text(CostItem.classification, "$.collection") == category
    return CostItem.classification["collection"].as_string() == category


def _region_note(line: AdjustLine, regions: dict[str, Decimal]) -> str | None:
    """Flag any named region that has no stored factor (treated as 1)."""
    missing = [
        region
        for region in (line.base_region, line.target_region)
        if region and region.strip() and region.strip() not in regions
    ]
    if not missing:
        return None
    joined = ", ".join(sorted(set(missing)))
    return f"no stored factor for region(s) {joined}; assumed 1"
