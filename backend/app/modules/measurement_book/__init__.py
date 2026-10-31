# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Measurement book: dated, checked site measurements per BOQ position.

Neutral record of what was measured on site, where, by whom and who
check-measured it. The cumulative checked quantity per position is the
running bill, and it feeds interim payments through the progress module:
posting the bill records a progress observation per position, which a
progress claim then picks up with its existing populate-from-progress flow.
"""


async def on_startup() -> None:
    """Module startup hook - register permissions and validation rules."""
    from app.modules.measurement_book.permissions import register_measurement_book_permissions
    from app.modules.measurement_book.validators import register_measurement_book_rules

    register_measurement_book_permissions()
    register_measurement_book_rules()
