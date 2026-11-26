# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the accommodation module (see app.core.data_paths)."""

from app.core.data_paths import DataPath, DataPaths, Entity

DATA_PATHS = DataPaths(
    why="data_paths.why.accommodation",
    entities=(
        Entity("Accommodation", label="data_paths.entity.accommodation"),
        Entity("Booking", label="data_paths.entity.booking"),
        Entity("Charge", label="data_paths.entity.charge"),
        Entity("Room", label="data_paths.entity.room"),
    ),
    inputs=(DataPath("oe_contacts", "Booking", via="Booking.occupant_contact_id", label="data_paths.entity.contact"),),
)
