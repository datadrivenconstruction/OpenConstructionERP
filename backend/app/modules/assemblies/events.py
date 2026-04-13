"""Assemblies event subscribers​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ — keep total_rate fresh.

Without this subscriber, ``Assembly.total_rate`` was a denormalised
string snapshot computed once at component create/update/delete time.
When a ``CostItem.rate`` changed externally via the costs module,
every Assembly that referenced it carried a stale unit_cost on its
Components and a stale total_rate on the parent — and any BOQ
position created from the assembly inherited the stale value
forever.

The subscriber listens for ``costs.item.updated``, finds every
Component whose ``cost_item_id`` matches the updated item, refreshes
the component's ``unit_cost`` + ``total`` from the new rate, and then
re-runs the assembly total math on each parent assembly so the
denormalised total stays in sync.

This is the "additive" cost-flow direction — assemblies stay
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
    rate — older publishers may not include it.
    """
    data = event.data or {}
    raw_id = data.get("cost_item_id") or data.get("id")
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
                asm_stmt = select(Assembly).where(
                    Assembly.id.in_(affected_assembly_ids)
                )
                assemblies = list(
                    (await session.execute(asm_stmt)).scalars().all()
                )
                # Refetch ALL components per assembly so the recompute
                # sees the full picture, not only the ones touched by
                # this specific cost item.
                for assembly in assemblies:
                    full_stmt = select(Component).where(
                        Component.assembly_id == assembly.id
                    )
                    full_components = list(
                        (await session.execute(full_stmt)).scalars().all()
                    )
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


def register_assemblies_subscribers() -> None:
    """Wire the cost-update subscriber to the global event bus."""
    event_bus.subscribe("costs.item.updated", _on_cost_item_updated)
    logger.info("Assemblies: subscribed to costs.item.updated")
