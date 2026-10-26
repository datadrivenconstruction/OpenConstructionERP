# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cutting optimisation module.

Replaces a flat waste percentage with a measured one wherever the cut list is
known. A cutting job holds the demanded pieces and the stock on offer (purchasable
lengths or sheets with cost and availability, plus offcuts from site inventory);
the optimiser turns it into a plan: per stock piece, the cuts taken from it, with
yield, waste, offcuts and cost.

The optimisers (:mod:`app.modules.cutting.linear`, :mod:`app.modules.cutting.sheet`)
and the rules (:mod:`app.modules.cutting.validators`) are pure Python with no
import-time database or registry work. Permission and rule registration are
deferred to :func:`on_startup`, which the module loader calls.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and the ``cutting`` rule set."""
    from app.modules.cutting.permissions import register_cutting_permissions
    from app.modules.cutting.validators import register_rules

    register_cutting_permissions()
    register_rules()
