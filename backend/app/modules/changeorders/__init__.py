"""Change Orders module.

Tracks scope changes during project execution with cost/schedule impact
and approval workflows (draft -> submitted -> approved/rejected).
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.changeorders.permissions import register_changeorder_permissions

    register_changeorder_permissions()
