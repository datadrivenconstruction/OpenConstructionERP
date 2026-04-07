"""Correspondence module.

Project correspondence tracking — letters, emails, and notices with
direction tracking, contact linking, and document cross-references.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.correspondence.permissions import register_correspondence_permissions

    register_correspondence_permissions()
