# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the compliance_ai module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (dSL-based compliance rule engine plus a natural-language rule builder powered by Claude. Rules compile into core ValidationRule subclasses so evaluation uses the single validation pipeline); reads code of ai, compliance, dashboards",
)
