# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Owner-scoped permissions are only safe next to an owner check.

The module has permissions that map to EDITOR on the assumption that every
route carrying them also calls a ``_verify_owner_via_*`` helper. Without that
helper, EDITOR-level RBAC is an open door: anyone with EDITOR can hit the
endpoint and there is nothing else stopping them. The ownership check IS the
security gate; the low RBAC level just makes sure the project owner can
actually reach it.

This test enforces the pairing at the source level (AST walk) so that a
route that picks up an owner-scoped permission without calling a helper is
caught before it ships. A missing call has no observable behaviour until
somebody actually exploits it.

Originally this covered only ``owner_scoped_delete``. After the R6/R8 dead-
route fix it covers every permission whose safety depends on ownership.
"""

import ast
from pathlib import Path

ROUTER = Path(__file__).resolve().parents[3] / "app" / "modules" / "property_dev" / "router.py"

# Every permission in this set MUST appear alongside a _verify_owner_via_*
# call in every route that uses it. If you add a new owner-scoped permission,
# add it here; the floor assertion will tell you if you forget.
OWNER_SCOPED_PERMISSIONS: set[str] = {
    "property_dev.owner_scoped_delete",
    "property_dev.owner_scoped_reservation_expire",
    "property_dev.owner_scoped_instalment_waive",
    # Permissions lowered to EDITOR because ALL their routes have owner
    # checks. If any route is ever added without a helper, it must either
    # get the helper or be moved to a new MANAGER permission.
    "property_dev.contract_buyer",
    "property_dev.lock_selection",
    "property_dev.handover",
    "property_dev.reservation.cancel",
    "property_dev.spa.send",
    "property_dev.spa.sign",
    "property_dev.spa.cancel",
    "property_dev.payment_schedule.activate",
    "property_dev.payment_schedule.suspend",
    "property_dev.contract_party.update_ownership",
    "property_dev.contract_party.remove",
    "property_dev.lead.delete",
    "property_dev.lead.convert",
    "property_dev.price_matrix.activate",
    "property_dev.price_matrix.bulk_recompute",
    "property_dev.regulator_report.generate",
    "property_dev.escrow.reconcile",
}

OWNER_HELPER_PREFIX = "_verify_owner_via"


def _permission_of(fn: ast.AST) -> str | None:
    """The literal inside ``Depends(RequirePermission("..."))``, if any."""
    for default in list(fn.args.defaults) + list(fn.args.kw_defaults):
        if not (isinstance(default, ast.Call) and isinstance(default.func, ast.Name)):
            continue
        if default.func.id != "Depends":
            continue
        for arg in default.args:
            if (
                isinstance(arg, ast.Call)
                and isinstance(arg.func, ast.Name)
                and arg.func.id == "RequirePermission"
                and arg.args
                and isinstance(arg.args[0], ast.Constant)
            ):
                return arg.args[0].value
    return None


def _calls_an_owner_helper(fn: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id.startswith(OWNER_HELPER_PREFIX)
        for node in ast.walk(fn)
    )


def _owner_scoped_routes() -> list[tuple[int, str, str, bool]]:
    """Return (line, func_name, permission, has_owner_check) for every route
    gated by one of the owner-scoped permissions."""
    tree = ast.parse(ROUTER.read_text(encoding="utf-8"))
    out = []
    for fn in ast.walk(tree):
        if not isinstance(fn, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        perm = _permission_of(fn)
        if perm in OWNER_SCOPED_PERMISSIONS:
            out.append((fn.lineno, fn.name, perm, _calls_an_owner_helper(fn)))
    return sorted(out)


def test_owner_scoped_permissions_always_sit_behind_an_owner_check() -> None:
    routes = _owner_scoped_routes()

    # Floor: at least one route must exist per permission. Without this the
    # test passes triumphantly over a renamed permission.
    found_permissions = {perm for _, _, perm, _ in routes}
    missing = OWNER_SCOPED_PERMISSIONS - found_permissions
    assert not missing, (
        f"{len(missing)} owner-scoped permission(s) have zero routes in router.py: "
        + ", ".join(sorted(missing))
        + ". Either the permission was renamed and the set here was left pointing at the old "
        "name, or the routes were restructured. Fix this set, do not delete the gate."
    )

    # Main invariant: every route carrying an owner-scoped permission must
    # call a _verify_owner_via_* helper.
    unguarded = [(line, name, perm) for line, name, perm, guarded in routes if not guarded]
    assert not unguarded, (
        f"{len(unguarded)} of {len(routes)} owner-scoped routes lack a "
        f"{OWNER_HELPER_PREFIX}* helper: "
        + ", ".join(f"{name} [{perm}] (router.py:{line})" for line, name, perm in unguarded)
        + ". These permissions map to EDITOR and are only safe because ownership is checked "
        "in the handler body. Without the helper any editor can hit the endpoint. "
        "Add the owner check, or move the route to a MANAGER-level permission."
    )
