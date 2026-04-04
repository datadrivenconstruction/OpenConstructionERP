"""Requirements & Quality Gates module.

Extract, validate, and track construction requirements using EAC
(Entity-Attribute-Constraint) triplets with a Gate-based quality pipeline.
"""


async def on_startup() -> None:
    """Module startup hook — register permissions."""
    from app.modules.requirements.permissions import register_requirements_permissions

    register_requirements_permissions()
