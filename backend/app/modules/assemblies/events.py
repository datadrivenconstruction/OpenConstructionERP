# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Assemblies event subscribers​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ - keep total_rate fresh.

Without this subscriber, ``Assembly.total_rate`` was a denormalised
string snapshot computed once at component create/update/delete time.
When a ``CostItem.rate`` changed externally via the costs module,
every Assembly that referenced it carried a stale unit_cost on its
Components and a stale total_rate on the parent - and any BOQ
position created from the assembly inherited the stale value
forever.

The subscriber listens for ``costs.item.updated``, finds every
Component whose ``cost_item_id`` matches the updated item, refreshes
the component's ``unit_cost`` + ``total`` from the new rate, and then
re-runs the assembly total math on each parent assembly so the
denormalised total stays in sync.

This is the "additive" cost-flow direction - assemblies stay
synchronised with the cost database without the BOQ positions
already created from them having to be hand-rebuilt.  Positions
created BEFORE the rate change are NOT touched (they're locked
financial commitments at create time); the next regenerate of the
position from the assembly picks up the new rate naturally.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.core.events import Event, event_bus
from app.database import async_session_factory
from app.modules.assemblies.models import Assembly, Component

logger = logging.getLogger(__name__)


def _safe_decimal(value: object, default: str = "0") -> Decimal:
    """Coerce a string / number to Decimal without raising."""
    try:
        return Decimal(str(value)) if value is not None else Decimal(default)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


async def _on_cost_item_updated(event: Event) -> None:
    """``costs.item.updated`` → refresh every Component that points at
    the updated CostItem and re-run the parent Assembly total.

    Pulls the new ``rate`` straight out of the event payload (the
    costs module emits the field-level diff with the new value).
    Falls back to a fresh DB lookup if the payload is missing the
    rate - older publishers may not include it.
    """
    data = event.data or {}
    # The costs module publishes ``costs.item.updated`` with the key
    # ``item_id`` (see ``costs/service.update_cost_item``). The previous
    # reads (``cost_item_id`` / ``id``) never matched, so every
    # cost-price edit was silently dropped here and assemblies kept a
    # stale unit_cost / total_rate forever (ASM-007 wiring bug a).
    # ``cost_item_id`` / ``id`` kept as fallbacks for any other / future
    # publisher shape.
    raw_id = data.get("item_id") or data.get("cost_item_id") or data.get("id")
    if not raw_id:
        return

    try:
        item_id = uuid.UUID(str(raw_id))
    except (ValueError, AttributeError):
        return

    new_rate_raw = data.get("rate") or data.get("new_rate")
    new_rate = _safe_decimal(new_rate_raw)

    try:
        async with async_session_factory() as session:
            # Step 1: find every Component referencing this cost item
            comp_stmt = select(Component).where(Component.cost_item_id == item_id)
            components = list((await session.execute(comp_stmt)).scalars().all())
            if not components:
                return

            # Step 2: if we did not get the new rate from the event,
            # look it up in the costs table once
            if new_rate == Decimal("0") and not new_rate_raw:
                try:
                    from app.modules.costs.models import CostItem

                    item = await session.get(CostItem, item_id)
                    if item is not None:
                        new_rate = _safe_decimal(getattr(item, "rate", "0"))
                except Exception:
                    logger.debug(
                        "assemblies cost-update: rate lookup failed for %s",
                        item_id,
                        exc_info=True,
                    )

            # Step 3: refresh each Component and remember its parent
            affected_assembly_ids: set[uuid.UUID] = set()
            for comp in components:
                comp.unit_cost = str(new_rate)
                # Recompute the per-component total: factor × quantity × unit_cost
                factor = _safe_decimal(comp.factor, "1.0")
                qty = _safe_decimal(comp.quantity, "1.0")
                comp.total = str(factor * qty * new_rate)
                affected_assembly_ids.add(comp.assembly_id)
            await session.flush()

            # Step 4: re-run the assembly total math for every
            # affected assembly.  We cannot call AssembliesService
            # without an HTTP request context, so we inline it here:
            # sum the component totals × bid_factor.  This must
            # match the logic in service._recalculate_total.
            if affected_assembly_ids:
                asm_stmt = select(Assembly).where(Assembly.id.in_(affected_assembly_ids))
                assemblies = list((await session.execute(asm_stmt)).scalars().all())
                # Refetch ALL components per assembly so the recompute
                # sees the full picture, not only the ones touched by
                # this specific cost item.
                for assembly in assemblies:
                    full_stmt = select(Component).where(Component.assembly_id == assembly.id)
                    full_components = list((await session.execute(full_stmt)).scalars().all())
                    component_sum = sum(
                        (_safe_decimal(c.total) for c in full_components),
                        Decimal("0"),
                    )
                    bid_factor = _safe_decimal(assembly.bid_factor, "1.0")
                    assembly.total_rate = str(component_sum * bid_factor)
                await session.flush()

            await session.commit()

            logger.info(
                "Assemblies cost-update: refreshed %d component(s) "
                "across %d assembly(s) after CostItem %s changed to %s",
                len(components),
                len(affected_assembly_ids),
                item_id,
                new_rate,
            )
    except Exception:
        logger.warning(
            "Assemblies cost-update subscriber failed for cost item %s",
            raw_id,
            exc_info=True,
        )


