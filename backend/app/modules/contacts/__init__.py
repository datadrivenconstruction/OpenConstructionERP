"""Contacts module.

Unified contacts directory for clients, subcontractors, suppliers,
consultants, and internal contacts.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.contacts.permissions import register_contacts_permissions

    register_contacts_permissions()
