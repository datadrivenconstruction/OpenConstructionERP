# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Resource-index method (Russia): reference data, BOQ mapping, VAT.

Orchestration only. The arithmetic lives in
:mod:`app.modules.price_index.resource_index_math`; this layer looks up the
indices for a region and quarter, the NR/SP norms per work type and the VAT
rate the platform's tax tables give for the date, maps a BOQ's positions onto
the computation's explicit input, and turns the result into the API shape.

Nothing here writes to a position. The only write outside the module's own
tables is the person's own choices (region, quarter, work types) kept under one
namespaced key of the BOQ's metadata.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import raiseload

from app.modules.boq.models import BOQ, Position
from app.modules.price_index import resource_index_math as rim
from app.modules.price_index.models import ResourceIndexValue, WorkTypeOverheadNorm
from app.modules.price_index.resource_index_schemas import (
    BOQResourceIndexComputeRequest,
    BOQResourceIndexSettings,
    ExcludedPositionOut,
    IndexUsedOut,
    LineOut,
    NormUsedOut,
    OverheadNormCreate,
    OverheadNormUpdate,
    PositionOut,
    ResourceIndexComputeRequest,
    ResourceIndexEstimateResponse,
    ResourceIndexValueCreate,
    ResourceIndexValueUpdate,
    TotalsOut,
    WorkTypeSummaryOut,
)
from app.modules.price_index.seed import SAMPLE_NORM_SOURCE_NOTE, SAMPLE_SOURCE_NOTE
from app.modules.projects.models import Project

#: Key under ``BOQ.metadata_`` that holds the person's choices for this method.
SETTINGS_KEY = "ru_resource_index"

#: Country whose tax tables price the VAT line.
VAT_COUNTRY = "RU"

#: How a BOQ resource ``type`` maps onto a resource kind of the method. A type
#: that is not here (electricity, subcontractor, other, blank) has no group in
#: the method, so its position is listed as excluded rather than guessed into
#: materials. Electricity in particular is booked differently by different
#: bases; the estimator reclassifies the line as machine or material.
_TYPE_TO_KIND: dict[str, str] = {
    "labor": rim.KIND_LABOR,
    "labour": rim.KIND_LABOR,
    "equipment": rim.KIND_MACHINE,
    "machine": rim.KIND_MACHINE,
    "operator": rim.KIND_OPERATOR,
    "material": rim.KIND_MATERIAL,
}


#: ``Position.price_basis`` values that say the line already stands on current
#: money: an invoice, a supplier quotation, a contract rate, the organisation's
#: own cost history. The method indexes base prices; indexing such a line would
#: bring 2026 roubles to 2026 roubles a second time, so the position is listed
#: as excluded whatever the person has confirmed for the bill.
_CURRENT_PRICE_BASES: frozenset[str] = frozenset({"invoice", "quotation", "contract_rate", "historic"})

#: The one ``price_basis`` that says the line stands on a published norm base,
#: and so is indexed without the bill-level confirmation. Every other value
#: (unset, ``price_list``, ``judgement``) says nothing about WHICH money the
#: price is in: the federal catalogue is a published list too, and so is a
#: supplier's current one. Those lines are indexed only when the person has
#: confirmed that the bill's resource prices are base prices.
_BASE_PRICE_BASES: frozenset[str] = frozenset({"norm"})

# ── Errors ───────────────────────────────────────────────────────────────────


class DuplicateEntryError(ValueError):
    """An index for the same region, quarter and group (or a norm for the same work type) exists."""


class VatUnresolvedError(ValueError):
    """The platform's tax tables give no VAT rate for the date."""

    def __init__(self, on_date: date, reason: str | None) -> None:
        self.on_date = on_date
        self.reason = reason or ""
        super().__init__(f"no VAT rate for {VAT_COUNTRY} on {on_date.isoformat()}: {self.reason}".rstrip(": "))


class SettingsIncompleteError(ValueError):
    """Region or quarter is missing, so there is nothing to look indices up by."""


class BOQNotFoundError(LookupError):
    """The BOQ does not exist."""


