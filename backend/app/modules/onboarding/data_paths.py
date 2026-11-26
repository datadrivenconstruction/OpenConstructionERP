# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Data paths of the onboarding module (see app.core.data_paths)."""

from app.core.data_paths import DataPaths

DATA_PATHS = DataPaths(
    reason="Owns no tables (non-blocking first-run provisioning. Runs the heavy first-run loads (regional cost base import, sample project install) as background jobs so the wizard never makes a new user wait, exposing a progress feed the UI polls and a banner that keeps working after the user has moved on); reads code of costs",
)
