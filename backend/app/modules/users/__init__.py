# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Users & Authentication module.

Provides user registration, JWT auth, API keys, and RBAC.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.users.permissions import register_user_permissions

    register_user_permissions()

    from app.config import get_settings
    from app.modules.users.sso_enforce import warn_if_misconfigured

    warn_if_misconfigured(get_settings())