class BOQLockedError(PermissionError):
    """The BOQ is locked, so not even this method's own choices are written onto it."""


@dataclass(frozen=True)
class _MappedPosition:
    position: rim.PositionInput
    work_type_source: str


def _dec(value: Any) -> Decimal:
    """Parse a stored number (str / int / float) into a finite Decimal or raise ValueError."""
    if isinstance(value, bool) or value is None:
        raise ValueError("not a number")
    text = str(value).strip()
    if text == "":
        return Decimal("0")
    try:
        dec = Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"cannot read {value!r} as a number") from exc
    if not dec.is_finite():
        raise ValueError("not a finite number")
    return dec


def _norm_region(code: str) -> str:
    return (code or "").strip().upper()


class ResourceIndexService:
    """Reference data and computation for the resource-index method."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── Index values ─────────────────────────────────────────────────────

    async def list_indices(
        self,
        region_code: str | None = None,
        quarter: str | None = None,
        *,
        offset: int = 0,
        limit: int | None = None,
    ) -> tuple[list[ResourceIndexValue], int]:
        """One page of index values, newest quarter first within each region, and the total."""
        stmt = select(ResourceIndexValue)
        if region_code:
            stmt = stmt.where(ResourceIndexValue.region_code == _norm_region(region_code))
        if quarter:
            stmt = stmt.where(ResourceIndexValue.quarter == rim.normalise_quarter(quarter))
        total = int((await self.session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one())
        stmt = stmt.order_by(
            ResourceIndexValue.region_code,
            ResourceIndexValue.quarter.desc(),
            ResourceIndexValue.resource_group,
            ResourceIndexValue.id,
        ).offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def create_index(self, data: ResourceIndexValueCreate) -> ResourceIndexValue:
        region = _norm_region(data.region_code)
        existing = (
            await self.session.execute(
                select(ResourceIndexValue.id).where(
                    ResourceIndexValue.region_code == region,
                    ResourceIndexValue.quarter == data.quarter,
                    ResourceIndexValue.resource_group == data.resource_group,
                )
            )
        ).first()
        if existing is not None:
            raise DuplicateEntryError(
                f"an index for {data.resource_group} in {region}, {data.quarter} already exists; edit it instead"
            )
        row = ResourceIndexValue(
            region_code=region,
            quarter=data.quarter,
            resource_group=data.resource_group,
            index_value=data.index_value,
            source=data.source,
            is_sample=False,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def update_index(self, index_id: uuid.UUID, data: ResourceIndexValueUpdate) -> ResourceIndexValue | None:
        row = await self.session.get(ResourceIndexValue, index_id)
        if row is None:
            return None
        changed = False
        if data.index_value is not None and data.index_value != row.index_value:
            row.index_value = data.index_value
            changed = True
        if data.source is not None and data.source != row.source:
            row.source = data.source
            changed = True
        if changed:
            # A person has put their own value or reference on the row, so it
            # no longer is the platform's sample, and the sample's "not an
            # official value" note must not stay on it as its source.
            row.is_sample = False
            if data.source is None and row.source == SAMPLE_SOURCE_NOTE:
                row.source = ""
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def delete_index(self, index_id: uuid.UUID) -> bool:
        row = await self.session.get(ResourceIndexValue, index_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

    # ── Overhead and profit norms ────────────────────────────────────────

    async def list_norms(self, *, offset: int = 0, limit: int | None = None) -> tuple[list[WorkTypeOverheadNorm], int]:
        """One page of NR/SP norms by work type code, and the total."""
        total = int((await self.session.execute(select(func.count(WorkTypeOverheadNorm.id)))).scalar_one())
        stmt = select(WorkTypeOverheadNorm).order_by(WorkTypeOverheadNorm.work_type_code).offset(offset)
        if limit is not None:
            stmt = stmt.limit(limit)
        return list((await self.session.execute(stmt)).scalars().all()), total

    async def create_norm(self, data: OverheadNormCreate) -> WorkTypeOverheadNorm:
        existing = (
            await self.session.execute(
                select(WorkTypeOverheadNorm.id).where(WorkTypeOverheadNorm.work_type_code == data.work_type_code)
            )
        ).first()
        if existing is not None:
            raise DuplicateEntryError(f"a norm for work type {data.work_type_code!r} already exists; edit it instead")
        row = WorkTypeOverheadNorm(
            work_type_code=data.work_type_code,
            label=data.label,
            nr_pct=data.nr_pct,
            sp_pct=data.sp_pct,
            source=data.source,
            is_sample=False,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def update_norm(self, norm_id: uuid.UUID, data: OverheadNormUpdate) -> WorkTypeOverheadNorm | None:
        row = await self.session.get(WorkTypeOverheadNorm, norm_id)
        if row is None:
            return None
        changed = False
        for name in ("label", "nr_pct", "sp_pct", "source"):
            value = getattr(data, name)
            if value is not None and value != getattr(row, name):
                setattr(row, name, value)
                changed = True
        if changed:
            row.is_sample = False
            if data.source is None and row.source == SAMPLE_NORM_SOURCE_NOTE:
                row.source = ""
        await self.session.flush()
        await self.session.refresh(row)
        return row

    async def delete_norm(self, norm_id: uuid.UUID) -> bool:
        row = await self.session.get(WorkTypeOverheadNorm, norm_id)
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

    # ── Lookups ──────────────────────────────────────────────────────────

    async def _indices_for(self, region: str, quarter: str) -> dict[str, ResourceIndexValue]:
        rows, _total = await self.list_indices(region, quarter)
        return {row.resource_group: row for row in rows}

    async def _norms_by_code(self) -> dict[str, WorkTypeOverheadNorm]:
        rows, _total = await self.list_norms()
        return {row.work_type_code: row for row in rows}

    async def resolve_vat(self, on_date: date) -> tuple[Decimal, str]:
        """Return the VAT rate in percent and its name from the platform's tax tables.

        Raises:
            VatUnresolvedError: When the tables give no rate for the date. There
                is no fallback number: an estimate with a guessed VAT line is
                worse than one that says it has none.
        """
        from app.modules.i18n_foundation.service import I18nFoundationService

        resolution = await I18nFoundationService(self.session).resolve_tax_rate(VAT_COUNTRY, None, on_date.isoformat())
        if not resolution.resolved or resolution.combined_rate_pct is None:
            raise VatUnresolvedError(on_date, resolution.reason)
        name = resolution.components[0].tax_name if resolution.components else ""
        return Decimal(str(resolution.combined_rate_pct)), name

    # ── Compute ──────────────────────────────────────────────────────────

    async def _run(
        self,
        *,
        region: str,
        quarter: str,
        on_date: date | None,
        mapped: list[_MappedPosition],
    ) -> tuple[rim.EstimateResult, dict[str, ResourceIndexValue], dict[str, WorkTypeOverheadNorm], Decimal, str, date]:
        day = on_date or datetime.now(UTC).date()
        index_rows = await self._indices_for(region, quarter)
        norm_rows = await self._norms_by_code()
        vat_pct, vat_name = await self.resolve_vat(day)
        result = rim.compute_resource_index_estimate(
            rim.EstimateInput(
                region=region,
                quarter=quarter,
                indices={group: row.index_value for group, row in index_rows.items()},
                norms={
                    code: rim.OverheadProfitNorm(work_type=code, nr_pct=row.nr_pct, sp_pct=row.sp_pct)
                    for code, row in norm_rows.items()
                },
                positions=tuple(m.position for m in mapped),
                vat_rate_pct=vat_pct,
            )
        )
        return result, index_rows, norm_rows, vat_pct, vat_name, day

    async def compute(self, request: ResourceIndexComputeRequest) -> ResourceIndexEstimateResponse:
        """Price explicit positions with the stored indices, norms and VAT."""
        mapped = [
            _MappedPosition(
                position=rim.PositionInput(
                    ref=p.ref or str(i + 1),
                    ordinal=p.ordinal or str(i + 1),
                    description=p.description,
                    unit=p.unit,
                    quantity=p.quantity,
                    work_type=p.work_type,
                    resources=tuple(
                        rim.ResourceLineInput(
                            code=r.code,
                            name=r.name,
                            unit=r.unit,
                            kind=r.kind,
                            quantity=r.quantity,
                            base_unit_price=r.base_unit_price,
                        )
                        for r in p.resources
                    ),
                ),
                work_type_source="explicit",
            )
            for i, p in enumerate(request.positions)
        ]
        region = _norm_region(request.region_code)
        result, index_rows, norm_rows, vat_pct, vat_name, day = await self._run(
            region=region, quarter=request.quarter, on_date=request.on_date, mapped=mapped
        )
        return _to_response(
            result,
            index_rows=index_rows,
            norm_rows=norm_rows,
            sources={m.position.ref: m.work_type_source for m in mapped},
            vat_name=vat_name,
            on_date=day,
            currency="RUB",
            excluded=[],
        )

    # ── BOQ ──────────────────────────────────────────────────────────────

    async def get_boq(self, boq_id: uuid.UUID) -> BOQ:
        """Load the BOQ row alone.

        Both of its collections are ``selectin``, so a plain load reads every
        position and markup of the bill to reach one metadata key. They are
        set to raise instead: nothing here walks them (positions are read by
        their own query in :meth:`compute_boq`), and an empty collection left
        in the identity map would be a worse surprise than an error.
        """
        boq = await self.session.get(BOQ, boq_id, options=[raiseload(BOQ.positions), raiseload(BOQ.markups)])
        if boq is None:
            raise BOQNotFoundError(str(boq_id))
        return boq

    @staticmethod
    def read_settings(boq: BOQ) -> BOQResourceIndexSettings:
        """The stored choices, or empty ones. A malformed blob reads as empty."""
        meta = boq.metadata_ if isinstance(boq.metadata_, dict) else {}
        raw = meta.get(SETTINGS_KEY)
        if not isinstance(raw, dict):
            return BOQResourceIndexSettings()
        try:
            return BOQResourceIndexSettings.model_validate(
                {
                    k: raw.get(k)
                    for k in ("region_code", "quarter", "default_work_type", "work_types", "resources_at_base_prices")
                    if k in raw
                }
            )
        except ValueError:
            return BOQResourceIndexSettings()

    async def save_settings(
        self, boq: BOQ, settings: BOQResourceIndexSettings, user_id: str
    ) -> BOQResourceIndexSettings:
        """Store the choices under :data:`SETTINGS_KEY`, leaving every other key alone.

        Raises:
            BOQLockedError: The BOQ is locked. A locked bill refuses every
                writer, this one included, even though it touches no position.
        """
        if boq.is_locked:
            raise BOQLockedError(str(boq.id))
        meta = dict(boq.metadata_) if isinstance(boq.metadata_, dict) else {}
        meta[SETTINGS_KEY] = {
            "region_code": _norm_region(settings.region_code),
            "quarter": settings.quarter,
            "default_work_type": settings.default_work_type,
            "work_types": dict(settings.work_types),
            "resources_at_base_prices": bool(settings.resources_at_base_prices),
            "updated_by": str(user_id),
            "updated_at": datetime.now(UTC).isoformat(),
        }
        # A new dict, so the JSON column sees the change.
        boq.metadata_ = meta
        await self.session.flush()
        return self.read_settings(boq)

    async def compute_boq(self, boq: BOQ, request: BOQResourceIndexComputeRequest) -> ResourceIndexEstimateResponse:
        """Price a BOQ's positions; positions that cannot be priced are listed, not dropped silently."""
        region = _norm_region(request.region_code)
        if not region or not request.quarter:
            raise SettingsIncompleteError("choose the region and the quarter of the indices first")

        project = await self.session.get(Project, boq.project_id) if boq.project_id else None
        currency = (getattr(project, "currency", "") or "RUB").strip().upper() or "RUB"

        rows = (
            (
                await self.session.execute(
                    select(Position).where(Position.boq_id == boq.id).order_by(Position.sort_order, Position.ordinal)
                )
            )
            .scalars()
            .all()
        )
        mapped, excluded = map_boq_positions(
            list(rows),
            currency=currency,
            work_types=request.work_types,
            default_work_type=request.default_work_type,
            resources_at_base_prices=request.resources_at_base_prices,
        )
        result, index_rows, norm_rows, _vat_pct, vat_name, day = await self._run(
            region=region, quarter=request.quarter, on_date=request.on_date, mapped=mapped
        )
        response = _to_response(
            result,
            index_rows=index_rows,
            norm_rows=norm_rows,
            sources={m.position.ref: m.work_type_source for m in mapped},
            vat_name=vat_name,
            on_date=day,
            currency=currency,
            excluded=excluded,
        )
        response.boq_id = boq.id
        response.boq_name = boq.name
        response.project_id = boq.project_id
        return response


