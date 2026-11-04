# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Management of Change (MoC) module."""


async def on_startup() -> None:
    """Module startup hook - register permissions + event subscribers."""
    from app.modules.moc.events import register_subscribers
    from app.modules.moc.permissions import register_moc_permissions

    register_moc_permissions()
    register_subscribers()
    from app.modules.moc.validators import register_moc_validation_rules

    register_moc_validation_rules()
