# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A viewer cannot start an estimate it could never delete again.

``boq.create`` used to be granted to VIEWER while ``boq.delete`` needs EDITOR,
so a viewer could leave BOQs behind that only an admin could clean up. Create
now needs the same rank as delete, and every route that starts a BOQ (new,
from template, duplicate, revision) is gated on it.
"""

from __future__ import annotations

import pytest

from app.core.permissions import Role, permission_registry
from app.modules.boq import router as boq_router
from app.modules.boq.permissions import register_boq_permissions


@pytest.fixture
def boq_registry():
    register_boq_permissions()
    return permission_registry


def test_create_needs_the_same_rank_as_delete(boq_registry) -> None:
    assert boq_registry.get_min_role("boq.create") == Role.EDITOR
    assert boq_registry.get_min_role("boq.create") == boq_registry.get_min_role("boq.delete")


def test_a_viewer_is_refused_create_and_an_editor_passes(boq_registry) -> None:
    assert not boq_registry.role_has_permission(Role.VIEWER, "boq.create")
    assert boq_registry.role_has_permission(Role.EDITOR, "boq.create")
    assert boq_registry.role_has_permission(Role.MANAGER, "boq.create")


def test_a_viewer_still_fills_an_estimate_it_was_invited_to(boq_registry) -> None:
    # Only creation moved; editing rows in a shared BOQ stays open to viewers.
    assert boq_registry.role_has_permission(Role.VIEWER, "boq.update")
    assert boq_registry.role_has_permission(Role.VIEWER, "boq.read")


@pytest.mark.parametrize(
    ("path", "endpoint"),
    [
        ("/boqs/", "create_boq"),
        ("/boqs/from-template/", "create_boq_from_template"),
        ("/boqs/{boq_id}/duplicate/", "duplicate_boq"),
        ("/boqs/{boq_id}/create-revision/", "create_revision"),
    ],
)
def test_every_route_that_starts_a_boq_asks_for_create(path: str, endpoint: str) -> None:
    route = next(r for r in boq_router.router.routes if getattr(r, "path", None) == path and "POST" in r.methods)
    assert route.endpoint.__name__ == endpoint
    gated = [getattr(dep.dependency, "permission", None) for dep in route.dependencies]
    assert "boq.create" in gated
