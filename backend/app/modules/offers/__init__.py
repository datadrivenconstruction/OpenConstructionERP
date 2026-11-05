"""Customer offer module: an estimate turned into the offer the customer receives."""

from app.modules.offers.manifest import manifest

__all__ = ["manifest", "on_startup"]


async def on_startup() -> None:
    """Register the offer validation rules."""
    from app.modules.offers.validators import register_offer_rules

    register_offer_rules()
