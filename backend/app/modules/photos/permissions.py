# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Photos module permission definitions."""

from app.core.permissions import Role, permission_registry

PHOTOS_PERMISSIONS: dict[str, Role] = {
    "photos.read": Role.VIEWER,
    "photos.upload": Role.EDITOR,
    "photos.edit": Role.EDITOR,
    "photos.delete": Role.MANAGER,
    "photos.ai.run": Role.EDITOR,
    "photos.ai.review": Role.EDITOR,
    "photos.export": Role.VIEWER,
    "photos.admin.backfill": Role.ADMIN,
}


def register_photos_permissions() -> None:
    """Register the photos permissions.

    Upload is editor level because the site roles carry no permissions of their
    own yet; deleting is manager level and only ever removes a gallery photo,
    an indexed diary or punch photo is archived instead.
    """
    permission_registry.register_module_permissions("photos", PHOTOS_PERMISSIONS)
