# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

"""Phonelog module - capture of phone-call and voice-note verbal instructions as dispute-ready records."""


async def on_startup() -> None:
    """Module startup hook - register the phone-log validation rules."""
    from app.modules.phonelog.validators import register_phonelog_validation_rules

    register_phonelog_validation_rules()
