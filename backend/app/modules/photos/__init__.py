# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Photos module: one archive over every photo a project already holds.

The photo row stays the documents gallery's ``ProjectPhoto``; diary, punch list,
field report and progress photos get an index row pointing at their own file.
"""

from app.modules.photos.manifest import manifest

__all__ = ["manifest", "on_startup"]


async def on_startup() -> None:
    """Register permissions, validation rules, event subscribers and job handlers."""
    from app.modules.photos.events import register_photos_event_subscribers
    from app.modules.photos.jobs import register_photos_job_handlers
    from app.modules.photos.permissions import register_photos_permissions
    from app.modules.photos.validators import register_photos_rules

    register_photos_permissions()
    register_photos_rules()
    register_photos_event_subscribers()
    register_photos_job_handlers()
