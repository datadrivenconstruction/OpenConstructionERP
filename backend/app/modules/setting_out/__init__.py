# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Setting-out and as-built module (survey family).

Stakeout requests from design (CSV, LandXML points or alignment with
chainage/offset), measured stakes with an instant tolerance verdict, NCR drafts
for failed stakes, and the printable setting-out sheet.
"""


async def on_startup() -> None:
    """Module startup hook - register validation rules (permissions come from survey_core)."""
    from app.modules.setting_out.validators import register_setting_out_validation_rules

    register_setting_out_validation_rules()
