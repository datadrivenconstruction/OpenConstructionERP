"""Resource price sheet: make coefficient cost bases calculable locally.

CWICR describes each work item (a rate_code) THROUGH its resources: the labour,
material and machine lines with a norm quantity each. Priced bases carry a unit
price on every resource line, so a work item's rate is already known. Coefficient
bases (Vietnam Dinh Muc, Indonesia AHSP) ship only the norm quantities and no
prices, because they are priced regionally - so their work items import with a
zero rate and cannot be estimated until someone supplies local resource prices.

This module closes that gap. It maintains one editable :class:`ResourcePrice`
row per resource per region (the "price sheet"), seeds it from whatever prices a
base already carries, lets a user edit any price, and re-prices every work item
in the region from the sheet:

    rate(work_item) = sum(component.quantity x sheet_price[resource]) over components

The same machinery upgrades a priced base too (re-price after a local price
edit), so it is uniform across coded and codeless bases. Money is handled as
:class:`~decimal.Decimal` and stored as a string, matching every other money
column in the schema.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.modules.costs.models import CostItem, ResourcePrice

logger = logging.getLogger(__name__)

# A resource line seeded from a base is treated as "priced" only above this
# threshold, so a stray 0.00 on one variant row never masks a real price seen
# elsewhere for the same resource.
_PRICE_EPS = Decimal("0.005")


def resource_key_for(code: str | None, name: str | None) -> str:
    """Stable per-region identity for a resource.

    Uses the resource code when the base carries one; codeless bases key on the
    normalized name (whitespace-collapsed, lowercased) with a ``name:`` prefix so
    a name key can never collide with a code. This is exactly the key a work
    item's components are matched against when re-pricing, so seeding and
    re-pricing always agree.
    """
    code = (code or "").strip()
    if code:
        return code[:100]
    norm = " ".join((name or "").split()).lower()
    return ("name:" + norm)[:300] if norm else "name:"


def _to_decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    """Parse a money/quantity value (str | int | float | None) to Decimal."""
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def _q2(value: Decimal) -> Decimal:
    """Round to 2 dp (money) with the schema's half-up convention."""
    return value.quantize(Decimal("0.01"))


@dataclass
class SeedResult:
    """Outcome of seeding a region's price sheet from its work items."""

    region: str
    resources: int = 0
    created: int = 0
    updated: int = 0
    priced: int = 0
    unpriced: int = 0
    preserved_user_edits: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "resources": self.resources,
            "created": self.created,
            "updated": self.updated,
            "priced": self.priced,
            "unpriced": self.unpriced,
            "preserved_user_edits": self.preserved_user_edits,
            "coverage": round(self.priced / self.resources, 4) if self.resources else 0.0,
        }


@dataclass
class RepriceResult:
    """Outcome of re-pricing a region's work items from its price sheet."""

    region: str
    items_total: int = 0
    items_repriced: int = 0
    items_changed: int = 0
    items_fully_priced: int = 0
    items_partially_priced: int = 0
    items_unpriced: int = 0
    missing_resources: set[str] = field(default_factory=set)
    dry_run: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "items_total": self.items_total,
            "items_repriced": self.items_repriced,
            "items_changed": self.items_changed,
            "items_fully_priced": self.items_fully_priced,
            "items_partially_priced": self.items_partially_priced,
            "items_unpriced": self.items_unpriced,
            "coverage": (round(self.items_fully_priced / self.items_total, 4) if self.items_total else 0.0),
            "missing_resource_count": len(self.missing_resources),
            "missing_resources_sample": sorted(self.missing_resources)[:25],
            "dry_run": self.dry_run,
        }


