# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Work Requests permissions.

Every authenticated user can READ the boards and RAISE a request - a PM
who needs a switchboard built must never be locked out of asking for it.
UPDATE (moving stages, logging hours, assigning) is editor-level; the
finer rail - that only the requester, the department or a manager may
change a given request - is enforced in the service, not here. MANAGE
(editing departments, their stages and request types, and the planner
capacity line) is manager-level.

The registry fails CLOSED on an unknown permission name, so this file
must be imported (and the call below run) before any of the module's
routes are hit - ``router.py`` calls it explicitly for that reason.
"""

from app.core.permissions import Role, permission_registry


def register_work_requests_permissions() -> None:
    permission_registry.register_module_permissions(
        "work_requests",
        {
            "work_requests.read": Role.VIEWER,
            "work_requests.create": Role.VIEWER,
            "work_requests.update": Role.EDITOR,
            "work_requests.manage": Role.MANAGER,
        },
    )


register_work_requests_permissions()
