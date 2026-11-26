# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site sensors​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ module manifest."""

from app.core.module_loader import ModuleManifest
from app.modules.site_sensors.data_paths import DATA_PATHS

manifest = ModuleManifest(
    name="oe_site_sensors",
    version="0.1.0",
    display_name="Site sensors",
    description=(
        "Concrete maturity and strength, noise, dust, vibration, weather and water level on site: devices, "
        "a compact time series, limits from country data, alerts with acknowledgement, formwork strikes"
    ),
    author="OpenConstructionERP Core Team",
    category="business",
    depends=["oe_users", "oe_projects", "oe_notifications"],
    auto_install=True,
    enabled=True,
    data_paths=DATA_PATHS,
)
