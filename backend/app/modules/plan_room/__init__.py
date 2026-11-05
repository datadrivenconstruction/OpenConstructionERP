# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plan Room module.

A read-only overlay compositor for a document page: it merges the page's
punch-list defect pins, drawing markups, takeoff measurements and site photos
into a single payload for the viewer, and owns a small table of positioned
photo / note pins dropped directly on the sheet.

Every external overlay source (punchlist, markups, takeoff, photos) is read at
request time behind a fail-soft lazy import, so an absent or disabled module
simply contributes an empty list rather than breaking the read.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions."""
    from app.modules.plan_room.permissions import register_plan_room_permissions

    register_plan_room_permissions()

    from app.modules.plan_room.validators import register_plan_room_validation_rules

    register_plan_room_validation_rules()
