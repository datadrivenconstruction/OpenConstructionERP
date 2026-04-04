"""Markups & Annotations module.

Provides drawing markups, scale calibration, and stamp templates
for document annotation workflows in construction projects.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions and seed default stamps."""
    from app.modules.markups.permissions import register_markups_permissions

    register_markups_permissions()