class ResourcePriceService:
    """Read/seed/edit the per-region resource price sheet and re-price bases."""

    # Cap a single re-price pass so a runaway region cannot lock the request for
    # minutes; well above any real regional base (the largest is ~60K items).
    _MAX_REPRICE_ITEMS = 250_000

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── seeding ──────────────────────────────────────────────────────────────

    async def seed_region(self, region: str) -> SeedResult:
        """Populate the price sheet for ``region`` from its work items.

        Distinct resources are collected from every work item's components. Each
        gets one sheet row; the seeded ``unit_price`` is the largest per-unit
        price observed for that resource across the base (0 for a coefficient
        base, which is the editable slot the user fills in). Idempotent: existing
        rows are refreshed, but a row a user has edited (``source == 'user'``) is
        never overwritten, so re-seeding after an import keeps local prices.
        """
        result = SeedResult(region=region)

        # Pull only the two columns needed to enumerate resources - never the
        # heavy description/metadata columns. Fully buffered (not a server-side
        # cursor) so the read completes before the seed writes below, which keeps
        # it safe under the savepoint-bound test session and embedded runtime.
        stmt = select(CostItem.components, CostItem.currency).where(
            CostItem.region == region, CostItem.is_active.is_(True)
        )
        observed: dict[str, dict[str, Any]] = {}
        currency_hint = ""
        for components, currency in (await self.session.execute(stmt)).all():
            if currency and not currency_hint:
                currency_hint = currency
            for comp in components or []:
                if not isinstance(comp, dict):
                    continue
                key = resource_key_for(comp.get("code"), comp.get("name"))
                price = _to_decimal(comp.get("unit_rate"))
                slot = observed.get(key)
                if slot is None:
                    slot = {
                        "resource_code": (comp.get("code") or "").strip()[:100],
                        "resource_name": (comp.get("name") or "").strip()[:300],
                        "resource_type": (comp.get("type") or "material") or "material",
                        "unit": (comp.get("unit") or "").strip()[:30],
                        "price": price,
                        "currency": currency or "",
                    }
                    observed[key] = slot
                else:
                    # Keep the strongest signal: the highest observed unit price
                    # and a non-empty name/unit/code if this row fills a gap.
                    if price > slot["price"]:
                        slot["price"] = price
                    if not slot["resource_name"] and comp.get("name"):
                        slot["resource_name"] = str(comp["name"]).strip()[:300]
                    if not slot["resource_code"] and comp.get("code"):
                        slot["resource_code"] = str(comp["code"]).strip()[:100]
                    if not slot["unit"] and comp.get("unit"):
                        slot["unit"] = str(comp["unit"]).strip()[:30]
                    if not slot["currency"] and currency:
                        slot["currency"] = currency

        if not observed:
            return result

        # Load existing sheet rows for the region in one query.
        existing_rows = (
            (await self.session.execute(select(ResourcePrice).where(ResourcePrice.region == region))).scalars().all()
        )
        existing = {row.resource_key: row for row in existing_rows}

        result.resources = len(observed)
        for key, slot in observed.items():
            price: Decimal = slot["price"]
            is_priced = price >= _PRICE_EPS
            if is_priced:
                result.priced += 1
            else:
                result.unpriced += 1

            row = existing.get(key)
            if row is None:
                self.session.add(
                    ResourcePrice(
                        region=region,
                        resource_key=key,
                        resource_code=slot["resource_code"],
                        resource_name=slot["resource_name"] or key,
                        resource_type=slot["resource_type"],
                        unit=slot["unit"],
                        unit_price=str(_q2(price)),
                        currency=slot["currency"] or currency_hint,
                        source="cwicr_import",
                        is_active=True,
                    )
                )
                result.created += 1
                continue

            # Refresh metadata on any row, but never touch a user-edited price.
            row.resource_code = row.resource_code or slot["resource_code"]
            row.resource_name = row.resource_name or slot["resource_name"] or key
            row.resource_type = slot["resource_type"] or row.resource_type
            row.unit = row.unit or slot["unit"]
            if not row.currency:
                row.currency = slot["currency"] or currency_hint
            if row.source == "user":
                result.preserved_user_edits += 1
            else:
                # Only lift the price when the base actually carries one, so a
                # re-seed never clobbers a good seeded price with a 0 from a
                # variant row.
                if is_priced:
                    row.unit_price = str(_q2(price))
                result.updated += 1

        await self.session.commit()
        logger.info(
            "Seeded resource prices for %s: %d resources (%d priced, %d unpriced), "
            "%d created, %d updated, %d user edits preserved",
            region,
            result.resources,
            result.priced,
            result.unpriced,
            result.created,
            result.updated,
            result.preserved_user_edits,
        )
        return result

    # ── reading ──────────────────────────────────────────────────────────────

    async def region_stats(self, region: str) -> dict[str, Any]:
        """Coverage stats for a region's price sheet (counts + priced ratio)."""
        total = (
            await self.session.execute(
                select(func.count())
                .select_from(ResourcePrice)
                .where(ResourcePrice.region == region, ResourcePrice.is_active.is_(True))
            )
        ).scalar_one()
        priced = (
            await self.session.execute(
                select(func.count())
                .select_from(ResourcePrice)
                .where(
                    ResourcePrice.region == region,
                    ResourcePrice.is_active.is_(True),
                    ResourcePrice.unit_price.notin_(["0", "0.0", "0.00", ""]),
                )
            )
        ).scalar_one()
        return {
            "region": region,
            "resources": int(total),
            "priced": int(priced),
            "unpriced": int(total) - int(priced),
            "coverage": round(int(priced) / int(total), 4) if total else 0.0,
        }

    async def list_prices(
        self,
        region: str,
        *,
        search: str | None = None,
        resource_type: str | None = None,
        only_unpriced: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[ResourcePrice], int]:
        """Paginated price-sheet rows for a region, newest-priced first.

        Returns ``(rows, total)`` where total is the count before pagination.
        """
        limit = max(1, min(limit, 500))
        offset = max(0, offset)
        conds = [ResourcePrice.region == region, ResourcePrice.is_active.is_(True)]
        if resource_type:
            conds.append(ResourcePrice.resource_type == resource_type)
        if only_unpriced:
            conds.append(ResourcePrice.unit_price.in_(["0", "0.0", "0.00", ""]))
        if search:
            like = f"%{search.strip()}%"
            conds.append(func.lower(ResourcePrice.resource_name).like(like.lower()))

        total = (await self.session.execute(select(func.count()).select_from(ResourcePrice).where(*conds))).scalar_one()
        rows = (
            (
                await self.session.execute(
                    select(ResourcePrice)
                    .where(*conds)
                    .order_by(ResourcePrice.resource_type, ResourcePrice.resource_name)
                    .limit(limit)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        return list(rows), int(total)

    # ── editing ──────────────────────────────────────────────────────────────

    async def set_price(
        self,
        region: str,
        resource_key: str,
        unit_price: str | Decimal,
        *,
        currency: str | None = None,
        unit: str | None = None,
        resource_name: str | None = None,
        resource_type: str | None = None,
        updated_by: uuid.UUID | None = None,
    ) -> ResourcePrice:
        """Set one resource's unit price for a region (creates the row if new).

        Marks the row ``source == 'user'`` so a later re-seed leaves it alone.
        """
        price = _to_decimal(unit_price)
        if price < 0:
            raise ValueError("unit_price must not be negative")

        row = (
            await self.session.execute(
                select(ResourcePrice).where(
                    ResourcePrice.region == region,
                    ResourcePrice.resource_key == resource_key,
                )
            )
        ).scalar_one_or_none()

        if row is None:
            row = ResourcePrice(
                region=region,
                resource_key=resource_key,
                resource_code="" if resource_key.startswith("name:") else resource_key,
                resource_name=(resource_name or resource_key)[:300],
                resource_type=resource_type or "material",
                unit=(unit or "")[:30],
                unit_price=str(_q2(price)),
                currency=(currency or "")[:10],
                source="user",
                is_active=True,
                updated_by=updated_by,
            )
            self.session.add(row)
        else:
            row.unit_price = str(_q2(price))
            row.source = "user"
            row.is_active = True
            if currency:
                row.currency = currency[:10]
            if unit:
                row.unit = unit[:30]
            if resource_name:
                row.resource_name = resource_name[:300]
            if resource_type:
                row.resource_type = resource_type
            row.updated_by = updated_by

        await self.session.commit()
        await self.session.refresh(row)
        return row

    async def set_prices_bulk(
        self,
        region: str,
        updates: list[dict[str, Any]],
        *,
        updated_by: uuid.UUID | None = None,
    ) -> int:
        """Apply many price edits in one transaction. Returns rows written.

        Each update is ``{"resource_key", "unit_price", optional metadata}``.
        Unknown keys create a row (source='user'); it is the caller's job to pass
        keys that exist in the region if they want an in-place edit.
        """
        by_key = {
            row.resource_key: row
            for row in (
                (await self.session.execute(select(ResourcePrice).where(ResourcePrice.region == region)))
                .scalars()
                .all()
            )
        }
        written = 0
        for upd in updates:
            key = str(upd.get("resource_key") or "").strip()
            if not key:
                continue
            price = _to_decimal(upd.get("unit_price"))
            if price < 0:
                continue
            row = by_key.get(key)
            if row is None:
                row = ResourcePrice(
                    region=region,
                    resource_key=key,
                    resource_code="" if key.startswith("name:") else key,
                    resource_name=str(upd.get("resource_name") or key)[:300],
                    resource_type=str(upd.get("resource_type") or "material"),
                    unit=str(upd.get("unit") or "")[:30],
                    unit_price=str(_q2(price)),
                    currency=str(upd.get("currency") or "")[:10],
                    source="user",
                    is_active=True,
                    updated_by=updated_by,
                )
                self.session.add(row)
                by_key[key] = row
            else:
                row.unit_price = str(_q2(price))
                row.source = "user"
                row.updated_by = updated_by
                if upd.get("currency"):
                    row.currency = str(upd["currency"])[:10]
            written += 1
        await self.session.commit()
        return written

    # ── re-pricing ───────────────────────────────────────────────────────────

    async def _price_map(self, region: str) -> dict[str, Decimal]:
        rows = (
            await self.session.execute(
                select(ResourcePrice.resource_key, ResourcePrice.unit_price).where(
                    ResourcePrice.region == region,
                    ResourcePrice.is_active.is_(True),
                )
            )
        ).all()
        return {key: _to_decimal(price) for key, price in rows}

    async def reprice_region(self, region: str, *, dry_run: bool = False) -> RepriceResult:
        """Recompute every work item's rate in ``region`` from the price sheet.

        For each work item: ``rate = sum(component.quantity x sheet_price)``. Each
        component's ``unit_rate`` and ``cost`` are rewritten to match the sheet,
        and the metadata labour/material/equipment breakdown is refreshed, so the
        stored rate and its explanation stay consistent. ``dry_run`` computes the
        summary without writing.
        """
        result = RepriceResult(region=region, dry_run=dry_run)
        prices = await self._price_map(region)
        if not prices:
            return result

        # Buffer the work items (only the columns we rewrite) so the read cursor
        # closes before any write - interleaving flushes with an open server-side
        # cursor is unsafe on asyncpg. Load only rate/components/metadata (plus
        # the always-present PK) to keep the buffer lean.
        stmt = (
            select(CostItem)
            .options(load_only(CostItem.rate, CostItem.components, CostItem.metadata_))
            .where(CostItem.region == region, CostItem.is_active.is_(True))
            .limit(self._MAX_REPRICE_ITEMS)
        )
        items = (await self.session.execute(stmt)).scalars().all()
        pending = 0
        for item in items:
            result.items_total += 1
            components = item.components or []
            if not components:
                result.items_unpriced += 1
                continue

            new_total = Decimal("0")
            by_type: dict[str, Decimal] = {}
            priced_lines = 0
            total_lines = 0
            new_components: list[dict[str, Any]] = []
            for comp in components:
                if not isinstance(comp, dict):
                    new_components.append(comp)
                    continue
                total_lines += 1
                key = resource_key_for(comp.get("code"), comp.get("name"))
                unit_price = prices.get(key)
                qty = _to_decimal(comp.get("quantity"))
                new_comp = dict(comp)
                if unit_price is not None and unit_price >= _PRICE_EPS:
                    priced_lines += 1
                    line_cost = _q2(qty * unit_price)
                    new_comp["unit_rate"] = float(unit_price)
                    new_comp["cost"] = float(line_cost)
                    new_total += line_cost
                    ctype = str(comp.get("type") or "other")
                    by_type[ctype] = by_type.get(ctype, Decimal("0")) + line_cost
                else:
                    result.missing_resources.add(key)
                new_components.append(new_comp)

            if total_lines and priced_lines == total_lines:
                result.items_fully_priced += 1
            elif priced_lines:
                result.items_partially_priced += 1
            else:
                result.items_unpriced += 1
                # No line priced: leave the item untouched rather than zero it.
                continue

            new_rate_str = str(_q2(new_total))
            changed = new_rate_str != str(item.rate)
            if changed:
                result.items_changed += 1
            result.items_repriced += 1

            if not dry_run:
                item.rate = new_rate_str
                item.components = new_components
                meta = dict(item.metadata_ or {})
                if by_type.get("labor") is not None or by_type.get("operator") is not None:
                    meta["labor_cost"] = float(
                        _q2(by_type.get("labor", Decimal("0")) + by_type.get("operator", Decimal("0")))
                    )
                if by_type.get("material") is not None:
                    meta["material_cost"] = float(_q2(by_type["material"]))
                equip = by_type.get("equipment", Decimal("0")) + by_type.get("electricity", Decimal("0"))
                if equip:
                    meta["equipment_cost"] = float(_q2(equip))
                item.metadata_ = meta
                pending += 1
                if pending >= 500:
                    await self.session.flush()
                    pending = 0

        if not dry_run:
            await self.session.commit()
        logger.info(
            "Repriced %s: %d/%d items (%d changed, %d fully, %d partial, %d unpriced)%s",
            region,
            result.items_repriced,
            result.items_total,
            result.items_changed,
            result.items_fully_priced,
            result.items_partially_priced,
            result.items_unpriced,
            " [dry-run]" if dry_run else "",
        )
        return result