# ── BOQ mapping (pure, unit-tested) ──────────────────────────────────────────


def map_boq_positions(
    positions: list[Any],
    *,
    currency: str,
    work_types: dict[str, str],
    default_work_type: str,
    resources_at_base_prices: bool = False,
) -> tuple[list[_MappedPosition], list[ExcludedPositionOut]]:
    """Turn BOQ positions into the computation's input.

    A position's resources carry a per-unit ``quantity`` and a ``unit_rate``
    (the platform's own shape, where the position total is
    ``quantity x sum(resource quantity x unit_rate)``). Section headers and
    untouched placeholder rows are skipped; every other position is either
    mapped or listed in the second return value with the reason.

    Which ``unit_rate`` is a base price is never assumed. A position is
    indexed when its ``price_basis`` is ``norm``, or when it is unjudged and
    the person confirmed ``resources_at_base_prices`` for the bill. A current
    basis (:data:`_CURRENT_PRICE_BASES`) is excluded either way, and so is a
    resource split the platform generated (rows flagged ``estimated``): those
    are percentage shares of the position's own current rate, whatever the
    bill says. A position with machines and no operator line is excluded too,
    because its operators' wages would enter FOT as a silent zero.
    """
    from app.modules.boq.service import _is_section, is_empty_position

    base = (currency or "").strip().upper()
    default_wt = (default_work_type or "").strip()
    mapped: list[_MappedPosition] = []
    excluded: list[ExcludedPositionOut] = []

    for pos in positions:
        if _is_section(pos) or is_empty_position(pos):
            continue
        pid = str(pos.id)

        def skip(reason: str, detail: str = "", _pos: Any = pos, _pid: str = pid) -> None:
            excluded.append(
                ExcludedPositionOut(
                    position_id=_pid,
                    ordinal=_pos.ordinal or "",
                    description=(_pos.description or "")[:500],
                    reason=reason,  # type: ignore[arg-type]
                    detail=detail,
                )
            )

        basis = str(getattr(pos, "price_basis", None) or "").strip().lower()
        if basis in _CURRENT_PRICE_BASES:
            skip("not_base_prices", basis)
            continue

        meta = pos.metadata_ if isinstance(pos.metadata_, dict) else {}
        resources = [r for r in (meta.get("resources") or []) if isinstance(r, dict)]
        if not resources:
            skip("no_resources")
            continue

        if any(r.get("estimated") for r in resources):
            skip("estimated_resources")
            continue

        if basis not in _BASE_PRICE_BASES and not resources_at_base_prices:
            skip("base_prices_unconfirmed", basis)
            continue

        unmapped = sorted(
            {
                str(r.get("type") or "").strip().lower() or "(blank)"
                for r in resources
                if str(r.get("type") or "").strip().lower() not in _TYPE_TO_KIND
            }
        )
        if unmapped:
            skip("unmapped_resource_type", ", ".join(unmapped))
            continue

        foreign = sorted(
            {
                str(r.get("currency")).strip().upper()
                for r in resources
                if str(r.get("currency") or "").strip() and str(r.get("currency")).strip().upper() != base
            }
        )
        if foreign:
            skip("foreign_currency", ", ".join(foreign))
            continue

        if rim.lacks_operator_wages([_TYPE_TO_KIND[str(r.get("type") or "").strip().lower()] for r in resources]):
            skip("machine_without_operator_wages")
            continue

        chosen = (work_types.get(pid) or "").strip()
        if chosen:
            work_type, source = chosen, "chosen"
        elif default_wt:
            work_type, source = default_wt, "default"
        else:
            skip("no_work_type")
            continue

        try:
            qty = _dec(pos.quantity)
            lines = tuple(
                rim.ResourceLineInput(
                    code=str(r.get("code") or ""),
                    name=str(r.get("name") or ""),
                    unit=str(r.get("unit") or ""),
                    kind=_TYPE_TO_KIND[str(r.get("type") or "").strip().lower()],
                    quantity=_dec(r.get("quantity", 0)),
                    base_unit_price=_dec(r.get("unit_rate", 0)),
                )
                for r in resources
            )
        except ValueError as exc:
            skip("bad_number", str(exc))
            continue
        if qty < 0 or any(line.quantity < 0 or line.base_unit_price < 0 for line in lines):
            skip("bad_number", "negative quantity or price")
            continue

        mapped.append(
            _MappedPosition(
                position=rim.PositionInput(
                    ref=pid,
                    ordinal=pos.ordinal or "",
                    description=pos.description or "",
                    unit=pos.unit or "",
                    quantity=qty,
                    work_type=work_type,
                    resources=lines,
                ),
                work_type_source=source,
            )
        )
    return mapped, excluded


