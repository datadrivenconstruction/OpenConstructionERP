# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Statutory checks module.

Neutral engines for the questions construction law asks in markets that tax
sales rather than value added and that protect payment with lien and notice
clocks: when a notice falls due, how much retention may be held, and who owes
the tax on each line of a bid. The law itself is data the regional packs
contribute; this module ships no number and no table of its own.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and validation rules."""
    from app.modules.statutory.permissions import register_statutory_permissions
    from app.modules.statutory.validators import register_statutory_rules

    register_statutory_permissions()
    register_statutory_rules()
