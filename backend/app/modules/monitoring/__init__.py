# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Deformation monitoring module (survey family).

Monitoring points (prism, settlement pin, convergence chord, inclinometer as
values only), epochs of imported readings, displacement against the baseline,
rate per day and alert / action / alarm levels from a threshold profile.
Readings are imported from CSV; this module never controls an instrument.
"""


async def on_startup() -> None:
    """Module startup hook - register validation rules (permissions come from survey_core)."""
    from app.modules.monitoring.validators import register_monitoring_validation_rules

    register_monitoring_validation_rules()
