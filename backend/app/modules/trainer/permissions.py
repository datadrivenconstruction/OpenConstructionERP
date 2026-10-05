# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Trainer module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_trainer_permissions() -> None:
    """Register the two trainer permissions.

    ``trainer.learn`` is open to every signed-in role, so a learner the store
    provisioned (a manager) has it. Ownership of an enrolment is checked per
    request on top of it. ``trainer.admin`` covers enrolment management, course
    reloads and the webhook log.
    """
    permission_registry.register_module_permissions(
        "trainer",
        {
            "trainer.learn": Role.VIEWER,
            "trainer.admin": Role.ADMIN,
        },
    )
