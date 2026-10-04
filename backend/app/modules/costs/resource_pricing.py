# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
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

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.core.events import event_bus
from app.modules.costs.models import CostItem, ResourcePrice

logger = logging.getLogger(__name__)


async def _safe_publish(name: str, data: dict[str, Any], source_module: str = "") -> None:
    """Publish without letting a bus failure fail the reprice that succeeded.

    Same shape as the one in ``costs.service``, kept local rather than imported
    so this module keeps its one-way dependency on the models and does not start
    importing the service that sits above it.
    """
    try:
        event_bus.publish_detached(name, data, source_module=source_module)
    except Exception:
        logger.debug("Event publish skipped: %s", name)


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
    """Parse a money value (str | int | float | None) to Decimal.

    An absent or unparseable value yields ``default``. That is the right
    contract for every price slot in this module: a coefficient base ships no
    prices at all, and a 0 there is then classified as unpriced by
    ``_PRICE_EPS``. It is NOT the right contract for a component's quantity -
    see :func:`component_quantity`.
    """
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


# Keys a recipe component may carry its norm quantity under. ``quantity`` is
# canonical and is what the CWICR ingest writes. ``factor`` is read as a legacy
# alias: it is the assemblies module's word for the same idea
# (``oe_assemblies_component.factor``), it is what the shipped recipe template
# and the import guide asked for up to 16.2.0, so customer files written against
# that documentation exist and must keep working. New writes are canonicalised
# to ``quantity`` at the API boundary (see ``CostItemCreate.components``).
_QUANTITY_KEYS: tuple[str, ...] = ("quantity", "factor")


def component_quantity(comp: dict[str, Any]) -> Decimal | None:
    """Norm quantity of a recipe component, or ``None`` when it carries none.

    A missing quantity is not a quantity of zero. Reading it as zero prices the
    line at nothing while the line still looks successfully priced, which turns
    a recipe the platform cannot read into a rate of ``0.00`` that reports
    itself as complete. So this returns ``None`` for anything unusable and
    leaves it to the caller to refuse or report the component.

    Args:
        comp: One entry of ``CostItem.components``.

    Returns:
        The quantity as a :class:`~decimal.Decimal` when the component carries a
        usable one - an explicit ``0`` included, which is a real quantity.
        ``None`` when the key is absent, blank, unparseable, not finite (a NaN
        can reach here from a parquet column with nulls) or negative.
    """
    for key in _QUANTITY_KEYS:
        if key not in comp:
            continue
        raw = comp[key]
        if raw is None or raw == "":
            continue
        try:
            qty = Decimal(str(raw))
        except (InvalidOperation, ValueError, TypeError):
            return None
        if not qty.is_finite() or qty < 0:
            return None
        return qty
    return None


def _q2(value: Decimal) -> Decimal:
    """Round to 2 dp (money) with the schema's half-up convention."""
    return value.quantize(Decimal("0.01"))


# Component types folded into each published breakdown bucket. Anything not
# listed lands in ``other_cost``, so the three named buckets plus the catch-all
# always add up to the rate no matter what a base calls its component types.
_LABOR_TYPES: frozenset[str] = frozenset({"labor", "operator"})
_EQUIPMENT_TYPES: frozenset[str] = frozenset({"equipment", "electricity"})
_MATERIAL_TYPES: frozenset[str] = frozenset({"material"})


