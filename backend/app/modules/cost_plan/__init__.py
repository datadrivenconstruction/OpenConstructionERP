# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Elemental cost plan module.

Reads a bill of quantities and lays it out as an NRM 1 elemental cost plan:
group elements 0-8 with their elements, the building works estimate, bill
items coded to groups 9-14, everything not allocated to an element, and the
bill's own markup cascade below, with cost per m2 of GIFA and share of total
on every line. It is a view. It owns no tables and writes nothing, and it
never prices a markup itself: the amounts come from the bill's one markup
engine in ``app.modules.boq.service``.

The rollup lives in the dependency-light :mod:`app.modules.cost_plan.engine`,
the element table in ``data/nrm1_elements.json``. The module loader mounts the
``router`` at ``/api/v1/cost-plan`` and calls :func:`on_startup` at boot.
"""

__all__ = ["on_startup"]


async def on_startup() -> None:
    """Module startup hook - register the module's permissions."""
    from app.modules.cost_plan.permissions import register_cost_plan_permissions

    register_cost_plan_permissions()
