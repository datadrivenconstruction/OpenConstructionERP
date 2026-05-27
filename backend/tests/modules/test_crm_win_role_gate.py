"""CRM win-opportunity role-gate tests (R7 audit).

``crm.win_opportunity`` was originally an ``EDITOR``-level permission.
Round-5 audit tightened it to ``MANAGER+`` because winning a deal:

  * triggers downstream Project creation;
  * locks the won-value into win-rate / forecast aggregates;
  * may compute & commit commission payouts via the finance subscriber.

A single EDITOR rep flipping their own deal to ``won`` to pad commission
is a classic insider-fraud vector — must be a manager+ decision.

The R7 layer also closes two adjacent holes that the original review
missed:

  * **update_opportunity must NOT accept ``status='won'`` via PATCH** —
    that would route the win through the unprivileged ``crm.update``
    permission and skip every won-side-effect (won_at stamp, project
    payload, win_reason catalogue check).
  * **win_reason_code** must be validated against the catalogue
    ``is_win_reason`` flag — accepting a loss reason silently corrupts
    every win-rate-by-reason dashboard segmentation.
"""

from __future__ import annotations

from app.core.permissions import Role, permission_registry
from app.modules.crm.permissions import register_crm_permissions


def _ensure_registered() -> None:
    # The permission registry is process-wide; re-registering is idempotent.
    register_crm_permissions()


def test_crm_win_opportunity_requires_manager_or_higher():
    _ensure_registered()
    assert (
        permission_registry.role_has_permission(
            Role.MANAGER.value,
            "crm.win_opportunity",
        )
        is True
    )
    assert (
        permission_registry.role_has_permission(
            Role.ADMIN.value,
            "crm.win_opportunity",
        )
        is True
    )


def test_crm_win_opportunity_denied_for_editor_and_below():
    _ensure_registered()
    assert (
        permission_registry.role_has_permission(
            Role.EDITOR.value,
            "crm.win_opportunity",
        )
        is False
    )
    assert (
        permission_registry.role_has_permission(
            Role.VIEWER.value,
            "crm.win_opportunity",
        )
        is False
    )


def test_crm_forget_requires_admin():
    """GDPR Art. 17 erasure must be ADMIN-only — distinct from crm.delete
    so the org can ring-fence "forget me" actioning even when MANAGERs
    hold the generic delete permission.
    """
    _ensure_registered()
    assert (
        permission_registry.role_has_permission(
            Role.ADMIN.value,
            "crm.forget",
        )
        is True
    )
    assert (
        permission_registry.role_has_permission(
            Role.MANAGER.value,
            "crm.forget",
        )
        is False
    )
    assert (
        permission_registry.role_has_permission(
            Role.EDITOR.value,
            "crm.forget",
        )
        is False
    )


def test_crm_compute_forecast_requires_manager():
    """Recomputing the forecast overwrites historical snapshots — manager+."""
    _ensure_registered()
    assert (
        permission_registry.role_has_permission(
            Role.MANAGER.value,
            "crm.compute_forecast",
        )
        is True
    )
    assert (
        permission_registry.role_has_permission(
            Role.EDITOR.value,
            "crm.compute_forecast",
        )
        is False
    )


def test_crm_lose_opportunity_kept_editor_level():
    """Losing a deal is recoverable + has no commission impact — editor OK."""
    _ensure_registered()
    assert (
        permission_registry.role_has_permission(
            Role.EDITOR.value,
            "crm.lose_opportunity",
        )
        is True
    )


# ── PATCH-bypass guard ────────────────────────────────────────────────────


def test_update_opportunity_rejects_status_won_via_patch():
    """Setting status='won' through generic PATCH must 400.

    Forces callers through ``/opportunities/{id}/win`` which carries the
    MANAGER+ gate and the side-effect chain (project payload, win_reason
    catalogue check, weighted_value recompute).
    """
    import asyncio
    import uuid
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.modules.crm.schemas import OpportunityUpdate
    from app.modules.crm.service import CrmService

    class _Repo:
        async def get_by_id(self, _id):
            now = datetime.now(UTC)
            return SimpleNamespace(
                id=_id,
                status="open",
                stage_id=uuid.uuid4(),
                estimated_value=100,
                probability_percent=50,
                weighted_value=50,
                won_at=None,
                lost_at=None,
                created_at=now,
                updated_at=now,
            )

        async def update_fields(self, *args, **kwargs):
            return None

    class _Session:
        async def refresh(self, *_args, **_kw):
            return None

    svc = CrmService.__new__(CrmService)
    svc.session = _Session()
    svc.opportunity_repo = _Repo()

    import pytest

    async def _go():
        await svc.update_opportunity(
            uuid.uuid4(),
            OpportunityUpdate(status="won"),
        )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_go())
    assert exc_info.value.status_code == 400
    assert "win" in str(exc_info.value.detail).lower()


def test_update_opportunity_rejects_status_lost_via_patch():
    """Same guard as ``won`` — ``lost`` skips lost_reason_code validation."""
    import asyncio
    import uuid
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from fastapi import HTTPException

    from app.modules.crm.schemas import OpportunityUpdate
    from app.modules.crm.service import CrmService

    class _Repo:
        async def get_by_id(self, _id):
            now = datetime.now(UTC)
            return SimpleNamespace(
                id=_id,
                status="open",
                stage_id=uuid.uuid4(),
                estimated_value=100,
                probability_percent=50,
                weighted_value=50,
                won_at=None,
                lost_at=None,
                created_at=now,
                updated_at=now,
            )

        async def update_fields(self, *args, **kwargs):
            return None

    class _Session:
        async def refresh(self, *_args, **_kw):
            return None

    svc = CrmService.__new__(CrmService)
    svc.session = _Session()
    svc.opportunity_repo = _Repo()

    import pytest

    async def _go():
        await svc.update_opportunity(
            uuid.uuid4(),
            OpportunityUpdate(status="lost"),
        )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_go())
    assert exc_info.value.status_code == 400


# ── Lifecycle FSM lockdown ────────────────────────────────────────────────


def test_won_is_terminal_no_further_transitions():
    """Won and lost opportunities are terminal — no resurrection via update."""
    from app.modules.crm.service import allowed_opportunity_transitions

    assert allowed_opportunity_transitions("won") == set()
    assert allowed_opportunity_transitions("lost") == set()
    assert allowed_opportunity_transitions("abandoned") == set()


def test_open_to_won_is_only_allowed_via_dedicated_endpoint():
    from app.modules.crm.service import allowed_opportunity_transitions

    # The set itself allows the transition (schema-level), but the
    # update_opportunity check above rejects it — forcing the dedicated
    # endpoint where the MANAGER+ gate lives.
    assert "won" in allowed_opportunity_transitions("open")
    assert "lost" in allowed_opportunity_transitions("open")
    assert "abandoned" in allowed_opportunity_transitions("open")


def test_lead_state_machine_has_no_silent_revival():
    """Disqualified / converted leads must not transition back to active."""
    from app.modules.crm.service import allowed_lead_transitions

    assert allowed_lead_transitions("disqualified") == set()
    assert allowed_lead_transitions("converted") == set()