def _to_response(
    result: rim.EstimateResult,
    *,
    index_rows: dict[str, ResourceIndexValue],
    norm_rows: dict[str, WorkTypeOverheadNorm],
    sources: dict[str, str],
    vat_name: str,
    on_date: date,
    currency: str,
    excluded: list[ExcludedPositionOut],
) -> ResourceIndexEstimateResponse:
    indices_used = [
        IndexUsedOut(
            resource_group=group,
            index_value=value,
            source=index_rows[group].source,
            is_sample=bool(index_rows[group].is_sample),
        )
        for group, value in result.indices_used.items()
    ]
    norms_used = [
        NormUsedOut(
            work_type_code=code,
            label=norm_rows[code].label,
            nr_pct=norm.nr_pct,
            sp_pct=norm.sp_pct,
            source=norm_rows[code].source,
            is_sample=bool(norm_rows[code].is_sample),
        )
        for code, norm in result.norms_used.items()
    ]
    positions = [
        PositionOut(
            ref=p.ref,
            ordinal=p.ordinal,
            description=p.description,
            unit=p.unit,
            quantity=p.quantity,
            work_type=p.work_type,
            work_type_source=sources.get(p.ref, "explicit"),  # type: ignore[arg-type]
            lines=[LineOut(**line.__dict__) for line in p.lines],
            base_ot=p.base_ot,
            base_em=p.base_em,
            base_otm=p.base_otm,
            base_m=p.base_m,
            base_direct=p.base_direct,
            ot=p.ot,
            em=p.em,
            otm=p.otm,
            m=p.m,
            direct=p.direct,
            fot=p.fot,
            nr_pct=p.nr_pct,
            nr=p.nr,
            sp_pct=p.sp_pct,
            sp=p.sp,
            total=p.total,
        )
        for p in result.positions
    ]
    by_work_type = [
        WorkTypeSummaryOut(
            work_type=row.work_type,
            label=norm_rows[row.work_type].label if row.work_type in norm_rows else "",
            nr_pct=row.nr_pct,
            sp_pct=row.sp_pct,
            fot=row.fot,
            nr=row.nr,
            sp=row.sp,
        )
        for row in result.by_work_type
    ]
    t = result.totals
    return ResourceIndexEstimateResponse(
        region_code=result.region,
        quarter=result.quarter,
        on_date=on_date,
        currency=currency,
        vat_rate_pct=t.vat_rate_pct,
        vat_tax_name=vat_name,
        indices_used=indices_used,
        norms_used=norms_used,
        uses_sample_data=any(i.is_sample for i in indices_used) or any(n.is_sample for n in norms_used),
        positions=positions,
        by_work_type=by_work_type,
        totals=TotalsOut(**t.__dict__),
        excluded=excluded,
        priced_count=len(positions),
        excluded_count=len(excluded),
        is_complete=not excluded,
    )