async def _recalc_assemblies(session, assembly_ids: set[uuid.UUID]) -> None:
    """Re-run ``total_rate = sum(component totals) * bid_factor``.

    Shared by the cost-item and catalog-resource refresh paths so the
    denormalised total stays in lock-step with ``service._recalculate_total``.
    """
    if not assembly_ids:
        return
    asm_stmt = select(Assembly).where(Assembly.id.in_(assembly_ids))
    assemblies = list((await session.execute(asm_stmt)).scalars().all())
    for assembly in assemblies:
        full_stmt = select(Component).where(Component.assembly_id == assembly.id)
        full_components = list((await session.execute(full_stmt)).scalars().all())
        component_sum = sum((_safe_decimal(c.total) for c in full_components), Decimal("0"))
        bid_factor = _safe_decimal(assembly.bid_factor, "1.0")
        assembly.total_rate = str(component_sum * bid_factor)
    await session.flush()


def _rate_or_none(raw: object) -> Decimal | None:
    """The rate as a number, or ``None`` when it cannot be read as one.

    Deliberately not ``_safe_decimal``, which answers 0 for anything it cannot
    parse. That is the right answer for a missing optional factor and the wrong
    one for a price: an item whose rate arrives as ``""`` or ``"12,50"`` would
    silently rewrite every component built on it to zero and collapse the parent
    assembly's total. A price we cannot read is a row to leave alone and count,
    not a row to zero.
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


async def refresh_region(session, region: str) -> tuple[int, int, int]:
    """Re-read every component priced from ``region`` and re-total its parents.

    Returns ``(components refreshed, assemblies re-totalled, rates unreadable)``.

    Takes the session rather than opening one so it can be exercised directly.
    The subscriber below is the production caller and does open one; a test lane
    that never binds ``async_session_factory`` can still reach this.

    Idempotent by construction: it writes the rate that is in the table, so a
    replayed or duplicated event lands on the same values.
    """
    from app.modules.costs.models import CostItem

    stmt = (
        select(Component, CostItem.rate)
        .join(CostItem, Component.cost_item_id == CostItem.id)
        .where(CostItem.region == region)
    )
    rows = list((await session.execute(stmt)).all())
    if not rows:
        return (0, 0, 0)

    affected_assembly_ids: set[uuid.UUID] = set()
    refreshed = 0
    unreadable = 0
    for comp, raw_rate in rows:
        new_rate = _rate_or_none(raw_rate)
        if new_rate is None:
            unreadable += 1
            continue
        factor = _safe_decimal(comp.factor, "1.0")
        qty = _safe_decimal(comp.quantity, "1.0")
        comp.unit_cost = str(new_rate)
        comp.total = str(factor * qty * new_rate)
        affected_assembly_ids.add(comp.assembly_id)
        refreshed += 1

    if not refreshed:
        return (0, 0, unreadable)
    await session.flush()
    await _recalc_assemblies(session, affected_assembly_ids)
    return (refreshed, len(affected_assembly_ids), unreadable)


async def _on_region_repriced(event: Event) -> None:
    """Pull a whole repriced region through into every assembly built on it.

    ``reprice_region`` rewrites the rate of every work item in a region from the
    resource price sheet. Before this subscriber existed it announced nothing,
    so the rates moved and the assemblies that quote them kept their own copy -
    the case a user hits when they reprice and their budget does not move.

    One event carries the region rather than the item ids. A single run may
    rewrite up to 250 000 items and a per-item event would mean that many
    detached tasks each opening a session. Joining Component to CostItem on the
    region instead makes the work proportional to how many components exist,
    which is the small number here, and it is the same work whether one price
    moved or a hundred thousand did.
    """
    data = event.data or {}
    region = str(data.get("region") or "").strip()
    if not region:
        return
    try:
        async with async_session_factory() as session:
            refreshed, assemblies, unreadable = await refresh_region(session, region)
            if not refreshed:
                return
            await session.commit()
            logger.info(
                "Assemblies region-reprice: refreshed %d component(s) across %d assembly(s) "
                "after region %s was repriced%s",
                refreshed,
                assemblies,
                region,
                f" ({unreadable} rate(s) unreadable, left alone)" if unreadable else "",
            )
    except Exception:
        logger.warning(
            "Assemblies region-reprice subscriber failed for region %s",
            region,
            exc_info=True,
        )


def _parse_uuids(values: object) -> list[uuid.UUID]:
    """Best-effort parse of an iterable of id strings into UUIDs."""
    out: list[uuid.UUID] = []
    if not isinstance(values, (list, tuple, set)):
        return out
    for v in values:
        try:
            out.append(uuid.UUID(str(v)))
        except (ValueError, AttributeError, TypeError):
            continue
    return out


async def _on_catalog_resource_updated(event: Event) -> None:
    """``catalog.resources.updated`` (bulk adjust-prices) → refresh every
    Component linked via ``catalog_resource_id``.

    Mirrors the cost-item flow (ASM-007): a Component built from a
    catalog resource carried a frozen ``unit_cost`` snapshot and never
    picked up a later catalog price edit or bulk ``adjust-prices`` run.

    Three payload shapes are handled (CAT-002):

    * **bulk adjust** - ``catalog.resources.updated`` carries
      ``{count, resource_ids, factor, filters}``. The catalog router
      has already written the new ``base_price`` to every matched row
      *before* publishing, so we re-price exactly the Components whose
      ``catalog_resource_id`` is in ``resource_ids`` from the current
      authoritative ``CatalogResource.base_price``.
    * **single resource** - payload has ``resource_id`` (+ optionally
      the new ``base_price``); only matching Components are refreshed.
    * **legacy / unknown bulk** - neither id list nor single id: every
      Component that points at *any* catalog resource is re-priced from
      the current ``CatalogResource.base_price`` (the only correct
      source of truth after a filtered bulk multiply).
    """
    data = event.data or {}
    raw_id = data.get("resource_id") or data.get("catalog_resource_id")
    # ``catalog.resources.updated`` (the name the catalog router
    # actually emits) ships the affected ids under ``resource_ids``.
    scoped_ids = _parse_uuids(data.get("resource_ids"))

    try:
        async with async_session_factory() as session:
            from app.modules.catalog.models import CatalogResource

            if raw_id:
                try:
                    res_id = uuid.UUID(str(raw_id))
                except (ValueError, AttributeError):
                    return
                comp_stmt = select(Component).where(Component.catalog_resource_id == res_id)
            elif scoped_ids:
                # Bulk adjust-prices - only the resources that were
                # actually re-priced. Keeps the blast radius tight
                # instead of re-walking every catalog-linked component.
                comp_stmt = select(Component).where(Component.catalog_resource_id.in_(scoped_ids))
            else:
                # Bulk price adjust - every catalog-linked component.
                comp_stmt = select(Component).where(Component.catalog_resource_id.isnot(None))

            components = list((await session.execute(comp_stmt)).scalars().all())
            if not components:
                return

            # Resolve the authoritative price per resource id (one
            # lookup per distinct resource - the bulk path may span
            # many). Prefer the event-supplied price for the single
            # case to avoid a redundant read.
            price_cache: dict[uuid.UUID, Decimal] = {}
            event_price = data.get("base_price") or data.get("new_price")
            affected_assembly_ids: set[uuid.UUID] = set()

            for comp in components:
                cr_id = comp.catalog_resource_id
                if cr_id is None:
                    continue
                if cr_id not in price_cache:
                    if raw_id and event_price is not None and str(cr_id) == str(raw_id):
                        price_cache[cr_id] = _safe_decimal(event_price)
                    else:
                        resource = await session.get(CatalogResource, cr_id)
                        price_cache[cr_id] = _safe_decimal(
                            getattr(resource, "base_price", "0") if resource is not None else "0"
                        )
                new_price = price_cache[cr_id]
                comp.unit_cost = str(new_price)
                factor = _safe_decimal(comp.factor, "1.0")
                qty = _safe_decimal(comp.quantity, "1.0")
                comp.total = str(factor * qty * new_price)
                affected_assembly_ids.add(comp.assembly_id)

            await session.flush()
            await _recalc_assemblies(session, affected_assembly_ids)
            await session.commit()

            logger.info(
                "Assemblies catalog-update: refreshed %d component(s) "
                "across %d assembly(s) after catalog resource %s changed",
                len(components),
                len(affected_assembly_ids),
                raw_id or (f"(bulk: {len(scoped_ids)} ids)" if scoped_ids else "(bulk)"),
            )
    except Exception:
        logger.warning(
            "Assemblies catalog-update subscriber failed for resource %s",
            raw_id,
            exc_info=True,
        )


def register_assemblies_subscribers() -> None:
    """Wire the cost / catalog refresh subscribers to the global event bus."""
    event_bus.subscribe_once("costs.item.updated", _on_cost_item_updated)
    # ASM-007 / CAT-002: keep catalog-resource-linked components fresh.
    # ``catalog.resources.updated`` (PLURAL) is the name the catalog
    # router emits from its bulk ``adjust-prices`` endpoint, the only way a
    # catalog price changes. The catalog has no single-resource edit, so
    # nothing publishes a singular name; a single-edit endpoint added later
    # publishes this same name with one id in ``resource_ids``.
    event_bus.subscribe_once("catalog.resources.updated", _on_catalog_resource_updated)
    # The third writer of CostItem.rate. costs.item.updated covers the single
    # PATCH and catalog.resources.updated covers the catalog's bulk adjust, but
    # reprice_region - the one that rewrites a whole region from the resource
    # price sheet, and the one a user reaches for when prices move - announced
    # nothing at all until now.
    event_bus.subscribe_once("costs.region.repriced", _on_region_repriced)
    logger.info("Assemblies: subscribed to costs.item.updated + costs.region.repriced + catalog.resources.updated")
