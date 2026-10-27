# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Quote​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ capture module: AI-assisted extraction and levelling of supplier quotes.

The machine reads, a person confirms: every extracted value carries a confidence
and a source anchor, and nothing is written into a bid, price list or purchase
order until a reviewer confirms the quote and the validation rules pass.
"""

from app.modules.quote_capture.manifest import manifest

__all__ = ["manifest", "on_startup"]


async def on_startup() -> None:
    """Register permissions and validation rules."""
    from app.modules.quote_capture.permissions import register_quote_capture_permissions
    from app.modules.quote_capture.validators import register_quote_capture_rules

    register_quote_capture_permissions()
    register_quote_capture_rules()
