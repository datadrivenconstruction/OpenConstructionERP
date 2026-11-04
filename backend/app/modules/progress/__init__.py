# OpenConstructionERP - DataDrivenConstruction (DDC)
# DDC-CWICR-OE-2026
"""Progress tracking module - site-execution measurement."""


async def on_startup() -> None:
    """Module startup hook - register RBAC permissions."""
    from app.modules.progress.permissions import register_progress_permissions

    register_progress_permissions()
    from app.modules.progress.validators import register_progress_validation_rules

    register_progress_validation_rules()
