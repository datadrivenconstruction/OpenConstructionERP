# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Field Diary module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.field_diary.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_field_diary",
    version="0.1.0",
    display_name="Field Diary",
    description=(
        "Field-worker MVP daily diary with PIN-gated magic-link auth and "
        "a dedicated per-project module-grant permission table."
    ),
    author="OpenConstructionERP Core Team",
    category="core",
    depends=["oe_projects", "oe_users"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
