# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""List Views module.

Named table layouts for any list page: filters, visible columns, column
order and widths, and sort, saved under a page key. A view is personal or
shared with the rest of the workspace (tenant). The state is opaque to the
server beyond its validated shape; the frontend list layer applies it.
"""


async def on_startup() -> None:
    """Module startup hook - permissions and validation rules."""
    from app.modules.list_views.permissions import register_list_views_permissions
    from app.modules.list_views.validators import register_list_views_rules

    register_list_views_permissions()
    register_list_views_rules()
