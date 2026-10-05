# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The role ladder provisioning applies: raise to manager, never lower, never guess.

The database side (a real admin row stays admin, with no audit row) is in
``tests/pg/trainer/test_provisioning_*``.
"""

from __future__ import annotations

import pytest

from app.core.permissions import ROLE_HIERARCHY, Role
from app.modules.trainer.provisioning import LEARNER_ROLE, learner_role_for


def test_the_learner_role_is_manager() -> None:
    """A self-registered account is a viewer, and a viewer cannot award a bid package."""
    assert LEARNER_ROLE is Role.MANAGER


@pytest.mark.parametrize("role", ["viewer", "editor", "Viewer ", "estimator", "readonly", "guest", "field_worker"])
def test_a_role_below_manager_is_raised(role: str) -> None:
    assert learner_role_for(role) == "manager"


@pytest.mark.parametrize("role", ["manager", "admin", "ADMIN", "owner", "superuser"])
def test_manager_and_above_are_left_alone(role: str) -> None:
    assert learner_role_for(role) is None


@pytest.mark.parametrize("role", ["", None, "custom_auditor", "god"])
def test_a_role_that_cannot_be_ranked_is_left_alone(role: str | None) -> None:
    assert learner_role_for(role) is None


def test_no_raise_ever_lands_below_the_role_it_replaces() -> None:
    for role in Role:
        raised = learner_role_for(role.value)
        if raised is not None:
            assert ROLE_HIERARCHY[Role(raised)] > ROLE_HIERARCHY[role]
