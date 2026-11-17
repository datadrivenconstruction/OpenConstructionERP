# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Business logic of the plant rate catalogue: versions, rates, import, rental defaults."""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from decimal import Decimal
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.active_markets import pack_active
from app.modules.equipment.models import Equipment
from app.modules.equipment.rate_import import (
    ALL_FIELDS,
    REQUIRED_NUMBER_FIELDS,
    TEXT_FIELDS,
    ColumnProfile,
    ImportResult,
    parse_table,
    read_table,
    suggest_mapping,
)
from app.modules.equipment.rate_math import (
    AVERAGE_VALUE,
    RateInputError,
    RateInputs,
    compute_rate,
    money,
    monthly_charge,
    to_decimal,
)
from app.modules.equipment.rate_models import EquipmentRateCatalogue, EquipmentRateItem, EquipmentRateProfile
from app.modules.equipment.rate_repository import RateRepository
from app.modules.equipment.rate_schemas import (
    CatalogueCreate,
    CatalogueResponse,
    CatalogueUpdate,
    ChargePreviewRequest,
    ChargePreviewResponse,
    ImportPreviewResponse,
    IssueOut,
    ItemCreate,
    ItemResponse,
    ItemUpdate,
    LayoutOut,
    PreviewRequest,
    PreviewResponse,
    ProfileCreate,
    RateBreakdown,
    RentalDefaults,
)
from app.modules.equipment.rate_validators import run_rate_rules

logger = logging.getLogger(__name__)

_ITEM_FIELDS = (
    "value",
    "residual",
    "life_years",
    "months_per_year",
    "interest",
    "repair",
    "hours_per_month",
)


def _item_payload(item: Any) -> dict[str, Any]:
    """The rule payload row of an item-like object (ORM row or dict)."""
    get = item.get if isinstance(item, dict) else lambda k: getattr(item, k, None)
    return {
        "id": str(get("id") or ""),
        "code": get("code") or "",
        **{k: get(k) for k in _ITEM_FIELDS},
    }


def breakdown_for(item: Any, convention: str = AVERAGE_VALUE, working_days: Decimal | None = None) -> RateBreakdown:
    """Month, hour and day rate of one machine; empty when the inputs cannot be used.

    A manual monthly rate overrides the formula; hourly and daily then derive from it.
    """
    get = item.get if isinstance(item, dict) else lambda k: getattr(item, k, None)
    override = to_decimal(get("override_monthly_rate"))
    hours = to_decimal(get("hours_per_month"))
    if override is not None:
        return RateBreakdown(
            monthly=money(override),
            hourly=money(override / hours) if hours and hours > 0 else None,
            daily=money(override / working_days) if working_days and working_days > 0 else None,
            manual=True,
        )
    values = {k: to_decimal(get(k)) for k in _ITEM_FIELDS if k != "hours_per_month"}
    if any(v is None for v in values.values()):
        return RateBreakdown()
    inputs = RateInputs(hours_per_month=hours, **values)  # type: ignore[arg-type]
    try:
        result = compute_rate(inputs, convention=convention, working_days_per_month=working_days)
    except RateInputError:
        return RateBreakdown()
    return RateBreakdown(
        depreciation=result.depreciation,
        interest=result.interest,
        repair=result.repair,
        monthly=result.monthly,
        hourly=result.hourly,
        daily=result.daily,
    )


def _issues(results: list[dict[str, Any]]) -> list[IssueOut]:
    return [
        IssueOut(
            rule_id=r["rule_id"],
            severity=r["severity"],
            message=r["message"],
            details=r.get("details") or {},
        )
        for r in results
        if not r["passed"]
    ]


