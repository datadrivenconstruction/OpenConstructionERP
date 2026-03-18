"""Users & Authentication module.

Provides user registration, JWT auth, API keys, and RBAC.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.users.permissions import register_user_permissions

    register_user_permissions()
