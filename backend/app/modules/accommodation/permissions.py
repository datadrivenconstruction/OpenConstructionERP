"""Accommodation module permission definitions.

Coarse RBAC tier - fine-grained gates can be split out later if a
customer needs to separate "front-desk operator" from "HR housing
coordinator". For the MVP we keep one read tier (VIEWER) and one write
tier (EDITOR) with MANAGER gating destructive actions (delete) and
state-machine escalations.
"""

from app.core.permissions import Role, permission_registry

ACCOMMODATION_PERMISSIONS: dict[str, Role] = {
    # Accommodation parent CRUD
    "accommodation.read": Role.VIEWER,
    "accommodation.create": Role.EDITOR,
    "accommodation.update": Role.EDITOR,
    "accommodation.delete": Role.MANAGER,
    # Rooms
    "accommodation.room.create": Role.EDITOR,
    "accommodation.room.update": Role.EDITOR,
    # Bookings
    "accommodation.booking.create": Role.EDITOR,
    "accommodation.booking.update": Role.EDITOR,
    "accommodation.booking.cancel": Role.MANAGER,
    # Charges
    "accommodation.charge.create": Role.EDITOR,
    "accommodation.charge.update": Role.EDITOR,
    # Deleting a billed line-item is a financial correction - gate it at
    # MANAGER like the other destructive actions (accommodation.delete).
    "accommodation.charge.delete": Role.MANAGER,
    # Cross-module integrations
    "accommodation.bootstrap_from_propdev": Role.EDITOR,
    # Suggest-from-HR is EDITOR (not VIEWER): its only purpose is to drive
    # a follow-up booking, which requires ``accommodation.booking.create``
    # (EDITOR). Gating the suggestion at VIEWER created a dead-end flow
    # where a viewer could request a suggestion then hit 403 on Confirm.
    "accommodation.suggest_from_hr": Role.EDITOR,
}


def register_accommodation_permissions() -> None:
    """Register permissions for the accommodation module."""
    permission_registry.register_module_permissions(
        "accommodation",
        ACCOMMODATION_PERMISSIONS,
    )
