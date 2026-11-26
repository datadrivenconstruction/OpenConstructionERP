# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the estimate_rollup module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (composes a project's full estimate headline number from the estimating modules that are tracked separately today: the BOQ base (measured works plus markups), the preliminaries register and the allowances / contingency register. Read-only - it reuses each module's own rollup and adds preliminaries and remaining allowances on top of the BOQ base without double-counting, with a line-item breakdown a UI can render as 'BOQ base + Preliminaries + Contingency = Estimate total'); reads code of allowances, boq, preliminaries",
)
