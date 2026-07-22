# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Unit tests for the approval-route preset library (DB-free).

Validates the pure ``PRESETS`` data - stable keys, valid target kinds / modes /
roles, dense ordinals - and dry-runs every preset through the inc3a simulator to
prove each one is well-formed and actually reaches ``approved`` with no design
warnings. The database-backed seed idempotency is covered by an integration
test.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.modules.approval_routes.models import STEP_MODES, TARGET_KINDS
from app.modules.approval_routes.seed import PRESETS
from app.modules.approval_routes.simulate import simulate_route

# The application roles a preset step may reference (must match the built-in
# role hierarchy so the presets work with no extra configuration).
_KNOWN_ROLES = {"admin", "manager", "editor", "viewer"}


def test_three_presets_with_unique_stable_keys() -> None:
    assert len(PRESETS) == 3
    keys = [p.system_key for p in PRESETS]
    assert len(set(keys)) == 3, f"system_keys must be unique: {keys}"
    assert all(k.startswith("cde_") for k in keys)


def test_presets_are_structurally_valid() -> None:
    for p in PRESETS:
        assert p.name and p.name.strip()
        assert p.target_kind in TARGET_KINDS, f"{p.system_key}: bad target_kind {p.target_kind}"
        assert p.steps, f"{p.system_key}: must have at least one step"
        # dense 1-based ordinals
        ordinals = sorted(s.ordinal for s in p.steps)
        assert ordinals == list(range(1, len(ordinals) + 1)), f"{p.system_key}: ordinals {ordinals}"
        for s in p.steps:
            assert s.mode in STEP_MODES, f"{p.system_key}: bad mode {s.mode}"
            assert s.approver_role in _KNOWN_ROLES, f"{p.system_key}: unknown role {s.approver_role}"
            if s.required_approver_count is not None:
                assert s.required_approver_count >= 1
            if s.sla_hours is not None:
                assert 1 <= s.sla_hours <= 720


def _steps_for_sim(preset: object) -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            ordinal=s.ordinal,
            mode=s.mode,
            approver_role=s.approver_role,
            approver_user_id=None,
            required_approver_count=s.required_approver_count,
        )
        for s in preset.steps  # type: ignore[attr-defined]
    ]


def test_every_preset_reaches_approved_with_no_warnings() -> None:
    for p in PRESETS:
        res = simulate_route(
            route_id=uuid.uuid4(),
            target_kind=p.target_kind,
            steps=_steps_for_sim(p),
            decisions=[],
        )
        assert res.happy_path.outcome == "completed", f"{p.system_key} does not reach approved"
        assert res.scenario is None
        # A well-formed preset should not trip the "needs two approvers" smell:
        # every step either declares a count or uses mode 'any'.
        assert res.warnings == [], f"{p.system_key} raised warnings: {res.warnings}"
        assert res.step_count == len(p.steps)


def test_expected_preset_keys_present() -> None:
    keys = {p.system_key for p in PRESETS}
    assert keys == {
        "cde_issue_for_review",
        "cde_comment_and_return",
        "cde_review_and_publish",
    }


def test_system_preset_is_read_only_guard() -> None:
    from fastapi import HTTPException

    from app.modules.approval_routes.router import _reject_if_system_preset

    # A user route (no system_key) passes untouched.
    _reject_if_system_preset(SimpleNamespace(system_key=None))

    # A seeded preset is rejected with a 409.
    for key in ("cde_issue_for_review", "cde_review_and_publish"):
        raised = False
        try:
            _reject_if_system_preset(SimpleNamespace(system_key=key))
        except HTTPException as exc:
            raised = True
            assert exc.status_code == 409
        assert raised, f"{key} should be rejected as read-only"
