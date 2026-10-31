# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Estimate check router surface and permission gates (structural, no app boot)."""

from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://oe:oe@localhost:5432/openestimate")
os.environ.setdefault("DATABASE_SYNC_URL", "postgresql://oe:oe@localhost:5432/openestimate")

import pytest

from app.modules.estimate_checks.router import router


def _route(path: str, method: str):
    for r in router.routes:
        if getattr(r, "path", None) == path and method in getattr(r, "methods", set()):
            return r
    return None


def _perms(route) -> set[str]:
    perms = {getattr(getattr(d, "dependency", None), "permission", None) for d in route.dependencies}
    return {p for p in perms if p}


@pytest.mark.parametrize(
    ("path", "method", "perm"),
    [
        ("/boq/{boq_id}", "GET", "estimate_checks.read"),
        ("/boq/{boq_id}/accept/{kpi_id}", "PUT", "estimate_checks.accept"),
        ("/boq/{boq_id}/accept/{kpi_id}", "DELETE", "estimate_checks.accept"),
        ("/settings", "GET", "estimate_checks.read"),
        ("/settings", "PUT", "estimate_checks.admin"),
        ("/preference", "GET", "estimate_checks.read"),
        ("/preference", "PUT", "estimate_checks.read"),
    ],
)
def test_route_and_permission(path: str, method: str, perm: str):
    route = _route(path, method)
    assert route is not None, f"{method} {path} is not mounted"
    assert perm in _perms(route)


def test_settings_schema_rejects_bad_values():
    from pydantic import ValidationError

    from app.modules.estimate_checks.schemas import AcceptRequest, PreferenceBody, SettingsBody

    with pytest.raises(ValidationError):
        SettingsBody(min_comparables=1)
    with pytest.raises(ValidationError):
        PreferenceBody(display_mode="loud")
    with pytest.raises(ValidationError):
        AcceptRequest(reason="")
    assert PreferenceBody().display_mode == "badge"


def test_permissions_register():
    from app.core.permissions import permission_registry
    from app.modules.estimate_checks.permissions import register_estimate_check_permissions

    register_estimate_check_permissions()
    assert "estimate_checks.admin" in permission_registry.list_all()
