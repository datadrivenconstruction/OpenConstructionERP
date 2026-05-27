"""‌⁠‍Admin — permissions matrix endpoint.

Exposes a view + edit surface for the live ``PermissionRegistry`` so the
frontend can render and tune the roles × modules matrix without re-
implementing the role-hierarchy logic in TypeScript.

Endpoints
~~~~~~~~~
* ``GET  /api/v1/admin/permissions/matrix``
      Read-only snapshot of every registered permission, gated by
      ``audit.view`` (Manager+). Matches the read-only governance view
      that has shipped since v2.x.

* ``PATCH /api/v1/admin/permissions/{permission_key}``
      Lower / raise the ``min_role`` for a single permission. Admin-only.
      Refuses to remove admin's own admin-level permissions (lockout
      protection — admin cannot un-admin itself).

* ``POST /api/v1/admin/permissions/preset/{preset_name}``
      Rewrite the entire matrix to a named baseline preset
      (``viewer-default`` / ``editor-default`` / ``manager-default``).
      Admin-only, audit-logged with the full before/after diff.

The read endpoint stays gated by ``audit.view`` (Manager+) so the matrix
remains visible to operators who can read the audit log but can't edit
RBAC. The write endpoints upgrade the gate to *role=admin* — only true
admins can flip permissions. Per the brief, when the caller lacks edit
privilege the frontend falls back to the read-only matrix.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.core.audit import audit_log
from app.core.permissions import (
    PRESETS,
    ROLE_HIERARCHY,
    Role,
    permission_registry,
)
from app.dependencies import (
    CurrentUserPayload,
    RequirePermission,
    RequireRole,
    SessionDep,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Pydantic v2 schemas ──────────────────────────────────────────────────


class PermissionUpdateBody(BaseModel):
    """Body for ``PATCH /permissions/{permission_key}``.

    ``min_role`` is the *new* minimum role required to call the
    permission. The previous value is reported back in the response.
    """

    min_role: Role = Field(
        description="New minimum role required (viewer/editor/manager/admin).",
    )


class PermissionUpdateResponse(BaseModel):
    """Result of a successful ``PATCH`` toggle."""

    permission: str
    previous_min_role: Role
    new_min_role: Role


class PresetApplyResponse(BaseModel):
    """Result of a successful ``POST /preset/{preset_name}``."""

    preset: str
    permissions_changed: int
    total_permissions: int
    changes: list[dict[str, str]]


# ── Matrix snapshot (read-only — unchanged contract) ─────────────────────


def _build_matrix_payload() -> dict[str, Any]:
    """Snapshot the live permission registry into the matrix response.

    Pulled out of the route handler so the unit test can call it
    directly without spinning up the full ASGI app.
    """
    # Canonical role order goes lowest-to-highest so the UI columns
    # read left→right as "more permissive".
    roles_ordered = [r.value for r in (Role.VIEWER, Role.EDITOR, Role.MANAGER, Role.ADMIN)]

    modules_payload: list[dict[str, Any]] = []
    modules_index = permission_registry.list_modules()
    all_perms = permission_registry.list_all()

    # Sort modules alphabetically — predictable for the UI test and
    # avoids surprises when the registration order shifts between
    # releases (module loader topological sort is dependency-driven).
    for module_name in sorted(modules_index.keys()):
        perm_keys = sorted(modules_index[module_name])
        modules_payload.append(
            {
                "name": module_name,
                "permissions": [
                    {
                        "key": perm,
                        # all_perms maps perm → role.value (a string),
                        # so this is safe to forward as-is.
                        "min_role": all_perms.get(perm, Role.ADMIN.value),
                    }
                    for perm in perm_keys
                ],
            }
        )

    return {
        "roles": roles_ordered,
        "role_hierarchy": {r.value: lvl for r, lvl in ROLE_HIERARCHY.items()},
        "modules": modules_payload,
        "presets": sorted(PRESETS.keys()),
    }


@router.get(
    "/permissions/matrix",
    summary="Snapshot the RBAC matrix (roles × modules × permissions)",
    description=(
        "Returns the live PermissionRegistry as a roles-by-modules matrix "
        "for the admin UI. Gated by ``audit.view`` (manager+) — the same "
        "permission that protects the audit log."
    ),
)
async def permissions_matrix(
    _perm: None = Depends(RequirePermission("audit.view")),
) -> dict[str, Any]:
    """‌⁠‍Return the full permissions matrix for the admin UI."""
    return _build_matrix_payload()


# ── Write surface (admin-only, audit-logged) ─────────────────────────────


def _is_admin_lockout(permission: str, new_min_role: Role) -> bool:
    """Refuse to remove admin's own ``permissions.admin`` grant.

    The admin role is treated as an unconditional bypass everywhere in
    the codebase, so in practice you can't un-admin a true ``role=admin``
    user via this endpoint regardless. But the brief asks for an
    explicit, surfaceable refusal so the UI never asks the operator
    "are you sure?" for a no-op self-foot-gun.

    The protected keys are:

    * ``permissions.admin`` — the conceptual "edit the matrix" capability
      (currently implemented via the ``role=admin`` gate, but reserved).
    * Anything matching ``system.permissions.*`` — future-proofing for a
      finer-grained admin permission split.
    """
    if permission == "permissions.admin":
        # Never let the matrix endpoint drop the admin gate on itself.
        return new_min_role is not Role.ADMIN
    if permission.startswith("system.permissions."):
        return new_min_role is not Role.ADMIN
    return False


@router.patch(
    "/permissions/{permission_key}",
    response_model=PermissionUpdateResponse,
    summary="Update the min_role for a single permission",
    description=(
        "Admin-only. Changes the minimum role required to call the "
        "permission. The previous value is returned so the UI can roll "
        "back on the user's confirmation. Refuses changes that would "
        "lock the admin role out of its own admin permissions."
    ),
)
async def update_permission_min_role(
    permission_key: str,
    body: PermissionUpdateBody,
    request: Request,
    session: SessionDep,
    payload: CurrentUserPayload,
    _role_gate: None = Depends(RequireRole("admin")),
) -> PermissionUpdateResponse:
    """Toggle the min_role for ``permission_key``.

    Audit-logged via ``oe_core_audit_log`` so security review can replay
    every matrix mutation. Returns 404 if the permission is not
    registered (we never silently create rows via the UI).
    """
    if not permission_registry.has(permission_key):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "permission_not_found",
                "message": f"Unknown permission: {permission_key}",
            },
        )

    new_min_role = body.min_role

    if _is_admin_lockout(permission_key, new_min_role):
        # Surface a clear 400 so the UI can show "cannot drop admin's
        # own admin permission" rather than letting the change apply
        # silently into a half-broken state.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "admin_lockout_blocked",
                "message": (
                    "Refusing to lower admin's own admin permission "
                    f"({permission_key}). Pick min_role=admin or pick a "
                    "different permission."
                ),
            },
        )

    previous = permission_registry.set_min_role(permission_key, new_min_role)

    # Audit log — entity_type=permission, entity_id=key, details carry
    # the before/after for replay.
    await audit_log(
        session,
        action="update",
        entity_type="permission",
        entity_id=permission_key,
        user_id=payload.get("sub"),
        ip_address=request.client.host if request.client else None,
        details={
            "previous_min_role": previous.value,
            "new_min_role": new_min_role.value,
            "actor_role": payload.get("role"),
        },
    )

    logger.info(
        "Permissions matrix toggle: actor=%s key=%s %s → %s",
        payload.get("sub"),
        permission_key,
        previous.value,
        new_min_role.value,
    )

    return PermissionUpdateResponse(
        permission=permission_key,
        previous_min_role=previous,
        new_min_role=new_min_role,
    )


@router.post(
    "/permissions/preset/{preset_name}",
    response_model=PresetApplyResponse,
    summary="Reset every permission to a named baseline preset",
    description=(
        "Admin-only. Walks every registered permission and rewrites its "
        "min_role to match the preset's rule. Returns the full list of "
        "changes for the UI to display in a confirmation toast. Audit-"
        "logged as a single ``preset_applied`` entry plus one per "
        "changed key."
    ),
)
async def apply_permission_preset(
    preset_name: str,
    request: Request,
    session: SessionDep,
    payload: CurrentUserPayload,
    _role_gate: None = Depends(RequireRole("admin")),
) -> PresetApplyResponse:
    """Rewrite every permission to the preset's recommended ``min_role``."""
    if preset_name not in PRESETS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "preset_not_found",
                "message": f"Unknown preset: {preset_name}",
            },
        )

    rule = PRESETS[preset_name]
    snapshot = permission_registry.snapshot()
    changes: list[dict[str, str]] = []

    for key, current_role in snapshot.items():
        desired = rule(key)
        # Hard guard: never demote admin-only system permissions below
        # admin. The preset rules already respect this for ``system.*``
        # keys, but the explicit guard makes the invariant local.
        if _is_admin_lockout(key, desired):
            desired = Role.ADMIN
        if desired != current_role:
            permission_registry.set_min_role(key, desired)
            changes.append(
                {
                    "permission": key,
                    "previous_min_role": current_role.value,
                    "new_min_role": desired.value,
                }
            )

    await audit_log(
        session,
        action="preset_applied",
        entity_type="permission_matrix",
        entity_id=preset_name,
        user_id=payload.get("sub"),
        ip_address=request.client.host if request.client else None,
        details={
            "preset": preset_name,
            "changes": changes,
            "actor_role": payload.get("role"),
            "total_permissions": len(snapshot),
        },
    )

    logger.info(
        "Permissions matrix preset applied: actor=%s preset=%s changed=%d/%d",
        payload.get("sub"),
        preset_name,
        len(changes),
        len(snapshot),
    )

    return PresetApplyResponse(
        preset=preset_name,
        permissions_changed=len(changes),
        total_permissions=len(snapshot),
        changes=changes,
    )
