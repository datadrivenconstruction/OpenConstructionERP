# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Photos module manifest."""

from app.core.module_loader import ModuleManifest

manifest = ModuleManifest(
    name="oe_photos",
    version="1.0.0",
    display_name="Photos",
    description=(
        "One photo archive for the whole project. Gallery, diary, punch list, field report and progress photos "
        "are indexed in place, never copied. Grid, timeline, map, albums and before/after comparison; links to "
        "BOQ positions, schedule activities, punch items, inspections and safety observations; drawing pins; "
        "AI captions, tags, progress and hazard proposals that a person accepts or rejects; zip export with a "
        "JSON record per photo."
    ),
    author="OpenConstructionERP Core Team",
    category="field",
    depends=["oe_projects", "oe_documents", "oe_file_tags"],
    optional_depends=["oe_plan_room", "oe_geo_hub", "oe_ai"],
    auto_install=True,
    enabled=True,
)
