"""Validation module.

Runs configurable validation rule sets against BOQs, documents, and CAD
imports, and persists the resulting reports for historical review.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.validation.permissions import register_validation_permissions

    register_validation_permissions()
