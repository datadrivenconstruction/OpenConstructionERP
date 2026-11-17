# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Survey register module (first of the survey family).

Project CRS, point sets imported from instrument files, and the SRV rules that
keep them trustworthy before volumes, stockpiles or parcels use them.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and validation rules."""
    from app.modules.survey_core.permissions import register_survey_permissions
    from app.modules.survey_core.validators import register_survey_validation_rules

    register_survey_permissions()
    register_survey_validation_rules()
