# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Drawing revision compare module.

Compares an older and a newer revision of a drawing and stores the result as a
list of changed regions linked to both revisions. PDF sheets are rasterised
and diffed in the browser (pdf.js), so the server stays free of rendering
dependencies and only validates and stores the regions; DWG/DXF revisions are
diffed here, entity by entity, from the records the CAD converter already
keeps. Each change can be triaged, turned into an RFI or a markup, and used to
flag the takeoff measurements and BOQ positions inside it for re-measure.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and the validation rule set."""
    from app.modules.drawing_compare.permissions import register_drawing_compare_permissions
    from app.modules.drawing_compare.validators import register_drawing_compare_rules

    register_drawing_compare_permissions()
    register_drawing_compare_rules()
