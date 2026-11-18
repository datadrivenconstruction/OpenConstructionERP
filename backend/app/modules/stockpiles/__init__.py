# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Stockpile survey (third module of the survey family).

A stockpile has a base surface and a book stock; each survey measures the pile
above that base (or takes a typed field-software volume), turns volume into
tonnes with a stated density, and compares it with the book. A variance becomes
an adjustment proposal; a person confirms before the inventory is touched.
"""


async def on_startup() -> None:
    """Module startup hook - register the STK validation rules."""
    from app.modules.stockpiles.validators import register_stockpile_validation_rules

    register_stockpile_validation_rules()
