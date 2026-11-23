# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BIM-LV container module (DIN SPEC 91350).

Reads and writes the BIM-LV container that bundles a GAEB LV, a reference to
the IFC/BIM model and the position-to-element link table, and materializes the
container's links onto existing BOQ positions and BIM elements.
"""

__all__ = ["on_startup"]


async def on_startup() -> None:
    """Module startup hook - register the module's validation rules."""
    from app.modules.bimlv.validators import register_bimlv_validation_rules

    register_bimlv_validation_rules()