def _breakdown_metadata(
    metadata: dict[str, Any] | None,
    by_type: dict[str, Decimal],
    total: Decimal,
) -> dict[str, Any]:
    """Restate an item's cost breakdown so it adds up to the repriced rate.

    Every component type that went into the rate is accounted for. The three
    named buckets keep the shape the catalogue API and the estimator UI already
    read; every other type (a subcontractor line, say) lands in ``other_cost``
    rather than being summed into the rate and left out of the explanation of
    it. ``cost_by_type`` carries the same money split by its own type name, so a
    reader can say what the catch-all is made of.

    All four money keys are written unconditionally, zeros included. The rate
    has just been recomputed from the price sheet, so any figure the previous
    import stamped is stale, and a stale bucket sitting next to a fresh rate is
    the same defect in a smaller place.

    Args:
        metadata: The item's existing metadata, or ``None``.
        by_type: Line costs accumulated per component ``type``.
        total: The recomputed rate; the buckets are guaranteed to sum to it.

    Returns:
        A new metadata dict. The caller assigns it, so the ORM sees a new object
        and marks the JSON column dirty.
    """
    meta = dict(metadata or {})
    labor = sum((v for k, v in by_type.items() if k in _LABOR_TYPES), Decimal("0"))
    material = sum((v for k, v in by_type.items() if k in _MATERIAL_TYPES), Decimal("0"))
    equipment = sum((v for k, v in by_type.items() if k in _EQUIPMENT_TYPES), Decimal("0"))
    meta["labor_cost"] = float(_q2(labor))
    meta["material_cost"] = float(_q2(material))
    meta["equipment_cost"] = float(_q2(equipment))
    # Derived from the total rather than re-summed, so rounding can never leave
    # the four buckets short of the rate they claim to explain.
    meta["other_cost"] = float(_q2(total - labor - material - equipment))
    meta["cost_by_type"] = {ctype: float(_q2(amount)) for ctype, amount in sorted(by_type.items())}
    return meta


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
    # Items left untouched because their recipe could not be read: at least one
    # component carried no usable quantity. Kept apart from ``items_unpriced``,
    # which means "we know the recipe, we do not know the prices".
    items_unreadable: int = 0
    # Items left untouched because a fully priced recipe computed to nothing.
    items_zero_total: int = 0
    missing_resources: set[str] = field(default_factory=set)
    unreadable_resources: set[str] = field(default_factory=set)
    dry_run: bool = False
    # True when the region held more work items than one pass may walk, so the
    # counts above describe the first ``items_cap`` of it and not the region.
    # Without this the caller reads a complete-looking summary of an incomplete
    # pass: ``items_total`` equals the cap, ``coverage`` is computed against it,
    # and nothing says the remainder still carries its old rates.
    items_truncated: bool = False
    items_cap: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "region": self.region,
            "items_total": self.items_total,
            "items_repriced": self.items_repriced,
            "items_changed": self.items_changed,
            "items_fully_priced": self.items_fully_priced,
            "items_partially_priced": self.items_partially_priced,
            "items_unpriced": self.items_unpriced,
            "items_unreadable": self.items_unreadable,
            "items_zero_total": self.items_zero_total,
            "coverage": (round(self.items_fully_priced / self.items_total, 4) if self.items_total else 0.0),
            "missing_resource_count": len(self.missing_resources),
            "missing_resources_sample": sorted(self.missing_resources)[:25],
            "unreadable_resource_count": len(self.unreadable_resources),
            "unreadable_resources_sample": sorted(self.unreadable_resources)[:25],
            "dry_run": self.dry_run,
            "items_truncated": self.items_truncated,
            "items_cap": self.items_cap,
        }


