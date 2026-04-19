"""Schedule module permission definitions."""

from app.core.permissions import Role, permission_registry


def register_schedule_permissions() -> None:
    """Register permissions for the Schedule module.

    ``schedule.baselines.delete`` is scoped to ADMIN because baselines are
    snapshot-in-time records used for EVM and contractual forensics — an
    estimator removing one destroys planned-vs-actual comparisons that
    may be referenced months later in arbitration. Regular schedule rows
    (activities, links) remain EDITOR-deletable under ``schedule.delete``.
    """
    permission_registry.register_module_permissions(
        "schedule",
        {
            "schedule.create": Role.EDITOR,
            "schedule.read": Role.VIEWER,
            "schedule.update": Role.EDITOR,
            "schedule.delete": Role.EDITOR,
            "schedule.baselines.delete": Role.ADMIN,
            "schedule.work_orders.manage": Role.EDITOR,
        },
    )
