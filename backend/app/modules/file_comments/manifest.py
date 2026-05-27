# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File Comments module manifest.

Polymorphic threaded comments on any file kind (document / photo / sheet /
bim_model / dwg_drawing / takeoff / report / markup). Comments may be
anchored to a PDF page + normalized (x, y) coordinate so they can render
as pins on the document.
"""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_file_comments",
    version="1.0.0",
    display_name="File Comments",
    description=(
        "Threaded comments + PDF markup pins across all file kinds, with @mention extraction and resolve workflow."
    ),
    author="OpenEstimate Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
)
