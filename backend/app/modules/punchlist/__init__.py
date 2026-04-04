"""Punch List module.

Tracks construction deficiencies and quality issues with location pinning,
photo attachments, status transitions, and verification workflows.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.punchlist.permissions import register_punchlist_permissions

    register_punchlist_permissions()
