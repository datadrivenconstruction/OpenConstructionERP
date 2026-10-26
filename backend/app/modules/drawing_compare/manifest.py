# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Drawing revision compare module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_drawing_compare",
    version="1.0.0",
    display_name="Drawing Revision Compare",
    description=(
        "Compare two revisions of a drawing (PDF sheets or DWG/DXF), list every changed region, "
        "triage it, raise an RFI or markup and flag takeoff and BOQ quantities for re-measure"
    ),
    author="OpenConstructionERP",
    category="extension",
    depends=["oe_projects", "oe_users"],
    # Every revision source and follow-up target is read fail-soft.
    optional_depends=["oe_takeoff", "oe_dwg_takeoff", "oe_documents", "oe_markups", "oe_rfi", "oe_boq"],
    auto_install=True,
    enabled=True,
)