class RateService:
    """Rate catalogue use cases."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = RateRepository(session)

    # ── catalogues ────────────────────────────────────────────────────────

    async def list_catalogues(self) -> list[CatalogueResponse]:
        rows = await self.repo.list_catalogues()
        counts = await self.repo.counts_by_catalogue()
        by_family: dict[uuid.UUID, list[EquipmentRateCatalogue]] = defaultdict(list)
        for row in rows:
            by_family[row.family_id].append(row)
        out: list[CatalogueResponse] = []
        for row in rows:
            newer = sorted(
                (c.valid_from for c in by_family[row.family_id] if c.valid_from > row.valid_from),
            )
            machines, assets = counts.get(row.id, (0, 0))
            resp = CatalogueResponse.model_validate(row)
            resp.superseded = bool(newer)
            resp.superseded_on = newer[0] if newer else None
            resp.machines, resp.used_by_assets = machines, assets
            out.append(resp)
        return out

    async def get_catalogue(self, catalogue_id: uuid.UUID) -> EquipmentRateCatalogue:
        row = await self.repo.get_catalogue(catalogue_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Rate catalogue not found")
        return row

    async def catalogue_response(self, catalogue_id: uuid.UUID) -> CatalogueResponse:
        for resp in await self.list_catalogues():
            if resp.id == catalogue_id:
                return resp
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rate catalogue not found")

    async def _require_editable(self, catalogue: EquipmentRateCatalogue) -> None:
        resp = await self.catalogue_response(catalogue.id)
        if resp.superseded:
            raise HTTPException(status.HTTP_409_CONFLICT, "A superseded catalogue version is read-only")

    async def create_catalogue(
        self, data: CatalogueCreate, family_id: uuid.UUID | None = None
    ) -> EquipmentRateCatalogue:
        row = EquipmentRateCatalogue(**data.model_dump(), family_id=family_id or uuid.uuid4())
        return await self.repo.add_catalogue(row)

    async def update_catalogue(self, catalogue_id: uuid.UUID, data: CatalogueUpdate) -> EquipmentRateCatalogue:
        row = await self.get_catalogue(catalogue_id)
        await self._require_editable(row)
        await self.repo.update_catalogue(row, data.model_dump(exclude_unset=True))
        return row

    async def delete_catalogue(self, catalogue_id: uuid.UUID) -> None:
        row = await self.get_catalogue(catalogue_id)
        counts = await self.repo.counts_by_catalogue()
        if counts.get(row.id, (0, 0))[1]:
            raise HTTPException(status.HTTP_409_CONFLICT, "Assets still use machines of this catalogue")
        await self.repo.delete_catalogue(row)

    # ── items ─────────────────────────────────────────────────────────────

    async def items(self, catalogue_id: uuid.UUID) -> list[ItemResponse]:
        catalogue = await self.get_catalogue(catalogue_id)
        assets = await self.repo.assets_by_item(catalogue_id)
        out: list[ItemResponse] = []
        for item in await self.repo.list_items(catalogue_id):
            resp = ItemResponse.model_validate(item)
            resp.rates = breakdown_for(item, catalogue.interest_convention, catalogue.working_days_per_month)
            resp.is_synthetic = catalogue.is_synthetic
            resp.assets = assets.get(item.id, 0)
            out.append(resp)
        return out

    async def _check_item(self, values: dict[str, Any]) -> list[IssueOut]:
        issues = _issues(await _run({"items": [_item_payload(values)]}))
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"message": "Rate inputs failed validation", "issues": [i.model_dump() for i in errors]},
            )
        return issues

    async def create_item(self, catalogue_id: uuid.UUID, data: ItemCreate) -> ItemResponse:
        catalogue = await self.get_catalogue(catalogue_id)
        await self._require_editable(catalogue)
        if await self.repo.get_item_by_code(catalogue_id, data.code) is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, f"Machine code '{data.code}' already exists")
        await self._check_item(data.model_dump())
        row = await self.repo.add_item(EquipmentRateItem(catalogue_id=catalogue_id, **data.model_dump()))
        resp = ItemResponse.model_validate(row)
        resp.rates = breakdown_for(row, catalogue.interest_convention, catalogue.working_days_per_month)
        resp.is_synthetic = catalogue.is_synthetic
        return resp

    async def update_item(self, item_id: uuid.UUID, data: ItemUpdate) -> ItemResponse:
        item = await self.repo.get_item(item_id)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Machine not found")
        catalogue = await self.get_catalogue(item.catalogue_id)
        await self._require_editable(catalogue)
        fields = data.model_dump(exclude_unset=True)
        merged = {**{k: getattr(item, k) for k in (*_ITEM_FIELDS, "code")}, **fields}
        await self._check_item(merged)
        await self.repo.update_item(item, fields)
        resp = ItemResponse.model_validate(item)
        resp.rates = breakdown_for(item, catalogue.interest_convention, catalogue.working_days_per_month)
        resp.is_synthetic = catalogue.is_synthetic
        return resp

    async def delete_item(self, item_id: uuid.UUID) -> None:
        item = await self.repo.get_item(item_id)
        if item is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Machine not found")
        await self._require_editable(await self.get_catalogue(item.catalogue_id))
        await self.repo.delete_item(item)

    async def preview(self, data: PreviewRequest) -> PreviewResponse:
        """Live result of the formula for the drawer; ``-`` (empty rates) while an input is invalid."""
        row = data.model_dump()
        issues = _issues(await _run({"items": [_item_payload(row)]}))
        has_error = any(i.severity == "error" for i in issues)
        rates = (
            RateBreakdown() if has_error else breakdown_for(row, data.interest_convention, data.working_days_per_month)
        )
        return PreviewResponse(valid=not has_error and rates.monthly is not None, rates=rates, issues=issues)

    async def validate_catalogue(self, catalogue_id: uuid.UUID) -> list[IssueOut]:
        await self.get_catalogue(catalogue_id)
        rows = [_item_payload(i) for i in await self.repo.list_items(catalogue_id)]
        return _issues(await _run({"items": rows}))

    # ── import ────────────────────────────────────────────────────────────

    def layouts(self, markets: list[str]) -> list[LayoutOut]:
        """The own layout plus the layouts of the packs that are active for ``markets``."""
        from app.core.regional_packs import pack_configs

        out = [
            LayoutOut(
                key="own",
                label_key="equipment.rates.layout_own",
                mapping={},
                decimal_comma=False,
                interest_convention=AVERAGE_VALUE,
            )
        ]
        for config in pack_configs():
            layout = config.get("equipment_rate_layout")
            if isinstance(layout, dict) and pack_active(markets, config.get("countries") or ()):
                out.append(
                    LayoutOut(
                        key=str(config.get("region_code", "pack")).lower(),
                        label_key=str(layout["label_key"]),
                        mapping=dict(layout.get("mapping") or {}),
                        decimal_comma=bool(layout.get("decimal_comma")),
                        interest_convention=str(layout.get("interest_convention") or AVERAGE_VALUE),
                    )
                )
        return out

    def import_preview(self, filename: str, data: bytes, markets: list[str]) -> ImportPreviewResponse:
        rows = read_table(filename, data)
        if not rows:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The table is empty")
        headers = rows[0]
        layouts = self.layouts(markets)
        suggested = suggest_mapping(headers)
        for layout in layouts[1:]:
            matched = {f: c for f, c in layout.mapping.items() if c in headers}
            if len(matched) > len(suggested):
                suggested = matched
        return ImportPreviewResponse(
            headers=headers,
            sample=rows[1:6],
            total_rows=len(rows) - 1,
            suggested_mapping=suggested,
            layouts=layouts,
            fields=list(ALL_FIELDS),
            required_fields=[*("code", "name"), *REQUIRED_NUMBER_FIELDS],
        )

    def dry_run(self, filename: str, data: bytes, profile: ColumnProfile) -> ImportResult:
        return parse_table(read_table(filename, data), profile)

    async def commit_import(
        self,
        result: ImportResult,
        catalogue: CatalogueCreate,
        family_id: uuid.UUID | None,
    ) -> EquipmentRateCatalogue:
        """New catalogue version from a clean dry run; rows with errors are never imported."""
        if result.error_rows:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={"message": "Fix the rows with errors first", "issues": result.issues[:50]},
            )
        if not result.items:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "No machines to import")
        if family_id is not None:
            existing = [c for c in await self.repo.list_catalogues() if c.family_id == family_id]
            if not existing:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Catalogue family not found")
            if any(c.valid_from >= catalogue.valid_from for c in existing):
                raise HTTPException(
                    status.HTTP_409_CONFLICT, "The new version must be valid from a later date than the current one"
                )
        row = await self.create_catalogue(catalogue, family_id)
        seen: set[str] = set()
        for item in result.items:
            if item["code"] in seen:
                continue
            seen.add(item["code"])
            await self.repo.add_item(
                EquipmentRateItem(catalogue_id=row.id, **{k: v for k, v in item.items() if k in ALL_FIELDS})
            )
        return row

    async def list_profiles(self) -> list[EquipmentRateProfile]:
        return await self.repo.list_profiles()

    async def save_profile(self, data: ProfileCreate) -> EquipmentRateProfile:
        existing = await self.repo.get_profile_by_name(data.name)
        if existing is not None:
            existing.layout_key = data.layout_key
            existing.mapping = dict(data.mapping)
            existing.decimal_comma = data.decimal_comma
            existing.percent_fields = list(data.percent_fields)
            await self.session.flush()
            return existing
        return await self.repo.add_profile(EquipmentRateProfile(**data.model_dump()))

    async def delete_profile(self, name: str) -> None:
        row = await self.repo.get_profile_by_name(name)
        if row is not None:
            await self.repo.delete_profile(row)

    # ── rentals and charges ───────────────────────────────────────────────

    async def rental_defaults(self, equipment_id: uuid.UUID) -> RentalDefaults:
        equipment = await self.session.get(Equipment, equipment_id)
        if equipment is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Equipment not found")
        out = RentalDefaults(equipment_id=equipment_id, currency=equipment.currency or "")
        if equipment.rate_item_id is None:
            return out
        item = await self.repo.get_item(equipment.rate_item_id)
        if item is None:
            return out
        catalogue = await self.get_catalogue(item.catalogue_id)
        rates = breakdown_for(item, catalogue.interest_convention, catalogue.working_days_per_month)
        out.item_id = item.id
        out.catalogue_name = catalogue.name
        out.currency = catalogue.currency or out.currency
        out.hourly_rate, out.daily_rate, out.monthly_rate = rates.hourly, rates.daily, rates.monthly
        out.synthetic = catalogue.is_synthetic
        out.tolerance_pct = catalogue.tolerance_pct
        return out

    async def charge_preview(self, data: ChargePreviewRequest) -> ChargePreviewResponse:
        defaults = await self.rental_defaults(data.equipment_id)
        resp = ChargePreviewResponse(currency=defaults.currency, hourly_rate=defaults.hourly_rate)
        if defaults.item_id is None or defaults.hourly_rate is None:
            return resp
        item = await self.repo.get_item(defaults.item_id)
        catalogue = await self.get_catalogue(item.catalogue_id) if item else None
        if item is None or catalogue is None:
            return resp
        charge = monthly_charge(
            hourly_rate=defaults.hourly_rate,
            operational_hours=data.operational_hours,
            standby_hours=data.standby_hours,
            breakdown_hours=data.breakdown_hours,
            standby_factor=catalogue.standby_factor,
            breakdown_factor=catalogue.breakdown_factor,
            operating_cost_per_hour=item.operating_cost_per_hour,
        )
        resp.operational, resp.standby, resp.breakdown = charge["operational"], charge["standby"], charge["breakdown"]
        resp.operating_cost, resp.total = charge["operating_cost"], charge["total"]
        resp.standby_billed = catalogue.standby_factor is not None or catalogue.breakdown_factor is not None
        return resp

    async def rental_rule_issues(
        self, equipment_id: uuid.UUID, hourly_rate: Decimal, *, project_is_demo: bool
    ) -> list[IssueOut]:
        """``equip_rate.rental_deviates`` and ``synthetic_in_use`` for a rental about to be saved."""
        defaults = await self.rental_defaults(equipment_id)
        if defaults.item_id is None or defaults.hourly_rate is None:
            return []
        row = {
            "id": str(equipment_id),
            "code": "",
            "rate": hourly_rate,
            "catalogue_rate": defaults.hourly_rate,
            "tolerance_pct": defaults.tolerance_pct,
            "synthetic": defaults.synthetic,
            "project_is_demo": project_is_demo,
        }
        return _issues(await _run({"rentals": [row]}))

    async def record_rental_source(
        self, rental: Any, equipment_id: uuid.UUID, hourly_rate: Decimal, reason: str | None
    ) -> None:
        """Log where a rental's rate came from; an override carries its reason."""
        defaults = await self.rental_defaults(equipment_id)
        if defaults.item_id is None:
            return
        meta = dict(rental.metadata_ or {})
        overridden = defaults.hourly_rate is not None and Decimal(str(hourly_rate)) != defaults.hourly_rate
        meta["rate_source"] = {
            "item_id": str(defaults.item_id),
            "catalogue": defaults.catalogue_name,
            "catalogue_hourly_rate": str(defaults.hourly_rate) if defaults.hourly_rate is not None else None,
            "overridden": overridden,
            **({"reason": reason} if overridden and reason else {}),
        }
        rental.metadata_ = meta
        await self.session.flush()


async def _run(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return await run_rate_rules(payload)


__all__ = ["TEXT_FIELDS", "RateService", "breakdown_for"]