class ResourcePriceService:
    """Read/seed/edit the per-region resource price sheet and re-price bases."""

    # Cap a single re-price pass so a runaway region cannot lock the request for
    # minutes; well above any real regional base (the largest is ~60K items).
    #
    # A region past the cap is repriced up to it and the rest is left alone,
    # which is a truncation. It is reported as one - ``items_truncated`` on the
    # result, and the cap itself next to it - because ``items_total`` otherwise
    # reads as the size of the region rather than as the size of the slice that
    # was walked, and ``coverage`` is computed against it.
    _MAX_REPRICE_ITEMS = 250_000

    # Work items read, repriced and released in one page.
    #
    # A reprice page is heavier than the seed scan's: the seed reads a
    # two-column tuple per row, this reads a whole ``CostItem`` entity carrying
    # two JSON documents, measured at ~4.6 KiB per work item, so 250 000 of them
    # in one buffered read is ~1.1 GiB and a real 55 700-item region is ~250 MiB.
    # At this page size the same walk holds ~9 MiB.
    #
    # Paging the read is only half of the bound. The session keeps every entity
    # it hands out, and these are entities the loop then MUTATES, so they are
    # retained until the transaction ends however the read was shaped - which is
    # why each page is flushed and expunged below rather than merely read.
    _REPRICE_SCAN_ROWS = 2000

    # Work items read in one page while the price sheet is being seeded.
    #
    # ``seed_region`` runs in the same request as a cost-base import, directly
    # after it, and it scans the components breakdown of every work item in the
    # region - the same JSON whose accumulation in the importer exhausted a
    # small server. Reading the region in a single buffered result put every one
    # of those breakdowns in memory at once, roughly 55 700 of them for a large
    # region, on top of what the import had just been holding.
    #
    # Paging changes nothing about the answer: the scan only ever folds a row
    # into ``observed``, which is keyed by resource and so is bounded by the
    # number of DISTINCT resources rather than by the number of work items.
    # Each page is still fully buffered before it is walked, so the read cursor
    # is closed before the seed writes below - the property the single read was
    # chosen for.
    _SEED_SCAN_ROWS = 5000

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ── seeding ──────────────────────────────────────────────────────────────

    async def seed_region(self, region: str, *, currency: str | None = None) -> SeedResult:
        """Populate the price sheet for ``region`` from its work items.

        Distinct resources are collected from every work item's components. Each
        gets one sheet row; the seeded ``unit_price`` is the largest per-unit
        price observed for that resource across the base (0 for a coefficient
        base, which is the editable slot the user fills in). Idempotent: existing
        rows are refreshed, but a row a user has edited (``source == 'user'``) is
        never overwritten, so re-seeding after an import keeps local prices.

        ``currency`` limits the scan to work items priced in that currency. A
        return to the home market passes the home currency: an item still
        carrying a market's prices would otherwise offer them as observed home
        prices, and the largest-price rule lets a high-number currency win.
        """
        result = SeedResult(region=region)

        # Pull only the two columns needed to enumerate resources - never the
        # heavy description/metadata columns. Each page is fully buffered (not a
        # server-side cursor) so the read completes before the seed writes below,
        # which keeps it safe under the savepoint-bound test session and embedded
        # runtime. ``order_by`` is what makes the paging total rather than
        # merely repeated: without it the offsets address an undefined order and
        # a row can be served twice or skipped.
        page_rows = self._SEED_SCAN_ROWS
        stmt = (
            select(CostItem.components, CostItem.currency)
            .where(CostItem.region == region, CostItem.is_active.is_(True))
            .order_by(CostItem.id)
        )
        if currency is not None:
            stmt = stmt.where(CostItem.currency == currency)
        observed: dict[str, dict[str, Any]] = {}
        currency_hint = ""
        offset = 0
        while True:
            page = (await self.session.execute(stmt.offset(offset).limit(page_rows))).all()
            if not page:
                break
            for components, currency in page:
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
                        # Keep the strongest signal: the highest observed unit
                        # price and a non-empty name/unit/code if this row fills
                        # a gap. Order-independent, so paging cannot change it.
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
            if len(page) < page_rows:
                break
            offset += page_rows

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

    async def reprice_region(
        self,
        region: str,
        *,
        dry_run: bool = False,
        where: Any = None,
        stamp_currency: str | None = None,
    ) -> RepriceResult:
        """Recompute every work item's rate in ``region`` from the price sheet.

        ``where`` narrows the walk to the work items matching it. It must not
        depend on a column this pass writes during the walk (rate, components,
        metadata): the region is paged by offset, and a filter the writes change
        would move rows out from under the pages. ``stamp_currency`` is written
        onto every item whose rate the pass rewrote, after the walk and in the
        same transaction, so the new rate never shows under an old label.

        For each work item: ``rate = sum(component.quantity x sheet_price)``. Each
        component's ``unit_rate`` and ``cost`` are rewritten to match the sheet,
        and the metadata breakdown is refreshed to add up to the new rate, so the
        stored rate and its explanation stay consistent. ``dry_run`` computes the
        summary without writing.

        Three outcomes leave an item's rate alone rather than publish a number
        that cannot be trusted, and each is reported separately: no priced line
        at all (``items_unpriced``), a component with no usable quantity
        (``items_unreadable``), and a fully priced recipe that computes to
        nothing while the item already carries a rate (``items_zero_total``).
        Only an item whose rate was actually recomputed counts towards
        ``items_fully_priced`` and therefore towards ``coverage``.

        The region is walked in pages of ``_REPRICE_SCAN_ROWS``, each flushed
        and released before the next is read, so the pass holds one page rather
        than the region. A region larger than ``_MAX_REPRICE_ITEMS`` is repriced
        up to that ceiling and reports ``items_truncated`` with the ceiling
        beside it, because every other number on the result then describes the
        slice that was walked and not the region.
        """
        result = RepriceResult(region=region, dry_run=dry_run)
        prices = await self._price_map(region)
        if not prices:
            return result

        # Read the work items (only the columns we rewrite) in bounded pages.
        # Each page is fully buffered, so the read cursor closes before the
        # writes below - interleaving flushes with an open server-side cursor is
        # unsafe on asyncpg - and ``order_by`` is what makes the paging total
        # rather than merely repeated, since offsets over an undefined order can
        # serve a row twice or skip one. The reprice writes rate, components and
        # metadata only, none of which appear in the filter or the ordering, so
        # the pages stay addressable while it walks them. Load only
        # rate/components/metadata (plus the always-present PK) to keep each
        # page lean.
        stmt = (
            select(CostItem)
            .options(load_only(CostItem.rate, CostItem.components, CostItem.metadata_))
            .where(CostItem.region == region, CostItem.is_active.is_(True))
            .order_by(CostItem.id)
        )
        if where is not None:
            stmt = stmt.where(where)
        # Ids of the items whose rate this pass rewrote, kept only when they
        # are to be given ``stamp_currency`` after the walk.
        written_ids: list[uuid.UUID] = []
        result.items_cap = self._MAX_REPRICE_ITEMS
        pending = 0
        offset = 0
        hit_cap = False
        while True:
            if offset >= self._MAX_REPRICE_ITEMS:
                hit_cap = True
                break
            page_rows = min(self._REPRICE_SCAN_ROWS, self._MAX_REPRICE_ITEMS - offset)
            page = (await self.session.execute(stmt.offset(offset).limit(page_rows))).scalars().all()
            if not page:
                break
            for item in page:
                result.items_total += 1
                components = item.components or []
                if not components:
                    result.items_unpriced += 1
                    continue

                new_total = Decimal("0")
                by_type: dict[str, Decimal] = {}
                priced_lines = 0
                total_lines = 0
                unreadable_lines = 0
                new_components: list[dict[str, Any]] = []
                for comp in components:
                    if not isinstance(comp, dict):
                        new_components.append(comp)
                        continue
                    total_lines += 1
                    key = resource_key_for(comp.get("code"), comp.get("name"))
                    qty = component_quantity(comp)
                    new_comp = dict(comp)
                    if qty is None:
                        # No usable quantity: this line cannot contribute a cost and
                        # must not be counted as one. Checked before the price so a
                        # malformed line is reported as malformed rather than as an
                        # ordinary gap in price coverage.
                        unreadable_lines += 1
                        result.unreadable_resources.add(key)
                        new_components.append(new_comp)
                        continue
                    unit_price = prices.get(key)
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

                if unreadable_lines:
                    # A recipe we cannot read is not a recipe we can price. Writing
                    # a rate here would publish a number computed from a total that
                    # was never computable, and the counts above would call it a
                    # success. Leave the item exactly as it was and report it.
                    result.items_unreadable += 1
                    continue

                fully_priced = bool(total_lines) and priced_lines == total_lines
                if not priced_lines:
                    result.items_unpriced += 1
                    # No line priced: leave the item untouched rather than zero it.
                    continue

                new_rate_str = str(_q2(new_total))
                if new_total == 0 and _to_decimal(item.rate) != 0:
                    # Every priced line came to nothing yet the item already carries
                    # a rate. Whatever the cause, overwriting a real rate with 0.00
                    # and calling the run fully priced is the worst of the two
                    # possible mistakes, so refuse and report instead.
                    result.items_zero_total += 1
                    continue

                if fully_priced:
                    result.items_fully_priced += 1
                else:
                    result.items_partially_priced += 1

                changed = new_rate_str != str(item.rate)
                if changed:
                    result.items_changed += 1
                result.items_repriced += 1

                if not dry_run:
                    item.rate = new_rate_str
                    item.components = new_components
                    item.metadata_ = _breakdown_metadata(item.metadata_, by_type, new_total)
                    if stamp_currency is not None:
                        written_ids.append(item.id)
                    pending += 1
                    if pending >= 500:
                        await self.session.flush()
                        pending = 0

            offset += len(page)
            # Write out whatever the page left pending, then let go of it. The
            # order is load-bearing: expunging first would detach the instances
            # with their UPDATEs still unflushed and this page's work would be
            # dropped on the floor. Releasing is the half that bounds memory -
            # paging the read alone does not, because the session keeps every
            # entity it hands out, and these are entities the loop then mutates.
            if not dry_run and pending:
                await self.session.flush()
                pending = 0
            for item in page:
                self.session.expunge(item)
            if len(page) < page_rows:
                break

        if hit_cap:
            # The pass stopped on the cap rather than on the end of the region.
            # Look one row past it before saying so: a region that ends exactly
            # on the cap is complete, and reporting that one as truncated would
            # be its own false alarm.
            overflow = (await self.session.execute(stmt.offset(offset).limit(1))).scalars().all()
            result.items_truncated = bool(overflow)
            for item in overflow:
                self.session.expunge(item)

        if not dry_run:
            # After the walk, so the ``where`` the pages were read through never
            # saw a row change under it. Chunked: one statement may carry at
            # most 32 767 bound values.
            for start in range(0, len(written_ids), 1000):
                await self.session.execute(
                    update(CostItem)
                    .where(CostItem.id.in_(written_ids[start : start + 1000]))
                    .values(currency=stamp_currency)
                )
            await self.session.commit()
            # Announce the reprice so the assemblies subscriber can pull the new
            # rates through. Without this the rates moved and every assembly
            # built on them kept its own copy, so a repriced region never
            # reached a budget - the one path of the three that write
            # CostItem.rate which published nothing.
            #
            # One event for the region, not one per item: the cap on a single
            # run is 250 000 items, and that many detached tasks each opening
            # its own session is a different outage. The subscriber joins
            # Component to CostItem on region instead, which is bounded by how
            # many components exist rather than by how many prices moved.
            #
            # Published after the commit, deliberately. The subscriber reads the
            # rate back through its own session, so publishing before the commit
            # is a race it can lose, and losing it means writing the old rate
            # back over the new one.
            if result.items_changed:
                await _safe_publish(
                    "costs.region.repriced",
                    {"region": region, "items_changed": result.items_changed},
                    source_module="oe_costs",
                )
        logger.info(
            "Repriced %s: %d/%d items (%d changed, %d fully, %d partial, %d unpriced, %d unreadable, %d zero-total)%s",
            region,
            result.items_repriced,
            result.items_total,
            result.items_changed,
            result.items_fully_priced,
            result.items_partially_priced,
            result.items_unpriced,
            result.items_unreadable,
            result.items_zero_total,
            (" [dry-run]" if dry_run else "")
            + (f" [TRUNCATED at {result.items_cap}]" if result.items_truncated else ""),
        )
        return result

    # ── market repricing ──────────────────────────────────────────────────────

    async def apply_market_catalog(
        self,
        base_region: str,
        market_token: str,
        rows: list[dict[str, Any]],
    ) -> RepriceResult:
        """Reprice a base into one market by overlaying that market's prices.

        Each parsed market-CSV row carries a language-independent ``resource_code``
        (identical to the base parquet's component codes) plus that market's
        ``price_avg`` and ``currency``. We upsert one price-sheet row per resource
        for ``base_region`` from the CSV, OVERWRITING whatever was there before -
        including ``source == 'user'`` edits: switching the pricing basis to a new
        market is an explicit, intended reset, unlike :meth:`seed_region` which
        preserves user edits. We then re-price every work item from the refreshed
        sheet.

        CRITICAL: :meth:`reprice_region` rewrites rates but never touches
        ``CostItem.currency``. Without also stamping the market currency onto the
        region's cost items, the freshly repriced (e.g. GBP) rates would still
        render under the base's home-currency label (e.g. CNY). So this method
        finishes by updating ``oe_costs_item.currency`` for the region.

        Returns the :class:`RepriceResult` from the reprice pass.
        """
        # The market currency is uniform across the CSV; take the first non-empty.
        market_currency = ""
        for row in rows:
            candidate = str(row.get("currency") or "").strip().upper()
            if candidate:
                market_currency = candidate
                break

        # Load the region's existing sheet rows once for an in-memory upsert.
        existing_rows = (
            (await self.session.execute(select(ResourcePrice).where(ResourcePrice.region == base_region)))
            .scalars()
            .all()
        )
        existing = {row.resource_key: row for row in existing_rows}

        written = 0
        for row in rows:
            code = str(row.get("resource_code") or "").strip()
            name = str(row.get("name") or "").strip()
            key = resource_key_for(code, name)
            if key == "name:":
                # No code and no name - nothing to key on; skip.
                continue
            price = _to_decimal(row.get("price_avg"))
            rtype = (str(row.get("type") or "material").strip().lower() or "material")[:30]
            unit = str(row.get("unit") or "").strip()[:30]

            sheet_row = existing.get(key)
            if sheet_row is None:
                sheet_row = ResourcePrice(
                    region=base_region,
                    resource_key=key,
                    resource_code=code[:100],
                    resource_name=(name or key)[:300],
                    resource_type=rtype,
                    unit=unit,
                    unit_price=str(_q2(price)),
                    currency=market_currency,
                    source="regional",
                    is_active=True,
                )
                self.session.add(sheet_row)
                existing[key] = sheet_row
            else:
                # Overwrite unconditionally - the market basis wins over any prior
                # seeded OR user-edited price (differs from seed_region on purpose).
                sheet_row.unit_price = str(_q2(price))
                sheet_row.currency = market_currency or sheet_row.currency
                sheet_row.resource_type = rtype
                if unit:
                    sheet_row.unit = unit
                if code and not sheet_row.resource_code:
                    sheet_row.resource_code = code[:100]
                if name:
                    sheet_row.resource_name = name[:300]
                sheet_row.source = "regional"
                sheet_row.is_active = True
            written += 1

        # Make the overlaid sheet visible to reprice_region's price-map read.
        await self.session.flush()
        logger.info(
            "Applied market %s to %s: %d resource prices overlaid (%s)",
            market_token,
            base_region,
            written,
            market_currency or "currency unset",
        )

        # Re-price every work item from the refreshed sheet (commits the upserts).
        result = await self.reprice_region(base_region)

        # Stamp the market currency onto the region's cost items so the repriced
        # rates render under the right currency label (reprice_region does not).
        if market_currency:
            await self.session.execute(
                update(CostItem).where(CostItem.region == base_region).values(currency=market_currency)
            )
            await self.session.commit()

        return result
