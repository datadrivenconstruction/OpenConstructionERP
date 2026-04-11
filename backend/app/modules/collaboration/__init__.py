"""Collaboration module — threaded comments + viewpoints for any entity."""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.collaboration.permissions import register_collaboration_permissions

    register_collaboration_permissions()
