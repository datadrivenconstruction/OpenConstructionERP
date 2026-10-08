# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Legal Entities module - the companies of a group and their branches.

Each entity carries the country it is registered in and the currency its books
are kept in; each branch belongs to one entity and may sit in another country.
Numbering, tax and stock ownership per entity build on this.
"""


async def on_startup() -> None:
    """Register permissions."""
    from app.modules.legal_entities.permissions import register_legal_entities_permissions

    register_legal_entities_permissions()
